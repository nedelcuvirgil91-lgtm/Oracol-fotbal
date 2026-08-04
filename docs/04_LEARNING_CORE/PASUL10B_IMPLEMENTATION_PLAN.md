# Pasul 10b — Implementation Plan (Champion serving live — wiring calibrare)

**Tip**: plan tehnic de execuție. NU e ADR — autoritatea de design rămâne `ADR-049` (ACCEPTED). Acest document decide exclusiv **cum** se propagă, la servire live, o decizie deja luată în Pasul 10a — nu redeschide nicio decizie arhitecturală, nu introduce niciun mecanism nou.

**Scop restrâns, confirmat explicit de proprietarul produsului**: exclusiv wiring-ul de servire live al calibrării deja antrenate și persistate în Pasul 10a. Cinci puncte, și doar acestea:

1. Încărcarea calibratorului în `champion_loader.py`.
2. Extinderea `ChampionLoadResult` cu câmpul `temperature`.
3. Propagarea temperaturii prin `oracle_engine.py` (`_resolve_champion()` → `seed_from_champion(...)`).
4. Validarea faptului că Champion-ul live servește probabilități calibrate atunci când calibratorul există.
5. Degradarea grațioasă la probabilități brute dacă artefactul de calibrare lipsește — exact cum stabilește ADR-049.

## Out of scope (explicit)

Acest plan **NU** modifică:

- **Algoritmul Temperature Scaling** — `_fit_temperature()`, `_softmax_with_temperature()` rămân exact cum au fost implementate și acceptate la Pasul 10a (`ml_predictor.py`, neatinse aici).
- **Formatul artefactelor** — `calibration_artifact_storage.py` (schema `{"temperature": T}`, validare `T>0` finit) rămâne neatins.
- **Politica de promovare Champion/Challenger** — `promotion_service.py` rămâne neatins (motivat în §2, rândul respectiv).
- **`model_artifact_storage.py`** — neatins.
- **Logica de antrenare** — `continuous_learning.py`, `training_runner.py`, `challenger_manager.py`, `challenger_shadow.py` rămân neatinse (wiring-ul lor pentru calibrare s-a închis deja la Pasul 10a).
- **`docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md`** (Frozen) — invariantul de utilizabilitate rămâne cu exact 6 condiții. Decizie deja confirmată explicit de proprietarul produsului înainte de Pasul 10a: calibrarea nu introduce o a 7-a condiție blocantă, fiindcă absența ei degradează grațios (Champion-ul rămâne utilizabil, servește probabilități brute), nu invalidează Champion-ul — vezi §1 mai jos pentru mecanismul exact.

## 1. Mecanismul ales (detalii de implementare, în limitele ADR-049 și ale deciziei RUNTIME_CONTRACT.md de mai sus)

- **Încărcare, nu re-validare**: `champion_loader.load_champion_or_none()` apelează `calibration_artifact_storage.load_calibration_artifact(training_run_id)` **după construirea modelului și după verificarea funcțională (`predict_proba` pe un probe zero) care stabilește utilizabilitatea Champion-ului** — adică după exact punctul din cod unde toate cele 6 condiții de utilizabilitate (`RUNTIME_CONTRACT.md`) sunt deja satisfăcute. Calibrarea nu participă la acea decizie, e strict o îmbogățire opțională a rezultatului deja decis.
- **Best-effort, simetric cu restul modulului**: `load_calibration_artifact()` (deja implementat, Pasul 10a) întoarce `None` — niciodată excepție — la orice eșec (artefact lipsă, corupt, `T` invalid, Supabase indisponibil). `champion_loader.py` nu adaugă niciun `try/except` suplimentar pentru acest apel — comportamentul e deja acoperit de `try/except Exception` existent, care înfășoară întreaga funcție.
- **Propagare, nu recalculare**: `oracle_engine._resolve_champion()` transmite `result.temperature` mai departe la `seed_from_champion(...)` — parametrul `temperature` există deja acolo din Pasul 10a (aditiv, opțional, implicit `None`), neapelat cu o valoare reală până acum. Acest plan e literalmente primul apelant real al acelui parametru.
- **Nicio schimbare în calea de predicție**: `MLPredictorEngine.predict()` deja ramifică pe `self.temperature is not None` (Pasul 10a) — dacă temperatura e propagată, calea calibrată se activează automat, fără nicio modificare suplimentară în `ml_predictor.py`.
- **Degradare grațioasă, nu gating**: dacă `load_calibration_artifact()` întoarce `None`, `ChampionLoadResult.temperature` e `None`, `seed_from_champion(..., temperature=None)` — exact comportamentul de azi (înainte de acest pas). Champion-ul tot se consideră utilizabil și servește; doar probabilitățile rămân brute, necalibrate, ca acum.

## 2. Modificări concrete pe fișiere

| # | Fișier | Modificare |
|---|---|---|
| 1 | `learning_core/champion_loader.py` | (a) `ChampionLoadResult` — câmp nou `temperature: float \| None`; (b) `load_champion_or_none()` — după validarea celor 6 condiții, apel la `calibration_artifact_storage.load_calibration_artifact(champion["training_run_id"])`, rezultat transmis direct în `ChampionLoadResult` — vezi §2.1 |
| 2 | `oracle_engine.py` | `_resolve_champion()` — un singur argument nou în apelul deja existent către `self.ml.seed_from_champion(...)`: `temperature=result.temperature` — vezi §2.2 |

**Neatinse, confirmat**: `ml_predictor.py`, `calibration_artifact_storage.py`, `model_artifact_storage.py`, `continuous_learning.py`, `challenger_shadow.py`, `challenger_manager.py`, `training_runner.py`, `promotion_service.py`, `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md`.

**De ce `promotion_service.py` rămâne neatins** (decizie explicită, nu omisiune): promovarea produce Champion-ul din care acest plan citește — nu creează nicio cerință nouă asupra procesului de promovare însuși. `_validate_artifact()` continuă să re-valideze exclusiv modelul, exact ca azi; calibrarea rămâne, ca și la Pasul 10a, garantată la existență prin gate-ul de creare a Challenger-ului (INV-1 extins), nu printr-o verificare suplimentară la promovare.

### 2.1 Diff conceptual — `champion_loader.py`

```python
@dataclass
class ChampionLoadResult:
    training_run_id: str
    model: Any
    samples_used: int
    algorithm_family: str
    algorithm_version: str
    league_scope: str
    accuracy: float | None
    log_loss: float | None
    trained_at: str | None
    # --- NOU, Pasul 10b ---
    temperature: float | None


def load_champion_or_none(algorithm_family: str, league_scope: str) -> ChampionLoadResult | None:
    try:
        ...
        # --- neschimbat: cele 6 condiții de utilizabilitate ---
        probe = np.zeros((1, len(FEATURE_COLUMNS)))
        model.predict_proba(probe)  # Condiția 5

        walk_forward_metrics = training_run.get("walk_forward_metrics") or {}

        # --- NOU: încărcare calibrare, DUPĂ decizia de utilizabilitate ---
        from learning_core import calibration_artifact_storage
        temperature = calibration_artifact_storage.load_calibration_artifact(champion["training_run_id"])

        return ChampionLoadResult(
            training_run_id=champion["training_run_id"],
            model=model,
            samples_used=training_run.get("samples_used", 0),
            algorithm_family=algorithm_family,
            algorithm_version=training_run.get("algorithm_version"),
            league_scope=league_scope,
            accuracy=walk_forward_metrics.get("accuracy"),
            log_loss=walk_forward_metrics.get("log_loss"),
            trained_at=training_run.get("created_at"),
            temperature=temperature,  # NOU — None dacă indisponibil, niciodată eroare
        )
    except Exception as exc:
        ...  # neschimbat
```

**Poziționare deliberată**: încărcarea calibrării stă strict DUPĂ proba de deserializare (Condiția 5), nu înainte și nu integrată în lanțul `if ... is None: return None` al celor 6 condiții — un eșec la încărcarea calibrării nu trebuie niciodată să scurtcircuiteze un Champion altfel valid.

### 2.2 Diff conceptual — `oracle_engine._resolve_champion()`

```python
    def _resolve_champion(self):
        try:
            from learning_core.champion_loader import load_champion_or_none
            from ml_predictor import _ALGORITHM_FAMILY, _LEAGUE_SCOPE

            result = load_champion_or_none(_ALGORITHM_FAMILY, _LEAGUE_SCOPE)
            if result is None:
                return None

            self.ml.seed_from_champion(
                result.model, result.samples_used,
                accuracy=result.accuracy, log_loss=result.log_loss, trained_at=result.trained_at,
                temperature=result.temperature,  # NOU, Pasul 10b — singura linie adăugată
            )
            return result
        except Exception as exc:
            ...  # neschimbat
```

Nicio altă linie din `_resolve_champion()`, din `_initialize_ml()`, sau din restul `oracle_engine.py` nu se schimbă.

## 3. Impact asupra testelor

| Fișier | Teste noi/extinse |
|---|---|
| `tests/test_champion_loader.py` | (a) calibrare disponibilă → `result.temperature` == valoarea din artefact; (b) calibrare absentă/`None` → `result.temperature is None`, Champion-ul TOT se consideră utilizabil (`result is not None`) — regresie explicită a degradării grațioase; (c) `test_module_has_single_known_importer` rămâne verde neschimbat (niciun importator nou al `champion_loader.py`) |
| `tests/test_champion_diagnostic_probe.py` | `_resolve_champion()` propagă `result.temperature` către `seed_from_champion(...)` — verificat direct pe argumentul transmis (mock/spy pe `self.ml.seed_from_champion`), atât pentru cazul cu valoare, cât și pentru `None` |
| Test de integrare end-to-end (nou, minimal) | Cu `champion_loader` mock-uit să întoarcă un `ChampionLoadResult` cu `temperature` setat, verifică că `FootballOracleEngine.ml.temperature` are exact acea valoare după `_initialize_ml()` — dovadă directă că firul complet (loader → resolve → seed → engine) funcționează, nu doar fiecare verigă izolat |

**Niciun test existent din Pasul 10a nu se modifică** — `ml_predictor.py`, `calibration_artifact_storage.py`, `continuous_learning.py`, `challenger_shadow.py` și suitele lor de teste rămân exact cum au fost lăsate la închiderea Pasului 10a.

## 4. Ordinea implementării

1. `champion_loader.py` — extinderea `ChampionLoadResult` + apelul de încărcare (§2.1), testabil izolat cu `calibration_artifact_storage.load_calibration_artifact` monkeypatch-uit.
2. Teste pentru pasul 1.
3. `oracle_engine.py` — propagarea argumentului (§2.2), o singură linie.
4. Teste pentru pasul 3 + testul de integrare end-to-end din §3.
5. `pytest tests/` complet — regresie, cu atenție specială la orice test existent care verifică semnătura exactă a apelului `seed_from_champion(...)` (ar putea necesita actualizare dacă folosește `assert_called_with` strict, nu `assert_called_with(..., **kwargs)` parțial).

## 5. Criterii de validare

- `pytest tests/` verde, inclusiv testele noi.
- **Verificare directă (nu presupusă)**: cu un Champion + calibrare mock-uite end-to-end, `FootballOracleEngine.ml.temperature` reflectă exact valoarea din artefact — dovedește că temperatura persistată e propagată integral până în `MLPredictorEngine`, activând mecanismul de calibrare deja implementat și testat la Pasul 10a (punctul 4 din scope). Corectitudinea matematică a calibrării în sine — că `softmax(margini/T)` produce probabilitățile corecte — rămâne responsabilitatea testelor din Pasul 10a (`tests/test_ml_temperature_calibration.py`), neduplicată aici.
- **Regresie explicită, obligatorie**: cu un Champion valid dar FĂRĂ calibrare (cazul de azi, până la acest pas), comportamentul rămâne identic cu cel dinainte de Pasul 10b — Champion-ul se încarcă, se consideră utilizabil, servește probabilități brute (`self.ml.temperature is None`) — dovedește punctul 5 din scope.
- Verificare AST/grep: `ml_predictor.py`, `calibration_artifact_storage.py`, `model_artifact_storage.py`, `continuous_learning.py`, `challenger_shadow.py`, `challenger_manager.py`, `training_runner.py`, `promotion_service.py`, `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` rămân neatinse — verificabil prin `git diff --stat`.
- `test_champion_loader.py::test_module_has_single_known_importer` rămâne verde — niciun import nou al `champion_loader.py` în afara `oracle_engine.py`.

## 6. Criterii de rollback

- **Cod**: `git revert` — trivial, nicio migrare SQL, nicio schimbare de schemă.
- **Date**: niciun rând existent modificat retroactiv; niciun artefact nou creat de acest pas (calibrarea deja există din Pasul 10a — acest pas doar o citește).
- **Comportament la rollback**: revenire imediată la starea Pasul 10a — Champion-ul continuă să servească probabilități brute, exact ca înainte de acest plan; niciun risc de servire a unor probabilități calibrate „pe jumătate" sau inconsistente, fiindcă schimbarea e strict aditivă (un parametru propagat, nicio ramură nouă de business logic în afara celei deja acceptate la Pasul 10a).
- **Declanșator**: orice eșec la §5 neexplicabil ca parte așteptată a schimbării, sau orice observație că `self.ml.temperature` diferă de artefactul persistat pentru Champion-ul activ (ar indica un bug de propagare, nu un comportament acceptat).

---

**Status**: **READY FOR IMPLEMENTATION** — 2026-08-04, de proprietarul produsului, după integrarea celor 2 clarificări de formulare cerute la review (fără impact asupra implementării): (1) §1, poziționarea exactă a încărcării calibrării în flux (după construirea modelului + verificarea funcțională `predict_proba`, nu doar „după cele 6 condiții"); (2) §5, precizarea că testul de integrare dovedește propagarea completă a temperaturii, nu corectitudinea matematică a calibrării în sine (deja acoperită de testele Pasului 10a). Implementarea Pasului 10b poate începe.
