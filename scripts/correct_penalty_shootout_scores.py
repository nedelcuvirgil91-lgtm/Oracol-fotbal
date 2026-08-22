"""
================================================================================
FOOTBALL ORACLE — Corecția scorurilor penalty-shootout (ADR-060, Faza 1)
================================================================================
Module: scripts/correct_penalty_shootout_scores.py

CORECȚIE SUPERVIZATĂ, nu un writer nou permanent. Vezi ADR-060
(`docs/00_GOVERNANCE/ADR-060-supervised-data-correction.md`) pentru contractul
complet — acest modul respectă toate cele 5 condiții de acolo:

  1. Dovadă verificată contra sursei — fiecare corecție de mai jos vine din
     `scripts/audit_penalty_shootout_rows.py`, GitHub Actions run 32560333453
     (7.534 rânduri fd_* verificate contra football-data.org, 0 negăsite,
     exact 6 nepotriviri, toate corespunzând meciurilor raportate PENALTY_SHOOTOUT).
  2. Corpus închis — cele 6 id-uri de mai jos, hardcodate, NU o interogare
     care ar putea returna mai mult/mai puțin la o rulare viitoare.
  3. Suprafață minimă — DOAR actual_home_goals/actual_away_goals/actual_result.
  4. SQL exact + aprobare separată — vezi `--dry-run` (implicit) mai jos.
  5. Idempotență — fiecare UPDATE verifică valoarea VECHE în WHERE; o rulare
     repetată nu găsește nimic de schimbat.

CE NU FACE (deliberat, per ADR-060 §"Ce NU declanșează"):
  - NU recalibrează (`_recalibrate_for_result` nu e apelat aici — o corecție
    de scor nu e o observație nouă din care sistemul "învață").
  - NU resetează `backfill_done` și NU atinge ELO/feature-uri. Recalculul
    downstream e parte a rebuild-ului ELO planificat separat (ADR-060, Faza 3),
    nu un efect automat al acestei corecții.
  - NU e reutilizabil pentru alt corpus — un caz nou cere propriul audit,
    propriul corpus verificat, propria trecere prin acest contract.

Utilizare:
    python scripts/correct_penalty_shootout_scores.py            # dry-run (implicit)
    python scripts/correct_penalty_shootout_scores.py --execute  # scrie in productie
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Corpus fixat (condiția 2, ADR-060). Fiecare intrare citează valoarea VECHE
# (folosită în WHERE, pentru idempotență) și valoarea NOUĂ, verificată contra
# football-data.org (run 32560333453). "old" nu e doar documentație — e parte
# a interogării de UPDATE, deci un rând deja corectat sau schimbat altfel de
# atunci NU va fi atins la o rulare repetată.
CORRECTIONS: list[dict] = [
    {"id": 3623, "fixture_id": "fd_451665", "meci": "Arsenal - Porto (2024-03-12)",
     "old": {"home": 5, "away": 2, "result": "H"},
     "new": {"home": 1, "away": 0, "result": "H"}},
    {"id": 3625, "fixture_id": "fd_451668", "meci": "Atletico Madrid - Inter Milan (2024-03-13)",
     "old": {"home": 5, "away": 3, "result": "H"},
     "new": {"home": 2, "away": 1, "result": "H"}},
    {"id": 3634, "fixture_id": "fd_451679", "meci": "Manchester City - Real Madrid (2024-04-17)",
     "old": {"home": 4, "away": 5, "result": "A"},
     "new": {"home": 1, "away": 1, "result": "D"}},
    {"id": 3809, "fixture_id": "fd_524100", "meci": "Liverpool - Paris Saint-Germain (2025-03-11)",
     "old": {"home": 1, "away": 5, "result": "A"},
     "new": {"home": 0, "away": 1, "result": "A"}},
    {"id": 3814, "fixture_id": "fd_524102", "meci": "Atletico Madrid - Real Madrid (2025-03-12)",
     "old": {"home": 3, "away": 4, "result": "A"},
     "new": {"home": 1, "away": 0, "result": "H"}},
    {"id": 114439, "fixture_id": "fd_552096", "meci": "Paris Saint-Germain - Arsenal (2026-05-30)",
     "old": {"home": 5, "away": 4, "result": "H"},
     "new": {"home": 1, "away": 1, "result": "D"}},
]


def build_sql(corrections: list[dict]) -> list[str]:
    """Generează SQL-ul EXACT pentru fiecare corecție. Funcție PURĂ — testată
    direct, fără Supabase (`tests/test_correct_penalty_shootout_scores.py`).

    WHERE include valorile vechi — asta e mecanismul de idempotență (condiția
    5, ADR-060): dacă rândul nu mai are exact acele valori, UPDATE-ul nu
    atinge nimic.
    """
    statements = []
    for c in corrections:
        old, new = c["old"], c["new"]
        stmt = (
            f"UPDATE match_history SET "
            f"actual_home_goals = {new['home']}, "
            f"actual_away_goals = {new['away']}, "
            f"actual_result = '{new['result']}' "
            f"WHERE id = {c['id']} "
            f"AND actual_home_goals = {old['home']} "
            f"AND actual_away_goals = {old['away']} "
            f"AND actual_result = '{old['result']}';"
        )
        statements.append(stmt)
    return statements


def _fetch_current(client, ids: list[int]) -> dict[int, dict]:
    res = (
        client.table("match_history")
        .select("id,fixture_id,actual_home_goals,actual_away_goals,actual_result,superseded_by")
        .in_("id", ids)
        .execute()
    )
    return {row["id"]: row for row in (res.data or [])}


def main() -> int:
    execute = "--execute" in sys.argv

    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    print(BAR)
    print("  CORECȚIE SUPERVIZATĂ — scoruri penalty-shootout (ADR-060, Faza 1)")
    print(f"  MOD: {'EXECUTE (scrie in productie)' if execute else 'DRY-RUN (zero scriere)'}")
    print(BAR)

    client = sb.get_client()
    ids = [c["id"] for c in CORRECTIONS]
    current = _fetch_current(client, ids)

    print("  Verificare pre-scriere — starea curenta trebuie sa corespunda 'old':")
    toate_ok = True
    for c in CORRECTIONS:
        row = current.get(c["id"])
        if row is None:
            print(f"    [!] id={c['id']} NU EXISTA in match_history — omis.")
            toate_ok = False
            continue
        old = c["old"]
        corespunde = (
            row.get("actual_home_goals") == old["home"]
            and row.get("actual_away_goals") == old["away"]
            and row.get("actual_result") == old["result"]
        )
        stare = "OK — corespunde 'old'" if corespunde else "NEPOTRIVIT — posibil deja corectat sau schimbat"
        live = "LIVE" if row.get("superseded_by") is None else "superseded"
        print(f"    id={c['id']:<8} {c['fixture_id']:<14} [{live:<11}] {stare}")
        if not corespunde:
            toate_ok = False

    print(BAR)
    print("  SQL exact (idempotent — WHERE include valoarea veche):")
    for stmt in build_sql(CORRECTIONS):
        print(f"    {stmt}")
    print(BAR)

    if not execute:
        print("  DRY-RUN — nicio scriere efectuata. Ruleaza cu --execute dupa aprobare explicita.")
        print(BAR)
        return 0 if toate_ok else 1

    if not toate_ok:
        print("  OPRIT — cel putin un rand nu corespunde starii asteptate. Nicio scriere.")
        print(BAR)
        return 1

    print("  EXECUTIE — scriere in productie:")
    scrise, sarite = 0, 0
    for c in CORRECTIONS:
        old, new = c["old"], c["new"]
        res = (
            client.table("match_history")
            .update({
                "actual_home_goals": new["home"],
                "actual_away_goals": new["away"],
                "actual_result": new["result"],
            })
            .eq("id", c["id"])
            .eq("actual_home_goals", old["home"])
            .eq("actual_away_goals", old["away"])
            .eq("actual_result", old["result"])
            .execute()
        )
        afectate = len(res.data or [])
        if afectate == 1:
            scrise += 1
            print(f"    id={c['id']:<8} corectat: {old['home']}-{old['away']} ({old['result']}) "
                  f"-> {new['home']}-{new['away']} ({new['result']})")
        else:
            sarite += 1
            print(f"    id={c['id']:<8} SARIT — WHERE nu a gasit valoarea veche (deja corectat?)")

    print(BAR)
    print(f"  Randuri corectate : {scrise}")
    print(f"  Randuri sarite    : {sarite}")
    print(BAR)
    print("  NU s-a declansat recalibrare. NU s-a resetat backfill_done/ELO —")
    print("  recalculul downstream ramane parte a rebuild-ului ELO, separat (ADR-060, Faza 3).")
    print(BAR)
    return 0 if sarite == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
