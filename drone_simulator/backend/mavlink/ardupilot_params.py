"""
mavlink/ardupilot_params.py
Parámetros estándar de ArduCopter / ArduPilot relevantes para la simulación.
Permite configurar el comportamiento del autopiloto simulado
con los mismos nombres de parámetro que usa ArduPilot real.
"""

# ── Parámetros de vuelo (ArduCopter) ──────────────────────────────────────────
PARAMS_DEFINITION = {
    # ── Velocidades ─────────────────────────────────────────────────
    "WPNAV_SPEED":       {"default": 500,  "unit": "cm/s",  "desc": "Velocidad horizontal en AUTO"},
    "WPNAV_SPEED_UP":    {"default": 250,  "unit": "cm/s",  "desc": "Velocidad de subida en AUTO"},
    "WPNAV_SPEED_DN":    {"default": 150,  "unit": "cm/s",  "desc": "Velocidad de bajada en AUTO"},
    "WPNAV_ACCEL":       {"default": 250,  "unit": "cm/s²", "desc": "Aceleración horizontal"},
    "WPNAV_RADIUS":      {"default": 200,  "unit": "cm",    "desc": "Radio de aceptación de WP"},

    # ── Altitud RTL ──────────────────────────────────────────────────
    "RTL_ALT":           {"default": 1500, "unit": "cm",    "desc": "Altitud AGL de vuelo RTL"},
    "RTL_ALT_FINAL":     {"default": 0,    "unit": "cm",    "desc": "Altitud final antes de aterrizar"},
    "RTL_SPEED":         {"default": 0,    "unit": "cm/s",  "desc": "0 = usar WPNAV_SPEED"},
    "RTL_LOIT_TIME":     {"default": 5000, "unit": "ms",    "desc": "Tiempo de loiter en RTL antes de bajar"},
    "RTL_CONE_SLOPE":    {"default": 3,    "unit": "ratio", "desc": "Pendiente de cono RTL"},

    # ── LOITER ───────────────────────────────────────────────────────
    "LOIT_SPEED":        {"default": 1250, "unit": "cm/s",  "desc": "Velocidad máx en LOITER"},
    "LOIT_ACC_MAX":      {"default": 500,  "unit": "cm/s²", "desc": "Aceleración máx en LOITER"},
    "LOIT_BRK_ACCEL":    {"default": 250,  "unit": "cm/s²", "desc": "Deceleración de frenada LOITER"},
    "LOIT_BRK_JERK":     {"default": 500,  "unit": "cm/s³", "desc": "Jerk de frenada LOITER"},
    "LOIT_BRK_DELAY":    {"default": 1.0,  "unit": "s",     "desc": "Retardo frenada LOITER"},

    # ── ALT_HOLD ─────────────────────────────────────────────────────
    "PILOT_SPEED_UP":    {"default": 250,  "unit": "cm/s",  "desc": "Vel. subida manual"},
    "PILOT_SPEED_DN":    {"default": 150,  "unit": "cm/s",  "desc": "Vel. bajada manual"},
    "PILOT_ACCEL_Z":     {"default": 250,  "unit": "cm/s²", "desc": "Aceleración vertical"},

    # ── ACRO ─────────────────────────────────────────────────────────
    "ACRO_ROLL_RATE":    {"default": 180,  "unit": "deg/s", "desc": "Tasa de roll en ACRO"},
    "ACRO_PITCH_RATE":   {"default": 180,  "unit": "deg/s", "desc": "Tasa de pitch en ACRO"},
    "ACRO_YAW_RATE":     {"default": 90,   "unit": "deg/s", "desc": "Tasa de yaw en ACRO"},
    "ACRO_EXPO":         {"default": 0.3,  "unit": "",      "desc": "Exponencial en ACRO (0-1)"},
    "ACRO_THR_MID":      {"default": 0.5,  "unit": "",      "desc": "Punto muerto de throttle ACRO"},

    # ── PID Estabilización ───────────────────────────────────────────
    "ATC_RAT_RLL_P":     {"default": 0.135,"unit": "",      "desc": "PID Roll - P"},
    "ATC_RAT_RLL_I":     {"default": 0.135,"unit": "",      "desc": "PID Roll - I"},
    "ATC_RAT_RLL_D":     {"default": 0.0036,"unit":"",      "desc": "PID Roll - D"},
    "ATC_RAT_PIT_P":     {"default": 0.135,"unit": "",      "desc": "PID Pitch - P"},
    "ATC_RAT_PIT_I":     {"default": 0.135,"unit": "",      "desc": "PID Pitch - I"},
    "ATC_RAT_PIT_D":     {"default": 0.0036,"unit":"",      "desc": "PID Pitch - D"},
    "ATC_RAT_YAW_P":     {"default": 0.18, "unit": "",      "desc": "PID Yaw - P"},
    "ATC_RAT_YAW_I":     {"default": 0.018,"unit": "",      "desc": "PID Yaw - I"},
    "ATC_RAT_YAW_D":     {"default": 0.0,  "unit": "",      "desc": "PID Yaw - D"},

    # ── Batería / motor ──────────────────────────────────────────────
    "BATT_LOW_VOLT":     {"default": 14.0, "unit": "V",     "desc": "Voltaje batería baja"},
    "BATT_CRT_VOLT":     {"default": 13.5, "unit": "V",     "desc": "Voltaje batería crítica"},
    "BATT_LOW_MAH":      {"default": 600,  "unit": "mAh",   "desc": "mAh restantes = batería baja"},
    "BATT_FAILSAFE":     {"default": 2,    "unit": "enum",  "desc": "0=nada 1=warn 2=RTL 3=land"},

    # ── GPS / EKF ────────────────────────────────────────────────────
    "GPS_TYPE":          {"default": 1,    "unit": "enum",  "desc": "1=Auto, 14=SITL"},
    "EK3_ENABLE":        {"default": 1,    "unit": "bool",  "desc": "Activar EKF3"},
    "EK3_GPS_TYPE":      {"default": 0,    "unit": "enum",  "desc": "GPS fusion type"},

    # ── Seguridad ────────────────────────────────────────────────────
    "FS_THR_ENABLE":     {"default": 2,    "unit": "enum",  "desc": "Failsafe throttle: 2=RTL"},
    "FS_GCS_ENABLE":     {"default": 2,    "unit": "enum",  "desc": "Failsafe GCS: 2=RTL"},
    "FENCE_ENABLE":      {"default": 0,    "unit": "bool",  "desc": "Geofence activo"},
    "FENCE_ALT_MAX":     {"default": 100,  "unit": "m",     "desc": "Altitud máx geofence"},
    "FENCE_RADIUS":      {"default": 300,  "unit": "m",     "desc": "Radio geofence"},
}


class ArduPilotParams:
    """
    Almacén de parámetros ArduPilot para un dron.
    Acepta get/set con los nombres estándar de ArduPilot.
    Convierte a las unidades usadas internamente por el simulador.
    """

    def __init__(self):
        self._params = {k: v["default"] for k, v in PARAMS_DEFINITION.items()}

    def get(self, name: str):
        return self._params.get(name)

    def set(self, name: str, value):
        if name not in self._params:
            return False
        self._params[name] = value
        return True

    def set_many(self, params: dict):
        for k, v in params.items():
            self.set(k, v)

    def all(self) -> dict:
        return dict(self._params)

    def to_sim_units(self) -> dict:
        """Convert to simulator internal units (SI)."""
        p = self._params
        return {
            # speeds in m/s
            "max_speed_auto":   p["WPNAV_SPEED"] / 100,
            "max_speed_loiter": p["LOIT_SPEED"]  / 100,
            "max_climb":        p["WPNAV_SPEED_UP"] / 100,
            "max_descent":      p["WPNAV_SPEED_DN"] / 100,
            "wp_radius":        p["WPNAV_RADIUS"] / 100,
            # RTL
            "rtl_safe_alt":     p["RTL_ALT"] / 100,
            "rtl_loit_time":    p["RTL_LOIT_TIME"] / 1000,
            # ACRO
            "acro_roll_rate":   p["ACRO_ROLL_RATE"],
            "acro_pitch_rate":  p["ACRO_PITCH_RATE"],
            "acro_yaw_rate":    p["ACRO_YAW_RATE"],
        }

    def failsafe_action(self) -> str:
        """Return the failsafe mode string."""
        v = self._params.get("BATT_FAILSAFE", 0)
        return {0: "NONE", 1: "WARN", 2: "RTL", 3: "LAND"}.get(v, "RTL")