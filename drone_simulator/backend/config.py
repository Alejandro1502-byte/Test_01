"""
config.py – Configuración central del simulador
Carga desde variables de entorno o valores por defecto.
"""
import os

# ── Servidor ──────────────────────────────────────────────────────────────────
HOST        = os.getenv("SIM_HOST", "0.0.0.0")
PORT        = int(os.getenv("SIM_PORT", 8765))
DEBUG       = os.getenv("SIM_DEBUG", "1") == "1"
RELOAD      = os.getenv("SIM_RELOAD", "1") == "1"

# ── Simulación ────────────────────────────────────────────────────────────────
SIM_HZ          = int(os.getenv("SIM_HZ", 20))          # ticks/seg
MAX_DRONES      = int(os.getenv("MAX_DRONES", 32))
DEFAULT_HOME    = {
    "lat": float(os.getenv("HOME_LAT",  40.416775)),
    "lon": float(os.getenv("HOME_LON",  -3.703790)),
    "alt": float(os.getenv("HOME_ALT",  650.0)),         # AMSL Madrid
}

# ── Terrain ───────────────────────────────────────────────────────────────────
TERRAIN_CACHE_DIR   = os.getenv("TERRAIN_CACHE", "./terrain/.elev_cache")
TERRAIN_USE_API     = os.getenv("TERRAIN_API", "1") == "1"
TERRAIN_CLEARANCE   = float(os.getenv("TERRAIN_CLEARANCE", 30))  # m AGL mínimo

# ── MAVLink / SITL ────────────────────────────────────────────────────────────
SITL_ADDRESS    = os.getenv("SITL_ADDRESS", "udp:127.0.0.1:14550")
SITL_ENABLED    = os.getenv("SITL_ENABLED", "0") == "1"
MAVLINK_SYSID   = int(os.getenv("MAV_SYSID", 1))
MAVLINK_COMPID  = int(os.getenv("MAV_COMPID", 1))

# ── Física de drones (defaults) ───────────────────────────────────────────────
PHYSICS = {
    "max_speed_acro":   28.0,    # m/s
    "max_speed_loiter": 12.0,
    "max_speed_auto":   18.0,
    "max_climb":        5.0,     # m/s vertical
    "max_descent":      3.0,
    "turn_rate_acro":   180.0,   # deg/s
    "turn_rate_loiter": 45.0,
    "acro_drag":        0.05,
    "battery_drain":    0.001,   # %/s en vuelo
    "rtl_safe_alt":     60.0,    # m AGL mínimo para RTL
}

# ── Tiles de mapa (frontend) ──────────────────────────────────────────────────
MAP_CENTER  = DEFAULT_HOME
MAP_ZOOM    = 13