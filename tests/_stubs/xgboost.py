"""
Stub minimal pt XGBClassifier — NU face parte din dependințele reale ale
proiectului. Folosit DOAR în teste, pentru a valida logica de fold-splitting
din MLPredictorEngine._walk_forward_validate (expanding window, absența
scurgerii de date) fără a necesita xgboost real instalat (indisponibil în
acest sandbox, fără acces la rețea).

Comportament: clasificator determinist trivial (întoarce mereu clasa
majoritară din antrenare, cu o distribuție de probabilitate fixă) — suficient
pentru a testa CORECTITUDINEA STRUCTURALĂ a walk-forward-ului (număr de
folduri, mărimea ferestrei expandabile, fără scurgere temporală), nu
acuratețea reală a unui model ML.
"""
import numpy as np


class XGBClassifier:
    def __init__(self, **kwargs):
        self._majority_class = 0
        self.n_classes = kwargs.get("num_class", 3)

    def fit(self, X, y):
        vals, counts = np.unique(np.asarray(y), return_counts=True)
        self._majority_class = int(vals[np.argmax(counts)])
        return self

    def predict(self, X, output_margin=False):
        if output_margin:
            # Pseudo-margini: log(predict_proba()) — softmax(log(p)/1) == p
            # exact la T=1, suficient pentru testarea structurală a căii de
            # calibrare (ADR-049, Pasul 10a), fără pretenție de fidelitate
            # reală XGBoost (stub-ul nu antrenează un model real, vezi
            # header-ul fișierului).
            probs = self.predict_proba(X)
            return np.log(np.clip(probs, 1e-9, None))
        return np.full(len(X), self._majority_class)

    def predict_proba(self, X):
        probs = np.full((len(X), self.n_classes), 0.1)
        probs[:, self._majority_class] = 1.0 - 0.1 * (self.n_classes - 1)
        return probs
