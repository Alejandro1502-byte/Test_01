import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://mongo:27017/')
DB_NAME   = os.environ.get('DB_NAME',   'dronesdb')

app = Flask(__name__)
CORS(app)

client     = MongoClient(MONGO_URI)
db         = client[DB_NAME]
drones_col = db['drones']
events_col = db['events']


def serialize(drone):
    drone['id'] = str(drone['_id'])
    del drone['_id']
    return drone


def log_event(drone_id, tipo, detalle=None):
    events_col.insert_one({
        'drone_id': str(drone_id),
        'tipo':     tipo,
        'detalle':  detalle,
        'ts':       datetime.utcnow()
    })


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


# ── DRONES ────────────────────────────────────────────────────────────────────

@app.route('/api/drones')
def list_drones():
    return jsonify([serialize(d) for d in drones_col.find()])


@app.route('/api/drones/<did>')
def get_drone(did):
    try:
        d = drones_col.find_one({'_id': ObjectId(did)})
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400
    if not d:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify(serialize(d))


@app.route('/api/drones', methods=['POST'])
def create_drone():
    data    = request.get_json() or {}
    missing = [f for f in ['modelo', 'fabricante'] if not data.get(f)]
    if missing:
        return jsonify({'error': f'Faltan: {", ".join(missing)}'}), 400

    # Posición: acepta lat/lon (geo) o x/y (grid)
    if data.get('lat') is not None:
        pos  = {'lat': float(data['lat']), 'lon': float(data.get('lon', 0))}
        home = pos.copy()   # punto de referencia para NED ↔ lat/lon
    else:
        pos  = {'x': float(data.get('x', 50)), 'y': float(data.get('y', 50))}
        home = None

    drone = {
        'modelo':     data['modelo'],
        'fabricante': data['fabricante'],
        'estado':     'en_tierra',
        'posicion':   pos,
        'home':       home,      # referencia NED para SITL
        'destino':    None,
        'bateria_pct': 100.0,
        'velocidad':  float(data.get('velocidad', 12)),
        'vel_m_s':    0.0,       # velocidad real de ArduCopter (m/s)
        'altitud':    0.0,       # AGL en metros
        'actitud':    {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0},
        'mision':     data.get('mision'),
        'created_at': datetime.utcnow(),
    }
    result = drones_col.insert_one(drone)
    drone['_id'] = result.inserted_id
    log_event(result.inserted_id, 'creado',
              f"UAV {drone['modelo']} registrado")
    return jsonify(serialize(drone)), 201


@app.route('/api/drones/<did>', methods=['DELETE'])
def delete_drone(did):
    try:
        r = drones_col.delete_one({'_id': ObjectId(did)})
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400
    if r.deleted_count == 0:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify({'deleted': did})


# ── ÓRDENES ───────────────────────────────────────────────────────────────────

@app.route('/api/drones/<did>/orden', methods=['POST'])
def orden(did):
    try:
        oid = ObjectId(did)
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400

    drone  = drones_col.find_one({'_id': oid})
    if not drone:
        return jsonify({'error': 'No encontrado'}), 404

    data   = request.get_json() or {}
    accion = data.get('accion')
    update = {}

    if accion == 'despegar':
        if drone['estado'] != 'en_tierra':
            return jsonify({'error': 'No está en tierra'}), 409
        if drone['bateria_pct'] < 10:
            return jsonify({'error': 'Batería insuficiente'}), 409
        update = {'estado': 'volando'}
        msg    = 'Despegue ejecutado'

    elif accion == 'aterrizar':
        if drone['estado'] != 'volando':
            return jsonify({'error': 'No está volando'}), 409
        update = {'estado': 'aterrizando', 'destino': None}
        msg    = 'Aterrizaje iniciado'

    elif accion == 'ir_a':
        if drone['estado'] != 'volando':
            return jsonify({'error': 'Debe estar volando'}), 409
        if data.get('lat') is not None:
            dest = {'lat': float(data['lat']), 'lon': float(data['lon'])}
            if data.get('alt'):
                dest['alt'] = float(data['alt'])
        elif data.get('x') is not None:
            dest = {'x': float(data['x']), 'y': float(data['y'])}
        else:
            return jsonify({'error': 'Faltan coordenadas'}), 400
        update = {'destino': dest}
        msg    = 'Destino asignado'

    elif accion == 'recargar':
        if drone['estado'] != 'en_tierra':
            return jsonify({'error': 'Solo en tierra'}), 409
        update = {'bateria_pct': 100.0}
        msg    = 'Batería recargada'

    elif accion == 'mantenimiento':
        update = {'estado': 'mantenimiento', 'destino': None}
        msg    = 'En mantenimiento'

    elif accion == 'activar':
        if drone['estado'] != 'mantenimiento':
            return jsonify({'error': 'No está en mantenimiento'}), 409
        update = {'estado': 'en_tierra'}
        msg    = 'UAV activado'

    else:
        return jsonify({'error': f'Acción desconocida: {accion}'}), 400

    drones_col.update_one({'_id': oid}, {'$set': update})
    log_event(oid, accion, msg)
    updated = serialize(drones_col.find_one({'_id': oid}))
    return jsonify({'ok': True, 'mensaje': msg, 'drone': updated})


# ── TELEMETRÍA (solo lectura) ─────────────────────────────────────────────────

@app.route('/api/drones/<did>/telemetria')
def telemetria(did):
    """Devuelve los campos de telemetría en tiempo real del dron."""
    try:
        d = drones_col.find_one({'_id': ObjectId(did)},
                                {'actitud':1, 'vel_m_s':1, 'altitud':1,
                                 'bateria_pct':1, 'velocidad':1, 'posicion':1})
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400
    if not d:
        return jsonify({'error': 'No encontrado'}), 404
    d['id'] = str(d['_id']); del d['_id']
    return jsonify(d)


# ── EVENTOS ───────────────────────────────────────────────────────────────────

@app.route('/api/eventos')
def list_events():
    drone_id = request.args.get('drone_id')
    query    = {'drone_id': drone_id} if drone_id else {}
    evs      = list(events_col.find(query).sort('ts', -1).limit(60))
    for e in evs:
        e['id'] = str(e['_id']); del e['_id']
        e['ts'] = e['ts'].isoformat()
    return jsonify(evs)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)