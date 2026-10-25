"""Nearest Australian locality to a point.

Mobile and home-based businesses (half the tradies) have no street address on
Google Maps, only a pin. ``nearest(lat, lng)`` turns that pin into "Dubbo NSW
2830" plus a sales region, from ``data/au_localities.csv`` (every gazetted
suburb and town: name, state, postcode, centre point, population, region).
"""

from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA = Path(__file__).resolve().parent.parent / "data" / "au_localities.csv"
CELL = 0.1  # degrees; ~10 km buckets

# Mainland + Tasmania + the near islands. Results outside are not Australian.
AU_BOUNDS = (-44.5, -9.0, 112.0, 154.5)  # lat_min, lat_max, lng_min, lng_max


def in_australia(lat: Optional[float], lng: Optional[float]) -> bool:
    if lat is None or lng is None:
        return True  # unknown: let the address / phone checks decide
    return AU_BOUNDS[0] <= lat <= AU_BOUNDS[1] and AU_BOUNDS[2] <= lng <= AU_BOUNDS[3]


def _cell(lat: float, lng: float) -> Tuple[int, int]:
    return int(math.floor(lat / CELL)), int(math.floor(lng / CELL))


@lru_cache(maxsize=1)
def _index() -> Dict[Tuple[int, int], List[dict]]:
    grid: Dict[Tuple[int, int], List[dict]] = {}
    if not DATA.exists():
        return grid
    with DATA.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                lat, lng = float(row["lat"]), float(row["lng"])
            except (KeyError, ValueError):
                continue
            row["lat"], row["lng"] = lat, lng
            row["population"] = int(float(row.get("population") or 0))
            # A town of 5,000 two km further away is a better label than a
            # hamlet of 40 people: bigger places get up to 2 km head start.
            row["bonus"] = min(2.0, math.log10(max(1, row["population"])) * 0.5)
            grid.setdefault(_cell(lat, lng), []).append(row)
    return grid


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def nearest(lat: float, lng: float, max_km: float = 60.0) -> Optional[dict]:
    """→ {"locality", "state", "postcode", "region", "km"} or None."""
    grid = _index()
    if not grid or not in_australia(lat, lng):
        return None
    cy, cx = _cell(lat, lng)
    kx = math.cos(math.radians(lat)) * 111.32  # km per degree of longitude here

    def scan(radius: int) -> Tuple[Optional[dict], float]:
        best, best_d = None, max_km
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                for row in grid.get((cy + dy, cx + dx), ()):
                    # Flat-earth distance is exact enough at these scales, and fast.
                    d = math.hypot((row["lat"] - lat) * 110.57, (row["lng"] - lng) * kx) - row["bonus"]
                    if d < best_d:
                        best, best_d = row, d
        return best, best_d

    # The 3x3 block reaches at least 8 km every way, so a winner under 6 km
    # (8 minus the size head start) can't be beaten from outside it.
    best, d = scan(1)
    if best is None or d > 6.0:
        best, d = scan(int(max_km / (CELL * kx)) + 1)
    if not best:
        return None
    return {"locality": best["locality"], "state": best["state"], "postcode": best["postcode"],
            "region": best.get("region", ""), "km": round(km(lat, lng, best["lat"], best["lng"]), 1)}
