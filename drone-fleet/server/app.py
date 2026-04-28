import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://mongo:27017/')
DB_NAME = os.environ.get('DB_NAME', 'dronesdb')

app = Flask(__name__)
CORS(app)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
drones_col = db['drones']
events_col = db['events']


def serialize(drone):
    drone['id'] = str(drone['_id'])
    del drone['_id']
    return drone


def log_event(drone_id, tipo, detalle=None):
    events_col.insert_one({
        'drone_id': str(drone_id),
        'tipo': tipo,
        'detalle': detalle,
        'ts': datetime.utcnow()
    })


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/drones', methods=['GET'])
def list_drones():
    return jsonify([serialize(d) for d in drones_col.find()])


@app.route('/api/drones/<drone_id>', methods=['GET'])
def get_drone(drone_id):
    try:
        drone = drones_col.find_one({'_id': ObjectId(drone_id)})
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400
    if not drone:
        return jsonify({'error': 'Dron no encontrado'}), 404
    return jsonify(serialize(drone))


@app.route('/api/drones', methods=['POST'])
def create_drone():
    data = request.get_json() or {}
    missing = [f for f in ['modelo', 'fabricante'] if not data.get(f)]
    if missing:
        return jsonify({'error': f'Faltan campos: {", ".join(missing)}'}), 400

    # Support both lat/lon (geo) and x/y (grid)
    if data.get('lat') is not None:
        pos = {'lat': float(data['lat']), 'lon': float(data.get('lon', 0))}
    else:
        pos = {'x': float(data.get('x', 50)), 'y': float(data.get('y', 50))}

    drone = {
        'modelo':     data['modelo'],
        'fabricante': data['fabricante'],
        'estado':     'en_tierra',
        'posicion':   pos,
        'destino':    None,
        'bateria_pct': 100.0,
        'velocidad':  float(data.get('velocidad', 12)),
        'altitud':    float(data.get('altitud', 120)),
        'created_at': datetime.utcnow(),
    }
    result = drones_col.insert_one(drone)
    drone['_id'] = result.inserted_id
    log_event(result.inserted_id, 'creado', f"UAV {drone['modelo']} registrado")
    return jsonify(serialize(drone)), 201


@app.route('/api/drones/<drone_id>', methods=['DELETE'])
def delete_drone(drone_id):
    try:
        result = drones_col.delete_one({'_id': ObjectId(drone_id)})
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400
    if result.deleted_count == 0:
        return jsonify({'error': 'Dron no encontrado'}), 404
    return jsonify({'deleted': drone_id})


@app.route('/api/drones/<drone_id>/orden', methods=['POST'])
def orden(drone_id):
    try:
        oid = ObjectId(drone_id)
    except InvalidId:
        return jsonify({'error': 'ID no válido'}), 400

    drone = drones_col.find_one({'_id': oid})
    if not drone:
        return jsonify({'error': 'Dron no encontrado'}), 404

    data = request.get_json() or {}
    accion = data.get('accion')
    update = {}

    if accion == 'despegar':
        if drone['estado'] != 'en_tierra':
            return jsonify({'error': 'El UAV no está en tierra'}), 409
        if drone['bateria_pct'] < 10:
            return jsonify({'error': 'Batería insuficiente'}), 409
        update = {'estado': 'volando'}
        msg = 'Despegue ejecutado'

    elif accion == 'aterrizar':
        if drone['estado'] != 'volando':
            return jsonify({'error': 'El UAV no está volando'}), 409
        update = {'estado': 'aterrizando', 'destino': None}
        msg = 'Aterrizaje iniciado'

    elif accion == 'ir_a':
        if drone['estado'] != 'volando':
            return jsonify({'error': 'El UAV debe estar volando'}), 409
        # Support lat/lon or x/y
        if data.get('lat') is not None:
            dest = {'lat': float(data['lat']), 'lon': float(data['lon'])}
        elif data.get('x') is not None:
            dest = {'x': float(data['x']), 'y': float(data['y'])}
        else:
            return jsonify({'error': 'Faltan coordenadas de destino'}), 400
        update = {'destino': dest}
        msg = f'Destino asignado'

    elif accion == 'recargar':
        if drone['estado'] != 'en_tierra':
            return jsonify({'error': 'Solo se recarga en tierra'}), 409
        update = {'bateria_pct': 100.0}
        msg = 'Batería recargada al 100%'

    elif accion == 'mantenimiento':
        update = {'estado': 'mantenimiento', 'destino': None}
        msg = 'UAV en mantenimiento'

    elif accion == 'activar':
        if drone['estado'] != 'mantenimiento':
            return jsonify({'error': 'El UAV no está en mantenimiento'}), 409
        update = {'estado': 'en_tierra'}
        msg = 'UAV activado'

    else:
        return jsonify({'error': f'Acción desconocida: {accion}'}), 400

    drones_col.update_one({'_id': oid}, {'$set': update})
    log_event(oid, accion, msg)
    return jsonify({'ok': True, 'mensaje': msg, 'drone': serialize(drones_col.find_one({'_id': oid}))})


@app.route('/api/eventos', methods=['GET'])
def list_events():
    drone_id = request.args.get('drone_id')
    query = {'drone_id': drone_id} if drone_id else {}
    events = list(events_col.find(query).sort('ts', -1).limit(60))
    for e in events:
        e['id'] = str(e['_id'])
        del e['_id']
        e['ts'] = e['ts'].isoformat()
    return jsonify(events)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)