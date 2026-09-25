# Chargewise — EV Charging Assistant

A working EV charging demo with station filtering, explainable server-side ranking, a Leaflet map, energy scenarios, a reproducible queue model and an optional FastAPI backend.

## What works

- React dashboard with synchronized map/list selection, station details, comparison for up to three stations, profile inputs, filters and ranking preferences.
- Battery reserve, connector, private-access and operational-status exclusions.
- Explicit demo mode using nine synthetic station records in Bengaluru and illustrative route fixtures. No real chargers are implied by these fixture names.
- Synthetic queue model trained offline with scikit-learn; exported JSON inference tree is shared by the Python and hosted backends.
- Energy comparison chart, API-fed synthetic telemetry, saved vehicle profiles on the current device.
- Connected-mode adapters for Open Charge Map and OpenRouteService; missing credentials produce an explicit error rather than simulated replacements.

## Runtime architecture

The published application uses the React/Vite-based Vinext runtime and server route handlers supported by its host. The requested Python/FastAPI implementation is included in `backend/`, with SQLite profile and station-cache storage. Set `PYTHON_API_URL` to send recommendations, energy estimates and simulation requests through that backend. Both implementations use the same station fixtures and exported scikit-learn model. Pure calculation parity is tested.

This is a deliberate hosting adaptation from the initial plain Vite + FastAPI proposal. A long-running Python process and SQLite database are not part of the published edge deployment. The frontend's “Save on this device” uses browser storage in either mode; the Python profile API provides additional local database persistence.

## Start the frontend locally

Requirements: Node 22.13 or newer and pnpm.

```bash
pnpm install
pnpm dev
```

Use the localhost address printed by the development server. Demo mode requires no API key. This repository contains a Sites execution-profile helper; when moving to another environment, refresh the local profile using the installed Sites skill if the supplied framework wrapper selects an unavailable runtime. The ordinary portable entrypoint is Vite with the checked-in configuration.

## Start the Python backend

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

For frontend requests to use Python, create `.env.local` containing:

```dotenv
PYTHON_API_URL=http://127.0.0.1:8000
```

Restart the frontend. Interactive Python API docs are available at `http://127.0.0.1:8000/docs`.

Set `CHARGEWISE_DB` to change the default local database location (`backend/state/chargewise.db`). It is ignored by Git. Use a persistent disk for any standalone Python deployment. This backend is intended for local development; add authentication and deployment-level request limits before exposing profile-write APIs publicly.

## Connect external data

For the hosted adapter, configure server-side `OCM_API_KEY` and optional `ORS_API_KEY` in the hosting environment. For Python, export them in the shell running Uvicorn. Never put keys into browser code.

- Open Charge Map: https://www.openchargemap.org/develop/api
- Routing API documentation: https://openrouteservice.org/dev/
- Map tile policy: https://operations.osmfoundation.org/policies/tiles/

Switch the UI explicitly to Connected stations. Without a road-routing key, station records can be inspected, but reachability is unverified and they will not become eligible recommendations. Provider prices are retained as raw text and remain unknown for cost scoring unless safely normalized; this implementation does not try to parse arbitrary tariffs.

Connected adapters are implemented but have not been exercised with valid provider credentials in this build. Station availability is never described as live. External response schemas and terms should be checked again when connecting production accounts. Visible attribution must retain the original data provider.

## Train and evaluate the model

```bash
python ml/train.py
```

The fixed-seed generator creates session arrivals and connector service queues. Decision-tree depth is selected using validation data, then compared with an hour/day baseline. Training uses days 1–49, validation days 50–59 and test days 60–70; two stations are held out.

Outputs: `data/model.json` and `data/metrics.json`. They are checked in so demo inference works immediately. The current training run has 58,745 synthetic sessions, 5.06-minute tree test MAE, 5.22-minute baseline MAE and 2.94-minute held-out station MAE. These results demonstrate a pipeline, not real-world prediction accuracy. Busy-period test error is larger and is recorded in the metrics file.

## Verification

```bash
python -m unittest discover -s tests -v
node tests/hosted.cjs
pnpm exec tsc --noEmit
pnpm build
```

`tests/hosted.cjs` emits recommendation cases for cross-runtime comparison. `tests/test_backend.py` includes eligibility, invalid-input, unknown-data, energy, profile and simulation API tests. See `docs/VALIDATION.md` for checks performed during this build.

## Main API routes

- `GET /api/health`
- `GET /api/stations`
- `GET /api/vehicle-profiles`
- `POST /api/recommendations`
- `POST /api/energy-scenarios`
- `POST /api/simulations`
- `GET /api/simulations/{id}/telemetry`
- `GET /api/model-metrics`
- Python additionally supports `POST /api/vehicle-profiles` for SQLite persistence.

## Known limits

- No real car integration, live occupancy, real traffic, reservations, payment or vehicle control.
- Demo route fixtures are deliberately illustrative and are not road navigation. They are available only from the Bengaluru preset; other origins remain unverified without routing.
- Routing lookup is bounded to eight nearby connection records per request. Stations outside that shortlist retain an unverified route.
- The optional connected mode has limited opening-hours information. Confirm access and opening times with the operator.
- Input profiles are generic. The ranking budget uses baseline Wh/km plus auxiliary use and a 15% uncertainty margin. The separate energy chart uses fixed 1,800 kg physics assumptions, so the two estimates are not expected to be identical.
- No road-specific speed recommendation is issued without speed-limit context.
- Hosted cache and rate limiting are per instance, not a globally durable quota system. Add shared caching and provider-specific quotas for a larger deployment.
- The synthetic simulation token is not a security credential and contains only the demo scenario state; it expires after 24 hours. Python simulations are process-local and expire on restart.
- Provider station records can be stale or incomplete; operational status is not a free connector guarantee.
