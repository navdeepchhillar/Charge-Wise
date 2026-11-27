"""Which charging station is best *right now*, from wherever the vehicle is.

For every station: road distance and drive time from the live position, energy needed and arrival
battery (with a reserve), compatible connector, open/available status, queue wait at arrival (ML model),
charge time to the target with a realistic slow-down above 80%, cost, reliability (uptime) and the detour
from the planned route. These become 0-1 components, weighted by the chosen preference, plus
plain-language reasons. Everything is deterministic for the same input.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from . import data
from .geo import haversine_km
from .live import availability
from .providers import stations_for
from .queue_model import predict_wait_min, version as model_version

DC_CONNECTORS = {"CCS2", "CHAdeMO"}
WEIGHTS: Dict[str, Dict[str, float]] = {
    #            travel wait  charge cost  buffer reliability detour
    "balanced": dict(travel=.20, wait=.15, charge=.20, cost=.10, buffer=.10, reliability=.15, detour=.10),
    "fastest":  dict(travel=.25, wait=.25, charge=.30, cost=.00, buffer=.05, reliability=.10, detour=.05),
    "cheapest": dict(travel=.10, wait=.10, charge=.10, cost=.45, buffer=.10, reliability=.10, detour=.05),
    "reliable": dict(travel=.10, wait=.10, charge=.10, cost=.05, buffer=.20, reliability=.35, detour=.10),
}
STICKY_BONUS = 4.0   # score points: another station must beat the current pick by more than this
UTURN_KM = 4.5       # extra km to turn back on a divided highway
SAFETY = 1.10        # +10% energy for A/C, traffic and estimation error
CHARGE_EFF = 0.92    # grid → battery


class RankRequest(BaseModel):
    lat: float = Field(12.9716, ge=-90, le=90)
    lng: float = Field(77.5946, ge=-180, le=180)
    soc: float = Field(45, ge=0, le=100, description="battery %")
    vehicle_id: str = "mg-zs-ev"
    reserve_pct: float = Field(10, ge=0, le=50)
    target_pct: float = Field(80, ge=10, le=100)
    preset: Literal["balanced", "fastest", "cheapest", "reliable"] = "balanced"
    radius_km: float = Field(40, ge=1, le=200)
    hour: int = Field(14, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    day: int = Field(2, ge=0, le=6, description="0 = Monday")
    route_id: Optional[str] = None
    progress_km: float = Field(0, ge=0)
    limit: int = Field(60, ge=1, le=200)
    source: Literal["synthetic", "ocm"] = Field("synthetic", description="station data: synthetic network or "
                                                "real Open Charge Map stations (needs OCM_API_KEY)")
    live: bool = Field(True, description="use the live availability feed (free plugs, faults)")
    sticky_id: Optional[str] = Field(None, description="the station currently recommended; it keeps a small "
                                     "bonus so the pick doesn't flip-flop between near-equal stations")


def _speed_kmh(road: str, hour: int) -> float:
    base = data.SPEED_KMH[road]
    rush = hour in (8, 9, 10, 17, 18, 19, 20)
    return base * (0.72 if rush and road == "city" else 0.9 if rush else 1.0)


def _open_at(hours: str, hour: int) -> bool:
    if hours == "24x7":
        return True
    if hours == "closed-now":
        return False
    start, end = (int(x) for x in hours.split("-"))
    return start <= hour < end


def _charge_minutes(arrival_pct: float, target_pct: float, capacity: float, kw: float, dc: bool) -> float:
    """Minutes to charge from arrival to target; DC slows to 45% of its power above 80% (typical taper)."""
    if target_pct <= arrival_pct or kw <= 0:
        return 0.0
    def kwh(a, b):
        return max(0.0, b - a) / 100 * capacity / CHARGE_EFF
    if not dc:
        return kwh(arrival_pct, target_pct) / kw * 60
    knee = 80.0
    fast = kwh(arrival_pct, min(target_pct, knee)) / kw
    slow = kwh(max(arrival_pct, knee), target_pct) / (kw * 0.45) if target_pct > knee else 0.0
    return (fast + slow) * 60


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def rank(req: RankRequest) -> Dict:
    if req.vehicle_id not in data.VEHICLES:
        raise ValueError(f"Unknown vehicle '{req.vehicle_id}'")
    v = data.VEHICLES[req.vehicle_id]
    cap, whkm = v["battery_kwh"], v["wh_per_km"]
    route = data.route(req.route_id)["line"] if req.route_id else None
    here = (req.lat, req.lng)
    weights = WEIGHTS[req.preset]
    usable_kwh = max(0.0, (req.soc - req.reserve_pct) / 100 * cap)
    range_km = usable_kwh / (whkm / 1000 * SAFETY)

    station_list, source_used, warning = stations_for(req.source, req.lat, req.lng, req.radius_km)
    out: List[Dict] = []
    for st in station_list:
        straight = haversine_km(here, (st["lat"], st["lng"]))
        if straight > req.radius_km:
            continue
        road = st.get("road", "city")
        road_km = straight * data.ROAD_FACTOR[road]
        minutes = road_km / _speed_kmh(road, req.hour) * 60
        hw = 1.12 if road == "highway" else 1.0           # highway speeds use more energy per km
        energy = road_km * whkm / 1000 * SAFETY * hw
        arrival = req.soc - energy / cap * 100
        arrive_total_min = req.hour * 60 + req.minute + minutes
        a_hour, a_day = int(arrive_total_min // 60) % 24, (req.day + int(arrive_total_min // 1440)) % 7

        reasons, cons, excluded, verify = [], [], False, False
        compatible = [c for c in st["connectors"] if c in v["connectors"]]
        if not st["connectors"]:
            cons.append("Connector type unknown, check before going"); verify = True
        elif not compatible:
            cons.append(f"No compatible connector (station has {', '.join(st['connectors'])})"); excluded = True
        if st["status"] == "offline":
            cons.append("Reported offline"); excluded = True
        elif st["status"] != "operational":
            cons.append("Status unknown, may not be working"); verify = True
        if st["access"] == "private":
            cons.append("Private access only"); excluded = True
        if not _open_at(st["hours"], a_hour):
            cons.append(f"Closed when you arrive (~{a_hour:02d}:00)"); excluded = True
        if arrival < req.reserve_pct:
            cons.append(f"Out of reach: you'd arrive with {max(arrival, 0):.0f}% (reserve {req.reserve_pct:.0f}%)"); excluded = True

        dc = bool(compatible and any(c in DC_CONNECTORS for c in compatible) and (st["power_kw"] or 0) >= 25)
        kw = min(st["power_kw"] or 0, v["max_dc_kw"] if dc else v["max_ac_kw"])
        arrival_c = max(arrival, 0.0)
        charge_min = _charge_minutes(arrival_c, req.target_pct, cap, kw, dc) if kw else None
        delivered = max(0.0, req.target_pct - arrival_c) / 100 * cap / CHARGE_EFF
        wait = predict_wait_min(a_hour, a_day, st["count"] or 1, st["power_kw"] or 7.4, st["category"])
        live = availability(st, req.day, req.hour, req.minute) if req.live else None
        if live and live["fault"]:
            cons.append(live["note"]); excluded = True
        elif live and live["free"] == 0:
            wait = max(wait, 8.0)
            cons.append(f"All {live['total']} plugs busy right now (live)")
        elif live and minutes <= 20:
            wait = round(wait * 0.4, 1)                      # plugs free now and you're close: queue unlikely
            reasons.append(f"{live['free']} of {live['total']} plugs free right now (live)")
        cost = round(delivered * st["price_per_kwh"]) if st["price_per_kwh"] is not None else None
        if cost is None:
            cons.append("Price not published")

        detour_km, ahead = None, None
        if route is not None:
            along, lateral = route.project((st["lat"], st["lng"]))
            ahead = along >= req.progress_km - 0.2
            back = 0.0 if ahead else (req.progress_km - along)
            detour_km = (2 * lateral + 2 * back) * data.ROAD_FACTOR[road]
            if not ahead and road == "highway":
                detour_km += UTURN_KM                          # divided highway: drive on to the next U-turn
                cons.append("Needs a U-turn on the highway")
            if ahead and lateral < 1.0:
                reasons.append(f"On your route, {along - req.progress_km:.1f} km ahead")
            elif ahead:
                reasons.append(f"Ahead on your route, {lateral:.1f} km off it")
            else:
                cons.append(f"Behind you: {back:.1f} km back")

        comp = {
            # on a route only the EXTRA driving counts (you'd pass stations ahead anyway); off-route: time to get there
            "travel": _clamp(1 - (detour_km / _speed_kmh(road, req.hour) * 60) / 30) if detour_km is not None
                      else _clamp(1 - minutes / 60),
            "wait": _clamp(1 - wait / 45),
            "charge": _clamp(1 - charge_min / 90) if charge_min is not None else 0.5,
            "cost": _clamp(1 - cost / 1500) if cost is not None else 0.5,
            "buffer": _clamp((arrival - req.reserve_pct) / 30),
            "reliability": _clamp((st["uptime"] - 0.6) / 0.4),
            "detour": _clamp(1 - detour_km / 12) if detour_km is not None else 0.5,
        }
        score = round(sum(weights[k] * comp[k] for k in weights) * 100, 1)
        rank_score = score + (STICKY_BONUS if st["id"] == req.sticky_id else 0.0)

        if dc and kw >= 50:
            reasons.append(f"Fast DC: {kw:.0f} kW for your car")
        elif not dc and kw:
            reasons.append(f"AC charging, {kw:g} kW (slow)")
        if wait <= 2:
            reasons.append("Little or no queue expected")
        elif wait >= 10:
            cons.append(f"Likely queue: ~{wait:.0f} min")
        if st["uptime"] >= 0.97:
            reasons.append(f"{st['uptime'] * 100:.0f}% uptime, very reliable")
        elif st["uptime"] < 0.85:
            cons.append(f"Less reliable: {st['uptime'] * 100:.0f}% uptime")
        if not excluded and arrival - req.reserve_pct < 8:
            cons.append("Tight: little battery margin on arrival")

        eligibility = "excluded" if excluded else "verify" if verify else "eligible"
        out.append({
            "id": st["id"], "name": st["name"], "operator": st["operator"], "area": st["area"],
            "lat": st["lat"], "lng": st["lng"], "power_kw": st["power_kw"], "connectors": st["connectors"],
            "count": st["count"], "price_per_kwh": st["price_per_kwh"], "status": st["status"], "access": st["access"],
            "hours": st["hours"], "uptime": st["uptime"], "amenities": st["amenities"], "road": road,
            "eligibility": eligibility, "score": score if not excluded else 0.0, "_rank": rank_score,
            "straight_km": round(straight, 2), "road_km": round(road_km, 1), "drive_min": round(minutes, 1),
            "energy_kwh": round(energy, 2), "arrival_pct": round(arrival, 1), "wait_min": wait,
            "charge_kw": round(kw, 1), "charge_min": round(charge_min, 1) if charge_min is not None else None,
            "cost_inr": cost, "detour_km": round(detour_km, 1) if detour_km is not None else None, "ahead": ahead,
            "total_min": round(minutes + wait + (charge_min or 0), 1), "live": live, "source": st.get("source"),
            "components": {k: round(x, 3) for k, x in comp.items()}, "reasons": reasons, "cons": cons,
        })

    order = {"eligible": 0, "verify": 1, "excluded": 2}
    rank_of = {s["id"]: s.pop("_rank") for s in out}
    out.sort(key=lambda s: (order[s["eligibility"]], -rank_of[s["id"]] if s["eligibility"] != "excluded" else 0,
                            s["road_km"], s["id"]))
    eligible = [s for s in out if s["eligibility"] == "eligible"]
    best = eligible[0] if eligible else None

    remaining_km = None
    if route is not None:
        remaining_km = max(0.0, route.length_km - req.progress_km) * 1.15
    if not eligible:
        alert = {"level": "stranded", "message": "No reachable compatible station within your reserve. Slow down, switch off A/C and head to the nearest station marked 'check'."}
    elif req.soc <= req.reserve_pct + 8 or (best and best["arrival_pct"] - req.reserve_pct < 6):
        alert = {"level": "charge_now", "message": f"Charge now: head to {best['name']} ({best['road_km']} km)."}
    elif remaining_km is not None and range_km < remaining_km:
        alert = {"level": "plan", "message": f"You can't finish this route on the current charge ({range_km:.0f} km range vs ~{remaining_km:.0f} km to go). Plan a stop: {best['name']} is the best option."}
    elif req.soc < 30:
        alert = {"level": "plan", "message": f"Battery getting low. Best stop: {best['name']}."}
    else:
        alert = {"level": "ok", "message": "Enough charge. Showing the best stop if you want one."}

    return {
        "vehicle": {"id": req.vehicle_id, **v}, "soc": req.soc, "range_km": round(range_km, 1),
        "remaining_route_km": round(remaining_km, 1) if remaining_km is not None else None,
        "best": best, "alert": alert, "preset": req.preset, "weights": weights,
        "counts": {k: sum(1 for s in out if s["eligibility"] == k) for k in order},
        "stations": out[: req.limit], "model_version": model_version(),
        "source": source_used, "warning": warning, "as_of": f"{req.hour:02d}:{req.minute:02d}",
    }
