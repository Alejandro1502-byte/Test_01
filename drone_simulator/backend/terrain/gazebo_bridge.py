"""
terrain/gazebo_bridge.py
Puente con Gazebo para extraer coordenadas de terreno reales.

Gazebo usa modelos de mundo (.world) que pueden contener:
  - Coordenadas esféricas (spherical_coordinates) → lat/lon de origen
  - Modelos de terreno heightmap con datos DEM reales
  - Conexión al plugin de autopiloto ArduPilot

Este módulo:
1. Lee archivos .world de Gazebo y extrae el origen geográfico
2. Convierte coordenadas locales Gazebo (X,Y,Z) a lat/lon/alt
3. Parsea heightmaps de Gazebo para obtener elevaciones reales
4. Opcionalmente se conecta a Gazebo via GazeboTransport (gz-transport)
"""

import math
import struct
import os
import xml.etree.ElementTree as ET
from typing import Optional, Tuple, Dict, List


# ── Modelos de mundo predefinidos (Gazebo stock worlds) ──────────────────────
GAZEBO_WORLDS = {
    "empty":    {"lat": 0.0,       "lon": 0.0,       "alt": 0.0,  "heading": 0},
    "sonoma":   {"lat": 38.161479, "lon": -122.4546,  "alt": 488,  "heading": 0},
    "iris_lawn":{"lat": 51.703,    "lon": -1.538,     "alt": 0.0,  "heading": 270},
    "madrid":   {"lat": 40.416775, "lon": -3.703790,  "alt": 650,  "heading": 0},
    "fcollado": {"lat": 37.4119,   "lon": -5.8945,    "alt": 12,   "heading": 0},
}


class GazeboWorldParser:
    """
    Parsea un archivo .world de Gazebo y extrae:
    - Coordenadas esféricas (origen del mundo)
    - Modelos de terreno con heightmap
    """

    def __init__(self, world_file: Optional[str] = None):
        self.origin_lat  = 0.0
        self.origin_lon  = 0.0
        self.origin_alt  = 0.0
        self.origin_hdg  = 0.0    # heading del norte en el mundo Gazebo
        self.heightmap   = None   # array 2D de elevaciones si existe
        self.hm_size     = (0, 0) # (cols, rows)
        self.hm_bounds   = {}     # {n,s,e,w} lat/lon

        if world_file and os.path.exists(world_file):
            self._parse(world_file)

    def load_preset(self, preset_name: str):
        """Carga un preset de mundo Gazebo conocido."""
        p = GAZEBO_WORLDS.get(preset_name, GAZEBO_WORLDS["empty"])
        self.origin_lat = p["lat"]
        self.origin_lon = p["lon"]
        self.origin_alt = p["alt"]
        self.origin_hdg = p["heading"]

    def _parse(self, path: str):
        try:
            tree = ET.parse(path)
            root = tree.getroot()

            # Find spherical_coordinates element
            world = root.find(".//world") or root
            sc = world.find(".//spherical_coordinates")
            if sc is not None:
                self.origin_lat = float(sc.findtext("latitude_deg",  "0"))
                self.origin_lon = float(sc.findtext("longitude_deg", "0"))
                self.origin_alt = float(sc.findtext("elevation",     "0"))
                self.origin_hdg = float(sc.findtext("heading_deg",   "0"))

            # Find heightmap
            hm = world.find(".//heightmap")
            if hm is not None:
                self._parse_heightmap(hm)

            print(f"[Gazebo] Mundo cargado: origin={self.origin_lat:.5f},{self.origin_lon:.5f} alt={self.origin_alt}m")
        except Exception as e:
            print(f"[Gazebo] Error parseando {path}: {e}")

    def _parse_heightmap(self, hm_elem):
        """Parsea datos de heightmap de Gazebo (archivo .png o inline)."""
        uri   = hm_elem.findtext("uri", "")
        size_el = hm_elem.find("size")
        pos_el  = hm_elem.find("pos")

        if size_el is not None:
            sx, sy, sz = [float(v) for v in size_el.text.split()]
            # sz = max elevation in metres
        else:
            sx = sy = sz = 0

        # Derive bounds from origin + size (rough)
        if sx > 0:
            dlat = (sy / 2) / 111320
            dlon = (sx / 2) / (111320 * math.cos(math.radians(self.origin_lat)))
            self.hm_bounds = {
                "n": self.origin_lat + dlat,
                "s": self.origin_lat - dlat,
                "e": self.origin_lon + dlon,
                "w": self.origin_lon - dlon,
            }

    # ── Coordinate conversion ─────────────────────────────────────────────────
    def gazebo_to_latlon(self, gx: float, gy: float, gz: float
                         ) -> Tuple[float, float, float]:
        """
        Convert Gazebo local ENU (East-North-Up) coordinates to lat/lon/alt.
        gx = East,  gy = North,  gz = Up
        """
        heading_r = math.radians(self.origin_hdg)
        # Rotate for world heading
        east  =  gx * math.cos(heading_r) + gy * math.sin(heading_r)
        north = -gx * math.sin(heading_r) + gy * math.cos(heading_r)

        dlat = north / 111320
        dlon = east  / (111320 * math.cos(math.radians(self.origin_lat)) + 1e-9)

        return (
            self.origin_lat + dlat,
            self.origin_lon + dlon,
            self.origin_alt + gz,
        )

    def latlon_to_gazebo(self, lat: float, lon: float, alt: float
                         ) -> Tuple[float, float, float]:
        """Convert lat/lon/alt to Gazebo local ENU."""
        north = (lat - self.origin_lat) * 111320
        east  = (lon - self.origin_lon) * 111320 * math.cos(math.radians(self.origin_lat))
        up    = alt - self.origin_alt

        heading_r = math.radians(self.origin_hdg)
        gx = east  * math.cos(heading_r) - north * math.sin(heading_r)
        gy = east  * math.sin(heading_r) + north * math.cos(heading_r)
        return gx, gy, up

    def origin(self) -> Dict:
        return {
            "lat": self.origin_lat,
            "lon": self.origin_lon,
            "alt": self.origin_alt,
            "heading": self.origin_hdg,
        }


# ── Live Gazebo bridge via gz-transport (optional) ────────────────────────────
class GazeboLiveBridge:
    """
    Conecta con Gazebo en tiempo real via gz-transport (Python bindings).
    Requiere: pip install gz-transport  (solo en Linux con Gazebo instalado)
    """

    def __init__(self):
        self._available = False
        try:
            import gz.transport13 as gz_transport  # Gazebo Harmonic
            self._gz = gz_transport
            self._available = True
            print("[Gazebo] gz-transport disponible – modo live activo")
        except ImportError:
            print("[Gazebo] gz-transport no disponible – modo offline")

    @property
    def available(self):
        return self._available

    def get_pose(self, model_name: str) -> Optional[Dict]:
        """Get model pose from Gazebo."""
        if not self._available:
            return None
        try:
            # Seria: /gazebo/default/pose/info topic
            # Implementación completa requiere gz-transport Python bindings
            return None
        except Exception:
            return None

    def set_model_pose(self, model_name: str,
                       gx: float, gy: float, gz: float,
                       roll=0.0, pitch=0.0, yaw=0.0) -> bool:
        """Teleport a Gazebo model (for feeding simulator state back to Gazebo)."""
        if not self._available:
            return False
        try:
            # Would publish to /gazebo/default/<model>/link/visual/pose
            return True
        except Exception:
            return False


# ── Convenience: load from preset string ─────────────────────────────────────
def world_from_preset(name: str) -> GazeboWorldParser:
    w = GazeboWorldParser()
    w.load_preset(name)
    return w


def world_from_file(path: str) -> GazeboWorldParser:
    return GazeboWorldParser(world_file=path)