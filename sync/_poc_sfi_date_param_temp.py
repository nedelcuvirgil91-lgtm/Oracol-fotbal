"""
================================================================================
POC TEMPORAR — formatul parametrului `d` la Soccer Football Info
================================================================================
Fișier: sync/_poc_sfi_date_param_temp.py

SE ȘTERGE după închiderea investigației (tiparul stabilit în CLAUDE.md,
§„Regulile pentru chei API"). Dovada rămâne în istoricul rulărilor GitHub
Actions + CHANGELOG, nu ca infrastructură vie.

────────────────────────────────────────────────────────────────────────────
DE CE EXISTĂ
────────────────────────────────────────────────────────────────────────────
Rularea `night_sync` din 26 oct a produs, prin ADR-081, primul corp de răspuns
al eșecurilor SFI:

    {"status":400,"errors":[{"code":8,"message":"Wrong d param"}],
     "pagination":[],"result":[]}

Deci NU e „not subscribed" (cheia e validă — RapidAPI a autentificat și a rutat
cererea până la backend, care a răspuns cu un corp parsat). E un parametru
respins. Codul de producție trimite `d` ca `YYYYMMDD`. Ultimul succes: 10 oct
08:20:04. Primul 400: 11 oct 08:37:03. Zero commit-uri de-ale noastre între 8 și
12 oct → schimbarea e la provider.

Ce NU știm: care e formatul acceptat ACUM. Documentația publică nu a putut fi
găsită. Sonda asta întreabă providerul, în loc să ghicim.

────────────────────────────────────────────────────────────────────────────
IZOLARE (regulile din CLAUDE.md, §POC)
────────────────────────────────────────────────────────────────────────────
  · NU importă `key_manager.py`, `soccerfootballinfo_client.py`,
    `cache_manager.py`, `request_manager.py`, `supabase_client.py`.
  · NU scrie nimic — nici în Supabase, nici în cache, nici pe disc.
  · NU e importat de niciun cod de producție.
  · NU modifică niciun workflow existent; rulează doar `workflow_dispatch`.
  · Citește cheia DIRECT din mediu. Cheia nu e tipărită NICIODATĂ — se tipărește
    exclusiv corpul RĂSPUNSULUI, despre care avem deja dovada (ADR-081) că nu
    conține secrete: cheia circulă doar în header-ul de CERERE.

────────────────────────────────────────────────────────────────────────────
BUGET — mărginit DUR, nu prin disciplină
────────────────────────────────────────────────────────────────────────────
SFI are 200 de apeluri/lună; `api_provider_status` arată 129 consumate pe
2026-10, deci ~71 rămase. Sonda cheltuie CEL MULT 6, iar contorul e impus în
cod (`_BUGET_MAXIM_APELURI`), nu lăsat pe seama structurii buclelor.

Se oprește la PRIMUL succes — nu cheltuie restul degeaba.

────────────────────────────────────────────────────────────────────────────
CE MĂSOARĂ, ȘI DE CE E AUTO-VALIDANTĂ
────────────────────────────────────────────────────────────────────────────
FAZA A (5 apeluri): aceeași dată, cinci formate — inclusiv formatul ACTUAL de
producție, ca martor de control. Asta face experimentul interpretabil fără
ipoteze ajutătoare:

    · controlul cade ȘI un alt format trece  → formatul s-a schimbat. Răspuns.
    · controlul TRECE                        → formatul e bun, iar cauza celor
                                               400 din producție e ALTA (data de
                                               AZI, nu formatul). Semnal diferit,
                                               la fel de util.
    · toate cinci cad                        → nu e formatul. Treci la FAZA B.

Fără martorul de control, un „ISO a mers" n-ar fi dovedit că vechiul format nu
mergea — ar fi fost o corelație, nu o comparație.

FAZA B (1 apel, DOAR dacă toate cele 5 din A cad): formatul de producție pe o
dată din perioada în care apelurile reușeau (9 oct). Distinge „providerul a
restrâns fereastra de date acceptate" de „endpoint-ul e mort indiferent de ce
trimitem".

NICIO reparație nu se face din acest fișier. Produce un verdict citit de om.
================================================================================
"""
from __future__ import annotations

import os
import sys

import requests

# ── Constante copiate DELIBERAT, nu importate ───────────────────────────────
# Importul din `soccerfootballinfo_client` ar lega POC-ul de producție (interzis
# de regulă) ȘI ar face sonda să testeze accidental altceva decât crede, dacă
# fișierul acela se schimbă între timp. Valorile sunt citate exact, cu sursa.
_BASE_URL = "https://soccer-football-info.p.rapidapi.com"   # client:41
_HOST = "soccer-football-info.p.rapidapi.com"               # key_manager PROVIDERS
_ENDPOINT = "matches/day/full/"                             # client:189
_TIMEOUT = 12                                               # client:141
_ENV_CHEIE = "RAPIDAPI_KEY_FREELIVEFOOTBALL"                # key_manager:40

_BUGET_MAXIM_APELURI = 6

# Dată recentă cu meciuri certe, folosită pentru TOATE formatele din Faza A.
# Aceeași dată peste tot — altfel am varia două lucruri simultan.
_DATA_FAZA_A = (2026, 10, 25)
# Dată din perioada în care apelurile de producție REUȘEAU (ultimul succes
# cunoscut: 10 oct 08:20:04). Folosită doar în Faza B.
_DATA_FAZA_B = (2026, 10, 9)


def _formate(an: int, luna: int, zi: int) -> list[tuple[str, str]]:
    """(eticheta, valoarea lui `d`). Primul e MARTORUL DE CONTROL — exact ce
    trimite producția azi (`date_iso.replace("-", "")`, client:188)."""
    return [
        ("CONTROL · YYYYMMDD (producție azi)", f"{an:04d}{luna:02d}{zi:02d}"),
        ("ISO · YYYY-MM-DD",                   f"{an:04d}-{luna:02d}-{zi:02d}"),
        ("punctat · DD.MM.YYYY",               f"{zi:02d}.{luna:02d}.{an:04d}"),
        ("slash · DD/MM/YYYY",                 f"{zi:02d}/{luna:02d}/{an:04d}"),
        ("slash invers · YYYY/MM/DD",          f"{an:04d}/{luna:02d}/{zi:02d}"),
    ]


class _Buget:
    """Plafonul e o stare explicită, nu o proprietate a buclelor. O buclă
    rescrisă greșit mâine lovește plafonul; una care doar „arată corect" nu e
    o garanție."""

    def __init__(self, maxim: int) -> None:
        self.maxim = maxim
        self.folosite = 0

    def consuma(self) -> None:
        if self.folosite >= self.maxim:
            raise RuntimeError(
                f"buget epuizat ({self.maxim} apeluri) — sonda se oprește "
                f"înainte de a mai cheltui din cota lunară"
            )
        self.folosite += 1


def _incearca(sesiune, cheie: str, valoare_d: str, buget: _Buget) -> dict:
    """Un singur apel. Întoarce un dicționar de raport; nu aruncă pe eroare de
    rețea — o sondă care moare la prima excepție nu mai spune nimic despre
    restul formatelor."""
    buget.consuma()
    antete = {"x-rapidapi-key": cheie, "x-rapidapi-host": _HOST}
    try:
        r = sesiune.get(f"{_BASE_URL}/{_ENDPOINT}", headers=antete,
                        params={"d": valoare_d}, timeout=_TIMEOUT)
    except Exception as exc:                      # noqa: BLE001 — raport, nu control de flux
        return {"status": None, "eroare": repr(exc), "corp": "", "meciuri": None}

    corp = " ".join((r.text or "").split())[:400]
    meciuri = None
    if r.ok:
        try:
            rezultat = r.json().get("result")
            meciuri = len(rezultat) if isinstance(rezultat, list) else None
        except Exception:                          # noqa: BLE001
            meciuri = None
    return {"status": r.status_code, "eroare": None, "corp": corp, "meciuri": meciuri}


def _raporteaza(eticheta: str, valoare_d: str, rez: dict) -> bool:
    reusit = rez["status"] == 200 and rez["eroare"] is None
    marcaj = "✅" if reusit else "❌"
    print(f"  {marcaj} {eticheta}")
    print(f"     d = {valoare_d!r}")
    if rez["eroare"]:
        print(f"     excepție: {rez['eroare']}")
    else:
        print(f"     HTTP {rez['status']}"
              + (f" · {rez['meciuri']} meciuri în result" if rez["meciuri"] is not None else ""))
        print(f"     corp: {rez['corp'] or '<corp gol>'}")
    print()
    return reusit


def main() -> int:
    cheie = os.environ.get(_ENV_CHEIE, "").strip()
    if not cheie:
        print(f"⛔ {_ENV_CHEIE} absentă din mediu — sonda nu pleacă în rețea.")
        return 2

    buget = _Buget(_BUGET_MAXIM_APELURI)
    sesiune = requests.Session()   # fără Retry: o reîncercare ar cheltui din cotă

    print("=" * 78)
    print("SONDĂ SFI — formatul parametrului `d`")
    print(f"endpoint: {_ENDPOINT} · buget maxim: {_BUGET_MAXIM_APELURI} apeluri")
    print("=" * 78)
    print()
    print(f"FAZA A — aceeași dată ({_DATA_FAZA_A[0]}-{_DATA_FAZA_A[1]:02d}-"
          f"{_DATA_FAZA_A[2]:02d}), cinci formate, martorul de control primul")
    print()

    castigator = None
    controlul_a_trecut = False
    for i, (eticheta, valoare) in enumerate(_formate(*_DATA_FAZA_A)):
        rez = _incearca(sesiune, cheie, valoare, buget)
        a_trecut = _raporteaza(eticheta, valoare, rez)
        if a_trecut:
            if i == 0:
                controlul_a_trecut = True
            castigator = (eticheta, valoare, rez)
            break   # primul succes oprește cheltuiala

    print("-" * 78)

    if castigator and controlul_a_trecut:
        print("VERDICT: formatul ACTUAL de producție FUNCȚIONEAZĂ pe o dată recentă.")
        print("         Deci cauza celor 400 din producție NU e formatul — e data")
        print("         cerută (producția cere ZIUA CURENTĂ) sau altceva legat de ea.")
        print("         ⚠ NU schimba formatul în cod pe baza acestui rezultat.")
    elif castigator:
        eticheta, valoare, _ = castigator
        print(f"VERDICT: formatul acceptat e «{eticheta}» → d = {valoare!r}")
        print("         Martorul de control a CĂZUT pe aceeași dată, deci e o")
        print("         comparație, nu o coincidență. Reparația e un singur loc:")
        print("         `soccerfootballinfo_client.get_matches_for_day()`, linia 188.")
    else:
        print("Toate cele 5 formate au căzut pe aceeași dată → NU e formatul.")
        print()
        print(f"FAZA B — formatul de producție pe o dată din perioada în care")
        print(f"         apelurile reușeau ({_DATA_FAZA_B[0]}-{_DATA_FAZA_B[1]:02d}-"
              f"{_DATA_FAZA_B[2]:02d})")
        print()
        _, valoare = _formate(*_DATA_FAZA_B)[0]
        rez = _incearca(sesiune, cheie, valoare, buget)
        a_trecut = _raporteaza("CONTROL · YYYYMMDD, pe dată cunoscut-bună",
                               valoare, rez)
        print("-" * 78)
        if a_trecut:
            print("VERDICT: formatul e bun, providerul a RESTRÂNS fereastra de date.")
            print("         Decizia devine «ce fereastră cerem», nu «ce format».")
        else:
            print("VERDICT: endpoint-ul respinge și formatul, și data cunoscut-bună.")
            print("         Cauza e mai adâncă (plan/abonament/endpoint retras) și")
            print("         cere audit de cheie — ramura pe care corpul de la 26 oct")
            print("         păruse s-o elimine. De reevaluat atunci, nu acum.")

    print()
    print(f"Apeluri consumate: {buget.folosite} din {_BUGET_MAXIM_APELURI} "
          f"(cotă lunară SFI: 200, ~71 rămase înainte de rulare).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
