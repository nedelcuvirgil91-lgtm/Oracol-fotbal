"""
Teste pentru _softmax_with_temperature() și MLPredictorEngine._fit_temperature()
(ADR-049, Pasul 10a) — funcții pure, fără rețea/Supabase.
"""
import numpy as np
import pytest

from ml_predictor import MLPredictorEngine, _softmax_with_temperature


# ── _softmax_with_temperature() — stabilitate numerică, validare T ──────

def test_softmax_with_temperature_rows_sum_to_one():
    margins = np.array([[2.0, 1.0, 0.1], [0.0, 0.0, 0.0], [-5.0, 5.0, 0.0]])
    probs = _softmax_with_temperature(margins, temperature=1.0)
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_softmax_with_temperature_t_equals_one_matches_plain_softmax():
    margins = np.array([[2.0, 1.0, 0.1]])
    probs = _softmax_with_temperature(margins, temperature=1.0)
    expected = np.exp(margins - margins.max()) / np.exp(margins - margins.max()).sum()
    assert np.allclose(probs, expected)


def test_softmax_with_temperature_high_t_flattens_distribution():
    """T mare -> distribuție mai aproape de uniform (mai puțină încredere) —
    exact corecția cerută de ADR-049 (supraîncredere -> T>1)."""
    margins = np.array([[5.0, 0.0, 0.0]])
    probs_t1 = _softmax_with_temperature(margins, temperature=1.0)
    probs_t10 = _softmax_with_temperature(margins, temperature=10.0)
    assert probs_t10[0, 0] < probs_t1[0, 0]
    assert probs_t10[0, 0] > 1.0 / 3.0  # tot dominant, dar mai puțin extrem


def test_softmax_with_temperature_no_overflow_on_large_margins():
    """Stabilitate numerică (logit shifting) — margini mari nu produc
    NaN/inf, spre deosebire de o implementare naivă fără shifting."""
    margins = np.array([[1000.0, 999.0, 998.0]])
    probs = _softmax_with_temperature(margins, temperature=0.1)
    assert np.all(np.isfinite(probs))
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_softmax_with_temperature_rejects_non_positive_t():
    margins = np.array([[1.0, 0.0, 0.0]])
    with pytest.raises(ValueError):
        _softmax_with_temperature(margins, temperature=0.0)
    with pytest.raises(ValueError):
        _softmax_with_temperature(margins, temperature=-1.0)


# ── _fit_temperature() — fitting pe set OOF ──────────────────────────────

def test_fit_temperature_returns_none_for_degenerate_single_class():
    margins = np.array([[1.0, 0.0, 0.0]] * 30)
    labels = np.zeros(30, dtype=int)  # o singură clasă reprezentată
    assert MLPredictorEngine._fit_temperature(margins, labels) is None


def test_fit_temperature_returns_none_for_too_few_samples():
    margins = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    labels = np.array([0, 1])
    assert MLPredictorEngine._fit_temperature(margins, labels) is None


def test_fit_temperature_returns_positive_value_for_valid_input():
    rng = np.random.RandomState(0)
    n = 200
    labels = rng.randint(0, 3, size=n)
    # margini artificial suprazcrezute pe eticheta reala (overconfident,
    # exact tiparul diagnosticat empiric în ORACLE_VS_ML_REPORT.md §3.2)
    margins = np.full((n, 3), -3.0)
    margins[np.arange(n), labels] = 6.0

    T = MLPredictorEngine._fit_temperature(margins, labels)

    assert T is not None
    assert T > 0


def test_fit_temperature_falls_back_to_one_when_optimizer_does_not_beat_baseline(monkeypatch):
    """[ADAUGAT — review Pasul 10a, observatia 4] Testeaza direct garda:
    daca optimizatorul intoarce un T al carui log-loss NU e strict mai bun
    decat baseline-ul T=1.0, _fit_temperature() trebuie sa cada pe T=1.0,
    nu pe valoarea gasita de optimizator — indiferent cat e de aproape.
    Optimizatorul real e monkeypatch-uit cu un rezultat controlat, ca
    testul sa verifice garda in sine, nu comportamentul statistic al unei
    optimizari reale pe date zgomotoase (unde "egalitate exacta" nu e
    garantata pe un esantion finit)."""
    rng = np.random.RandomState(0)
    n = 200
    labels = rng.randint(0, 3, size=n)
    margins = rng.normal(size=(n, 3))

    class _FakeResult:
        success = True
        x = 3.7  # T "gasit" de optimizator
        fun = None  # completat mai jos, egal cu baseline -> nu e strict mai bun

    def _fake_minimize_scalar(func, bounds=None, method=None):
        baseline = func(1.0)
        result = _FakeResult()
        result.fun = baseline  # exact egal -> nu trece testul "strict mai bun"
        return result

    import scipy.optimize
    monkeypatch.setattr(scipy.optimize, "minimize_scalar", _fake_minimize_scalar)

    T = MLPredictorEngine._fit_temperature(margins, labels)

    assert T == 1.0, f"cand optimizatorul nu bate baseline-ul, garda trebuie sa intoarca T=1.0, a iesit {T}"


def test_fit_temperature_corrects_overconfidence():
    """Pe un set suprazcrezut sintetic, T ajustat trebuie să fie > 1
    (reduce încrederea) — verificare directă a direcției corecției."""
    rng = np.random.RandomState(1)
    n = 300
    labels = rng.randint(0, 3, size=n)
    margins = np.full((n, 3), -4.0)
    margins[np.arange(n), labels] = 8.0
    # zgomot: 30% din etichete sunt gresite fata de clasa cu margine maxima
    flip_idx = rng.choice(n, size=int(n * 0.3), replace=False)
    labels = labels.copy()
    labels[flip_idx] = (labels[flip_idx] + 1) % 3

    T = MLPredictorEngine._fit_temperature(margins, labels)

    assert T is not None
    assert T > 1.0, f"T ar trebui sa reduca increderea (T>1) pe un set suprazcrezut, a iesit {T}"
