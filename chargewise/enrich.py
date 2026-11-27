"""Filling the gaps in open station data, honestly.

Open data (OpenStreetMap, Open Charge Map) rarely has prices and, in India, often lacks the plug type and
power. Instead of leaving those blank we:

  * infer plug type / power from the operator for the main car-charging networks (marked "likely");
  * estimate the price from typical Indian public tariffs for that kind of charger (marked "est.");
  * grade every station: confirmed (from the data), likely (some fields inferred), unknown (no plug info).

Nothing here pretends to be measured: every filled field is listed in `inferred` and shown to the user.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Car-charging networks in India whose public chargers are (almost always) CCS2 DC plus Type 2 AC.
# power_kw is a conservative typical DC output, used only when the data has none.
NETWORKS: List[Tuple[re.Pattern, Dict]] = [
    (re.compile(r"tata\s*power|ez\s*charge", re.I), {"network": "Tata Power EZ Charge", "power_kw": 30}),
    (re.compile(r"statiq", re.I), {"network": "Statiq", "power_kw": 60}),
    (re.compile(r"charge\s*zone|chargezone", re.I), {"network": "ChargeZone", "power_kw": 60}),
    (re.compile(r"jio[\s-]*bp", re.I), {"network": "Jio-bp pulse", "power_kw": 60}),
    (re.compile(r"\bzeon\b", re.I), {"network": "Zeon Charging", "power_kw": 60}),
    (re.compile(r"glida|fortum", re.I), {"network": "Glida (Fortum)", "power_kw": 50}),
    (re.compile(r"shell\s*recharge", re.I), {"network": "Shell Recharge", "power_kw": 60}),
    (re.compile(r"magenta|charge\s*grid", re.I), {"network": "Magenta ChargeGrid", "power_kw": 30}),
    (re.compile(r"\b(mg\s*motor|tata\s*motors|hyundai|kia|mahindra|byd|mercedes|bmw|audi|volvo)\b", re.I),
     {"network": "Car dealership", "power_kw": 30}),
]
NETWORK_CONNECTORS = ["CCS2", "Type 2"]

# Government / utility networks that still run many Bharat DC-001 (GB/T-based) chargers, which most CCS2
# cars cannot use: keep their plug type unknown and say why.
BHARAT_DC001 = re.compile(r"\b(eesl|bescom|ntpc|nhpc|convergence|energy efficiency services|rel\b)", re.I)

# Typical public tariffs in India (₹/kWh incl. GST), used only when the station publishes no price.
TYPICAL_PRICE = {"dc_fast": 22.0, "dc": 19.0, "ac": 13.0}
DC_PLUGS = {"CCS2", "CHAdeMO", "CCS1", "Tesla", "GB/T DC"}


def typical_price(power_kw: Optional[float], connectors: List[str]) -> float:
    dc = bool(set(connectors) & DC_PLUGS) or (power_kw or 0) >= 25
    if not dc:
        return TYPICAL_PRICE["ac"]
    return TYPICAL_PRICE["dc_fast"] if (power_kw or 0) >= 50 else TYPICAL_PRICE["dc"]


def _label(st: Dict) -> str:
    return " ".join(str(st.get(k) or "") for k in ("name", "operator", "network", "brand"))


def enrich(st: Dict) -> Dict:
    """A copy of the station with gaps filled and `data_quality`, `inferred`, `network`, `price_estimated` set."""
    s = dict(st)
    label = _label(s)
    inferred: List[str] = list(dict.fromkeys(s.get("inferred") or []))
    s["network"] = s.get("network")
    s["note"] = None
    had_connectors = bool(s.get("connectors"))
    net = next((info for rx, info in NETWORKS if rx.search(label)), None)
    if net:
        s["network"] = net["network"]
        if not had_connectors:
            s["connectors"] = list(NETWORK_CONNECTORS)
            if "plug type" not in inferred:
                inferred.append("plug type")
        if s.get("power_kw") is None or s.get("power_assumed"):
            s["power_kw"] = float(net["power_kw"])
            s["power_assumed"] = False
            if "power" not in inferred:
                inferred.append("power")
    elif not had_connectors and BHARAT_DC001.search(label):
        s["note"] = "Government/utility chargers here are often Bharat DC-001, which many CCS2 cars can't use."
    if s.get("power_assumed") and "power" not in inferred:
        inferred.append("power")
    s["price_estimated"] = bool(s.get("price_estimated")) or s.get("price_per_kwh") is None   # idempotent
    if s.get("price_per_kwh") is None:
        s["price_per_kwh"] = typical_price(s.get("power_kw"), s.get("connectors") or [])
    s["inferred"] = inferred
    if not s.get("connectors"):
        s["data_quality"] = "unknown"
    elif inferred:
        s["data_quality"] = "likely"
    else:
        s["data_quality"] = "confirmed"
    return s
