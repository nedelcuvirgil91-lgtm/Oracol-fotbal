# Pasul 10a — Implementation Plan (Calibrare post-hoc — antrenare, persistare, flux Challenger)

**Tip**: plan tehnic de execuție. NU e ADR — autoritatea de design rămâne `ADR-049` (ACCEPTED). Acest document decide exclusiv **cum**, în limitele deja fixate de ADR-049 — nu redeschide nicio decizie arhitecturală.

**Scop restrâns, confirmat explicit**: antrenare (temperatura), persistare (artefact separat), integrare în fluxul Challenger (creare + shadow logging). **Exclude deliberat** `champion_loader.py` și `oracle_engine.py` (servire live Champion) — acelea rămân Pasul 10b, plan separat, după închiderea acestuia. `promotion_service.py` rămâne de asemenea neatins (motivat în §2, rândul respectiv).

---

## 1. Mecanismul ales (detalii de implementare, în limitele ADR-049)

- **Sursa de date de calibrare** (ADR-049 §5): predicțiile out-of-fold deja generate de `_walk_forward_validate()` — extinsă să captureze și marginile brute (`output_margin=True`), nu doar `predict_proba()`.
- **Algoritmul de fitting**: optimizare scalară 1D (`scipy.optimize.minimize_scalar`, mărginită la un interval pozitiv rezonabil, ex. `[0.05, 10.0]`) care minimizează log-loss-ul lui `softmax(margini/T)` față de etichetele reale OOF.
- **Persistare** (ADR-049 §7C): modul nou, `learning_core/calibration_artifact_storage.py`, complet separat de `model_artifact_storage.py` (neatins) — aceeași filosofie (best-effort, degradare grațioasă, niciodată excepție către apelant), cheie derivată din `training_run_id` (`<training_run_id>.calibration.json`), conținut minimal (`{"temperature": T}`).
- **Aplicare** (ADR-049 §4): în `MLPredictorEngine.predict()` — dacă temperatura există, se folosește `model.predict(X, output_margin=True)` + softmax scalat; altfel, exact calea de azi (`predict_proba()`), byte-identică, fără regresie pentru cazul necalibrat.
- **Stabilitate numerică a softmax-ului calibrat** (cerut explicit la review): `_softmax_with_temperature()` trebuie implementată în forma numeric stabilă — logit shifting, `softmax((z - max(z))/T) = softmax(z/T)` matematic identic, dar fără risc de overflow la exponențiere. `T` trebuie validat strict pozitiv (`T > 0`) înainte de orice utilizare — atât la fitting (§4, `_fit_temperature()`, intervalul de optimizare `[0.05, 10.0]` deja exclude `T ≤ 0` prin construcție), cât și la aplicare (`predict()`/`challenger_shadow.py`), unde o valoare încărcată dintr-un artefact de calibrare corupt/manipulat manual ar putea, teoretic, fi ≤0 — tratat ca eșec de încărcare (`None`), nu ca valoare folosită direct.

## 2. Modificări concrete pe fișiere

| # | Fișier | Modificare |
|---|---|---|
| 1 | `learning_core/calibration_artifact_storage.py` (**nou**) | `save_calibration_artifact(temperature, training_run_id) -> str \| None`, `load_calibration_artifact(training_run_id) -> float \| None` — best-effort, simetric cu `model_artifact_storage.py`, dar fișier complet separat |
| 2 | `ml_predictor.py` | (a) `_walk_forward_validate()` — capturează suplimentar marginile brute per fold, concatenate în `oof_margins`/`oof_labels` (chei noi, aditive — cheile existente `folds`/`avg_accuracy`/`avg_log_loss`/`avg_brier_score` neschimbate); (b) `_fit_temperature(margins, labels) -> float \| None` (nou, static/privat); (c) `_softmax_with_temperature(margins, T) -> np.ndarray` (nou, funcție pură, reutilizabilă și de `challenger_shadow.py`); (d) `train()` — apelează `_fit_temperature()` pe setul OOF, stochează `self.temperature`; (e) `predict()` — folosește calea calibrată dacă `self.temperature is not None`, altfel calea actuală neschimbată; (f) `get_calibration_temperature(self) -> float \| None` (accesor nou); (g) `seed_from_champion(..., temperature: float \| None = None)` — parametru nou, opțional, aditiv (pregătit pentru Pasul 10b, neapelat cu valoare reală până atunci) |
| 3 | `learning_core/model_registry.py` | Adaugă `get_calibration_temperature()` la `Protocol LearningAlgorithm` |
| 4 | `learning_core/algorithms/xgboost_v1.py` | `def get_calibration_temperature(self): return self._engine.temperature` |
| 5 | `learning_core/algorithms/production_champion.py` | `def get_calibration_temperature(self): return None` |
| 6 | `learning_core/algorithms/league_weights_adaptive.py` | `def get_calibration_temperature(self): return None` |
| 7 | `learning_core/continuous_learning.py` | `_phase_b_train_new()` — al doilea pas gating, imediat după persistarea artefactului de model (Pasul 9), înainte de `create_challenger()` — vezi §2.1 |
| 8 | `learning_core/challenger_shadow.py` | `predict_with_challenger()` — încarcă și aplică calibrarea dacă există; degradare grațioasă (nu gating) dacă lipsește — vezi §2.2 |

**Neatinse, confirmat**: `model_artifact_storage.py`, `training_runner.py`, `challenger_manager.py`, `promotion_service.py`, `champion_loader.py`, `oracle_engine.py`.

**De ce `promotion_service.py` rămâne neatins** (decizie explicită, nu omisiune): `_validate_artifact()` re-validează azi funcțional DOAR modelul. Odată ce gate-ul de la §2.1 există, un Challenger nu poate ajunge să existe fără calibrare validă — INV-1 extins (ADR-049 §9) garantează asta la creare, nu doar la promovare. Nu există un risc nou, specific promovării, pe care re-validarea actuală să nu-l acopere deja indirect — o validare suplimentară a calibratorului la promovare ar fi verificare defensivă pentru un scenariu deja imposibil prin construcție, nu o precondiție reală nouă.

### 2.1 Diff conceptual — `_phase_b_train_new()` (după blocul de persistare a modelului, Pasul 9, neschimbat)

```python
    ar.complete_run(persist_run_id, summary={"result": "SUCCESS", "artifact_path": artifact_path})
    # --- sfârșit bloc Pasul 9 ---

    # --- NOU: persistare calibrator, extensie INV-1 (ADR-049 §9) ---
    persist_calib_run_id = ar.write_run(PRODUCER, "calibration_persistence", "T2", target_key=target_key)
    if persist_calib_run_id is None:
        return
    ar.start_run(persist_calib_run_id)

    temperature = algorithm.get_calibration_temperature()
    if temperature is None:
        ar.fail_run(persist_calib_run_id, "CALIBRATION_NOT_AVAILABLE: algoritmul nu a produs o calibrare validă")
        return  # extensie D3 — Challenger NU se creează

    try:
        calibration_path = calibration_artifact_storage.save_calibration_artifact(
            temperature, report.result.training_run_id,
        )
    except Exception as exc:
        calibration_path = None
        logger.error("[ContinuousLearning] save_calibration_artifact a ridicat excepție neașteptată: %s", exc)

    if calibration_path is None:
        ar.fail_run(persist_calib_run_id, "CALIBRATION_STORAGE_FAILURE: save_calibration_artifact a eșuat")
        return  # extensie D3

    ar.complete_run(persist_calib_run_id, summary={"result": "SUCCESS", "temperature": temperature})
    # --- sfârșit bloc nou ---

    try:
        challenger_manager.create_challenger(...)
        ...
```

Simetric complet cu blocul de persistare a modelului (Pasul 9) — aceleași coduri de rezultat (`SUCCESS`/`*_NOT_AVAILABLE`/`*_STORAGE_FAILURE`), aceeași filosofie `try/except Exception` cu justificare identică (ADR-049 §9 extinde explicit INV-1 la eșecul de calibrare).

**Comportament explicit la eșec parțial al `create_challenger()`** (cerut la review — aceeași rigoare aplicată la Pasul 9): la acest punct au fost deja persistate DOUĂ artefacte (model + calibrare), ambele reușite. Dacă `create_challenger()` eșuează după aceea (cursă pe indexul unic, Postgres indisponibil — cazul deja tratat de `try/except challenger_manager.ChallengerManagerError`, neschimbat), **ambele artefacte rămân orfane în Storage** — niciunul nu se șterge automat. Aceasta e aceeași filosofie deja stabilită la ADR-048 (Failure Matrix §4.1, rândul 2, pentru artefactul de model) — extinsă simetric la artefactul de calibrare: un artefact orfan e cost de stocare izolat, acceptat, nu o entitate invalidă vizibilă restului sistemului. **Implementarea NU introduce niciun mecanism de „cleanup inteligent"** la acest eșec — nici pentru model, nici pentru calibrare — eventuala ștergere a artefactelor orfane rămâne exclusiv responsabilitatea unei viitoare politici de Garbage Collection (gol cunoscut, acceptat, deferat — `MODEL_ARTIFACT_STORAGE_CONTRACT.md` §4, neschimbat).

### 2.2 Diff conceptual — `challenger_shadow.predict_with_challenger()`

```python
def predict_with_challenger(features: dict, training_run_id: str) -> tuple[float, float, float] | None:
    try:
        from learning_core import model_artifact_storage, calibration_artifact_storage
        from ml_predictor import FEATURE_COLUMNS, _softmax_with_temperature
        ...
        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return None

        row = pd.DataFrame(...)  # neschimbat

        temperature = calibration_artifact_storage.load_calibration_artifact(training_run_id)
        if temperature is not None:
            margins = model.predict(row, output_margin=True)
            probs = _softmax_with_temperature(margins, temperature)[0]
        else:
            probs = model.predict_proba(row)[0]  # cale actuală, neschimbată — degradare grațioasă

        return float(probs[0]), float(probs[1]), float(probs[2])
    except Exception as exc:
        ...  # neschimbat
```

**Important**: aici absența calibrării NU oprește shadow logging-ul (spre deosebire de §2.1, la creare) — degradare grațioasă, consecvent cu ADR-049 §8/§9 („artefactul de calibrare nu poate fi încărcat → probabilități brute, log explicit"), nu gating. Gate-ul e o singură dată, la creare (§2.1); după aceea, absența calibrării (teoretic imposibilă prin construcție, dar tratată defensiv aici fiindcă funcția rulează la fiecare predicție live) degradează, nu blochează.

## 3. Impact asupra testelor

| Fișier | Teste noi/extinse |
|---|---|
| `tests/test_calibration_artifact_storage.py` (**nou**) | Round-trip save/load; degradare grațioasă fără Supabase; degradare la artefact lipsă/corupt — mirror direct al `tests/test_model_artifact_storage.py` |
| `tests/test_ml_walk_forward.py` | Verificare aditivă: `oof_margins`/`oof_labels` prezente în rezultat, chei existente neschimbate |
| `tests/test_ml_predictor_seed_from_champion.py` | `seed_from_champion(..., temperature=...)` — stochează corect; apel fără `temperature` (backward compat) — `self.temperature` rămâne `None` |
| Test nou pentru `predict()` calibrat vs. necalibrat | Cu `self.temperature=None`: ieșire byte-identică cu `predict_proba()` de azi (regresie explicită — proprietatea „fără calibrare, fără schimbare" din ADR-049 §3). Cu `self.temperature` setat: `argmax` neschimbat față de necalibrat (proprietatea centrală a Temperature Scaling, verificată direct, nu presupusă) |
| `tests/test_learning_core_xgboost_adapter.py` | `get_calibration_temperature()` — `None` înainte de antrenare, valoare după |
| `tests/test_learning_core_production_champion.py`, `tests/test_league_weights_adaptive.py` | `get_calibration_temperature()` → `None`, necondiționat |
| `tests/test_continuous_learning.py` | Simetric cu Pasul 9: (a) cale fericită — calibrare persistată, Challenger creat; (b) `CALIBRATION_NOT_AVAILABLE` → Challenger NU se creează; (c) `CALIBRATION_STORAGE_FAILURE` (`None` și excepție) → Challenger NU se creează; (d) persistare model+calibrare reușite + `create_challenger()` eșuează → ambele artefacte orfane, niciun Challenger, flux curat (extensie a testului deja existent din Pasul 9) |
| `tests/test_challenger_shadow_adapter.py` | Cu calibrare disponibilă → foloseşte calea calibrată; fără calibrare → cade pe `predict_proba()`, identic cu azi |

## 4. Ordinea implementării

1. `calibration_artifact_storage.py` — izolat, testabil singur, fără dependențe noi.
2. `ml_predictor.py` — fitting + aplicare + accesori, testabil izolat (fără dependență de pașii 3-8).
3. Teste pentru pasul 2 (`test_ml_walk_forward.py`, `test_ml_predictor_seed_from_champion.py`, testul nou de calibrare la `predict()`).
4. `model_registry.py` + cei 3 adaptoare — `get_calibration_temperature()`.
5. Teste pentru pasul 4.
6. `continuous_learning.py` — wiring-ul din §2.1.
7. `challenger_shadow.py` — wiring-ul din §2.2.
8. Teste pentru pașii 6-7.
9. `pytest tests/` complet — regresie.

Motivul ordinii: fiecare pas verificabil izolat înainte de următorul (storage → engine → protocol → orchestrator → shadow), consistent cu disciplina deja aplicată la Pasul 9.

## 5. Criterii de validare

- `pytest tests/` verde, inclusiv testele noi.
- **Regresie explicită, obligatorie**: pe un fixture cunoscut, fără calibrare disponibilă, `MLPredictorEngine.predict()` produce exact aceleași probabilități ca înainte de acest pas — nicio schimbare de comportament pentru calea necalibrată.
- Verificare directă (nu presupusă) că `argmax`-ul probabilităților rămâne neschimbat înainte/după calibrare, pe un eșantion de test — proprietatea centrală care a motivat alegerea Temperature Scaling (ADR-049 §2.4/§3).
- Verificare AST/grep: `model_artifact_storage.py`, `training_runner.py`, `challenger_manager.py`, `promotion_service.py`, `champion_loader.py`, `oracle_engine.py` rămân neatinse — verificabil prin `git diff --stat`.

## 6. Criterii de rollback

- **Cod**: `git revert` — trivial, nicio migrare SQL.
- **Date**: niciun rând existent modificat retroactiv.
- **Storage**: artefacte de calibrare deja scrise (dacă implementarea a rulat live) rămân — fără GC, cost de stocare neglijabil (un scalar per artefact), gol deja acceptat prin precedent (ADR-048 §4/`model_artifact_storage.py`). Artefactul de calibrare NU se șterge automat la rollback local (`git revert`) și nici la eșecul parțial descris în §2.1 — urmează aceeași filosofie ADR-048 privind artefactele orfane: rămân în Storage, eliminarea lor e exclusiv responsabilitatea unei viitoare politici de GC, niciodată a unui cleanup ad-hoc introdus tacit la implementare.
- **Declanșator**: orice eșec la §5 neexplicabil ca parte așteptată a schimbării.

---

**Status**: **READY FOR IMPLEMENTATION** — 2026-08-04, de proprietarul produsului, după integrarea celor 2 clarificări obligatorii cerute la review: (1) stabilitate numerică a softmax-ului calibrat, logit shifting + validare `T > 0` — §1; (2) comportament explicit la eșec parțial al `create_challenger()` — ambele artefacte (model + calibrare) rămân orfane, fără cleanup inteligent, aceeași filosofie ADR-048 — §2.1/§6. Implementarea Pasului 10a poate începe. Pasul 10b (wiring servire live, `champion_loader.py`/`oracle_engine.py`) rămâne explicit separat, cu propriul plan, după închiderea acestuia.
