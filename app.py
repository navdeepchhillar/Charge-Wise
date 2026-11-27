"""
app.py — Chargewise web app (FastAPI). Also the Vercel entry point.
--------------------------------------------------------------------
Run:  uvicorn app:app --port 8000      then open http://127.0.0.1:8000

Endpoints
  GET  /                    the live ride map (ui/index.html)
  GET  /api/health          status, model version, counts
  GET  /api/vehicles        vehicle profiles
  GET  /api/routes          ride routes (summary); /api/routes/{id} adds the full path
  GET  /api/stations        the synthetic station network
  POST /api/recommend       rank stations from any position + battery level
  POST /api/ride/state      simulated car after N seconds + best station from there
  GET  /api/model-metrics   queue-wait model metrics (ml/train.py output)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from chargewise import data
from chargewise.providers import ocm_enabled
from chargewise.queue_model import version as model_version
from chargewise.ranking import RankRequest, rank
from chargewise.simulator import RideRequest, ride_state

ROOT = Path(__file__).parent
STARTED = time.time()

app = FastAPI(title="Chargewise", version="2.0.0",
              description="Best and most reliable EV charging stop for a moving vehicle (synthetic data).")
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "ui" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"status": "ok", "model_version": model_version(), "stations": len(data.stations()),
            "routes": len(data.ROUTES), "vehicles": len(data.VEHICLES), "uptime_s": round(time.time() - STARTED, 1),
            "data": "synthetic", "real_stations": ocm_enabled()}


@app.get("/api/vehicles")
def vehicles():
    return [{"id": k, **v} for k, v in data.VEHICLES.items()]


@app.get("/api/routes")
def routes():
    return [{k: x for k, x in data.route_public(rid).items() if k != "path"} for rid in data.ROUTES]


@app.get("/api/routes/{route_id}")
def route_detail(route_id: str):
    if route_id not in data.ROUTES:
        raise HTTPException(404, f"Unknown route '{route_id}'")
    return data.route_public(route_id)


@app.get("/api/stations")
def stations():
    return data.stations()


@app.post("/api/recommend")
def recommend(req: RankRequest):
    if req.route_id is not None and req.route_id not in data.ROUTES:
        raise HTTPException(422, f"Unknown route '{req.route_id}'")
    try:
        return rank(req)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/ride/state")
def ride(req: RideRequest):
    try:
        return ride_state(req)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/model-metrics")
def model_metrics():
    return json.loads((ROOT / "data" / "metrics.json").read_text())
