"""
================================================================================
FOOTBALL ORACLE — Redenumire la forma canonică (ADR-060, Faza 2b)
================================================================================
Module: scripts/rename_teams_to_canonical.py

CORECȚIE SUPERVIZATĂ, conform ADR-060
(`docs/00_GOVERNANCE/ADR-060-supervised-data-correction.md`). Respectă toate
cele 5 condiții de acolo:

  1. Dovadă verificată contra sursei — nu contra unei API externe, ci contra
     propriului vocabular al aplicației (`mappings.normalize_team_name()`),
     extins deliberat, un pas separat, în Faza 2a (`scripts/
     detect_identity_alias_candidates.py`, verificat pe date reale, zero
     potrivire fuzzy, cu veto absolut pentru coincidențe false).
  2. Corpus închis — calculat DETERMINIST, o singură dată, din starea live a
     bazei la momentul dry-run-ului. Rândurile care ar coliziona pe indexul
     unic după redenumire sunt EXCLUSE automat, niciodată forțate.
  3. Suprafață minimă — DOAR `home_team`/`away_team`, pe rândul care are
     nevoie de schimbare (unul, celălalt, sau ambele).
  4. SQL exact + aprobare separată — dry-run implicit; `--execute` scrie.
  5. Idempotență — fiecare UPDATE verifică valorile VECHI (home_team +
     away_team) în WHERE. O rulare repetată nu găsește nimic de schimbat pe
     rândurile deja redenumite.

CE NU FACE:
  - NU inventează un canonic nou — folosește EXCLUSIV `normalize_team_name()`,
    deja aprobat, deja folosit la fiecare scriere nouă (`database.queries.
    _normalize_team_fields`). Redenumirea aduce rândurile VECHI la același
    standard pe care rândurile NOI îl primesc deja automat.
  - NU redenumește o pereche dacă rezultatul ar coliziona cu un alt rând viu
    pe `(home_team, away_team, kickoff_date)` — exact cheia indexului unic
    `idx_match_history_natural_key_canonical`. O coliziune înseamnă că cele
    două rânduri ar putea fi, de fapt, DUPLICATE ale aceluiași meci —
    decizie diferită (reconciliere ADR-059), nu redenumire.
  - NU atinge ELO/feature-uri/predicții — rebuild-ul ELO e Faza 3, separată,
    executată DUPĂ ce vocabularul e complet unificat (altfel ar recalcula
    corect peste serii încă fragmentate).

Reutilizează `classify()` din `analyze_d2_vocabulary_drift.py` — ACELAȘI cod
care a produs numărătorile prezentate înainte de aprobare, nu o reimplementare
paralelă care ar putea diverge.

Utilizare:
    python scripts/rename_teams_to_canonical.py            # dry-run (implicit)
    python scripts/rename_teams_to_canonical.py --execute  # scrie in productie
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def plan_renames(rows: list[dict], normalize) -> dict:
    """Planul de redenumire, ca funcție PURĂ peste rândurile deja aduse.

    Reutilizează `classify()` (analiza D2) pentru rename_map și collisions —
    un singur loc care calculează "ce s-ar schimba", nu două implementări
    care ar putea diverge silențios.

    Returnează:
      - `updates`: listă de (id, old_home, old_away, new_home, new_away)
        pentru rândurile SIGURE de redenumit (fără coliziune).
      - `excluded_ids`: id-urile rândurilor omise fiindcă redenumirea lor
        (sau a partenerului de coliziune) ar viola indexul unic.
    """
    from analyze_d2_vocabulary_drift import classify

    result = classify(rows, normalize)
    rename_map = result["rename_map"]
    collisions = result["collisions"]

    # id-urile implicate în orice coliziune — nu se redenumește NICIUNUL din
    # ele, chiar dacă doar unul dintre cele două rânduri ar coliziona real
    # (ambele rămân neatinse, ca perechea să poată fi inspectată împreună).
    excluded_ids: set = set()
    for ids in collisions.values():
        excluded_ids.update(ids)

    updates = []
    for row in rows:
        rid = row.get("id")
        if rid in excluded_ids:
            continue
        h, a = row.get("home_team") or "", row.get("away_team") or ""
        new_h = rename_map.get(h, h)
        new_a = rename_map.get(a, a)
        if new_h != h or new_a != a:
            updates.append((rid, h, a, new_h, new_a))

    return {"updates": updates, "excluded_ids": sorted(excluded_ids),
            "collisions": collisions, "d2_distinct_names": result["d2_distinct_names"]}


def _fetch_live_rows(client) -> list[dict]:
    """[FIX — descoperit 2026-08-22] `.range()` fara `.order()` explicit nu
    are ordine garantata intre pagini sub scriere concurenta — poate intoarce
    acelasi rand de doua ori. `id` e imutabil si monoton, deci ordonarea pe
    el face paginarea provabil stabila."""
    rows: list[dict] = []
    seen_ids: set = set()
    offset, page_size = 0, 1000
    while True:
        batch = (
            client.table("match_history")
            .select("id,home_team,away_team,kickoff_date")
            .is_("superseded_by", "null")
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute().data
        ) or []
        for row in batch:
            rid = row.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            rows.append(row)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main() -> int:
    execute = "--execute" in sys.argv

    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from mappings import normalize_team_name

    print(BAR)
    print("  REDENUMIRE LA FORMA CANONICA (ADR-060, Faza 2b)")
    print(f"  MOD: {'EXECUTE (scrie in productie)' if execute else 'DRY-RUN (zero scriere)'}")
    print(BAR)

    client = sb.get_client()
    rows = _fetch_live_rows(client)
    print(f"  Randuri live analizate : {len(rows)}")

    plan = plan_renames(rows, normalize_team_name)
    updates = plan["updates"]
    excluded = plan["excluded_ids"]

    print(f"  Nume distincte care s-ar schimba : {plan['d2_distinct_names']}")
    print(f"  Randuri de redenumit             : {len(updates)}")
    print(f"  Randuri EXCLUSE (coliziune)      : {len(excluded)}")
    print(BAR)

    if plan["collisions"]:
        print("  COLIZIUNI — randuri NEATINSE, cer decizie separata (reconciliere, nu redenumire):")
        for (h, a, kd), ids in sorted(plan["collisions"].items(), key=lambda kv: str(kv[0])):
            print(f"    {h} vs {a} @ {kd}  -> id-uri {ids}")
        print(BAR)

    if not execute:
        print("  Exemple (primele 15 din plan):")
        for rid, oh, oa, nh, na in updates[:15]:
            print(f"    id={rid:<8} '{oh}' -> '{nh}'   |   '{oa}' -> '{na}'")
        print(BAR)
        print("  DRY-RUN — nicio scriere efectuata. Ruleaza cu --execute dupa aprobare explicita.")
        print(BAR)
        return 0

    print("  EXECUTIE — scriere in productie:")
    scrise, sarite, erori = 0, 0, 0
    for rid, oh, oa, nh, na in updates:
        try:
            res = (
                client.table("match_history")
                .update({"home_team": nh, "away_team": na})
                .eq("id", rid)
                .eq("home_team", oh)
                .eq("away_team", oa)
                .execute()
            )
            if len(res.data or []) == 1:
                scrise += 1
            else:
                sarite += 1
        except Exception as exc:  # noqa: BLE001 — raportat, nu ascuns
            erori += 1
            print(f"    id={rid:<8} EROARE: {exc}")

    print(BAR)
    print(f"  Randuri redenumite : {scrise}")
    print(f"  Randuri sarite     : {sarite}")
    print(f"  Erori              : {erori}")
    print(BAR)
    print("  NU s-a atins ELO/feature-uri/predictii — rebuild-ul ELO ramane Faza 3, separata.")
    print(BAR)
    return 0 if erori == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
