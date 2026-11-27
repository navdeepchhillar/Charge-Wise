# Chargewise

**The best and most reliable EV charging stop from where you are *right now*, while you drive.**

Chargewise follows a car along a route (simulated, or your real GPS), watches the battery, and every
second re-ranks every charging station by how quickly, cheaply and safely it gets you charged. It explains
each choice in plain words, warns you before the battery gets critical, and avoids flip-flopping between
near-equal stations.

> **Live GPS mode uses real data:** your phone's location and clock, real charging stations around you from
> OpenStreetMap (worldwide, no key), and real road distance/time from OSRM. **Simulated mode** uses a
> synthetic, seeded Bengaluru network so the demo is repeatable. Prices and live plug occupancy are not
> published openly, so they are missing (real) or simulated (synthetic). Always check before you go.

▶ **How to run it:** [howtorun.md](howtorun.md)

---

## What it does

| | |
|---|---|
| 🚗 **Simulated ride** | A virtual car drives one of four routes (city commute, airport run, Whitefield, Bengaluru → Mysuru highway) at 10×–300× speed, with rush-hour traffic and realistic battery drain. |
| 📍 **Live GPS (real data)** | Your phone's location → real stations within ~15 km from OpenStreetMap (cached per area: the server for 30 min, the phone for 24 h) → real road km/minutes from OSRM for the nearest candidates → ranked. Battery drops as you drive (estimated from distance; correct it with the slider). 2-wheeler and battery-swap stations are filtered out. |
| 🏆 **Best stop, with reasons** | "On your route, 6 km ahead · Fast DC 60 kW · 3 of 4 plugs free right now · 98% uptime", plus warnings such as "Needs a U-turn on the highway". |
| ⚠️ **Alerts** | *Plan*: you can't finish the route on this charge. *Charge now*: battery low; the ride pauses so you can act. *Stranded*: nothing reachable. |
| ⚡ **Charge here** | Simulates the detour, queue and charge (with the DC slow-down above 80%), then continues the ride. |
| 🧭 **Navigate** | Opens Google Maps directions to the chosen station. |
| 📊 **Trip summary & decision log** | Stops, money spent, minutes charging, and every time the pick changed and why. |
| 🗺️ **Check any spot** | While paused, click the map to see the best stop from there. |
| 👋 **Onboarding** | Four "Continue" steps: welcome → your car → battery → simulated or live. |

## Architecture

```
 Browser (ui/index.html, Leaflet + vanilla JS)
   │  every ~0.6 s: POST /api/ride/state {route, car, start battery, elapsed seconds, preference…}
   │  live mode:    POST /api/recommend  {lat, lng, battery, now…}
   ▼
 FastAPI (app.py) ── stateless, one Vercel Python function
   ├─ chargewise/simulator.py   where is the car after N seconds? speed = road × rush hour × traffic;
   │                            energy = km × Wh/km × road factor; strands at 0%
   ├─ chargewise/ranking.py     scores every station from the car's position (below)
   │     ├─ chargewise/routing.py      real road km / minutes (OSRM table API), nearest candidates, cached
   │     ├─ chargewise/live.py         simulated live feed for synthetic stations: free plugs, faults
   │     ├─ chargewise/queue_model.py  ML queue wait (decision tree, data/model.json)
   │     └─ chargewise/providers.py    stations: synthetic network, or real ones (OpenStreetMap via
   │                                   Overpass, + Open Charge Map with a key), cached per ~5 km area
   ├─ chargewise/data.py        routes, vehicle profiles, synthetic station network (seeded)
   └─ chargewise/geo.py         haversine, bearings, polyline position/projection
```

**Live GPS data flow.** On the first fix in an area the browser calls `GET /api/stations/near` once
(Overpass can take 5–30 s; the server races three mirrors) and keeps the answer for 24 h. Every ~4 s it
then sends its position, battery and those stations to `POST /api/recommend`, which adds OSRM road
distances and returns the ranking in under a second. If anything external fails, the app says so and
falls back (estimated distances, or synthetic stations) instead of breaking.

**Stateless by design.** The server keeps no ride session: a ride "leg" is fully described by the route,
car, start km, start battery and start clock, and the browser sends the elapsed time. Any server instance
gives the same answer, which is what makes it work on serverless (Vercel) and scale horizontally. After a
charging stop, the browser just starts a new leg from the current km.

## How a station is ranked

For each station within the search radius, from the car's **current** position:

1. **Distance and time**: real road km and minutes from OSRM for the nearest candidates in live mode (confirmed stations first), plus a rush-hour slowdown; otherwise straight line × road factor (city 1.32, highway 1.12) at a speed by road type and hour.
2. **Energy and arrival battery**: Wh/km × 1.10 safety margin (× 1.12 on highways). Arriving below the reserve ⇒ **excluded**.
3. **Hard filters**: wrong connector, offline, private, closed when you'd arrive, or a live fault ⇒ **excluded**; unknown status/connector ⇒ **check first**. A confirmed station always beats a "check first" one; if *nothing* nearby is confirmed (common in sparse real data) the best unconfirmed one is shown, clearly labelled.
4. **Queue**: the ML model predicts the wait at your arrival hour; the live feed adjusts it (all plugs busy ⇒ at least 8 min; plugs free and you're close ⇒ much shorter).
5. **Charging time**: to your target %, at min(station kW, car kW), with DC dropping to 45% power above 80%.
6. **Cost**: kWh delivered ÷ 0.92 efficiency × ₹/kWh.
7. **Route fit**: on a route only the *extra* driving counts. Stations ahead cost ~0, stations behind cost 2× the way back (+4.5 km U-turn on highways).
8. **Score**: 7 components in 0..1 (travel, wait, charge, cost, battery buffer, reliability/uptime, detour), weighted by the preference:

| Preference | travel | wait | charge | cost | buffer | reliability | detour |
|---|---|---|---|---|---|---|---|
| Balanced | .20 | .15 | .20 | .10 | .10 | .15 | .10 |
| Fastest | .25 | .25 | .30 | – | .05 | .10 | .05 |
| Cheapest | .10 | .10 | .10 | .45 | .10 | .10 | .05 |
| Reliable | .10 | .10 | .10 | .05 | .20 | .35 | .10 |

9. **Stickiness**: the current pick gets +4 points, so it only changes when another station is clearly better.

## API

| Method | Path | |
|---|---|---|
| GET | `/` | the app |
| GET | `/api/health` | status, model version, station count, whether real stations are enabled |
| GET | `/api/vehicles` · `/api/routes` · `/api/routes/{id}` · `/api/stations` | reference data |
| GET | `/api/stations/near?lat=&lng=` | real stations around a point (OpenStreetMap / Open Charge Map) |
| POST | `/api/recommend` | rank stations from any `lat, lng, soc` (+ `route_id`, `progress_km`, `preset`, `source`, `stations`, `road_routing`, …) |
| POST | `/api/ride/state` | simulated telemetry after `elapsed_s` + the recommendation from there |
| GET | `/api/model-metrics` | queue model metrics |

Interactive docs at `/docs` (FastAPI Swagger UI).

## Project layout

```
app.py                 FastAPI app + Vercel entry point
chargewise/            engine: geo, data, simulator, ranking, live feed, providers, queue model
ui/index.html          single-page app (no build step)
data/                  stations.json (9 fixtures), model.json (queue tree), metrics.json
ml/train.py            retrains the queue model (needs requirements-ml.txt)
tests/                 82 pytest tests (external services mocked)
docs/VALIDATION.md     what is tested and what is not claimed
```

## From the previous version

The original was a ChatGPT "Sites" app (vinext + Cloudflare Workers) that could not deploy to Vercel, and its
Python core only computed distances from one fixed starting point: move more than 300 m and every station lost
its distance, so a moving car never got a recommendation. This version replaces it with a single
FastAPI service + static page, computes everything from the live position, and adds the ride simulator, live
feed, alerts, stickiness, route awareness and live GPS. The trained queue model is reused unchanged.

## Branches and deployments

```
feature/*  ──PR──▶  develop  ──PR (after review)──▶  main
   │                   │                               │
 Vercel preview      Vercel preview = staging         Vercel production
```

- Work happens on `feature/<name>` branches and is merged into `develop` through a pull request.
- Every pushed branch gets its own Vercel **preview** URL, so it can be tested before it goes anywhere.
- `develop` is the staging site. `main` is **production** and only changes when the `develop → main`
  pull request is approved and merged. Nothing is deployed to production directly.

## Roadmap (real-world)

- Real plug availability and prices via OCPI / operator APIs (Tata Power EZ Charge, Statiq, ChargeZone…):
  swap `live.availability()` and fill `price_per_kwh`; nothing else changes.
- Own OSRM / Overpass instances (set `OSRM_URL`, `OVERPASS_URLS`) for production traffic.
- Elevation and temperature in consumption.
- Car telemetry (OBD / manufacturer APIs) instead of distance-based battery estimates.
- Retrain the queue model on real session logs; reliability from real uptime history.
- Accounts: saved cars, favourite networks, charging cards, trip history.
