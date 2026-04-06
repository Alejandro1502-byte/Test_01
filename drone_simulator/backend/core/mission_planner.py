"""
core/mission_planner.py – AUTO mode waypoint generator
Supports grid surveys, orbit patterns, corridor mapping and direct missions.
"""
import math
from typing import List, Dict, Any


class MissionPlanner:
    def __init__(self, terrain):
        self.terrain = terrain

    def plan(self, cfg: dict) -> dict:
        pattern = cfg.get("pattern", "direct")

        if pattern == "grid":
            wps = self._grid_survey(cfg)
        elif pattern == "orbit":
            wps = self._orbit(cfg)
        elif pattern == "corridor":
            wps = self._corridor(cfg)
        elif pattern == "swarm":
            wps = self._swarm_attack(cfg)
        else:
            wps = self._direct(cfg)

        # Snap altitude to terrain + clearance
        clearance = cfg.get("clearance", 30)
        for wp in wps:
            ground = self.terrain.get_elevation(wp["lat"], wp["lon"])
            wp["alt"] = max(wp.get("alt", 50), ground + clearance)

        return {
            "pattern": pattern,
            "waypoints": wps,
            "drone_id": cfg.get("drone_id"),
        }

    # ── Pattern generators ───────────────────────────────────────────────────
    def _direct(self, cfg: dict) -> List[dict]:
        """Single takeoff → target flight."""
        origin = cfg.get("origin", {})
        target = cfg.get("target", {})
        alt = cfg.get("altitude", 50)
        return [
            {"lat": origin["lat"], "lon": origin["lon"], "alt": alt, "wp_type": "WAYPOINT"},
            {"lat": target["lat"], "lon": target["lon"], "alt": alt, "wp_type": "WAYPOINT"},
        ]

    def _grid_survey(self, cfg: dict) -> List[dict]:
        """Lawnmower grid over a bounding box."""
        bounds = cfg["bounds"]   # {n, s, e, w}
        alt     = cfg.get("altitude", 80)
        spacing = cfg.get("spacing", 0.001)  # degrees
        wps = []
        lat  = bounds["s"]
        col  = 0
        while lat <= bounds["n"]:
            if col % 2 == 0:
                lon_range = self._lon_range(bounds["w"], bounds["e"], spacing)
            else:
                lon_range = list(reversed(self._lon_range(bounds["w"], bounds["e"], spacing)))
            for lon in lon_range:
                wps.append({"lat": lat, "lon": lon, "alt": alt, "wp_type": "WAYPOINT"})
            lat += spacing
            col += 1
        return wps

    def _orbit(self, cfg: dict) -> List[dict]:
        """Circular orbit around a centre point."""
        c   = cfg["centre"]
        r_m = cfg.get("radius", 100)     # metres
        pts = cfg.get("points", 16)
        alt = cfg.get("altitude", 60)
        wps = []
        for i in range(pts + 1):
            angle = math.radians(i * 360 / pts)
            dlat = (r_m * math.cos(angle)) / 111320
            dlon = (r_m * math.sin(angle)) / (111320 * math.cos(math.radians(c["lat"])))
            wps.append({"lat": c["lat"] + dlat, "lon": c["lon"] + dlon, "alt": alt, "wp_type": "WAYPOINT"})
        return wps

    def _corridor(self, cfg: dict) -> List[dict]:
        """Follow a polyline with width offset passes."""
        line  = cfg["line"]   # list of {lat, lon}
        alt   = cfg.get("altitude", 50)
        return [{"lat": p["lat"], "lon": p["lon"], "alt": alt, "wp_type": "WAYPOINT"} for p in line]

    def _swarm_attack(self, cfg: dict) -> List[dict]:
        """
        Distribute N drones to converge on a target from different approach angles.
        Returns the WPs for one drone (drone_index).
        """
        origin = cfg["origin"]
        target = cfg["target"]
        n_drones = cfg.get("n_drones", 4)
        idx      = cfg.get("drone_index", 0)
        alt      = cfg.get("altitude", 60)
        spread_r = cfg.get("spread_radius", 0.005)  # deg

        angle = math.radians(idx * 360 / n_drones)
        stag_lat = origin["lat"] + spread_r * math.cos(angle)
        stag_lon = origin["lon"] + spread_r * math.sin(angle)

        return [
            {"lat": origin["lat"], "lon": origin["lon"], "alt": alt, "wp_type": "WAYPOINT"},
            {"lat": stag_lat,      "lon": stag_lon,      "alt": alt, "wp_type": "WAYPOINT"},
            {"lat": target["lat"], "lon": target["lon"], "alt": alt, "wp_type": "WAYPOINT"},
        ]

    @staticmethod
    def _lon_range(w, e, step):
        lons = []
        lon = w
        while lon <= e:
            lons.append(round(lon, 7))
            lon += step
        return lons