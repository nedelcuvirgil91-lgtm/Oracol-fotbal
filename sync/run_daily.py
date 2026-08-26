"""
================================================================================
FOOTBALL ORACLE v4.0 — Daily Sync Orchestrator
================================================================================
Module: sync/run_daily.py

Punctul de intrare pentru sincronizarea zilnică automată.
Rulat de GitHub Actions la 03:00 UTC în fiecare zi.

Flux de execuție:
  0. Sincronizează rezultatele meciurilor de ieri (owner `actual_*`)
  1. Match Statistics — Soccer Football Info (owner nou, Sprint 1 v6/ADR-041
     Faza 1), cu fallback real către FreeLF pentru ligile neacoperite încă —
     alegerea providerului trece prin sync_provider_manager.choose_provider(),
     pentru meciurile din pasul 0 (Sprint 1, ADR-039/ADR-041) — vezi
     PIPELINE_STEPS mai jos
  2. Sincronizează meciuri noi (football-data.org + openfootball)
  3. Actualizează feature-urile derivate (formă, H2H, cornere, cartonașe,
     faulturi) pentru meciurile noi — sync.backfill_features.run_backfill(),
     non-destructiv, gating per-coloană (Regula #13). Vezi ADR-014. ELO-ul
     e recalculat aici (ELOTracker, MOV V2_damped — ADR-022), nu mai printr-un
     pas separat — vezi ARCHITECTURE_AUDIT_2026-07-15.md pt eliminarea
     implementării ELO necanonice (sync/calculate_elo.py).
  4. Evaluează experimentele shadow active (shadow_testing.py — vezi
     architecture/ADR-004-continuous-learning.md pt ordinea completă)
  5. Persistă cote de piață (odds_history) — vezi
     docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md (Frozen, ADR-005, ADR-006)
  6. Afișează raport de sincronizare

  [ELIMINAT ADR-054] "Verifică dacă trebuie reantrenat modelul ML" — pas
  legacy, fără scop practic (antrena și arunca modelul, fără artefact/
  Challenger). Antrenarea ML reală rulează exclusiv prin Learning Core
  (continuous_learning.py, ADR-030), etapa 8 din night_sync.yml.

Folosire:
  python sync/run_daily.py                # rulare completă
  python sync/run_daily.py --no-features  # fără actualizare feature-uri derivate
  python sync/run_daily.py --dry-run      # simulare fără scriere în Supabase
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Root în path
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Configurare logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.DailySync")


# ════════════════════════════════════════════════════════════════════════════
# PIPELINE STEPS — manifest declarativ (Sprint 1, ADR-039, decizie explicită
# proprietar produs: "gândește run_daily.py ca un orchestrator de pipeline,
# nu pași hardcodați unul după altul")
# ════════════════════════════════════════════════════════════════════════════
# [NOTĂ DE SCOP] NU e un motor de execuție — corpul lui `run()` de mai jos
# rămâne imperativ, exact ordinea din acest manifest (zero regresie pe cod
# deja testat/funcțional, "no defect, no rewrite"). Acest manifest e sursa
# de adevăr DECLARATĂ pentru nume + dependențe — validată static la import
# (`_validate_pipeline_steps`, mai jos) — orice pas nou adăugat în viitor
# trebuie declarat aici, cu dependențele lui reale, înainte de a fi inserat
# în `run()`. O adevărată orchestrare bazată pe acest manifest (execuție
# automată în ordine topologică) rămâne o extindere viitoare, neaprobată
# acum — scop deliberat restrâns (Sprint 1 „solid, nu mare").

@dataclass(frozen=True)
class PipelineStep:
    name: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)


PIPELINE_STEPS: tuple[PipelineStep, ...] = (
    PipelineStep("results"),
    PipelineStep("match_statistics", depends_on=("results",)),
    PipelineStep("history_sync"),
    # [ADAUGAT Sprint 3, Prioritatea 2] Descoperire meciuri Database-First
    # (R-Sync-7a, `sync/sync_scheduled_fixtures.py`) — cei 6 adaptori
    # existau deja, `scheduled_fixtures` era 0 rânduri (verificat live) —
    # niciodată programat în orchestrarea zilnică. Rulează STRICT în
    # PARALEL cu calea live veche (`oracle_api.get_matches_for_week()`,
    # neatinsă) — Oracle Engine NU citește încă de aici (R-Sync-7b, separat,
    # neînceput). Fără dependințe reale (surse externe, nu alte pipeline
    # steps).
    PipelineStep("scheduled_fixtures"),
    # [ADAUGAT Sprint 3, Pasul 3 — R-Sync-8] Team Stats TheSportsDB —
    # inlocuieste Level 4 live din oracle_engine._build_profile()
    # (self.api.get_team_stats()). Depinde REAL de "scheduled_fixtures"
    # (pasul de mai sus): tsdb_home_team_id/tsdb_away_team_id, cheia care
    # deblocheaza acest sync, sunt scrise DOAR de TsdbFixtureAdapter, in
    # acel pas.
    PipelineStep("team_stats_tsdb", depends_on=("scheduled_fixtures",)),
    # [ADAUGAT Sprint 3, Pasul 3 — R-Sync-9] H2H Free Live Football —
    # inlocuieste ultimul apel live ramas, eliminabil, din
    # oracle_engine._build_h2h() (self.api.get_h2h()). Depinde REAL de
    # "scheduled_fixtures": freelf_event_id, cheia care deblocheaza acest
    # sync, e scris DOAR de FreelfFixtureAdapter, in acel pas.
    PipelineStep("h2h_freelf", depends_on=("scheduled_fixtures",)),
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Team Form FreeLF — fara
    # dependinte reale (ligi statice, mappings.FREE_LF_LEAGUE_IDS), plasat
    # aici doar ca ordine de citire, nu ca dependinta declarata.
    PipelineStep("team_form_freelf"),
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Team Form football-data.org
    # și Weather Forecast — la fel, fara dependinte reale (ligi/perechi
    # statice sau derivate din discovery live, nu din alte PIPELINE_STEPS).
    PipelineStep("team_form_footballdata"),
    PipelineStep("weather_forecast"),
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Team Health (API-Football
    # injuries+coaches) — echipe cu meciuri in urmatoarele 48h
    # (days_ahead=2, deja implicit in sync_team_health.py), consumatorul
    # real de cota API-Football (audit §5), activat ultimul dintre cele
    # ieftine/gratuite conform ordinii aprobate.
    PipelineStep("team_health"),
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Odds API meciuri terminate
    # recente — sursa canonica unica pentru forma echipe SI H2H (audit
    # R-Sync-6, optiunea A), consumatorul de cota Odds API din cele 6.
    # Ultimul din ordinea aprobata (cele doua provideri "serioase" ca
    # cota — API-Football, Odds API — activate la final, izolabile usor
    # daca apare o problema de consum).
    PipelineStep("odds_recent_results"),
    PipelineStep("feature_update", depends_on=("history_sync",)),
    PipelineStep("shadow_evaluation", depends_on=("feature_update",)),
    PipelineStep("odds_persistence"),
    # [ELIMINAT ADR-054] "ml_retrain" — antrena MLPredictorEngine direct,
    # in fiecare noapte, fara sa salveze artefact/sa creeze Challenger,
    # doar loga accuracy si arunca modelul. Antrenarea ML reala ruleaza
    # exclusiv prin Learning Core (continuous_learning.py, ADR-030),
    # etapa 8 din night_sync.yml — vezi ADR-054 pentru investigatia
    # completa (contamina pragul de volum al Challenger-ului).
    # [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #2] intretinere provider_call_log
    # (retentie 9 zile) — fara dependinte, poate rula oricand in pipeline;
    # plasat ultimul deliberat, housekeeping, nu afecteaza restul fluxului.
    PipelineStep("provider_call_log_cleanup"),
)


def _validate_pipeline_steps(steps: tuple[PipelineStep, ...]) -> None:
    """Fail-fast, la import — un pas nu poate depinde de un nume nedeclarat
    încă (referință înainte) sau inexistent. Nu verifică ordinea reală de
    execuție din `run()` (asta ar fi motorul de execuție, explicit deferat)."""
    declared: set[str] = set()
    for step in steps:
        for dep in step.depends_on:
            if dep not in declared:
                raise ValueError(
                    f"PIPELINE_STEPS: pasul '{step.name}' depinde de '{dep}', "
                    "care nu e declarat înainte de el (sau nu există deloc)"
                )
        if step.name in declared:
            raise ValueError(f"PIPELINE_STEPS: pas duplicat '{step.name}'")
        declared.add(step.name)


_validate_pipeline_steps(PIPELINE_STEPS)


def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_header() -> None:
    _print_separator("═")
    print("  ⚽  FOOTBALL ORACLE — Daily Sync")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    _print_separator("═")
    print()


def _print_sync_report(reports: list) -> None:
    """Afișează raportul de sincronizare meciuri."""
    print("\n📥  HISTORY SYNC")
    _print_separator()

    total_fetched = 0
    total_new     = 0
    total_skipped = 0
    all_leagues: set[str] = set()

    for r in reports:
        status_icon = "✅" if r.errors == 0 else "⚠️"
        print(f"  {status_icon} {r.source:<20} "
              f"+{r.matches_new} meciuri noi  "
              f"({r.matches_skipped} duplicate  "
              f"{r.duration_sec}s)")
        total_fetched += r.matches_fetched
        total_new     += r.matches_new
        total_skipped += r.matches_skipped
        all_leagues.update(r.leagues_synced)

    print()
    print(f"  Total descărcat : {total_fetched}")
    print(f"  Meciuri noi     : {total_new}")
    print(f"  Duplicate       : {total_skipped}")
    print(f"  Competiții      : {len(all_leagues)}")


def _print_match_statistics_report(results: list) -> None:
    """`results`: listă de `SyncTaskResult` (sync_orchestrator.py) —
    Soccer Football Info (owner nou, Sprint 1 v6/ADR-041 Faza 1), fallback
    real FreeLF pentru ligile neacoperite încă."""
    print("\n📊  MATCH STATISTICS (Soccer Football Info + fallback FreeLF)")
    _print_separator()
    ran = sum(1 for r in results if r.ran)
    errors = [r for r in results if r.error]
    print(f"  ✅ {ran}/{len(results)} meciuri completate cu statistici noi")
    if errors:
        print(f"  ⚠️  {len(errors)} erori")
        for r in errors[:5]:
            print(f"     - {r.task_name}: {r.error}")


def _print_features_report(result: dict) -> None:
    print("\n🧩  FEATURE UPDATE")
    _print_separator()
    status = result.get("status")
    if status == "done":
        print(f"  ✅ {result.get('processed', 0)} meciuri actualizate "
              f"({result.get('already_done', 0)} deja complete, "
              f"{result.get('errors', 0)} erori)")
    elif status == "skipped":
        print(f"  ℹ️  {result.get('message', 'Sărit')}")
    else:
        print(f"  ⚠️  {result.get('message', 'Status necunoscut')}")


def run(
    skip_features: bool = False,
    dry_run:       bool = False,
) -> dict[str, Any]:
    start_total = time.time()
    # [ADAUGAT 2026-08-26] Cronometrare per pas — golul notat in CLAUDE.md:
    # "NEVERIFICAT inca cat din durata totala a night_sync provine efectiv
    # din acest tipar (vs. alte etape genuin lente)". Pana acum, toata
    # durata acestei functii era invizibila, ascunsa intr-un singur bloc
    # ("1-4. Discovery + API Providers...") in raportul run_night.py.
    # Cheile sunt EXACT numele din PIPELINE_STEPS (sursa de adevar declarata
    # mai sus) — validat la finalul functiei, nu presupus.
    durations: dict[str, float] = {}
    _print_header()

    if dry_run:
        print("  ⚠️  DRY RUN — nicio scriere în Supabase\n")

    # ── Pasul 0 (PIPELINE_STEPS: "results") — Rezultate de ieri ────────────
    print("▶  Pasul 0/6 — Rezultate meciuri de ieri...")
    _t0 = time.time()

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_results import sync_yesterday_results
            results_status = sync_yesterday_results()
            updated   = results_status.get("updated", 0)
            not_found = results_status.get("not_found", 0)
            print(f"  ✅ {updated} meciuri actualizate cu scoruri reale")
            if not_found > 0:
                print(f"  ℹ️  {not_found} meciuri negăsite în match_history")
        except Exception as exc:
            logger.error("[DailySync] sync_yesterday_results failed: %s", exc)
            print(f"  ⚠️  Eroare la sync rezultate: {exc}")
    durations["results"] = round(time.time() - _t0, 1)

    # ── Pasul 1 (PIPELINE_STEPS: "match_statistics", depends_on="results") ─
    # [ADAUGAT Sprint 1, extins ADR-041 Faza 1] Owner nou (Soccer Football
    # Info) pentru setul complet de statistici — posesie, xG, șuturi,
    # cornere, faulturi, cartonașe, lineup, manageri, arbitru, stadion —
    # ales per meci prin sync_provider_manager.choose_provider(), cu
    # fallback real către FreeLF (posesie + xG) pentru ligile neacoperite
    # încă de Soccer Football Info. Rulează DUPĂ rezultate (pasul 0), pe
    # fereastra scurtă implicită (2 zile) — sincronizare zilnică, separată
    # deliberat de backfill istoric (`sync/backfill_match_stats.py`,
    # `sync/backfill_match_statistics_freelf.py`).
    print("\n▶  Pasul 1/6 — Match Statistics (Soccer Football Info + fallback FreeLF)...")
    _t0 = time.time()

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_match_statistics import run as run_match_statistics
            match_stats_results = run_match_statistics()
            _print_match_statistics_report(match_stats_results)
        except Exception as exc:
            logger.error("[DailySync] sync_match_statistics failed: %s", exc)
            print(f"  ⚠️  Eroare la sync statistici meci: {exc}")
    durations["match_statistics"] = round(time.time() - _t0, 1)

    # ── Pasul 2 (PIPELINE_STEPS: "history_sync") ───────────────────────────
    print("▶  Pasul 2/6 — Sincronizare meciuri istorice...")
    _t0 = time.time()

    if not dry_run:
        from sync.sync_matches import sync_all
        sync_reports = sync_all(
            use_football_data = True,
            use_openfootball  = True,
        )
    else:
        # Simulare dry run
        from sync.sync_matches import SyncReport
        sync_reports = [
            SyncReport(source="football_data [DRY RUN]",
                       matches_fetched=100, matches_new=0,
                       matches_skipped=100, duration_sec=0.1),
            SyncReport(source="openfootball [DRY RUN]",
                       matches_fetched=50, matches_new=0,
                       matches_skipped=50, duration_sec=0.1),
        ]

    _print_sync_report(sync_reports)
    durations["history_sync"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "scheduled_fixtures") ──────────────────────────────
    # [ADAUGAT Sprint 3, Prioritatea 2] Vezi comentariul din PIPELINE_STEPS —
    # rulează în PARALEL cu calea live veche, Oracle Engine neatins aici.
    print("\n▶  Descoperire meciuri Database-First (scheduled_fixtures, paralel cu calea live)...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_scheduled_fixtures import run as run_scheduled_fixtures
            fixtures_results = run_scheduled_fixtures()
            ran = sum(1 for r in fixtures_results if r.ran)
            print(f"  ✅ {ran}/{len(fixtures_results)} task-uri de descoperire executate")
        except Exception as exc:
            logger.error("[DailySync] sync_scheduled_fixtures failed: %s", exc)
            print(f"  ⚠️  Eroare la descoperire meciuri: {exc}")
    durations["scheduled_fixtures"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "team_stats_tsdb") ─────────────────────────────────
    # [ADAUGAT Sprint 3, Pasul 3 — R-Sync-8] Owner nou (TheSportsDB events)
    # pentru tsdb_team_stats_snapshot — înlocuiește Level 4 live din
    # oracle_engine._build_profile(). Rulează DUPĂ "scheduled_fixtures" —
    # citește echipele de sincronizat din tsdb_home_team_id/
    # tsdb_away_team_id, scrise de acel pas.
    print("\n▶  Sincronizare team stats — TheSportsDB...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_team_stats_tsdb import run as run_team_stats_tsdb
            team_stats_tsdb_results = run_team_stats_tsdb()
            ran = sum(1 for r in team_stats_tsdb_results if r.ran)
            print(f"  ✅ {ran}/{len(team_stats_tsdb_results)} echipe sincronizate (TheSportsDB)")
        except Exception as exc:
            logger.error("[DailySync] sync_team_stats_tsdb failed: %s", exc)
            print(f"  ⚠️  Eroare la sync team stats (TheSportsDB): {exc}")
    durations["team_stats_tsdb"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "h2h_freelf") ───────────────────────────────────────
    # [ADAUGAT Sprint 3, Pasul 3 — R-Sync-9] Owner nou (Free Live Football
    # H2H) pentru freelf_h2h_snapshot — înlocuiește ultimul apel live rămas,
    # eliminabil, din oracle_engine._build_h2h(). Rulează DUPĂ
    # "scheduled_fixtures" — citește fixture-urile de sincronizat din
    # freelf_event_id, scris de acel pas.
    print("\n▶  Sincronizare H2H — Free Live Football...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_h2h_freelf import run as run_h2h_freelf
            h2h_freelf_results = run_h2h_freelf()
            ran = sum(1 for r in h2h_freelf_results if r.ran)
            print(f"  ✅ {ran}/{len(h2h_freelf_results)} fixture-uri sincronizate (FreeLF H2H)")
        except Exception as exc:
            logger.error("[DailySync] sync_h2h_freelf failed: %s", exc)
            print(f"  ⚠️  Eroare la sync H2H (FreeLF): {exc}")
    durations["h2h_freelf"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "team_form_freelf") ────────────────────────────────
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Owner nou (FreeLF standings)
    # pentru freelf_team_form_snapshot — adaptor deja construit (R-Sync-6),
    # niciodată programat până acum (verificat live, 0 rânduri). Fără
    # dependință de descoperirea meciurilor — iterează exclusiv
    # mappings.FREE_LF_LEAGUE_IDS (8 ligi statice).
    print("\n▶  Sincronizare formă echipe — FreeLF...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_team_form_freelf import run as run_team_form_freelf
            team_form_freelf_results = run_team_form_freelf()
            ran = sum(1 for r in team_form_freelf_results if r.ran)
            print(f"  ✅ {ran}/{len(team_form_freelf_results)} ligi sincronizate (FreeLF)")
        except Exception as exc:
            logger.error("[DailySync] sync_team_form_freelf failed: %s", exc)
            print(f"  ⚠️  Eroare la sync formă echipe (FreeLF): {exc}")
    durations["team_form_freelf"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "team_form_footballdata") ──────────────────────────
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Owner nou (football-data.org
    # standings) pentru footballdata_team_form_snapshot — adaptor deja
    # construit (R-Sync-3), niciodată programat până acum. Fără dependință
    # de descoperirea meciurilor — iterează exclusiv mappings.FD_COMPETITIONS
    # (8 ligi statice).
    print("\n▶  Sincronizare formă echipe — football-data.org...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_team_form_footballdata import run as run_team_form_footballdata
            team_form_fd_results = run_team_form_footballdata()
            ran = sum(1 for r in team_form_fd_results if r.ran)
            print(f"  ✅ {ran}/{len(team_form_fd_results)} ligi sincronizate (football-data.org)")
        except Exception as exc:
            logger.error("[DailySync] sync_team_form_footballdata failed: %s", exc)
            print(f"  ⚠️  Eroare la sync formă echipe (football-data.org): {exc}")
    durations["team_form_footballdata"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "weather_forecast") ────────────────────────────────
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Owner nou (WeatherAPI) pentru
    # weather_forecast_cache — adaptor deja construit (R-Sync-5), niciodată
    # programat până acum. Frecvență Daily (nu every-6h) — decizie explicită,
    # proprietar produs: obiectivul Sprintului 2 e activarea pipeline-ului,
    # nu optimizarea lui; every-6h rămâne o extensie viitoare, dacă se
    # dovedește necesară.
    print("\n▶  Sincronizare prognoză meteo...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_weather_forecast import run as run_weather_forecast
            weather_results = run_weather_forecast()
            ran = sum(1 for r in weather_results if r.ran)
            print(f"  ✅ {ran}/{len(weather_results)} perechi (oraș, dată) sincronizate")
        except Exception as exc:
            logger.error("[DailySync] sync_weather_forecast failed: %s", exc)
            print(f"  ⚠️  Eroare la sync prognoză meteo: {exc}")
    durations["weather_forecast"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "team_health") ──────────────────────────────────────
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Owner nou (API-Football
    # injuries+coaches) pentru team_health_snapshot — adaptor deja construit
    # (R-Sync-2), niciodată programat până acum. Scope deja restrâns la
    # echipe cu meciuri în următoarele 48h (days_ahead=2, implicit) —
    # consumatorul real de cotă API-Football, activat ultimul dintre cele
    # cinci sync-uri ieftine/gratuite, conform ordinii aprobate.
    print("\n▶  Sincronizare stare sănătate echipe (API-Football)...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_team_health import run as run_team_health
            team_health_results = run_team_health()
            ran = sum(1 for r in team_health_results if r.ran)
            print(f"  ✅ {ran}/{len(team_health_results)} echipe sincronizate")
        except Exception as exc:
            logger.error("[DailySync] sync_team_health failed: %s", exc)
            print(f"  ⚠️  Eroare la sync stare sănătate echipe: {exc}")
    durations["team_health"] = round(time.time() - _t0, 1)

    # ── (PIPELINE_STEPS: "odds_recent_results") ─────────────────────────────
    # [ADAUGAT Sprint 2, Etapa C — Data Quality] Owner nou (Odds API /scores)
    # pentru odds_api_recent_results — adaptor deja construit (R-Sync-6),
    # niciodată programat până acum. Sursă canonică unică pentru formă
    # echipe ȘI H2H (audit R-Sync-6, opțiunea A) — ultimul din cele 6
    # sync-uri orfane activate, conform ordinii aprobate.
    print("\n▶  Sincronizare rezultate recente (Odds API)...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_odds_recent_results import run as run_odds_recent_results
            odds_recent_results = run_odds_recent_results()
            ran = sum(1 for r in odds_recent_results if r.ran)
            print(f"  ✅ {ran}/{len(odds_recent_results)} ligi sincronizate (Odds API)")
        except Exception as exc:
            logger.error("[DailySync] sync_odds_recent_results failed: %s", exc)
            print(f"  ⚠️  Eroare la sync rezultate recente (Odds API): {exc}")
    durations["odds_recent_results"] = round(time.time() - _t0, 1)

    # ── Pasul 3 (PIPELINE_STEPS: "feature_update", depends_on="history_sync") ──
    # [ADAUGAT — ADR-014] Completează implementarea ADR-004 ("Toate
    # feature-urile — ELO, formă, standings — se recalculează incremental
    # după fiecare actualizare de rezultate"): înainte, acest pas rula doar
    # manual (workflow_dispatch pe backfill.yml). run_backfill() e deja
    # non-destructiv (gating per-coloană, Regula #13) și idempotent — sigur
    # de rulat zilnic pe tot dataset-ul, cost marginal pentru rândurile deja
    # complete.
    print("\n▶  Pasul 3/6 — Actualizare feature-uri derivate (formă, H2H, cornere, cartonașe, faulturi)...")
    _t0 = time.time()

    if skip_features:
        print("  ℹ️  Sărit (--no-features)")
        features_result = {"status": "skipped", "message": "--no-features flag"}
    elif dry_run:
        print("  ℹ️  Sărit (dry run)")
        features_result = {"status": "skipped", "message": "dry run"}
    else:
        try:
            from sync.backfill_features import run_backfill
            features_result = run_backfill(dry_run=False)
        except Exception as exc:
            logger.error("[DailySync] run_backfill failed: %s", exc)
            features_result = {"status": "error", "message": str(exc)}

    _print_features_report(features_result)
    durations["feature_update"] = round(time.time() - _t0, 1)

    # ── Pasul 4 (PIPELINE_STEPS: "shadow_evaluation", depends_on="feature_update") ──
    # [ADAUGAT] Vezi architecture/ADR-004-continuous-learning.md — ordinea
    # corectă e ELO/formă/standings -> shadow evaluation -> ML retraining,
    # NU recalibrare automată per-meci (deja discutat, dezactivat separat).
    print("\n▶  Pasul 4/6 — Evaluare experimente shadow...")
    _t0 = time.time()

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
        shadow_eval_results = []
    else:
        try:
            import shadow_testing
            shadow_eval_results = shadow_testing.evaluate_all_active_experiments()
            if shadow_eval_results:
                for r in shadow_eval_results:
                    print(f"  ✅ {r['experiment_name']}/{r['experiment_version']}: "
                          f"status={r['status']} (n={r['n_matches_evaluated']})")
            else:
                print("  ℹ️  Niciun experiment activ de evaluat")
            from database.queries import upsert_sync_status
            upsert_sync_status(
                source="experiment_evaluation",
                last_sync=datetime.now(timezone.utc).isoformat(),
                matches_added=0, matches_updated=len(shadow_eval_results),
                status="ok",
                notes=f"{len(shadow_eval_results)} experimente evaluate",
            )
        except Exception as exc:
            logger.error("[DailySync] evaluate_all_active_experiments failed: %s", exc)
            shadow_eval_results = []
            try:
                from database.queries import upsert_sync_status
                upsert_sync_status(
                    source="experiment_evaluation",
                    last_sync=datetime.now(timezone.utc).isoformat(),
                    matches_added=0, matches_updated=0,
                    status="error", notes=str(exc),
                )
            except Exception:
                pass
    durations["shadow_evaluation"] = round(time.time() - _t0, 1)

    # ── Pasul 5 (PIPELINE_STEPS: "odds_persistence") — cote de piață ───────
    # [ADAUGAT] Conform docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md (Frozen,
    # ADR-005, ADR-006). Domain service independent - vezi services/.
    #
    # [MASURAT — 2026-08-26, golul din CLAUDE.md] Acest pas e locul unde
    # `get_matches_for_week()` (oracle_api.py) declanseaza cererile catre
    # Odds API, deci exact pasul unde spam-ul `[RateLimit] oddsapi: cota
    # zilnica epuizata` (`rate_limit_manager.py:can_request`) s-ar acumula
    # daca durata lui creste anormal. Durata masurata aici raspunde direct
    # la intrebarea ramasa deschisa — fara sa mai fie nevoie de grep prin
    # log-uri GitHub Actions, care s-au dovedit prea lungi pentru instrumentele
    # curente (peste 100.000 de linii per rulare, doar ultimele ~5.000
    # accesibile).
    print("\n▶  Pasul 5/6 — Persistare cote de piață (odds_history)...")
    _t0 = time.time()

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from oracle_api import FootballOracleAPI
            from services.odds_persistence_service import OddsPersistenceService

            api = FootballOracleAPI()
            matches_with_odds = api.get_matches_for_week(days_ahead=7)
            odds_service = OddsPersistenceService()
            odds_result = odds_service.persist_odds_snapshot(matches_with_odds)

            print(f"  ✅ {odds_result.attempted} meciuri verificate, {odds_result.written} scrieri efective")
            print(f"     ({odds_result.skipped_ineligible} kickoff trecut, "
                  f"{odds_result.skipped_invalid} date invalide, "
                  f"{odds_result.skipped_no_odds} fără cote, "
                  f"{len(odds_result.errors)} erori)")

            from database.queries import upsert_sync_status
            upsert_sync_status(
                source="odds_persistence",
                last_sync=datetime.now(timezone.utc).isoformat(),
                matches_added=0, matches_updated=odds_result.written,
                status="ok" if not odds_result.errors else "partial",
                notes=f"{odds_result.written} scrise / {odds_result.attempted} verificate",
            )
        except Exception as exc:
            logger.error("[DailySync] OddsPersistenceService failed: %s", exc)
            try:
                from database.queries import upsert_sync_status
                upsert_sync_status(
                    source="odds_persistence",
                    last_sync=datetime.now(timezone.utc).isoformat(),
                    matches_added=0, matches_updated=0,
                    status="error", notes=str(exc),
                )
            except Exception:
                pass
    durations["odds_persistence"] = round(time.time() - _t0, 1)

    # [ELIMINAT ADR-054] Pasul "ml_retrain" — vezi comentariul din
    # PIPELINE_STEPS de mai sus și ADR-054 pentru motiv complet.

    # ── Intretinere (PIPELINE_STEPS: "provider_call_log_cleanup") ──────────
    # [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #2] Singura intretinere necesara
    # pentru provider_call_log (Health Score pe ferestre) — Python, aici,
    # nu cron SQL, nu trigger, nu job separat (cerinta explicita). Retentie
    # 9 zile — marja peste fereastra de 7 zile folosita de Health Score.
    print("\n▶  Curățenie — provider_call_log (retenție 9 zile)...")
    _t0 = time.time()
    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from supabase_client import cleanup_provider_call_log
            deleted = cleanup_provider_call_log(retention_days=9)
            print(f"  ✅ {deleted} rânduri vechi șterse")
        except Exception as exc:
            logger.error("[DailySync] cleanup_provider_call_log failed: %s", exc)
            print(f"  ⚠️  Eroare la curățenie provider_call_log: {exc}")
    durations["provider_call_log_cleanup"] = round(time.time() - _t0, 1)

    # ── Raport final ──────────────────────────────────────────────────────
    total_duration = round(time.time() - start_total, 1)
    print()
    _print_separator("═")
    total_new = sum(r.matches_new for r in sync_reports)
    print(f"  ✅ Sincronizare completă în {total_duration}s")
    print(f"     +{total_new} meciuri noi în Supabase")

    # [ADAUGAT 2026-08-26] Cei mai lenti 5 pasi, afisati direct in raport —
    # nu doar stocati tacit in `durations`. Un raport care aduna date dar nu
    # le arata nu rezolva golul din CLAUDE.md, doar il muta.
    lente = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)[:5]
    print("  Cei mai lenți pași:")
    for nume, secunde in lente:
        print(f"     {secunde:>7.1f}s  {nume}")

    # Validare, nu presupunere (North Star #8): daca un pas nou apare in
    # PIPELINE_STEPS fara sa fie instrumentat mai sus (sau invers), raportam
    # explicit — nu lasam `durations` sa para complet cand nu e.
    nume_declarate = {s.name for s in PIPELINE_STEPS}
    nume_masurate = set(durations)
    lipsa_din_masuratori = nume_declarate - nume_masurate
    in_plus_fata_de_manifest = nume_masurate - nume_declarate
    if lipsa_din_masuratori:
        logger.warning("[DailySync] pași declarați în PIPELINE_STEPS dar necronometrați: %s",
                       sorted(lipsa_din_masuratori))
    if in_plus_fata_de_manifest:
        logger.warning("[DailySync] durate măsurate pentru pași absenți din PIPELINE_STEPS: %s",
                       sorted(in_plus_fata_de_manifest))

    _print_separator("═")
    print()

    return {
        "total_duration_s": total_duration,
        "step_durations_s": durations,
        "steps_missing_from_manifest": sorted(in_plus_fata_de_manifest),
        "manifest_steps_not_timed": sorted(lipsa_din_masuratori),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Daily Sync"
    )
    parser.add_argument(
        "--no-features", action="store_true",
        help="Sări actualizarea feature-urilor derivate (formă, H2H, cornere, cartonașe, faulturi)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulare fără scriere în Supabase"
    )
    args = parser.parse_args()

    run(
        skip_features = args.no_features,
        dry_run       = args.dry_run,
    )


if __name__ == "__main__":
    main()
