"""
Teste pentru learning_core.blend_challenger_shadow (Pasul 13, derivat din
ADR-050) — tipar identic tests/test_challenger_shadow_adapter.py, dar
pentru Challenger-ul de tip Blend (algorithm_family="blend_v1"). Verifică
orchestrarea internă: log_shadow_for_active_blend_challenger(), singurul
punct de intrare public folosit de oracle_engine._log_blend_challenger_shadow().
"""
from learning_core import blend_challenger_shadow


def _base_kwargs(**overrides) -> dict:
    base = dict(
        league_scope="all",
        oracle_probs=(0.40, 0.30, 0.30),
        features={"home_elo": 1550, "away_elo": 1500},
        fixture_id="fx-1", home_xg=1.4, away_xg=1.1,
        league="Test League", home_team="Home FC", away_team="Away FC",
        kickoff_date="2026-07-14",
    )
    base.update(overrides)
    return base


def test_noop_when_no_active_blend_challenger(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara Challenger Blend activ")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    result = blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    assert result is False


def test_noop_when_artifact_unavailable(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-blend-1"},
    )
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara artefact valid")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    result = blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    assert result is False


def test_active_challenger_calls_get_active_challenger_with_blend_family(monkeypatch):
    """Familia hardcodată blend_v1 (Pasul 13 §... — un singur algoritm compus
    azi, nicio generalizare peste mai multe familii, YAGNI)."""
    seen = {}

    def _capture(family, scope):
        seen["family"] = family
        seen["scope"] = scope
        return None

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _capture)

    blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs(league_scope="all"))

    assert seen["family"] == "blend_v1"
    assert seen["scope"] == "all"


class _FakeMLModel:
    def predict_proba(self, X):
        return [[0.5, 0.3, 0.2]]

    def predict(self, X, output_margin=False):
        if output_margin:
            return [[3.0, 1.0, 0.0]]
        return [0]


def test_logs_treatment_and_control_with_correct_groups(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-blend-1"},
    )
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: _FakeMLModel(),
    )
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda run_id: {"samples_used": 200},
    )
    logged_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: logged_calls.append(kw) or True,
    )

    kwargs = _base_kwargs()
    result = blend_challenger_shadow.log_shadow_for_active_blend_challenger(**kwargs)

    assert result is True
    assert len(logged_calls) == 2
    groups = {c["experiment_group"] for c in logged_calls}
    assert groups == {"treatment", "control"}

    treatment = next(c for c in logged_calls if c["experiment_group"] == "treatment")
    assert treatment["experiment_version"] == "run-blend-1"
    assert treatment["experiment_name"] == "blend_v1"
    # blend intre Oracle (0.40, 0.30, 0.30) si ML (0.5, 0.3, 0.2) — nici
    # Oracle pur, nici ML pur (dovedeste ca blend_predictions() a rulat)
    assert treatment["prob_home"] not in (0.40, 0.5)
    assert abs(treatment["prob_home"] + treatment["prob_draw"] + treatment["prob_away"] - 1.0) < 1e-6

    control = next(c for c in logged_calls if c["experiment_group"] == "control")
    assert (control["prob_home"], control["prob_draw"], control["prob_away"]) == kwargs["oracle_probs"]


def test_sample_factor_scales_ml_contribution(monkeypatch):
    """blend_predictions() scalează contribuția ML după samples_used
    (Implementation Plan Pasul 13 §5) — puține eșantioane => blend aproape
    identic cu Oracle pur."""
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-blend-1"},
    )
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: _FakeMLModel(),
    )
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda run_id: {"samples_used": 0},
    )
    logged_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: logged_calls.append(kw) or True,
    )

    oracle_probs = (0.40, 0.30, 0.30)
    blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs(oracle_probs=oracle_probs))

    treatment = next(c for c in logged_calls if c["experiment_group"] == "treatment")
    assert abs(treatment["prob_home"] - oracle_probs[0]) < 1e-6
    assert abs(treatment["prob_draw"] - oracle_probs[1]) < 1e-6
    assert abs(treatment["prob_away"] - oracle_probs[2]) < 1e-6


def test_uses_calibrated_path_when_available(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-blend-1"},
    )
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: _FakeMLModel(),
    )
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: 2.0,
    )
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda run_id: {"samples_used": 200},
    )

    uncalibrated_calls = []
    calibrated_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: calibrated_calls.append(kw) or True,
    )

    blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    calibrated_treatment = next(c for c in calibrated_calls if c["experiment_group"] == "treatment")

    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: uncalibrated_calls.append(kw) or True,
    )
    blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    uncalibrated_treatment = next(c for c in uncalibrated_calls if c["experiment_group"] == "treatment")

    assert calibrated_treatment["prob_home"] != uncalibrated_treatment["prob_home"]


def test_exceptions_in_challenger_manager_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata in challenger_manager")

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _boom)

    result = blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    assert result is False


def test_shadow_testing_error_does_not_propagate(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-blend-1"},
    )
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: _FakeMLModel(),
    )
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: None,
    )
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda run_id: {"samples_used": 200},
    )

    def _boom(**kw):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _boom)

    result = blend_challenger_shadow.log_shadow_for_active_blend_challenger(**_base_kwargs())
    assert result is False


def test_samples_used_defaults_to_zero_when_training_run_not_found(monkeypatch):
    """training_runs.samples_used e NOT NULL DEFAULT 0 in schema (migration
    002) — deci fallback-ul la 0 conteaza doar cand get_training_run()
    intoarce None (run negasit/Supabase indisponibil), niciodata pt o
    coloana lipsa dintr-un rand existent. Aici verificam explicit cazul
    None: samples_used=0 => sample_factor=0 => blend_predictions()
    degradeaza la Oracle pur, exact ca la test_sample_factor_scales_ml_contribution."""
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: _FakeMLModel(),
    )
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact",
        lambda run_id: None,
    )
    monkeypatch.setattr("supabase_client.get_training_run", lambda run_id: None)

    oracle_probs = (0.40, 0.30, 0.30)
    result = blend_challenger_shadow.predict_with_blend_challenger(
        oracle_probs, {"home_elo": 1500}, "run-blend-missing",
    )

    assert result is not None
    ph, pd_, pa = result
    assert abs(ph - oracle_probs[0]) < 1e-6
    assert abs(pd_ - oracle_probs[1]) < 1e-6
    assert abs(pa - oracle_probs[2]) < 1e-6


def test_predict_with_blend_challenger_none_when_model_missing(monkeypatch):
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda run_id: None,
    )
    result = blend_challenger_shadow.predict_with_blend_challenger(
        (0.40, 0.30, 0.30), {"home_elo": 1500}, "run-blend-1",
    )
    assert result is None
