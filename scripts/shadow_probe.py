"""
================================================================================
FOOTBALL ORACLE — Utilitar operațional PERMANENT: Shadow Probe
================================================================================
Module: scripts/shadow_probe.py

NU e un POC, NU e un script one-shot — utilitar de operare/mentenanță,
destinat rulării repetate, oricând e nevoie să se verifice cu dovezi reale
că mecanismul de shadow logging funcționează end-to-end (Pasul 14, derivat
din ADR-050 — vezi docs/00_GOVERNANCE/PASUL14_ACTIVATION_REPORT.md pentru
prima lui utilizare reală).

De ce există: `oracle_engine.evaluate_match()` — singurul loc care
declanșează shadow logging (`_log_challenger_shadow()`,
`_log_blend_challenger_shadow()`) — rulează azi DOAR din UI-ul Streamlit,
la interacțiune reală de utilizator. Nu există niciun job programat care
să-l apeleze. Fără acest tool, verificarea operațională a oricărui shadow
logging (Challenger existent sau viitor) ar depinde exclusiv de trafic
organic imprevizibil.

Generic, nu hardcodat pe o familie de algoritm: tool-ul doar apelează
`evaluate_match()` — orice shadow logging deja activ în `model_config`
(xgboost_v1, blend_v1, sau orice familie viitoare) se declanșează singur,
exact ca la trafic real. Tool-ul NU decide, NU citește, NU scrie niciun
flag `*_shadow_logging_enabled` — activarea rămâne responsabilitatea
separată a operatorului, pe `model_config` (Supabase), nu a acestui script.

Izolare de producție — garantată prin cod, nu doar prin convenție:
  - `fixture_id` sintetic, cu prefixul `PROBE_FIXTURE_PREFIX` — niciodată
    un ID real.
  - `kickoff_date` = `SENTINEL_KICKOFF_DATE` (constantă fixă, în viitor
    îndepărtat). Motiv: `supabase_client.upsert_match_history()` (apelat
    intern de `evaluate_match()` prin `_cache_prediction()`) NU cheie pe
    `fixture_id` — rutează prin RPC-ul `upsert_match_canonical`, care face
    lookup pe CHEIA NATURALĂ normalizată (home_team + away_team +
    kickoff_date). Un `kickoff_date` real ar risca un UPDATE peste un rând
    real deja existent. Sentinela garantează că orice probă produce
    întotdeauna un rând NOU, izolat, niciodată o suprascriere.
  - Echipe + ligă REALE, alese dintr-un meci deja TERMINAT din
    `match_history` — profilul construit de `_build_profile()` e realist
    (formă reală, ELO real), nu sintetic — o probă credibilă, nu un test
    cu date inventate. `get_team_recent_results()` filtrează oricum după
    ceasul real (`datetime.now()`), nu după `kickoff_date`-ul meciului de
    prezis — sentinela din viitor nu afectează deloc calitatea formei
    calculate.
  - NU importă `learning_core.challenger_manager` sau
    `learning_core.promotion_service` — nu creează, nu tranziționează, nu
    promovează niciun Challenger. Exercită STRICT calea de citire
    (evaluate_match() -> shadow logging deja existent).
  - `--confirm` obligatoriu pentru orice scriere reală — fără el, tool-ul
    doar afișează ce ar face (fixture-urile alese, echipele, liga) și iese,
    fără niciun apel către `evaluate_match()` sau Supabase write.

Idempotență la rulări repetate: fiecare probă primește un `fixture_id` nou
(`uuid4()`), niciodată reutilizat — rulările repetate NU suprascriu nimic,
ACUMULEAZĂ rânduri noi, distincte, toate cu prefixul `shadow-probe-`
(comportament intenționat al unui instrument de diagnostic, nu bug).
Curățenie: NU automată — tool-ul nu șterge niciodată nimic (decizie
explicită, vezi docs/00_GOVERNANCE/SHADOW_PROBE_OPERATIONAL_GUIDE.md,
Invariant 3); `--list-probes` oferă audit read-only oricând.

Rulare locală (necesită SUPABASE_URL/SUPABASE_SECRET_KEY):
    python scripts/shadow_probe.py --limit 3          # dry-run, doar afișează planul
    python scripts/shadow_probe.py --limit 3 --confirm  # rulare reală
    python scripts/shadow_probe.py --list-probes        # audit read-only

Rulare prin GitHub Actions (secretele reale de producție):
    .github/workflows/shadow_probe.yml, workflow_dispatch,
    input `confirm` obligatoriu = "yes" (sau `list_probes="yes"` pt audit).

Vezi docs/00_GOVERNANCE/SHADOW_PROBE_OPERATIONAL_GUIDE.md pentru ghidul
complet (scop, când se folosește / NU se folosește, cei 4 invarianți
verificați).
================================================================================
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROBE_FIXTURE_PREFIX = "shadow-probe-"
SENTINEL_KICKOFF_DATE = "2099-01-01"  # niciodată o dată reală — vezi header


def pick_probe_source_matches(limit: int) -> list[dict]:
    """Eșantion aleator de `limit` meciuri TERMINATE reale din
    match_history (home_team/away_team/league) — sursa de date realiste
    pentru probele injectate. Read-only."""
    import supabase_client as sb

    client = sb.get_client()
    if client is None:
        raise RuntimeError(
            "Supabase indisponibil — necesită SUPABASE_URL/SUPABASE_SECRET_KEY."
        )
    res = (
        client.table("match_history")
        .select("home_team,away_team,league,kickoff_date")
        .not_.is_("actual_result", "null")
        .not_.is_("home_team", "null")
        .not_.is_("away_team", "null")
        .not_.is_("league", "null")
        .order("kickoff_date", desc=True)
        .limit(max(limit * 20, 200))
        .execute()
    )
    rows = res.data or []
    if not rows:
        return []
    random.shuffle(rows)
    return rows[:limit]


def build_probe_match(source_row: dict) -> dict:
    """Construiește dict-ul `match` pentru evaluate_match() — echipe/ligă
    REALE din `source_row`, fixture_id + kickoff_date sintetice, izolate
    (vezi header-ul modulului)."""
    home = source_row["home_team"]
    away = source_row["away_team"]
    league = source_row["league"]
    tag = uuid.uuid4().hex[:8]
    return {
        "fixture_id": f"{PROBE_FIXTURE_PREFIX}{tag}",
        "home_team": home,
        "away_team": away,
        "league": league,
        "kickoff_date": SENTINEL_KICKOFF_DATE,
        "home_team_id": "",
        "away_team_id": "",
    }


def count_shadow_rows_for_fixture(fixture_id: str) -> list[dict]:
    """Rândurile din shadow_predictions scrise pentru acest fixture_id
    exact — atribuire fără ambiguitate (fixture_id sintetic, unic per
    probă), spre deosebire de un count global, care s-ar amesteca cu
    trafic real concurent."""
    import supabase_client as sb

    client = sb.get_client()
    if client is None:
        return []
    res = (
        client.table("shadow_predictions")
        .select("experiment_name,experiment_group,prob_home,prob_draw,prob_away,created_at")
        .eq("fixture_id", fixture_id)
        .execute()
    )
    return res.data or []


def get_active_champion_snapshot() -> dict | None:
    """Informativ — dovadă directă că invariantul 'Champion live neschimbat'
    (ADR-050 §7.1) nu e afectat de rularea probei. Read-only."""
    import supabase_client as sb

    return sb.get_active_champion("xgboost_v1", "all")


def list_probe_rows() -> dict:
    """Audit read-only al TUTUROR rândurilor create de acest tool, oricând,
    de oricine — folosește exclusiv PROBE_FIXTURE_PREFIX (nicio altă
    presupunere). Curățenia (dacă e dorită vreodată) rămâne o decizie
    separată, explicită a operatorului (ștergere din date live — vezi
    regulile Supabase din CLAUDE.md) — acest tool NU șterge niciodată
    nimic, doar listează."""
    import supabase_client as sb

    client = sb.get_client()
    if client is None:
        raise RuntimeError("Supabase indisponibil.")

    mh = (
        client.table("match_history")
        .select("fixture_id,home_team,away_team,league,created_at")
        .like("fixture_id", f"{PROBE_FIXTURE_PREFIX}%")
        .order("created_at", desc=True)
        .execute()
    )
    sp = (
        client.table("shadow_predictions")
        .select("fixture_id,experiment_name,experiment_group,created_at")
        .like("fixture_id", f"{PROBE_FIXTURE_PREFIX}%")
        .order("created_at", desc=True)
        .execute()
    )
    return {"match_history_rows": mh.data or [], "shadow_predictions_rows": sp.data or []}


def run_probe(limit: int, confirm: bool) -> dict:
    sources = pick_probe_source_matches(limit)
    if not sources:
        print("Niciun meci terminat găsit în match_history — nimic de probat.")
        return {"probed": 0, "results": []}

    probes = [build_probe_match(row) for row in sources]

    print(f"Plan: {len(probes)} probă/probe, echipe/ligă reale, fixture_id + kickoff_date izolate:")
    for m in probes:
        print(f"  {m['fixture_id']}  {m['home_team']} vs {m['away_team']}  [{m['league']}]")

    if not confirm:
        print("\n--confirm neset — DRY RUN, nicio scriere. Rulează din nou cu --confirm pentru execuție reală.")
        return {"probed": 0, "dry_run": True, "planned": probes}

    champion_before = get_active_champion_snapshot()

    import oracle_engine

    engine = oracle_engine.FootballOracleEngine()

    results = []
    for m in probes:
        print(f"\n━━━ Probă: {m['fixture_id']} ({m['home_team']} vs {m['away_team']}) ━━━")
        try:
            pred = engine.evaluate_match(m)
        except Exception as exc:
            print(f"  evaluate_match() a ridicat excepție: {exc}")
            results.append({"fixture_id": m["fixture_id"], "match": m, "error": str(exc)})
            continue

        if pred is None:
            print("  evaluate_match() a întors None (degradare gracioasă — vezi log-uri).")
            results.append({"fixture_id": m["fixture_id"], "match": m, "prediction": None})
            continue

        print(f"  Predicție: home={pred.prob_home_win:.4f} draw={pred.prob_draw:.4f} away={pred.prob_away_win:.4f}")

        shadow_rows = count_shadow_rows_for_fixture(m["fixture_id"])
        print(f"  shadow_predictions pentru acest fixture_id: {len(shadow_rows)} rând(uri)")
        for row in shadow_rows:
            print(f"    - {row['experiment_name']} / {row['experiment_group']}: "
                  f"home={row['prob_home']} draw={row['prob_draw']} away={row['prob_away']}")

        results.append({
            "fixture_id": m["fixture_id"], "match": m,
            "prediction": {
                "prob_home": pred.prob_home_win, "prob_draw": pred.prob_draw,
                "prob_away": pred.prob_away_win,
            },
            "shadow_rows": shadow_rows,
        })

    champion_after = get_active_champion_snapshot()
    champion_unchanged = champion_before == champion_after

    print(f"\nChampion activ (xgboost_v1/all) înainte: {champion_before}")
    print(f"Champion activ (xgboost_v1/all) după:     {champion_after}")
    print(f"Invariant 'Champion neschimbat': {'OK' if champion_unchanged else 'ATENȚIE — SCHIMBAT'}")

    return {
        "probed": len(results), "results": results,
        "champion_before": champion_before, "champion_after": champion_after,
        "champion_unchanged": champion_unchanged,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3, help="Număr de meciuri de probat (implicit 3).")
    parser.add_argument("--confirm", action="store_true", help="Execută efectiv (fără el: dry-run, doar plan).")
    parser.add_argument("--output-json", default=None, help="Scrie rezultatul complet ca JSON la această cale.")
    parser.add_argument(
        "--list-probes", action="store_true",
        help="Read-only: listează TOATE rândurile create vreodată de acest tool "
             "(match_history + shadow_predictions, filtrate după PROBE_FIXTURE_PREFIX). "
             "Nu șterge nimic — curățenia rămâne o decizie separată, explicită.",
    )
    args = parser.parse_args()

    if args.list_probes:
        audit = list_probe_rows()
        print(f"match_history: {len(audit['match_history_rows'])} rând(uri) cu prefixul {PROBE_FIXTURE_PREFIX!r}")
        for row in audit["match_history_rows"]:
            print(f"  {row['fixture_id']}  {row['home_team']} vs {row['away_team']}  [{row['league']}]  {row.get('created_at', '')}")
        print(f"\nshadow_predictions: {len(audit['shadow_predictions_rows'])} rând(uri) cu prefixul {PROBE_FIXTURE_PREFIX!r}")
        for row in audit["shadow_predictions_rows"]:
            print(f"  {row['fixture_id']}  {row['experiment_name']}/{row['experiment_group']}  {row.get('created_at', '')}")
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(audit, f, indent=2, ensure_ascii=False, default=str)
            print(f"\nRezultat complet scris la {args.output_json}")
        return

    summary = run_probe(limit=args.limit, confirm=args.confirm)

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nRezultat complet scris la {args.output_json}")


if __name__ == "__main__":
    main()
