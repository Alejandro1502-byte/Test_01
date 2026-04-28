"""
Simulador de flota — soporta coordenadas lat/lon (geo) y x/y (grid).
Tick configurable. Actualiza posición, batería y estado.
"""
import os, math, time, logging
from datetime import datetime
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SIM] %(message)s')
log = logging.getLogger(__name__)

MONGO_URI   = os.environ.get('MONGO_URI', 'mongodb://mongo:27017/')
DB_NAME     = os.environ.get('DB_NAME', 'dronesdb')
TICK        = float(os.environ.get('TICK_SECONDS', '2'))
BAT_DRAIN   = float(os.environ.get('BATTERY_DRAIN', '0.5'))
LAND_DRAIN  = float(os.environ.get('LANDING_DRAIN', '0.2'))
ARRIVE_THR  = float(os.environ.get('ARRIVAL_THRESHOLD', '0.00005'))  # degrees ~5m


def connect():
    for i in range(20):
        try:
            c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            c.admin.command('ping')
            log.info("MongoDB conectado ✓")
            return c
        except Exception as e:
            log.warning(f"Intento {i+1}/20: {e}")
            time.sleep(3)
    raise RuntimeError("Sin conexión a MongoDB")


def log_event(col, drone_id, tipo, detalle=None):
    col.insert_one({'drone_id': str(drone_id), 'tipo': tipo, 'detalle': detalle, 'ts': datetime.utcnow()})


def dist_geo(a, b):
    return math.sqrt((b['lat']-a['lat'])**2 + (b['lon']-a['lon'])**2)

def dist_xy(a, b):
    return math.sqrt((b['x']-a['x'])**2 + (b['y']-a['y'])**2)

def move_geo(pos, dest, speed_deg):
    dx = dest['lat'] - pos['lat']
    dy = dest['lon'] - pos['lon']
    d  = math.sqrt(dx*dx + dy*dy)
    if d <= speed_deg:
        return dest.copy(), True
    f = speed_deg / d
    return {'lat': pos['lat']+dx*f, 'lon': pos['lon']+dy*f}, False

def move_xy(pos, dest, speed):
    dx = dest['x'] - pos['x']
    dy = dest['y'] - pos['y']
    d  = math.sqrt(dx*dx + dy*dy)
    if d <= speed:
        return dest.copy(), True
    f = speed / d
    return {'x': pos['x']+dx*f, 'y': pos['y']+dy*f}, False


def tick(drones_col, events_col):
    updated = 0
    for d in drones_col.find():
        did    = d['_id']
        estado = d.get('estado', 'en_tierra')
        pos    = d.get('posicion', {})
        dest   = d.get('destino')
        bat    = d.get('bateria_pct', 100.0)
        speed  = d.get('velocidad', 12)
        update = {}

        is_geo = 'lat' in pos

        # Speed in appropriate units
        if is_geo:
            speed_u = speed * 0.000009  # ~1 m/s ≈ 9e-6 degrees
        else:
            speed_u = speed * 0.1

        if estado == 'volando' and bat <= 5.0:
            update = {'estado': 'aterrizando', 'destino': None}
            log_event(events_col, did, 'bateria_critica', f'Batería {bat:.1f}% → aterrizaje forzado')

        elif estado == 'aterrizando':
            bat = max(0.0, bat - LAND_DRAIN)
            update = {'bateria_pct': bat, 'estado': 'en_tierra'}
            log_event(events_col, did, 'aterrizaje', f'Aterrizó. Batería: {bat:.1f}%')

        elif estado == 'volando':
            bat = max(0.0, bat - BAT_DRAIN)
            update['bateria_pct'] = bat

            if dest:
                if is_geo and 'lat' in dest:
                    new_pos, arrived = move_geo(pos, dest, speed_u)
                    thr = ARRIVE_THR
                elif not is_geo and 'x' in dest:
                    new_pos, arrived = move_xy(pos, dest, speed_u)
                    thr = 0.5
                else:
                    arrived = False; new_pos = pos

                update['posicion'] = new_pos
                if arrived:
                    update['destino'] = None
                    log_event(events_col, did, 'destino_alcanzado', 'Llegó al destino')

        if update:
            drones_col.update_one({'_id': did}, {'$set': update})
            updated += 1

    return updated


def main():
    c  = connect()
    db = c[DB_NAME]
    log.info(f"Simulador activo — tick cada {TICK}s")
    while True:
        try:
            n = tick(db['drones'], db['events'])
            if n: log.info(f"Tick — {n} UAVs actualizados")
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(TICK)

if __name__ == '__main__':
    main()