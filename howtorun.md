# How to run Chargewise

No API keys, no database, no Node.js. Simulated mode is fully offline (synthetic data); Live GPS mode uses
your real location with free public services (OpenStreetMap stations, OSRM road routing).

## 1. Requirements

- **Python 3.10+** (3.11 recommended): check with `python3 --version`
- **Git**
- A modern browser (Chrome, Edge, Safari, Firefox)

## 2. Get the code

```bash
git clone https://github.com/navdeepchhillar/Charge-Wise.git
cd Charge-Wise
git checkout develop          # staging; main = production
```

## 3. Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements.txt` is what the server needs (FastAPI, Pydantic, truststore). `requirements-dev.txt` adds
uvicorn (local server), pytest and httpx (tests).

## 4. Run

```bash
uvicorn app:app --reload --port 8000
```

Open **http://127.0.0.1:8000**. The 4-step onboarding appears on the first visit (reopen it with **⚙ Setup**).

API docs (Swagger): http://127.0.0.1:8000/docs

## 5. Try these

| Scenario | How | What you should see |
|---|---|---|
| **Run out on the highway** | Route *Highway: Bengaluru → Mysuru*, battery **35%**, speed **300×**, Start | At km 0: "You can't finish this route on the current charge". Around 17% the ride pauses: "Charge now". Press **⚡ Charge here** and it reaches Mysuru with ~50%. Skip the charge and it strands around km 98. |
| **City rush hour** | *City commute*, start **09:00** vs **14:00** | Rush hour is ~40% slower and queues are longer; the pick changes. |
| **Preference** | Switch Balanced → Cheapest → Fastest → Reliable | Different stations win; the score breakdown changes. |
| **Live faults** | Leave a ride running | Now and then a station reports a charger fault (red chip) and the pick reroutes; see the Decision log. |
| **Any spot** | Pause, click anywhere on the map | Best stop from that point. |
| **Live GPS (real data)** | Tab **📍 Live GPS** → set battery → **Start live tracking** (allow location) | "Loading real charging stations near you…" (first time in an area 10–30 s, then instant). Real stations appear on the map; the best one shows road km/minutes, reasons, and **🧭 Navigate** opens Google Maps directions from where you are. Phones need HTTPS: use the Vercel URL. |

## 6. Real data: what it uses and options

| What | Source | Key needed? |
|---|---|---|
| Your position, speed, heading | Browser Geolocation API (stays on your device, sent only to this app's API) | no |
| Charging stations | OpenStreetMap via Overpass (`amenity=charging_station`) | no |
| More stations (merged) | Open Charge Map | `OCM_API_KEY` (free: https://openchargemap.org/site/develop/api) |
| Road distance and time | OSRM `table` API (public demo server by default) | no |
| Turn-by-turn directions | Google Maps (opened by 🧭 Navigate) | no |

Optional environment variables (Vercel → Settings → Environment Variables → Redeploy; locally `export …`):

| Variable | Default | Use |
|---|---|---|
| `OCM_API_KEY` | – | merge Open Charge Map stations |
| `OSRM_URL` | `https://router.project-osrm.org` | your own OSRM server for production traffic |
| `OVERPASS_URLS` | 3 public mirrors | comma-separated Overpass endpoints (raced in parallel) |
| `OVERPASS_TIMEOUT_S` / `OSRM_TIMEOUT_S` | 25 / 4 | how long to wait before falling back |

Real-data gaps and how the app fills them: plug type and power are inferred from the operator for the
main car networks (shown as "≈ likely"); missing prices are estimated from typical tariffs (shown as
"est."); stations with no plug information stay "? unknown / check first". Live occupancy is not published
openly, so the queue is the ML estimate. 2-wheeler and battery-swap stations are filtered out. Adding an
`OCM_API_KEY` merges Open Charge Map, which often has more plug details.

## 7. Tests

```bash
pytest -q          # 102 tests, ~5 s, no network (external services are mocked)
```

## 8. Branches and deploying (Git → Vercel)

```
feature/*  ──PR──▶  develop (staging)  ──PR──▶  main (production)
```

1. Branch from `develop`: `git checkout develop && git pull && git checkout -b feature/my-change`
2. Commit, `git push -u origin feature/my-change`. Vercel builds a **preview URL** for the branch
   (shown on the pull request and in Vercel → Deployments).
3. Open a pull request into `develop`, check the preview, merge. `develop`'s preview is the staging site.
4. When staging is good, open a pull request `develop → main`. Merging it is what deploys **production**.

Vercel setup (once): Add New → Project → import `Charge-Wise`, framework preset **Other**, no build command.
Production branch = `main` (Settings → Git). `vercel.json`, `requirements.txt` and `app.py` (exports `app`)
are all it needs. Check `https://<deployment>/api/health` returns `"status": "ok"`.

## 9. Retrain the queue model (optional)

```bash
pip install -r requirements-ml.txt
python ml/train.py        # rewrites data/model.json and data/metrics.json (seed 42)
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: fastapi` | Activate the venv (`source .venv/bin/activate`) and reinstall. |
| Port already in use | `uvicorn app:app --port 8001` |
| Map is grey | The map tiles come from openstreetmap.org: check your internet connection. The API still works. |
| "Location permission was denied" | Allow location for the site in browser settings; on phones use the HTTPS (Vercel) URL. |
| "API error" pill in the header | The server isn't running or crashed: check the terminal running uvicorn. |
| "Real station data is unavailable" | Public OpenStreetMap servers are busy: wait a minute, or untick "Use real stations" to use the synthetic network. |
| `CERTIFICATE_VERIFY_FAILED` locally | Behind a corporate proxy: `pip install -r requirements.txt` (includes `truststore`, which uses your OS certificates). |
