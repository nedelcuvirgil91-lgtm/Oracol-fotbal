# Pasul 12 — Audit (read-only): capacitatea infrastructurii de shadow testing pentru un Challenger Blend

**Tip**: audit tehnic, read-only. Nu e un ADR, nu e un Implementation Plan — nu propune nicio soluție, nicio schimbare de cod. Răspunde exclusiv la întrebarea de mai jos, pe baza codului citit direct, nu presupus.
**Data**: 2026-08-04
**Metodă**: citire directă a codului sursă (nu grep superficial) — `shadow_testing.py`, `learning_core/challenger_shadow.py`, `learning_core/model_registry.py`, plus dependențele descoperite în timpul auditului și relevante direct pentru întrebare: `learning_core/model_artifact_storage.py`, `learning_core/continuous_learning.py`, `learning_core/bootstrap.py`, `learning_core/algorithms/*.py`, `oracle_engine.py` (punctul de apel), `ml_predictor.blend_predictions()`.

## Întrebarea auditului

> Poate infrastructura actuală de `shadow_testing.py` evalua corect un Challenger de tip Blend, fără să afecteze producția? NU dacă Blend e mai bun — dacă infrastructura poate evalua unul.

---

## 1. `shadow_testing.py` — ce presupune azi despre un Challenger

**Concluzie: complet generic, fără nicio presupunere specifică ML.**

- `log_shadow_prediction()` (linia 56) primește exact `(prob_home, prob_draw, prob_away)` + metadate string (`experiment_name`, `experiment_version`, `experiment_group`) — niciun tip de model, niciun format de artefact. Orice sursă de probabilități e acceptată identic.
- `evaluate_experiment()` (linia 229) compară rândurile din `shadow_predictions` (`experiment_group="treatment"`) cu baseline-ul deja servit, citit din `match_history.prob_*_pred` — Brier/log-loss/accuracy calculate identic, indiferent ce a produs probabilitățile logate.
- `STATISTICAL_TESTS` (paired bootstrap/permutation/Wilcoxon) — operează pe liste de scoruri numerice, fără nicio referință la algoritm.

**Verificat direct**: nicio linie din acest fișier importă `xgboost`, `ml_predictor`, sau orice modul specific ML. Modulul e deja documentat explicit ca independent (header, liniile 7-20).

## 2. `learning_core/challenger_shadow.py` — puncte de integrare, ciclu, metrici

**Concluzie: acesta e punctul real de blocaj — cuplat strict la XGBoost, nu la abstracția `LearningAlgorithm`.**

### 2.1 `predict_with_challenger(features, training_run_id)` (linia 46)

- Încarcă artefactul brut direct prin `model_artifact_storage.load_model_artifact()` — care la rândul lui (verificat, `model_artifact_storage.py` liniile 39-59) apelează `model.save_model()`/implicit `.load_model()` — API nativ XGBoost, nu o abstracție.
- Apelează direct `model.predict_proba(row)` / `model.predict(row, output_margin=True)` pe obiectul încărcat — API specific XGBoost/sklearn.
- **Nu trece prin `LearningAlgorithm.predict()`** — bypasses complet Model Registry. Chiar și pentru `xgboost_v1` (singurul algoritm ML înregistrat azi), evaluarea shadow NU apelează `XGBoostV1Algorithm.predict()` — reimplementează o cale de inferență paralelă, direct pe artefactul brut.
- Nu calculează nicio componentă Oracle — nicio referință la `feature_engine.calibrate_xg()`/`poisson_model()` în acest fișier.

### 2.2 `log_shadow_for_active_challenger()` (linia 86) — apelat din `oracle_engine.py`

- Verificat la sursă (`oracle_engine.py:1848-1855`, metoda `_log_challenger_shadow()`): apelul e făcut cu `algorithm_family=_ALGORITHM_FAMILY`, unde `_ALGORITHM_FAMILY = "xgboost_v1"` e o constantă HARDCODATĂ în `ml_predictor.py:44` — nu o iterare peste toate familiile din Model Registry.
- Consecință directă: chiar dacă un Challenger de tip `algorithm_family="blend_v1"` ar exista în tabela `challengers`, acest punct de intrare unic din `oracle_engine.py` NU l-ar verifica/evalua niciodată — verifică exclusiv un Challenger sub familia `"xgboost_v1"`.
- `home_xg`/`away_xg` logate identic pentru `control` ȘI `treatment` (valorile Oracle-ului deja servit, calculate în afara acestui modul) — nu afectează evaluarea (doar `prob_*` participă la Brier/log-loss/accuracy), dar înseamnă că un viitor Challenger care ar produce propriul xG nu are azi nicio cale să-l facă vizibil în `shadow_predictions`.

## 3. `learning_core/model_registry.py` — tipuri de artefacte/metadate, contract existent

**Concluzie: Protocolul `LearningAlgorithm` e generic ca formă (`fit`/`predict`/`describe`), dar `get_trained_model()` e contractual restrâns, explicit, la un backend XGBoost.**

- Docstring-ul `get_trained_model()` (liniile 66-84): *"compatibil cu backend-ul curent de persistență (XGBClassifier `.save_model()`/`.load_model()`/`.predict_proba()`, vezi `model_artifact_storage.py`) — NU orice obiect Python arbitrar — sau None dacă algoritmul nu produce un artefact persistabil real (vezi ADR-028)."*
- Acest contract, combinat cu `model_artifact_storage.save_model_artifact()` (care apelează direct `model.save_model(...)`), înseamnă: orice `LearningAlgorithm` ce vrea un Challenger persistat trebuie să întoarcă la `get_trained_model()` un obiect cu API XGBoost nativ.
- `get_calibration_temperature()` (Pasul 10a) — același tipar: `None` dacă algoritmul nu produce o calibrare validă, fără nicio presupunere suplimentară specifică unui algoritm compus.

## 4. Precedent direct, deja documentat în cod — ADR-028 (`league_weights_adaptive`)

Auditul a găsit un precedent EXACT pentru această întrebare, deja rezolvat și documentat, nu ipotetic:

`learning_core/algorithms/league_weights_adaptive.py` (liniile 22-32) documentează explicit că a lovit aceeași problemă structurală: *"întregul lanț `challenger_shadow → model_artifact_storage → promotion_service/champion_loader` e construit explicit peste `XGBClassifier.save_model()/.load_model()/.predict_proba()`... Un weights dict nu are aceste metode — generalizarea acelui lanț pentru algoritmi non-artifact ar fi o extindere de scope reală, nu o migrare recalibrare→Registry, și ar necesita un ADR nou dedicat."*

Decizia oficială (ADR-028, FROZEN) a fost: acel algoritm NU participă la Challenger Framework (`participates_in_challenger_framework: False`, citit generic în `continuous_learning.py:163`) — `predict()` există doar pentru conformitate cu Protocolul, niciodată apelat de calea reală de shadow/promovare.

**Diferență relevantă pentru Blend**: `league_weights_adaptive` e un caz "curat" (nu produce deloc probabilități 1X2 proprii, deci excluderea totală e naturală). Un Challenger Blend e un caz compus — ARE un submodel ML real (XGBoost, deci compatibil cu `get_trained_model()`), dar rezultatul lui final depinde ȘI de probabilitățile Oracle (nu sunt „antrenate", sunt calculate live din `feature_engine`). Excluderea totală (ca la `league_weights_adaptive`) ar elimina orice evaluare reală a Blend-ului; participarea neschimbată (ca la `xgboost_v1`) ar produce o evaluare falsă (calea de azi ar evalua doar submodelul ML, ignorând complet componenta Oracle a Blend-ului).

## 5. `production_champion` — precedent parțial diferit, tot neconcludent pentru Blend

`ProductionChampionAdapter` (liniile 1-30) ÎNFĂȘOARĂ deja întregul pipeline de producție (Poisson → Monte Carlo → blend ELO/ML → de-vig → value betting) — conceptual cel mai apropiat de „Blend" dintre cei 3 algoritmi înregistrați azi. Dar:

- `fit()` e no-op intenționat (niciodată nu antrenează), `get_trained_model()` întoarce mereu `None`.
- `describe()` NU setează `participates_in_challenger_framework` (implicit `True`, per `continuous_learning.py:163`) — deci NU e exclus explicit ca `league_weights_adaptive`.
- În schimb, e blocat printr-un mecanism DIFERIT: gate-ul INV-1/ADR-048 din `_phase_b_train_new()` (`continuous_learning.py:326-329`) — `algorithm.get_trained_model() is None` → `MODEL_NOT_AVAILABLE`, Challenger-ul nu se creează.
- Concluzie: acest adaptor reprezintă explicit „campionul curent", nu un candidat evaluabil — nu poate fi refolosit ca bază pentru un Challenger Blend fără o antrenare/evaluare separată de campion.

## 6. `ml_predictor.blend_predictions()` — funcție pură deja existentă, dar input-ul ei nu e produs azi de nicio cale Challenger

Semnătura verificată (`ml_predictor.py:618`): `blend_predictions(poisson_probs: tuple[float,float,float], ml_pred: MLPrediction | None, ml_weight: float = 0.35)`.

- Are nevoie de `poisson_probs` — calculat LIVE, per meci, prin `feature_engine.calibrate_xg()`/`poisson_model()`.
- Are nevoie de un obiect `MLPrediction` complet (`.prob_home/.prob_draw/.prob_away/.samples_used/.model_version`), nu doar 3 probabilități brute — `sample_factor` din interiorul funcției citește explicit `.samples_used`.
- `predict_with_challenger()` (§2.1) nu calculează niciodată `poisson_probs` și nu construiește un `MLPrediction` — întoarce strict un tuple de 3 probabilități, direct din artefactul XGBoost.

---

## Verdict

### 1. Contractele existente sunt suficiente / nu sunt suficiente

- **`shadow_testing.py`**: **SUFICIENT**, neschimbat — complet generic, nicio presupunere ML.
- **`learning_core/model_registry.py`** (Protocolul `LearningAlgorithm`): **SUFICIENT ca formă** (`fit`/`predict`/`describe` generice) — dar `get_trained_model()` e **INSUFICIENT ca domeniu de valori** pentru o entitate compusă ca Blend (contractual restrâns la XGBoost).
- **`learning_core/challenger_shadow.py`**: **INSUFICIENT** — cuplat direct la artefactul XGBoost brut (bypasses `LearningAlgorithm.predict()`) ȘI hardcodat pe o singură familie de algoritm la punctul de apel din `oracle_engine.py`.

### 2. Ce lipsește exact

- Un mecanism generic prin care evaluarea shadow să poată obține probabilitățile unui Challenger care nu e evaluat direct prin API-ul XGBoost (`predict_proba()`/`predict(output_margin=True)` pe artefactul brut) — auditul nu stabilește care ar trebui să fie acel mecanism.
- Acces la probabilitățile Oracle LIVE (`poisson_probs`) în punctul de evaluare shadow — azi zero calcul `feature_engine` în `challenger_shadow.py`.
- Iterare peste mai multe familii de algoritm în `oracle_engine._log_challenger_shadow()` — azi hardcodat la o singură familie (`ml_predictor._ALGORITHM_FAMILY`).
- O decizie explicită despre ce înseamnă „artefact persistat" pentru un Challenger Blend (probabil doar submodelul ML, dat fiind că Oracle nu e „antrenat" în sensul curent) — neclarificat azi, nicio urmă de precedent direct (doar cazurile „curate" `xgboost_v1` și „exclus complet" `league_weights_adaptive`).

### 3. Ce poate rămâne neschimbat

- `shadow_testing.py` — fără nicio modificare.
- `learning_core/model_artifact_storage.py` / `learning_core/calibration_artifact_storage.py` — reutilizabile ca atare pentru submodelul ML al unui Blend, dacă acel submodel rămâne un `XGBClassifier` (aceleași contracte, ADR-048/ADR-049, neatinse).
- `learning_core/training_runner.py`, `learning_core/challenger_manager.py` — complet generice (`algorithm_family` e text liber, fără constrângere de schemă) — nicio schimbare necesară.
- `ml_predictor.blend_predictions()` — funcție pură deja existentă, direct reutilizabilă.

### 4. Riscuri identificate

- **Duplicare de logică Oracle**: dacă probabilitățile Oracle ar fi recalculate în interiorul lanțului de shadow (nu doar reutilizate din predicția deja servită), ar risca să dubleze `feature_engine.calibrate_xg()`/`poisson_model()` — contrar disciplinei „cod real, nu reimplementat" respectate consecvent la Pașii 9-11.
- **Extindere de scope care necesită ADR nou** — precedentul ADR-028 spune explicit acest lucru pentru generalizarea lanțului XGBoost-specific; e un cost de guvernanță documentat deja, nu doar o presupunere a acestui audit.
- **Risc de regresie pe Challenger-ul XGBoost existent**: orice mecanism generic care ar înlocui calea actuală de inferență directă pe artefact (§2.1) ar reprezenta o schimbare de contract, nu doar o adăugare — comportamentul azi verificat al lui `xgboost_v1` în shadow s-ar putea schimba subtil. Orice modificare acolo trebuie tratată ca risc pentru Challenger-ul ML existent, nu doar ca facilitare pentru Blend.
- **Ambiguitate de „artefact persistat" pentru Blend**: fără o decizie explicită, o implementare grăbită ar putea persista incorect fie doar submodelul ML (pierzând trasabilitatea ponderii de blend folosite la momentul evaluării), fie ar inventa un format nou de artefact (contrar filosofiei „niciun flag/schimbare de contract fără ADR").

**Întrebare rămasă în afara scopului auditului**: pentru un viitor Challenger Blend, trebuie clarificat dacă Temperature Scaling (ADR-049) se aplică asupra probabilităților submodelului ML înainte de combinarea cu Oracle sau asupra probabilităților rezultate după blend. Auditul nu răspunde acestei întrebări, deoarece ea aparține fazei de design, nu celei de diagnostic — dar poate influența definiția artefactului și contractul de inferență discutate mai sus.

### 5. Implementation Plan

Nu e inclus în acest document — per cerința explicită, auditul se oprește la diagnostic. Următorul pas, dacă e aprobat, e un Implementation Plan separat pentru Pasul 12/13.
