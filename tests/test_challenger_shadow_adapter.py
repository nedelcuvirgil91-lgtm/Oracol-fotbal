"""
Teste pentru learning_core.challenger_shadow (Shadow Adapter) — Pasul 3,
addendum Chief Architect Review. Testează orchestrarea internă a
adapterului: `log_shadow_for_active_challenger()`, singurul punct de
intrare public folosit de oracle_engine.py.

Regulă arhitecturală verificată aici (din partea cealaltă a frontierei
față de tests/test_challenger_shadow_logging.py): acest modul e SINGURUL
importator legitim al learning_core.challenger_manager pentru scopul de
shadow logging — vezi tests/test_challenger_manager.py, garda actualizată.
"""
import pytest

from learning_core import challenger_shadow


def _base_kwargs(**overrides) -> dict:
    base = dict(
        algorithm_family="xgboost_v1", league_scope="all",
        features={"home_elo": 1550, "away_elo": 1500},
        fixture_id="fx-1", home_xg=1.4, away_xg=1.1,
        control_prob_home=0.45, control_prob_draw=0.28, control_prob_away=0.27,
        league="Test League", home_team="Home FC", away_team="Away FC",
        kickoff_date="2026-07-14",
    )
    base.update(overrides)
    return base


def test_noop_when_no_active_challenger(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara Challenger activ")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    result = challenger_shadow.log_shadow_for_active_challenger(**_base_kwargs())
    assert result is False


def test_noop_when_artifact_unavailable(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara artefact valid")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    result = challenger_shadow.log_shadow_for_active_challenger(**_base_kwargs())
    assert result is False


def test_logs_treatment_and_control_with_correct_groups(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: (0.9, 0.05, 0.05),
    )
    logged_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: logged_calls.append(kw) or True,
    )

    kwargs = _base_kwargs()
    result = challenger_shadow.log_shadow_for_active_challenger(**kwargs)

    assert result is True
    assert len(logged_calls) == 2
    groups = {c["experiment_group"] for c in logged_calls}
    assert groups == {"treatment", "control"}

    treatment = next(c for c in logged_calls if c["experiment_group"] == "treatment")
    assert treatment["prob_home"] == 0.9
    assert treatment["experiment_version"] == "run-xyz"
    assert treatment["experiment_name"] == "xgboost_v1"

    control = next(c for c in logged_calls if c["experiment_group"] == "control")
    assert control["prob_home"] == kwargs["control_prob_home"]
    assert control["prob_draw"] == kwargs["control_prob_draw"]
    assert control["prob_away"] == kwargs["control_prob_away"]


def test_exceptions_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata in challenger_manager")

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _boom)

    result = challenger_shadow.log_shadow_for_active_challenger(**_base_kwargs())
    assert result is False


def test_shadow_testing_error_does_not_propagate(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: (0.9, 0.05, 0.05),
    )

    def _boom(**kw):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _boom)

    result = challenger_shadow.log_shadow_for_active_challenger(**_base_kwargs())
    assert result is False
