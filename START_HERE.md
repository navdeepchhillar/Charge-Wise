# Start here — Chargewise EV Assistant

This ZIP contains the dashboard source, Python/FastAPI backend, trained model, training script, tests and dependency lockfile.

## Run the dashboard

1. Extract this ZIP.
2. Open a terminal in the extracted `Chargewise` folder.
3. Install Node.js 22.13 or newer and pnpm if they are not already installed.
4. Run `pnpm install`.
5. Run `pnpm dev`.
6. Open the local address shown in your terminal (normally http://localhost:5173).

The demo works without API keys and without starting Python. Dependencies are downloaded during installation, so internet access is needed for that step. Map tiles also need internet access.

## Optional Python backend

Follow README.md to create a Python virtual environment, install backend/requirements.txt and start Uvicorn. Set PYTHON_API_URL in .env.local only when you want to use that running Python backend.

Do not copy the Python URL into your configuration for the standalone demo unless the Python backend is running.

## External connections

OCM_API_KEY and ORS_API_KEY are optional server-side settings. No credentials are included. Connected mode requires a real station API key; verified road reachability also needs routing access. Vehicle telemetry and waiting-time data remain simulated.

## Important files

- README.md — setup, architecture and limitations
- app/ and components/ — React dashboard and hosted API routes
- backend/ — FastAPI backend and SQLite persistence
- data/ — sample stations, trained model and measured metrics
- ml/train.py — reproducible model training
- tests/ — backend and hosted calculation tests
- docs/VALIDATION.md — validation notes

This is source code, not a standalone executable. node_modules, environment secrets, local databases, caches and generated build files are intentionally not included.
