"""Chargewise: pick the best and most reliable charging station for a moving EV."""
try:  # outbound HTTPS (Overpass, OSRM, Open Charge Map) trusts the OS certificate store, incl. corporate proxies
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - optional; the default certifi/OpenSSL store is used otherwise
    pass
