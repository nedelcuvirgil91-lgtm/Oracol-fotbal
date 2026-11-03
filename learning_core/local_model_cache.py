"""
================================================================================
FOOTBALL ORACLE — Learning Core: Local Model Cache
================================================================================
Module: learning_core/local_model_cache.py

[ADAUGAT — fix „aplicația pornește foarte greu"] Al doilea nivel de servire
ML, sub Champion, deasupra „fără ML": încarcă ultimul artefact antrenat cu
succes — NICIODATĂ nu antrenează nimic aici. Înainte, absența unui Champion
promovat însemna că `oracle_engine._initialize_ml()` reantrena XGBoost
sincron, la fiecare pornire de motor (fiecare restart de container, fiecare
„Clear cache") — 6 antrenări complete (5 fold-uri walk-forward + fit final)
pe tot istoricul (peste 50.000 de meciuri), blocând startup-ul 3-5 minute.
Acest modul elimină complet acel blocaj: antrenarea reală rămâne exclusiv
responsabilitatea learning_core/continuous_learning.py (Faza B, ADR-030),
decuplată, în fundal (cron GitHub Actions `continuous_learning.yml`),
niciodată în calea de servire.

Structural, oglindește champion_loader.py — aceleași condiții de
utilizabilitate (status=='trained', algorithm_version compatibil, artefact
încărcabil, deserializare funcțională reală) — dar sursa e
list_recent_training_runs() (orice antrenare reușită, indiferent dacă a
devenit vreodată Challenger/Champion), nu get_active_champion(). Încearcă
rândurile în ordine de la cel mai recent — dacă cel mai nou nu are artefact
persistat (ex. un retrain manual, retrain_ml_model(), care nu persistă
model_artifact_storage), cade grațios pe următorul cel mai recent cu
artefact valid, nu declară cache-ul indisponibil.

Nu implică nicio validare statistică — spre deosebire de un Champion
promovat, un model din cache NU a trecut prin Shadow Evaluation (North
Star #2); e tratat identic cu ce oracle_engine.py eticheta deja
`ml_source="local"` înainte de acest fix — doar încărcat, nu reantrenat.

[ADAUGAT — ADR-086, Decizia B] Singura excepție la fraza de mai sus, și e
NEGATIVĂ, nu pozitivă: cu flagul `local_cache_fsm_guard_enabled` activ, un
artefact al cărui Challenger e `REJECTED` nu mai e servit. Regula rămâne
„un artefact respins nu servește", NICIODATĂ „doar un Challenger/campion
servește" — un prag pozitiv ar opri ML-ul azi (niciunul din cele 5
artefacte măsurate n-a fost vreodată campion) și ar contrazice ADR-051.
Până la 2026-11-03 selecția nu consulta deloc starea FSM, iar siguranța
venea din ORDINE, nu din gardă: respingerile au venit cu 12,6–23,5 zile
DUPĂ ce artefactul fusese deja înlocuit (ADR-086 §4.1). Riscul pe care
ordinea nu-l acoperă: o expirare comisă fără ca Faza B să apuce să
antreneze înlocuitorul — atunci artefactul respins ar servi nelimitat.

Complet izolat: niciun alt fișier din proiect nu importă acest modul în
afara `oracle_engine.py` și propriului test.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.LearningCore.LocalModelCache")

_MAX_CANDIDATES = 10

# [ADAUGAT — ADR-086, Decizia B] Stările de Challenger care DESCALIFICĂ un
# artefact de la servire.
#
# 🔴 NU se folosește `challenger_manager.TERMINAL_STATES` aici, și nu e o
# scăpare — e exact capcana consemnată în ADR-086 §4.0. Constanta aceea e
# `{"PROMOTED", "REJECTED"}`, fiindcă răspunde la întrebarea „s-a terminat
# ciclul FSM?". Întrebarea de AICI e alta: „mai are voie să servească?" — iar
# `PROMOTED` e campionul, adică exact artefactul care TREBUIE să servească.
# Reutilizarea constantei ar fi oprit servirea campionului, inversul scopului.
# O gardă dedicată cade dacă cineva o reintroduce.
#
# Clasa: *o constantă corectă pentru întrebarea ei devine greșită pentru altă
# întrebare* — ruda lui `has_stats` („pagina descărcată" citit ca „extragere
# reușită") și a lui `referee` folosit ca martor (ADR-077).
_STARI_CARE_NU_SERVESC = frozenset({"REJECTED"})

_FLAG_GARDA_FSM = "local_cache_fsm_guard_enabled"


def is_fsm_guard_enabled() -> bool:
    """`local_cache_fsm_guard_enabled` (ADR-086, Decizia B) — implicit
    **False** (North Star #3): un merge pe `main` NU schimbă ce artefact
    servește.

    FAIL-OPEN deliberat, cu motivul scris. Dacă citirea configurației eșuează
    (Supabase indisponibil, credențiale lipsă), se întoarce `False`, adică
    **comportamentul curent de producție** — nu `True`. Direcția contează:
    un fail-closed ar însemna că un hopa de configurație oprește ML-ul
    complet (vezi ADR-086 §4.2 — garda activă fără Challenger netermina duce
    la Oracle-only), ceea ce e o regresie mai mare decât statu-quo-ul pe care
    garda vrea să-l îmbunătățească. Același tipar ca
    `oracle_api._oddsapi_quota_exhausted()`."""
    try:
        import supabase_client as sb

        cfg = sb.load_config({_FLAG_GARDA_FSM: False})
        return bool(cfg.get(_FLAG_GARDA_FSM, False))
    except Exception as exc:
        logger.warning("[LocalModelCache] citirea flagului %s a eșuat — garda rămâne OPRITĂ "
                        "(comportamentul curent de producție): %s", _FLAG_GARDA_FSM, exc)
        return False


def _artefact_descalificat_de_fsm(training_run_id: str) -> bool:
    """True DOAR dacă există un rând `challengers` pentru acest artefact ȘI
    starea lui e în `_STARI_CARE_NU_SERVESC`.

    ABSENȚA unui Challenger NU descalifică — deliberat, și e decizia §5.1 din
    ADR-086: regula adoptată e **negativă** („un artefact respins nu
    servește"), niciodată „doar un Challenger/campion servește". Un prag
    pozitiv ar opri ML-ul azi, fiindcă niciunul din cele 5 artefacte măsurate
    n-a fost vreodată campion, și ar contrazice ADR-051 („niciun motor nu e
    primar prin construcție").

    Orice eșec de citire întoarce False — nu descalificăm un artefact pe baza
    unei interogări care n-a reușit (Regula #8: o stare necunoscută rămâne
    necunoscută, nu se aproximează la „respins")."""
    try:
        import supabase_client as sb

        rand = sb.get_challenger(training_run_id)
        if not rand:
            return False
        return str(rand.get("state") or "") in _STARI_CARE_NU_SERVESC
    except Exception as exc:
        logger.warning("[LocalModelCache] starea FSM a lui %s nu a putut fi citită — "
                        "artefactul NU e descalificat (stare necunoscută, nu respinsă): %s",
                        training_run_id, exc)
        return False


@dataclass
class LocalCacheLoadResult:
    training_run_id: str
    model: Any
    samples_used: int
    algorithm_family: str
    algorithm_version: str
    league_scope: str
    accuracy: float | None
    log_loss: float | None
    trained_at: str | None
    temperature: float | None


def load_latest_trained_model_or_none(algorithm_family: str, league_scope: str) -> LocalCacheLoadResult | None:
    """Ultimul artefact antrenat cu succes, servabil fără nicio antrenare.
    None dacă niciun candidat (dintre cele mai recente _MAX_CANDIDATES
    rulări) nu satisface toate condițiile — niciodată excepție propagată
    către apelant (Regula #8, degradare grațioasă, tipar identic
    champion_loader.py)."""
    try:
        import numpy as np

        import supabase_client as sb
        from learning_core import calibration_artifact_storage, model_artifact_storage
        from ml_predictor import _ALGORITHM_VERSION, FEATURE_COLUMNS

        candidates = sb.list_recent_training_runs(algorithm_family, league_scope, limit=_MAX_CANDIDATES)

        # [ADAUGAT — ADR-086, Decizia B] Flagul se citește O SINGURĂ DATĂ per
        # apel, nu per candidat — altfel ar fi până la 10 citiri de
        # configurație la fiecare pornire de motor.
        garda_fsm = is_fsm_guard_enabled()

        for training_run in candidates:
            if training_run.get("status") != "trained":
                continue
            if training_run.get("algorithm_version") != _ALGORITHM_VERSION:
                logger.warning(
                    "[LocalModelCache] Rularea %s are algorithm_version=%r, codul curent așteaptă %r — sărită.",
                    training_run.get("training_run_id"), training_run.get("algorithm_version"), _ALGORITHM_VERSION,
                )
                continue

            training_run_id = training_run["training_run_id"]

            # [ADAUGAT — ADR-086, Decizia B] Garda FSM vine ÎNAINTEA
            # descărcării artefactului, nu după. Ordinea nu e cosmetică: o
            # interogare `challengers` costă un SELECT, iar
            # `load_model_artifact()` descarcă un obiect din Supabase Storage.
            # Un artefact respins n-are niciun rost descărcat ca să fie apoi
            # aruncat. Aceeași lecție ca la `live_sync`, unde `polite_delay()`
            # rula ÎNAINTEA verificării Delta Sync și consuma jumătate din
            # rulare dormind pe un canal pe care nu cerea nimic. Un test
            # dedicat verifică ORDINEA în cod, nu doar efectul.
            if garda_fsm and _artefact_descalificat_de_fsm(training_run_id):
                logger.warning(
                    "[LocalModelCache] Artefactul %s are Challenger în stare %s — sărit, "
                    "NU servește (ADR-086 B). Artefactul nu e descărcat.",
                    training_run_id, sorted(_STARI_CARE_NU_SERVESC),
                )
                continue

            model = model_artifact_storage.load_model_artifact(training_run_id)
            if model is None:
                continue

            try:
                probe = np.zeros((1, len(FEATURE_COLUMNS)))
                model.predict_proba(probe)
            except Exception as exc:
                logger.warning(
                    "[LocalModelCache] Artefact %s încărcat dar deserializare/inferență eșuată — sărit: %s",
                    training_run_id, exc,
                )
                continue

            walk_forward_metrics = training_run.get("walk_forward_metrics") or {}
            temperature = calibration_artifact_storage.load_calibration_artifact(training_run_id)

            return LocalCacheLoadResult(
                training_run_id=training_run_id,
                model=model,
                samples_used=training_run.get("samples_used", 0),
                algorithm_family=algorithm_family,
                algorithm_version=training_run.get("algorithm_version"),
                league_scope=league_scope,
                accuracy=walk_forward_metrics.get("accuracy"),
                log_loss=walk_forward_metrics.get("log_loss"),
                trained_at=training_run.get("created_at"),
                temperature=temperature,
            )

        return None
    except Exception as exc:
        logger.warning("[LocalModelCache] load_latest_trained_model_or_none eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None
