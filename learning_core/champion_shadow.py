"""
================================================================================
FOOTBALL ORACLE — Learning Core: Champion Shadow Adapter (ADR-082)
================================================================================
Module: learning_core/champion_shadow.py

Banda de predicții a campionului PROMOVAT. Fișier NOU, separat de
`challenger_shadow.py` și `blend_challenger_shadow.py`, care rămân neatinse.

── Ce problemă rezolvă ────────────────────────────────────────────────────────
`log_shadow_for_active_challenger` nu loghează decât pentru un Challenger
ACTIV (docstring-ul ei, linia 94). Un model promovat iese din FSM, deci nimic
nu-l mai loghează: campionul `blend_v1/8ac89c70` a scris ultima dată pe
2026-08-23 09:23:17 — cu 13 minute înainte de promovarea de la 09:36:27 — și
ZERO rânduri în cele 65 de zile următoare.

Consecința, măsurată: din 1135 de meciuri ale ferestrei Champion Guardian,
doar 172 (15,2%) au o predicție proprie a campionului; de la 1 septembrie,
~99% nu au niciuna. Gardianul citea `match_history.prob_*_pred` — ieșirea
Poisson a lui Oracle — deci raporta sănătatea lui Oracle sub numele
campionului (ADR-082 §1.1).

── Ce NU face, deliberat ──────────────────────────────────────────────────────
NU calculează predicția campionului. Aceasta e deja calculată la fiecare meci
servit, de `oracle_engine._get_blend_v1_champion_prediction()` (ADR-061, flag
`blend_v1_champion_display_enabled`), și se arunca. Adaptorul o primește ca
parametru. Un al doilea apel la predictor ar putea divergea tăcut de ce s-a
afișat — iar o bandă care nu corespunde afișării e mai rea decât niciuna.

NU citește niciun flag: poarta trăiește în Oracle Engine, care deține
configurația (aceeași regulă ca în `challenger_shadow`, ADR-073).

NU promovează, NU retrage, NU tranziționează nimic. Citește `model_champions`
exclusiv prin `get_active_champion` și scrie exclusiv prin
`shadow_testing.log_shadow_prediction()`.

── De ce grup propriu, `'champion'` ──────────────────────────────────────────
Verificat în producție: `shadow_predictions` nu are niciun `CHECK` pe
`experiment_group`, iar cheia de conflict e
`fixture_id, experiment_name, experiment_version, experiment_group,
processing_stage`. Deci grupul nou e un rând distinct — zero migrare, iar cele
394 de rânduri `treatment` istorice ale aceluiași `training_run_id` NU se
ating și NU se rescriu (North Star #9: dovada că problema a existat se
păstrează).

Reutilizarea lui `'treatment'` a fost respinsă explicit (ADR-082 §7c): ar
amesteca, sub același `training_run_id`, predicții făcute ca Challenger cu
predicții făcute ca Campion, iar seria ar avea o gaură de 65 de zile la mijloc
fără nimic care s-o explice în date.

── De ce se scrie și rândul `control` ────────────────────────────────────────
`shadow_testing._control_rows_for()` (liniile 457-462) împerechează pe
`experiment_name` + `experiment_version` + `experiment_group='control'` +
`processing_stage='final'`. Seria de `control` a campionului se oprește și ea
pe 23 august, deci fără rândul pereche banda ar fi nepereche și neevaluabilă.

Rândul `control` al benzii NU primește `feature_metadata`. Motivul e măsurat,
nu economic: pe toate cele 512 meciuri comune, rândul `control` e identic bit
cu bit între familii (0 probabilități diferite, 0 `ml_features` diferite,
divergență maximă 0,0e-10). O a treia copie a înregistrării ADR-073 ar fi
duplicare pură, la ~1065 de octeți pe rând.

Best-effort, simetric cu celelalte două adaptoare: orice eșec întoarce False,
niciodată o excepție propagată către Oracle Engine (Regula #8).
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.ChampionShadow")

# Valoarea de grup a benzii se importă din `supabase_client` — stratul de date,
# unde o citește și sursa gardianului (`get_champion_lane_outcomes`). Definită
# acolo, nu aici, fiindcă invers ar fi o dependință „în sus" (North Star #10):
# stratul de date n-are voie să importe din Learning Core. Două șiruri scrise de
# mână, în scriitor și în cititor, ar putea divergea — clasa de defect plătită
# deja la `_PAGE_SIZE`.
from supabase_client import EXPERIMENT_GROUP_CHAMPION  # noqa: E402  (re-export)


def log_shadow_for_active_champion(
    algorithm_family: str, league_scope: str, fixture_id: str,
    champion_prob_home: float, champion_prob_draw: float, champion_prob_away: float,
    control_prob_home: float, control_prob_draw: float, control_prob_away: float,
    home_xg: float, away_xg: float,
    league: str, home_team: str, away_team: str, kickoff_date: str,
) -> bool:
    """Punctul de intrare PUBLIC folosit de `oracle_engine.py` — singurul.

    `champion_prob_*` sunt predicția campionului, DEJA calculată de apelant
    (`pred.blend_v1_champion_prediction`). Nu se recalculează aici — vezi
    docstring-ul modulului.

    Întoarce False, fără să scrie nimic, dacă nu există campion activ pentru
    `(algorithm_family, league_scope)`. Un campion absent e o stare legitimă
    (familia `xgboost_v1` n-a avut niciodată unul), nu o eroare."""
    try:
        import supabase_client as sb

        champion = sb.get_active_champion(algorithm_family, league_scope)
        if champion is None:
            return False
        training_run_id = champion.get("training_run_id")
        if not training_run_id:
            # Un campion fără `training_run_id` n-ar putea fi identificat în
            # bandă, iar un rând neidentificabil e mai rău decât niciun rând
            # (North Star #9). Nu se aproximează (Regula #8).
            logger.warning("[ChampionShadow] campion activ fără training_run_id "
                           "pentru %s/%s — nu se scrie nimic",
                           algorithm_family, league_scope)
            return False

        import shadow_testing

        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=algorithm_family, experiment_version=training_run_id,
            home_xg=home_xg, away_xg=away_xg,
            prob_home=champion_prob_home, prob_draw=champion_prob_draw,
            prob_away=champion_prob_away,
            experiment_group=EXPERIMENT_GROUP_CHAMPION, processing_stage="final",
            league=league, home_team=home_team, away_team=away_team,
            kickoff_date=kickoff_date,
        )
        # Rândul pereche. `feature_metadata` NU se pasează — vezi docstring-ul
        # modulului: o a treia copie a înregistrării ADR-073, măsurat identică.
        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=algorithm_family, experiment_version=training_run_id,
            home_xg=home_xg, away_xg=away_xg,
            prob_home=control_prob_home, prob_draw=control_prob_draw,
            prob_away=control_prob_away,
            experiment_group="control", processing_stage="final",
            league=league, home_team=home_team, away_team=away_team,
            kickoff_date=kickoff_date,
        )
        return True
    except Exception as exc:
        logger.warning("[ChampionShadow] log_shadow_for_active_champion eșuat: %s", exc)
        return False
