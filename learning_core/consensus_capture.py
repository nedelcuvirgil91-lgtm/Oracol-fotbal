"""
================================================================================
FOOTBALL ORACLE — Learning Core: Consensus Capture Adapter (ADR-033, Faza 1)
================================================================================
Module: learning_core/consensus_capture.py

Singura frontieră între Oracle Engine (Prediction Pipeline) și infrastructura
proprie de eșantionare ADR-033 — simetric ca rol cu
`learning_core/challenger_shadow.py`, dar infrastructură complet separată,
independentă de `shadow_predictions`/Challenger Framework (decizie explicită
din ADR-033, Clarification Pass: „reutilizează tiparul, nu infrastructura").

Strict observațional — persistă exact ce ADR-031 produce deja
(`MatchPrediction.raw_predictions`), fără să calculeze, interpreteze sau
decidă nimic. Faza 2 (evaluarea T1, `learning_core/consensus_validation.py`)
citește separat, periodic — acest modul nu declanșează și nu apelează
niciodată evaluarea.

`capture_raw_predictions()` nu întoarce nimic folosit de apelant pentru a
construi predicția — e strict un side effect, la fel ca Shadow Adapter-ul.
Fail-open necondiționat (Regula #8): orice eșec (Supabase indisponibil,
eroare de rețea, orice altă cauză) întoarce False, niciodată excepție —
predicția servită utilizatorului nu e niciodată afectată.
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.ConsensusCapture")


def capture_raw_predictions(
    fixture_id: str, raw_predictions: list,
    league: str, home_team: str, away_team: str, kickoff_date: str | None,
) -> bool:
    """Persistă perechea de ieșiri brute (ADR-031) pentru un fixture, o
    singură dată — `UNIQUE(fixture_id)` la nivel de bază de date face ca
    apeluri repetate pentru același fixture (rerulări Streamlit — confirmat
    ca scenariu real, nu ipotetic, la reconnaissance) să fie no-op sigur,
    nu eroare, nu duplicare.

    Best-effort, fail-open: orice excepție e prinsă aici, niciodată
    propagată către Oracle Engine."""
    if not raw_predictions:
        return False
    try:
        import supabase_client as sb

        return sb.save_consensus_capture_sample(
            fixture_id=fixture_id, league=league,
            home_team=home_team, away_team=away_team,
            kickoff_date=kickoff_date, raw_predictions=raw_predictions,
        )
    except Exception as exc:
        logger.debug("[ConsensusCapture] capture_raw_predictions eșuat pentru %s: %s",
                      fixture_id, exc)
        return False
