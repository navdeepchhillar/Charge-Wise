"""Where station data comes from.

  synthetic (default)  the deterministic network in data.py: works offline, used by the ride simulator.
  real                 real stations around the given point:
                         * OpenStreetMap via the Overpass API: free, no key, worldwide
                           (amenity=charging_station with socket / power / opening-hours tags);
                         * plus Open Charge Map when OCM_API_KEY is set (merged; duplicates within 60 m dropped).
                       Cached per ~5 km area for 30 minutes (Overpass is slow: 5-30 s on a cold query).
                       Any failure falls back to synthetic stations with a warning, so the app never breaks.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Dict, List, Optional, Tuple

from . import data
from .geo import haversine_km

UA = "chargewise/2.0 (EV charging demo)"
CACHE_TTL_S = 1800
TILE_DEG = 0.05                    # ~5.5 km cache tiles
FETCH_RADIUS_KM = 15               # each tile fetches stations within this radius of its centre
FAIL_TTL_S = 60                    # after a failure, don't retry the same area for a minute
OVERPASS_URLS = [u for u in os.environ.get(
    "OVERPASS_URLS", "https://maps.mail.ru/osm/tools/overpass/api/interpreter,https://overpass-api.de/api/interpreter,"
                     "https://overpass.private.coffee/api/interpreter").split(",") if u]
OVERPASS_TIMEOUT_S = float(os.environ.get("OVERPASS_TIMEOUT_S", "25"))
OCM_URL = "https://api.openchargemap.io/v3/poi/"

_cache: Dict[Tuple, Tuple[float, object]] = {}
_lock = threading.Lock()


def ocm_enabled() -> bool:
    return bool(os.environ.get("OCM_API_KEY"))


def _http_json(url: str, body: Optional[bytes] = None, timeout: float = 6.0):
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── OpenStreetMap (Overpass) ─────────────────────────────────────────────
OSM_SOCKETS = {"type2_combo": "CCS2", "type2": "Type 2", "type2_cable": "Type 2", "chademo": "CHAdeMO",
               "type1_combo": "CCS1", "type1": "Type 1", "tesla_supercharger": "Tesla", "gb_dc": "GB/T DC",
               "gb_ac": "GB/T AC"}
# networks / station types that serve only 2- and 3-wheelers or swap batteries (very common in Indian OSM data)
TWO_WHEELER = re.compile(r"\b(ather|ola|bounce|yulu|battery\s*smart|sun\s*mobility|gogoro|e:?\s*swap|swap|"
                         r"swapping|battery\s*station|two[- ]?wheeler|2w|e-?rickshaw|scooter|bike)\b", re.I)
_KW = re.compile(r"([\d.]+)\s*(kw|w)?", re.I)


def _power_kw(value: str) -> Optional[float]:
    best = None
    for num, unit in _KW.findall(value or ""):
        try:
            kw = float(num) / (1000 if (unit or "").lower() == "w" else 1)
        except ValueError:
            continue
        if 1 <= kw <= 500:
            best = max(best or 0, kw)
    return best


def map_osm(el: Dict) -> Optional[Dict]:
    tags = el.get("tags") or {}
    lat = el.get("lat", (el.get("center") or {}).get("lat"))
    lng = el.get("lon", (el.get("center") or {}).get("lon"))
    if lat is None or lng is None:
        return None
    # skip chargers that are only for 2/3-wheelers (very common in India), or disused ones
    if tags.get("motorcar") == "no" or (tags.get("motorcar") != "yes" and any(
            tags.get(k) == "yes" for k in ("bicycle", "scooter", "motorcycle")) and not any(
            k.startswith("socket:type2") or k.startswith("socket:chademo") for k in tags)):
        return None
    label = " ".join(tags.get(k, "") for k in ("name", "brand", "operator", "network"))
    if TWO_WHEELER.search(label) and tags.get("motorcar") != "yes":
        return None
    if any(k.startswith(("disused:", "abandoned:")) for k in tags) or tags.get("operational_status") in ("closed", "broken"):
        return None
    connectors, powers, count = set(), [], 0
    for key, val in tags.items():
        m = re.fullmatch(r"socket:([a-z0-9_]+)(:output)?", key)
        if not m or m.group(1) not in OSM_SOCKETS:
            continue
        if m.group(2):
            p = _power_kw(val)
            if p:
                powers.append(p)
        else:
            connectors.add(OSM_SOCKETS[m.group(1)])
            if val.isdigit():
                count += int(val)
    power = max(powers) if powers else _power_kw(tags.get("charging_station:output") or tags.get("maxpower") or "")
    power_assumed = False
    if power is None and connectors & {"CCS2", "CHAdeMO", "CCS1", "Tesla", "GB/T DC"}:
        power, power_assumed = 30.0, True                # DC socket without a stated output: assume a modest DC
    elif power is None and connectors:
        power, power_assumed = 7.4, True                 # AC socket without a stated output: assume a typical wallbox
    access = tags.get("access", "yes")
    hours_raw = tags.get("opening_hours")
    name = tags.get("name") or tags.get("brand") or tags.get("operator") or "EV charging station"
    return {
        "id": f"osm-{el.get('type', 'n')[0]}{el.get('id')}", "name": name,
        "area": tags.get("addr:suburb") or tags.get("addr:city") or tags.get("addr:street") or "",
        "operator": tags.get("operator") or tags.get("brand") or tags.get("network") or "Unknown operator",
        "lat": lat, "lng": lng, "power_kw": power, "connectors": sorted(connectors),
        "count": int(tags["capacity"]) if str(tags.get("capacity", "")).isdigit() else (count or None),
        "price_per_kwh": None, "access": "private" if access in ("private", "no") else "public",
        "status": "unknown" if tags.get("fixme") else "operational",
        "category": 2 if (power or 0) >= 100 else 1 if (power or 0) >= 25 else 0,
        "hours": "24x7" if (hours_raw in (None, "24/7")) else "unknown", "hours_raw": hours_raw,
        "uptime": 0.9, "amenities": [], "road": "city", "source": "openstreetmap", "power_assumed": power_assumed,
    }


def osm_stations(lat: float, lng: float) -> List[Dict]:
    """Ask every Overpass mirror at once and take the first good answer (public mirrors are often slow)."""
    q = (f'[out:json][timeout:{int(OVERPASS_TIMEOUT_S)}];'
         f'nwr["amenity"="charging_station"](around:{FETCH_RADIUS_KM * 1000},{lat},{lng});out center tags;')
    body = urllib.parse.urlencode({"data": q}).encode()
    pool = ThreadPoolExecutor(max_workers=len(OVERPASS_URLS))
    try:
        pending = {pool.submit(_http_json, url, body, OVERPASS_TIMEOUT_S) for url in OVERPASS_URLS}
        deadline, last = time.monotonic() + OVERPASS_TIMEOUT_S, None
        while pending:
            done, pending = wait(pending, timeout=max(0.0, deadline - time.monotonic()), return_when=FIRST_COMPLETED)
            if not done:
                break
            for f in done:
                try:
                    els = f.result().get("elements", [])
                    return [s for s in (map_osm(e) for e in els) if s]
                except Exception as e:  # noqa: BLE001 - wait for another mirror
                    last = e
        raise last or TimeoutError("Overpass timed out")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ── Open Charge Map (optional, needs a key) ───────────────────────────────
OCM_CONNECTORS = {33: "CCS2", 32: "CCS1", 2: "CHAdeMO", 25: "Type 2", 1036: "Type 2", 30: "Tesla", 1: "Type 1",
                  28: "Type 2", 27: "Tesla"}


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
    return {
        "id": f"ocm-{poi.get('ID')}", "name": addr.get("Title") or "Charging station", "area": addr.get("Town") or "",
        "operator": (poi.get("OperatorInfo") or {}).get("Title") or "Unknown operator", "lat": lat, "lng": lng,
        "power_kw": power, "connectors": names, "count": count, "price_per_kwh": None,
        "access": "private" if private else "public", "status": status,
        "category": 2 if (power or 0) >= 100 else 1 if (power or 0) >= 25 else 0, "hours": "24x7", "hours_raw": None,
        "uptime": 0.92 if status == "operational" else 0.75, "amenities": [], "road": "city", "source": "openchargemap",
    }


def ocm_stations(lat: float, lng: float) -> List[Dict]:
    q = urllib.parse.urlencode({"output": "json", "latitude": lat, "longitude": lng, "distance": FETCH_RADIUS_KM,
                                "distanceunit": "KM", "maxresults": 200, "compact": "true", "verbose": "false",
                                "key": os.environ["OCM_API_KEY"]})
    return [s for s in (map_ocm(p) for p in _http_json(OCM_URL + "?" + q)) if s]


def _merge(primary: List[Dict], extra: List[Dict]) -> List[Dict]:
    out = list(primary)
    for s in extra:
        if all(haversine_km((s["lat"], s["lng"]), (o["lat"], o["lng"])) > 0.06 for o in out):
            out.append(s)
    return out


def real_stations(lat: float, lng: float) -> Tuple[List[Dict], List[str]]:
    """Stations for the cache tile containing (lat, lng). Returns (stations, provider names)."""
    tile = (round(lat / TILE_DEG), round(lng / TILE_DEG))
    now = time.time()
    with _lock:
        hit = _cache.get(tile)
        if hit and isinstance(hit[1], Exception) and now - hit[0] < FAIL_TTL_S:
            raise hit[1]
        if hit and not isinstance(hit[1], Exception) and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    clat, clng = tile[0] * TILE_DEG, tile[1] * TILE_DEG
    stations, used, errors = [], [], []
    if ocm_enabled():
        try:
            stations = ocm_stations(clat, clng); used.append("Open Charge Map")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    try:
        stations = _merge(stations, osm_stations(clat, clng)); used.append("OpenStreetMap")
    except Exception as e:  # noqa: BLE001
        errors.append(e)
    if not used:
        with _lock:
            _cache[tile] = (now, errors[-1])
        raise errors[-1]
    result = (stations, used)
    with _lock:
        _cache[tile] = (now, result)
    return result


def stations_for(source: str, lat: float, lng: float, radius_km: float) -> Tuple[List[Dict], str, Optional[str]]:
    """(stations, source label actually used, warning or None)."""
    if source in ("real", "ocm"):
        try:
            found, used = real_stations(lat, lng)
            return found, " + ".join(used), None
        except Exception as e:  # noqa: BLE001 - any network/API failure falls back
            return (data.stations(), "synthetic",
                    f"Real station data unavailable right now ({type(e).__name__}); showing synthetic stations.")
    return data.stations(), "synthetic", None
