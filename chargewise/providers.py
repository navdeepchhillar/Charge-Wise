"""Where station data comes from.

  synthetic  (default)  the deterministic network in data.py: works offline, used by the ride simulator.
  ocm                   real stations from Open Charge Map (https://openchargemap.org) near a point, when the
                        OCM_API_KEY environment variable is set. Cached for 10 minutes per ~1 km area so a
                        moving car doesn't hit the API on every update. Falls back to synthetic on any error.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from . import data

OCM_URL = "https://api.openchargemap.io/v3/poi/"
CACHE_TTL_S = 600
_cache: Dict[Tuple, Tuple[float, List[Dict]]] = {}
_lock = threading.Lock()

# Open Charge Map ConnectionTypeID → our connector names
OCM_CONNECTORS = {33: "CCS2", 32: "CCS1", 2: "CHAdeMO", 25: "Type 2", 1036: "Type 2", 30: "Tesla", 1: "Type 1",
                  28: "Type 2", 27: "Tesla"}


def ocm_enabled() -> bool:
    return bool(os.environ.get("OCM_API_KEY"))


def _fetch_json(url: str, timeout: float = 6.0):
    req = urllib.request.Request(url, headers={"User-Agent": "chargewise/2.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def map_ocm(poi: Dict) -> Optional[Dict]:
    addr = poi.get("AddressInfo") or {}
    lat, lng = addr.get("Latitude"), addr.get("Longitude")
    if lat is None or lng is None:
        return None
    conns = poi.get("Connections") or []
    names = sorted({OCM_CONNECTORS[c["ConnectionTypeID"]] for c in conns if c.get("ConnectionTypeID") in OCM_CONNECTORS})
    power = max([c.get("PowerKW") or 0 for c in conns] or [0]) or None
    count = poi.get("NumberOfPoints") or sum(int(c.get("Quantity") or 1) for c in conns) or None
    st = poi.get("StatusType") or {}
    status = "operational" if st.get("IsOperational") is True else "offline" if st.get("IsOperational") is False else "unknown"
    usage = poi.get("UsageType") or {}
    private = usage.get("ID") in (2, 6) or "private" in (usage.get("Title") or "").lower()
    op = (poi.get("OperatorInfo") or {}).get("Title") or "Unknown operator"
    return {
        "id": f"ocm-{poi.get('ID')}", "name": addr.get("Title") or "Charging station", "area": addr.get("Town") or "",
        "operator": op, "lat": lat, "lng": lng, "power_kw": power, "connectors": names, "count": count,
        "price_per_kwh": None, "access": "private" if private else "public", "status": status,
        "category": 2 if (power or 0) >= 100 else 1 if (power or 0) >= 25 else 0, "hours": "24x7",
        "uptime": 0.92 if status == "operational" else 0.75, "amenities": [], "road": "city", "source": "openchargemap",
    }


def ocm_stations(lat: float, lng: float, radius_km: float) -> List[Dict]:
    key = (round(lat, 2), round(lng, 2), int(radius_km))
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    q = urllib.parse.urlencode({"output": "json", "latitude": lat, "longitude": lng, "distance": radius_km,
                                "distanceunit": "KM", "maxresults": 150, "compact": "true", "verbose": "false",
                                "key": os.environ["OCM_API_KEY"]})
    out = [s for s in (map_ocm(p) for p in _fetch_json(OCM_URL + "?" + q)) if s]
    with _lock:
        _cache[key] = (now, out)
    return out


def stations_for(source: str, lat: float, lng: float, radius_km: float) -> Tuple[List[Dict], str, Optional[str]]:
    """(stations, source actually used, warning)."""
    if source == "ocm":
        if not ocm_enabled():
            return data.stations(), "synthetic", "Real station data is off (no OCM_API_KEY on the server); showing synthetic stations."
        try:
            return ocm_stations(lat, lng, radius_km), "ocm", None
        except Exception as e:  # noqa: BLE001 - any network/API failure falls back
            return data.stations(), "synthetic", f"Open Charge Map unavailable ({type(e).__name__}); showing synthetic stations."
    return data.stations(), "synthetic", None
