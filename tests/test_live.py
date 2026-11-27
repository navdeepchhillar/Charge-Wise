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


# ── Open Charge Map provider ─────────────────────────────────────────────
OCM_POI = {
    "ID": 123, "NumberOfPoints": 2,
    "AddressInfo": {"Title": "Real Mall Chargers", "Town": "Bengaluru", "Latitude": 12.95, "Longitude": 77.64},
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 60, "Quantity": 1}, {"ConnectionTypeID": 25, "PowerKW": 22}],
    "StatusType": {"IsOperational": True}, "UsageType": {"ID": 1, "Title": "Public"},
    "OperatorInfo": {"Title": "Some Operator"},
}


def test_map_ocm():
    s = providers.map_ocm(OCM_POI)
    assert s["id"] == "ocm-123" and s["connectors"] == ["CCS2", "Type 2"] and s["power_kw"] == 60
    assert s["status"] == "operational" and s["access"] == "public" and s["count"] == 2
    assert providers.map_ocm({"AddressInfo": {}}) is None


def test_ocm_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("OCM_API_KEY", raising=False)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="ocm"))
    assert res["source"] == "synthetic" and "OCM_API_KEY" in res["warning"] and res["best"]


def test_ocm_with_key_uses_real_stations_and_caches(monkeypatch):
    monkeypatch.setenv("OCM_API_KEY", "test-key")
    providers._cache.clear()
    calls = []
    def fake(url, timeout=6.0):
        calls.append(url)
        return [OCM_POI]
    monkeypatch.setattr(providers, "_fetch_json", fake)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="ocm"))
    assert res["source"] == "ocm" and res["warning"] is None and res["best"]["id"] == "ocm-123"
    rank(RankRequest(lat=12.931, lng=77.621, soc=50, source="ocm"))
    assert len(calls) == 1 and "key=test-key" in calls[0]


def test_ocm_error_falls_back(monkeypatch):
    monkeypatch.setenv("OCM_API_KEY", "test-key")
    providers._cache.clear()
    def boom(url, timeout=6.0):
        raise TimeoutError("slow")
    monkeypatch.setattr(providers, "_fetch_json", boom)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, source="ocm"))
    assert res["source"] == "synthetic" and "TimeoutError" in res["warning"] and res["best"]
