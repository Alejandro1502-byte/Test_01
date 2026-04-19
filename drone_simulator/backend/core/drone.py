"""
core/drone.py – Drone physics, flight modes, MAVLink state machine
"""

import math
import uuid
import time
from enum import Enum
from typing import List, Optional, Dict, Any


# ─── Enums ────────────────────────────────────────────────────────────────────
class DroneMode(Enum):
    # Manual sub-modes
    ACRO      = "ACRO"       # Raw rate control – full aerobatics
    LOITER    = "LOITER"     # GPS position hold + smooth nav
    ALT_HOLD  = "ALT_HOLD"   # Hold altitude, free horizontal movement
    # Auto
    AUTO      = "AUTO"       # Autonomous waypoint mission
    # Emergency
    RTL       = "RTL"        # Return to Launch / Rally point
    ABORT     = "ABORT"      # Abort mission → fly to rally point or home
    # Ground
    STABILIZE = "STABILIZE"  # Manual with self-levelling
    LAND      = "LAND"
    GUIDED    = "GUIDED"


class FlightPhase(Enum):
    IDLE        = "IDLE"
    TAKEOFF     = "TAKEOFF"
    CRUISE      = "CRUISE"
    WP_TURN     = "WP_TURN"
    LOITER      = "LOITER"
    DESCEND     = "DESCEND"
    LAND        = "LAND"
    RTL_CLIMB   = "RTL_CLIMB"
    RTL_FLY     = "RTL_FLY"
    RTL_LAND    = "RTL_LAND"
    ABORT_CLIMB = "ABORT_CLIMB"   # Abort: subir a altitud segura
    ABORT_FLY   = "ABORT_FLY"     # Abort: volar al rally/home
    ABORT_HOLD  = "ABORT_HOLD"    # Abort: loiter en rally point
    IMPACT      = "IMPACT"


# ─── Waypoint ────────────────────────────────────────────────────────────────
class Waypoint:
    def __init__(self, lat: float, lon: float, alt: float,
                 speed: Optional[float] = None, loiter_radius: float = 0,
                 loiter_time: float = 0, wp_type: str = "WAYPOINT"):
        self.lat   = lat
        self.lon   = lon
        self.alt   = alt          # AGL metres
        self.speed = speed        # None = inherit drone speed
        self.loiter_radius = loiter_radius
        self.loiter_time   = loiter_time
        self.wp_type = wp_type    # WAYPOINT | LOITER_UNLIM | LOITER_TIME | LAND | RTL

    def to_dict(self):
        return {"lat": self.lat, "lon": self.lon, "alt": self.alt,
                "speed": self.speed, "loiter_radius": self.loiter_radius,
                "loiter_time": self.loiter_time, "wp_type": self.wp_type}


# ─── Drone ────────────────────────────────────────────────────────────────────
class Drone:
    GRAVITY = 9.81

    # Physics defaults
    MAX_SPEED_ACRO   = 28.0   # m/s
    MAX_SPEED_LOITER = 12.0
    MAX_SPEED_AUTO   = 18.0
    MAX_CLIMB        = 5.0    # m/s vertical
    MAX_DESCENT      = 3.0
    TURN_RATE_ACRO   = 180.0  # deg/s
    TURN_RATE_LOITER = 45.0
    ACRO_DRAG        = 0.05   # velocity damping per tick

    def __init__(self, lat: float, lon: float, alt: float = 0,
                 name: str = "UAV", color: str = "#00ff88"):
        self.id    = str(uuid.uuid4())[:8].upper()
        self.name  = name
        self.color = color

        # Position — alt es AGL (sobre el terreno), no AMSL
        self.lat = lat
        self.lon = lon
        self.alt = alt        # AGL: empieza en 0 = en el suelo

        # Velocity (m/s in local NED-ish frame)
        self.vx = 0.0   # north
        self.vy = 0.0   # east
        self.vz = 0.0   # up

        # Attitude
        self.roll  = 0.0   # degrees
        self.pitch = 0.0
        self.yaw   = 0.0   # heading degrees 0-360

        # Mode & phase
        self.mode  = DroneMode.LOITER
        self.phase = FlightPhase.IDLE

        # Mission
        self.waypoints: List[Waypoint] = []
        self.wp_idx = 0
        self.speed  = 10.0   # m/s cruise
        self.target_alt = alt

        # RTL / ABORT
        self.rtl_home: Optional[Dict] = {"lat": lat, "lon": lon, "alt": alt}
        self.rtl_safe_alt = 50.0   # climb to this AGL before flying home
        # Rally point: destino de ABORT (si es None, usa rtl_home)
        self.rally_point: Optional[Dict] = None
        self.abort_loiter_time = 0.0   # segundos en ABORT_HOLD

        # ACRO state
        self.acro_roll_rate  = 0.0   # deg/s commanded
        self.acro_pitch_rate = 0.0
        self.acro_yaw_rate   = 0.0

        # ALT_HOLD
        self.alt_hold_target = alt

        # Telemetry
        self.battery   = 100.0   # %
        self.armed     = True   # armado por defecto en simulador
        self.gps_sats  = 16
        self.rssi      = -55     # dBm
        self.created_at = time.time()

        # Trail
        self.trail: List[Dict] = []
        self.MAX_TRAIL = 500

    # ── Mode switch ──────────────────────────────────────────────────────────
    def set_mode(self, mode_str: str, params: dict = {}):
        try:
            self.mode = DroneMode[mode_str.upper()]
        except KeyError:
            return False

        if self.mode == DroneMode.RTL:
            self.phase = FlightPhase.RTL_CLIMB
        elif self.mode == DroneMode.ABORT:
            self.phase = FlightPhase.ABORT_CLIMB
            self.abort_loiter_time = 0.0
        elif self.mode == DroneMode.ALT_HOLD:
            self.alt_hold_target = params.get("altitude", self.alt)
            self.target_alt = self.alt_hold_target
        elif self.mode == DroneMode.AUTO:
            self.wp_idx = 0
            self.phase  = FlightPhase.TAKEOFF if self.phase == FlightPhase.IDLE else FlightPhase.CRUISE
        return True

    def add_waypoint(self, wp_dict: dict):
        wp = Waypoint(
            lat=wp_dict["lat"], lon=wp_dict["lon"], alt=wp_dict.get("alt", 50),
            speed=wp_dict.get("speed"), loiter_radius=wp_dict.get("loiter_radius", 0),
            loiter_time=wp_dict.get("loiter_time", 0), wp_type=wp_dict.get("wp_type","WAYPOINT")
        )
        self.waypoints.append(wp)

    # ── Physics step ─────────────────────────────────────────────────────────
    def step(self, dt: float, terrain) -> Optional[Dict]:
        """Advance simulation by dt seconds. Returns telemetry dict."""
        if self.phase == FlightPhase.IDLE and not self.armed:
            return None
        # Si armado pero IDLE → arrancar despegue
        if self.phase == FlightPhase.IDLE and self.armed:
            self.phase = FlightPhase.TAKEOFF
            self.target_alt = 30.0   # 30m AGL por defecto

        terrain_alt = terrain.get_elevation(self.lat, self.lon)

        if self.mode == DroneMode.ACRO:
            self._step_acro(dt)
        elif self.mode == DroneMode.LOITER:
            self._step_loiter(dt)
        elif self.mode == DroneMode.ALT_HOLD:
            self._step_alt_hold(dt)
        elif self.mode == DroneMode.AUTO:
            self._step_auto(dt, terrain)
        elif self.mode == DroneMode.RTL:
            self._step_rtl(dt, terrain)
        elif self.mode == DroneMode.ABORT:
            self._step_abort(dt, terrain)

        # Apply velocity to position
        self._integrate_position(dt)

        # El simulador trabaja en AGL puro (alt=0 es el suelo)
        # terrain_alt es AMSL pero nosotros lo ignoramos — alt=0 ya ES el suelo
        SAFETY_CLEARANCE = 2.0
        if self.alt < 0:
            self.alt = 0.0
            self.vz  = max(0.0, self.vz)
        if self.alt < SAFETY_CLEARANCE:
            if self.phase in (FlightPhase.LAND, FlightPhase.RTL_LAND, FlightPhase.IDLE):
                self.alt = 0.0
                self.vz  = 0.0
                self.vx  = self.vx * 0.8
                self.vy  = self.vy * 0.8
            else:
                self.alt = SAFETY_CLEARANCE
                if self.vz < 0:
                    self.vz = 0.3

        # Battery drain (rough)
        self.battery = max(0.0, self.battery - 0.001 * dt)

        # Trail
        if len(self.trail) == 0 or self._trail_dist() > 1:
            self.trail.append({"lat": self.lat, "lon": self.lon, "alt": self.alt})
            if len(self.trail) > self.MAX_TRAIL:
                self.trail.pop(0)

        return self.serialize()

    # ── Mode controllers ─────────────────────────────────────────────────────
    def _step_acro(self, dt: float):
        """Acrobatic mode – direct rate control."""
        self.roll  = (self.roll  + self.acro_roll_rate  * dt) % 360
        self.pitch = max(-90, min(90, self.pitch + self.acro_pitch_rate * dt))
        self.yaw   = (self.yaw   + self.acro_yaw_rate   * dt) % 360

        # Convert pitch/roll to velocity
        yaw_r = math.radians(self.yaw)
        pitch_r = math.radians(self.pitch)
        roll_r  = math.radians(self.roll)

        thrust = self.speed * math.cos(pitch_r) * math.cos(roll_r)
        self.vx = thrust * math.cos(yaw_r)
        self.vy = thrust * math.sin(yaw_r)
        self.vz = self.speed * math.sin(pitch_r)

        # drag
        self.vx *= (1 - self.ACRO_DRAG)
        self.vy *= (1 - self.ACRO_DRAG)

    def _step_loiter(self, dt: float):
        """Loiter – gentle, GPS-stabilised flight towards next WP."""
        if not self.waypoints:
            # Hover in place
            self.vx *= 0.9
            self.vy *= 0.9
            self._vert_ctrl(self.target_alt, dt)
            return
        self._navigate_to_wp(dt, self.MAX_SPEED_LOITER, self.TURN_RATE_LOITER)

    def _step_alt_hold(self, dt: float):
        """Alt hold – maintain altitude, accept lateral velocity from joystick."""
        self._vert_ctrl(self.alt_hold_target, dt)
        # Lateral: keep existing vx/vy with light damping
        self.vx *= 0.97
        self.vy *= 0.97

    def _step_auto(self, dt: float, terrain):
        """Autonomous mission – fly through waypoints in sequence."""
        if self.phase == FlightPhase.IDLE:
            self.phase = FlightPhase.TAKEOFF

        if self.phase == FlightPhase.TAKEOFF:
            takeoff_alt = self.waypoints[0].alt if self.waypoints else 50
            self._vert_ctrl(takeoff_alt, dt)
            if abs(self.alt - takeoff_alt) < 2:
                self.phase = FlightPhase.CRUISE
            return

        if not self.waypoints or self.wp_idx >= len(self.waypoints):
            # Mission complete
            self.phase = FlightPhase.LAND
            self._vert_ctrl(terrain.get_elevation(self.lat, self.lon), dt)
            return

        wp = self.waypoints[self.wp_idx]
        dist = self._haversine(self.lat, self.lon, wp.lat, wp.lon)

        if dist < 5.0:  # arrived
            if wp.wp_type == "LOITER_TIME":
                # simple: just advance after loiter_time (not tracked here for brevity)
                pass
            self.wp_idx += 1
            if self.wp_idx >= len(self.waypoints):
                self.phase = FlightPhase.LAND
        else:
            speed = wp.speed or self.speed
            self._navigate_to_target(wp.lat, wp.lon, wp.alt, dt, min(speed, self.MAX_SPEED_AUTO), self.TURN_RATE_LOITER)

    def _step_rtl(self, dt: float, terrain):
        """Return to Launch – climb, fly home, land."""
        home = self.rtl_home or {"lat": self.lat, "lon": self.lon, "alt": 0}

        if self.phase == FlightPhase.RTL_CLIMB:
            self._vert_ctrl(self.rtl_safe_alt, dt)
            self.vx *= 0.9
            self.vy *= 0.9
            if self.alt >= self.rtl_safe_alt - 2:
                self.phase = FlightPhase.RTL_FLY

        elif self.phase == FlightPhase.RTL_FLY:
            dist = self._haversine(self.lat, self.lon, home["lat"], home["lon"])
            if dist < 5.0:
                self.phase = FlightPhase.RTL_LAND
            else:
                self._navigate_to_target(home["lat"], home["lon"], self.rtl_safe_alt,
                                         dt, self.MAX_SPEED_LOITER, self.TURN_RATE_LOITER)

        elif self.phase == FlightPhase.RTL_LAND:
            self._vert_ctrl(0.0, dt)   # bajar hasta AGL=0
            self.vx *= 0.9
            self.vy *= 0.9
            if self.alt < 1.0:
                self.alt  = 0.0
                self.vz   = 0.0
                self.phase = FlightPhase.IDLE
                self.vx = self.vy = self.vz = 0.0

    def _step_abort(self, dt: float, terrain):
        """
        ABORT – misión interrumpida.
        1) Sube a altitud segura (rtl_safe_alt)
        2) Vuela en línea recta al rally_point (o home si no hay rally)
        3) Hace loiter indefinido en ese punto hasta nueva orden
        """
        dest = self.rally_point or self.rtl_home or {"lat": self.lat, "lon": self.lon, "alt": 0}

        if self.phase == FlightPhase.ABORT_CLIMB:
            self._vert_ctrl(self.rtl_safe_alt, dt)
            self.vx *= 0.85
            self.vy *= 0.85
            if self.alt >= self.rtl_safe_alt - 2:
                self.phase = FlightPhase.ABORT_FLY

        elif self.phase == FlightPhase.ABORT_FLY:
            dist = self._haversine(self.lat, self.lon, dest["lat"], dest["lon"])
            if dist < 8.0:
                self.phase = FlightPhase.ABORT_HOLD
            else:
                self._navigate_to_target(
                    dest["lat"], dest["lon"], self.rtl_safe_alt,
                    dt, self.MAX_SPEED_LOITER, self.TURN_RATE_LOITER
                )

        elif self.phase == FlightPhase.ABORT_HOLD:
            # Loiter circular sobre el rally point
            self.abort_loiter_time += dt
            orbit_r  = 30.0  # metros de radio
            orbit_spd = 5.0   # m/s
            angle = (self.abort_loiter_time * orbit_spd / orbit_r) % (2 * math.pi)
            dlat = (orbit_r * math.cos(angle)) / 111320
            dlon = (orbit_r * math.sin(angle)) / (111320 * math.cos(math.radians(dest["lat"])) + 1e-9)
            tlat = dest["lat"] + dlat
            tlon = dest["lon"] + dlon
            self._navigate_to_target(tlat, tlon, self.rtl_safe_alt, dt, orbit_spd, 60.0)

    # ── Navigation helpers ───────────────────────────────────────────────────
    def _navigate_to_wp(self, dt: float, max_speed: float, turn_rate: float):
        if not self.waypoints or self.wp_idx >= len(self.waypoints):
            return
        wp = self.waypoints[self.wp_idx]
        dist = self._haversine(self.lat, self.lon, wp.lat, wp.lon)
        if dist < 5.0:
            self.wp_idx = min(self.wp_idx + 1, len(self.waypoints) - 1)
            return
        self._navigate_to_target(wp.lat, wp.lon, wp.alt, dt, max_speed, turn_rate)

    def _navigate_to_target(self, tlat, tlon, talt, dt, max_speed, turn_rate):
        bearing_deg = self._bearing(self.lat, self.lon, tlat, tlon)
        # Turn yaw towards bearing
        delta = ((bearing_deg - self.yaw + 540) % 360) - 180
        step  = min(abs(delta), turn_rate * dt)
        self.yaw = (self.yaw + math.copysign(step, delta)) % 360

        # Speed ramp: full speed when aligned
        align = max(0.0, 1.0 - abs(delta) / 90.0)
        spd   = max_speed * align

        yr = math.radians(self.yaw)
        self.vx = spd * math.cos(yr)
        self.vy = spd * math.sin(yr)

        self._vert_ctrl(talt, dt)

    def _vert_ctrl(self, target_alt: float, dt: float):
        err = target_alt - self.alt
        vz_cmd = max(-self.MAX_DESCENT, min(self.MAX_CLIMB, err * 1.5))
        self.vz += (vz_cmd - self.vz) * min(1.0, 3.0 * dt)

    # ── Position integration ─────────────────────────────────────────────────
    def _integrate_position(self, dt: float):
        # 1 deg lat ≈ 111320 m
        self.lat += (self.vx * dt) / 111320.0
        self.lon += (self.vy * dt) / (111320.0 * math.cos(math.radians(self.lat)) + 1e-9)
        self.alt += self.vz * dt

        # attitude from velocity
        spd2d = math.sqrt(self.vx**2 + self.vy**2)
        if spd2d > 0.1:
            self.yaw   = (math.degrees(math.atan2(self.vy, self.vx))) % 360
            self.pitch = math.degrees(math.atan2(self.vz, spd2d))

    # ── Trail distance ───────────────────────────────────────────────────────
    def _trail_dist(self) -> float:
        if not self.trail:
            return 999
        last = self.trail[-1]
        return self._haversine(last["lat"], last["lon"], self.lat, self.lon)

    # ── Geometry ─────────────────────────────────────────────────────────────
    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        R = 6371000
        p = math.pi / 180
        a = (math.sin((lat2-lat1)*p/2)**2 +
             math.cos(lat1*p)*math.cos(lat2*p)*math.sin((lon2-lon1)*p/2)**2)
        return 2*R*math.asin(math.sqrt(a))

    @staticmethod
    def _bearing(lat1, lon1, lat2, lon2) -> float:
        p = math.pi / 180
        dlon = (lon2 - lon1) * p
        x = math.sin(dlon) * math.cos(lat2 * p)
        y = (math.cos(lat1*p)*math.sin(lat2*p) -
             math.sin(lat1*p)*math.cos(lat2*p)*math.cos(dlon))
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    # ── Serialise ────────────────────────────────────────────────────────────
    def serialize(self) -> Dict:
        spd = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        return {
            "id":       self.id,
            "name":     self.name,
            "color":    self.color,
            "lat":      round(self.lat, 7),
            "lon":      round(self.lon, 7),
            "alt":      round(max(self.alt, 0), 2),   # AGL
            "roll":     round(self.roll, 1),
            "pitch":    round(self.pitch, 1),
            "yaw":      round(self.yaw, 1),
            "speed":    round(spd, 2),
            "vz":       round(self.vz, 2),
            "mode":     self.mode.value,
            "phase":    self.phase.value,
            "battery":  round(self.battery, 1),
            "armed":    self.armed,
            "gps_sats": self.gps_sats,
            "rssi":     self.rssi,
            "wp_idx":   self.wp_idx,
            "wp_total": len(self.waypoints),
            "trail":    self.trail[-20:],   # last 20 pts for map
            "waypoints": [w.to_dict() for w in self.waypoints],
        }