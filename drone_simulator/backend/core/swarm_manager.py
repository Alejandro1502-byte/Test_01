"""
core/swarm_manager.py – manages all active drones
"""
from typing import Dict, List, Optional
from core.drone import Drone


class SwarmManager:
    def __init__(self):
        self._drones: Dict[str, Drone] = {}

    def add_drone(self, cfg: dict) -> Drone:
        d = Drone(
            lat=cfg.get("lat", 40.416775),
            lon=cfg.get("lon", -3.703790),
            alt=cfg.get("alt", 0),
            name=cfg.get("name", f"UAV-{len(self._drones)+1:02d}"),
            color=cfg.get("color", "#00ff88"),
        )
        if cfg.get("home"):
            d.rtl_home = cfg["home"]
        d.armed = cfg.get("armed", False)
        self._drones[d.id] = d
        return d

    def remove_drone(self, drone_id: str):
        self._drones.pop(drone_id, None)

    def get(self, drone_id: str) -> Optional[Drone]:
        return self._drones.get(drone_id)

    def all_drones(self) -> List[Drone]:
        return list(self._drones.values())

    def serialize_all(self) -> List[dict]:
        return [d.serialize() for d in self._drones.values()]

    def reset(self):
        self._drones.clear()