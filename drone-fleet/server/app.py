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


# ── DRONES CRUD ────────────────────────────────────────────────────────────────

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
    data = request.get_json() or {}
    required = ['modelo', 'fabricante']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Faltan: {", ".join(missing)}'}), 400

    # Posición: acepta lat/lon (geo) o x/y (grid)
    if data.get('lat') is not None:
        pos  = {'lat': float(data['lat']), 'lon': float(data.get('lon', 0))}
        home = pos.copy()   # punto de referencia para NED ↔ lat/lon
    else:
        pos  = {'x': float(data.get('x', 50)), 'y': float(data.get('y', 50))}
        home = None

    # Support both lat/lon (geo) and x/y (grid)
    if data.get('lat') is not None:
        pos = {'lat': float(data['lat']), 'lon': float(data.get('lon', 0))}
    else:
        pos = {'x': float(data.get('x', 50)), 'y': float(data.get('y', 50))}

    drone = {
        'modelo':     data['modelo'],
        'fabricante': data['fabricante'],
        'estado': 'en_tierra',
        'posicion': {'x': data.get('x', 0.0), 'y': data.get('y', 0.0)},
        'destino': None,
        'bateria_pct': 100.0,
        'velocidad': data.get('velocidad', 1.0),
        'created_at': datetime.utcnow(),
    }
    result = drones_col.insert_one(drone)
    drone['_id'] = result.inserted_id
    log_event(result.inserted_id, 'creado', f"Dron {drone['modelo']} creado")
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


# ── ÓRDENES ────────────────────────────────────────────────────────────────────

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
        if drone['estado'] not in ('en_tierra',):
            return jsonify({'error': 'El dron no está en tierra'}), 409
        if drone['bateria_pct'] < 10:
            return jsonify({'error': 'Batería insuficiente'}), 409
        update = {'estado': 'volando'}
        msg = 'Despegue ordenado'

    elif accion == 'aterrizar':
        if drone['estado'] not in ('volando',):
            return jsonify({'error': 'El dron no está volando'}), 409
        update = {'estado': 'aterrizando', 'destino': None}
        msg = 'Aterrizaje ordenado'

    elif accion == 'ir_a':
        x = data.get('x')
        y = data.get('y')
        if x is None or y is None:
            return jsonify({'error': 'Faltan coordenadas x e y'}), 400
        if drone['estado'] not in ('volando',):
            return jsonify({'error': 'El dron debe estar volando para recibir destino'}), 409
        update = {'destino': {'x': float(x), 'y': float(y)}}
        msg = f'Destino establecido: ({x}, {y})'

    elif accion == 'recargar':
        if drone['estado'] != 'en_tierra':
            return jsonify({'error': 'Solo se puede recargar en tierra'}), 409
        update = {'bateria_pct': 100.0, 'estado': 'en_tierra'}
        msg = 'Batería recargada al 100%'

    elif accion == 'mantenimiento':
        update = {'estado': 'mantenimiento', 'destino': None}
        msg = 'Dron en mantenimiento'

    elif accion == 'activar':
        if drone['estado'] != 'mantenimiento':
            return jsonify({'error': 'El dron no está en mantenimiento'}), 409
        update = {'estado': 'en_tierra'}
        msg = 'Dron activado'

    else:
        return jsonify({'error': f'Acción desconocida: {accion}'}), 400

    drones_col.update_one({'_id': oid}, {'$set': update})
    log_event(oid, accion, msg)
    drone = drones_col.find_one({'_id': oid})
    return jsonify({'ok': True, 'mensaje': msg, 'drone': serialize(drone)})


# ── EVENTOS ────────────────────────────────────────────────────────────────────

@app.route('/api/eventos')
def list_events():
    drone_id = request.args.get('drone_id')
    query = {}
    if drone_id:
        query['drone_id'] = drone_id
    events = list(events_col.find(query).sort('ts', -1).limit(50))
    for e in events:
        e['id'] = str(e['_id'])
        del e['_id']
        e['ts'] = e['ts'].isoformat()
    return jsonify(evs)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)