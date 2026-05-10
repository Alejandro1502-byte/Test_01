"""
sitl_bridge.py
==============
Puente entre MongoDB (estado de la flota) y ArduCopter SITL via pymavlink.

Arquitectura:
  - Un hilo por dron: lee estado de Mongo, envía comandos MAVLink al SITL,
    recibe telemetría y escribe de vuelta a Mongo.
  - Si no hay SITL disponible en el puerto, cae a simulación propia (fallback).
  - El SITL debe correr externamente (ver README) o en otro contenedor.

Variables de entorno:
  MONGO_URI        mongodb://admin:admin123@mongo:27017/
  DB_NAME          dronesdb
  SITL_HOST        host donde corren los procesos SITL (default: host.docker.internal)
  SITL_BASE_PORT   puerto UDP base del primer dron (default: 14550)
  TICK_SECONDS     segundos entre ticks (default: 0.25)
  USE_SITL         true/false — si false usa simulación propia (default: false)
  BATTERY_DRAIN    % batería por segundo en vuelo (default: 0.05)
"""

import os, time, math, logging, threading
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BRIDGE %(threadName)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
MONGO_URI       = os.environ.get("MONGO_URI",       "mongodb://mongo:27017/")
DB_NAME         = os.environ.get("DB_NAME",         "dronesdb")
SITL_HOST       = os.environ.get("SITL_HOST",       "host.docker.internal")
SITL_BASE_PORT  = int(os.environ.get("SITL_BASE_PORT", "14550"))
TICK            = float(os.environ.get("TICK_SECONDS",  "0.25"))
USE_SITL        = os.environ.get("USE_SITL", "false").lower() == "true"
BAT_DRAIN       = float(os.environ.get("BATTERY_DRAIN", "0.05"))  # %/s en vuelo

# ── Modelo físico de fallback (cuando no hay SITL) ────────────────────────────
# Basado en cinemática simple pero con parámetros diferenciados por misión
MISSION_PARAMS = {
    "imagen":     {"vel": 10.0, "alt": 150.0, "bat_drain": 0.04, "accel": 2.0},
    "ataque":     {"vel": 35.0, "alt":  80.0, "bat_drain": 0.10, "accel": 8.0},
    "vigilancia": {"vel":  8.0, "alt": 200.0, "bat_drain": 0.05, "accel": 1.5},
    "default":    {"vel": 12.0, "alt": 120.0, "bat_drain": 0.05, "accel": 3.0},
}
# Conversión grados → metros (aprox Madrid lat 40°)
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(40.4))
ARRIVE_M       = 3.0   # metros para considerar "llegado"

# ── MongoDB ───────────────────────────────────────────────────────────────────
def mongo_connect():
    for i in range(20):
        try:
            c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            c.admin.command("ping")
            log.info("MongoDB conectado ✓")
            return c
        except Exception as e:
            log.warning(f"Mongo intento {i+1}/20: {e}")
            time.sleep(3)
    raise RuntimeError("No se puede conectar a MongoDB")

def log_event(col, drone_id, tipo, detalle=None):
    col.insert_one({
        "drone_id": str(drone_id),
        "tipo":     tipo,
        "detalle":  detalle,
        "ts":       datetime.utcnow(),
    })

# ── Conversión lat/lon ↔ metros ───────────────────────────────────────────────
def latlon_to_m(origin, pos):
    """Devuelve (dx_m, dy_m) desde origin hasta pos."""
    dlat = pos["lat"] - origin["lat"]
    dlon = pos["lon"] - origin["lon"]
    return dlat * M_PER_DEG_LAT, dlon * M_PER_DEG_LON

def m_to_latlon(origin, dx, dy):
    return {
        "lat": origin["lat"] + dx / M_PER_DEG_LAT,
        "lon": origin["lon"] + dy / M_PER_DEG_LON,
    }

def dist_m(pos, dest):
    dx = (dest["lat"] - pos["lat"]) * M_PER_DEG_LAT
    dy = (dest["lon"] - pos["lon"]) * M_PER_DEG_LON
    return math.sqrt(dx*dx + dy*dy)

# ═══════════════════════════════════════════════════════════════════════════════
# SITL WORKER — un hilo por dron, usa pymavlink
# ═══════════════════════════════════════════════════════════════════════════════
class SITLWorker(threading.Thread):
    """
    Conecta a un proceso ArduCopter SITL via MAVLink UDP.
    - Arma el dron
    - Escucha telemetría (LOCAL_POSITION_NED, ATTITUDE, BATTERY_STATUS)
    - Traduce órdenes de Mongo (estado → comandos MAVLink)
    - Escribe telemetría de vuelta a Mongo
    """

    def __init__(self, drone_doc, port, drones_col, events_col):
        super().__init__(name=f"SITL-{drone_doc['_id']}", daemon=True)
        self.drone_id   = drone_doc["_id"]
        self.port       = port
        self.drones_col = drones_col
        self.events_col = events_col
        self._stop      = threading.Event()

    def run(self):
        try:
            from pymavlink import mavutil
        except ImportError:
            log.error("pymavlink no instalado")
            return

        conn_str = f"udpin:{SITL_HOST}:{self.port}"
        log.info(f"Conectando a SITL en {conn_str}")
        try:
            mav = mavutil.mavlink_connection(conn_str, baud=57600)
            mav.wait_heartbeat(timeout=10)
            log.info(f"SITL heartbeat recibido en puerto {self.port} ✓")
        except Exception as e:
            log.warning(f"SITL no disponible ({e}), usando fallback")
            FallbackWorker(self.drone_id, self.drones_col, self.events_col).run_loop(self._stop)
            return

        # Solicitar streams de telemetría
        mav.mav.request_data_stream_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1  # 4 Hz
        )

        # Armar
        mav.arducopter_arm()
        log.info(f"Dron {self.drone_id} armado")

        last_estado = None

        while not self._stop.is_set():
            # ── Leer telemetría MAVLink ──
            msg = mav.recv_match(
                type=["LOCAL_POSITION_NED","ATTITUDE","BATTERY_STATUS","VFR_HUD"],
                blocking=True, timeout=1.0
            )
            if msg is None:
                continue

            update = {}
            mt = msg.get_type()

            if mt == "LOCAL_POSITION_NED":
                # Convertir NED → lat/lon relativo al home
                drone = self.drones_col.find_one({"_id": self.drone_id})
                if drone and drone.get("home"):
                    home = drone["home"]
                    new_pos = m_to_latlon(home, msg.x, msg.y)
                    new_pos["alt"] = -msg.z  # NED z negativo = arriba
                    update["posicion"] = new_pos
                    update["vel_m_s"]  = round(math.sqrt(msg.vx**2 + msg.vy**2), 2)
                    update["altitud"]  = round(-msg.z, 1)

            elif mt == "ATTITUDE":
                update["actitud"] = {
                    "roll":  round(math.degrees(msg.roll),  1),
                    "pitch": round(math.degrees(msg.pitch), 1),
                    "yaw":   round(math.degrees(msg.yaw),   1),
                }

            elif mt == "BATTERY_STATUS":
                if msg.battery_remaining >= 0:
                    update["bateria_pct"] = float(msg.battery_remaining)

            elif mt == "VFR_HUD":
                update["velocidad"] = round(msg.groundspeed, 1)
                update["altitud"]   = round(msg.alt, 1)

            if update:
                self.drones_col.update_one(
                    {"_id": self.drone_id}, {"$set": update}
                )

            # ── Leer estado de Mongo y traducir a comandos MAVLink ──
            drone = self.drones_col.find_one({"_id": self.drone_id})
            if not drone:
                break

            estado = drone.get("estado")
            if estado != last_estado:
                self._handle_estado_change(mav, estado, drone)
                last_estado = estado

            # Si tiene destino y está volando, enviar waypoint
            if estado == "volando" and drone.get("destino"):
                dest = drone["destino"]
                self._send_position_target(mav, dest)

            time.sleep(TICK)

    def _handle_estado_change(self, mav, estado, drone):
        from pymavlink import mavutil
        if estado == "volando":
            alt = drone.get("altitud", 50)
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0, 0, 0, 0, 0, 0, 0, alt
            )
            log.info(f"Dron {self.drone_id} → TAKEOFF alt={alt}m")

        elif estado == "aterrizando":
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_NAV_LAND,
                0, 0, 0, 0, 0, 0, 0, 0
            )
            log.info(f"Dron {self.drone_id} → LAND")

    def _send_position_target(self, mav, dest):
        from pymavlink import mavutil
        lat  = int(dest["lat"] * 1e7)
        lon  = int(dest["lon"] * 1e7)
        alt  = dest.get("alt", 50.0)
        # MAV_FRAME_GLOBAL_RELATIVE_ALT = 6
        mav.mav.set_position_target_global_int_send(
            0,  # time_boot_ms
            mav.target_system, mav.target_component,
            6,       # frame: GLOBAL_RELATIVE_ALT
            0b0000111111111000,  # type_mask: solo posición
            lat, lon, alt,
            0,0,0,   # velocidades (ignoradas)
            0,0,0,   # aceleraciones (ignoradas)
            0, 0     # yaw, yaw_rate
        )

    def stop(self):
        self._stop.set()


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK WORKER — simulación propia cuando no hay SITL
# Usa cinemática real diferenciada por tipo de misión
# ═══════════════════════════════════════════════════════════════════════════════
class FallbackWorker:
    def __init__(self, drone_id, drones_col, events_col):
        self.drone_id   = drone_id
        self.drones_col = drones_col
        self.events_col = events_col

    def run_loop(self, stop_event):
        log.info(f"Fallback activo para dron {self.drone_id}")
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log.error(f"Error en fallback tick {self.drone_id}: {e}")
            time.sleep(TICK)

    def _tick(self):
        drone = self.drones_col.find_one({"_id": self.drone_id})
        if not drone:
            return

        estado  = drone.get("estado", "en_tierra")
        pos     = drone.get("posicion", {})
        dest    = drone.get("destino")
        bat     = drone.get("bateria_pct", 100.0)
        mision  = drone.get("mision", "default")
        params  = MISSION_PARAMS.get(mision, MISSION_PARAMS["default"])
        vel_max = params["vel"]          # m/s
        bat_drain = params["bat_drain"]  # %/s

        update  = {}

        # ── batería crítica ──────────────────────────────────
        if estado == "volando" and bat <= 5.0:
            update["estado"]  = "aterrizando"
            update["destino"] = None
            log_event(self.events_col, self.drone_id,
                      "bateria_critica", f"Batería {bat:.1f}% → aterrizaje forzado")

        # ── aterrizando ──────────────────────────────────────
        elif estado == "aterrizando":
            bat = max(0.0, bat - bat_drain * TICK * 0.4)
            update["bateria_pct"] = round(bat, 2)
            update["estado"]      = "en_tierra"
            update["altitud"]     = 0.0
            log_event(self.events_col, self.drone_id,
                      "aterrizaje", f"Aterrizó. Batería: {bat:.1f}%")

        # ── volando ──────────────────────────────────────────
        elif estado == "volando":
            # drenar batería
            bat = max(0.0, bat - bat_drain * TICK)
            update["bateria_pct"] = round(bat, 2)

            # altitud objetivo
            alt_target = params["alt"]
            alt_actual = drone.get("altitud", 0.0)
            alt_actual += min(params["accel"] * TICK,
                              alt_target - alt_actual) if alt_actual < alt_target else 0
            update["altitud"] = round(max(0, alt_actual), 1)

            # actitud simulada (pequeñas oscilaciones realistas)
            t = time.time()
            update["actitud"] = {
                "roll":  round(math.sin(t * 0.7) * 3.5, 1),
                "pitch": round(math.cos(t * 0.5) * 2.8, 1),
                "yaw":   round(drone.get("actitud", {}).get("yaw", 0), 1),
            }

            if dest and "lat" in pos and "lat" in dest:
                d_m = dist_m(pos, dest)

                if d_m <= ARRIVE_M:
                    # llegó
                    update["posicion"] = dest.copy()
                    update["destino"]  = None
                    update["velocidad"] = 0.0
                    log_event(self.events_col, self.drone_id,
                              "destino_alcanzado",
                              f"Llegó al destino (d={d_m:.1f}m)")
                else:
                    # avanzar hacia destino
                    step_m = min(vel_max * TICK, d_m)
                    ratio  = step_m / d_m
                    dx = (dest["lat"] - pos["lat"]) * ratio
                    dy = (dest["lon"] - pos["lon"]) * ratio
                    new_pos = {
                        "lat": round(pos["lat"] + dx, 6),
                        "lon": round(pos["lon"] + dy, 6),
                    }
                    update["posicion"]  = new_pos
                    update["velocidad"] = round(vel_max * min(1.0, d_m / 30.0), 1)

                    # simular velocidad en m/s con variación natural
                    noise = math.sin(t * 2.3) * 0.8
                    update["vel_m_s"] = round(
                        max(0, vel_max * min(1, d_m/30) + noise), 1
                    )

        if update:
            self.drones_col.update_one(
                {"_id": self.drone_id}, {"$set": update}
            )


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — detecta drones nuevos y arranca workers
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    client     = mongo_connect()
    db         = client[DB_NAME]
    drones_col = db["drones"]
    events_col = db["events"]

    workers    = {}   # drone_id → worker thread
    port_map   = {}   # drone_id → puerto UDP SITL

    log.info(f"Bridge arrancado — USE_SITL={USE_SITL}, TICK={TICK}s")

    while True:
        # Detectar drones en BD
        current_ids = set()
        for drone in drones_col.find():
            did = drone["_id"]
            current_ids.add(did)

            if did not in workers:
                if USE_SITL:
                    # Asignar puerto SITL
                    port = SITL_BASE_PORT + len(port_map)
                    port_map[did] = port
                    w = SITLWorker(drone, port, drones_col, events_col)
                    w.start()
                    workers[did] = w
                    log.info(f"SITLWorker arrancado para {did} en puerto {port}")
                else:
                    # Usar fallback
                    stop_ev = threading.Event()
                    fb = FallbackWorker(did, drones_col, events_col)

                    def run_fb(fb=fb, ev=stop_ev):
                        fb.run_loop(ev)

                    t = threading.Thread(target=run_fb,
                                         name=f"FB-{did}", daemon=True)
                    t._stop_ev = stop_ev
                    t.start()
                    workers[did] = t
                    log.info(f"FallbackWorker arrancado para {did}")

        # Limpiar workers de drones eliminados
        stale = set(workers.keys()) - current_ids
        for did in stale:
            w = workers.pop(did)
            if hasattr(w, "stop"):
                w.stop()
            elif hasattr(w, "_stop_ev"):
                w._stop_ev.set()
            log.info(f"Worker eliminado para {did}")

        time.sleep(2.0)   # re-escanear cada 2s


if __name__ == "__main__":
    main()