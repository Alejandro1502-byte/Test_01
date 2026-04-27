"""
Simulador de flota de drones.
Cada TICK_SECONDS actualiza:
  - Posición de drones en vuelo (avanzan hacia destino)
  - Batería (baja por tick mientras vuelan)
  - Estado: si llegan al destino → limpian destino
           si batería < 5% → aterrizaje forzado
           si estado == aterrizando → pasan a en_tierra
"""
import os
import math
import time
import logging
from datetime import datetime

from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SIM] %(message)s')
log = logging.getLogger(__name__)

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://mongo:27017/')
DB_NAME = os.environ.get('DB_NAME', 'dronesdb')
TICK_SECONDS = float(os.environ.get('TICK_SECONDS', '2'))
BATTERY_DRAIN_PER_TICK = float(os.environ.get('BATTERY_DRAIN', '0.5'))  # % por tick en vuelo
LANDING_DRAIN = float(os.environ.get('LANDING_DRAIN', '0.2'))           # % por tick aterrizando
ARRIVAL_THRESHOLD = float(os.environ.get('ARRIVAL_THRESHOLD', '0.5'))   # unidades


def connect():
    for attempt in range(20):
        try:
            c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            c.admin.command('ping')
            log.info("Conectado a MongoDB ✓")
            return c
        except Exception as e:
            log.warning(f"Intento {attempt+1}/20 fallido: {e}")
            time.sleep(3)
    raise RuntimeError("No se pudo conectar a MongoDB")


def log_event(events_col, drone_id, tipo, detalle=None):
    events_col.insert_one({
        'drone_id': str(drone_id),
        'tipo': tipo,
        'detalle': detalle,
        'ts': datetime.utcnow(),
    })


def distance(a, b):
    return math.sqrt((b['x'] - a['x']) ** 2 + (b['y'] - a['y']) ** 2)


def move_towards(pos, dest, speed):
    """Devuelve nueva posición movida `speed` unidades hacia dest."""
    dx = dest['x'] - pos['x']
    dy = dest['y'] - pos['y']
    dist = math.sqrt(dx * dx + dy * dy)
    if dist <= speed:
        return dest.copy(), True  # llegó
    factor = speed / dist
    return {'x': pos['x'] + dx * factor, 'y': pos['y'] + dy * factor}, False


def tick(drones_col, events_col):
    updates = 0
    for drone in drones_col.find():
        did = drone['_id']
        estado = drone.get('estado', 'en_tierra')
        pos = drone.get('posicion', {'x': 0.0, 'y': 0.0})
        dest = drone.get('destino')
        bat = drone.get('bateria_pct', 100.0)
        speed = drone.get('velocidad', 1.0)

        update = {}

        # ── Batería crítica → aterrizaje forzado ──────────────────────────────
        if estado == 'volando' and bat <= 5.0:
            update['estado'] = 'aterrizando'
            update['destino'] = None
            log.info(f"[{did}] Batería crítica ({bat:.1f}%) → aterrizando forzado")
            log_event(events_col, did, 'bateria_critica', f'Batería al {bat:.1f}%, aterrizaje forzado')

        # ── Procesando aterrizaje ──────────────────────────────────────────────
        elif estado == 'aterrizando':
            bat = max(0.0, bat - LANDING_DRAIN)
            update['bateria_pct'] = bat
            update['estado'] = 'en_tierra'
            log.info(f"[{did}] Aterrizó. Batería: {bat:.1f}%")
            log_event(events_col, did, 'aterrizaje', f'Aterrizó con batería al {bat:.1f}%')

        # ── Volando ───────────────────────────────────────────────────────────
        elif estado == 'volando':
            bat = max(0.0, bat - BATTERY_DRAIN_PER_TICK)
            update['bateria_pct'] = bat

            if dest:
                new_pos, arrived = move_towards(pos, dest, speed)
                update['posicion'] = new_pos
                if arrived:
                    update['destino'] = None
                    log.info(f"[{did}] Llegó al destino ({dest['x']:.1f}, {dest['y']:.1f})")
                    log_event(events_col, did, 'destino_alcanzado',
                              f"Llegó a ({dest['x']:.1f}, {dest['y']:.1f})")

        if update:
            drones_col.update_one({'_id': did}, {'$set': update})
            updates += 1

    return updates


def main():
    mongo_client = connect()
    db = mongo_client[DB_NAME]
    drones_col = db['drones']
    events_col = db['events']

    log.info(f"Simulador arrancado. Tick cada {TICK_SECONDS}s")
    while True:
        try:
            n = tick(drones_col, events_col)
            if n:
                log.info(f"Tick procesado — {n} drones actualizados")
        except Exception as e:
            log.error(f"Error en tick: {e}")
        time.sleep(TICK_SECONDS)


if __name__ == '__main__':
    main()
