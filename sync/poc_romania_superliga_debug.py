"""
================================================================================
FOOTBALL ORACLE — Diagnostic: Romania SuperLiga 0 meciuri (bug raportat)
================================================================================
Module: sync/poc_romania_superliga_debug.py

Discovery, NU o schimbare de productie — nu scrie nicaieri, nu modifica
oracle_api.py/mappings.py/provider_selector.py. Trece prin fiecare etapa
a pipeline-ului REAL din get_matches_for_week(), cu apeluri reale, si
raporteaza dovada la fiecare pas: fetch brut per provider, filtrare pe
data, deduplicare, Selection Engine (shadow, doar pentru referinta),
rezultatul final end-to-end.

Rulare:
    python sync/poc_romania_superliga_debug.py
================================================================================
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from oracle_api import (
    API_FOOTBALL_LEAGUE_IDS, ESPN_LEAGUE_SLUGS, FD_COMPETITIONS,
    FREE_LF_LEAGUE_IDS, ODDS_SPORT_KEYS, TSDB_LEAGUE_IDS, FootballOracleAPI,
)
from mappings import match_key

LEAGUE = "Romania SuperLiga"


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    api = FootballOracleAPI()
    today = date.today()
    days_ahead = 7
    d_from = today.isoformat()
    d_to = (today + timedelta(days=days_ahead)).isoformat()

    section("STAGE 1 — fetch brut per provider (apeluri REALE)")

    sk = ODDS_SPORT_KEYS.get(LEAGUE)
    print(f"\n[Odds API] sport_key={sk!r}")
    odds_raw = api._fetch_events_odds_api(sk, days_ahead) if sk else []
    print(f"  raw fixtures: {len(odds_raw)}")
    for m in odds_raw:
        print(f"    {m.get('home_team')!r} vs {m.get('away_team')!r}  league={m.get('league')!r}  "
              f"kickoff_date={m.get('kickoff_date')}  kickoff_utc={m.get('kickoff_utc')}")

    lf_id = FREE_LF_LEAGUE_IDS.get(LEAGUE)
    print(f"\n[FreeLF] league_id={lf_id!r}")
    lf_raw = []
    if lf_id is None:
        print("  NEATINS — liga nu are id mapat in FREE_LF_LEAGUE_IDS -> pasul 2 din "
              "get_matches_for_week() nu incearca niciodata aceasta liga")
    else:
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            lf_raw += api._fetch_freelf_matches(target, LEAGUE)
        print(f"  raw fixtures: {len(lf_raw)}")

    fd_code = FD_COMPETITIONS.get(LEAGUE)
    print(f"\n[football-data.org] comp_code={fd_code!r}")
    fd_raw = []
    if fd_code is None:
        print("  NEATINS — liga nu e in FD_COMPETITIONS -> pasul 3 nu poate returna "
              "niciodata date pentru aceasta liga")
    else:
        fd_raw = api._fetch_matches_fd(d_from, d_to, [fd_code])
        print(f"  raw fixtures: {len(fd_raw)}")

    slug = ESPN_LEAGUE_SLUGS.get(LEAGUE)
    print(f"\n[ESPN] slug={slug!r}")
    espn_raw = []
    if slug:
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            r = api._fetch_matches_espn(LEAGUE, target)
            print(f"  {target}: {len(r)} meciuri brute")
            for m in r:
                print(f"      {m.get('home_team')!r} vs {m.get('away_team')!r}  "
                      f"kickoff_utc={m.get('kickoff_utc')}  kickoff_date={m.get('kickoff_date')}")
            espn_raw += r
    print(f"  TOTAL ESPN raw fixtures (7 zile): {len(espn_raw)}")

    tsdb_id = TSDB_LEAGUE_IDS.get(LEAGUE)
    print(f"\n[TheSportsDB] league_id={tsdb_id!r} "
          f"(apelat DIRECT, bypass gate global 'len(matches)<5' din productie — doar diagnostic)")
    tsdb_raw = api._fetch_matches_tsdb(tsdb_id, LEAGUE) if tsdb_id else []
    print(f"  raw fixtures: {len(tsdb_raw)}")
    for m in tsdb_raw:
        print(f"    {m.get('home_team')!r} vs {m.get('away_team')!r}  kickoff_date={m.get('kickoff_date')}")

    af_id = API_FOOTBALL_LEAGUE_IDS.get(LEAGUE)
    print(f"\n[API-Football] league_id={af_id!r}")
    af_raw = api._fetch_matches_api_football(LEAGUE, d_from, d_to) if af_id else []
    print(f"  raw fixtures: {len(af_raw)}  (asteptat 0 — plan_restricted, confirmat anterior)")

    section("STAGE 1 — rezumat")
    print(f"Odds API:      {len(odds_raw)}")
    print(f"FreeLF:        {'neatins (fara id mapat)' if lf_id is None else len(lf_raw)}")
    print(f"football-data: {'neatins (fara comp_code mapat)' if fd_code is None else len(fd_raw)}")
    print(f"ESPN:          {len(espn_raw)}")
    print(f"TheSportsDB:   {len(tsdb_raw)}  (in productie, atins DOAR daca len(matches_global)<5 dupa pasii 1-4)")
    print(f"API-Football:  {len(af_raw)}")

    section("STAGE 4 — filtrare pe data (fereastra reala din productie)")
    print(f"Fereastra: {d_from} -> {d_to}   (UTC now: {datetime.now(timezone.utc).isoformat()})")
    all_raw = odds_raw + lf_raw + fd_raw + espn_raw + tsdb_raw + af_raw
    for m in all_raw:
        kd = m.get("kickoff_date") or "9999"
        passes = d_from <= kd <= d_to
        print(f"  [{m.get('source')}] {m.get('home_team')!r} vs {m.get('away_team')!r}: "
              f"kickoff_date={kd}  kickoff_utc={m.get('kickoff_utc')}  "
              f"-> {'TRECE' if passes else 'ELIMINAT'} filtrul de data")

    section("STAGE 5 — deduplicare (match_key, exact ca in productie)")
    seen: dict[str, dict] = {}
    for m in all_raw:
        mk = match_key(m.get("home_team", ""), m.get("away_team", ""), m.get("kickoff_date", ""))
        if mk in seen:
            print(f"  COLIZIUNE: {mk} — pastrat sursa {seen[mk].get('source')}, "
                  f"eliminat duplicatul de la {m.get('source')}")
        else:
            seen[mk] = m
    print(f"Total brute (toate sursele): {len(all_raw)}  ->  Dupa deduplicare: {len(seen)}")

    section("STAGE 6 — Shadow Mode (ADR-034 PR5) — confirmare ca NU influenteaza rezultatul")
    import shadow_config
    print(f"selection_engine_shadow_enabled = {shadow_config.is_enabled()}")
    print("Hook-ul din get_matches_for_week() citeste `matches` DUPA ce e complet finalizat "
          "(vezi oracle_api.py, chiar inainte de _cset/return) — nu-l poate modifica structural. "
          "Rezultatul end-to-end de mai jos e produs de ACEEASI rulare in care flag-ul e True live.")

    section("REZULTAT FINAL — apel real get_matches_for_week() (exact ca in productie/app.py)")
    final = api.get_matches_for_week(days_ahead=7, competitions=[LEAGUE])
    print(f"Rezultat: {len(final)} meciuri pentru {LEAGUE!r}")
    for m in final:
        print(f"  {m.get('home_team')} vs {m.get('away_team')}  ({m.get('kickoff_date')})  source={m.get('source')}")

    section("STAGE 3 — Selection Engine (shadow, DOAR referinta — nu afecteaza rezultatul de mai sus)")
    from provider_capabilities import DataType
    from provider_selector import recommend_provider, render_reason_text
    from provider_source_resolver import determine_current_provider

    current = determine_current_provider(LEAGUE, final)
    print(f"current_provider detectat (cele mai multe meciuri in rezultatul final): {current!r}")
    if current:
        rec = recommend_provider(LEAGUE, DataType.FIXTURES, current)
        print(render_reason_text(rec))
    else:
        print("Niciun provider real in rezultatul final -> Selection Engine nu are ce evalua "
              "pentru current_provider (dar tot poate calcula un candidat, vezi mai jos).")
        rec = recommend_provider(LEAGUE, DataType.FIXTURES, "espn")  # referinta, ipotetic
        print("(referinta ipotetica, current_provider='espn'):")
        print(render_reason_text(rec))


if __name__ == "__main__":
    main()
