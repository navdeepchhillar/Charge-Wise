# Validation

What is checked, how, and what is NOT claimed.

## Automated (`pytest`, 61 tests)

| Area | What the tests prove |
|---|---|
| Moving vehicle (the original bug) | A recommendation exists from 5 points along each of the 4 routes; distances change as the car moves; same input gives the same output. |
| Safety rules | The best station is always reachable with the reserve left; out-of-reach, offline, private, wrong-connector (CHAdeMO-only) and closed-at-arrival stations are excluded; unknown-status stations are "check first", never best. |
| Alerts | `stranded` when nothing is reachable, `charge_now` when low, `plan` when the route can't be finished on the current charge. |
| Scoring | Presets change the pick (cheapest is cheaper, fastest is faster than the median); on a route, stations ahead win over ones behind (highway U-turn cost); the current pick is sticky unless another station is clearly better; DC taper above 80%; AC is slow. |
| Simulator | Starts at the route start; never goes backwards; battery only drains; finishes; strands on the highway with 25%; a new leg after charging continues from the same km; rush hour is slower; the clock rolls over midnight and the day changes. |
| Live feed | Free plugs stay within 0..total, stable inside a 5-minute tick, change across ticks, are busier at rush hour; faults happen and exclude the station; `live=false` disables it. |
| Real stations | Open Charge Map records map to the station schema; without a key or on a network error the app falls back to synthetic stations with a warning; responses are cached (one call for nearby positions). Network is mocked; no key needed. |
| API | Every endpoint, 404/422 validation, page served, `/api/ride/state` under 150 ms. |

## Manual (browser)

- Onboarding: 4 steps (welcome, car, battery, mode), Back/Skip/Escape, remembered per browser.
- Simulated ride: Mysuru highway at 35%: warned at km 0 that the route can't be finished, auto-paused at ~17%, "Charge here" took it to 80% and the car finished with ~50%. Without charging it strands at km ~98.
- Live GPS (with a fed location): real clock, battery estimate drops with distance, Navigate opens Google Maps.
- Phone width (375 px): no horizontal scroll.

## Not claimed

- Stations, prices, traffic, plug availability and faults are **synthetic** (deterministic, seeded). The queue model was trained on simulated sessions (`ml/train.py`, metrics in `data/metrics.json`): test MAE 5.06 min vs 5.22 baseline. It is not validated on real chargers.
- Routes are polylines between real place coordinates, not turn-by-turn road routing.
- Open Charge Map has not been exercised with a real key in CI.
