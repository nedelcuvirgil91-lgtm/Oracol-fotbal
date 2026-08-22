"""
================================================================================
FOOTBALL ORACLE — Cat de gresit e ELO-ul persistat? (masuratoare, ZERO scriere)
================================================================================
Module: scripts/measure_elo_divergence.py

STRICT read-only. Nu scrie nimic, nicaieri. Nu modifica `mappings.py`, nu
atinge Supabase decat prin SELECT-uri.

DE CE EXISTA: reconcilierea identitatii (ADR-025 Faza 3+4, executata
2026-08-22) a scos 403 meciuri duplicate din replay. De acum inainte,
replay-ul ELO e corect. DAR `run_backfill()` e NULL-only prin design
(gating v4.1, `_missing_feature_columns`) — nu recalculeaza niciodata o
coloana deja populata. Deci valorile ELO scrise INAINTE de reconciliere raman
exact cum erau: calculate pe lanturi fragmentate, cu meciuri numarate de doua
ori.

S-a demonstrat CALITATIV ca problema e reala ("Zwolle" si "PEC Zwolle" au
rulat lanturi paralele 2021-2025; "Liverpool" = 1960 vs "Liverpool FC (ENG)"
= 1615 in acelasi meci). Nu s-a masurat niciodata CU CAT greseste. Acest
script produce acea cifra — singura care poate decide daca rebuild-ul e
urgent, cosmetic sau undeva la mijloc.

Rebuild-ul e singura operatie ireversibila din tot lantul (cere reset
distructiv al coloanelor inainte de replay, fiindca backfill-ul e NULL-only).
"Masuram de doua ori, taiem o data": aceasta e masuratoarea.

CUM: reproduce replay-ul ELO folosind EXACT componentele de productie —
`fetch_all_matches()` (acelasi filtru: rezultat non-NULL, superseded exclus,
ordonare cronologica) si `ELOTracker` (aceeasi clasa, nemodificata). Ordinea
apelurilor e identica cu cea din `run_backfill()`:
    home_elo, away_elo = tracker.get_elos_before_match(home, away)
    tracker.process_match(home, away, hg, ag, result)
    home_elo_after = round(tracker.get_elo(home))
Apoi compara valoarea RECALCULATA cu cea PERSISTATA, rand cu rand.

SCOP DECLARAT: masoara DOAR ELO (`home_elo`/`away_elo` pre-meci si
`home_elo_after`/`away_elo_after` post-meci). NU masoara off/def ratings,
forma, H2H sau mediile recente — acelea depind si de weights/config incarcate
din Supabase si ar cere reproducerea intregului `team_pre_match_rating()`.
ELO e insa cel mai important: intra direct in `ml_predictor.FEATURE_COLUMNS`
(ca `home_elo`/`away_elo`) SI in servirea live (ca `home_elo_after`, prin
`database.queries.get_latest_team_elo`).

Utilizare:
    python scripts/measure_elo_divergence.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Praguri de interpretare, alese explicit (nu magice):
#   - ELO-ul initial e 1500 si un meci muta tipic 10-30 de puncte
#     (K-factor din `backfill_features`), deci o diferenta sub 5 puncte e
#     zgomot de rotunjire acumulat, fara efect practic asupra unei predictii.
#   - Peste 50 de puncte, diferenta e comparabila cu avantajul de teren propriu
#     si schimba material probabilitatile Poisson/Elo.
PRAG_NEGLIJABIL = 5
PRAG_MATERIAL = 50


def _pct(part: int, total: int) -> str:
    return f"{(100.0 * part / total):.1f}%" if total else "n/a"


def summarize(diffs: list[int]) -> dict:
    """Statistici pe o lista de diferente absolute. Functie PURA — testabila
    fara Supabase (`tests/test_measure_elo_divergence.py`)."""
    if not diffs:
        return {"n": 0, "zero": 0, "neglijabil": 0, "material": 0,
                "max": 0, "media": 0.0, "mediana": 0, "p95": 0}
    s = sorted(diffs)
    n = len(s)
    return {
        "n": n,
        "zero": sum(1 for d in s if d == 0),
        "neglijabil": sum(1 for d in s if 0 < d < PRAG_NEGLIJABIL),
        "material": sum(1 for d in s if d >= PRAG_MATERIAL),
        "max": s[-1],
        "media": sum(s) / n,
        "mediana": s[n // 2],
        "p95": s[min(n - 1, int(n * 0.95))],
    }


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from sync.backfill_features import ELOTracker, fetch_all_matches

    print(BAR)
    print("  MASURATOARE — divergenta ELO persistat vs. recalculat")
    print("  ZERO scriere. Foloseste ELOTracker si fetch_all_matches de productie.")
    print(BAR)

    matches = fetch_all_matches(None)
    if not matches:
        print("EROARE: niciun meci returnat de fetch_all_matches().")
        return 1
    print(f"  Meciuri in replay (post-reconciliere): {len(matches)}")

    tracker = ELOTracker()
    pre_diffs: list[int] = []
    post_diffs: list[int] = []
    # {echipa: (diferenta_absoluta, elo_persistat, elo_recalculat, data)} pentru
    # ULTIMUL meci al fiecarei echipe — adica exact valoarea pe care o serveste
    # `get_latest_team_elo()` in productie.
    ultima_stare: dict[str, tuple[int, int, int, str]] = {}
    randuri_comparate = 0

    for m in matches:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        result = m.get("actual_result", "")
        hg = m.get("actual_home_goals", 0) or 0
        ag = m.get("actual_away_goals", 0) or 0
        if not home or not away or not result:
            continue

        calc_home_pre, calc_away_pre = tracker.get_elos_before_match(home, away)
        tracker.process_match(home, away, hg, ag, result)
        calc_home_post = round(tracker.get_elo(home))
        calc_away_post = round(tracker.get_elo(away))

        kd = (m.get("kickoff_date") or "")[:10]
        randuri_comparate += 1

        for pers, calc, bucket in (
            (m.get("home_elo"), calc_home_pre, pre_diffs),
            (m.get("away_elo"), calc_away_pre, pre_diffs),
            (m.get("home_elo_after"), calc_home_post, post_diffs),
            (m.get("away_elo_after"), calc_away_post, post_diffs),
        ):
            if pers is not None:
                bucket.append(abs(int(pers) - int(calc)))

        # Starea curenta servita live: ultimul elo_after cunoscut per echipa.
        if m.get("home_elo_after") is not None:
            ultima_stare[home] = (abs(int(m["home_elo_after"]) - calc_home_post),
                                  int(m["home_elo_after"]), calc_home_post, kd)
        if m.get("away_elo_after") is not None:
            ultima_stare[away] = (abs(int(m["away_elo_after"]) - calc_away_post),
                                  int(m["away_elo_after"]), calc_away_post, kd)

    print(f"  Meciuri comparate                   : {randuri_comparate}")
    print(BAR)

    for eticheta, diffs in (("ELO PRE-meci (home_elo/away_elo — intra in ML)", pre_diffs),
                            ("ELO POST-meci (elo_after — serveste live)", post_diffs)):
        st = summarize(diffs)
        print(f"  {eticheta}")
        print(f"    valori comparate      : {st['n']}")
        print(f"    identice (diferenta 0): {st['zero']}  ({_pct(st['zero'], st['n'])})")
        print(f"    sub {PRAG_NEGLIJABIL} puncte        : {st['neglijabil']}  ({_pct(st['neglijabil'], st['n'])})")
        print(f"    >= {PRAG_MATERIAL} puncte (material): {st['material']}  ({_pct(st['material'], st['n'])})")
        print(f"    medie / mediana / p95 : {st['media']:.1f} / {st['mediana']} / {st['p95']}")
        print(f"    maxim                 : {st['max']}")
        print(BAR)

    # Cea mai importanta sectiune: ce se serveste ACUM, per echipa.
    st_live = summarize([v[0] for v in ultima_stare.values()])
    print("  STAREA SERVITA AZI (ultimul elo_after per echipa)")
    print(f"    echipe                : {st_live['n']}")
    print(f"    corecte (diferenta 0) : {st_live['zero']}  ({_pct(st_live['zero'], st_live['n'])})")
    print(f"    >= {PRAG_MATERIAL} puncte gresite : {st_live['material']}  ({_pct(st_live['material'], st_live['n'])})")
    print(f"    medie / mediana / p95 : {st_live['media']:.1f} / {st_live['mediana']} / {st_live['p95']}")
    print(f"    maxim                 : {st_live['max']}")
    print(BAR)

    print("  TOP 25 echipe cu cea mai mare divergenta (persistat -> recalculat):")
    for team, (d, pers, calc, kd) in sorted(ultima_stare.items(), key=lambda kv: -kv[1][0])[:25]:
        print(f"    {d:>5}  {team:<34} {pers:>5} -> {calc:>5}   (ultimul meci {kd})")
    print(BAR)
    print("  Masuratoare incheiata. ZERO scriere efectuata.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
