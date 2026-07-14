"""
Teste pentru MLPredictorEngine.seed_from_champion() — Pasul 6, "Golul A"
(Chief Architect Review, Architecture Gate 6): nicio dublă reprezentare a
aceluiași obiect — is_trained/model_version/samples_used/feature_names
trebuie să fie coerente indiferent dacă modelul provine din train() local
sau dintr-un Champion încărcat.
"""
import ml_predictor


class _FakeModel:
    def predict_proba(self, X):
        return [[0.4, 0.3, 0.3]]


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
