"""Live availability feed: how many plugs are free right now, and is any charger faulted?

Real networks expose this through OCPI / operator APIs. Here it is a *simulated* feed with the same shape,
so the ranking code is written exactly as it would be against a real one:

  * refreshed every 5 minutes (a "tick"), deterministic for a given station + tick, so every user and every
    test sees the same "now";
  * busier when the queue model predicts a longer wait (rush hours, few plugs, popular sites);
  * about 2% of ticks a charger reports a fault for 15-30 minutes, which knocks the station out and forces
    the recommendation to switch: the "reroute in real time" case.

Swap `availability()` for a call to a real feed and nothing else changes.
"""
from __future__ import annotations

import hashlib
from typing import Dict

from .queue_model import predict_wait_min

TICK_MIN = 5


def _u(*parts) -> float:
    """Stable uniform [0, 1) from any key (hash-based, so no global RNG state)."""
    h = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2 ** 64


def tick_of(day: int, hour: int, minute: int) -> int:
    return ((day % 7) * 1440 + hour * 60 + minute) // TICK_MIN


def availability(station: Dict, day: int, hour: int, minute: int) -> Dict:
    total = int(station.get("count") or 1)
    tick = tick_of(day, hour, minute)
    sid = station["id"]
    # fault: a fault starting in one of the previous 3-6 ticks is still active
    for back in range(0, 6):
        t0 = tick - back
        if _u(sid, "fault", t0) < 0.02 and back < 3 + int(_u(sid, "len", t0) * 3):
            return {"free": 0, "total": total, "fault": True, "tick": tick,
                    "updated": _clock(tick), "note": f"Charger fault reported at {_clock(t0)}"}
    wait = predict_wait_min(hour, day, total, station.get("power_kw") or 7.4, station.get("category", 0))
    busy_p = min(0.95, 0.15 + wait / 25)                   # longer predicted queue ⇒ plugs more likely in use
    free = sum(1 for k in range(total) if _u(sid, "plug", k, tick) > busy_p)
    return {"free": free, "total": total, "fault": False, "tick": tick, "updated": _clock(tick), "note": None}


def _clock(tick: int) -> str:
    m = (tick * TICK_MIN) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"
