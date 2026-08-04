# ADR-048 — Ownership și moment de persistare a artefactului de model (`save_model_artifact()`)

**Status**: **PROPUS (v3)** — în așteptarea aprobării explicite a proprietarului produsului. Revizuit 2026-08-04 (a doua rundă): separare strictă normativ/implementare (§8, Anexa A), analiză explicită de atomicitate cu Failure Matrix (§4), invariant reformulat ca regulă de sistem (§5), clarificare explicită `artifact_dead` (§5), tabel de impact separat pe normativ vs. sugestie de implementare (§9).

**Data**: 2026-08-04

**Context declanșator**: EPIC „ML Activation & Oracle Evolution", Pasul 9 (`docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §3.1/§6.3 pasul 9). Planul cerea explicit ca ADR-ul „să clarifice explicit scopul: dacă persistența acoperă doar calea Champion (încărcare la boot), sau și artefactele intermediare de Challenger pe durata evaluării FSM".

---

## 1. Problema (recap din audit)

`learning_core/model_artifact_storage.py::save_model_artifact()` are zero apelanți în producție (grep exhaustiv — singurele apeluri sunt din propriul test). Efect: `champion_loader.load_champion_or_none()` întoarce mereu `None`, `oracle_engine._initialize_ml()` reantrenează efemer la fiecare pornire de proces, iar `promotion_service._validate_artifact()`/`challenger_shadow.predict_with_challenger()` — ambele deja scrise și funcționale — eșuează mereu în producție azi, fiindcă niciun artefact nu există vreodată la calea pe care o citesc.

## 2. Investigație — dovezi de cod

### 2.1 Contract deja documentat, ownership explicit

`docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md` §3 (scris la închiderea Pasului 1 al Learning Core, **înainte** ca Challenger FSM-ul real să fi fost implementat prin ADR-016/ADR-030):

> „Owner-ul persistenței Model Artifact este Challenger Manager... **Training Runner nu scrie niciodată artefacte.**... invocat, conform contractului Learning Orchestrator deja înghețat, exclusiv prin Orchestrator — niciodată component-la-component direct."

### 2.2 FSM-ul real, implementat ulterior, nu are un pas `compare()` înainte de creare

Contractul din 2.1 descrie fluxul intenționat ca `train() → compare() → DACĂ îmbunătățire simultană → persist() → devine Challenger`. Verificat direct în `continuous_learning._phase_b_train_new()` (implementat ulterior, prin ADR-030): fluxul real e `run_training()` reușit → `challenger_manager.create_challenger()` → tranziție directă `WAITING` → `EVALUATING`, fără nicio comparație intermediară. Comparația reală (verdict statistic) se întâmplă **după**, în `_phase_a_monitor_existing()`, pe baza traficului live acumulat în `shadow_predictions`.

### 2.3 Dovadă directă că artefactul trebuie să existe din chiar momentul creării Challenger-ului

`learning_core/challenger_shadow.py::predict_with_challenger()` — apelat din `oracle_engine._log_challenger_shadow()` la fiecare predicție live servită, cât timp există un Challenger activ — face:

```python
model = model_artifact_storage.load_model_artifact(training_run_id)
if model is None:
    return None
```

Dacă artefactul nu există din momentul `EVALUATING`, shadow logging-ul e mort de la prima predicție — Challenger-ul acumulează zero rânduri utile în `shadow_predictions`, `evaluate_active_challenger()` nu ajunge niciodată la un verdict, Challenger-ul rămâne blocat la nesfârșit.

**Răspuns la întrebarea pusă de plan**: nu există o distincție reală „artefact Champion" vs. „artefact Challenger intermediar" — e un singur artefact, per `training_run_id`, citit identic de trei consumatori (`champion_loader`, `challenger_shadow`, `promotion_service`). Trebuie să existe din momentul în care Challenger-ul intră în `EVALUATING`.

### 2.4 Precedent existent — ADR-028

`learning_core/algorithms/league_weights_adaptive.py` documentează deja, pentru un caz vecin, aceeași concluzie despre lanțul `challenger_shadow → model_artifact_storage → promotion_service/champion_loader`: e construit explicit peste `XGBClassifier.save_model()/.load_model()/.predict_proba()`, iar generalizarea lui pentru algoritmi non-artifact ar necesita un ADR dedicat. Acest ADR nu extinde acel scop.

---

## 3. Decizia arhitecturală — CE și DE CE (nu CUM)

**D1 — Ownership**: apelul către `save_model_artifact()` se face **exclusiv din Orchestrator** (`learning_core/continuous_learning.py`, Faza B). Niciodată din `training_runner.py`. Niciodată din `challenger_manager.py`.

**D2 — Moment**: persistarea se face **imediat după o antrenare reușită, înainte de crearea Challenger-ului** (`challenger_manager.create_challenger()`) — nu lazy, nu la promovare.

**D3 — Comportament la eșec**: dacă persistarea eșuează, **Challenger-ul nu se creează deloc**. Nu există o cale de creare-apoi-respingere pentru acest caz.

Acestea sunt cele trei decizii normative ale acestui ADR. Mecanismul concret prin care Orchestratorul obține referința la modelul antrenat, formatul mesajelor de eroare, numele pasului din Activity Recorder — toate sunt detalii de implementare, tratate separat (§8, Anexa A), nu parte a deciziei.

### 3.1 De ce Orchestrator și nu `challenger_manager.py`

- `challenger_manager.py` își declară explicit, în propriul header, un scop unic: „Singurul modul care scrie în tabela `challengers`... Introduce DOAR starea și tranzițiile unui Challenger... Nu implementează Shadow Evaluation, Promotion, sau citirea Champion/Runtime — nimic altceva." A adăuga acolo un apel către Supabase Storage ar introduce o a doua responsabilitate, contrazicând acest scop declarat.
- Contractul deja existent (§2.1) cere explicit ca orice invocare de acest tip să treacă „exclusiv prin Orchestrator — niciodată component-la-component direct". `continuous_learning.py` e singurul modul care azi orchestrează deja `training_runner` + `challenger_manager` + `promotion_service` + `rollback_service` + `champion_guardian` în aceeași secvență — e locul firesc, nu unul nou introdus.
- Filosofii de eșec incompatibile: `challenger_manager.py` RIDICĂ excepție la orice eșec („o tranziție care nu se poate confirma nu trebuie niciodată raportată drept succes tăcut"); `model_artifact_storage.py` e explicit best-effort, degradare grațioasă, nu ridică niciodată excepție. Combinarea celor două filosofii într-un singur modul le-ar amesteca — Orchestratorul, care deja gestionează ambele tipare separat, e locul corect pentru a le secvenția fără a le contopi.
- Doar Orchestratorul are deja, într-un singur loc, atât `report.result.training_run_id` (din `training_runner`), cât și apelul următor către `challenger_manager.create_challenger()` — fără cuplaj nou între cele două module.

### 3.2 De ce persistarea e înainte de `create_challenger()`, nu după

Justificare narativă mai jos; analiza formală, exhaustivă, e în §4 (Failure Matrix).

Cele două operații (`upload artefact`, `create_challenger`) rulează pe două sisteme eterogene (Supabase Storage, Postgres) — **nu există o tranzacție care să le lege**, deci ordinea în care rulează determină ce fel de stare inconsistentă e posibilă la eșec parțial. Alegerea nu elimină posibilitatea unui eșec parțial (imposibil fără tranzacție distribuită) — alege deliberat care dintre cele două tipuri de inconsistență posibilă e acceptabilă.

## 4. Analiza atomicității — Failure Matrix

Nu există tranzacție între Supabase Storage (`upload`) și Postgres (`create_challenger`, protejat de `idx_challengers_active_unique`) — cele două operații pot reuși/eșua independent. Tabelul de mai jos enumeră exhaustiv combinațiile posibile, pentru ambele ordini posibile.

### 4.1 Ordinea aleasă (D2): `upload` → `create_challenger`

| # | `upload` | `create_challenger` (încercat doar dacă `upload` a reușit) | Stare rezultată | Entitate invalidă? | Acceptat? |
|---|---|---|---|---|---|
| 1 | ✅ reușește | ✅ reușește | Artefact + Challenger, ambele există, consistente | Nu | ✅ Cale fericită |
| 2 | ✅ reușește | ❌ eșuează (cursă pe indexul unic, Postgres indisponibil, proces omorât înainte de a încerca) | Artefact orfan în Storage; niciun rând `challengers` | Nu — doar cost de stocare, izolat | ✅ Acceptat — GC-ul artefactelor orfane e deja gol cunoscut (`MODEL_ARTIFACT_STORAGE_CONTRACT.md` §4, neschimbat); ciclul următor reîncearcă antrenarea de la zero |
| 3 | ❌ eșuează | (nu se încearcă, per D3) | Niciun artefact, niciun Challenger | Nu | ✅ Acceptat — reîncercare idempotentă la ciclul următor |

**Zero combinații produc o entitate invalidă vizibilă restului sistemului.**

### 4.2 Ordinea respinsă (alternativă): `create_challenger` → `upload`

| # | `create_challenger` | `upload` (încercat doar dacă `create_challenger` a reușit) | Stare rezultată | Entitate invalidă? | Acceptat? |
|---|---|---|---|---|---|
| 1 | ✅ reușește | ✅ reușește | Artefact + Challenger, ambele există | Nu | Echivalent cu cazul fericit, dar... |
| 2 | ✅ reușește | ❌ eșuează (timeout de rețea la upload, proces omorât după creare) | **Rând `challengers` real, activ, FĂRĂ artefact corespunzător** | **Da — Challenger „fantomă"** | ❌ **Respins** |
| 3 | ❌ eșuează | (nu se încearcă) | Niciun artefact, niciun Challenger | Nu | Moot — ordinea e oricum respinsă |

Rândul 2 e motivul respingerii: un Challenger „fantomă" ocupă singurul slot activ permis per `(algorithm_family, league_scope)` (`idx_challengers_active_unique`), e interogat de fiecare predicție live (`get_active_challenger()`), eșuează silențios la fiecare shadow log, și blochează orice antrenare nouă până la intervenție manuală — un defect vizibil, activ, cu efecte în restul sistemului. Comparativ, rândul 2 din §4.1 (artefact orfan) e complet izolat, fără efecte asupra vreunui alt component.

**Concluzie**: ordinea din D2 e aleasă fiindcă elimină complet singura combinație care produce o entitate invalidă — nu fiindcă ar realiza o atomicitate reală (imposibilă între cele două sisteme), ci fiindcă alege deliberat care parte a eșecului parțial rămâne izolată vs. care ar deveni vizibilă.

## 5. Invariantul de sistem — INV-1

> **INV-1**: The system SHALL never create a Challenger (`challenger_manager.create_challenger()`) unless its corresponding model artifact has already been successfully persisted in `model-artifacts`.
>
> Echivalent, în română, pentru restul documentației proiectului: **Sistemul nu creează niciodată un Challenger fără ca artefactul lui de model să fi fost deja persistat cu succes.**

Acesta e regula de sistem impusă de D2+D3 împreună — nu doar o proprietate observată, ci comportamentul obligatoriu al Orchestratorului. Limite explicite ale garanției (nu ascunse):

- **Mecanism de garantare**: ordinea de execuție a Orchestratorului (§4.1) — NU o constrângere la nivel de bază de date. Nu există, și acest ADR nu introduce, o cheie străină/trigger care să lege Postgres de Supabase Storage — cele două sisteme sunt eterogene, nu pot fi legate printr-o constrângere relațională. INV-1 e o garanție de proces, nu de schemă.
- **Acoperă crearea, nu persistența la nesfârșit**: INV-1 garantează starea la momentul `create_challenger()`. Nu garantează că artefactul rămâne accesibil ulterior (ex. o ștergere manuală din bucket, în afara acestui flux, ar rupe invariantul retroactiv, pentru un Challenger deja existent).
- **`artifact_dead` (motiv de respingere deja definit în `challenger_manager.VALID_REJECTION_REASONS`) rămâne rezervat exclusiv pentru degradarea ulterioară a unui artefact care exista la momentul creării** (ex. ștergere manuală din bucket, corupere descoperită ulterior) — **NU pentru eșecul persistării inițiale**. Eșecul persistării inițiale e acoperit direct de INV-1: Challenger-ul pur și simplu nu ajunge să existe, nu există o stare `CREATED`/`WAITING` de respins ulterior cu acest motiv. Conectarea reală a `artifact_dead` la un flux de detecție a degradării ulterioare rămâne, ca și înainte, în afara scopului acestui ADR (§14).
- **Nu se aplică retroactiv**: nu există azi niciun Challenger real (`model_champions`/`challengers` conțin exclusiv rânduri `gate_validation_test`, per `ARCHITECTURE_STATE.md` §4) — INV-1 nu necesită backfill.

## 6. Alternative analizate și respinse

### 6.1 Persistare în `training_runner.py`

**De ce nu**: (a) interzis explicit de contractul deja existent (§2.1); (b) `run_training()` e apelat și de CLI-ul manual (`train.py`), pentru rulări explicit ephemere, de inspecție, niciodată menite să devină Challenger — persistarea necondiționată acolo ar începe să scrie în Storage la fiecare rulare manuală, o extindere de comportament nedorită, în afara scopului Pasului 9; (c) `training_runner.py` nu are, și nu ar trebui să capete, vizibilitate asupra faptului că o antrenare anume va deveni sau nu Challenger — acea decizie aparține Orchestratorului, nu executorului antrenării.

### 6.2 Persistare în `challenger_manager.py`

**De ce nu**: detaliat în §3.1 — ar contrazice scopul declarat explicit al modulului (strict FSM bookkeeping) și ar amesteca două filosofii de eșec incompatibile (fail-fast cu excepție vs. best-effort degradat).

### 6.3 Persistare lazy, la primul shadow prediction

Ideea: `save_model_artifact()` s-ar apela abia când `challenger_shadow.predict_with_challenger()` are nevoie de model prima dată, nu proactiv la creare.

**De ce nu**:
- Modelul antrenat există doar **în memoria procesului** care a rulat `fit()` — de regulă un run GitHub Actions efemer. Când acel proces se închide, modelul dispare. O persistare lazy declanșată de o predicție live (proces Streamlit complet separat) nu ar avea de unde să obțină modelul de persistat — ar necesita fie păstrarea lui în afara procesului de antrenare, fie re-antrenare on-demand în calea de servire live.
- Re-antrenare on-demand în calea de servire live ar încălca North Star #1 (producția nu e niciodată afectată de un experiment activ) și North Star #10 (nicio dependință „în sus") — ar face latența unei predicții live dependentă de antrenarea unui model ML.
- `_log_challenger_shadow()` se auto-documentează explicit ca „zero impact asupra producției" — o operație lentă, blocantă (upload de model) în calea asta ar contrazice chiar design-ul deja scris al funcției.

### 6.4 Persistare la promovare

Ideea: artefactul se salvează abia când `promotion_service.promote_challenger()` e apelat, nu la crearea Challenger-ului.

**De ce nu**: auto-contradictoriu. Promovarea depinde de un verdict `candidate_for_promotion`, care depinde de `evaluate_active_challenger()`, care depinde de rânduri acumulate în `shadow_predictions`, care depind de `predict_with_challenger()` reușind pe parcursul întregii ferestre de evaluare — adică exact perioada DINAINTE de promovare. Dacă artefactul nu există decât la promovare, Challenger-ul nu poate produce niciodată shadow predictions valide, deci nu poate ajunge niciodată la verdictul care ar declanșa promovarea. `promotion_service._validate_artifact()` e deja scris ca o **re-validare** a unui artefact presupus existent, nu ca un producător — confirmă că designul deja implementat presupune persistare anterioară promovării.

## 7. Amendament la `docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md`

**Nu e o corectare de eroare.** Contractul original (§2.1) a fost scris la închiderea Pasului 1 al Learning Core, **înainte** ca Challenger FSM-ul (ADR-016) și Orchestratorul (ADR-030) să fi fost efectiv implementate — descria un design intenționat, la momentul respectiv corect ca intenție, pentru o arhitectură care încă nu exista în cod. Implementarea ulterioară a FSM-ului a evoluat diferit: fără un pas `compare()` separat înainte de creare, cu evaluarea mutată după creare, pe trafic live. Acest ADR nu declară contractul original „greșit" — declară că arhitectura efectiv construită a divergut de designul inițial, lucru normal într-un proiect care evoluează incremental, și amendează contractul cu autoritatea unui ADR nou (cerută explicit de propriul text al contractului) ca să reflecte arhitectura reală, nu una ipotetică.

Textul de înlocuit la §3 din `MODEL_ARTIFACT_STORAGE_CONTRACT.md`:

> Înlocuiește descrierea `train() → compare() → DACĂ îmbunătățire simultană → persist() → devine Challenger` cu: „Persistarea are loc imediat după o antrenare reușită (`status == 'trained'`), ca parte a `continuous_learning._phase_b_train_new()` (Faza B, Orchestrator), înainte de `challenger_manager.create_challenger()` (D2, ADR-048) — nu există un pas de comparație separat înainte de creare; comparația reală (verdict statistic) are loc ulterior, pe durata stării `EVALUATING`, pe baza traficului live acumulat în `shadow_predictions`. Vezi ADR-048 pentru justificarea completă, Failure Matrix-ul (§4) și invariantul de sistem INV-1 (§5) garantate de această ordine."

Restul contractului (§1 format, §2 naming convention, §4 GC, §5 atomicitate locală) rămâne neschimbat.

## 8. Acces la modelul antrenat — cerință normativă minimă

**Normativ**: Orchestratorul trebuie să poată obține modelul antrenat, imediat după o antrenare reușită, pentru a-l transmite lui `save_model_artifact()`. Azi, `TrainingRunResult`/`RunReport` (întors de `run_training()`) nu conțin acest obiect — doar metadate.

**Mecanismul concret prin care se obține acest acces e o decizie de implementare, nu normativă** — vezi Anexa A pentru o propunere și alternativele luate în considerare. Orice mecanism e conform cu acest ADR atâta timp cât respectă D1 (doar Orchestratorul cheamă `save_model_artifact()`) și D2 (înainte de `create_challenger()`).

---

## 9. Impact asupra componentelor

### 9.1 Normativ (impus direct de acest ADR — D1/D2/D3/INV-1)

| Componentă | Ce anume, la nivel normativ |
|---|---|
| `learning_core/continuous_learning.py` | `_phase_b_train_new()` TREBUIE să apeleze `save_model_artifact()` înainte de `create_challenger()`; la eșec de persistare, `create_challenger()` NU TREBUIE apelat (D1, D2, D3) |
| `training_runner.py`, `train.py` (CLI) | TREBUIE să rămână neatinse — interzis explicit să apeleze `save_model_artifact()` (D1) |
| `challenger_manager.py` | TREBUIE să rămână neatins — interzis explicit să apeleze `save_model_artifact()` (D1); `artifact_dead` rămâne rezervat exclusiv pentru degradare ulterioară, nu pentru eșecul persistării inițiale (§5) |
| `docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md` | Amendament §3 (§7) |
| `tests/test_continuous_learning.py` | TREBUIE să acopere ambele căi ale INV-1: persistare reușită → `create_challenger` apelat; persistare eșuată → `create_challenger` NU e apelat (forma exactă a testului nu e normativă) |

### 9.2 Sugestie de implementare (NU impusă de acest ADR — poate varia fără ADR nou)

| Componentă | Ce anume |
|---|---|
| `learning_core/model_registry.py` + adaptoare | Mecanismul concret de expunere a modelului antrenat către Orchestrator — vezi Anexa A |
| `promotion_service.py`, `champion_loader.py`, `challenger_shadow.py` | Neatinse — deja scrise corect, așteaptă doar ca artefactul să existe; nicio schimbare necesară sau propusă |
| `model_artifact_storage.py` | Neatins — funcția există deja, corect |

## 10. Ce NU se schimbă

- Formatul artefactului, naming convention-ul căii de Storage, politica de GC — neatinse (§1/§2/§4 din contract).
- `training_runner.py`/`train.py` (CLI manual) — comportament identic cu azi (§6.1).
- `participates_in_challenger_framework = False` (`league_weights_adaptive`) — neatins (ADR-028).
- Niciun flag nou activat implicit (North Star #3) — `learning_core_enabled` rămâne singurul comutator.
- `artifact_dead` — rămâne definit, cu scopul lui clarificat explicit (§5), neconectat la niciun flux nou.

## 11. Strategie de testare/validare

- Teste noi, izolate (mock-uite, fără rețea/Supabase live): cale fericită (persistare reușită → `create_challenger` apelat cu `training_run_id` corect) și cale de eșec (persistare eșuată → `create_challenger` NU e apelat deloc, assert explicit `not called`) — acoperă direct INV-1.
- Regresie completă `pytest tests/` — verificare că servirea live (`_resolve_champion()`) nu e afectată.
- Nu există azi un Champion/Challenger real în producție (doar `gate_validation_test`) — validarea end-to-end pe date reale rămâne condiționată de trafic live suficient, gol deja documentat (`ARCHITECTURE_STATE.md` §5), neschimbat de acest ADR.

## 12. Strategie de rollback

- **Cod**: `git revert` — trivial, nicio migrare SQL implicată.
- **Date**: niciun rând existent modificat retroactiv — doar comportamentul viitor al `_phase_b_train_new()`.
- **Storage**: artefacte deja scrise rămân (fără GC, gol acceptat, neschimbat) — cost de stocare, nu problemă de corectitudine.
- **Criteriu de declanșare**: orice regresie la `pytest tests/` sau la verificarea funcțională a `_resolve_champion()`/`evaluate_match()` neexplicabilă ca parte așteptată a schimbării.

## 13. Decizie

Se aprobă (dacă concluziile de mai sus sunt acceptate):

1. **D1** — Ownership: apelul se face exclusiv din `continuous_learning.py` (Orchestrator, Faza B).
2. **D2** — Moment: imediat după antrenare reușită, înainte de `create_challenger()`.
3. **D3** — Eșec: Challenger-ul nu se creează deloc.
4. **INV-1** — regulă de sistem (§5), cu limitele ei explicite și clarificarea `artifact_dead`.
5. Amendament la `MODEL_ARTIFACT_STORAGE_CONTRACT.md` §3 (§7), ca evoluție de arhitectură, nu corectare de eroare.
6. §8/Anexa A (mecanismul exact de acces la model) rămâne detaliu de implementare — poate fi decis la codare, fără ADR separat, cât timp respectă D1-D3.

**Status**: în așteptarea aprobării explicite. Implementarea NU începe înainte de aprobare.

## 14. Out of Scope

- Politica de Garbage Collection pentru artefacte orfane/respinse — gol cunoscut, acceptat, deferată.
- Verificare explicită de versiune XGBoost la load — gol cunoscut, acceptat, neschimbat.
- Conectarea `artifact_dead` la un flux real de detecție a degradării ulterioare — nu face parte din acest ADR.
- Generalizarea persistenței pentru algoritmi non-XGBoost — respinsă explicit, per ADR-028.
- Pașii 10-14 ai EPIC-ului — blocați tehnic de acest ADR, dar nu fac parte din scopul lui.

---

## Anexa A — Posibilă implementare (NEnormativă, informativă)

Nimic din această anexă nu face parte din decizia aprobată prin acest ADR (§13). E inclusă doar ca reper pentru sesiunea de implementare, poate fi înlocuită integral fără a necesita un nou ADR, atât timp cât rezultatul respectă D1-D3.

Orchestratorul are nevoie de o referință către modelul antrenat, ca să-l poată transmite lui `save_model_artifact(model, training_run_id)`.

**O variantă posibilă**: extinderea protocolului `LearningAlgorithm` cu o metodă `get_trained_model() -> Any | None`, implementată de cei 3 algoritmi înregistrați azi (`xgboost_v1` → modelul real; `production_champion`/`league_weights_adaptive` → `None`, consecvent cu ADR-028).

**Alte variante posibile, considerate, fără o preferință impusă de acest ADR**:

- Un câmp `model: Any | None` direct pe `TrainingRunResult`, transportat prin `RunReport` — evită o metodă nouă pe protocol, dar mixează un obiect greu (model antrenat) într-un dataclass altfel ușor, folosit și pentru afișare (`train.py` CLI îl printează integral) — risc de a printa/serializa accidental un obiect model uriaș dacă cineva extinde `_print_report()`.
- Un „ultimul model antrenat" ținut ca stare de `training_runner.py` (dict `{(name, version): model}`) — ar face din `training_runner.py` un deținător temporar de stare model, exact responsabilitatea pe care contractul (§2.1) o exclude azi — probabil cea mai slabă variantă dintre cele trei, dar menționată pentru completitudine.

Alegerea finală, între acestea sau altă variantă, se face la momentul implementării, fără a necesita revizuirea acestui ADR.
