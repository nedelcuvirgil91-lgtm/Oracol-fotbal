# Pasul 13 — Implementation Plan (extinderea Challenger Framework pentru Blend, derivat din ADR-050)

**Tip**: plan tehnic de execuție. NU e ADR — autoritatea de design rămâne `docs/00_GOVERNANCE/ADR-050-challenger-framework-compound-algorithms.md` (ACCEPTED). Acest document decide exclusiv **CUM**, în limitele deja fixate de ADR-050 — nu redeschide nicio decizie arhitecturală. Orice alegere tehnică de mai jos e verificabilă direct împotriva unui punct din ADR-050; unde nu există o asemenea trasabilitate, alegerea e semnalată explicit ca decizie de execuție, nu de arhitectură.

**Precondiții**: `docs/00_GOVERNANCE/PASUL12_AUDIT_SHADOW_BLEND_CAPABILITY.md` (înghețat) + `ADR-050` (ACCEPTED) — ambele citite ca bază factuală/contractuală, nu re-investigate aici.

---

## 1. Obiectiv și scope

**Obiectiv**: un Challenger de tip Blend (`algorithm_family="blend_v1"`) poate fi antrenat, evaluat prin shadow testing pe trafic live, și — dacă un om aprobă — propus pentru promovare, **fără nicio modificare a comportamentului Challenger-ului XGBoost existent** (`xgboost_v1`) și fără nicio schimbare a ce servește azi Champion-ul live.

### 1.1 În scope

- Un adaptor nou `LearningAlgorithm` pentru Blend (`learning_core/algorithms/blend_v1.py`), înregistrat în Model Registry.
- Un mecanism nou, izolat, de inferență shadow pentru Challenger-ul Blend (`learning_core/blend_challenger_shadow.py`) — fișier nou, nu modificare a `challenger_shadow.py`.
- Extinderea punctului de apel din `oracle_engine.py` (`_log_challenger_shadow()`) ca să verifice, ADDITIV, și un Challenger activ sub familia `blend_v1` — pe lângă verificarea existentă pentru `xgboost_v1`, nu în locul ei.
- Un flag nou, dedicat, implicit oprit: `blend_challenger_shadow_logging_enabled`.
- Rezolvarea explicită a interacțiunii calibrare↔blend (ADR-050 §5, lăsată deschisă) — decizie de execuție, motivată în §2.4.
- Teste — unitare pentru fiecare componentă nouă, plus o gardă structurală care verifică (prin `git diff`/AST) că fișierele declarate neatinse chiar rămân neatinse.

### 1.2 Explicit în afara scope-ului (per ADR-050 §8, neschimbat)

- Promovare live / `champion_loader.py` / `oracle_engine._resolve_champion()` / `RUNTIME_CONTRACT.md` — dacă un Challenger `blend_v1` ar ajunge vreodată la `candidate_for_promotion` și ar fi promovat manual, el ar deveni un rând în `model_champions` **niciodată citit** de `_resolve_champion()` (hardcodat azi la `_ALGORITHM_FAMILY="xgboost_v1"`, neatins de acest plan) — un Champion „orfan", fără efect asupra servirii live. Verificat explicit în §6 din acest plan („Riscuri și rollback"), nu doar presupus.
- Decizia dacă Blend „e mai bun" — răspuns parțial deja dat de Pasul 11, rămâne subiect al Pasului 14.
- `ADR-028`/`league_weights_adaptive` — neatinse.
- Orice extindere generică a `LearningAlgorithm.get_trained_model()` pentru algoritmi fără submodel XGBoost — Blend ARE un submodel XGBoost (vezi §2.1); acest caz nu-l cere.
- `learning_core/model_registry.py` — neatins. ADR-050 §6.1 lăsase deschisă posibilitatea unui „contract suplimentar" pentru algoritmi compuși; §2.1 de mai jos rezolvă explicit acea întrebare: `blend_v1` se încadrează exact în contractul `LearningAlgorithm` existent (fără nicio extindere), deci fișierul rămâne neatins.

## 2. Modificări pe componente

### 2.1 `learning_core/algorithms/blend_v1.py` (nou)

Adaptor `LearningAlgorithm`, tipar identic `xgboost_v1.py` (nu reinventat):

- `name = "blend_v1"`, `version = "1"`, `league_scope = "all"`.
- `fit()`: instanțiază propriul `MLPredictorEngine()` și apelează `.train()` — exact ca `XGBoostV1Algorithm.fit()`. **Decizie de execuție**: `blend_v1` antrenează propriul submodel ML, independent de orice Challenger `xgboost_v1` existent (nu reutilizează artefactul altui Challenger) — cea mai simplă opțiune, consecventă cu tiparul deja existent, fără cuplare nouă între Challenger-i de familii diferite. Cost acceptat: antrenare duplicată dacă ambele familii rulează simultan — antrenarea XGBoost e deja documentată ca sub-secundă (`ml_predictor.py`, comentariu existent), cost neglijabil.
- `get_trained_model()`: întoarce `self._engine.model` (submodelul ML) — **identic** cu `XGBoostV1Algorithm.get_trained_model()`. Răspunde explicit la întrebarea lăsată deschisă în ADR-050 §5: „artefactul persistat" pentru un Challenger Blend e submodelul ML, nimic mai mult — componenta Oracle a Blend-ului nu e „antrenată", e configurație deja versionată separat (`model_weights`/`model_config`), neatinsă de acest plan.
- `get_calibration_temperature()`: întoarce `self._engine.temperature` — identic `xgboost_v1`, reutilizează exact mecanismul ADR-049/Pasul 10a, neschimbat.
- `predict(features)`: **nu e apelat de fluxul de shadow al acestui plan** (vezi §2.3 — evaluarea shadow pentru Blend nu trece prin `LearningAlgorithm.predict()`, la fel ca `xgboost_v1` azi). Implementat totuși, pentru conformitate cu Protocolul (`runtime_checkable`) — deleagă la `self._engine.predict(features)`, fără blend (returnează probabilitățile ML brute) — documentat explicit în docstring ca „neutilizat de calea reală, doar conformitate structurală", exact tiparul deja folosit de `league_weights_adaptive.predict()`.

**Consecință directă**: `learning_core/bootstrap.py` capătă o singură linie nouă, aditivă — `model_registry.register(BlendV1Algorithm())` — simetrică cu cele 3 existente. Faza A/B din `continuous_learning.py` (`run_cycle()`, `for name, version in model_registry.list_available()`) preiau automat noul algoritm — **verificat direct în cod, zero schimbare necesară în `continuous_learning.py`** (iterarea e deja generică).

### 2.2 `learning_core/blend_challenger_shadow.py` (nou, izolat)

Mecanism de inferență shadow pentru Blend — fișier separat de `challenger_shadow.py`, care rămâne **complet neatins** (garanție verificabilă prin `git diff --stat`, nu doar declarată).

```python
def predict_with_blend_challenger(
    oracle_probs: tuple[float, float, float], features: dict, training_run_id: str,
) -> tuple[float, float, float] | None:
    """oracle_probs = probabilitățile Oracle deja calculate de apelant
    (oracle_engine.py) pentru meciul curent — NU recalculate aici, evită
    duplicarea feature_engine.calibrate_xg()/poisson_model() (risc semnalat
    explicit în audit/ADR-050 §5)."""
    try:
        from learning_core import model_artifact_storage, calibration_artifact_storage
        from ml_predictor import FEATURE_COLUMNS, MLPrediction, blend_predictions, _softmax_with_temperature
        import supabase_client as sb

        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return None

        row = ...  # identic challenger_shadow.predict_with_challenger(), FEATURE_COLUMNS + fillna median/0.0

        temperature = calibration_artifact_storage.load_calibration_artifact(training_run_id)
        if temperature is not None:
            margins = model.predict(row, output_margin=True)
            ml_probs = _softmax_with_temperature(margins, temperature)[0]
        else:
            ml_probs = model.predict_proba(row)[0]

        training_run = sb.get_training_run(training_run_id)  # deja existent, reutilizat (champion_loader.py îl folosește identic)
        samples_used = training_run.get("samples_used", 0) if training_run else 0

        ml_pred = MLPrediction(
            prob_home=float(ml_probs[0]), prob_draw=float(ml_probs[1]), prob_away=float(ml_probs[2]),
            confidence=max(ml_probs), model_version=1, samples_used=samples_used,
        )
        ph, pd_, pa, _label = blend_predictions(oracle_probs, ml_pred)  # funcție pură, neatinsă
        return ph, pd_, pa
    except Exception as exc:
        logger.warning(...)
        return None


def log_shadow_for_active_blend_challenger(
    league_scope: str, oracle_probs: tuple[float, float, float], features: dict,
    fixture_id: str, home_xg: float, away_xg: float,
    league: str, home_team: str, away_team: str, kickoff_date: str,
) -> bool:
    """Simetric cu challenger_shadow.log_shadow_for_active_challenger(),
    dar hardcodat pe algorithm_family="blend_v1" — NU generic peste mai
    multe familii compuse (YAGNI, un singur algoritm compus există azi)."""
    ...  # identic ca structură cu funcția existentă, family="blend_v1"
```

**Notă asupra `MLPrediction`**: constructor deja existent în `ml_predictor.py` — reutilizat direct, nicio schimbare la definiția clasei.

### 2.3 Calea de inferență aleasă pentru această implementare

Implementarea propusă aici utilizează o cale paralelă de inferență (§2.2, direct pe artefacte), nu o rutare prin `LearningAlgorithm.predict()` — decizie de execuție pentru acest plan, nu o închidere arhitecturală (forma rămâne deschisă la nivel de ADR-050, o implementare viitoare ar putea alege altfel, cu propria analiză). Motivul alegerii de aici: evită introducerea unei capacități noi (reconstrucția unei instanțe `LearningAlgorithm` „hidratate" dintr-un `training_run_id`, azi inexistentă) doar pentru acest caz, și păstrează comportamentul actual al Challenger-ului XGBoost complet neatins — `xgboost_v1`-ul din `challenger_shadow.py` continuă, la fel ca azi, să nu treacă prin `XGBoostV1Algorithm.predict()` (confirmat în audit), deci simetria dintre cele două căi rămâne intactă.

### 2.4 Interacțiunea calibrare↔blend — decizie de execuție (ADR-050 §5, deschisă)

**Decizie**: Temperature Scaling se aplică pe probabilitățile submodelului ML **înainte** de combinarea cu Oracle (vezi pseudocodul §2.2 — `ml_probs` e deja calibrat când intră în `blend_predictions()`), nu pe rezultatul blend-ului — se reutilizează aceeași ordine deja validată în Pasul 11 (ML calibrat → Blend), evitând un al doilea strat de calibrare, nevalidat, asupra rezultatului compus.

### 2.5 Ownership-ul ciclului de viață — reutilizare integrală, nu duplicare

Blend reutilizează integral ciclul de viață existent al Challenger Framework — creare (`challenger_manager.create_challenger()`), tranziții FSM (`challenger_manager.transition()`), atașare artefact model (`model_artifact_storage.save_model_artifact()`), atașare artefact calibrare (`calibration_artifact_storage.save_calibration_artifact()`), verdict `candidate_for_promotion` (`shadow_testing.evaluate_experiment()` prin `challenger_evaluation.evaluate_active_challenger()`) — exact aceleași componente ca pentru `xgboost_v1`, apelate identic din `continuous_learning.py` (deja generic, §2.1). Singura diferență reală introdusă de acest plan e mecanismul de inferență shadow (§2.2) — nimic din restul ciclului de viață nu e duplicat sau reimplementat pentru Blend.

## 3. Respectarea invariantelor ADR-050 (§7.1)

| Invariant | Cum e respectat aici |
|---|---|
| Champion live neschimbat | `champion_loader.py`, `oracle_engine._resolve_champion()` — neatinse (§1.2 din acest plan). Verificat suplimentar în §6 din acest plan („Riscuri și rollback"): un `blend_v1` promovat n-ar fi niciodată citit de `_resolve_champion()`, hardcodat pe `xgboost_v1`. |
| Niciun Challenger nu influențează predicția live | `blend_challenger_shadow.py` e apelat DUPĂ ce predicția finală (`pred`) e deja construită complet — identic tiparului `_log_challenger_shadow()` existent (side effect, nu parte din pipeline). |
| Shadow testing strict read-only | `log_shadow_for_active_blend_challenger()` scrie exclusiv în `shadow_predictions` (prin `shadow_testing.log_shadow_prediction()`, neatins) — nicio scriere în `match_history`/`weights.json`/`model_config`. |
| Promovarea rămâne singura cale spre producție | `promotion_service.py` neatins de acest plan — un `blend_v1` `candidate_for_promotion` ar necesita încă o aprobare umană explicită (T3a, `continuous_learning.py`, neschimbat) pentru orice tranziție. |
| **(ADR-050 §4) Comportamentul `xgboost_v1` neschimbat** | `challenger_shadow.py` — zero linii modificate. Verificat prin gardă de test (§5 din acest plan, „Plan de validare"). |

## 4. Strategia de migrare

- **Fără flag activ implicit** — `blend_challenger_shadow_logging_enabled` (nou, `DEFAULT_CONFIG`) implicit `False`, simetric cu `challenger_shadow_logging_enabled`/`flashscore_shadow_logging_enabled`/`consensus_capture_enabled` (precedent deja stabilit de 3 ori în `oracle_engine.py`).
- **Fără modificare a comportamentului existent** — orice linie atinsă în `oracle_engine.py` e strict adăugare (un bloc nou, condiționat de flag-ul nou), niciodată editare a blocului existent pentru `xgboost_v1`.
- **Mecanism nou, izolat** — `learning_core/blend_challenger_shadow.py`, fișier separat, nu extensie a `challenger_shadow.py`.
- Nicio migrare de date, nicio schimbare de schemă SQL — `challengers`/`training_runs`/`shadow_predictions` deja generice (confirmat live, audit §1-3), `algorithm_family="blend_v1"` e doar o valoare nouă într-o coloană `TEXT` deja fără constrângere.

## 5. Plan de validare

| Nivel | Ce se testează |
|---|---|
| Unitar — `blend_v1.py` | `fit()`/`get_trained_model()`/`get_calibration_temperature()` — tipar identic testelor existente pentru `xgboost_v1.py`. |
| Unitar — `blend_challenger_shadow.py` | `predict_with_blend_challenger()`: calibrare disponibilă/absentă, artefact lipsă, eroare neașteptată (degradare grațioasă) — tipar identic `test_challenger_shadow_adapter.py`. Verificare explicită: rezultatul respectă `sample_factor` din `blend_predictions()` (blend-ul se comportă diferit la `samples_used` mic vs. mare). |
| Unitar — `oracle_engine._log_challenger_shadow()` | Cu flag oprit (implicit): zero import, zero apel — identic tiparului existent. Cu flag pornit, fără Challenger `blend_v1` activ: no-op. Cu Challenger activ: apel corect, cu `oracle_probs` = exact `(pred.prob_home_win, pred.prob_draw, pred.prob_away_win)`. |
| **Gardă structurală (obligatorie)** | Test nou, bazat pe **AST** (consecvent cu gărzile deja existente în proiect, ex. `test_champion_loader.py::test_module_has_single_known_importer`, `test_canonical_feature_ownership.py`) — verifică static faptul că `learning_core/challenger_shadow.py` nu importă/nu e importat de niciun modul nou legat de Blend, și că semnătura funcțiilor sale existente (`predict_with_challenger`, `log_shadow_for_active_challenger`) rămâne neschimbată. Cod persistat, parte din suita de teste, nu o verificare punctuală la commit. |
| Integrare | Registry: `register_default_algorithms()` idempotent cu 4 algoritmi (nu 3) — extensie a `test_learning_core_bootstrap.py`. `run_cycle()` procesează `blend_v1` fără nicio ramură specială (verifică direct genericitatea confirmată în §2.1). |
| Shadow (verificare manuală, nu automatizată) | Cu flag activat pe un mediu de test, confirmare că un Challenger `blend_v1` acumulează rânduri în `shadow_predictions` fără nicio scriere în `match_history`/`model_champions`. |
| Regresie completă | `pytest tests/` — verde, fără nicio schimbare la testele existente pentru `xgboost_v1`/`challenger_shadow.py`/`champion_loader.py`. |

### Criterii de acceptare

1. `pytest tests/` verde, inclusiv testele noi.
2. `git diff --stat` confirmă: `challenger_shadow.py`, `champion_loader.py`, `oracle_engine._resolve_champion()`, `promotion_service.py`, `RUNTIME_CONTRACT.md`, `ADR-028`, `learning_core/model_registry.py` — neatinse.
3. Gardă structurală (descrisă mai sus, în tabelul din această secțiune) verde.
4. Verificare manuală shadow (dacă mediul o permite) — confirmă zero efect asupra `match_history`/Champion live.
5. **`scripts/rerun_etapa3_benchmark.py` (Pasul 11) produce aceleași rezultate numerice pentru `xgboost_v1`/ML necalibrat-calibrat ca înainte de această implementare** — cea mai directă dovadă disponibilă că invariantul central (§3 din acest plan, „Respectarea invariantelor ADR-050", rândul „comportament `xgboost_v1` neschimbat") chiar a fost respectat, nu doar presupus din `git diff`.

## 6. Riscuri și rollback

| Risc | Mitigare | Rollback |
|---|---|---|
| Un `blend_v1` `candidate_for_promotion` e aprobat manual înainte de a exista un „Pasul 10b pentru Blend" | Verificat explicit (nu doar presupus): `_resolve_champion()` rămâne hardcodat pe `_ALGORITHM_FAMILY="xgboost_v1"` — un Champion `blend_v1` promovat e „orfan", niciodată citit de servirea live. Zero risc real de servire. | N/A — nu există stare de servire de revenit. |
| Antrenare duplicată (submodel ML propriu pentru `blend_v1`, separat de `xgboost_v1`) | Cost acceptat explicit (§2.1) — antrenare sub-secundă, documentat deja în cod. | Dezactivarea completă a căii Blend (flag-ul `blend_challenger_shadow_logging_enabled` oprit + Challenger `blend_v1` dezactivat/deprecat) — revenire imediată la fluxul existent XGBoost, fără nicio schimbare de comportament pentru `xgboost_v1`. |
| Al doilea cod-cale de inferență shadow (`blend_challenger_shadow.py`) | Izolat într-un singur fișier nou, fără dependențe încrucișate cu `challenger_shadow.py`. | Aceeași dezactivare comportamentală de mai sus; eliminarea codului (`git revert`, ștergerea fișierului + linia din `bootstrap.py`) e un detaliu de execuție ulterior, nu condiția care restabilește comportamentul corect. |
| Artefacte orfane (model+calibrare) dacă `create_challenger()` eșuează după persistare, pentru `blend_v1` | Identic filosofiei deja acceptate la ADR-048/049 — niciun cleanup ad-hoc introdus. | N/A — cost de stocare neglijabil, deja acceptat ca precedent. |

**Declanșator general de rollback**: orice eșec la criteriile din §5 neexplicabil ca parte așteptată a schimbării, sau orice observație (prin verificare manuală) că `xgboost_v1` se comportă diferit față de înainte de acest pas.

## 7. Tabel de trasabilitate (ADR-050 → implementare → test)

Notă de citire: coloana din stânga citează secțiuni din **ADR-050**; trimiterile din coloana dreaptă către secțiuni ale **acestui plan** sunt marcate explicit „din acest plan", ca să nu se confunde cu numerotarea ADR-050 (ambele documente au, de exemplu, un §5 — cu conținut diferit).

| Cerință ADR-050 | Componentă | Test care o validează |
|---|---|---|
| ADR-050 §4 — comportament `xgboost_v1` neschimbat | `challenger_shadow.py` neatins | Gardă structurală (§5 din acest plan, „Plan de validare") |
| ADR-050 §7.1 — Champion live neschimbat | `champion_loader.py`/`_resolve_champion()` neatinse | `git diff --stat` (criteriu acceptare #2) + verificare hardcodare `_ALGORITHM_FAMILY` (§6 din acest plan, „Riscuri și rollback") |
| ADR-050 §7.1 — niciun Challenger nu influențează predicția live | `_log_challenger_shadow()` — apel după `pred` completă | Test unitar `oracle_engine._log_challenger_shadow()` (§5 din acest plan) |
| ADR-050 §7.1 — shadow strict read-only | `blend_challenger_shadow.py` — scrie doar `shadow_predictions` | Test unitar `log_shadow_for_active_blend_challenger()` (§5 din acest plan) |
| ADR-050 §7.1 — promovarea rămâne singura cale | `promotion_service.py` neatins, T3a neschimbat | `git diff --stat` |
| ADR-050 §5 — evitare duplicare logică Oracle | `oracle_probs` transmis de apelant, nu recalculat | Review de cod (`blend_challenger_shadow.py` nu importă `feature_engine`) |
| ADR-050 §5 — interacțiune calibrare↔blend | Calibrare ML înainte de blend (§2.4 din acest plan) | Test unitar — verifică ordinea explicit (calibrare aplicată, apoi `blend_predictions()` apelat cu `ml_probs` deja calibrat) |
| ADR-050 §5 — ce înseamnă „artefact persistat" | `get_trained_model()` = submodel ML (§2.1 din acest plan) | Test unitar `blend_v1.py` |
| ADR-050 §6.1 — suport multi-familie în `oracle_engine.py` | Bloc nou, aditiv, gatat de flag dedicat | Test unitar (flag oprit/pornit, cu/fără Challenger activ) |
| ADR-050 §6.1 — `get_trained_model()` rămâne valabil pentru algoritmii existenți, fără slăbire | `learning_core/model_registry.py` neatins — `blend_v1` se încadrează în contractul actual, fără contract suplimentar (§2.1 din acest plan) | `git diff --stat` (criteriu acceptare #2) |
| North Star #3 (`CLAUDE.md`) — niciun flag nou implicit activ | `blend_challenger_shadow_logging_enabled` implicit `False` | Test unitar (comportament implicit) |

---

**Status**: **READY FOR IMPLEMENTATION** — 2026-08-04, de proprietarul produsului, după două runde de review: (1) 6 observații de fond (§2.3 reformulat ca decizie de execuție, nu închidere arhitecturală; §2.4 redus la un paragraf; gardă structurală fixată pe AST; rollback descris comportamental; criteriu de acceptare nou — reproducerea Pasului 11; §2.5 nou — ownership-ul ciclului de viață); (2) o trecere de consistență editorială — terminologie unificată („algoritm/Challenger compus", nicio variantă „hibrid"), toate referințele „ADR-050 §X" verificate împotriva numerotării finale, toate auto-referințele la secțiunile acestui plan disambiguate explicit („din acest plan") acolo unde s-ar fi putut confunda cu numerotarea ADR-050, și `learning_core/model_registry.py` adăugat explicit la lista de fișiere neatinse (rezolvă punctul lăsat deschis la ADR-050 §6.1 — `blend_v1` se încadrează în contractul existent, fără extindere). Seria Audit (Pasul 12, înghețat) → ADR-050 (ACCEPTED) → acest plan e închisă din punct de vedere al designului. Implementarea poate începe; commit-ul întregii serii urmează abia după implementare + validare.
