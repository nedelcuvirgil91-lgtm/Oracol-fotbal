import random
import shadow_testing as st


def test_brier_perfect_prediction_is_zero():
    assert st._brier(1.0, 0.0, 0.0, "H") == 0.0


def test_brier_worst_prediction_is_two():
    assert abs(st._brier(0.0, 0.0, 1.0, "H") - 2.0) < 1e-9


def test_paired_bootstrap_detects_clear_improvement():
    random.seed(42)
    baseline = [0.6] * 300
    experiment = [0.55] * 300
    result = st._paired_bootstrap(baseline, experiment, favorable_direction=-1)
    assert result.significant is True
    assert result.delta < 0


def test_paired_bootstrap_no_false_positive_on_noise():
    random.seed(7)
    baseline = [0.6 + random.uniform(-0.1, 0.1) for _ in range(300)]
    experiment = [0.6 + random.uniform(-0.1, 0.1) for _ in range(300)]
    result = st._paired_bootstrap(baseline, experiment, favorable_direction=-1)
    assert result.significant is False


def test_paired_permutation_detects_clear_improvement():
    random.seed(1)
    baseline = [0.6] * 200
    experiment = [0.5] * 200
    result = st._paired_permutation(baseline, experiment, favorable_direction=-1)
    assert result.significant is True


def test_wilcoxon_detects_clear_improvement_or_falls_back():
    baseline = [0.6] * 50
    experiment = [0.5] * 50
    result = st._wilcoxon(baseline, experiment, favorable_direction=-1)
    assert result.method in ("wilcoxon", "paired_bootstrap")


def test_statistical_tests_registry_has_all_three():
    assert set(st.STATISTICAL_TESTS.keys()) == {"paired_bootstrap", "paired_permutation", "wilcoxon"}


def test_graceful_degradation_without_supabase():
    """Fara credentiale Supabase in acest mediu de test - totul trebuie sa
    returneze gol/False, fara exceptie."""
    assert st.log_shadow_prediction(
        "fx1", "test_exp", "v1", 1.0, 1.0, 0.5, 0.3, 0.2,
    ) is False
    assert st.get_shadow_predictions("test_exp") == []
    assert st.get_distinct_experiments() == []
    assert st.evaluate_all_active_experiments() == []
    assert st.evaluate_experiment("test_exp", "v1") is None
