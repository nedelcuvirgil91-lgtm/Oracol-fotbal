"""
================================================================================
FOOTBALL ORACLE — Sync Match Statistics (Sprint 1, ADR-039 / ADR-041 Faza 1)
================================================================================
Module: sync/sync_match_statistics.py

Punctul de intrare Sync Layer pentru Match Statistics — completează meciurile
deja încheiate (owner `actual_*`: sync_results) care încă nu au statistici.
Sincronizare ZILNICĂ pe fereastră scurtă (implicit 2 zile) — separată
deliberat de backfill-ul istoric (`sync/backfill_match_statistics_freelf.py`),
per politica din `DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_2026-07-27.md §1`.

[ADR-041 Faza 1] Providerul NU mai e hardcodat (FreeLF) — alegerea trece prin
`sync_provider_manager.choose_provider()`, punctul unic de decizie al Sync
Layer-ului (reutilizează Selection Engine-ul ADR-034, sau lanțul static de
urgență dacă `selection_engine_v2` e dezactivat, implicit). Soccer Football
Info e Owner-ul implicit al lanțului static pentru acest domeniu (Sprint 1
v6, §3) — set de câmpuri mult mai larg (shots/corners/fouls/lineup/manageri/
arbitru/stadion), dar acoperire de ligă ÎNGUSTĂ azi (doar Romania SuperLiga,
League Mapping v2 confirmat live). FreeLF rămâne fallback REAL, nu doar
teoretic: fiecare task de meci încearcă, pe rând, TOATĂ ordinea din
`fallback_chain("match_statistics")` (începând cu alegerea lui
`choose_provider()`), până când un provider chiar produce date pentru acel
meci — niciun provider existent nu devine inaccesibil doar pentru că nu e
primul ales (cerință explicită: "zero regresii funcționale", niciun provider
eliminat).

[LIMITĂ RECUNOSCUTĂ EXPLICIT, Faza 1 — nu Faza 2] Gating-ul de buget la
nivel de orchestrator (`SyncTask.provider` → `RequestManager.should_request`)
se aplică STRICT primului provider din ordinea de încercare — dacă acela are
cota epuizată, task-ul întreg e blocat de orchestrator, fără să ajungă la
fallback intern. Fiecare adaptor/client își gatează totuși PROPRIUL buget
intern (`RequestManager`/`RateLimitManager`, deja corect, neatins) — un
provider din lanțul de fallback interceptat DUPĂ ce task-ul a pornit e deci
în continuare protejat individual. Gating de buget conștient de ÎNTREG
lanțul de fallback la nivel de orchestrator rămâne Faza 2 (load balancing
dinamic, Sprint 1 v6 §Faza 2) — nu inventat aici fără caz de utilizare
dovedit.

Rulare:
    python -m sync.sync_match_statistics [--days-back N]
    (sau apelat din `sync/run_daily.py`, ca pas declarat cu dependență pe
    rezultatele zilei precedente — vezi PIPELINE_STEPS acolo)
================================================================================
"""
from __future__ import annotations

import argparse
import logging
from typing import Callable

from match_statistics_adapter import MatchStatisticsAdapter
from soccerfootballinfo_match_statistics_adapter import SoccerFootballInfoMatchStatisticsAdapter
from sync_adapter import SyncAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator
from sync_provider_manager import Intent, choose_provider, fallback_chain

logger = logging.getLogger("FootballOracle.Sync.MatchStatistics")

_DOMAIN = "match_statistics"

# [ADR-041 Faza 1] O singură instanță per provider, reutilizată pentru toate
# meciurile din aceeași rulare — tiparul deja folosit de celelalte adaptoare
# singleton din proiect. `sportapi` apare în `_STATIC_FALLBACK_CHAINS`
# (Sprint 1 v6, §3) dar NU are încă un adaptor concret implementat — sărit
# explicit la runtime (log, nu excepție), nu o "gaură" ascunsă.
_ADAPTER_FACTORIES: dict[str, Callable[[], SyncAdapter]] = {
    "soccerfootballinfo": SoccerFootballInfoMatchStatisticsAdapter,
    "freelivefootball": MatchStatisticsAdapter,
}
_adapter_cache: dict[str, SyncAdapter] = {}


def _get_adapter(provider_id: str) -> SyncAdapter | None:
    if provider_id not in _adapter_cache:
        factory = _ADAPTER_FACTORIES.get(provider_id)
        if factory is None:
            return None
        _adapter_cache[provider_id] = factory()
    return _adapter_cache[provider_id]


def _provider_order(league: str) -> list[str]:
    """Alegerea lui `choose_provider()` (Selection Engine sau lanț static),
    urmată de restul `fallback_chain()`-ului, fără duplicate — ordinea REALĂ
    de încercare pentru un meci din această ligă."""
    choice = choose_provider(_DOMAIN, league, intent=Intent.LIVE)
    order: list[str] = []
    if choice.provider_id is not None:
        order.append(choice.provider_id)
    for provider_id in fallback_chain(_DOMAIN):
        if provider_id not in order:
            order.append(provider_id)
    return order


def _matches_missing_stats(days_back: int = 2) -> list[dict]:
    """[REPARAT Sprint 3, Prioritatea 1] `require_referee=True` — exact
    semnalul descris în docstring-ul `get_finished_matches_missing_stats()`
    (`referee` e populat STRICT de Soccer Football Info). Cu implicitul
    vechi (`home_possession IS NULL`), un meci la care FreeLF completa deja
    possession+xG dispărea permanent din rezultat — Soccer Football Info nu
    mai apuca niciodată să încerce restul câmpurilor (shots/corners/fouls/
    cards/offsides/penalties/substitutions/lineup/manager/stadion/
    provider_raw_json), deși owner-ul lor rămâne exclusiv SFI și COALESCE-
    only (ADR-036) nu risca nicio suprascriere.

    [ADAUGAT Pasul 1 Master Repair Plan, ADR-045 — Single Owner] `include_id`
    + filtrare finală prin `get_match_ids_with_complete_flashscore_stats()`:
    un meci deja complet colectat de Flashscore (`flashscore_data_
    completeness.has_stats=True`) NU mai ajunge în lista de task-uri —
    Soccer Football Info/FreeLF nu mai sunt interogate degeaba pentru el.
    Nu schimbă nimic pentru meciurile pe care Flashscore NU le-a colectat
    încă (rămân în listă, provider_order normal, neschimbat)."""
    from database.queries import (
        get_finished_matches_missing_stats,
        get_match_ids_with_complete_flashscore_stats,
    )
    matches = get_finished_matches_missing_stats(days_back=days_back, require_referee=True, include_id=True)
    if not matches:
        return matches
    match_ids = [m["id"] for m in matches if m.get("id") is not None]
    already_complete = get_match_ids_with_complete_flashscore_stats(match_ids)
    if not already_complete:
        return matches
    skipped = [m for m in matches if m.get("id") in already_complete]
    if skipped:
        logger.info("[MatchStatistics] %d meciuri sărite — Flashscore are deja statistici complete (Single Owner)",
                     len(skipped))
    return [m for m in matches if m.get("id") not in already_complete]


def _make_task_runner(match: dict, provider_order: list[str]):
    def _run() -> None:
        params = {
            "home_team": match["home_team"], "away_team": match["away_team"],
            "kickoff_date": match["kickoff_date"], "league": match["league"],
        }
        for provider_id in provider_order:
            adapter = _get_adapter(provider_id)
            if adapter is None:
                logger.debug("[MatchStatistics] provider %r fără adaptor implementat — sărit", provider_id)
                continue
            raw = adapter.fetch(params)
            if raw is None:
                continue
            records = adapter.validate(adapter.normalize(raw))
            if records:
                adapter.persist(records)
            return
        logger.debug("[MatchStatistics] niciun provider din %r a produs date pentru %s vs %s (%s)",
                     provider_order, match["home_team"], match["away_team"], match["kickoff_date"])
    return _run


def run(days_back: int = 2) -> list:
    orchestrator = get_sync_orchestrator()

    matches = _matches_missing_stats(days_back)
    logger.info("[MatchStatistics] %d meciuri fără statistici (ultimele %d zile)", len(matches), days_back)

    for match in matches:
        provider_order = _provider_order(match["league"])
        if not provider_order:
            logger.debug("[MatchStatistics] niciun provider eligibil pentru %s vs %s (%s)",
                         match["home_team"], match["away_team"], match["league"])
            continue

        task_name = f"match_stats:{match['home_team']}_vs_{match['away_team']}_{match['kickoff_date']}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=provider_order[0],
            priority=Priority.P1,
            run=_make_task_runner(match, provider_order),
            # Coverage deja gatată intern de fiecare adaptor/resolver (League
            # Mapping v2 pentru SFI, FREE_LF_LEAGUE_IDS pentru FreeLF) —
            # tiparul deja folosit de ApiFootballHealthAdapter.
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare statistici meci (Soccer Football Info, owner nou, fallback FreeLF)")
    parser.add_argument("--days-back", type=int, default=2)
    args = parser.parse_args()

    results = run(days_back=args.days_back)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
