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

# [ADAUGAT — ADR-015] Identitate fixă pentru istoricul de antrenare — trebuie
# să coincidă exact cu learning_core.algorithms.xgboost_v1.XGBoostV1Algorithm
# (name/version/league_scope), fiindcă reprezintă același algoritm; train()
# e apelat direct de fluxul de producție (run_daily.py, oracle_engine.py),
# nu doar prin adaptorul Learning Core — de aceea înregistrarea se face aici,
# nu doar în XGBoostV1Algorithm.fit().
_ALGORITHM_FAMILY  = "xgboost_v1"
_ALGORITHM_VERSION = "1"
_LEAGUE_SCOPE       = "all"


def _record_training_run(status: str, samples_used: int, walk_forward_metrics: dict,
                          message: str) -> None:
    """Înregistrează rularea în training_runs (local + Supabase best-effort)
    și compară cu campionul activ, dacă există — pur informativ, loghează
    rezultatul. Nu decide, nu promovează, nu întrerupe niciodată train():
    orice eșec aici e prins și logat, fără să afecteze MLTrainingResult
    returnat apelantului."""
    try:
        import uuid
        from learning_core import champion_comparison, storage
        from learning_core.model_registry import TrainingRunResult

        run_id = str(uuid.uuid4())
        storage.save_training_run(
            TrainingRunResult(
                training_run_id=run_id, status=status, samples_used=samples_used,
                walk_forward_metrics=walk_forward_metrics, message=message,
            ),
            algorithm_name=_ALGORITHM_FAMILY,
            algorithm_version=_ALGORITHM_VERSION,
            league_scope=_LEAGUE_SCOPE,
        )
        if walk_forward_metrics:
            comparison = champion_comparison.compare_to_champion(
                algorithm_family=_ALGORITHM_FAMILY,
                algorithm_version=_ALGORITHM_VERSION,
                league_scope=_LEAGUE_SCOPE,
                new_training_run_id=run_id,
                new_metrics=walk_forward_metrics,
            )
            logger.info("[ML] training_run %s înregistrat. %s", run_id, comparison.message)
        else:
            logger.info("[ML] training_run %s înregistrat (status=%s, fără metrici de comparat).",
                         run_id, status)
    except Exception as exc:
        logger.warning("[ML] Înregistrare training_run eșuată (nu afectează antrenarea): %s", exc)

FEATURE_COLUMNS = [
    # [ELIMINAT — audit de feature importance, permutation importance
    # măsurată pe 53.409 meciuri reale: "home_xg_pred", "away_xg_pred",
    # "weather_penalty", "mc_prob_home", "mc_prob_draw", "mc_prob_away" —
    # toate 100% goale în match_history (niciodată populate istoric),
    # importanță confirmată exact 0.0000, ablația confirmă rezultat
    # identic cu/fără ele. Rămân calculate și folosite în fluxul live
    # (_build_ml_features/_cache_prediction) pentru alte scopuri — doar
    # eliminate ca input al modelului ML, unde nu contribuiau cu nimic.]
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
    # [ADAUGAT — ADR-012] Promovate prin test de ablație walk-forward pe
    # 5.253 meciuri reale (docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_
    # 2026-07-13.md): acuratețe/log-loss/Brier îmbunătățite simultan.
    # Calculate în _fetch_training_dataframe() din cele 4 coloane brute
    # (home/away_corner_avg_recent, home/away_card_avg_recent) — nu
    # stocate redundant ca atare în match_history.
    "corner_dominance", "card_diff",
    # [ADAUGAT — ADR-013] Promovat prin test de ablație walk-forward pe
    # 5.253 meciuri reale (docs/03_ENGINE/FOULS_DOMINANCE_ABLATION_
    # 2026-07-14.md): acuratețe/log-loss/Brier îmbunătățite simultan
    # (magnitudine mică, raportată onest). Calculat din cele 2 coloane
    # brute (home/away_foul_avg_recent) — nu stocat redundant. `ht_goal_
    # diff` a fost testat separat și RESPINS (docs/03_ENGINE/HT_SCORE_
    # ABLATION_2026-07-14.md) — accuracy câștigă, log-loss/Brier regresează.
    "foul_diff",
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

    # [ADAUGAT — Pasul 6, Implementation Contract Learning Core] Populează
    # starea internă dintr-un model deja antrenat, încărcat dintr-un
    # Champion (learning_core.champion_loader) — fără să treacă prin
    # train() local. Garantează aceeași reprezentare internă
    # (is_trained/model_version/samples_used/feature_names) indiferent de
    # proveniența modelului — nicio dublă reprezentare a aceluiași obiect
    # (Chief Architect Review, Architecture Gate 6, "Golul A").
    #
    # Nu modifică NIMIC din train()/predict() — metodă complet aditivă.
    def seed_from_champion(self, model, samples_used: int, model_version: int = 1) -> None:
        self.model = model
        self.model_version = model_version
        self.samples_used = samples_used
        self.feature_names = list(FEATURE_COLUMNS)
        self.is_trained = True
        self.last_train_status = "trained_from_champion"

    # ── Pregătire date ──────────────────────────────────────────────────
    def _fetch_training_dataframe(self) -> pd.DataFrame | None:
        rows = sb.get_training_data(only_with_results=True)
        if not rows:
            return None
        df = pd.DataFrame(rows)
        # [ADAUGAT — ADR-012] corner_dominance/card_diff se calculează din
        # cele 4 coloane brute, nu se citesc direct — dacă lipsesc brutele
        # (meci fără istoric de cornere/cartonașe), rezultă NaN, gestionat
        # nativ de XGBoost (missing-value split), niciodată aproximat.
        if "home_corner_avg_recent" in df.columns and "away_corner_avg_recent" in df.columns:
            df["corner_dominance"] = df["home_corner_avg_recent"] - df["away_corner_avg_recent"]
        else:
            df["corner_dominance"] = np.nan
        if "home_card_avg_recent" in df.columns and "away_card_avg_recent" in df.columns:
            df["card_diff"] = df["away_card_avg_recent"] - df["home_card_avg_recent"]
        else:
            df["card_diff"] = np.nan
        # [ADAUGAT — ADR-013] foul_diff, aceeași disciplină ca mai sus.
        if "home_foul_avg_recent" in df.columns and "away_foul_avg_recent" in df.columns:
            df["foul_diff"] = df["away_foul_avg_recent"] - df["home_foul_avg_recent"]
        else:
            df["foul_diff"] = np.nan
        missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
        for c in missing:
            df[c] = np.nan
        df = df.dropna(subset=["actual_result"])
        df = df[df["actual_result"].isin(["H", "D", "A"])]
        return df if not df.empty else None

    # ── Walk-forward validation (expanding window) ──────────────────────────
    # [ADAUGAT] Inlocuieste train_test_split() aleator, care permitea
    # scurgere temporala (meciuri viitoare in antrenare, meciuri vechi in
    # test) - fotbalul e o serie temporala, nu un dataset static.
    # Expanding window: fold k antreneaza pe tot ce e INAINTE de segmentul k,
    # valideaza DOAR pe segmentul k (niciodata pe date "din viitor" fata de
    # antrenare) - simuleaza exact conditiile reale de productie.
    @staticmethod
    def _multiclass_brier(y_true: np.ndarray, probs: np.ndarray, n_classes: int = 3) -> float:
        """Brier score multi-clasa (Brier 1950): media patratelor diferentelor
        intre probabilitatea prezisa si eticheta one-hot reala, peste toate
        clasele si toate esantioanele. 0 = perfect, 2 = cel mai rau posibil."""
        one_hot = np.eye(n_classes)[y_true]
        return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))

    @classmethod
    def _walk_forward_validate(cls, X: pd.DataFrame, y: pd.Series, n_folds: int = 5) -> dict:
        """
        X, y trebuie sa fie deja ordonate cronologic (index resetat, 0..n-1).
        Imparte in n_folds+1 segmente egale; fold k = antrenare pe segmentele
        [0..k), validare pe segmentul k. Returneaza metrici per-fold si medii.
        """
        from xgboost import XGBClassifier
        from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

        n = len(X)
        # n_folds foldurilor de validare necesita n_folds+1 segmente in total
        # (primul segment e mereu folosit doar la antrenare, niciodata validat) -
        # deci n_folds+2 puncte de granita, nu n_folds+1.
        boundaries = np.linspace(0, n, n_folds + 2, dtype=int)
        fold_metrics = []

        for k in range(1, n_folds + 1):
            val_start, val_end = boundaries[k], boundaries[k + 1]
            X_tr, y_tr = X.iloc[:val_start], y.iloc[:val_start]
            X_val, y_val = X.iloc[val_start:val_end], y.iloc[val_start:val_end]

            if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
                continue  # segment prea mic pt un fold semnificativ - sarit, nu esuat

            fold_model = XGBClassifier(
                n_estimators=150, max_depth=4, learning_rate=0.08,
                subsample=0.85, colsample_bytree=0.85,
                objective="multi:softprob", num_class=3,
                eval_metric="mlogloss", random_state=42,
            )
            fold_model.fit(X_tr, y_tr)
            preds = fold_model.predict(X_val)
            probs = fold_model.predict_proba(X_val)

            acc = float(accuracy_score(y_val, preds))
            try:
                ll = float(sk_log_loss(y_val, probs, labels=[0, 1, 2]))
            except Exception:
                ll = None
            brier = cls._multiclass_brier(y_val.to_numpy(), probs)

            fold_metrics.append({
                "fold": k, "train_size": len(X_tr), "val_size": len(X_val),
                "accuracy": round(acc, 4), "log_loss": round(ll, 4) if ll is not None else None,
                "brier_score": round(brier, 4),
            })

        if not fold_metrics:
            return {"folds": [], "avg_accuracy": None, "avg_log_loss": None, "avg_brier_score": None}

        avg_acc = float(np.mean([f["accuracy"] for f in fold_metrics]))
        valid_ll = [f["log_loss"] for f in fold_metrics if f["log_loss"] is not None]
        avg_ll = float(np.mean(valid_ll)) if valid_ll else None
        avg_brier = float(np.mean([f["brier_score"] for f in fold_metrics]))

        return {
            "folds": fold_metrics,
            "avg_accuracy": round(avg_acc, 4),
            "avg_log_loss": round(avg_ll, 4) if avg_ll is not None else None,
            "avg_brier_score": round(avg_brier, 4),
        }

    # ── Antrenare ─────────────────────────────────────────────────────────
    def train(self) -> MLTrainingResult:
        if not sb.is_available():
            self.last_train_status = "unavailable"
            _record_training_run("unavailable", 0, {},
                                  "Supabase indisponibil — verifică SUPABASE_URL / SUPABASE_SECRET_KEY în secrets.")
            return MLTrainingResult(
                status="unavailable",
                message="Supabase indisponibil — verifică SUPABASE_URL / SUPABASE_SECRET_KEY în secrets.",
            )

        df = self._fetch_training_dataframe()
        if df is None or len(df) < MIN_SAMPLES_TO_TRAIN:
            n = 0 if df is None else len(df)
            self.last_train_status = "insufficient_data"
            msg = f"Doar {n} meciuri cu rezultat cunoscut — minim {MIN_SAMPLES_TO_TRAIN} necesare pentru antrenare ML."
            _record_training_run("insufficient_data", n, {}, msg)
            return MLTrainingResult(status="insufficient_data", samples_used=n, message=msg)

        try:
            from xgboost import XGBClassifier
            from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

            # [ADAUGAT] Ordonare cronologică STRICTĂ înainte de orice split —
            # esențială pentru walk-forward; get_training_data() ordonează
            # după fixture_id, nu după dată.
            if "kickoff_date" in df.columns:
                df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)
            else:
                logger.warning("[ML] kickoff_date absent din date — walk-forward validation "
                                "degradează la ordinea brută din DB (posibil nesigur temporal).")

            X = df[FEATURE_COLUMNS].astype(float).fillna(df[FEATURE_COLUMNS].astype(float).median())
            y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)

            # Validare onestă, temporală (nu mai afectează modelul final)
            wf = self._walk_forward_validate(X, y, n_folds=5)
            acc, ll = wf["avg_accuracy"], wf["avg_log_loss"]
            brier = wf["avg_brier_score"]

            # Modelul de PRODUCȚIE se antrenează pe TOT istoricul disponibil —
            # walk-forward de mai sus a fost strict pt evaluare onestă,
            # nu pt selecția datelor de antrenare finale.
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
            model.fit(X, y)

            self.model = model
            self.feature_names = list(FEATURE_COLUMNS)
            self.samples_used = len(df)
            self.model_version += 1
            self.is_trained = True
            self.last_train_status = "trained"

            fold_summary = "; ".join(
                f"fold{f['fold']}: acc={f['accuracy']} brier={f['brier_score']}"
                for f in wf["folds"]
            )
            notes = (
                f"Walk-forward validation ({len(wf['folds'])} folds, expanding window). "
                f"Model final antrenat pe tot istoricul ({len(df)} meciuri). "
                f"Brier mediu={brier}. {fold_summary}"
            )

            from datetime import datetime, timezone
            sb.save_ml_status(
                trained_at=datetime.now(timezone.utc).isoformat(),
                samples_used=self.samples_used,
                accuracy=acc, log_loss=ll,
                feature_names=self.feature_names,
                model_version=self.model_version,
                notes=notes,
            )

            logger.info(
                "[ML] Trained v%d on %d samples (production, full history). "
                "Walk-forward eval: acc=%s log_loss=%s brier=%s (%d folds)",
                self.model_version, self.samples_used, acc, ll, brier, len(wf["folds"]),
            )

            train_message = (
                f"Model antrenat pe {self.samples_used} meciuri. "
                f"Validare walk-forward: {len(wf['folds'])} folds, Brier mediu={brier}."
            )
            _record_training_run(
                "trained", self.samples_used,
                {"accuracy": acc, "log_loss": ll, "brier_score": brier},
                train_message,
            )
            return MLTrainingResult(
                status="trained", samples_used=self.samples_used,
                accuracy=acc, log_loss=ll,
                message=train_message,
            )

        except Exception as exc:
            logger.error("[ML] Training failed: %s", exc)
            self.last_train_status = "error"
            _record_training_run("error", 0, {}, str(exc))
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
