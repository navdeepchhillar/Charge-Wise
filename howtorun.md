# How to run Chargewise

Everything runs on synthetic data out of the box: no API keys, no database, no Node.js.

## 1. Requirements

- **Python 3.10+** (3.11 recommended): check with `python3 --version`
- **Git**
- A modern browser (Chrome, Edge, Safari, Firefox)

## 2. Get the code

```bash
git clone https://github.com/navdeepchhillar/Charge-Wise.git
cd Charge-Wise
git checkout vercel-ride-sim
```

## 3. Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements.txt` is what the server needs (FastAPI + Pydantic). `requirements-dev.txt` adds uvicorn
(local server), pytest and httpx (tests).

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
| **Live GPS** | Tab **📍 Live GPS** → set battery → **Start live tracking** | Uses your real location and clock. Synthetic stations only exist around Bengaluru; elsewhere enable real stations (step 6). Phones need HTTPS, so use the Vercel URL. |

## 6. Optional: real station locations (Open Charge Map)

1. Get a free key: https://openchargemap.org/site/develop/api
2. Locally: `cp .env.example .env`, put the key after `OCM_API_KEY=`, then start with
   `OCM_API_KEY=$(grep OCM_API_KEY .env | cut -d= -f2) uvicorn app:app --port 8000`
3. On Vercel: Project → Settings → Environment Variables → `OCM_API_KEY` → **Redeploy**.
4. In the app: Live GPS → tick **Use real stations near me**.

Without a key the app keeps working with synthetic stations and says so.

## 7. Tests

```bash
pytest -q          # 61 tests, ~10 s, no network
```

## 8. Deploy to Vercel

The repo is ready as-is (`vercel.json`, `requirements.txt`, `app.py` exports `app`).

1. vercel.com → **Add New → Project** → import `Charge-Wise`.
2. Framework preset: **Other**. No build command, no output directory.
3. Settings → Git → **Production Branch** = `vercel-ride-sim` (or merge into `main`).
4. Deploy. Check `https://<project>.vercel.app/api/health` returns `"status": "ok"`.

Or from the CLI: `npm i -g vercel && vercel --prod`.

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
