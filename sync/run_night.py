"""
================================================================================
FOOTBALL ORACLE — Night Sync (Faza 2, §7)
================================================================================
Module: sync/run_night.py

Orchestrator de noapte, decuplat de `daily.yml`/`sync/run_daily.py`
(Tier 1 API providers) — secvențiază fluxul complet cerut explicit:

    Discovery → API Providers → Flashscore → Validation → Canonical
    Database → Team DNA → Oracle Data Layer → Diagnostics → Cleanup →
    Backup → Final Report

Plus DOUĂ etape SUPLIMENTARE, în afara acestor 11 nume:
  - Challenger Shadow Batch (ADR-056) — loghează predicții shadow pentru
    Challenger-ul activ pe toate meciurile descoperite, indiferent de
    vizionare, ca să accelereze acumularea celor 200 de meciuri necesare
    evaluării (pragul NU se schimbă, doar viteza).
  - Continuous Learning (Learning Core, ADR-030), PRE-EXISTENTĂ, complet
    independentă de Flashscore/Team DNA/Faza 2/Faza 3 (Champion/Challenger,
    nu recalibrare Predictor) — păstrată aici doar ca să nu se piardă
    automatizarea ei după consolidarea schedulerului (vezi
    `.github/workflows/continuous_learning.yml`, cron dezactivat acolo).
    Gatată intern de `learning_core_enabled`, implicit OPRIT — no-op sigur
    azi. Rulează DUPĂ Challenger Shadow Batch, ca predicțiile proaspete să
    existe deja la evaluare.

Fiecare etapă rulează IZOLAT (o excepție într-o etapă nu oprește restul
pipeline-ului — la fel ca `sync/run_daily.py`, care deja tratează fiecare
Pas independent). Idempotent: fiecare etapă individuală apelată aici
(`sync.run_daily.run`, `providers.flashscore.run_foundation_data_layer.run`
cu Delta Sync, `learning_core.run_continuous_learning.main`,
`providers.flashscore.season_cleanup.build_cleanup_dry_run_report`,
`providers.flashscore.backup.run_backup`) e deja idempotentă independent
— rularea secvențială, repetată, nu produce duplicate (Backup produce un
fișier nou per rulare, niciodată suprascriere).

Team DNA rulează LIVE, la fiecare predicție din Oracle Engine — nu are
(și nu are nevoie de) un pas batch separat; raportat explicit ca atare,
niciodată simulat ca un pas care "rulează" ceva. Oracle Data Layer e
DOAR infrastructură/context (home/away_flashscore_dna pe
MatchPrediction) — nicio recalibrare, nicio schimbare de blending/
confidence (Faza 3, neînceput). Backup e REAL (`providers/flashscore/
backup.py`, export JSON read-only) — Delete/Integrity Check rămân
neimplementate (ADR-044 Addendum A6, `delete_executed` rămâne mereu
False în Season Cleanup).
================================================================================
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.NightSync")


def _run_stage(name: str, fn: Callable[[], Any], report: list[dict],
               critic: bool = False) -> None:
    """Rulează o etapă și o înregistrează în raport.

    `critic` — implicit **False**, deliberat. O etapă devine critică doar dacă
    e marcată EXPLICIT la apel, niciodată din oficiu. Consecință: adăugarea
    acestui parametru nu colorează nimic roșu de la sine, iar lista de etape
    critice crește prin decizie, nu prin construcție (North Star #3, aplicat
    și la ceva care nu e un flag de produs).
    """
    print(f"\n▶  {name}")
    t0 = time.time()
    try:
        detail = fn()
        report.append({
            "stage": name, "ok": True, "critic": critic,
            "duration_s": round(time.time() - t0, 1), "detail": detail,
        })
        print(f"   ✅ OK ({report[-1]['duration_s']}s)")
    except Exception as exc:
        logger.error("[NightSync] Etapa %s a eșuat: %s", name, exc)
        report.append({
            "stage": name, "ok": False, "critic": critic,
            "duration_s": round(time.time() - t0, 1), "error": str(exc),
        })
        print(f"   ❌ EȘUAT: {exc}")


# [ADAUGAT 2026-10-21] Producător înregistrat sub ADR-026 §Idempotency.
#
# DE CE `automation_runs` si NU o tabela noua: tabela are deja exact campurile
# necesare (`producer`, `process_type`, `status`, `error_detail`, `summary`
# jsonb, `started_at`, `completed_at`) si are DEJA producatori din afara
# Learning Core — `ADR-040` (echivalenta R-Sync-7b, stratul de sincronizare)
# si `ADR-052` (validare). Deci zero schema noua, nicio migrare, nicio grija
# cu regula `GRANT` de la 30 oct.
#
# CHEIA DE IDENTITATE, ceruta explicit de ADR-026 §2: data UTC a rularii.
# Consecinta regulii „Reuse": o a doua rulare pornita cat timp prima e inca
# `running` o REFOLOSESTE in loc sa scrie un rand paralel; una pornita dupa ce
# prima s-a incheiat creeaza corect un rand nou (cazul real de azi, rulari 93
# si 94 in aceeasi zi).
#
# UN SINGUR RAND PE RULARE, nu unul pe etapa — masurat, nu presupus:
# `list_recent_runs(limit=50)` NU filtreaza pe `producer` si alimenteaza
# ecranul „Activity Log" din `app.py`. La ~13 randuri/zi azi, 50 de randuri
# inseamna ~4 zile de istoric; 10 randuri/noapte l-ar fi redus la ~2, cu ~43%
# succese de rutina. As fi reparat un punct orb creand altul.
_PRODUCATOR_NIGHT_SYNC = "night_sync"
_PROCES_NIGHT_SYNC = "night_sync_run"


def _deschide_rand_audit(started_at: str) -> int | None:
    """Deschide rândul de audit al rulării, sau întoarce `None` dacă nu se poate.

    **Observabilitatea nu are voie să rupă lucrul pe care îl observă** — exact
    lecția din reparația de azi a cache-ului, unde o funcție auxiliară arunca
    în apelant și omora o etapă întreagă. Orice eșec de aici (Supabase picat,
    credențiale lipsă, modul inexistent) se loghează și se continuă: o rulare
    de noapte nu se oprește fiindcă n-a putut scrie un rând de evidență.
    """
    try:
        import automation_runs as ar
        run_id = ar.write_run(
            _PRODUCATOR_NIGHT_SYNC, _PROCES_NIGHT_SYNC, "T1",
            target_key=started_at[:10],  # data UTC = cheia de identitate
        )
        if run_id is not None:
            ar.start_run(run_id)
        return run_id
    except Exception as exc:
        logger.warning("[NightSync] rândul de audit nu s-a putut deschide: %s", exc)
        return None


def _inchide_rand_audit(run_id: int | None, rezumat: dict[str, Any],
                        critice: list[str]) -> None:
    """Închide rândul de audit. `failed` DOAR dacă o etapă critică a eșuat —
    aceeași regulă ca pentru codul de ieșire, ca `status` din bază și culoarea
    jobului din GitHub să nu poată spune lucruri diferite."""
    if run_id is None:
        return
    try:
        import automation_runs as ar
        if critice:
            ar.fail_run(run_id, "etape critice eșuate: " + ", ".join(critice),
                        summary=rezumat)
        else:
            ar.complete_run(run_id, rezumat)
    except Exception as exc:
        logger.warning("[NightSync] rândul de audit nu s-a putut închide: %s", exc)


def rezumat_pentru_audit(report: list[dict[str, Any]],
                         started_at: str, finished_at: str) -> dict[str, Any]:
    """Raportul pe etape, condensat pentru `automation_runs.summary`.

    Funcție **pură**. Păstrează per etapă doar ce se poate interoga ulterior
    (nume, reușită, critică, durată) plus `step_durations_s` unde etapa îl
    întoarce — adică exact defalcarea care, până acum, se calcula corect și se
    arunca la ultima linie, și care a trebuit reconstituită din log-uri la
    fiecare investigație de durată din august.

    NU copiază `detail` întreg: e arbitrar ca mărime și ar transforma un rând
    de audit într-un depozit.
    """
    etape = []
    for r in report:
        intrare: dict[str, Any] = {
            "etapa": r.get("stage"),
            "ok": bool(r.get("ok", False)),
            "critic": bool(r.get("critic", False)),
            "durata_s": r.get("duration_s"),
        }
        if not r.get("ok", False) and r.get("error"):
            intrare["eroare"] = str(r["error"])[:500]
        detaliu = r.get("detail")
        if isinstance(detaliu, dict) and detaliu.get("step_durations_s"):
            intrare["pasi_s"] = detaliu["step_durations_s"]
        etape.append(intrare)

    reusite = sum(1 for r in report if r.get("ok", False))
    return {
        "etape": etape,
        "etape_total": len(report),
        "etape_reusite": reusite,
        "etape_esuate": len(report) - reusite,
        "critice_esuate": etape_critice_esuate(report),
        "inceput": started_at,
        "sfarsit": finished_at,
        # Legătura cu log-ul: API-ul GitHub întoarce doar ultimele ~5000 de
        # linii, iar o rulare de noapte produce peste 100.000 — deci rândul
        # ăsta trebuie să poată trimite la rularea exactă, nu invers.
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    }


def etape_critice_esuate(report: list[dict[str, Any]]) -> list[str]:
    """Numele etapelor CRITICE care au eșuat. Funcție pură — nicio citire, nicio
    scriere, niciun efect. Separată tocmai ca decizia „jobul e roșu sau verde"
    să fie testabilă fără să ruleze o rulare de noapte.

    `critic` absent se citește ca **False**: un raport scris de cod mai vechi
    nu devine retroactiv critic.
    """
    return [
        str(r.get("stage"))
        for r in report
        if not r.get("ok", False) and r.get("critic", False)
    ]


def _stage_api_providers() -> dict:
    """1. Discovery + Provideri API + Validation + Canonical Database —
    întreg `sync/run_daily.py` (Pașii 0-6, cadență Tier 1, deja idempotent).

    [ADAUGAT 2026-08-26] Pana acum, `run_daily_sync()` era apelat orb —
    valoarea intoarsa nu era citita, deci durata reala din interior (15
    pasi, inclusiv `odds_persistence`, locul unde se face cererea catre
    Odds API) era complet invizibila in raportul de noapte, ascunsa sub un
    singur nume ("1-4. Discovery + API Providers..."). Golul era notat
    explicit in CLAUDE.md ca "NEVERIFICAT inca". `run()` acum intoarce
    `step_durations_s` (vezi `sync/run_daily.py`) — cablat aici, nu doar
    calculat si aruncat."""
    from sync.run_daily import run as run_daily_sync
    rezultat = run_daily_sync()
    durate = (rezultat or {}).get("step_durations_s", {})
    lente = sorted(durate.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "detail": "sync/run_daily.py rulat complet (Pașii 0-6)",
        "total_duration_s": (rezultat or {}).get("total_duration_s"),
        "step_durations_s": durate,
        "cei_mai_lenti_5_pasi": lente,
    }


def _stage_flashscore() -> str:
    """2. Flashscore — Discovery + fetch/normalize/validate/persist, cu
    Delta Sync (sare meciurile deja persistate canonic, Faza 2 §7).

    [ADAUGAT Pasul 1 Master Repair Plan, ADR-045; rafinat dupa feedback]
    Doua schimbari fata de comportamentul original (limit_per_league=None,
    fara nicio protectie):
    - `include_future_fixtures=False` — solutia REALA pentru cauza
      radacina a celor 240 de fixture-uri VIITOARE persistate integral
      (audit 2026-08-03): rularile automate nu mai incearca deloc hub-ul
      `/fixtures/` — Flashscore nu are niciodata valoare pe un meci
      nejucat (ADR-045, Owner matrix), deci nu mai are rost sa-l descopere
      automat, indiferent daca Sync Layer il are deja in scheduled_fixtures.
    - `limit_per_league=get_limit_per_league_automated()` — plafon
      CONFIGURABIL (Supabase `model_config`, cheia
      `flashscore_limit_per_league_automated`), nu hardcodat; se aplica
      doar hub-ului `/results/` (meciuri terminate), ca proxy pentru
      "cele mai recente N meciuri" (hub-ul e cronologic, cel mai recent
      primul — vezi discovery.py pentru justificare completa).
    Rularile manuale (CLI, `--limit-per-league`/`--no-future-fixtures`)
    raman complet neafectate."""
    from providers.flashscore.discovery import get_limit_per_league_automated
    from providers.flashscore.run_foundation_data_layer import run as run_flashscore
    # [ADAUGAT 2026-08-10] Listă EXPLICITĂ, nu `leagues=None` ("toate din
    # FLASHSCORE_TRACKED_COMPETITIONS") — cerere explicită proprietar produs:
    # extinderea etapizată la ligi noi (Jupiler Pro League/Ekstraklasa/
    # Scottish Premiership) nu trebuie să îngreuneze automat night_sync-ul
    # existent. Ligile noi rulează separat, la altă oră, prin
    # flashscore_extra_leagues.yml (vezi workflow-ul dedicat). Dacă se
    # adaugă o ligă nouă la setul de bază pe viitor, lista de aici trebuie
    # extinsă manual, deliberat — nu implicit.
    _NIGHT_SYNC_LEAGUES = [
        "Romania SuperLiga", "Champions League", "Premier League", "La Liga",
        "Serie A", "Bundesliga", "Ligue 1", "Europa League", "MLS",
        "Primeira Liga", "Eredivisie", "Super Lig", "HNL", "Conference League",
    ]
    exit_code = run_flashscore(leagues=_NIGHT_SYNC_LEAGUES, limit_per_league=get_limit_per_league_automated(),
                                dry_run=False, include_future_fixtures=False)
    return f"exit_code={exit_code}"


def _stage_team_dna() -> str:
    """6. Team DNA (flashscore_team_dna.py) — rulează LIVE, per predicție,
    în Oracle Engine (_build_flashscore_dna, apelat din evaluate_match())
    — niciun pas batch de precalcul există azi, deci nimic de rulat aici.
    Documentat explicit, nu simulat."""
    return "calculat live per predicție (Oracle Engine) — fără pas batch de precalcul"


def _stage_oracle_data_layer() -> str:
    """7. Oracle Data Layer — infrastructura/contextul (home/away_
    flashscore_dna pe MatchPrediction) există deja, populată la fiecare
    evaluate_match(); NU există (și nu trebuie să existe, per cerința
    explicită "doar infrastructură și context") un pas batch de
    precalcul/recalibrare aici — asta rămâne Faza 3."""
    return "context disponibil live în Oracle Engine (home/away_flashscore_dna) — fără recalibrare, fără pas batch"


def _stage_challenger_shadow_batch() -> dict:
    """[ADAUGAT — ADR-056] Loghează predicții shadow pentru Challenger-ul
    activ pe TOATE meciurile descoperite (nu doar cele vizionate în
    aplicație) — accelerează acumularea celor 200 de meciuri necesare
    evaluării (MIN_MATCHES_FOR_EVALUATION, neschimbat), fără nicio
    relaxare a rigorii statistice de promovare. Rulează ÎNAINTE de etapa
    Continuous Learning de mai jos, ca predicțiile proaspete să existe
    deja când _phase_a_monitor_existing() evaluează Challenger-ul, în
    aceeași rulare nocturnă. Vezi oracle_engine.log_challenger_shadow_
    for_week() pentru detaliu complet (idempotent, Database-First)."""
    from oracle_engine import FootballOracleEngine
    engine = FootballOracleEngine()
    return engine.log_challenger_shadow_for_week()


def _stage_ml_refresh_pre_existing() -> str:
    """Etapă SUPLIMENTARĂ, în afara celor 11 numite explicit — Continuous
    Learning (Learning Core, ADR-030) PRE-EXISTENTĂ, independentă de
    Flashscore/Faza 2/Faza 3 (Champion/Challenger, nu recalibrare Team
    DNA/Predictor). Rulată aici DOAR ca să nu se piardă automatizarea ei
    (cron-ul propriu, continuous_learning.yml, a fost dezactivat la
    consolidarea schedulerului — vezi acel fișier) — gatată intern de
    `learning_core_enabled`, implicit OPRIT, deci no-op sigur azi."""
    from learning_core.run_continuous_learning import main as run_continuous_learning
    run_continuous_learning()
    return "learning_core.run_continuous_learning executat (pre-existent, ADR-030, gatat de learning_core_enabled)"


def _stage_diagnostics() -> dict:
    """8. Diagnostics — snapshot real de completitudine Foundation Data
    Layer (ultimele meciuri procesate), NU un probe live nou (acela e
    diagnostics_api_football.py, unealtă POC separată, nefolosită aici)."""
    from database.queries import get_recent_flashscore_matches
    recent = get_recent_flashscore_matches(limit=20)
    if not recent:
        return {"matches_checked": 0, "avg_coverage_percent": None}
    coverages = [r.get("coverage_percent", 0.0) for r in recent]
    return {
        "matches_checked": len(recent),
        "avg_coverage_percent": round(sum(coverages) / len(coverages), 1),
        "min_coverage_percent": min(coverages),
    }


def _stage_cleanup() -> dict:
    """9. Cleanup — Season Cleanup DRY RUN (ADR-044 Addendum A6) — RAPORT
    DOAR, nicio ștergere (`delete_executed` rămâne mereu False, garantat
    prin construcție de `season_cleanup.py`, care nu conține niciun DELETE)."""
    from providers.flashscore.season_cleanup import build_cleanup_dry_run_report
    report = build_cleanup_dry_run_report()
    rezultat = {"delete_executed": report.get("delete_executed", False),
                "cleanup_candidates": report.get("cleanup_candidates", [])}

    # [ADAUGAT — ADR-069] Raportul de retentie pe cheia de DATA, alaturi de cel
    # pe `season`. Nu il inlocuieste: cele doua spun lucruri diferite si ambele
    # sunt oneste. Raportul pe `season` arata ca retentia clasica NU poate
    # actiona (coloana e NULL pe toate cele 12.573 de randuri din
    # `flashscore_match_context`); cel de aici arata ce ar sterge efectiv
    # regula ancorata in calendarele reale (ADR-067).
    #
    # STRICT dry-run aici, indiferent de flag — `execute_retention(dry_run=True)`
    # returneaza inainte de orice poarta de stergere. Prima rulare reala cere
    # aprobare separata (ADR-069, decizia 6), deci nu se declanseaza din
    # orchestratorul de noapte.
    try:
        from providers.flashscore.retention import execute_retention
        retentie = execute_retention(dry_run=True)
        rezultat["retention_adr069"] = {
            "prag": retentie.get("prag"),
            "delete_activat": retentie.get("delete_activat"),
            "candidati": {t: i.get("candidati") for t, i in retentie.get("tabele", {}).items()},
            "fara_data": {t: i.get("fara_data") for t, i in retentie.get("tabele", {}).items()},
        }
    except Exception as exc:
        logger.warning("[NightSync] raportul de retentie ADR-069 a esuat: %s", exc)
        rezultat["retention_adr069"] = {"error": str(exc)}

    return rezultat


def _stage_backup() -> dict:
    """10. Backup — export JSON, read-only, al celor 6 tabele Foundation
    Data Layer (`providers/flashscore/backup.py`) — activarea explicit
    cerută a pasului lăsat neimplementat de ADR-044 Addendum A6. Delete/
    Integrity Check rămân neimplementate (scope neschimbat, doar Backup a
    fost cerut)."""
    from providers.flashscore.backup import run_backup
    return run_backup()


def run() -> list[dict[str, Any]]:
    print()
    print("═" * 78)
    print("  Football Oracle — Night Sync")
    print("  Discovery → API Providers → Flashscore → Validation →")
    print("  Canonical Database → Team DNA → Oracle Data Layer → Diagnostics →")
    print("  Cleanup → Backup → Final Report")
    print("  (+ Challenger Shadow Batch, ADR-056)")
    print("  (+ Continuous Learning, ADR-030, pre-existentă, gatată OFF implicit)")
    print("═" * 78)

    started_at = datetime.now(timezone.utc).isoformat()
    report: list[dict[str, Any]] = []
    run_id = _deschide_rand_audit(started_at)

    _run_stage("1-4. Discovery + API Providers + Validation + Canonical Database", _stage_api_providers, report)
    _run_stage("5. Flashscore (Discovery + fetch/persist, Delta Sync)", _stage_flashscore, report)
    _run_stage("6. Team DNA", _stage_team_dna, report)
    _run_stage("7. Oracle Data Layer", _stage_oracle_data_layer, report)
    # SINGURA etapă marcată critică azi, și e marcată pentru un motiv măsurat:
    # a murit la 2,3 s în patru nopți consecutive (18-21 oct, nume de fișier de
    # cache peste 255 de octeți) iar jobul a raportat VERDE de fiecare dată.
    # Fără ea, rândul `control` nu se mai împrospătează — adică exact sursa pe
    # care ADR-072 a promovat-o la bază de decizie pentru promovări.
    #
    # Celelalte 9 etape rămân NEmarcate deliberat: nu avem încă istoricul lor
    # de eșecuri (raportul pe etape nu se persistă nicăieri), deci a le marca
    # acum ar fi ghicit, nu măsurat.
    _run_stage("[extra, ADR-056] Challenger Shadow Batch (logare predicții pe toate meciurile)",
               _stage_challenger_shadow_batch, report, critic=True)
    _run_stage("[extra, pre-existentă] Continuous Learning (ADR-030)", _stage_ml_refresh_pre_existing, report)
    _run_stage("8. Diagnostics", _stage_diagnostics, report)
    _run_stage("9. Cleanup (Season Cleanup — dry run)", _stage_cleanup, report)
    _run_stage("10. Backup", _stage_backup, report)

    finished_at = datetime.now(timezone.utc).isoformat()
    ok_count = sum(1 for r in report if r["ok"])
    fail_count = len(report) - ok_count

    print()
    print("═" * 78)
    print(f"  RAPORT FINAL — Night Sync")
    print(f"  Început: {started_at}   Sfârșit: {finished_at}")
    print(f"  Etape: {ok_count} reușite, {fail_count} eșuate din {len(report)}")
    for r in report:
        status = "✅" if r["ok"] else "❌"
        # Marcajul apare DOAR pe o etapă critică EȘUATĂ: pe cele reușite ar fi
        # zgomot, iar pe cele necritice ar sugera că jobul devine roșu din
        # cauza lor. Cine citește raportul trebuie să poată spune din prima
        # linie DE CE jobul e roșu.
        eticheta = "  ⟵ CRITICĂ, jobul eșuează din cauza ei" if (
            not r["ok"] and r.get("critic", False)) else ""
        print(f"    {status} {r['stage']} ({r['duration_s']}s){eticheta}")

        # [ADAUGAT 2026-08-27] Defalcarea pe pasii interiori, pentru etapele
        # care o intorc. Fara asta, `step_durations_s` era calculat corect,
        # cablat corect prin `_stage_api_providers()`, stocat in
        # `report[...]["detail"]` — si NICIODATA afisat. Cablare cu un pas mai
        # putin decat trebuia: exact clasa de defect "extragere buna, fir
        # netaiat" pe care o semnalam in alta parte.
        #
        # Locul conteaza: `run_daily.run()` isi tiparea deja propriul rezumat,
        # dar la MIJLOCUL rularii de noapte (~06:45 la rularea din 27 august),
        # iar API-ul de log-uri GitHub intoarce doar ultimele ~5.000 de linii —
        # fereastra incepea la 07:28. Tiparit aici, la final, intra garantat
        # in fereastra citibila.
        durate = (r.get("detail") or {}) if isinstance(r.get("detail"), dict) else {}
        pasi = durate.get("step_durations_s") or {}
        if pasi:
            for nume, secunde in sorted(pasi.items(), key=lambda kv: kv[1], reverse=True):
                print(f"         {secunde:>8.1f}s  {nume}")
            netimed = durate.get("manifest_steps_not_timed") or []
            extra = durate.get("steps_missing_from_manifest") or []
            if netimed:
                print(f"         [ATENȚIE] pași declarați dar necronometrați: {netimed}")
            if extra:
                print(f"         [ATENȚIE] durate pentru pași absenți din manifest: {extra}")
    print("═" * 78)
    print()

    # Rândul de audit se închide DUPĂ raportul tipărit: dacă scrierea în bază
    # ar arunca (nu poate — e prinsă — dar să rămână adevărat și dacă cineva
    # relaxează garda), raportul a fost deja afișat, nu pierdut.
    critice = etape_critice_esuate(report)
    _inchide_rand_audit(
        run_id,
        rezumat_pentru_audit(report, started_at, finished_at),
        critice,
    )

    return report


if __name__ == "__main__":
    # [ADAUGAT 2026-10-21] Înainte, aici era `run()` simplu: raportul era
    # calculat corect, tipărit corect, și ARUNCAT. Jobul ieșea cu 0 oricâte
    # etape eșuau — de aceea „Challenger Shadow Batch" a putut muri patru nopți
    # la rând sub un job verde. Clasa `check_data_health` inversată: roșu-mereu
    # te antrenează să ignori, verde-mereu te antrenează să nu te uiți.
    #
    # Ies cu 1 DOAR pentru etapele marcate critice. O etapă necritică eșuată
    # lasă jobul verde, exact ca înainte — schimbarea nu colorează roșu nimic
    # ce nu a fost marcat deliberat.
    _raport = run()
    _critice = etape_critice_esuate(_raport)
    if _critice:
        print(f"IEȘIRE 1 — etape critice eșuate: {', '.join(_critice)}")
        raise SystemExit(1)
