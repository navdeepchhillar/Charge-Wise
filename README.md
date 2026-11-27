# Chargewise

**The best and most reliable EV charging stop from where you are *right now*, while you drive.**

Chargewise follows a car along a route (simulated, or your real GPS), watches the battery, and every
second re-ranks every charging station by how quickly, cheaply and safely it gets you charged. It explains
each choice in plain words, warns you before the battery gets critical, and avoids flip-flopping between
near-equal stations.

> All station, price, traffic and plug-availability data is synthetic (deterministic, seeded) unless you
> add an Open Charge Map key for real station locations. Not for real navigation.

▶ **How to run it:** [howtorun.md](howtorun.md)

---

## What it does

| | |
|---|---|
| 🚗 **Simulated ride** | A virtual car drives one of four routes (city commute, airport run, Whitefield, Bengaluru → Mysuru highway) at 10×–300× speed, with rush-hour traffic and realistic battery drain. |
| 📍 **Live GPS** | Uses your phone's location. Battery drops as you drive (estimated from distance); recommendations use your real clock. |
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
   │     ├─ chargewise/live.py         live feed: free plugs per 5-min tick, occasional faults
   │     ├─ chargewise/queue_model.py  ML queue wait (decision tree, data/model.json)
   │     └─ chargewise/providers.py    stations: synthetic network, or Open Charge Map (cached 10 min)
   ├─ chargewise/data.py        routes, vehicle profiles, synthetic station network (seeded)
   └─ chargewise/geo.py         haversine, bearings, polyline position/projection
```

**Stateless by design.** The server keeps no ride session: a ride "leg" is fully described by the route,
car, start km, start battery and start clock, and the browser sends the elapsed time. Any server instance
gives the same answer, which is what makes it work on serverless (Vercel) and scale horizontally. After a
charging stop, the browser just starts a new leg from the current km.

## How a station is ranked

For each station within the search radius, from the car's **current** position:

1. **Distance and time**: straight line × road factor (city 1.32, highway 1.12); speed by road type and hour.
2. **Energy and arrival battery**: Wh/km × 1.10 safety margin (× 1.12 on highways). Arriving below the reserve ⇒ **excluded**.
3. **Hard filters**: wrong connector, offline, private, closed when you'd arrive, or a live fault ⇒ **excluded**; unknown status/connector ⇒ **check first** (never chosen as best).
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
| POST | `/api/recommend` | rank stations from any `lat, lng, soc` (+ `route_id`, `progress_km`, `preset`, `source`, …) |
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
tests/                 61 pytest tests
docs/VALIDATION.md     what is tested and what is not claimed
```

## From the previous version

The original was a ChatGPT "Sites" app (vinext + Cloudflare Workers) that could not deploy to Vercel, and its
Python core only computed distances from one fixed starting point: move more than 300 m and every station lost
its distance, so a moving car never got a recommendation. This version replaces it with a single
FastAPI service + static page, computes everything from the live position, and adds the ride simulator, live
feed, alerts, stickiness, route awareness and live GPS. The trained queue model is reused unchanged.

## Roadmap (real-world)

- Real plug availability via OCPI / operator APIs (swap `live.availability()`; nothing else changes).
- Road routing (OSRM/OpenRouteService) instead of road factors; elevation and temperature in consumption.
- Car telemetry (OBD / manufacturer APIs) instead of distance-based battery estimates.
- Retrain the queue model on real session logs; reliability from real uptime history.
- Accounts: saved cars, favourite networks, charging cards, trip history.
