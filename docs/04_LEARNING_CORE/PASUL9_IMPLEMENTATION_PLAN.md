# Pasul 9 — Implementation Plan (Model Artifact Persistence)

**Tip**: plan tehnic de execuție. NU e ADR — autoritatea de design rămâne `ADR-048` (D1/D2/D3/INV-1, aprobate). Acest document decide exclusiv **cum**, în limitele deja fixate de ADR-048 — nu redeschide nicio decizie arhitecturală.

**Scop**: wire `save_model_artifact()` în `continuous_learning._phase_b_train_new()`, conform D1 (Orchestrator), D2 (înainte de `create_challenger()`), D3 (eșec → Challenger nu se creează).

---

## 1. Mecanismul ales pentru accesul la modelul antrenat

Din opțiunile analizate în ADR-048 Anexa A (neaprobată ca decizie, doar ca listă de opțiuni): **se alege extinderea protocolului `LearningAlgorithm` cu `get_trained_model() -> Any | None`.**

Motiv (criteriu de implementare, nu arhitectural): cea mai puțin invazivă dintre cele 3 opțiuni — nu atinge `TrainingRunResult`/`RunReport` (folosite și pentru afișare în `train.py` CLI), nu introduce stare nouă în `training_runner.py` (opțiune deja respinsă ca fiind cea mai slabă, chiar în Anexa A). Simetrică cu `describe()`, deja o metodă a protocolului fără parametri, care întoarce metadate despre starea internă a algoritmului.

Semnătură exactă:

```python
def get_trained_model(self) -> Any | None:
    """Modelul antrenat, compatibil cu backend-ul curent de persistență
    (XGBClassifier .save_model()/.load_model()/.predict_proba(), vezi
    model_artifact_storage.py) — NU orice obiect Python arbitrar — sau None
    dacă algoritmul nu produce un artefact persistabil real."""
    ...
```

**Compatibilitate cu backend-ul, nu „orice model"** (observație acceptată — semnătura `Any | None` era prea permisivă): `get_trained_model()` nu promite un model generic — promite un obiect compatibil cu backend-ul de persistență existent azi (`model_artifact_storage.py`, format XGBoost nativ). Un algoritm viitor al cărui model nu poate fi serializat prin acest backend întoarce `None` (ca `production_champion`/`league_weights_adaptive` azi) — generalizarea backend-ului de persistență pentru alte formate rămâne, ca și în ADR-028, în afara scopului acestui plan; nu se presupune implicit „orice model merge".

**Contract de viață, declarat explicit** (observație acceptată — altfel rămâne implicit): protocolul `LearningAlgorithm` capătă, prin această metodă, o a patra obligație pe lângă `fit`/`predict`/`describe`. Regula:

> După un `fit()` reușit (`status == "trained"`), algoritmul garantează că `get_trained_model()` întoarce **același obiect model** (identitate, nu doar egalitate structurală), consistent, până la următorul `fit()` sau până la distrugerea instanței. Nu există azi (și acest plan nu introduce) niciun mecanism de expirare/invalidare între cele două.

Respectat implicit de implementarea propusă (`self._engine.model`, atribut de instanță, neschimbat între apeluri) — declarat aici explicit ca să nu rămână presupus.

**Proprietăți suplimentare ale contractului** (observație acceptată — Orchestratorul doar citește, nu deține și nu poate modifica):

- **Side-effect free**: apelul `get_trained_model()` nu declanșează antrenare, nu modifică `is_trained`/starea internă a algoritmului, nu are efecte observabile în afara valorii întoarse.
- **Idempotent la apeluri repetate**: poate fi apelat de mai multe ori între două `fit()`-uri, întotdeauna cu același rezultat (vezi identitatea de mai sus).
- **Fără transfer de ownership**: algoritmul rămâne proprietarul obiectului model — `get_trained_model()` întoarce o referință, nu o copie, dar apelantul (Orchestratorul) nu capătă dreptul de a-l muta/distruge.
- **Simetric, `save_model_artifact()` nu are voie să modifice obiectul model primit** — regulă implicită azi (funcția doar citește prin `model.save_model(path)`, nu scrie pe obiect), consemnată aici explicit ca parte a contractului dintre Orchestrator și cele două module pe care le apelează.

**Regulă de extensibilitate** (observație acceptată): orice algoritm nou adăugat în Model Registry, care produce un model real, persistabil prin backend-ul curent, **trebuie** să implementeze `get_trained_model()` întorcând acel model — nu doar `None` din comoditate. Un algoritm care nu produce un model persistabil prin acest backend (cazul `production_champion`/`league_weights_adaptive` azi) întoarce `None`, explicit, nu omite metoda.

**Regulă `trained` ⇒ model existent, pentru algoritmi persistabili** (observație acceptată — previne o interpretare greșită viitoare a lui `MODEL_NOT_AVAILABLE` ca „normal"):

> Pentru un algoritm care participă la Challenger Framework (`participates_in_challenger_framework != False`, per ADR-028), `status == "trained"` implică obligatoriu că `get_trained_model()` întoarce un obiect non-`None`. `trained` + `None` simultan e o **stare incorectă a algoritmului**, nu un caz normal de tratat silențios — de aceea Orchestratorul o tratează explicit ca eșec (`MODEL_NOT_AVAILABLE`, §2.1), nu ca „algoritm fără model, ca de obicei". Pentru algoritmi care nu participă la Challenger Framework (`production_champion`, `league_weights_adaptive`), regula nu se aplică — `get_trained_model()` întoarce mereu `None`, indiferent de `status`, prin design (ADR-028).

## 2. Modificări concrete pe fișiere

| # | Fișier | Modificare |
|---|---|---|
| 1 | `learning_core/model_registry.py` | Adaugă `get_trained_model()` la `Protocol LearningAlgorithm` (după `describe()`) |
| 2 | `learning_core/algorithms/xgboost_v1.py` | `def get_trained_model(self): return self._engine.model if self._engine.is_trained else None` |
| 3 | `learning_core/algorithms/production_champion.py` | `def get_trained_model(self): return None` (fit() e no-op, niciodată model real) |
| 4 | `learning_core/algorithms/league_weights_adaptive.py` | `def get_trained_model(self): return None` (ADR-028 — nu participă la Challenger Framework) |
| 5 | `learning_core/continuous_learning.py` | (a) adaugă `model_artifact_storage` la importurile de la nivel de modul din `learning_core`; (b) `_phase_b_train_new()` — inserează pasul de persistare între `ar.complete_run(train_run_id, ...)` (existent) și `challenger_manager.create_challenger(...)` (existent) — vezi §2.1 |
| 6 | `docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md` | Amendament §3, text exact din ADR-048 §7 |

### 2.1 Diff conceptual — `_phase_b_train_new()`

```python
    ar.complete_run(train_run_id, summary={
        "training_run_id": report.result.training_run_id,
        "samples_used": report.result.samples_used,
    })

    # --- NOU: persistare artefact, D2/D3 (ADR-048) ---
    persist_run_id = ar.write_run(PRODUCER, "artifact_persistence", "T2", target_key=target_key)
    if persist_run_id is None:
        return
    ar.start_run(persist_run_id)

    model = algorithm.get_trained_model()
    if model is None:
        ar.fail_run(persist_run_id, "MODEL_NOT_AVAILABLE: algoritmul nu a produs un model persistabil deși status=='trained'")
        return  # D3 — Challenger NU se creează

    try:
        artifact_path: str | None = model_artifact_storage.save_model_artifact(model, report.result.training_run_id)
    except Exception as exc:
        # De ce prindem Exception generic aici (întrebare așteptată la review):
        # save_model_artifact() e documentată best-effort și nu ridică azi
        # nicio excepție (vezi model_artifact_storage.py) — dar INV-1/D3
        # (ADR-048 §5) impun ca un Challenger să nu fie NICIODATĂ creat fără
        # artefact confirmat, indiferent de implementarea internă a
        # modulului de storage, azi sau după o refactorizare viitoare. Dacă
        # acel modul ar începe vreodată să ridice excepții (schimbare de
        # implementare, nu de contract), acest bloc garantează că D3 tot se
        # respectă — excepția e tratată identic cu artifact_path is None,
        # nu propagată mai departe, nu lasă Challenger-ul să se creeze.
        artifact_path = None
        logger.error("[ContinuousLearning] save_model_artifact a ridicat excepție neașteptată: %s", exc)

    if artifact_path is None:
        ar.fail_run(persist_run_id, "STORAGE_FAILURE: save_model_artifact a eșuat sau a ridicat excepție")
        return  # D3 — Challenger NU se creează

    ar.complete_run(persist_run_id, summary={"result": "SUCCESS", "artifact_path": artifact_path})
    # --- sfârșit bloc nou ---

    try:
        challenger_manager.create_challenger(report.result.training_run_id, family, league)
        challenger_manager.transition(report.result.training_run_id, "WAITING")
        challenger_manager.transition(report.result.training_run_id, "EVALUATING")
    except challenger_manager.ChallengerManagerError as exc:
        logger.error(
            "[ContinuousLearning] crearea/tranzitia Challenger-ului a esuat pentru %s: %s",
            report.result.training_run_id, exc,
        )  # neschimbat — artefactul rămâne orfan în Storage, acceptat (ADR-048 §4.1, rândul 2)
```

**Tip de retur al `save_model_artifact()`, fixat explicit** (observație acceptată): contractul deja existent al funcției (`model_artifact_storage.py`, neatins de acest plan) e `str | None` — calea de storage la succes, `None` la orice eșec. Acest plan **nu introduce niciun caz nou** de retur (ex. un dict cu metadate suplimentare precum `checksum`) — dacă o extensie viitoare ar avea nevoie de mai mult decât o cale, asta ar fi o schimbare de contract a `model_artifact_storage.py` însuși, cu propriul review, nu o decizie luată tacit aici. Orchestratorul (§2.1) presupune explicit `str | None`, nu un tip mai bogat.

**Coduri de rezultat pentru pasul `artifact_persistence`** (observație acceptată — documentate explicit, nu doar mesaje libere): `summary`/`error_detail` din Activity Recorder folosesc un prefix identificabil, pentru observabilitate directă în interogări/dashboard, fără parsare de text liber:

| Cod | Când | Metodă AR |
|---|---|---|
| `SUCCESS` | `save_model_artifact()` a întors o cale validă | `ar.complete_run(..., summary={"result": "SUCCESS", ...})` |
| `MODEL_NOT_AVAILABLE` | `algorithm.get_trained_model()` a întors `None` deși `status == "trained"` | `ar.fail_run(..., "MODEL_NOT_AVAILABLE: ...")` |
| `STORAGE_FAILURE` | `save_model_artifact()` a întors `None` SAU a ridicat excepție | `ar.fail_run(..., "STORAGE_FAILURE: ...")` |

Restul funcției (`threshold_check`, decizia `should_train`) rămâne neschimbat.

## 3. Impact asupra testelor

| Fișier | Teste noi/extinse |
|---|---|
| `tests/test_learning_core_xgboost_adapter.py` | `get_trained_model()` → `None` înainte de `fit()`; → obiectul model (mock) după `fit()` reușit; **apelat de două ori consecutiv, fără un `fit()` nou între ele, întoarce aceeași instanță** (`is`, identitate — nu doar egalitate structurală), verificând explicit contractul de viață din §1 |
| `tests/test_learning_core_production_champion.py` | `get_trained_model()` → `None`, necondiționat |
| `tests/test_league_weights_adaptive.py` | `get_trained_model()` → `None`, necondiționat |
| `tests/test_continuous_learning.py` | (a) cale fericită: `save_model_artifact` mock-uit succes → `create_challenger` apelat cu `training_run_id` corect; (b) cale eșec — model lipsă: `get_trained_model` mock-uit `None` → `create_challenger` NU apelat (`assert_not_called`), rezultat `MODEL_NOT_AVAILABLE`; (c) cale eșec — persistare: `save_model_artifact` mock-uit `None` (și, separat, mock-uit să ridice excepție) → `create_challenger` NU apelat, rezultat `STORAGE_FAILURE`; (d) verificare că runul `artifact_persistence` apare `fail_run`-uit în cazurile (b)/(c) cu codul corect; (e) **persistare reușită + `create_challenger` ridică `ChallengerManagerError`** (Failure Matrix, ADR-048 §4.1 rândul 2) — `save_model_artifact` mock-uit succes, `create_challenger` mock-uit să ridice excepție → verificare: runul `artifact_persistence` rămâne `SUCCESS` (nu se retrage retroactiv), niciun Challenger nu există (`get_active_challenger`/`create_challenger` a eșuat), funcția se întoarce curat, fără propagarea excepției către apelant |

Toate mock-uite, fără rețea/Supabase live — consistent cu suita existentă. Niciun test existent nu ar trebui să se rupă: `_phase_b_train_new()`-urile testate azi (linia 251 comentariu „la run_training() -> create_challenger()") vor avea nevoie de mock suplimentar pe `save_model_artifact`/`get_trained_model` ca să treacă de noul pas — acestea sunt actualizări, nu rescrieri.

## 4. Ordinea implementării

1. `model_registry.py` — extindere protocol (fără efect funcțional până nu e implementat de adaptoare).
2. Cei 3 adaptoare (`xgboost_v1.py`, `production_champion.py`, `league_weights_adaptive.py`) — implementare `get_trained_model()`, câte un commit logic sau toate 3 împreună (schimbare mică, simetrică).
3. Teste pentru pasul 1-2 (`test_learning_core_xgboost_adapter.py`, `test_learning_core_production_champion.py`, `test_league_weights_adaptive.py`) — verificare izolată, înainte de a atinge Orchestratorul.
4. `continuous_learning.py` — wiring-ul din §2.1.
5. Teste pentru pasul 4 (`test_continuous_learning.py`) — cele 4 cazuri din §3.
6. `MODEL_ARTIFACT_STORAGE_CONTRACT.md` — amendament (doc-only, poate fi oricând în secvență, dar logic ultimul, după ce codul reflectă deja realitatea descrisă).
7. `pytest tests/` complet — regresie.

Motivul ordinii: fiecare pas e verificabil izolat înainte de a trece la următorul (protocol → adaptoare → Orchestrator), consistent cu disciplina „un pas, o verificare" a EPIC-ului.

## 5. Domeniul de propagare a `artifact_path`

Observație acceptată — consemnată explicit, nu decisă tacit. La acest pas, `artifact_path` (întors de `save_model_artifact()`) e folosit **exclusiv** ca metadată de observabilitate în Activity Recorder (`summary={"result": "SUCCESS", "artifact_path": artifact_path}`) — nu e propagat mai departe, nu e scris pe rândul `challengers` (care nu are o coloană pentru asta azi), nu e transportat către `promotion_service`/`champion_loader` (ambele derivă calea artefactului din `training_run_id` prin `_artifact_path()`, nu au nevoie de el explicit).

**Declarat explicit: `artifact_path` din `summary` NU face parte din contractul dintre componente** — e informație de diagnostic/observabilitate, citibilă de un operator uman care inspectează Activity Recorder, nu o valoare pe care vreun modul viitor are voie s-o citească din `summary` și s-o trateze ca sursă de adevăr (sursa de adevăr rămâne `_artifact_path(training_run_id)`, derivată determinist, nu stocată). Orice cod viitor care ar avea nevoie de calea artefactului trebuie s-o deriveze din `training_run_id`, nu s-o extragă din `summary`-ul unui run istoric.

**Nu se introduce, în acest plan, nicio propagare suplimentară.** Dacă apare vreodată o nevoie reală (ex. afișarea căii exacte în UI de diagnostic), asta e o extensie separată, cu propriul review — nu se anticipează aici (consecvent cu „nu construim infrastructură pentru viitor").

## 6. Criterii de validare

- `pytest tests/` verde, inclusiv testele noi din §3.
- Verificare funcțională manuală (fără trafic live real, dat fiind că nu există azi Champion/Challenger real): apel direct `XGBoostV1Algorithm().get_trained_model()` înainte/după `fit()` pe date de test, confirmare vizuală a obiectului întors.
- Verificare AST/grep: `training_runner.py` și `challenger_manager.py` rămân neatinse (D1) — verificabil prin `git diff --stat`, nu doar promisiune.
- Regresie asupra `_resolve_champion()`/`evaluate_match()` — Predictor Regression Suite, ca să confirme zero impact asupra servirii live (deja garantat de faptul că `champion_loader.py` nu e atins, dar verificat explicit).

## 7. Criterii de rollback

Identice cu ADR-048 §12: `git revert` pe commit-ul de implementare, trivial — nicio migrare SQL, niciun rând de date modificat retroactiv. Artefacte deja scrise în bucket (dacă implementarea a rulat live înainte de revert) rămân, cost de stocare acceptat, fără GC (gol cunoscut, neschimbat).

**Declanșator de rollback**: orice eșec la §6 neexplicabil ca parte așteptată a schimbării.

---

**Status**: propus, în așteptarea aprobării. Implementarea Pasului 9 începe după aprobarea acestui plan.
