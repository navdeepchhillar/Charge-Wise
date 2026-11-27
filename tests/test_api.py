"""HTTP layer: every endpoint, validation errors, and the page itself."""
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_index_serves_the_ui():
    r = client.get("/")
    assert r.status_code == 200 and "Chargewise" in r.text and "leaflet" in r.text.lower()


def test_health():
    j = client.get("/api/health").json()
    assert j["status"] == "ok" and j["stations"] > 20 and j["model_version"] == "synthetic-queue-v1"


def test_vehicles_and_routes():
    assert {v["id"] for v in client.get("/api/vehicles").json()} >= {"nexon-ev", "mg-zs-ev"}
    routes = client.get("/api/routes").json()
    assert len(routes) == 4 and all("path" not in r for r in routes)
    detail = client.get("/api/routes/airport-run").json()
    assert len(detail["path"]) > 20 and detail["length_km"] > 20


def test_unknown_route_404():
    assert client.get("/api/routes/nowhere").status_code == 404


def test_stations_schema():
    s = client.get("/api/stations").json()[0]
    assert {"id", "lat", "lng", "power_kw", "connectors", "status", "uptime", "hours"} <= set(s)


def test_recommend():
    j = client.post("/api/recommend", json={"lat": 12.93, "lng": 77.62, "soc": 40}).json()
    assert j["best"]["eligibility"] == "eligible" and j["alert"]["level"] in {"ok", "plan", "charge_now"}


@pytest.mark.parametrize("body", [
    {"soc": 140}, {"lat": 200}, {"preset": "random"}, {"vehicle_id": "nope"}, {"route_id": "nowhere"},
])
def test_recommend_validation(body):
    assert client.post("/api/recommend", json=body).status_code == 422


def test_ride_state():
    j = client.post("/api/ride/state", json={"route_id": "city-commute", "start_soc": 30, "elapsed_s": 900}).json()
    assert j["telemetry"]["progress_km"] > 0 and j["recommendation"]["best"]


@pytest.mark.parametrize("body", [{"elapsed_s": -1}, {"route_id": "moon"}, {"vehicle_id": "x"}, {"start_hour": 24}])
def test_ride_state_validation(body):
    assert client.post("/api/ride/state", json=body).status_code == 422


def test_model_metrics():
    assert client.get("/api/model-metrics").status_code == 200


def test_ride_state_is_fast():
    import time
    t0 = time.perf_counter()
    for s in range(0, 7200, 600):
        client.post("/api/ride/state", json={"route_id": "mysuru-highway", "start_soc": 90, "elapsed_s": s, "limit": 200})
    assert (time.perf_counter() - t0) / 12 < 0.15
