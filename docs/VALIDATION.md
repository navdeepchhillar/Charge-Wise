# Validation

What is checked, how, and what is NOT claimed.

## Automated (`pytest`, 102 tests)

| Area | What the tests prove |
|---|---|
| Moving vehicle (the original bug) | A recommendation exists from 5 points along each of the 4 routes; distances change as the car moves; same input gives the same output. |
| Safety rules | The best station is always reachable with the reserve left; out-of-reach, offline, private, wrong-connector (CHAdeMO-only) and closed-at-arrival stations are excluded; unknown-status stations are "check first", never best. |
| Alerts | `stranded` when nothing is reachable, `charge_now` when low, `plan` when the route can't be finished on the current charge. |
| Scoring | Presets change the pick (cheapest is cheaper, fastest is faster than the median); on a route, stations ahead win over ones behind (highway U-turn cost); the current pick is sticky unless another station is clearly better; DC taper above 80%; AC is slow. |
| Simulator | Starts at the route start; never goes backwards; battery only drains; finishes; strands on the highway with 25%; a new leg after charging continues from the same km; rush hour is slower; the clock rolls over midnight and the day changes. |
| Live feed | Free plugs stay within 0..total, stable inside a 5-minute tick, change across ticks, are busier at rush hour; faults happen and exclude the station; `live=false` disables it. |
| Real stations | OpenStreetMap tags map to the schema (sockets → CCS2/Type 2/CHAdeMO, power, capacity, opening hours); 2-wheeler and battery-swap stations are dropped; unlisted power is assumed and flagged; Open Charge Map merges in with a key (duplicates within 60 m dropped); one provider failing still gives real data; all failing falls back to synthetic with a warning; results and failures are cached per area; client-supplied stations are ranked. Network mocked. |
| Road routing | OSRM distances/times replace estimates (with rush-hour slowdown), confirmed stations are routed first, one call per position (cached), failure falls back to estimates with a warning. |
| Gap filling | Known networks get likely CCS2 + Type 2 and a typical power (name or operator field); tagged data is kept and stays confirmed; only missing fields are filled; EESL/BESCOM stay unknown with a Bharat DC-001 note; missing prices are estimated by charger type and labelled; published prices kept; likely stations are usable but lose to an equally placed confirmed one; enrichment is idempotent. |
| Unconfirmed best | With no confirmed station nearby the best unconfirmed one is shown and flagged; a confirmed one always wins. |
| API | Every endpoint, 404/422 validation, page served, `/api/ride/state` under 150 ms. |

## Manual (browser)

- Onboarding: 4 steps (welcome, car, battery, mode), Back/Skip/Escape, remembered per browser.
- Simulated ride: Mysuru highway at 35%: warned at km 0 that the route can't be finished, auto-paused at ~17%, "Charge here" took it to 80% and the car finished with ~50%. Without charging it strands at km ~98.
- Live GPS with real data (fed positions, real OpenStreetMap + OSRM): Connaught Place, Delhi at 18%: 117 real stations loaded in ~9 s; best = EESL 60 kW DC (CCS2/CHAdeMO/Type 2), 9.1 km / 13 min by road, "Charge now"; distance updated as the car moved. Koramangala, Bengaluru: 29 stations; 2-wheeler chargers (Ola, Ather, swap stations) removed.
- Live GPS: real clock, battery estimate drops with distance, Navigate opens Google Maps directions from the device's location.
- Phone width (375 px): no horizontal scroll.

## Not claimed

- Stations, prices, traffic, plug availability and faults are **synthetic** (deterministic, seeded). The queue model was trained on simulated sessions (`ml/train.py`, metrics in `data/metrics.json`): test MAE 5.06 min vs 5.22 baseline. It is not validated on real chargers.
- Routes are polylines between real place coordinates, not turn-by-turn road routing.
- Open Charge Map has not been exercised with a real key. OpenStreetMap coverage and tag quality vary by city.
- Real prices and live occupancy are not available from open data.
