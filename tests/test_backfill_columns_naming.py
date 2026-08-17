"""Gardă permanentă contra target leakage prin coloane POST-meci — audit
ADR-051/052 (2026-08-17).

Context: `sync/backfill_features.py` conține o listă de coloane numită
înainte `FEATURE_COLUMNS` — coliziune de nume cu `ml_predictor.
FEATURE_COLUMNS`, care e o listă DIFERITĂ (inputurile reale ale modelului).
Lista de backfill include `home_elo_after`/`away_elo_after`: ratingul ELO
de DUPĂ meci, care codifică direct rezultatul. Dacă acele coloane ar ajunge
vreodată în feature set-ul ML, modelul ar "vedea" cine a câștigat —
target leakage catastrofal, invizibil în walk-forward (walk-forward
protejează ordinea temporală ÎNTRE meciuri, nu conținutul unui feature).

Testele de aici nu verifică o implementare, ci o INVARIANTĂ: oricât s-ar
schimba codul, nicio coloană post-meci nu are voie în FEATURE_COLUMNS.
Fără rețea."""
from __future__ import annotations

import sync.backfill_features as bf
from ml_predictor import FEATURE_COLUMNS

# Coloane care reflectă starea de DUPĂ meci — interzise ca input ML.
POST_MATCH_COLUMNS = ("home_elo_after", "away_elo_after")


def test_post_match_columns_never_in_ml_feature_set():
    """INVARIANTA CENTRALĂ — dacă acest test pică, modelul ML are acces la
    rezultatul meciului pe care încearcă să-l prezică."""
    for col in POST_MATCH_COLUMNS:
        assert col not in FEATURE_COLUMNS, (
            f"{col!r} reflectă starea de DUPĂ meci (codifică rezultatul) și NU "
            f"are voie în ml_predictor.FEATURE_COLUMNS — target leakage."
        )


def test_no_ml_feature_column_has_after_suffix():
    """Generalizare: orice coloană viitoare cu sufix `_after` e, prin
    convenția proiectului (ADR-023), o valoare post-meci."""
    offenders = [c for c in FEATURE_COLUMNS if c.endswith("_after")]
    assert not offenders, f"Coloane post-meci găsite în FEATURE_COLUMNS: {offenders}"


def test_backfill_constant_renamed_and_no_legacy_alias():
    """Redenumirea trebuie să fie completă — un alias `FEATURE_COLUMNS`
    păstrat în backfill_features ar reintroduce exact ambiguitatea pe care
    redenumirea o elimină."""
    assert hasattr(bf, "BACKFILL_COLUMNS"), "BACKFILL_COLUMNS lipsește din backfill_features"
    assert not hasattr(bf, "FEATURE_COLUMNS"), (
        "backfill_features.FEATURE_COLUMNS încă există — coliziunea de nume cu "
        "ml_predictor.FEATURE_COLUMNS nu a fost eliminată."
    )


def test_backfill_columns_still_contains_post_match_elo():
    """Redenumirea NU trebuie să schimbe conținutul — backfill-ul chiar
    trebuie să scrie aceste coloane (consumator: servirea live, ADR-023)."""
    for col in POST_MATCH_COLUMNS:
        assert col in bf.BACKFILL_COLUMNS


def test_the_two_lists_are_genuinely_different():
    """Documentează prin test de ce redenumirea era necesară: listele chiar
    diferă, deci confuzia dintre ele avea consecințe reale."""
    assert set(bf.BACKFILL_COLUMNS) != set(FEATURE_COLUMNS)
