"""
geo.py
------
Distance maths (haversine, no API needed) and best-effort geocoding.
Geocoding uses the free OSM Nominatim endpoint at runtime; if the network
is blocked it falls back to the lat/lng baked into seed_suburbs.
"""
from __future__ import annotations
import math
import time
from typing import Optional, Tuple

import requests


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 2)


def geocode(query: str, timeout: int = 8) -> Optional[Tuple[float, float]]:
    """Free OSM geocode. Returns (lat, lng) or None. Be polite: 1 req/sec."""
    try:
        time.sleep(1.0)
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{query}, Victoria, Australia", "format": "json", "limit": 1},
            headers={"User-Agent": "childcare-acquisition-intel/0.1 (MVP)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None
