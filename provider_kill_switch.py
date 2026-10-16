"""
================================================================================
FOOTBALL ORACLE — Întrerupător de provider extern
================================================================================
Module: provider_kill_switch.py

Oprește apelurile HTTP către un provider extern, din configurație, **fără
deploy**. Un singur `UPDATE model_config` stinge providerul; altul îl
repornește. Rollback în câteva secunde, nu într-o rulare de CI.

**Incidentul care l-a cerut (2026-10-16).** TheSportsDB a început să întoarcă
404 pe 100% din apeluri — 443 din 443, după 0-2 eșecuri pe zi în săptămâna
dinainte. Nu rețea (ar fi timeout), nu cotă (429), nu autentificare (403):
404 pe toate cele 4 rute `.php`, peste noapte, cu codul nostru neatins.

Costul nu a fost eșecul în sine, ci **timpul**: distribuția latențelor a ieșit
strict bimodală — 327 de apeluri sub 1 s și **117 între 20 și 120 s**, nimic
între. Cele 117 (26% din apeluri) au consumat **106 din cele 109 minute**
cheltuite pe acest provider. Rularea `night_sync` a fost anulată la plafonul
de 180 de minute, după 10 rulări consecutive de 80-105 minute.

Cauza acelor 20-120 s e deja diagnosticată și NEreparată (D-9): `timeout=12`
pasat lui `requests` e timeout **între octeți**, nu total — un server care
trimite câte un octet ține conexiunea deschisă oricât. Acest modul **nu**
repară D-9; îl ocolește, oprind cererea înainte să plece.

**De ce generic și nu un flag `thesportsdb_enabled`.** Pentru că următoarea
cădere nu va fi neapărat a lui TheSportsDB. Un flag per provider ar fi cerut
cod nou la fiecare incident, exact când nu e timp de scris cod.

**De ce aici și nu la cele două locuri de apel.** Toate cele 5 endpoint-uri
TheSportsDB trec prin `oracle_api._get()`. O poartă în `_get` nu poate fi
ocolită de un endpoint adăugat mâine; două porți la apelanți, da.

**North Star #3 — respectat în literă.** Comportamentul NOU e oprirea unui
provider, iar el pornește STINS: `disabled_providers` lipsește din
`model_config`, deci mulțimea e goală și merge-ul singur nu schimbă nimic.
Oprirea cere o decizie explicită de producție, arătată și confirmată.

**Fail-open, deliberat.** Dacă citirea configurației eșuază, nu se oprește
nimic. Direcția inversă ar transforma o indisponibilitate Supabase într-o
cădere totală a tuturor providerilor — aceeași disciplină ca
`RateLimitManager`, care la header-e necunoscute lasă cererea să treacă.
================================================================================
"""
from __future__ import annotations

import logging
import time

import supabase_client as sb

logger = logging.getLogger(__name__)

# Numele cheii din `model_config.data`. Valoarea e o listă de nume de
# provider, exact cum le produce `oracle_api._detect_provider_endpoint()`
# (ex. "thesportsdb", "oddsapi", "espn") — aceeași convenție folosită deja
# de `provider_metrics` și `provider_call_log`, ca să nu existe un al doilea
# vocabular de nume de provideri.
CHEIE_CONFIG = "disabled_providers"

_DEFAULT_CONFIG = {CHEIE_CONFIG: []}

# `_get()` se apelează de sute de ori per rulare, iar `sb.load_config()` face
# un drum la Supabase de fiecare dată (verificat: fără cache). Fără TTL,
# poarta asta ar costa mai mult decât providerul pe care îl oprește.
# 300 s e compromisul: o stingere făcută în timpul unei rulări prinde efect
# în cel mult cinci minute, iar costul e ~18 citiri pe o rulare de 90 min.
TTL_SECUNDE = 300.0

_cache: tuple[float, frozenset[str]] | None = None


def _normalizeaza(brut: object) -> frozenset[str]:
    """Lista din configurație → mulțime de nume, în litere mici.

    O valoare care nu e listă (cineva scrie `"thesportsdb"` în loc de
    `["thesportsdb"]`) întoarce mulțimea goală, NU o interpretare creativă:
    un șir ar fi iterat caracter cu caracter și ar opri providerul „t"."""
    if not isinstance(brut, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(
        str(p).strip().lower() for p in brut if str(p).strip()
    )


def opriti(*, acum: float | None = None) -> frozenset[str]:
    """Mulțimea providerilor opriți, cu cache de `TTL_SECUNDE`.

    La eroare de citire se întoarce ultima valoare cunoscută, iar dacă nu
    există niciuna, mulțimea goală — fail-open."""
    global _cache
    t = time.monotonic() if acum is None else acum

    if _cache is not None and (t - _cache[0]) < TTL_SECUNDE:
        return _cache[1]

    try:
        cfg = sb.load_config(_DEFAULT_CONFIG)
        lista = _normalizeaza(cfg.get(CHEIE_CONFIG))
    except Exception as exc:
        logger.warning("[ProviderKillSwitch] citirea configurației a eșuat, "
                       "nu opresc nimic: %s", exc)
        return _cache[1] if _cache is not None else frozenset()

    _cache = (t, lista)
    return lista


def este_oprit(provider: str | None) -> bool:
    """`True` dacă providerul e oprit din configurație.

    `None`, șirul gol și `"unknown"` întorc mereu `False`: un URL al cărui
    provider nu a putut fi identificat nu are cum să fie oprit intenționat,
    iar a-l opri ar însemna să tăiem cereri la întâmplare."""
    if not provider:
        return False
    nume = provider.strip().lower()
    if not nume or nume == "unknown":
        return False
    return nume in opriti()


def goleste_cache() -> None:
    """Invalidează cache-ul. Pentru teste și pentru o stingere care trebuie
    să prindă efect imediat, fără să aștepte TTL-ul."""
    global _cache
    _cache = None
