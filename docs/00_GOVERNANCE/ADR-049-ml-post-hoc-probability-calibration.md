# ADR-049 — Calibrare post-hoc a probabilităților ML

**Status**: **ACCEPTED** — 2026-08-04, de proprietarul produsului, după integrarea a trei clarificări cerute la review: (1) verificarea explicită, empirică, a disponibilității marginilor brute (`output_margin=True`) în backend-ul XGBoost pinat de proiect — §2.4; (2) separarea explicită dintre decizia de arhitectură (acest ADR) și mecanismul de implementare prin care predicțiile out-of-fold ajung la calibrator — §5; (3) contractul semantic model↔calibrator ca unitate logică unică de inferență, identificată prin `training_run_id` — §7.

**Data**: 2026-08-04

**Context declanșator**: EPIC „ML Activation & Oracle Evolution", Pasul 10 (`docs/00_GOVERNANCE/ML_ACTIVATION_IMPLEMENTATION_PLAN.md` §3.2/§6.3 pasul 10). Precondiție satisfăcută: Pasul 9 (ADR-048 — persistență reală a artefactului de model) e închis (`main` @ `f2272b0`), neatins de acest document. Acest ADR e strict un document de design — decide **dacă** și **cum** ar arăta calibrarea, nu implementează, nu produce plan de implementare, nu propune cod.

---

## 1. Care e problema?

Confirmat empiric, nu presupus — `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md` §3.2, walk-forward, n=1250 predicții agregate din 5 folduri temporale (expanding window, `ml_predictor._walk_forward_validate()`):

| Interval încredere | n | Încredere medie (ML) | Acuratețe reală (ML) | Gap |
|---|---|---|---|---|
| [0.00, 0.40) | 55 | 0.376 | 0.327 | 4.9pp |
| [0.40, 0.50) | 274 | 0.456 | 0.401 | 5.5pp |
| [0.50, 0.60) | 327 | 0.549 | 0.434 | 11.5pp |
| [0.60, 0.70) | 227 | 0.647 | 0.476 | 17.1pp |
| **[0.70, 1.01)** | **367** | **0.821** | **0.578** | **24.3pp** |

Pentru comparație, Oracle (Poisson/ELO), pe același eșantion, are gap ≤6pp pe toate bin-urile — aproape perfect calibrat. XGBoost-ul (`xgboost_v1`) raportează sistematic mai multă încredere decât justifică acuratețea lui reală, agravat exact în zona de încredere mare (367/1250 = 29.4% din predicții, cea mai numeroasă categorie).

**De ce apare** (cauză, nu doar corelație — deja documentată în `ORACLE_VS_ML_REPORT.md` §5 și `ML_ENGINE_AUDIT.md`): fiecare fold de validare walk-forward antrenează de la zero pe un eșantion relativ mic per fold (primul fold: câteva sute de rânduri), condiție cunoscută ca predispusă la overfitting pentru gradient boosting cu 150 de estimatori (`n_estimators=150, max_depth=4`, `ml_predictor.py:263-268`/`355-365`). Modelul de producție însuși (antrenat pe *tot* istoricul disponibil, `model.fit(X, y)` fără set de validare reținut, `ml_predictor.py:366`) nu are niciun mecanism care să-i corecteze probabilitățile brute (`predict_proba()`, softmax peste `multi:softprob`) — ele ies direct din model, fără nicio funcție intermediară de recalibrare.

**De ce contează pentru arhitectura Champion/Challenger**: `promotion_service`/`shadow_testing.evaluate_experiment()` compară Brier/log-loss între Challenger și Champion pentru decizia de promovare (North Star #2 — dovadă statistică simultană pe metrici multiple). Brier și log-loss sunt ambele sensibile direct la calitatea calibrării, nu doar la acuratețea de clasificare (`argmax`) — un model supraîncrezut poate avea accuracy rezonabil dar Brier/log-loss vizibil mai slabe exact din cauza gap-ului de mai sus (confirmat: ML are Brier=0.6747 vs. Oracle=0.6150 pe același eșantion, deși accuracy diferă doar cu 1.68pp). O decizie de promovare bazată pe probabilități necalibrate riscă să respingă (sau să accepte greșit) un Challenger pe baza unui artefact matematic al supraadaptării, nu al calității reale a predicției.

**De ce probabilitățile brute XGBoost nu sunt suficiente**: `objective="multi:softprob"` produce o distribuție softmax peste marginile (logits) modelului — matematic o distribuție de probabilitate validă (sumă 1, valori în [0,1]), dar „calibrare" (probabilitatea raportată = frecvența reală observată) nu e o proprietate garantată de antrenarea prin minimizarea log-loss-ului pe setul de antrenare; e o proprietate separată, care trebuie verificată și, dacă lipsește, corectată explicit — exact ce demonstrează empiric tabelul de mai sus.

## 2. Alternative analizate

Patru opțiuni, evaluate pe: eficiență pe eșantion mic (dat fiind `MIN_SAMPLES_TO_TRAIN=30`, un prag deliberat de jos), compatibilitate cu ieșirea multi-clasă (3 clase: H/D/A), păstrarea ranking-ului/accuracy (argmax neschimbat), complexitate de persistare, potrivire cu cauza diagnosticată (supraîncredere sistematică, nu o formă complexă de miscalibrare).

### 2.1 Fără calibrare (status quo)

Respinsă ca opțiune finală, dar nu ca non-decizie — e baseline-ul față de care se măsoară celelalte 3. Argumentul „nu schimbăm nimic" ar fi valid DOAR dacă gap-ul de 24.3pp ar fi în limitele de zgomot statistic ale eșantionului (n=367) — nu e cazul: un interval de încredere binomial aproximativ pe acuratețea reală (0.578, n=367) dă o marjă de eroare de cca ±5pp la 95% — gap-ul de 24.3pp e de peste 4× mai mare decât zgomotul așteptat, deci real, nu artefact de eșantionare mică.

### 2.2 Platt Scaling (regresie logistică pe scorurile modelului)

Un singur parametru (sau doi, `A`/`B` din formula sigmoid clasică) învățat per clasă, prin regresie logistică pe scorurile brute vs. etichetele reale. Avantaj: eficient pe eșantion mic (proiectat inițial pentru SVM-uri, exact contextul „puține date de calibrare"), simplu de implementat și de persistat (2 scalari per clasă). Dezavantaj: presupune o formă sigmoidală a miscalibrării — nu întotdeauna potrivită, deși pentru gradient boosting cu supraîncredere sistematică (nu bimodală/neregulată) e de regulă o presupunere rezonabilă. Pentru 3 clase, necesită fie o extensie one-vs-rest (3 seturi de parametri, urmate de renormalizare), fie o formulare multinomială dedicată.

### 2.3 Isotonic Regression

Non-parametrică, complet flexibilă — nu presupune nicio formă funcțională a miscalibrării. Avantaj teoretic: poate corecta orice tip de miscalibrare monoton. Dezavantaj concret, documentat consecvent în literatură (Niculescu-Mizil & Caruana 2005): are nevoie de **semnificativ mai multe date** decât Platt pentru a nu supraadapta ea însăși — iar supraadaptarea pe eșantion mic e exact cauza-rădăcină deja diagnosticată aici (§1). Aplicarea unei metode predispuse la overfitting ca remediu pentru un simptom de overfitting e o contradicție internă care trebuie cel puțin recunoscută explicit, nu ignorată. Pentru un algoritm cu `MIN_SAMPLES_TO_TRAIN=30` (prag deliberat de jos, per proiect), riscul e concret, nu doar teoretic.

### 2.4 Temperature Scaling

Un singur parametru scalar `T`, aplicat pe marginile (logits) modelului înainte de softmax: `softmax(logits / T)`. `T > 1` reduce încrederea (exact corecția necesară aici — cazul diagnosticat e supraîncredere, nu subîncredere). Avantaj central, verificabil direct pe evidența din §1: Temperature Scaling **nu schimbă niciodată `argmax`** — deci `accuracy` rămâne matematic identică înainte/după, doar Brier/log-loss/gap-ul de calibrare se schimbă — efect izolat, ușor de verificat împotriva metodologiei deja folosite în `ORACLE_VS_ML_REPORT.md` (aceleași 3 metrici + tabelul de calibrare pe bin-uri). Cel mai eficient pe date puține dintre toate cele 3 metode (un singur parametru de estimat, nu 2×3 sau o funcție neparametrică). Dezavantaj: nu poate corecta o miscalibrare neuniformă între clase (presupune că toate cele 3 clase H/D/A sunt supraîncrezute proporțional) — o presupunere care trebuie verificată empiric, nu doar acceptată (vezi §10, limitări).

**Precondiție tehnică, verificată explicit, nu presupusă** (cerută la review): Temperature Scaling clasic operează pe marginile brute (logits), nu pe `predict_proba()` — dacă backend-ul XGBoost nu ar expune marginile brute, „Temperature Scaling" ar înceta să fie metoda descrisă în literatură și ar deveni altceva (ex. o rescalare aproximativă pe probabilități deja trecute prin softmax, cu proprietăți matematice diferite). Verificat direct, în mediul de execuție al proiectului (nu documentație generică):

```
$ python -c "import xgboost; print(xgboost.__version__)"
3.2.0
$ python -c "from xgboost import XGBClassifier; import inspect; print(inspect.signature(XGBClassifier.predict))"
(self, X, *, output_margin: bool = False, ...)
```

`XGBClassifier.predict(X, output_margin=True)` — parte a API-ului sklearn-wrapper deja folosit peste tot în `ml_predictor.py` (`model.fit()`/`model.predict_proba()`) — există și e disponibil exact în versiunea XGBoost pinată azi de proiect (`3.2.0`, aceeași versiune documentată în `MODEL_ARTIFACT_STORAGE_CONTRACT.md` §1). Precondiția e satisfăcută azi, confirmat, nu presupus.

**Decizia rămâne totuși explicit condiționată** de disponibilitatea continuă a acestei capacități: dacă o versiune viitoare de XGBoost ar elimina sau ar schimba semnificativ acest API fără echivalent, alegerea Temperature Scaling trebuie reanalizată înainte de orice implementare — nu presupusă valabilă la nesfârșit doar pentru că e valabilă azi.

## 3. Decizia

**Se alege Temperature Scaling.**

Justificare tehnică, nu preferință: (a) potrivire directă cu cauza diagnosticată — supraîncredere sistematică pe un model de gradient boosting cu puține date per fold, nu o formă complexă/neregulată de miscalibrare care ar justifica flexibilitatea (și riscul) Isotonic; (b) cea mai mică cerință de date dintre cele 3 metode active — un singur parametru scalar, potrivit cu `MIN_SAMPLES_TO_TRAIN=30`; (c) proprietatea verificabilă „`accuracy` neschimbat" oferă un test de sanitate direct și ieftin pentru orice implementare viitoare — dacă `accuracy` s-ar schimba după calibrare, ar însemna o eroare de implementare, nu un efect așteptat; (d) amprentă minimă de persistare (§7) — un scalar, nu o structură complexă.

Platt Scaling rămâne alternativa de rezervă dacă o viitoare investigație (Pasul 10, dacă e reluat cu date suplimentare) arată că miscalibrarea nu e uniformă între cele 3 clase — decizie de reconsiderat cu dovezi, nu presupusă acum.

## 4. Locul calibrării în pipeline

Două scheme au fost puse explicit față în față:

**Schema A** — calibrare la antrenare, înainte de persistare:
```
training → model → calibrator → artifact(e) → challenger (create)
```

**Schema B** — calibrare la promovare:
```
training → artifact → promotion → calibrare
```

**Decizie: Schema A.**

Motiv, ancorat direct în ADR-048 (nu redeschis, doar extins consecvent): `challenger_shadow.predict_with_challenger()` — apelat la **fiecare predicție live** cât timp există un Challenger activ, pe toată durata stării `EVALUATING`, adică **înainte** de orice decizie de promovare — produce probabilitățile care alimentează `shadow_predictions`, pe baza cărora `evaluate_active_challenger()` calculează exact metricile (Brier, log-loss) care decid dacă un Challenger devine `candidate_for_promotion`. Dacă Schema B ar fi aleasă, întreaga fereastră de evaluare a Challenger-ului ar rula pe probabilități **necalibrate** — decizia de promovare s-ar baza pe o comparație Champion-vs-Challenger unde niciunul, unul, sau ambele ar putea fi calibrate diferit față de ce se servește efectiv după promovare. Aceasta ar reintroduce exact problema pe care ADR-048 §5.4 a respins-o explicit pentru persistarea artefactului însuși (·persistare la promovare· → auto-contradictoriu, fiindcă evaluarea premergătoare promovării depinde de artefactul deja existent).

**Consecință directă**: calibrarea trebuie să fie disponibilă din chiar momentul creării Challenger-ului — same timing constraint ca artefactul brut (ADR-048 D2) — nu doar „undeva înainte de servire live".

## 5. Sursa datelor de calibrare — o întrebare pe care pipeline-ul actual o ridică, nediscutată de plan

Nu presupusă în promptul acestui task, dar descoperită prin citirea directă a `ml_predictor.py::train()`: modelul de producție se antrenează pe **tot istoricul disponibil** (`model.fit(X, y)`, linia 366) — nu există niciun set reținut ("held-out") pentru validare finală. Walk-forward-ul (`_walk_forward_validate()`, 5 folduri, expanding window) rulează separat, **exclusiv pentru raportarea onestă a metricilor** — probabilitățile lui `predict_proba()` per fold sunt calculate, folosite pentru `accuracy`/`brier`/`log_loss` agregate, apoi **aruncate** (nu persistate per-eșantion azi).

Trei surse posibile pentru antrenarea calibratorului, evaluate explicit (regula proiectului: zero scurgere temporală, fără excepție, CLAUDE.md):

1. **Predicțiile out-of-fold deja generate de walk-forward** — fiecare fold validează STRICT pe date ulterioare antrenării lui (deja garantat walk-forward-safe de codul existent). Concatenarea celor 5 seturi de `(probs, y_val)` produce exact eșantionul folosit și pentru tabelul de calibrare din `ORACLE_VS_ML_REPORT.md` §3.2 (n=1250 în acel benchmark) — aceeași sursă de date, aceeași disciplină temporală, deja verificată empiric mai sus în acest document. **Aleasă.**
2. **Un split final reținut, dedicat exclusiv calibrării** — ar necesita reducerea datelor disponibile modelului de producție (care azi le folosește pe toate) — cost real, nejustificat când opțiunea 1 e deja disponibilă, walk-forward-safe, fără cost suplimentar de date.
3. **Predicțiile modelului de producție pe propriile lui date de antrenare** — respinsă explicit: ar calibra pe eșantionul pe care modelul deja s-a suprapotrivit, mascând exact problema diagnosticată, nu corectând-o (scurgere clasică, echivalentul unui calibrator „prea încrezător în încrederea lui însuși").

**Separare explicită decizie/mecanism** (clarificare cerută la review): acest ADR decide DOAR sursa validă de date (opțiunea 1 de mai sus — predicțiile out-of-fold ale walk-forward-ului, singura consecventă cu disciplina walk-forward a proiectului). **Acest ADR nu decide mecanismul concret prin care acele predicții out-of-fold — azi calculate în memorie și aruncate imediat după agregarea metricilor — devin efectiv disponibile calibratorului** (ex. dacă se colectează într-un array temporar în interiorul aceluiași apel `train()`, dacă se persistă intermediar, sau altă soluție tehnică). Acesta e un detaliu de implementare, responsabilitatea viitorului Implementation Plan (după modelul deja folosit la Pasul 9) — nu al acestui document de arhitectură.

## 6. Impact asupra componentelor Champion/Challenger

Evaluat la nivel de decizie de arhitectură — fără a proiecta codul concret (în afara scopului acestui ADR):

| Componentă | Impact |
|---|---|
| **Champion** (`champion_loader.py`) | `load_champion_or_none()` ar trebui să încarce și calibratorul asociat `training_run_id`-ului campionului activ, nu doar modelul brut — altfel campionul servit ar fi necalibrat chiar dacă a fost calibrat la antrenare. Extensie de contract, nu implementată aici. |
| **Challenger** (`challenger_shadow.py`) | `predict_with_challenger()` ar trebui să aplice aceeași calibrare — consecință directă a deciziei din §4 (calibrare disponibilă din momentul creării). |
| **Promotion Service** | `_validate_artifact()` re-validează funcțional artefactul (`predict_proba()` pe un rând-sondă) — ar trebui extinsă să valideze și încărcarea/funcționarea calibratorului, nu doar a modelului brut, consecvent cu principiul deja aplicat acolo („re-validare funcțională, nu doar existența fișierului"). |
| **Champion Loader** | Cele 6 condiții de utilizabilitate deja documentate (`RUNTIME_CONTRACT.md`) ar avea nevoie de o a 7-a — existența/validitatea calibratorului — sau o decizie explicită că absența lui degradează grațios la necalibrat (§8). |
| **Shadow Evaluation** (`shadow_testing.py`, `challenger_evaluation.py`) | **Neatinsă structural** — consumă `shadow_predictions`, care ar conține deja probabilități calibrate (dacă predict() calibrează intern) — modulul nu are nevoie să știe că a avut loc o calibrare, primește doar numere mai bune. |

## 7. Persistență — un singur artefact, două artefacte, sau wrapper?

**Constrângere de bază, verificată direct în cod, neignorabilă**: `model_artifact_storage.save_model_artifact()`/`load_model_artifact()` (Pasul 9, neatins) sunt scrise explicit pentru API-ul nativ XGBoost — `model.save_model(path)` / `XGBClassifier().load_model(path)` (`model_artifact_storage.py:54`/`88`). Un obiect de calibrare (parametru `T` scalar, sau o funcție sklearn) **nu e** un `XGBClassifier` — nu poate fi serializat prin acest API fără a-l ocoli sau extinde.

Trei opțiuni analizate:

**(A) Un singur artefact** — un wrapper Python care conține atât modelul XGBoost, cât și parametrul `T`, expunând el însuși `predict_proba()` calibrat. **Respinsă**: wrapper-ul nu mai e un `XGBClassifier` — `model.save_model()` nu mai funcționează pe el. Ar necesita schimbarea **formatului artefactului** deja documentat ca parte de contract în `MODEL_ARTIFACT_STORAGE_CONTRACT.md` §1 („Formatul este parte din contract... nu poate fi schimbat fără migrare"), fie a serializatorului (de la JSON nativ XGBoost la ceva capabil să reprezinte obiecte Python arbitrare, ex. pickle — abandonând exact motivul pentru care JSON nativ a fost ales inițial, robustețea cross-version). Ar însemna o migrare a Pasului 1/Pasul 9 — exact ce acest task interzice explicit să atingă.

**(B) Wrapper la nivel de cod, artefact unic re-derivat** — modelul brut se persistă exact ca azi (neatins), iar parametrul `T` s-ar recalcula la fiecare încărcare, nepersistat. **Respinsă**: ar necesita re-rularea walk-forward-ului (costisitor, minute per algoritm) la fiecare încărcare a campionului (la fiecare boot de proces) — contrazice motivul pentru care Pasul 9 a rezolvat exact problema opusă („nu reantrena la fiecare boot"). Ar reintroduce o formă a aceleiași probleme rezolvate de ADR-048, doar mutată de la model la calibrator.

**(C) Două artefacte separate, aceeași cheie logică** — modelul XGBoost brut se persistă **exact ca azi, neschimbat** (`model-artifacts/<training_run_id>.json`, `model_artifact_storage.py` complet neatins), iar parametrul de calibrare se persistă **separat**, ca un artefact nou, mic (un scalar sau un JSON minimal), sub o cheie derivată din același `training_run_id` (ex. `model-artifacts/<training_run_id>.calibration.json` sau un bucket/prefix dedicat — decizie de naming, nu de acest ADR). **Aleasă.**

Motivare: respectă literal constrângerea „nu se modifică nimic din Pasul 9" — `model_artifact_storage.py`, formatul, naming convention-ul modelului rămân intacte. Amprenta noului artefact e minimă (un scalar sau câțiva, nu un model întreg) — cost de stocare neglijabil. Cei doi artefacți rămân cuplați logic prin `training_run_id`, exact tiparul deja folosit pentru relația `training_runs`↔`model-artifacts` (o cheie comună, două locații de stocare diferite, niciodată o singură scriere compusă).

**Contract semantic, distinct de stocarea fizică** (clarificare cerută la review): separarea în doi artefacți (§7C) e o decizie de **stocare** — nu înseamnă că modelul și calibratorul lui sunt două entități independente din perspectiva **contractului**. Semantic, ele formează o singură unitate logică de inferență, identificată prin același `training_run_id`: un model nu e „complet" pentru servire calibrată fără calibratorul lui exact, și un calibrator nu are sens fără modelul pe care a fost antrenat să-l corecteze. Trei stări posibile, explicit:

- **Model `training_run_id=A` + calibrator `training_run_id=A`** — stare normală, unitatea completă.
- **Model `A` + calibrator lipsă** — stare validă, explicit degradată (backward compatibility, §8/§9) — se servesc probabilități brute, nu o eroare.
- **Model `A` + calibrator provenit dintr-un alt `training_run_id` (`B`)** — **stare invalidă**, nu doar nedorită. Un calibrator antrenat pe marginile unui model `B` nu are nicio garanție matematică de valabilitate pentru marginile unui model `A` diferit (parametri diferiți, antrenare diferită, distribuție diferită de logits) — aplicarea lui ar produce probabilități fals-calibrate, mai periculoase decât lipsa completă a calibrării (o eroare tăcută, nu o degradare vizibilă). Orice mecanism de încărcare (viitor, la nivel de implementare) trebuie să valideze potrivirea `training_run_id` între cele două artefacte înainte de a le folosi împreună — nu doar existența separată a fiecăruia.

## 8. Backward compatibility

**Verificat, nu presupus**: azi (2026-08-04), `model_champions`/`challengers` conțin exclusiv rânduri `gate_validation_test` (fixturi, per `ARCHITECTURE_STATE.md` §4) — **zero Champion sau Challenger real există în producție**. Nu există, deci, niciun artefact real de model deja persistat prin Pasul 9 care ar avea nevoie de calibrare retroactivă — problema de backward compatibility e azi teoretică, nu operațională.

Decizie de principiu, pentru cazul în care ar exista deja artefacte necalibrate (relevant dacă acest ADR e implementat după ce Pasul 9 a rulat deja o vreme în producție): un artefact de model fără artefact de calibrare asociat **nu e o eroare** — e o stare cunoscută, explicită („necalibrat"), consecventă cu North Star #8 al proiectului („nicio stare necunoscută nu se aproximează — rămâne explicit 'necunoscut'"). Sistemul ar trebui să degradeze grațios la probabilități brute (necalibrate), cu logare explicită a stării, nu să trateze absența calibratorului ca eșec al modelului însuși.

## 9. Failure Matrix

| Scenariu | Comportament propus | Justificare |
|---|---|---|
| **Calibrarea eșuează la antrenare** (eșantion OOF degenerat — o singură clasă reprezentată, optimizare numerică instabilă pentru `T`) | Tratat identic cu eșecul de persistare a modelului brut (ADR-048 D3) — **Challenger-ul nu se creează deloc**. | Extensie consecventă a INV-1 (ADR-048 §5): un Challenger fără calibrare validă e la fel de „entitate invalidă" cât unul fără artefact de model — ambele ar produce o evaluare netrasabilă/inconsistentă pe durata `EVALUATING`. |
| **Artefactul de calibrare nu poate fi încărcat** la predict (fișier lipsă, corupt) — modelul brut ÎNSĂ se încarcă cu succes | Degradare grațioasă — se folosesc probabilitățile brute, necalibrate, cu log explicit de avertizare (Regula #8, degradare grațioasă). **Nu** se blochează predicția întreagă doar pentru lipsa calibrării. | Simetric cu tratarea existentă a lui `model_artifact_storage.load_model_artifact()` — `None` la orice eșec, niciodată excepție propagată. Modelul brut rămâne funcțional; calibrarea e o îmbunătățire, nu o precondiție de existență a predicției. |
| **Modelul nu poate fi calibrat deloc** (eșantion de antrenare sub un prag minim pentru calibrare, distinct de `MIN_SAMPLES_TO_TRAIN`) | Tratat ca eșec de calibrare la antrenare (primul rând al tabelului) — Challenger nu se creează. | Nu se introduce o cale silențioasă „antrenat dar necalibrat, promovabil oricum" — ar contrazice §4 (calibrarea trebuie să existe din momentul creării, nu opțional). |

## 10. Consecințe

**Avantaje**: corectează direct gap-ul de 24.3pp demonstrat empiric (§1); îmbunătățește Brier/log-loss — metricile care decid promovarea — fără a atinge `accuracy` (Temperature Scaling, prin construcție); face comparațiile Champion-vs-Challenger din Promotion Service trasabile la o realitate matematică verificată, nu la un artefact de supraadaptare; respectă complet granița Pasului 9 (zero atingere a `model_artifact_storage.py`, `training_runner.py`, `challenger_manager.py`).

**Dezavantaje**: nu corectează cauza-rădăcină (overfitting per-fold pe eșantion mic) — doar simptomul ei asupra probabilităților; presupune (§2.4) o miscalibrare uniformă între cele 3 clase, neverificată încă empiric per-clasă; introduce un al doilea tip de artefact de persistat, deci un al doilea punct de eșec posibil (mitigat prin degradare grațioasă, §9).

**Cost operațional**: neglijabil — Temperature Scaling optimizează un singur scalar pe date deja calculate (predicțiile OOF din walk-forward, care oricum rulează azi pentru raportarea metricilor) — nicio extragere suplimentară de date, nicio rulare suplimentară de antrenare.

**Impact asupra latenței**: neglijabil — o împărțire scalară + un softmax suplimentar per predicție, cost computațional nesemnificativ față de `predict_proba()` însuși.

**Impact asupra mentenanței**: un artefact nou de urmărit (§7C), o cale de degradare nouă de testat (§9), o extensie conceptuală a celor 6 condiții de utilizabilitate din `RUNTIME_CONTRACT.md` (§6) — cost real, dar mic, izolat, și consecvent cu tiparele deja existente în Learning Core (degradare grațioasă, chei logice comune, artefacte separate cuplate prin `training_run_id`).

---

## 11. Limitări explicite ale acestui ADR (nu ascunse)

- Nu s-a verificat empiric dacă supraîncrederea e uniformă între clasele H/D/A — presupunerea din spatele Temperature Scaling (§2.4/§3) rămâne o ipoteză plauzibilă, nu un fapt confirmat pe date reale până la implementare.
- Formatul exact al artefactului de calibrare (§7C — JSON minimal, cheie de naming exactă) nu e decis aici — e detaliu de implementare, pentru un viitor Implementation Plan, nu pentru acest document de design.
- Acest ADR nu decide DACĂ Pasul 10 se implementează acum — decide doar, DACĂ se implementează, cum ar trebui să arate arhitectural.

## 12. Decizie finală

Se adoptă: Temperature Scaling (§3), calculată la antrenare din predicțiile out-of-fold ale walk-forward-ului deja existent (§5), aplicată identic la orice consum al probabilităților unui `training_run_id` — Champion, Challenger shadow, Promotion validation (§4/§6) — persistată ca artefact separat, cuplat prin `training_run_id`, fără nicio schimbare asupra `model_artifact_storage.py`/formatului/naming convention-ului existent (§7C), tratat ca unitate semantică unică de inferență împreună cu modelul lui, niciodată amestecat cu calibratorul altui `training_run_id` (§7), cu degradare grațioasă la absența calibrării (§8/§9) și extindere consecventă a invariantului INV-1 (ADR-048) la eșecul de calibrare la antrenare (§9).

**Status: ACCEPTED** — 2026-08-04, de proprietarul produsului. Fără implementation plan, fără cod, fără commit ca parte a acestui document — decizia arhitecturală e închisă. Următorul document e un Implementation Plan dedicat Pasului 10 (stil identic cu Pasul 9), care trebuie să respecte ADR-049 fără a-l redeschide.
