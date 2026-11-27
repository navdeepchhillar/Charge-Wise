"""Filling gaps in open data: operator → plugs/power, typical prices, data-quality grades."""
import pytest

from chargewise.enrich import TYPICAL_PRICE, enrich, typical_price
from chargewise.ranking import RankRequest, rank


def st(**kw):
    base = {"id": "x", "name": "EV charging station", "lat": 12.93, "lng": 77.62, "connectors": [], "power_kw": None,
            "price_per_kwh": None, "status": "operational", "access": "public", "hours": "24x7", "count": 2,
            "category": 0, "uptime": 0.9, "amenities": [], "road": "city", "area": "", "operator": "Unknown operator"}
    base.update(kw)
    return base


@pytest.mark.parametrize("name,network", [("Tata Power EZ Charge", "Tata Power EZ Charge"), ("Statiq Hub", "Statiq"),
                                          ("CHARGE ZONE Mall", "ChargeZone"), ("Jio-bp pulse", "Jio-bp pulse"),
                                          ("Zeon Charging", "Zeon Charging"), ("Glida", "Glida (Fortum)")])
def test_known_networks_get_likely_plugs_and_power(name, network):
    e = enrich(st(name=name))
    assert e["network"] == network and e["connectors"] == ["CCS2", "Type 2"] and e["power_kw"] >= 30
    assert e["data_quality"] == "likely" and set(e["inferred"]) == {"plug type", "power"}


def test_operator_field_is_used_too():
    assert enrich(st(name="Mall parking", operator="Tata Power"))["network"] == "Tata Power EZ Charge"


def test_tagged_data_is_kept_and_confirmed():
    e = enrich(st(name="Statiq", connectors=["CCS2"], power_kw=120.0))
    assert e["connectors"] == ["CCS2"] and e["power_kw"] == 120 and e["data_quality"] == "confirmed" and e["inferred"] == []


def test_network_fills_only_missing_power():
    e = enrich(st(name="Statiq", connectors=["Type 2"], power_kw=None))
    assert e["connectors"] == ["Type 2"] and e["inferred"] == ["power"] and e["data_quality"] == "likely"


def test_bharat_dc001_networks_stay_unknown_with_a_note():
    e = enrich(st(name="EESL Charging Station"))
    assert e["connectors"] == [] and e["data_quality"] == "unknown" and "Bharat DC-001" in e["note"]
    row = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=[st(name="BESCOM EV station")]))["stations"][0]
    assert row["eligibility"] == "verify" and any("Bharat DC-001" in c for c in row["cons"])


def test_unknown_station_stays_unknown():
    assert enrich(st())["data_quality"] == "unknown"


def test_typical_prices():
    assert typical_price(7.4, ["Type 2"]) == TYPICAL_PRICE["ac"]
    assert typical_price(30, ["CCS2"]) == TYPICAL_PRICE["dc"]
    assert typical_price(60, ["CCS2"]) == TYPICAL_PRICE["dc_fast"]


def test_missing_price_is_estimated_and_labelled():
    e = enrich(st(name="Statiq", connectors=["CCS2"], power_kw=60.0))
    assert e["price_estimated"] and e["price_per_kwh"] == TYPICAL_PRICE["dc_fast"]
    row = rank(RankRequest(lat=12.93, lng=77.62, soc=40, stations=[e]))["best"]
    assert row["cost_inr"] > 0 and row["price_estimated"] and any("est. ₹22" in c for c in row["cons"])


def test_published_price_is_kept():
    e = enrich(st(connectors=["CCS2"], power_kw=60.0, price_per_kwh=18.5))
    assert e["price_per_kwh"] == 18.5 and not e["price_estimated"]


def test_likely_station_is_usable_and_explained():
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=[st(name="Tata Power EZ Charge")]))
    b = res["best"]
    assert b["eligibility"] == "eligible" and b["data_quality"] == "likely" and res["best_confirmed"] is False
    assert res["best_quality"] == "likely" and any("inferred from the operator" in c for c in b["cons"])
    assert b["charge_min"] and b["cost_inr"]


def test_confirmed_beats_equally_placed_likely():
    a = st(id="likely", name="Statiq", lat=12.931)
    b = st(id="confirmed", name="Plain", lat=12.931, lng=77.6201, connectors=["CCS2", "Type 2"], power_kw=60.0)
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50, stations=[a, b]))
    assert res["best"]["id"] == "confirmed" and res["best_confirmed"] is True


def test_synthetic_network_is_confirmed():
    res = rank(RankRequest(lat=12.93, lng=77.62, soc=50))
    assert res["best"]["data_quality"] == "confirmed" and res["best_confirmed"] is True


def test_enrich_is_idempotent():
    once = enrich(st(name="Tata Power"))
    twice = enrich(once)
    assert twice == {**once} and twice["price_estimated"] and twice["inferred"] == ["plug type", "power"]
