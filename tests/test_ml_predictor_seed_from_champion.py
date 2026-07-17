"""
Teste pentru MLPredictorEngine.seed_from_champion()/status_summary() —
Pasul 6 ("Golul A") + Pasul 7B ("Defectul B", Architecture Gate 7B): nicio
dublă reprezentare a aceluiași obiect — is_trained/model_version/
samples_used/feature_names/accuracy/log_loss/trained_at trebuie să fie
coerente indiferent dacă modelul provine din train() local sau dintr-un
Champion încărcat, iar status_summary() trebuie să reflecte EXCLUSIV
modelul care servește efectiv — niciodată o sursă concurentă.
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


def test_seed_from_champion_sets_champion_metadata():
    engine = ml_predictor.MLPredictorEngine()
    engine.seed_from_champion(
        _FakeModel(), samples_used=500, accuracy=0.52, log_loss=1.02, trained_at="2026-07-14T00:00:00Z",
    )
    assert engine.champion_accuracy == 0.52
    assert engine.champion_log_loss == 1.02
    assert engine.champion_trained_at == "2026-07-14T00:00:00Z"


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
