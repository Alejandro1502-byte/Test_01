# DRONE SIM // ArduPilot SITL Simulator

Simulador de drones 3D cliente-servidor con mapa satelital real, elevaciones de terreno,
modos de vuelo ArduPilot y puente MAVLink/SITL.

```
╔══════════════════════════════════════════════╗
║       DRONE SIM // ArduPilot SITL           ║
╚══════════════════════════════════════════════╝
```

---

## Estructura del proyecto

```
drone-sim/
│
├── backend/                        ← Servidor Python (FastAPI + WebSocket)
│   ├── run.py                      ← Script de arranque
│   ├── server.py                   ← FastAPI app, WS hub, loop de simulación
│   ├── config.py                   ← Configuración central (env vars)
│   ├── requirements.txt
│   │
│   ├── core/
│   │   ├── drone.py                ← Física de vuelo + todos los modos (ACRO/LOITER/ALT_HOLD/AUTO/RTL)
│   │   ├── mission_planner.py      ← Generador de waypoints (GRID/ORBIT/CORRIDOR/SWARM/DIRECT)
│   │   └── swarm_manager.py        ← Gestión de la flota de drones
│   │
│   ├── terrain/
│   │   ├── elevation.py            ← Elevaciones reales via Open-Elevation API + caché disco
│   │   └── gazebo_bridge.py        ← Parser de mundos .world de Gazebo + conversión coords
│   │
│   ├── mavlink/
│   │   ├── sitl_bridge.py          ← Puente MAVLink / ArduPilot SITL (real o demo)
│   │   └── ardupilot_params.py     ← Definición y gestión de parámetros ArduCopter
│   │
│   └── client/
│       └── gcs_terminal.py         ← GCS en terminal (cliente Python independiente)
│
└── frontend/                       ← Cliente web (HTML + JS puro)
    ├── index.html                  ← UI principal
    ├── css/
    │   └── style.css               ← Tema táctico oscuro
    └── js/
        ├── ws.js                   ← Cliente WebSocket con reconexión automática
        ├── map3d.js                ← MapLibre GL 3D: terreno, satélite, markers drones
        ├── drone_state.js          ← Registro cliente + telemetría cards
        ├── ui.js                   ← Todos los controles de UI y lógica de paneles
        ├── hud.js                  ← HUD overlay y reloj de misión
        ├── params_panel.js         ← Panel de parámetros ArduPilot
        └── attitude_indicator.js   ← Indicador de actitud (ADI) en Canvas
```

---

## Instalación y arranque

### Requisitos
- Python 3.10+
- Navegador moderno (Chrome/Firefox/Edge) con WebGL

### Backend

```bash
cd drone-sim/backend
pip install -r requirements.txt
python run.py
```

El servidor arranca en `http://localhost:8765`.
El navegador se abre automáticamente.

### Opciones de arranque

```bash
# Normal (demo sin SITL)
python run.py

# Con ArduPilot SITL real
python run.py --sitl

# Puerto personalizado
python run.py --port 9000

# Solo frontend (sin servidor)
python run.py --demo

# GCS terminal (cliente independiente)
python client/gcs_terminal.py
python client/gcs_terminal.py --add-drone --start
```

---

## Modos de vuelo

| Modo | Descripción | Comportamiento |
|------|-------------|----------------|
| **ACRO** | Acrobático puro | Control directo de tasas roll/pitch/yaw. Sin auto-nivelado. |
| **LOITER** | Posición GPS | Vuelo suave hacia waypoints. Frenada automática. |
| **ALT_HOLD** | Altitud fija | Mantiene la altitud configurada. Control lateral libre. |
| **AUTO** | Misión autónoma | Sigue la secuencia de waypoints planificada. |
| **RTL** | Return to Launch | 1) Sube a altitud segura → 2) Vuela en línea recta al home → 3) Aterriza |

### Comportamiento RTL detallado
```
Estado actual           → SUBIR a rtl_safe_alt (default: 60m AGL)
Altitud alcanzada       → VOLAR en línea recta al punto home
Sobre punto home        → DESCENDER a tierra
Tierra alcanzada        → IDLE (desarmado)
```

---

## Patrones de misión AUTO

| Patrón | Descripción |
|--------|-------------|
| `direct` | Vuelo directo origen → destino |
| `grid` | Barrido en lawnmower sobre un bounding box |
| `orbit` | Órbita circular alrededor de un punto central |
| `corridor` | Sigue una polilínea de puntos |
| `swarm` | N drones convergen sobre un target desde ángulos distintos |

Todos los WPs se ajustan automáticamente a la elevación del terreno + margen de seguridad.

---

## Terreno real (elevaciones)

El módulo `terrain/elevation.py` obtiene elevaciones reales:

1. **Caché en disco** (`.elev_cache/elev_cache.json`) — sin latencia
2. **Open-Elevation API** (`api.open-elevation.com`) — datos SRTM globales
3. **OpenTopoData** (fallback) — SRTM 90m
4. **Aproximación** — para uso offline / demo

```python
from terrain.elevation import TerrainProvider
t = TerrainProvider()
elev = t.get_elevation(40.416, -3.703)  # → 650.0 m
tile  = t.get_tile_elevations({"n":40.43,"s":40.40,"e":-3.68,"w":-3.73})
```

---

## Integración con Gazebo

```python
from terrain.gazebo_bridge import world_from_file, world_from_preset

# Cargar mundo Gazebo
world = world_from_preset("sonoma")           # mundo predefinido
world = world_from_file("/path/to/iris.world") # archivo .world real

# Convertir coordenadas
lat, lon, alt = world.gazebo_to_latlon(gx=10, gy=20, gz=5)
gx, gy, gz    = world.latlon_to_gazebo(lat=38.16, lon=-122.45, alt=500)
```

Mundos predefinidos: `empty`, `sonoma`, `iris_lawn`, `madrid`, `fcollado`

---

## Integración MAVLink / ArduPilot SITL

### Arrancar ArduPilot SITL (externo)

```bash
# Descargar ArduPilot
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
./Tools/autotest/sim_vehicle.py -v ArduCopter --map --console \
  --home=40.416775,-3.703790,650,0

# O directamente:
./arducopter --model quad --speedup 1 \
  --home 40.416775,-3.703790,650,0
```

### Conectar el simulador

```bash
python run.py --sitl
```

El bridge `mavlink/sitl_bridge.py` se conecta a `udp:127.0.0.1:14550`.

### Parámetros ArduPilot

Los parámetros se gestionan con nombres estándar de ArduCopter:

```
WPNAV_SPEED    500   cm/s    Velocidad en AUTO
RTL_ALT        1500  cm      Altitud de vuelo RTL
ACRO_ROLL_RATE 180   deg/s   Tasa de roll en ACRO
BATT_FAILSAFE  2     enum    2=RTL al bajo voltaje
```

Se pueden editar desde el panel **⚙ PARÁMETROS** en el frontend.

---

## API REST

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/drones` | GET | Lista todos los drones |
| `/api/drones` | POST | Añadir dron |
| `/api/drones/{id}` | DELETE | Eliminar dron |
| `/api/elevation?lat=&lon=` | GET | Elevación en punto |
| `/api/terrain?n=&s=&e=&w=` | GET | Grid de elevaciones |
| `/api/mavlink/sitl_status` | GET | Estado conexión SITL |
| `/docs` | GET | Swagger UI |

## WebSocket (`ws://localhost:8765/ws`)

### Mensajes cliente → servidor

```json
{"type": "add_drone",          "lat": 40.4, "lon": -3.7, "name": "UAV-01"}
{"type": "set_mode",           "drone_id": "AB12", "mode": "RTL"}
{"type": "add_waypoint",       "drone_id": "AB12", "waypoint": {"lat":..,"lon":..,"alt":50}}
{"type": "plan_mission",       "drone_id": "AB12", "pattern": "grid", "altitude": 60}
{"type": "start_simulation"}
{"type": "stop_simulation"}
{"type": "get_elevation",      "lat": 40.4, "lon": -3.7}
{"type": "mavlink_command",    "drone_id": "AB12", "command": "ARM"}
{"type": "set_params",         "drone_id": "AB12", "params": {"WPNAV_SPEED": 800}}
```

### Mensajes servidor → cliente

```json
{"type": "telemetry_batch", "drones": [{...}], "tick": 1234, "t": 61.5}
{"type": "drone_added",     "drone": {...}}
{"type": "mission_planned", "result": {"waypoints": [...]}}
{"type": "mode_changed",    "drone_id": "AB12", "mode": "RTL"}
{"type": "elevation",       "lat": 40.4, "lon": -3.7, "elevation": 650.0}
```

---

## Variables de entorno

```bash
SIM_HOST=0.0.0.0        # Interfaz de escucha
SIM_PORT=8765           # Puerto
SIM_HZ=20               # Ticks de simulación por segundo
MAX_DRONES=32           # Máximo de drones simultáneos
HOME_LAT=40.416775      # Coordenada home por defecto
HOME_LON=-3.703790
HOME_ALT=650.0          # Altitud AMSL del home (m)
TERRAIN_API=1           # 1=usar Open-Elevation API, 0=solo aproximación
TERRAIN_CLEARANCE=30    # Margen AGL sobre terreno (m)
SITL_ENABLED=0          # 1=conectar con ArduPilot SITL
SITL_ADDRESS=udp:127.0.0.1:14550
```

---

## Tecnologías

| Componente | Tecnología |
|------------|------------|
| Backend    | Python 3.10+ / FastAPI / uvicorn |
| WebSocket  | `websockets` / FastAPI WebSocket |
| MAVLink    | `pymavlink` (opcional) |
| Mapa 3D    | MapLibre GL JS 4.x |
| Terreno    | Open-Elevation API / SRTM |
| Satélite   | Google Maps tiles (demo) / MapTiler |
| Gazebo     | gz-transport (opcional) |
| Frontend   | HTML5 / CSS3 / JS ES6+ (sin frameworks) |