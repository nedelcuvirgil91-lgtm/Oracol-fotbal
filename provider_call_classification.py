"""
================================================================================
FOOTBALL ORACLE — Provider Call Failure Classification (ADR-041 Faza 2, Sprint 1.1 #3)
================================================================================
Module: provider_call_classification.py

Funcție pură, reutilizată de orice client HTTP de provider
(football_providers.py, soccerfootballinfo_client.py, oracle_api.py) — un
singur loc care traduce un răspuns HTTP eșuat sau o excepție de rețea
într-o pereche `(http_status, failure_reason)` normalizată, gata de scris
în `provider_call_log` (`supabase_client.record_provider_call()`). Fără
acest modul, fiecare client ar reimplementa propria clasificare — exact
duplicarea de cod pe care ADR-041 o interzice explicit.

`failure_reason` NU e un enum închis în schema tabelei (decizie explicită,
proprietar produs, Sprint 1.1) — valorile de mai jos sunt un vocabular
INIȚIAL, extensibil oricând, fără migrare nouă.

Contract: se apelează DOAR când apelantul știe deja că `success is False`
— nu clasifică succese (acelea nu au nevoie de `failure_reason`).
================================================================================
"""
from __future__ import annotations


def classify_failure(status_code: int | None, exc: Exception | None = None) -> tuple[int | None, str | None]:
    """`status_code`: codul HTTP dacă un răspuns a fost primit (poate fi
    `None` — eroare de rețea/timeout, niciun răspuns). `exc`: excepția
    prinsă la nivelul apelului HTTP, dacă a existat una (poate fi `None`
    — eroare HTTP „curată", fără excepție, ex. 429/403/5xx normal)."""
    if exc is not None:
        import requests
        if isinstance(exc, requests.exceptions.Timeout):
            return status_code, "timeout"
        return status_code, "network"
    if status_code is None:
        return None, None
    if status_code == 429:
        return status_code, "quota"
    if status_code == 403:
        return status_code, "forbidden"
    if 500 <= status_code < 600:
        return status_code, "upstream_5xx"
    return status_code, "other_error"
