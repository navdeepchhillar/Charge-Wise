# Build verification

## Completed

- Fifteen Python core and FastAPI tests passed: compatibility, insufficient reserve, missing price, unknown route, private/offline/closed station, AC/DC limits, energy scaling, deterministic prediction, input validation, missing station key, complete recommendation/energy flow, SQLite profile persistence and simulation API.
- Browser: station map and tiles loaded; initial recommendations rendered; two-station comparison showed current battery, travel, wait, charging and cost values; the energy chart loaded actual API estimates.
- The exported queue model was trained from seed 42. Its evaluation metrics are in data/metrics.json; no real-world accuracy claim is made.

- Nine cross-runtime parity cases passed, comparing eligibility, energy, arrival battery, waiting, charging, session costs, ranking and order. Cases include low battery, alternate connectors, changed origin, complete-data filters, rush hour, reduced power and cost preference.
- TypeScript static check passed.
- Browser: low battery returned zero eligible stations; connected mode without credentials returned a clear setup error; returning to demo restored the station list.

## Not verified with real external accounts

- Open Charge Map requests with a valid account key.
- OpenRouteService requests with a valid account key.
- Actual vehicle telemetry, occupancy or traffic (not implemented).
