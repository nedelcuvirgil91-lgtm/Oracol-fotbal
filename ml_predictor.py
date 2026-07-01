"""
================================================================================
FOOTBALL ORACLE — ML Predictor (XGBoost) v1.0
================================================================================
Module: ml_predictor.py

Strat de machine learning care învață tipare din meciuri istorice (feature-uri
calculate de motorul Poisson + rezultatul real introdus manual de utilizator)
și produce o predicție 1X2 complementară, combinată (blend) cu Poisson/Monte
Carlo în oracle_engine.py.

Datele de antrenare vin din Supabase (tabela match_history), populate automat
de oracle_engine.update_weights_from_result() de fiecare dată când utilizatorul
introduce scorul real al unui meci analizat anterior.

Modelul NU se antrenează automat la fiecare predicție (ar fi ineficient).
Se antrenează manual din tab-ul Setări → ML, sau quando samples_used crește
semnificativ. Modelul antrenat e ținut în memorie (cache_resource Streamlit)
pentru sesiunea curentă; la fiecare restart de aplicație se reantrenează rapid
din datele din Supabase (antrenarea XGBoost pe câteva sute de rânduri durează
sub o secundă, deci nu necesită serializare/persistare a modelului în sine).
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

import supabase_client as sb

logger = logging.getLogger("FootballOracle.ML")

MIN_SAMPLES_TO_TRAIN = 30  # sub acest prag, ML nu se activează — doar Poisson

FEATURE_COLUMNS = [
    "home_xg_pred", "away_xg_pred",
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
    "weather_penalty",
    "mc_prob_home", "mc_prob_draw", "mc_prob_away",
]

RESULT_TO_LABEL = {"H": 0, "D": 1, "A": 2}
LABEL_TO_RESULT = {0: "H", 1: "D", 2: "A"}


@dataclass
class MLTrainingResult:
    status: str               # "trained" | "insufficient_data" | "error" | "unavailable"
    samples_used: int = 0
    accuracy: float | None = None
    log_loss: float | None = None
    message: str = ""


@dataclass
class MLPrediction:
    prob_home: float
    prob_draw: float
    prob_away: float
    confidence: float          # 0-1, cât de sigur e modelul pe predicția dominantă
    model_version: int
    samples_used: int


class MLPredictorEngine:
    """Wrapper peste un model XGBoost antrenat pe date istorice din Supabase."""

    def __init__(self) -> None:
        self.model = None
        self.feature_names: list[str] = list(FEATURE_COLUMNS)
        self.model_version: int = 0
        self.samples_used: int = 0
        self.is_trained: bool = False
        self.last_train_status: str = "not_trained"

    # ── Pregătire date ──────────────────────────────────────────────────
    def _fetch_training_dataframe(self) -> pd.DataFrame | None:
        rows = sb.get_training_data(only_with_results=True)
        if not rows:
            return None
        df = pd.DataFrame(rows)
        missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
        for c in missing:
            df[c] = np.nan
        df = df.dropna(subset=["actual_result"])
        df = df[df["actual_result"].isin(["H", "D", "A"])]
        return df if not df.empty else None

    # ── Antrenare ─────────────────────────────────────────────────────────
    def train(self) -> MLTrainingResult:
        if not sb.is_available():
            self.last_train_status = "unavailable"
            return MLTrainingResult(
                status="unavailable",
                message="Supabase indisponibil — verifică SUPABASE_URL / SUPABASE_SECRET_KEY în secrets.",
            )

        df = self._fetch_training_dataframe()
        if df is None or len(df) < MIN_SAMPLES_TO_TRAIN:
            n = 0 if df is None else len(df)
            self.last_train_status = "insufficient_data"
            return MLTrainingResult(
                status="insufficient_data", samples_used=n,
                message=f"Doar {n} meciuri cu rezultat cunoscut — minim {MIN_SAMPLES_TO_TRAIN} necesare pentru antrenare ML.",
            )

        try:
            from xgboost import XGBClassifier
            from sklearn.model_selection import train_test_split
            from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

            X = df[FEATURE_COLUMNS].astype(float).fillna(df[FEATURE_COLUMNS].astype(float).median())
            y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)

            test_size = 0.2 if len(df) >= 50 else 0.1
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42, stratify=y if y.nunique() > 1 else None,
            )

            model = XGBClassifier(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                objective="multi:softprob",
                num_class=3,
                eval_metric="mlogloss",
                random_state=42,
            )
            model.fit(X_train, y_train)

            acc = None
            ll = None
            if len(X_test) > 0:
                preds = model.predict(X_test)
                probs = model.predict_proba(X_test)
                acc = round(float(accuracy_score(y_test, preds)), 4)
                try:
                    ll = round(float(sk_log_loss(y_test, probs, labels=[0, 1, 2])), 4)
                except Exception:
                    ll = None

            self.model = model
            self.feature_names = list(FEATURE_COLUMNS)
            self.samples_used = len(df)
            self.model_version += 1
            self.is_trained = True
            self.last_train_status = "trained"

            from datetime import datetime, timezone
            sb.save_ml_status(
                trained_at=datetime.now(timezone.utc).isoformat(),
                samples_used=self.samples_used,
                accuracy=acc, log_loss=ll,
                feature_names=self.feature_names,
                model_version=self.model_version,
                notes=f"Train/test split: {len(X_train)}/{len(X_test)}",
            )

            logger.info("[ML] Trained v%d on %d samples. acc=%s log_loss=%s",
                        self.model_version, self.samples_used, acc, ll)

            return MLTrainingResult(
                status="trained", samples_used=self.samples_used,
                accuracy=acc, log_loss=ll,
                message=f"Model antrenat pe {self.samples_used} meciuri.",
            )

        except Exception as exc:
            logger.error("[ML] Training failed: %s", exc)
            self.last_train_status = "error"
            return MLTrainingResult(status="error", message=str(exc))

    # ── Predicție ─────────────────────────────────────────────────────────
    def predict(self, features: dict) -> MLPrediction | None:
        """
        features: dict cu cheile din FEATURE_COLUMNS (vine din oracle_engine,
        calculat în timpul evaluate_match() — vezi _build_ml_features()).
        """
        if not self.is_trained or self.model is None:
            return None
        try:
            row = pd.DataFrame([{c: features.get(c, np.nan) for c in self.feature_names}])
            row = row.astype(float)
            row = row.fillna(row.median(numeric_only=True)).fillna(0.0)
            probs = self.model.predict_proba(row)[0]
            ph, pd_, pa = float(probs[0]), float(probs[1]), float(probs[2])
            confidence = float(max(ph, pd_, pa))
            return MLPrediction(
                prob_home=round(ph, 4), prob_draw=round(pd_, 4), prob_away=round(pa, 4),
                confidence=round(confidence, 4),
                model_version=self.model_version, samples_used=self.samples_used,
            )
        except Exception as exc:
            logger.warning("[ML] predict() failed: %s", exc)
            return None

    # ── Status pentru UI ─────────────────────────────────────────────────
    def status_summary(self) -> dict:
        remote = sb.get_ml_status()
        return {
            "is_trained_this_session": self.is_trained,
            "model_version": self.model_version or remote.get("model_version", 0),
            "samples_used": self.samples_used or remote.get("samples_used", 0),
            "last_trained_at": remote.get("trained_at"),
            "accuracy": remote.get("accuracy"),
            "log_loss": remote.get("log_loss"),
            "min_samples_required": MIN_SAMPLES_TO_TRAIN,
        }


def blend_predictions(
    poisson_probs: tuple[float, float, float],
    ml_pred: MLPrediction | None,
    ml_weight: float = 0.35,
) -> tuple[float, float, float, str]:
    """
    Combină probabilitățile Poisson/Monte Carlo cu predicția ML.
    ml_weight = cât de mult contează ML în blend (restul e Poisson).
    Dacă ML nu e disponibil (insuficiente date), returnează Poisson neschimbat.
    """
    ph_p, pd_p, pa_p = poisson_probs
    if ml_pred is None:
        return ph_p, pd_p, pa_p, "poisson-only"

    # Scalează ml_weight în funcție de încrederea modelului ML (mai puține
    # date / confidence scăzută → ponderăm mai puțin ML în blend)
    sample_factor = min(ml_pred.samples_used / 150.0, 1.0)
    effective_w = ml_weight * sample_factor

    ph = ph_p * (1 - effective_w) + ml_pred.prob_home * effective_w
    pd_ = pd_p * (1 - effective_w) + ml_pred.prob_draw * effective_w
    pa = pa_p * (1 - effective_w) + ml_pred.prob_away * effective_w

    total = ph + pd_ + pa
    if total > 0:
        ph, pd_, pa = ph / total, pd_ / total, pa / total

    label = f"blend (ML weight={effective_w:.0%}, v{ml_pred.model_version}, n={ml_pred.samples_used})"
    return round(ph, 4), round(pd_, 4), round(pa, 4), label
