"""Ranking + simulator: the moving-vehicle cases the original demo got wrong, and the safety rules."""
import pytest

from chargewise import data
from chargewise.geo import Polyline, haversine_km
from chargewise.queue_model import predict_wait_min
from chargewise.ranking import RankRequest, _charge_minutes, rank
from chargewise.simulator import RideRequest, ride_state, simulate


def by_id(result):
    return {s["id"]: s for s in result["stations"]}


# ── geometry ──────────────────────────────────────────────────────────────
def test_haversine_known_distance():
    # MG Road → Kempegowda Airport is ~27 km in a straight line
    assert 25 < haversine_km((12.9756, 77.6066), (13.1989, 77.7068)) < 29


def test_polyline_point_and_project_roundtrip():
    line = data.route("airport-run")["line"]
    for d in (0.0, 5.0, 17.3, line.length_km):
        p, _ = line.point_at(d)
        along, lateral = line.project(p)
        assert abs(along - d) < 0.05 and lateral < 0.01


def test_polyline_needs_two_points():
    with pytest.raises(ValueError):
        Polyline([(0, 0)])


# ── the original bug: recommendations must work from ANY position ──────────
@pytest.mark.parametrize("route_id", list(data.ROUTES))
def test_recommendations_everywhere_along_every_route(route_id):
    line = data.route(route_id)["line"]
    for f in (0, 0.25, 0.5, 0.75, 1.0):
        (lat, lng), _ = line.point_at(line.length_km * f)
        res = rank(RankRequest(lat=lat, lng=lng, soc=60, route_id=route_id, progress_km=line.length_km * f))
        assert res["best"] is not None, (route_id, f)
        assert res["best"]["road_km"] > 0 and res["best"]["drive_min"] > 0


def test_distances_change_as_the_car_moves():
    line = data.route("city-commute")["line"]
    a = by_id(rank(RankRequest(lat=line.point_at(1)[0][0], lng=line.point_at(1)[0][1], soc=60)))
    b = by_id(rank(RankRequest(lat=line.point_at(15)[0][0], lng=line.point_at(15)[0][1], soc=60)))
    common = set(a) & set(b)
    assert common and any(abs(a[i]["road_km"] - b[i]["road_km"]) > 1 for i in common)


def test_deterministic():
    req = RankRequest(lat=12.93, lng=77.62, soc=33, route_id="city-commute", progress_km=6)
    assert rank(req) == rank(req)


# ── safety rules ──────────────────────────────────────────────────────────
def test_best_is_always_reachable_with_reserve():
    for soc in (15, 20, 30, 50, 90):
        res = rank(RankRequest(lat=12.70, lng=77.25, soc=soc, reserve_pct=10, route_id="mysuru-highway", progress_km=60))
        if res["best"]:
            assert res["best"]["eligibility"] == "eligible" and res["best"]["arrival_pct"] >= 10


def test_unreachable_stations_are_excluded():
    res = rank(RankRequest(lat=12.72, lng=77.28, soc=11, reserve_pct=10, radius_km=60))
    far = [s for s in res["stations"] if s["road_km"] > 10]
    assert far and all(s["eligibility"] == "excluded" for s in far)
    assert any("Out of reach" in c for s in far for c in s["cons"])


def test_offline_private_and_wrong_plug_are_excluded():
    res = rank(RankRequest(lat=12.97, lng=77.6, soc=90, radius_km=200, limit=200))
    stations = {s["id"]: s for s in data.stations()}
    for s in res["stations"]:
        st = stations[s["id"]]
        if st["status"] == "offline" or st["access"] == "private" or (st["connectors"] and not set(st["connectors"]) & {"CCS2", "Type 2"}):
            assert s["eligibility"] == "excluded", s["id"]
    assert any(s["connectors"] == ["CHAdeMO"] and s["eligibility"] == "excluded" for s in res["stations"])


def test_station_closed_at_night_is_excluded():
    night = rank(RankRequest(lat=12.97, lng=77.6, soc=90, radius_km=200, limit=200, hour=2))
    part_time = [s for s in night["stations"] if s["hours"] == "06-23"]
    assert part_time and all(s["eligibility"] == "excluded" for s in part_time)
    assert all(any("Closed when you arrive" in c for c in s["cons"]) for s in part_time)
    day = {s["id"]: s for s in rank(RankRequest(lat=12.97, lng=77.6, soc=90, radius_km=200, limit=200, hour=12))["stations"]}
    assert any(day[s["id"]]["eligibility"] != "excluded" for s in part_time)


def test_unknown_status_needs_verification_not_best():
    res = rank(RankRequest(lat=12.97, lng=77.6, soc=90, radius_km=200, limit=200))
    unknown = [s for s in res["stations"] if s["status"] == "unknown" and s["eligibility"] != "excluded"]
    assert unknown and all(s["eligibility"] == "verify" for s in unknown)
    assert res["best"]["status"] == "operational"


def test_stranded_alert_when_nothing_reachable():
    res = rank(RankRequest(lat=12.52, lng=76.9, soc=10.5, reserve_pct=10))
    assert res["best"] is None and res["alert"]["level"] == "stranded"


def test_charge_now_alert_when_low():
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=16, reserve_pct=10))
    assert res["alert"]["level"] == "charge_now" and res["best"]


def test_plan_alert_when_route_too_long():
    res = rank(RankRequest(lat=12.9443, lng=77.524, soc=35, route_id="mysuru-highway", progress_km=0))
    assert res["alert"]["level"] == "plan" and "can't finish" in res["alert"]["message"]


# ── scoring ───────────────────────────────────────────────────────────────
def test_presets_change_the_choice():
    kw = dict(lat=12.93, lng=77.62, soc=40, radius_km=40)
    cheap = rank(RankRequest(preset="cheapest", **kw))["best"]
    fast = rank(RankRequest(preset="fastest", **kw))["best"]
    elig = [s for s in rank(RankRequest(**kw))["stations"] if s["eligibility"] == "eligible" and s["cost_inr"] is not None]
    assert cheap["cost_inr"] <= sorted(s["cost_inr"] for s in elig)[len(elig) // 2]
    assert fast["total_min"] <= sorted(s["total_min"] for s in elig)[len(elig) // 2]


def test_stations_ahead_beat_stations_behind_on_route():
    line = data.route("mysuru-highway")["line"]
    for km in (20, 45, 70, 95):
        (lat, lng), _ = line.point_at(km)
        res = rank(RankRequest(lat=lat, lng=lng, soc=60, route_id="mysuru-highway", progress_km=km))
        assert res["best"]["ahead"] is True, km


def test_sticky_pick_survives_small_differences():
    req = dict(lat=12.93, lng=77.62, soc=40)
    ranked = [s for s in rank(RankRequest(**req))["stations"] if s["eligibility"] == "eligible"]
    second = ranked[1]
    if ranked[0]["score"] - second["score"] < 4:
        assert rank(RankRequest(sticky_id=second["id"], **req))["best"]["id"] == second["id"]
    far = ranked[-1]
    if ranked[0]["score"] - far["score"] > 4:
        assert rank(RankRequest(sticky_id=far["id"], **req))["best"]["id"] == ranked[0]["id"]


def test_dc_taper_above_80():
    to80 = _charge_minutes(60, 80, 50, 60, dc=True)
    to100 = _charge_minutes(80, 100, 50, 60, dc=True)
    assert to100 > 2 * to80
    assert _charge_minutes(90, 80, 50, 60, dc=True) == 0


def test_ac_charging_is_slow():
    assert _charge_minutes(20, 80, 50, 7.4, dc=False) > 200


def test_queue_model_returns_minutes():
    for h in range(24):
        w = predict_wait_min(h, 2, 2, 60, 1)
        assert 0 <= w < 120


def test_unknown_vehicle_rejected():
    with pytest.raises(ValueError):
        rank(RankRequest(vehicle_id="tesla-cybertruck"))


# ── simulator ─────────────────────────────────────────────────────────────
def test_ride_starts_at_route_start():
    t = simulate(RideRequest(route_id="whitefield", elapsed_s=0))
    w = data.ROUTES["whitefield"]["waypoints"][0]
    assert t["progress_km"] == 0 and abs(t["lat"] - w[1]) < 1e-4 and t["soc"] == 40


def test_ride_moves_forward_and_drains_battery():
    prev = None
    for s in range(0, 3600, 300):
        t = simulate(RideRequest(route_id="airport-run", start_soc=80, elapsed_s=s))
        if prev:
            assert t["progress_km"] >= prev["progress_km"] and t["soc"] <= prev["soc"]
        prev = t
    assert prev["progress_km"] > 10 and prev["soc"] < 80


def test_ride_finishes():
    t = simulate(RideRequest(route_id="whitefield", start_soc=90, elapsed_s=6 * 3600))
    assert t["finished"] and t["remaining_km"] == 0 and t["speed_kmh"] == 0 and t["eta_min"] == 0


def test_highway_with_low_battery_strands():
    t = simulate(RideRequest(route_id="mysuru-highway", start_soc=25, elapsed_s=6 * 3600))
    assert t["stranded"] and not t["finished"] and t["soc"] == 0 and t["progress_km"] < t["route_km"]


def test_leg_after_charging_continues_from_same_km():
    t = simulate(RideRequest(route_id="mysuru-highway", start_soc=80, start_km=50, elapsed_s=0))
    assert abs(t["progress_km"] - 50) < 1e-6 and t["soc"] == 80
    t2 = simulate(RideRequest(route_id="mysuru-highway", start_soc=80, start_km=50, elapsed_s=1800))
    assert t2["progress_km"] > 60


def test_rush_hour_is_slower():
    rush = simulate(RideRequest(route_id="city-commute", start_hour=9, elapsed_s=1800))
    calm = simulate(RideRequest(route_id="city-commute", start_hour=14, elapsed_s=1800))
    assert calm["progress_km"] > rush["progress_km"]


def test_clock_rolls_over_midnight():
    t = simulate(RideRequest(route_id="mysuru-highway", start_soc=100, start_hour=23, start_minute=30, day=6, elapsed_s=3600))
    assert t["hour"] == 0 and t["day"] == 0


def test_ride_state_includes_recommendation():
    r = ride_state(RideRequest(route_id="mysuru-highway", start_soc=35, elapsed_s=1200))
    assert r["telemetry"]["progress_km"] > 0 and r["recommendation"]["best"]
    assert r["recommendation"]["alert"]["level"] in {"plan", "charge_now"}


def test_finished_ride_does_not_mark_everything_behind():
    r = ride_state(RideRequest(route_id="whitefield", start_soc=90, elapsed_s=6 * 3600))
    assert r["telemetry"]["finished"] and r["recommendation"]["best"]["ahead"] is None


def test_unknown_route_rejected():
    with pytest.raises(ValueError):
        simulate(RideRequest(route_id="moon-base"))
