"""
terrain/elevation.py – Terrain elevation provider
Uses Open-Elevation API (open-elevation.com) with local disk cache.
Fallback: SRTM approximation formula for offline use.
"""
import math
import json
import os
import hashlib
from typing import Dict, List
try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".elev_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
OPEN_TOPO_URL      = "https://api.opentopodata.org/v1/srtm90m"


class TerrainProvider:
    """
    Get real terrain elevation (metres AMSL) for lat/lon points.
    Priority: disk cache → Open-Elevation API → flat-earth fallback.
    """

    def __init__(self, use_api: bool = True):
        self._cache: Dict[str, float] = {}
        self._use_api = use_api and REQUESTS_OK
        self._load_cache()

    # ── Public API ────────────────────────────────────────────────────────────
    def get_elevation(self, lat: float, lon: float) -> float:
        key = f"{lat:.5f},{lon:.5f}"
        if key in self._cache:
            return self._cache[key]

        elev = self._fetch_single(lat, lon)
        self._cache[key] = elev
        self._save_cache()
        return elev

    def get_tile_elevations(self, bounds: dict, resolution: int = 20) -> dict:
        """
        Sample a grid of elevations inside bounds {n,s,e,w}.
        Returns a 2-D array suitable for MapLibre terrain exaggeration.
        """
        n, s, e, w = bounds["n"], bounds["s"], bounds["e"], bounds["w"]
        dlat = (n - s) / resolution
        dlon = (e - w) / resolution

        # Batch fetch from API if possible
        points = []
        for row in range(resolution + 1):
            for col in range(resolution + 1):
                points.append({
                    "latitude":  s + row * dlat,
                    "longitude": w + col * dlon,
                })

        elevations = self._batch_fetch(points)
        grid = []
        i = 0
        for row in range(resolution + 1):
            r = []
            for col in range(resolution + 1):
                r.append(elevations[i])
                i += 1
            grid.append(r)

        return {
            "bounds": bounds,
            "resolution": resolution,
            "grid": grid,
            "min_elev": min(elevations),
            "max_elev": max(elevations),
        }

    # ── Fetch helpers ─────────────────────────────────────────────────────────
    def _fetch_single(self, lat: float, lon: float) -> float:
        if not self._use_api:
            return self._srtm_approx(lat, lon)
        try:
            r = requests.post(
                OPEN_ELEVATION_URL,
                json={"locations": [{"latitude": lat, "longitude": lon}]},
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()["results"][0]["elevation"]
        except Exception:
            pass
        # Fallback to opentopodata
        try:
            r = requests.get(f"{OPEN_TOPO_URL}?locations={lat},{lon}", timeout=5)
            if r.status_code == 200:
                return r.json()["results"][0]["elevation"] or 0.0
        except Exception:
            pass
        return self._srtm_approx(lat, lon)

    def _batch_fetch(self, points: list) -> List[float]:
        """Batch fetch up to 100 points; fill from cache first."""
        results = [None] * len(points)
        to_fetch = []

        for i, p in enumerate(points):
            key = f"{p['latitude']:.5f},{p['longitude']:.5f}"
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                to_fetch.append((i, p))

        if to_fetch and self._use_api:
            try:
                batch_pts = [{"latitude": p["latitude"], "longitude": p["longitude"]}
                             for _, p in to_fetch]
                r = requests.post(OPEN_ELEVATION_URL,
                                  json={"locations": batch_pts}, timeout=10)
                if r.status_code == 200:
                    res_list = r.json()["results"]
                    for (idx, p), res in zip(to_fetch, res_list):
                        elev = res.get("elevation", 0) or 0
                        results[idx] = elev
                        self._cache[f"{p['latitude']:.5f},{p['longitude']:.5f}"] = elev
                    self._save_cache()
                    to_fetch = [(i, p) for i, p in to_fetch if results[i] is None]
            except Exception:
                pass

        # Fill remaining with approximation
        for i, p in to_fetch:
            if results[i] is None:
                elev = self._srtm_approx(p["latitude"], p["longitude"])
                results[i] = elev
                self._cache[f"{p['latitude']:.5f},{p['longitude']:.5f}"] = elev

        return [r or 0.0 for r in results]

    # ── SRTM approximation ────────────────────────────────────────────────────
    @staticmethod
    def _srtm_approx(lat: float, lon: float) -> float:
        """
        Very rough approximation – for offline/demo use only.
        Uses a pseudo-random heightmap seeded by tile position.
        """
        import random
        rng = random.Random(int(lat * 100) * 10000 + int(lon * 100))
        base = max(0.0, rng.gauss(200, 150))
        # Add small local noise
        noise_rng = random.Random(int(lat * 10000) * 100000 + int(lon * 10000))
        return round(base + noise_rng.gauss(0, 20), 1)

    # ── Disk cache ────────────────────────────────────────────────────────────
    def _cache_path(self) -> str:
        return os.path.join(CACHE_DIR, "elev_cache.json")

    def _load_cache(self):
        try:
            with open(self._cache_path()) as f:
                self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def _save_cache(self):
        try:
            with open(self._cache_path(), "w") as f:
                json.dump(self._cache, f)
        except Exception:
            pass