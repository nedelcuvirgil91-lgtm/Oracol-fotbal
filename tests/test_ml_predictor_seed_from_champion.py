"""
Teste pentru MLPredictorEngine.seed_from_champion()/status_summary() —
Pasul 6 ("Golul A") + Pasul 7B ("Defectul B", Architecture Gate 7B): nicio
dublă reprezentare a aceluiași obiect — is_trained/model_version/
samples_used/feature_names/accuracy/log_loss/trained_at trebuie să fie
coerente indiferent dacă modelul provine din train() local sau dintr-un
Champion încărcat, iar status_summary() trebuie să reflecte EXCLUSIV
modelul care servește efectiv — niciodată o sursă concurentă.
"""
import numpy as np
import pytest

import ml_predictor


class _FakeModel:
    def predict_proba(self, X):
        return [[0.4, 0.3, 0.3]]

    def predict(self, X, output_margin=False):
        if output_margin:
            return [[1.0, 0.5, 0.2]]
        return [0]


def test_seed_from_champion_sets_all_descriptive_fields():
    engine = ml_predictor.MLPredictorEngine()
    model = _FakeModel()

    engine.seed_from_champion(model, samples_used=12345)

    assert engine.model is model
    assert engine.is_trained is True
    assert engine.samples_used == 12345
    assert engine.model_version == 1
    assert engine.feature_names == list(ml_predictor.FEATURE_COLUMNS)
    assert engine.last_train_status == "trained_from_champion"


def test_seed_from_champion_accepts_explicit_model_version():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=100, model_version=7)
    assert engine.model_version == 7


def test_fresh_engine_is_not_trained_before_seeding():
    """Regresie: starea implicita (inainte de train() sau seed_from_champion())
    ramane exact ca azi -- is_trained=False, samples_used=0."""
    engine = ml_predictor.MLPredictorEngine()
    assert engine.is_trained is False
    assert engine.samples_used == 0
    assert engine.model_version == 0
    assert engine.last_train_status == "not_trained"


def test_seeded_engine_predict_uses_seeded_model():
    """predict() foloseste modelul seedat identic cum ar folosi unul
    antrenat local -- nicio cale de cod separata."""
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=500)

    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}
    pred = engine.predict(features)

    assert pred is not None
    assert pred.samples_used == 500
    assert pred.model_version == 1


# ── temperature (ADR-049, Pasul 10a) — parametru aditiv, opțional ───────

def test_seed_from_champion_without_temperature_leaves_it_none():
    """Backward compatibility: apel fără `temperature` (cazul de azi, Pasul
    10b neimplementat încă) — self.temperature rămâne None, exact
    comportamentul unui model necalibrat."""
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=500)
    assert engine.temperature is None


def test_seed_from_champion_stores_explicit_temperature():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=500, temperature=1.4)
    assert engine.temperature == 1.4
    assert engine.get_calibration_temperature() == 1.4


def test_seed_from_champion_sets_champion_metadata():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(
        _FakeModel(), samples_used=500, accuracy=0.52, log_loss=1.02, trained_at="2026-07-14T00:00:00Z",
    )
    assert engine.champion_accuracy == 0.52
    assert engine.champion_log_loss == 1.02
    assert engine.champion_trained_at == "2026-07-14T00:00:00Z"


# ── seed_from_cache() — fix "aplicatia porneste foarte greu" ────────────────

def test_seed_from_cache_sets_all_descriptive_fields():
    engine = ml_predictor.MLPredictorEngine()
    model = _FakeModel()

    engine.seed_from_cache(model, samples_used=12345, training_run_id="cache-run-1")

    assert engine.model is model
    assert engine.is_trained is True
    assert engine.samples_used == 12345
    assert engine.model_version == 1
    assert engine.feature_names == list(ml_predictor.FEATURE_COLUMNS)
    assert engine.last_train_status == "trained_from_cache"


def test_seed_from_cache_sets_last_training_run_id_for_traceability():
    """Spre deosebire de seed_from_champion() (trasabilitatea vine din
    champion_diagnostic, sursă separată), _resolve_ml_traceability() cu
    ml_source=="local" citește self.ml.last_training_run_id direct —
    seed_from_cache() TREBUIE să-l populeze, altfel Validation Framework
    ar pierde trasabilitatea pentru un model servit din cache."""
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_cache(_FakeModel(), samples_used=100, training_run_id="cache-run-xyz")
    assert engine.last_training_run_id == "cache-run-xyz"


def test_seed_from_cache_sets_cache_metadata():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_cache(
        _FakeModel(), samples_used=500, training_run_id="cache-run-1",
        accuracy=0.52, log_loss=1.02, trained_at="2026-08-01T00:00:00Z",
    )
    assert engine.cache_accuracy == 0.52
    assert engine.cache_log_loss == 1.02
    assert engine.cache_trained_at == "2026-08-01T00:00:00Z"


def test_seed_from_cache_stores_explicit_temperature():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_cache(_FakeModel(), samples_used=500, training_run_id="cache-run-1", temperature=1.4)
    assert engine.temperature == 1.4
    assert engine.get_calibration_temperature() == 1.4


def test_seed_from_cache_does_not_touch_champion_metadata():
    """seed_from_cache() nu trebuie sa scrie champion_accuracy/champion_log_loss/
    champion_trained_at — ramanele None distinge corect un model din cache
    de unul dintr-un Champion real (status_summary() se bazeaza pe
    last_train_status, nu pe aceste campuri, dar rămân onest neatinse)."""
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_cache(_FakeModel(), samples_used=500, training_run_id="cache-run-1", accuracy=0.5)
    assert engine.champion_accuracy is None
    assert engine.champion_log_loss is None
    assert engine.champion_trained_at is None


# ── status_summary() — Defectul B, Architecture Gate 7B ─────────────────────

def test_status_summary_uses_champion_metadata_when_seeded_from_champion(monkeypatch):
    """Nu trebuie sa existe doua surse de adevar concurente: cand modelul
    servit vine dintr-un Champion, status_summary() NU trebuie sa citeasca
    deloc ml_model_status (ar putea fi complet diferit/stale)."""
    def _fail_if_called():
        raise AssertionError("sb.get_ml_status() nu trebuie apelat cand sursa e Champion")

    monkeypatch.setattr(ml_predictor.sb, "get_ml_status", _fail_if_called)

    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(
        _FakeModel(), samples_used=321, accuracy=0.61, log_loss=0.88, trained_at="2026-07-01T00:00:00Z",
    )

    summary = engine.status_summary()

    assert summary["accuracy"] == 0.61
    assert summary["log_loss"] == 0.88
    assert summary["last_trained_at"] == "2026-07-01T00:00:00Z"
    assert summary["samples_used"] == 321
    assert summary["model_version"] == 1


def test_status_summary_uses_cache_metadata_when_seeded_from_cache(monkeypatch):
    """Simetric cu test_status_summary_uses_champion_metadata_when_seeded_from_champion
    (fix "aplicatia porneste foarte greu") — un model din Local Model Cache
    nu a fost antrenat in acest proces, deci status_summary() nu trebuie sa
    citeasca deloc ml_model_status (ar putea reflecta o antrenare diferita)."""
    def _fail_if_called():
        raise AssertionError("sb.get_ml_status() nu trebuie apelat cand sursa e Local Model Cache")

    monkeypatch.setattr(ml_predictor.sb, "get_ml_status", _fail_if_called)

    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_cache(
        _FakeModel(), samples_used=321, training_run_id="cache-run-1",
        accuracy=0.61, log_loss=0.88, trained_at="2026-08-01T00:00:00Z",
    )

    summary = engine.status_summary()

    assert summary["accuracy"] == 0.61
    assert summary["log_loss"] == 0.88
    assert summary["last_trained_at"] == "2026-08-01T00:00:00Z"
    assert summary["samples_used"] == 321
    assert summary["model_version"] == 1


def test_status_summary_uses_remote_status_when_not_champion_sourced(monkeypatch):
    """Comportamentul existent (antrenare locala/neantrenat) ramane
    neschimbat -- citeste ml_model_status, exact ca azi."""
    monkeypatch.setattr(
        ml_predictor.sb, "get_ml_status",
        lambda: {"model_version": 3, "samples_used": 1000, "trained_at": "2026-06-01T00:00:00Z",
                  "accuracy": 0.49, "log_loss": 1.05},
    )

    engine = ml_predictor.MLPredictorEngine()  # neantrenat -- last_train_status == "not_trained"
    summary = engine.status_summary()

    assert summary["accuracy"] == 0.49
    assert summary["log_loss"] == 1.05
    assert summary["last_trained_at"] == "2026-06-01T00:00:00Z"


# ── Invarianța algoritmului (Architecture Gate 7B, punctul 3) ───────────────

def test_predict_byte_identical_regardless_of_provenance():
    """predict() trebuie sa produca exact aceleasi rezultate indiferent daca
    starea a fost populata prin train() (simulat direct pe atribute, ca
    train() insusi are nevoie de retea) sau prin seed_from_champion() --
    singura diferenta permisa e OBIECTUL model, niciodata codul de
    inferenta."""
    shared_model = _FakeModel()
    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}

    locally_trained = ml_predictor.MLPredictorEngine()
    locally_trained.model = shared_model
    locally_trained.feature_names = list(ml_predictor.FEATURE_COLUMNS)
    locally_trained.samples_used = 500
    locally_trained.model_version = 1
    locally_trained.is_trained = True
    locally_trained.last_train_status = "trained"

    champion_seeded = ml_predictor.MLPredictorEngine()
    champion_seeded.seed_from_champion(shared_model, samples_used=500, model_version=1)

    pred_local = locally_trained.predict(features)
    pred_champion = champion_seeded.predict(features)

    assert pred_local.prob_home == pred_champion.prob_home
    assert pred_local.prob_draw == pred_champion.prob_draw
    assert pred_local.prob_away == pred_champion.prob_away
    assert pred_local.confidence == pred_champion.confidence


# ── Calibrare (Temperature Scaling, ADR-049, Pasul 10a) ──────────────────

def test_predict_without_temperature_is_byte_identical_to_pre_calibration_path():
    """Regresie explicită, cerută în PASUL10A_IMPLEMENTATION_PLAN.md §5:
    fără calibrare (self.temperature is None), predict() trebuie să
    producă exact aceleași probabilități ca predict_proba() nativă —
    nicio schimbare de comportament pentru cazul necalibrat."""
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=500)  # temperature=None implicit
    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}

    pred = engine.predict(features)

    assert (pred.prob_home, pred.prob_draw, pred.prob_away) == (0.4, 0.3, 0.3)


def test_predict_with_temperature_uses_calibrated_path():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(_FakeModel(), samples_used=500, temperature=2.0)
    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}

    pred = engine.predict(features)

    # Cu T=2.0 aplicat pe marginile [1.0, 0.5, 0.2] din _FakeModel, rezultatul
    # NU mai e [0.4, 0.3, 0.3] (calea predict_proba nativă) — trebuie sa
    # difere, dovedind ca a fost folosita calea calibrata, nu cea veche.
    assert (pred.prob_home, pred.prob_draw, pred.prob_away) != (0.4, 0.3, 0.3)
    assert abs(pred.prob_home + pred.prob_draw + pred.prob_away - 1.0) < 1e-6


def test_predict_with_temperature_preserves_argmax():
    """Proprietatea centrală care a motivat alegerea Temperature Scaling
    (ADR-049 §2.4/§3): argmax-ul probabilităților nu se schimbă niciodată,
    indiferent de T — verificat direct pe marginile din _FakeModel
    ([1.0, 0.5, 0.2], home e deja dominant), pentru mai multe valori de T."""
    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}

    baseline = ml_predictor.MLPredictorEngine()
    baseline.seed_from_champion(_FakeModel(), samples_used=500)  # necalibrat
    baseline_pred = baseline.predict(features)
    baseline_argmax = max(
        ("prob_home", baseline_pred.prob_home),
        ("prob_draw", baseline_pred.prob_draw),
        ("prob_away", baseline_pred.prob_away),
        key=lambda kv: kv[1],
    )[0]

    for T in (0.5, 1.0, 2.0, 5.0):
        engine = ml_predictor.MLPredictorEngine()
        engine.seed_from_champion(_FakeModel(), samples_used=500, temperature=T)
        pred = engine.predict(features)
        argmax = max(
            ("prob_home", pred.prob_home),
            ("prob_draw", pred.prob_draw),
            ("prob_away", pred.prob_away),
            key=lambda kv: kv[1],
        )[0]
        assert argmax == baseline_argmax, f"argmax schimbat la T={T}"


class _ConsistentFakeModel:
    """Spre deosebire de _FakeModel (unde predict_proba() și predict(...,
    output_margin=True) întorc valori independente, arbitrare — suficient
    pentru testele de mai sus, care doar verifică ce cale de cod rulează),
    acest model garantează predict_proba() == softmax(margini) exact, ca
    să poată verifica egalitate NUMERICĂ reală, nu doar "calea corectă"."""

    _margins = np.array([[2.0, 1.0, 0.5]])

    def predict_proba(self, X):
        shifted = self._margins - self._margins.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probs = exp / exp.sum(axis=1, keepdims=True)
        return probs.tolist()

    def predict(self, X, output_margin=False):
        if output_margin:
            return self._margins
        return [0]


def test_predict_with_temperature_equal_to_one_is_identical_to_predict_proba():
    """[ADAUGAT — review Pasul 10a, observația 5, opțională] T=1.0 trebuie
    să producă exact același rezultat ca predict_proba() nativă — verificat
    la nivelul MLPredictorEngine.predict(), nu doar la nivelul funcției pure
    _softmax_with_temperature() (deja acoperit de
    test_softmax_with_temperature_t_equals_one_matches_plain_softmax).
    T=1.0 e o valoare persistată explicit (nu None), deci calea de cod
    parcursă e cea CALIBRATĂ (_softmax_with_temperature), nu fallback-ul
    necalibrat — testul dovedește că cele două căi coincid numeric la T=1."""
    model = _ConsistentFakeModel()
    features = {c: 1.0 for c in ml_predictor.FEATURE_COLUMNS}

    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(model, samples_used=500, temperature=1.0)
    pred = engine.predict(features)

    expected = model.predict_proba(None)[0]

    # predict() rotunjește la 4 zecimale (comportament existent, neschimbat
    # de calibrare) — toleranța reflectă exact acea rotunjire, nu o
    # aproximare numerică a calibrării în sine.
    assert pred.prob_home == pytest.approx(expected[0], abs=5e-5)
    assert pred.prob_draw == pytest.approx(expected[1], abs=5e-5)
    assert pred.prob_away == pytest.approx(expected[2], abs=5e-5)
