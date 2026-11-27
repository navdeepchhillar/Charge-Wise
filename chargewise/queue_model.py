"""Queue-wait predictions from the synthetic decision tree trained by ml/train.py (data/model.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def model() -> dict:
    return json.loads((ROOT / "data" / "model.json").read_text())


def predict_wait_min(hour: int, day: int, count: int, power_kw: float, category: int) -> float:
    """Expected minutes waiting for a free connector at a station at that hour/day.
    Features follow model.json: hour, day_of_week, connector_count, power_kw, category."""
    m = model()
    hour, day = int(hour) % 24, int(day) % 7
    if m.get("selected") != "tree":
        return round(max(0.0, m["baseline"][f"{hour}-{day}"]), 1)
    x = [hour, day, count, power_kw, category]
    t, i = m["tree"], 0
    while t["left"][i] != -1:
        i = t["left"][i] if x[t["feature"][i]] <= t["threshold"][i] else t["right"][i]
    return round(max(0.0, float(t["value"][i])), 1)


def version() -> str:
    return model().get("version", "unknown")
