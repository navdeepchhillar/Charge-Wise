"""Stateless ride simulator: where is the car after `elapsed_s` seconds of driving, and how much battery is left?

The server keeps no session. A ride "leg" is fully described by (route, vehicle, start km, start battery,
start clock); the client sends the elapsed simulated seconds and gets the same answer every time. After a
charging stop the client simply starts a new leg from the current km with the new battery level.

Speed per route segment = road-kind cruise speed x rush-hour factor (from the simulated clock) x a fixed
per-segment traffic factor (seeded noise). Energy = km x Wh/km x road factor (highway speeds cost more,
crawling city traffic a little more too).
"""
from __future__ import annotations

import random
from bisect import bisect_right
from functools import lru_cache
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from . import data
from .ranking import RankRequest, rank


class RideRequest(BaseModel):
    route_id: str = "city-commute"
    vehicle_id: str = "mg-zs-ev"
    start_soc: float = Field(40, ge=0, le=100)
    start_km: float = Field(0, ge=0)
    elapsed_s: float = Field(0, ge=0, le=7 * 24 * 3600)
    start_hour: int = Field(9, ge=0, le=23)
    start_minute: int = Field(0, ge=0, le=59)
    day: int = Field(2, ge=0, le=6)
    preset: Literal["balanced", "fastest", "cheapest", "reliable"] = "balanced"
    reserve_pct: float = Field(10, ge=0, le=50)
    target_pct: float = Field(80, ge=10, le=100)
    radius_km: float = Field(40, ge=1, le=200)
    limit: int = Field(40, ge=1, le=200)
    sticky_id: Optional[str] = None
    live: bool = True


def _rush(hour: int, kind: str) -> float:
    if hour in (8, 9, 10, 17, 18, 19, 20):
        return 0.62 if kind == "city" else 0.85
    if hour in (23, 0, 1, 2, 3, 4, 5):
        return 1.25 if kind == "city" else 1.08
    return 1.0


@lru_cache(maxsize=None)
def _traffic(route_id: str) -> List[float]:
    """A fixed traffic factor per segment (0.75-1.15), smoothed so speed changes gradually."""
    n = len(data.route(route_id)["line"].points) - 1
    rnd = random.Random(f"traffic-{route_id}")
    raw = [rnd.uniform(0.75, 1.15) for _ in range(n)]
    return [sum(raw[max(0, i - 2): i + 3]) / len(raw[max(0, i - 2): i + 3]) for i in range(n)]


def _energy_factor(kind: str, speed: float) -> float:
    if kind == "highway":
        return 1.12
    return 1.06 if speed < 18 else 1.0      # stop-and-go costs a little extra


def simulate(req: RideRequest) -> Dict:
    if req.route_id not in data.ROUTES:
        raise ValueError(f"Unknown route '{req.route_id}'")
    if req.vehicle_id not in data.VEHICLES:
        raise ValueError(f"Unknown vehicle '{req.vehicle_id}'")
    r = data.route(req.route_id)
    line, kinds, traffic = r["line"], r["kinds"], _traffic(req.route_id)
    v = data.VEHICLES[req.vehicle_id]
    cap, whkm = v["battery_kwh"], v["wh_per_km"]
    available = req.start_soc / 100 * cap
    clock0 = req.start_hour * 60 + req.start_minute          # minutes since midnight of `day`

    d = min(req.start_km, line.length_km)
    i = min(max(bisect_right(line.cum, d) - 1, 0), len(line.points) - 2)
    t, energy, speed, kind = 0.0, 0.0, 0.0, kinds[i]
    finished = stranded = False
    while True:
        if d >= line.length_km - 1e-9:
            finished, speed = True, 0.0
            break
        seg_end = line.cum[i + 1]
        seg_len = seg_end - d
        kind = kinds[i]
        hour = int((clock0 + t / 60) // 60) % 24
        speed = data.SPEED_KMH[kind] * _rush(hour, kind) * traffic[i]
        kwh_per_km = whkm / 1000 * _energy_factor(kind, speed)
        seg_t = seg_len / speed * 3600
        # how far can we go in this segment before time runs out or the battery is empty?
        frac_t = (req.elapsed_s - t) / seg_t if seg_t > 0 else 1.0
        frac_e = (available - energy) / (seg_len * kwh_per_km) if seg_len > 0 else 1.0
        frac = min(1.0, frac_t, frac_e)
        d += seg_len * frac
        t += seg_t * frac
        energy += seg_len * frac * kwh_per_km
        if frac_e <= frac_t and frac_e < 1.0:
            stranded, speed = True, 0.0
            break
        if frac_t < 1.0 or t >= req.elapsed_s:
            break
        i += 1
        if i >= len(line.points) - 1:
            d, finished, speed = line.length_km, True, 0.0
            break

    # ETA for the rest of the route at the speeds we'd see from here
    eta_s, j, dd = 0.0, min(i, len(line.points) - 2), d
    while dd < line.length_km - 1e-9 and j < len(line.points) - 1:
        hour = int((clock0 + (t + eta_s) / 60) // 60) % 24
        sp = data.SPEED_KMH[kinds[j]] * _rush(hour, kinds[j]) * traffic[j]
        eta_s += (line.cum[j + 1] - dd) / sp * 3600
        dd, j = line.cum[j + 1], j + 1

    (lat, lng), heading = line.point_at(d)
    soc = max(0.0, req.start_soc - energy / cap * 100)
    now_min = clock0 + t / 60
    day = (req.day + int(now_min // 1440)) % 7
    hour, minute = int(now_min // 60) % 24, int(now_min % 60)
    seg_index = min(max(bisect_right(line.cum, d) - 1, 0), len(line.points) - 2)
    return {
        "route_id": req.route_id, "lat": round(lat, 6), "lng": round(lng, 6), "heading": round(heading, 1),
        "speed_kmh": round(speed, 1), "road": kind, "progress_km": round(d, 3),
        "route_km": round(line.length_km, 2), "remaining_km": round(max(0.0, line.length_km - d), 2),
        "segment_index": seg_index, "soc": round(soc, 2), "energy_used_kwh": round(energy, 3),
        "elapsed_s": round(t, 1), "clock": f"{hour:02d}:{minute:02d}", "hour": hour, "minute": minute, "day": day,
        "eta_min": round(eta_s / 60, 1), "finished": finished, "stranded": stranded,
    }


def ride_state(req: RideRequest) -> Dict:
    """Telemetry plus the best station from the car's current position and battery."""
    tel = simulate(req)
    rec = rank(RankRequest(
        lat=tel["lat"], lng=tel["lng"], soc=tel["soc"], vehicle_id=req.vehicle_id, reserve_pct=req.reserve_pct,
        target_pct=req.target_pct, preset=req.preset, radius_km=req.radius_km, hour=tel["hour"],
        minute=tel["minute"], day=tel["day"], route_id=None if tel["finished"] else req.route_id, progress_km=tel["progress_km"],
        limit=req.limit, sticky_id=req.sticky_id, live=req.live,
    ))
    return {"telemetry": tel, "recommendation": rec}
