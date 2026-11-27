"""The synthetic world: ride routes, vehicle profiles and the charging-station network.

Everything here is synthetic and deterministic (fixed seeds), so every run, test and deployment sees
exactly the same world. Station names and operators are fictional; routes are illustrative straight-ish
lines between real place coordinates, not road navigation.
"""
from __future__ import annotations

import json
import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from .geo import Polyline, haversine_km, offset

ROOT = Path(__file__).resolve().parents[1]

# ── Routes ──────────────────────────────────────────────────────────────────────
# (name, lat, lng, road kind of the leg that STARTS here: "city" or "highway")
ROUTES: Dict[str, Dict] = {
    "city-commute": {
        "name": "City commute: MG Road → Electronic City",
        "waypoints": [("MG Road", 12.9756, 77.6066, "city"), ("Richmond Circle", 12.9634, 77.5970, "city"),
                      ("Koramangala", 12.9352, 77.6245, "city"), ("Silk Board", 12.9177, 77.6233, "city"),
                      ("HSR Layout", 12.9116, 77.6474, "city"), ("Bommanahalli", 12.8996, 77.6180, "city"),
                      ("Electronic City", 12.8452, 77.6602, "city")],
    },
    "airport-run": {
        "name": "Airport run: Cubbon Park → Kempegowda Airport",
        "waypoints": [("Cubbon Park", 12.9763, 77.5929, "city"), ("Mekhri Circle", 13.0141, 77.5840, "city"),
                      ("Hebbal", 13.0358, 77.5970, "highway"), ("Yelahanka", 13.1007, 77.5963, "highway"),
                      ("Bettahalasuru", 13.1580, 77.6290, "highway"), ("Kempegowda Airport", 13.1989, 77.7068, "highway")],
    },
    "whitefield": {
        "name": "Tech corridor: Indiranagar → Whitefield",
        "waypoints": [("Indiranagar", 12.9719, 77.6412, "city"), ("Domlur", 12.9610, 77.6387, "city"),
                      ("Marathahalli", 12.9592, 77.6974, "city"), ("Brookefield", 12.9654, 77.7187, "city"),
                      ("Whitefield", 12.9698, 77.7500, "city")],
    },
    "mysuru-highway": {
        "name": "Highway: Bengaluru → Mysuru (~125 km)",
        "waypoints": [("Nayandahalli", 12.9443, 77.5240, "city"), ("Kengeri", 12.9081, 77.4826, "highway"),
                      ("Bidadi", 12.7975, 77.3889, "highway"), ("Ramanagara", 12.7209, 77.2799, "highway"),
                      ("Channapatna", 12.6518, 77.2085, "highway"), ("Maddur", 12.5843, 77.0434, "highway"),
                      ("Mandya", 12.5218, 76.8951, "highway"), ("Srirangapatna", 12.4237, 76.6815, "highway"),
                      ("Mysuru", 12.2958, 76.6394, "city")],
    },
}
SPEED_KMH = {"city": 28.0, "highway": 78.0}     # average cruise speed per road kind (synthetic traffic varies it)
ROAD_FACTOR = {"city": 1.32, "highway": 1.12}   # road km per straight-line km


def _densify(waypoints) -> tuple:
    """~0.4 km steps with a gentle deterministic wiggle so the car follows a road-like line."""
    pts, kinds = [], []
    for (n1, la1, ln1, kind), (_, la2, ln2, _k) in zip(waypoints, waypoints[1:]):
        seg = haversine_km((la1, ln1), (la2, ln2))
        steps = max(2, int(seg / 0.4))
        for s in range(steps):
            f = s / steps
            wiggle_km = math.sin(f * math.pi * 3) * min(0.25, seg * 0.015) * (1 if kind == "city" else 0.4)
            # unit vector perpendicular to the leg, in (lat, lng) degrees; a sub-km wiggle along it
            plat, plng = -(ln2 - ln1), (la2 - la1)
            norm = math.hypot(plat, plng) or 1.0
            base = (la1 + (la2 - la1) * f, ln1 + (ln2 - ln1) * f)
            pts.append((base[0] + plat / norm * wiggle_km / 111.0, base[1] + plng / norm * wiggle_km / 111.0))
            kinds.append(kind)
    last = waypoints[-1]
    pts.append((last[1], last[2]))
    kinds.append(kinds[-1])
    return pts, kinds


@lru_cache(maxsize=None)
def route(route_id: str) -> Dict:
    if route_id not in ROUTES:
        raise KeyError(route_id)
    spec = ROUTES[route_id]
    pts, kinds = _densify(spec["waypoints"])
    line = Polyline(pts)
    return {"id": route_id, "name": spec["name"], "line": line, "kinds": kinds,
            "waypoints": [{"name": n, "lat": la, "lng": ln} for n, la, ln, _ in spec["waypoints"]]}


def route_public(route_id: str) -> Dict:
    r = route(route_id)
    return {"id": r["id"], "name": r["name"], "length_km": round(r["line"].length_km, 1),
            "waypoints": r["waypoints"], "path": [[round(a, 5), round(b, 5)] for a, b in r["line"].points]}


def kind_at(route_id: str, d_km: float) -> str:
    r = route(route_id)
    from bisect import bisect_right
    i = min(max(bisect_right(r["line"].cum, d_km) - 1, 0), len(r["kinds"]) - 1)
    return r["kinds"][i]


# ── Vehicles (approximate public specs; consumption is a typical real-world figure) ───────────
VEHICLES: Dict[str, Dict] = {
    "nexon-ev": {"name": "Tata Nexon EV (LR)", "battery_kwh": 40.5, "wh_per_km": 145, "connectors": ["CCS2", "Type 2"],
                 "max_ac_kw": 7.2, "max_dc_kw": 50},
    "mg-zs-ev": {"name": "MG ZS EV", "battery_kwh": 50.3, "wh_per_km": 160, "connectors": ["CCS2", "Type 2"],
                 "max_ac_kw": 7.4, "max_dc_kw": 76},
    "ioniq-5": {"name": "Hyundai Ioniq 5", "battery_kwh": 72.6, "wh_per_km": 170, "connectors": ["CCS2", "Type 2"],
                "max_ac_kw": 11, "max_dc_kw": 220},
    "byd-atto-3": {"name": "BYD Atto 3", "battery_kwh": 60.5, "wh_per_km": 155, "connectors": ["CCS2", "Type 2"],
                   "max_ac_kw": 7, "max_dc_kw": 80},
}

# ── Stations ─────────────────────────────────────────────────────────────────────
OPERATORS = ["VoltPoint", "GreenGrid", "ChargeHub", "AmpLane", "SparkWay", "EcoCharge"]
SUFFIX_CITY = ["EV Hub", "Mall Parking", "Tech Park Chargers", "Metro Station Lot", "Fuel Plaza", "Hotel Chargers"]
SUFFIX_HWY = ["Highway Plaza", "Food Court Chargers", "Expressway Hub", "Toll Plaza Lot", "Dhaba Chargers"]
AMENITIES = ["Restroom", "Café", "Wi-Fi", "Food court", "Shopping", "Parking", "24×7 security"]


def _fixture_stations() -> List[Dict]:
    out = []
    for s in json.loads((ROOT / "data" / "stations.json").read_text()):
        out.append({
            "id": s["id"], "name": s["name"], "area": s.get("area", ""), "operator": "Demo fixture",
            "lat": s["lat"], "lng": s["lng"], "power_kw": s.get("power"),
            "connectors": [s["connector"]] if s.get("connector") and s["connector"] != "Unknown" else [],
            "count": s.get("count"), "price_per_kwh": s.get("price"), "access": s.get("access", "public"),
            "status": s.get("status", "operational"), "category": s.get("category", 0),
            "hours": "closed-now" if s.get("closed") else "24x7", "uptime": 0.95 if s.get("status") == "operational" else 0.8,
            "amenities": ["Parking"], "road": "city", "source": "original fixture",
        })
    return out


def _generated_stations() -> List[Dict]:
    out, n = [], 0
    for route_id, spec in ROUTES.items():
        rnd = random.Random(f"stations-{route_id}")
        r = route(route_id)
        line = r["line"]
        d = 2.5
        while d < line.length_km - 1:
            kind = kind_at(route_id, d)
            (lat, lng), heading = line.point_at(d)
            side = rnd.choice([-1, 1])
            lateral = rnd.uniform(0.15, 2.2 if kind == "city" else 1.2)
            h = math.radians(heading + 90 * side)
            lat, lng = offset((lat, lng), lateral * math.cos(h), lateral * math.sin(h))
            near = min(r["waypoints"], key=lambda w: haversine_km((w["lat"], w["lng"]), (lat, lng)))["name"]
            hwy = kind == "highway"
            power = rnd.choice([30, 60, 60, 120, 150] if hwy else [7.4, 22, 22, 30, 60, 120])
            dc = power >= 25
            connectors = (["CCS2"] + (["CHAdeMO"] if rnd.random() < 0.2 else []) + (["Type 2"] if rnd.random() < 0.4 else [])) if dc else ["Type 2"]
            if dc and rnd.random() < 0.1:
                connectors = ["CHAdeMO"]          # a few DC sites without CCS2: must be excluded for CCS2 cars
            status = rnd.choices(["operational", "unknown", "offline"], weights=[85, 8, 7])[0]
            n += 1
            out.append({
                "id": f"syn-{n:03d}", "name": f"{near} {rnd.choice(SUFFIX_HWY if hwy else SUFFIX_CITY)}",
                "area": near, "operator": rnd.choice(OPERATORS), "lat": round(lat, 5), "lng": round(lng, 5),
                "power_kw": power, "connectors": connectors, "count": rnd.randint(1, 6),
                "price_per_kwh": None if rnd.random() < 0.08 else round(rnd.uniform(17, 25) if dc else rnd.uniform(9, 16), 1),
                "access": "private" if rnd.random() < 0.07 else "public", "status": status,
                "category": 2 if hwy else rnd.choice([0, 1]),
                "hours": "24x7" if (hwy or rnd.random() < 0.65) else "06-23",
                "uptime": round(rnd.uniform(0.9, 0.995) if status == "operational" else rnd.uniform(0.6, 0.85), 3),
                "amenities": sorted(rnd.sample(AMENITIES, rnd.randint(1, 4))), "road": kind, "source": "synthetic",
            })
            d += rnd.uniform(9, 16) if hwy else rnd.uniform(2.0, 4.0)
    return out


@lru_cache(maxsize=1)
def stations() -> List[Dict]:
    """The whole synthetic network (fixtures first), cached: built once per process."""
    return _fixture_stations() + _generated_stations()
