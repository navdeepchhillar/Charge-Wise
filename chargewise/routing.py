"""Real road distance and drive time (OSRM), for the few stations that matter.

One OSRM `table` request gives road km and free-flow minutes from the car to up to N stations. Used for the
nearest candidates in live mode; everything else (and any failure) uses the straight-line x road-factor
estimate. Results are cached per ~100 m car position for 2 minutes, so a moving car makes at most one call
every few seconds. Set OSRM_URL to your own server for production (the public demo server is rate-limited).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Dict, Optional, Sequence, Tuple

OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_TIMEOUT_S = float(os.environ.get("OSRM_TIMEOUT_S", "4"))
MAX_DESTINATIONS = 12
CACHE_TTL_S = 120
_cache: Dict[Tuple, Tuple[float, Dict[str, Tuple[float, float]]]] = {}
_lock = threading.Lock()


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "chargewise/2.0 (EV charging demo)"})
    with urllib.request.urlopen(req, timeout=OSRM_TIMEOUT_S) as r:
        return json.loads(r.read().decode())


def road_table(origin: Tuple[float, float], stations: Sequence[Dict]) -> Tuple[Dict[str, Tuple[float, float]], Optional[str]]:
    """{station id: (road km, free-flow minutes)} for up to MAX_DESTINATIONS stations, plus a warning or None."""
    stations = list(stations)[:MAX_DESTINATIONS]
    if not stations:
        return {}, None
    key = (round(origin[0], 3), round(origin[1], 3), tuple(s["id"] for s in stations))
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1], None
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in [origin] + [(s["lat"], s["lng"]) for s in stations])
    try:
        j = _fetch(f"{OSRM_URL}/table/v1/driving/{coords}?sources=0&annotations=distance,duration")
        if j.get("code") != "Ok":
            raise ValueError(j.get("code"))
        out: Dict[str, Tuple[float, float]] = {}
        for s, dist, dur in zip(stations, j["distances"][0][1:], j["durations"][0][1:]):
            if dist is not None and dur is not None:
                out[s["id"]] = (dist / 1000, dur / 60)
    except Exception as e:  # noqa: BLE001 - fall back to estimates
        return {}, f"Road routing unavailable ({type(e).__name__}); distances are estimates."
    with _lock:
        _cache[key] = (now, out)
    return out, None
