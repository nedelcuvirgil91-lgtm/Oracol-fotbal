"""
================================================================================
FOOTBALL ORACLE — Din ce nivel al cascadei vine profilul, la meciurile de cupă?
================================================================================
Module: scripts/report_cup_profile_sources.py

STRICT read-only. Nu scrie nimic, nicăieri.

DE CE EXISTĂ: `_build_profile()` alege sursa unui profil dintr-o cascadă de
niveluri (istoric Supabase → statistici de națională → clasament Flashscore →
context de meci Flashscore → FreeLF → football-data → neutru). Nivelul ales e
decisiv pentru calitatea predicției, dar NU e agregat nicăieri — ca să răspunzi
la „de ce n-are echipa asta date?" trebuia până acum o investigație manuală, cu
patru interogări scrise pe loc.

Întrebarea căreia îi răspunde, pentru Champions/Europa/Conference League acum
că a început faza principală: câte echipe sunt servite de fiecare nivel, și
care rămân sub ultimul nivel util.

Scriptul NU repară nimic și NU schimbă nicio predicție. E un instrument de
măsură: pașii următori (reordonarea cascadei pentru cupe, ponderarea formei
după forța adversarului) se decid pe cifrele lui, nu pe intuiție — și fiecare
cere ADR propriu.

**Fidelitate față de motor**: apelează EXACT aceleași funcții de citire ca
`_build_profile()`, în aceeași ordine, cu același prag. Partea de date nu poate
diverge. Ce se poate desincroniza e ORDINEA nivelurilor și PRAGUL, dacă motorul
se schimbă — de aceea `tests/test_report_cup_profile_sources.py` verifică
pragul citind sursa motorului, nu o constantă copiată aici.

Utilizare:
    python scripts/report_cup_profile_sources.py
    python scripts/report_cup_profile_sources.py --zile 30
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

CUPE = ("Champions League", "Europa League", "Conference League")

# Pragul de la care Level DB (istoric Supabase) e considerat suficient.
# Oglindește `MIN_DB_MATCHES` din `oracle_engine._build_profile()`; un test
# citește sursa motorului și cade dacă cele două se despart.
PRAG_ISTORIC_DB = 3

# Ordinea EXACTĂ din `_build_profile()`. Primul nivel care produce statistici
# câștigă; restul nici nu se mai interoghează.
NIVEL_DB       = "supabase-history"
NIVEL_NATIONAL = "national-stats-hardcoded"
NIVEL_FS       = "flashscore-standings"
NIVEL_FS2      = "flashscore-match-context"
NIVEL_SUB_FS2  = "sub-FS2 (FreeLF / football-data / neutru)"

ORDINEA_NIVELURILOR = (NIVEL_DB, NIVEL_NATIONAL, NIVEL_FS, NIVEL_FS2, NIVEL_SUB_FS2)


def nivel_servit(echipa: str, competitie: str, *, citeste_istoric, citeste_national,
                 citeste_clasament, citeste_context, prag_db: int = PRAG_ISTORIC_DB) -> str:
    """Ce nivel al cascadei ar servi profilul acestei echipe, ACUM.

    Cititoarele sunt injectate — de aceea funcția se testează fără Supabase, iar
    în producție primește exact funcțiile pe care le folosește motorul."""
    istoric = citeste_istoric(echipa, competitie) or []
    if len(istoric) >= prag_db:
        return NIVEL_DB

    if citeste_national(echipa):
        return NIVEL_NATIONAL

    rand = citeste_clasament(echipa, competitie)
    # Motorul cere formă NEvidă, nu doar existența rândului: un clasament la
    # runda 0 (toate cupele acum) are `played=0` și formă goală, iar un
    # `results=[]` ar produce form_score=0.0 — cel mai rău caz, nu neutru.
    if rand and (rand.get("form") or []):
        return NIVEL_FS

    if citeste_context(echipa):
        return NIVEL_FS2

    return NIVEL_SUB_FS2


def _echipe_din_cupe(client, zile: int) -> dict[str, set[str]]:
    """`competiție -> set de echipe` cu meciuri în fereastra cerută."""
    from datetime import datetime, timedelta, timezone

    de_la = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    pana_la = (datetime.now(timezone.utc) + timedelta(days=zile)).date().isoformat()

    iesire: dict[str, set[str]] = {c: set() for c in CUPE}
    randuri = (
        client.table("match_history")
        .select("league,home_team,away_team,kickoff_date")
        .in_("league", list(CUPE))
        .gte("kickoff_date", de_la)
        .lte("kickoff_date", pana_la + "T23:59:59")
        .execute()
    ).data or []
    for r in randuri:
        liga = str(r.get("league") or "")
        if liga in iesire:
            for cheie in ("home_team", "away_team"):
                nume = str(r.get(cheie) or "").strip()
                if nume:
                    iesire[liga].add(nume)
    return iesire


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Din ce nivel al cascadei vine profilul, la meciurile de cupă")
    parser.add_argument("--zile", type=int, default=14,
                        help="fereastra de meciuri viitoare analizată (implicit 14)")
    args = parser.parse_args()

    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from database.queries import (get_client, get_team_recent_form_context,
                                  get_team_standings_row)
    from mappings import NATIONAL_TEAM_STATS

    client = get_client()
    if client is None:
        print("EROARE: client Supabase indisponibil.")
        return 1

    def citeste_istoric(echipa, competitie):
        return sb.get_team_recent_results(echipa, competitie, 5)

    def citeste_national(echipa):
        return NATIONAL_TEAM_STATS.get(echipa)

    def citeste_clasament(echipa, competitie):
        try:
            return get_team_standings_row(echipa, competitie)
        except Exception:
            return None

    def citeste_context(echipa):
        try:
            return get_team_recent_form_context(echipa, n=5)
        except Exception:
            return []

    print(BAR)
    print("  SURSA PROFILULUI LA MECIURILE DE CUPĂ — raport read-only")
    print(f"  Fereastră: următoarele {args.zile} zile · prag Level DB: {PRAG_ISTORIC_DB} meciuri")
    print(BAR)

    pe_cupa = _echipe_din_cupe(client, args.zile)
    total = Counter()
    ramase_jos: list[tuple[str, str]] = []

    for competitie in CUPE:
        echipe = sorted(pe_cupa.get(competitie, set()))
        if not echipe:
            print(f"\n  {competitie}: niciun meci în fereastră.")
            continue

        numaratoare = Counter()
        for echipa in echipe:
            nivel = nivel_servit(
                echipa, competitie,
                citeste_istoric=citeste_istoric, citeste_national=citeste_national,
                citeste_clasament=citeste_clasament, citeste_context=citeste_context,
            )
            numaratoare[nivel] += 1
            total[nivel] += 1
            if nivel == NIVEL_SUB_FS2:
                ramase_jos.append((competitie, echipa))

        print(f"\n  {competitie} — {len(echipe)} echipe")
        for nivel in ORDINEA_NIVELURILOR:
            n = numaratoare.get(nivel, 0)
            if n:
                print(f"    {nivel:<42s} {n:>3d}  ({100.0 * n / len(echipe):.0f}%)")

    n_total = sum(total.values())
    if n_total:
        print("\n" + BAR)
        print(f"  TOTAL — {n_total} profile de echipă")
        for nivel in ORDINEA_NIVELURILOR:
            n = total.get(nivel, 0)
            if n:
                print(f"    {nivel:<42s} {n:>3d}  ({100.0 * n / n_total:.0f}%)")

    if ramase_jos:
        print("\n" + BAR)
        print(f"  ECHIPE SUB ULTIMUL NIVEL UTIL — {len(ramase_jos)}")
        print("  (profil construit din valori implicite; predicția lor nu poartă")
        print("   informație reală despre echipă)")
        for competitie, echipa in ramase_jos:
            print(f"    {competitie:<20s} {echipa}")
    else:
        print("\n  Nicio echipă sub ultimul nivel util.")

    print(BAR)
    print("  Raport încheiat. ZERO scriere efectuată.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
