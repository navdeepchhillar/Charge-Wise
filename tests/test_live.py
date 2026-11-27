"""Live availability feed and real-station provider (Open Charge Map, mocked: no network, no key)."""
from chargewise import data, live, providers
from chargewise.ranking import RankRequest, rank

ST = {"id": "t-1", "count": 4, "power_kw": 60, "category": 1}


def test_availability_shape_and_bounds():
    for m in range(0, 1440, 37):
        a = live.availability(ST, 2, m // 60, m % 60)
        assert 0 <= a["free"] <= a["total"] == 4 and isinstance(a["fault"], bool) and len(a["updated"]) == 5


def test_availability_is_stable_within_a_tick_and_changes_across_ticks():
    assert live.availability(ST, 2, 9, 0) == live.availability(ST, 2, 9, 4)
    seen = {live.availability(ST, 2, h, 0)["free"] for h in range(24)}
    assert len(seen) > 1


def test_rush_hour_is_busier_on_average():
    stations = data.stations()
    def free_ratio(hour):
        f = t = 0
        for st in stations:
            for minute in range(0, 60, 5):
                a = live.availability(st, 2, hour, minute)
                f += a["free"]; t += a["total"]
        return f / t
    assert free_ratio(3) >= free_ratio(18)


def test_faults_happen_and_exclude_the_station():
    stations = data.stations()
    faults = [(st, d, h, m) for st in stations[:20] for d in range(7) for h in range(24) for m in (0, 30)
              if live.availability(st, d, h, m)["fault"]]
    assert faults, "the feed should produce occasional faults"
    st, d, h, m = faults[0]
    res = rank(RankRequest(lat=st["lat"], lng=st["lng"], soc=80, day=d, hour=h, minute=m, radius_km=5, limit=200))
    row = next(s for s in res["stations"] if s["id"] == st["id"])
    assert row["eligibility"] == "excluded" and any("fault" in c for c in row["cons"])
    # without the live feed the same station is fine again (if nothing else rules it out)
    res2 = rank(RankRequest(lat=st["lat"], lng=st["lng"], soc=80, day=d, hour=h, minute=m, radius_km=5, limit=200, live=False))
    row2 = next(s for s in res2["stations"] if s["id"] == st["id"])
    assert not any("fault" in c for c in row2["cons"])


def test_live_off_has_no_live_block():
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, live=False))
    assert all(s["live"] is None for s in res["stations"])


# ── Real stations (OpenStreetMap + Open Charge Map), all network mocked ───────────────────
import pytest

from chargewise import routing

OCM_POI = {
    "ID": 123, "NumberOfPoints": 2,
    "AddressInfo": {"Title": "Real Mall Chargers", "Town": "Bengaluru", "Latitude": 12.95, "Longitude": 77.64},
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 60, "Quantity": 1}, {"ConnectionTypeID": 25, "PowerKW": 22}],
    "StatusType": {"IsOperational": True}, "UsageType": {"ID": 1, "Title": "Public"},
    "OperatorInfo": {"Title": "Some Operator"},
}
OSM_FAST = {"type": "node", "id": 11, "lat": 12.935, "lon": 77.625, "tags": {
    "amenity": "charging_station", "name": "Forum Mall DC", "operator": "Statiq", "socket:type2_combo": "2",
    "socket:type2_combo:output": "60 kW", "socket:type2": "1", "socket:type2:output": "22 kW", "opening_hours": "24/7"}}
OSM_SCOOTER = {"type": "node", "id": 12, "lat": 12.97, "lon": 77.63, "tags": {
    "amenity": "charging_station", "scooter": "yes", "motorcycle": "yes"}}
OSM_WAY = {"type": "way", "id": 13, "center": {"lat": 12.94, "lon": 77.62}, "tags": {
    "amenity": "charging_station", "fixme": "details", "opening_hours": "Mo-Sa 09:00-21:00"}}
OSM_DUP_OF_OCM = {"type": "node", "id": 14, "lat": 12.9501, "lon": 77.6401, "tags": {"amenity": "charging_station"}}


def test_map_osm_reads_sockets_power_and_hours():
    s = providers.map_osm(OSM_FAST)
    assert s["id"] == "osm-n11" and s["connectors"] == ["CCS2", "Type 2"] and s["power_kw"] == 60
    assert s["count"] == 3 and s["hours"] == "24x7" and s["status"] == "operational" and s["source"] == "openstreetmap"


def test_map_osm_skips_two_wheeler_chargers_and_handles_ways():
    assert providers.map_osm(OSM_SCOOTER) is None
    w = providers.map_osm(OSM_WAY)
    assert w["lat"] == 12.94 and w["connectors"] == [] and w["status"] == "unknown" and w["hours"] == "unknown"


def test_power_parsing():
    assert providers._power_kw("7.4 kW") == 7.4 and providers._power_kw("22000 W") == 22 and providers._power_kw("") is None


def test_map_ocm():
    s = providers.map_ocm(OCM_POI)
    assert s["id"] == "ocm-123" and s["connectors"] == ["CCS2", "Type 2"] and s["power_kw"] == 60
    assert providers.map_ocm({"AddressInfo": {}}) is None


@pytest.fixture
def net(monkeypatch):
    """Fake HTTP for Overpass/OCM; records calls."""
    providers._cache.clear(); routing._cache.clear()
    calls = []
    state = {"osm": [OSM_FAST, OSM_SCOOTER, OSM_WAY], "ocm": [OCM_POI], "fail": set()}
    def fake(url, body=None, timeout=6.0):
        kind = "ocm" if "openchargemap" in url else "osm"
        calls.append(kind)
        if kind in state["fail"]:
            raise TimeoutError("slow")
        return state["ocm"] if kind == "ocm" else {"elements": state["osm"]}
    monkeypatch.setattr(providers, "_http_json", fake)
    monkeypatch.delenv("OCM_API_KEY", raising=False)
    return state, calls


def test_real_source_uses_osm_without_any_key(net):
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    assert res["source"] == "OpenStreetMap" and res["warning"] is None
    assert res["best"]["id"] == "osm-n11"
    ids = {s["id"] for s in res["stations"]}
    assert "osm-n12" not in ids and not any(i.startswith("syn-") for i in ids)


def test_real_stations_have_no_simulated_live_feed(net):
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    assert all(s["live"] is None for s in res["stations"])


def test_unknown_osm_station_needs_checking(net):
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    w = next(s for s in res["stations"] if s["id"] == "osm-w13")
    assert w["eligibility"] == "verify" and any("Opening hours" in c for c in w["cons"])


def test_real_stations_cached_per_area(net):
    _, calls = net
    rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    first = len(calls)
    rank(RankRequest(lat=12.931, lng=77.622, soc=50, source="real"))
    assert first >= 1 and len(calls) == first                  # second request in the same area: no network


def test_failure_is_cached_briefly(net):
    state, calls = net
    state["fail"] = {"osm"}
    rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    first = len(calls)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    assert len(calls) == first and res["source"] == "synthetic"


def test_client_supplied_stations_are_ranked():
    mine = [{"id": "mine-1", "name": "My Office Charger", "lat": 12.931, "lng": 77.621, "power_kw": 60,
             "connectors": ["CCS2"], "count": 2, "status": "operational"}]
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=mine, stations_label="OpenStreetMap"))
    assert res["source"] == "OpenStreetMap" and res["best"]["id"] == "mine-1" and len(res["stations"]) == 1


def test_ocm_merged_when_key_set_and_duplicates_dropped(net, monkeypatch):
    state, calls = net
    monkeypatch.setenv("OCM_API_KEY", "test-key")
    state["osm"] = [OSM_FAST, OSM_DUP_OF_OCM]
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real", limit=200))
    ids = {s["id"] for s in res["stations"]}
    assert res["source"] == "Open Charge Map + OpenStreetMap" and "ocm-123" in ids and "osm-n11" in ids
    assert "osm-n14" not in ids and set(calls) == {"ocm", "osm"}


def test_one_provider_failing_still_gives_real_data(net, monkeypatch):
    state, _ = net
    monkeypatch.setenv("OCM_API_KEY", "test-key")
    state["fail"] = {"ocm"}
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    assert res["source"] == "OpenStreetMap" and res["best"]


def test_all_real_providers_failing_falls_back_to_synthetic(net):
    state, _ = net
    state["fail"] = {"osm"}
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real"))
    assert res["source"] == "synthetic" and "unavailable" in res["warning"] and res["best"]


# ── Road routing (OSRM), mocked ──────────────────────────────────────────
def test_road_routing_replaces_estimates(net, monkeypatch):
    urls = []
    def fake(url):
        urls.append(url)
        n = url.split("/driving/")[1].split("?")[0].count(";")
        return {"code": "Ok", "distances": [[0] + [9000.0] * n], "durations": [[0] + [900.0] * n]}
    monkeypatch.setattr(routing, "_fetch", fake)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real", road_routing=True, hour=14))
    b = res["best"]
    assert res["routing"] == "osrm" and b["distance_source"] == "road" and b["road_km"] == 9.0 and b["drive_min"] == 15.0
    rush = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real", road_routing=True, hour=9))["best"]
    assert rush["drive_min"] > 15.0 and len(urls) == 1           # rush slows it; same position served from cache


def test_road_routing_failure_falls_back_to_estimates(net, monkeypatch):
    def boom(url):
        raise TimeoutError("osrm down")
    monkeypatch.setattr(routing, "_fetch", boom)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="real", road_routing=True))
    assert res["routing"] == "estimate" and "Road routing unavailable" in res["warning"]
    assert res["best"]["distance_source"] == "estimate"


@pytest.mark.parametrize("name", ["Ola Hyper Charger", "Ather Grid", "Battery Swap", "Honda e:swap", "Yulu Zone"])
def test_two_wheeler_and_swap_stations_are_skipped(name):
    assert providers.map_osm({"type": "node", "id": 1, "lat": 12.9, "lon": 77.6,
                              "tags": {"amenity": "charging_station", "name": name}}) is None


def test_car_tagged_station_is_kept_even_with_two_wheeler_brand():
    s = providers.map_osm({"type": "node", "id": 2, "lat": 12.9, "lon": 77.6,
                           "tags": {"amenity": "charging_station", "name": "Ola Hub", "motorcar": "yes"}})
    assert s is not None


def test_unconfirmed_best_when_no_station_is_confirmed():
    unknown = [{"id": f"u{i}", "name": f"Unknown {i}", "lat": 12.93 + i / 200, "lng": 77.62} for i in range(3)]
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=unknown))
    assert res["best"]["eligibility"] == "verify" and res["best_confirmed"] is False
    assert res["alert"]["level"] != "stranded"


def test_confirmed_station_beats_closer_unconfirmed_one():
    st = [{"id": "near-unknown", "lat": 12.9301, "lng": 77.6201},
          {"id": "far-confirmed", "lat": 12.96, "lng": 77.62, "connectors": ["CCS2"], "power_kw": 60,
           "status": "operational", "count": 2}]
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=st))
    assert res["best"]["id"] == "far-confirmed" and res["best_confirmed"] is True


def test_assumed_power_for_unlisted_sockets():
    ac = providers.map_osm({"type": "node", "id": 3, "lat": 1, "lon": 1, "tags": {"amenity": "charging_station", "socket:type2": "2"}})
    dc = providers.map_osm({"type": "node", "id": 4, "lat": 1, "lon": 1, "tags": {"amenity": "charging_station", "socket:type2_combo": "1"}})
    assert (ac["power_kw"], ac["power_assumed"]) == (7.4, True) and (dc["power_kw"], dc["power_assumed"]) == (30.0, True)
    res = rank(RankRequest(lat=1.0, lng=1.0, soc=50, stations=[{**ac, "status": "operational"}]))
    assert any("Power not listed" in c for c in res["best"]["cons"]) and res["best"]["charge_min"] > 0


def test_routing_prefers_confirmed_stations(monkeypatch):
    routing._cache.clear()
    sent = []
    def fake(url):
        coords = url.split("/driving/")[1].split("?")[0].split(";")[1:]
        sent.extend(coords)
        return {"code": "Ok", "distances": [[0] + [1000.0] * len(coords)], "durations": [[0] + [60.0] * len(coords)]}
    monkeypatch.setattr(routing, "_fetch", fake)
    unknown = [{"id": f"u{i}", "lat": 12.93 + i / 1000, "lng": 77.62} for i in range(1, 15)]
    confirmed = {"id": "far", "lat": 12.99, "lng": 77.62, "connectors": ["CCS2"], "power_kw": 60, "status": "operational"}
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=60, stations=unknown + [confirmed], road_routing=True, limit=200))
    assert "77.620000,12.990000" in sent and res["best"]["id"] == "far" and res["best"]["distance_source"] == "road"
