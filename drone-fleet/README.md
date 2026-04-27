# Drone Fleet Control — Sistema de Mando y Control

Aplicación CRUD + simulador en tiempo real para gestionar una flota de drones, orquestada con Docker Compose.

## Arquitectura

```
┌──────────────┐   HTTP    ┌──────────────┐  pymongo  ┌──────────────┐
│   client     │──────────▶│   server     │──────────▶│    mongo     │
│  (nginx)     │  :5001    │  (Flask)     │  :27017   │  (MongoDB)   │
│  :8080       │           │              │           │              │
└──────────────┘           └──────────────┘           └──────┬───────┘
                                                              │
                            ┌──────────────┐                 │ :27017
                            │  simulator   │─────────────────┘
                            │  (Python)    │ (escribe directo a Mongo)
                            └──────────────┘
                                                       ┌──────────────┐
                                                       │ mongo-express│
                                                       │   :8081      │
                                                       └──────────────┘
```

| Servicio | Imagen | Puerto | Función |
|---|---|---|---|
| **client** | nginx:alpine | 8080 | UI táctica (HTML + canvas) |
| **server** | python:3.11-slim | 5001 | API REST Flask (CRUD + órdenes) |
| **simulator** | python:3.11-slim | — | Tick cada 2s: mueve drones, baja batería |
| **mongo** | mongo:7 | 27017 | Persistencia de flota y eventos |
| **mongo-express** | mongo-express:1.0.2 | 8081 | UI web para inspeccionar BD |

## Arrancar

```bash
docker compose up --build
```

- [http://localhost:8080](http://localhost:8080) → **Aplicación** (mando y control)
- [http://localhost:8081](http://localhost:8081) → **mongo-express** (`admin`/`admin123`)
- [http://localhost:5001/api/health](http://localhost:5001/api/health) → Health check API

## Cómo usar

1. Registra un dron con el formulario inferior izquierdo.
2. Selecciona el dron en la lista → aparece resaltado en el mapa.
3. Pulsa **▲ DESPEGAR** para ponerlo en vuelo.
4. Haz **click en el mapa** (o usa "IR A…") para asignarle un destino.
5. El simulador lo moverá automáticamente cada 2 segundos.
6. La batería baja 0.5% por tick mientras vuela. Si cae al 5% → aterrizaje forzado.
7. Aterriza y recarga con **⚡ RECARGAR**.

## Modelo de dron

```json
{
  "modelo": "Mavic 3",
  "fabricante": "DJI",
  "estado": "en_tierra | volando | aterrizando | mantenimiento",
  "posicion": { "x": 50.0, "y": 50.0 },
  "destino": { "x": 80.0, "y": 30.0 },
  "bateria_pct": 87.5,
  "velocidad": 2.0
}
```

## Endpoints de la API

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/drones` | Lista la flota |
| GET | `/api/drones/<id>` | Un dron |
| POST | `/api/drones` | Crear dron |
| DELETE | `/api/drones/<id>` | Eliminar dron |
| POST | `/api/drones/<id>/orden` | Enviar orden |
| GET | `/api/eventos` | Histórico de eventos |

### Órdenes disponibles

```json
{ "accion": "despegar" }
{ "accion": "aterrizar" }
{ "accion": "ir_a", "x": 75, "y": 40 }
{ "accion": "recargar" }
{ "accion": "mantenimiento" }
{ "accion": "activar" }
```

## Variables de entorno del simulador

| Variable | Default | Descripción |
|---|---|---|
| `TICK_SECONDS` | 2 | Segundos entre ticks |
| `BATTERY_DRAIN` | 0.5 | % batería por tick en vuelo |
| `LANDING_DRAIN` | 0.2 | % batería al aterrizar |
| `ARRIVAL_THRESHOLD` | 0.5 | Distancia para considerar "llegado" |

## Estructura de archivos

```
drone-fleet/
├── docker-compose.yml
├── README.md
├── client/
│   ├── Dockerfile
│   └── index.html
├── server/
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
└── simulator/
    ├── Dockerfile
    └── simulator.py
```
