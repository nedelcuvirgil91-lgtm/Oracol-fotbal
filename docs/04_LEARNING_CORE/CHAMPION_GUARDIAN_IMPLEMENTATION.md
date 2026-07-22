# CHAMPION_GUARDIAN_IMPLEMENTATION.md — Football Oracle

**Status**: Document de implementare (design detaliat). Capitolele 1–15 descriu designul înghețat înainte de cod; **cap. 16 consemnează starea reală de implementare după închiderea R1 (Rollback Engine) și R2 (Champion Guardian)** — la orice divergență inline față de codul livrat, cap. 16 e normativ. Detaliază, la nivel executabil-fără-reinterpretare, deciziile deja înghețate în `docs/00_GOVERNANCE/ADR-037-learning-core-rollback-and-champion-guardian.md`.

**Referință de autoritate**: ADR-037 (stabil, aprobat). Acest document **nu** modifică ADR-037; îl detaliază. Orice contradicție între acest document și ADR-037 se rezolvă în favoarea ADR-037.

**Reguli respectate**: Verificat, nu presupus · nicio modificare a contractelor Frozen · niciun redesign · fără cod · fără SQL.

---

## 1. Scope

### 1.1 Ce implementează (R1–R4)
- **Rollback Engine** (R1): un mecanism atomic de reversie a campionului activ la predecesorul lui, append-only, cu un serviciu single-owner și un set închis de motive.
- **Champion Guardian** (R2): un evaluator read-only al sănătății campionului activ, care clasifică starea, calculează cele patru dimensiuni de sănătate și persistă fapte imuabile în `champion_health_evaluations`.
- **Orchestrare** (R3): cablarea Guardian → propunere de decizie T3a → execuție a rollback-urilor aprobate, în bucla de Continuous Learning existentă.
- **Activare** (R4): trecerea `learning_core_enabled` pe `True` în producție, după verificarea R1–R3.

### 1.2 Ce NU implementează
- Rollback automat fără om în buclă (rămâne sub un ADR dedicat de risc, per ADR-037 §14).
- Marcarea unui `training_run_id` de model servitor pe fiecare predicție (atribuire precisă) — se folosește atribuire temporală (ADR-037 §9).
- Calculul efectiv al axei **Confidence** (prevăzută, dar neimplementată în Stage 1 — ADR-037 §6.2).
- Rollback în lanț (mai mult de un pas de reversie).
- Corecția comparațiilor multiple (Bonferroni/FDR).
- Orice dashboard/UI (aparține Monitoring Layer, viitor).
- Orice schimbare a formulelor de model (Poisson/Monte Carlo/XGBoost/blend).

### 1.3 Dependențe față de ADR-037
Fiecare capitol de mai jos derivă dintr-o decizie ADR-037: Rollback append-only (§3/D1), cele șase motive (§4/D2), ownership Champion Guardian (§5/D3), Health States + patru dimensiuni (§6/D4), `champion_health_evaluations` + `baseline_source` (§7/D5), politica de baseline și atribuirea temporală (§9), ciclul de viață (§10), strategia de eșec (§12), compatibilitatea înapoi (§13), etapele (§15). Distincția conceptuală Promotion vs. Rollback (§2) e premisă transversală.

### 1.4 Dependențe față de ADR-015…019 și ADR-030
- **ADR-015** — `training_runs` + `model_champions` (schema pe care Rollback scrie) și `champion_comparison` (informativ, neatins).
- **ADR-016** — `challengers` FSM. Rollback **nu** atinge FSM-ul (ambele rânduri implicate sunt deja terminale `PROMOTED`).
- **ADR-017/018** — shadow logging + `challenger_evaluations` (sursa baseline-ului live pentru Guardian).
- **ADR-019** — contractele Frozen `PROMOTION_CONTRACT` / `ATOMICITY_CONTRACT` / `PROMOTION_SERVICE_CONTRACT` / `RUNTIME_CONTRACT` (precedente și granițe pe care Rollback le urmează simetric, fără a le modifica).
- **ADR-030** — `learning_core/continuous_learning.py` (bucla A/B/C gata construită) + `automation_runs` (registrul de guvernanță T1/T2/T3a + decision feed) în care se cablează faza de rollback.

---

## 2. Champion Guardian

### 2.1 Responsabilități
- Evaluează periodic sănătatea campionului **activ** per `(algorithm_family, league_scope)`.
- Calculează cele patru dimensiuni de sănătate (baseline deviation, trend, structural, prediction stability — cap. 7/8).
- Clasifică rezultatul într-o stare unică de sănătate (Healthy/Watch/Degrading/Critical — cap. 5).
- Persistă fiecare evaluare ca fapt imuabil în `champion_health_evaluations` (cap. 3).
- Când starea justifică, **propune** o recomandare de rollback în decision feed (nu execută).

### 2.2 Inputuri
- Identitatea campionului activ: citită din `model_champions` (rândul cu `superseded_at IS NULL`).
- Predicțiile servite ale campionului: `match_history.prob_home_pred`/`prob_draw_pred`/`prob_away_pred` (scrise de Prediction Engine la `_cache_prediction`).
- Rezultatele reale: `match_history.actual_result`/`actual_home_goals`/`actual_away_goals` (owner: `sync/sync_results.py`, ADR-036).
- Baseline-ul de promovare: rândul de verdict din `challenger_evaluations` al campionului (`brier_experiment`/`logloss_experiment`/`accuracy_experiment`), obținut prin funcția de citire existentă `get_latest_challenger_evaluation(training_run_id)`.
- Fereastra de atribuire temporală: `kickoff_date` raportat la `promoted_at` (ADR-037 §9).
- Istoricul de sănătate anterior: rândurile precedente din `champion_health_evaluations` (pentru „ferestre consecutive").

### 2.3 Outputuri
- Un rând nou, imuabil, în `champion_health_evaluations` la fiecare rulare cu fereastră nouă.
- Opțional, o **recomandare** de rollback (propunere T3a în decision feed), niciodată o execuție.
- Guardian-ul nu întoarce nimic consumat de Prediction Engine — e strict în afara căii de servire.

### 2.4 Ownership și relația cu Learning Core
Champion Guardian aparține **Learning Core** (planul de control), nu Monitoring Layer — argumentare completă în ADR-037 §5.1. Granița: evaluarea + recomandarea = Learning Core; vizualizarea = Monitoring Layer (viitor). Guardian-ul e un component nou, izolat, cu un singur punct de intrare public, în tiparul „single owner" al celorlalte componente Learning Core.

### 2.5 Relația cu Promotion Engine
Niciuna directă. Guardian-ul **citește** un artefact al Promotion (rândul de verdict din `challenger_evaluations`) ca baseline, dar nu importă Promotion Service, nu declanșează promovări, nu recalculează verdicte de promovare. Promotion și Guardian sunt cele două fețe ale evaluării de calitate (pre- vs. post-promovare), deliberat nefuzionate (ADR-037 §11).

### 2.6 Relația cu Rollback Engine
Guardian **propune**; Rollback Engine **execută**. Guardian nu apelează niciodată `rollback_champion()` direct și nu scrie niciodată `model_champions`. Legătura trece exclusiv prin decision feed + aprobare umană (excepție: `emergency`, care ocolește fereastra T3a — dar tot uman-inițiat, nu Guardian-inițiat).

---

## 3. Champion Health Evaluations (tabelă nouă)

Tabelă nouă, aditivă, append-only, imuabilă — precedent exact `challenger_evaluations` (ADR-018). Fără SQL aici; contractul de date de mai jos e normativ.

### 3.1 Câmpuri și semnificație
- **identitate campion**: `training_run_id` (campionul evaluat), `algorithm_family`, `league_scope` — cui aparține evaluarea.
- **fereastră**: marcaj de sfârșit de fereastră (derivat din `kickoff_date`-ul ultimului meci inclus) + numărul de meciuri evaluate în fereastră — definesc unitatea de evaluare.
- **metrici de sănătate**: valorile live ale metricilor de scoring reutilizate din `shadow_testing` (aceleași definiții Brier/Log-loss/Accuracy) pe fereastră + indicatorul de stabilitate a predicțiilor (cap. 8).
- **`health_state`**: starea derivată (Healthy/Watch/Degrading/Critical).
- **`baseline_source`**: din setul `{promotion_evaluation, trend_only, manual_override}` (cap. 4) — pe ce bază a fost calculată sănătatea.
- **rezultate per-semnal**: care dimensiune(i) a(u) declanșat (baseline / trend / structural / stability), pentru audit și pentru regula ferestrelor consecutive.
- **timestamp**: momentul evaluării, UTC.

### 3.2 Invariants
- **Append-only**: fiecare evaluare e un rând nou; nu se face UPDATE pe rânduri existente.
- **Imutabilitate**: un rând, odată scris, nu se mai modifică niciodată — un fapt istoric, nu o stare mutabilă. (Consecvent cu `challenger_evaluations`; dacă e nevoie de garanție la nivel de bază de date, se aplică același tipar de trigger ca la `odds_history`/`model_champions`, decis la implementare.)
- **UNIQUE (training_run_id, n_matches_evaluated)** *(implementat — vezi cap. 16.1; înlocuiește `window_end` din designul inițial)*: aceeași fereastră (același campion + același număr de meciuri evaluate) nu poate produce decât un singur rând, pentru totdeauna — o rerulare cu aceeași fereastră e un no-op garantat. O fereastră NOUĂ (mai multe meciuri acumulate între timp → `n_matches_evaluated` mai mare) produce un rând NOU, distinct — un fapt nou, nu o corecție. `n_matches_evaluated` (monoton crescător pe măsură ce se acumulează dovezi) e cheia de fereastră stabilă folosită și de regula ferestrelor consecutive (cap. 16.3).
- **Fereastră nouă = dovezi noi**: un rând nou se scrie doar când s-au acumulat suficiente meciuri noi de la fereastra precedentă (pas minim), nu la re-evaluarea acelorași meciuri — condiție necesară ca „ferestrele consecutive" să reflecte evidență nouă.

### 3.3 Indexuri (intenție, nu DDL)
- index pe `(training_run_id)` — pentru citirea istoricului de sănătate al unui campion (regula ferestrelor consecutive).
- index pe `(algorithm_family, league_scope, <timestamp>)` — pentru interogări istorice cronologice.
Exact profilul de indexare din `challenger_evaluations` (un index pe training_run_id, unul de istoric).

### 3.4 Retenție
Append-only, fără ștergere automată — istoricul de sănătate e un fapt de audit permanent (Regula #9: trasabilitate completă). Nu se prevede TTL în Stage 1; o eventuală politică de arhivare e Future Work, tratată explicit, niciodată prin ștergere tăcută.

---

## 4. Baseline

`baseline_source` marchează, per evaluare, pe ce bază a fost calculată sănătatea. Trei valori, mutual exclusive:

- **`promotion_evaluation`** — se folosește când campionul activ **are** un rând de verdict de promovare în `challenger_evaluations` (cazul normal: campionul a fost promovat prin lanțul challenger). Baseline-ul sunt metricile lui `*_experiment` de la promovare, măsurate *live* pe date shadow → comparabile like-for-like cu performanța live ulterioară. E baseline-ul preferat.
- **`trend_only`** — se folosește când campionul **nu are** un verdict de promovare (ex. primul campion, bootstrapat, fără fază de challenger). Regula „Never approximate": nu se inventează un baseline; deviația de la baseline e sărită complet, iar sănătatea se sprijină exclusiv pe evaluarea de trend (cap. 7).
- **`manual_override`** — se folosește când un operator furnizează explicit un punct de referință (ex. o investigație țintită). Rezervat; în Stage 1 apare doar dacă e invocat manual, niciodată derivat automat.

Regula de selecție e deterministă: existența verdictului de promovare → `promotion_evaluation`; absența lui → `trend_only`; intervenție umană explicită → `manual_override`.

---

## 5. Champion Health State Machine

O singură clasificare derivată per evaluare (punct unic de decizie, tiparul `_classify_data_quality()`, ADR-035 D4). Designul inițial a enumerat patru stări; implementarea a adăugat explicit a cincea, **`insufficient_data`** (distinctă de Healthy — vezi cap. 16.2), astfel încât „date insuficiente" să nu fie niciodată confundat cu „sănătos". „Tranzițiile" nu sunt o mașină cu efecte laterale la runtime — sunt reclasificări succesive, fereastră după fereastră, fiecare persistată ca fapt.

### 5.1 Stări
- **🟢 Healthy** — toate semnalele în limite. Acțiune: doar înregistrare.
- **⚪ InsufficientData** *(implementat — cap. 16.2)* — sub `MIN_MATCHES_FOR_HEALTH` meciuri scorabile; nicio judecată statistică posibilă. Distinctă de Healthy (Regula #8: „necunoscut" nu se aproximează cu „sănătos"). Acțiune: doar înregistrare (dacă n≥1), zero recomandare.
- **🟡 Watch** — un singur semnal statistic degradat, ori o deviație ușoară, ori un flag de instabilitate (cap. 8). Acțiune: doar log, nicio recomandare.
- **🟠 Degrading** — degradare statistică susținută (ferestre degradate consecutive — cap. 7). Acțiune: propune rollback `regression` (T3a).
- **🔴 Critical** — eșec structural (artifact_missing / model_error), ori colaps statistic sever. Acțiune: recomandare imediată; structural poate justifica `emergency`.

### 5.2 Tranziții
- **Healthy → Watch**: apare primul semnal statistic degradat, sau o deviație ușoară, sau instabilitate.
- **Watch → Degrading**: semnalul statistic se susține pe ferestre consecutive.
- **Watch → Healthy**: fereastra următoare revine în limite (semnalul a fost un spike izolat) — mecanismul central de reducere a zgomotului.
- **Degrading → Critical**: degradarea se adâncește la colaps sever, sau apare un eșec structural.
- **orice stare → Critical**: un eșec structural (artefact absent/rupt) forțează Critical imediat, indiferent de starea statistică anterioară (structural = imediat, cap. 7/9).
- **Degrading/Critical → (post-rollback)**: după un rollback executat, campionul activ se schimbă; evaluarea repornește pentru noul campion activ (predecesorul reactivat) — o nouă serie de sănătate, nu o continuare a celei vechi.
- **Critical (structural) → Healthy** nu se produce de la sine: un campion structural mort rămâne Critical până la rollback (nu se „vindecă" singur).

Instabilitatea (cap. 8) nu poate ridica starea peste **Watch** în nicio tranziție.

---

## 6. Champion Confidence

### 6.1 Două axe diferite
- **Health** = *starea* modelului (cât de degradat e).
- **Confidence** = *cât de mult ne putem încrede în verdict* (cât de puternic e semnalul).

Sunt ortogonale: `Health = Degrading, Confidence = Low` (ex. eșantion mic) e un semnal fragil de urmărit; `Health = Degrading, Confidence = High` (ex. eșantion mare) e un semnal robust de acționat. Operatorul trebuie să distingă imediat între ele — de aceea nu se contopesc într-un singur scor.

### 6.2 De ce Confidence NU influențează rollback în Stage 1
Confidence e **prevăzută arhitectural, dar neimplementată** în Stage 1 (ADR-037 §6.2). Motivul: derivarea ei corectă (din numărul de meciuri, consistența ferestrelor, stabilitatea metricilor) e o dimensiune în sine, care ar întârzia livrarea mecanismului de reversie. În Stage 1, robustețea semnalului e asigurată *procedural* — prin regula ferestrelor consecutive (o degradare trebuie susținută înainte de recomandare) și prin pragul minim de eșantion — nu printr-un scor de Confidence. Ieșirea Guardian-ului **rezervă** câmpul/axa (transportat ca „necomputat"), ca introducerea ulterioară a Confidence să fie aditivă, fără schimbare de contract.

---

## 7. Trend Evaluation

### 7.1 Rolling windows
Predicțiile servite rezolvate ale campionului (cele cu `prob_*_pred` și `actual_result` prezente, `kickoff_date ≥ promoted_at`) se ordonează cronologic după `kickoff_date`. Evaluarea de trend operează pe **ferestre rulante** ale celor mai recente meciuri — nu pe tot istoricul cumulativ (care ar dilua un declin recent).

### 7.2 Consecutive degraded windows
O singură fereastră degradată → **Watch** (posibil spike). Degradarea trebuie să se **susțină pe ferestre consecutive** înainte de a deveni **Degrading** și de a genera o recomandare. „Consecutiv" înseamnă evaluări succesive, fiecare peste o fereastră cu dovezi noi (meciuri noi acumulate), persistate ca rânduri distincte în `champion_health_evaluations`. Numărul exact de ferestre = parametru de implementare, nu decizie de arhitectură.

### 7.3 Concept drift
Trend-ul compară o sub-fereastră recentă cu una anterioară a **aceluiași** campion — detectează *drift* gradual (lumea se schimbă, modelul rămâne fix) chiar când nivelul absolut încă pare acceptabil față de baseline. E complementar deviației de la baseline (care prinde căderi abrupte).

### 7.4 Evaluări succesive
Fiecare rulare Guardian produce cel mult o fereastră nouă; seria de ferestre din `champion_health_evaluations` e substratul pe care se aplică regula „consecutive". Fără formule concrete aici — metrica de trend și pragurile sunt detaliu de implementare.

---

## 8. Prediction Stability

- **Scop**: detectarea modelelor „nervoase" — care emit predicții extrem de încrezătoare ce oscilează haotic între ferestre, nejustificate de rezultate.
- **Ce măsoară**: o dispersie/volatilitate a vectorului de probabilități servite pe o fereastră recentă (metrica exactă = implementare). Ortogonală acurateței: un model poate fi precis dar nervos, sau stabil dar greșit.
- **De ce e doar informațional**: instabilitatea nu implică per se că modelul e greșit — e un semnal de fragilitate, util ca avertizare timpurie, nu ca dovadă de degradare.
- **De ce nu produce rollback**: nu are motiv propriu în setul închis; contribuie cel mult la **Watch** (ca `instability_detected`); nu poate ridica starea la Degrading/Critical și nu poate declanșa singură o recomandare. Rollback rămâne rezervat degradării demonstrate (statistice susținute) sau eșecului structural.

---

## 9. Rollback Reasons

Set închis de șase motive (ADR-037 §4). Pentru fiecare: cine îl generează, cine îl execută, când apare, dacă necesită T3a.

| Motiv | Cine îl generează | Cine îl execută | Când apare | T3a? |
|---|---|---|---|---|
| **regression** | Champion Guardian (degradare statistică susținută: baseline sau trend) | Rollback Service, după aprobare | ferestre degradate consecutive → Degrading | **Da** (guvernat) |
| **artifact_missing** | Champion Guardian (sondă structurală: artefact absent/necitibil/nedeserializabil) | Rollback Service | imediat la detectare → Critical | Da, sau operator direct |
| **model_error** | Champion Guardian (sondă structurală: obiect încărcat dar `predict_proba` invalid / `algorithm_version` incompatibil) | Rollback Service | imediat la detectare → Critical | Da, sau operator direct |
| **data_error** | Operator (corupție amonte identificată) | Rollback Service | investigație umană | Nu (autoritate operator) |
| **operator** | Operator (decizie umană, fără semnal automat) | Rollback Service | judecată umană | Nu (direct) |
| **emergency** | Operator (override cu efect imediat) | Rollback Service | urgență | **Ocolește** fereastra T3a; rămâne logat |

Notă load-bearing (ADR-037 §4): pentru `artifact_missing`/`model_error`, servirea e deja protejată (fallback pe local ML în `RUNTIME_CONTRACT`); rollback-ul structural restabilește un campion declarat sănătos, nu salvează servirea.

---

## 10. Rollback Flow

Fluxul complet, guvernat (motivul `regression` și structuralele guvernate). Fără cod.

```
Champion Guardian
   │  clasifică sănătatea; dacă Degrading/Critical →
   ▼
Decision Feed (propunere T3a, cu evidence: training_run_id predecesor, motiv, dovezi de sănătate)
   │  om aprobă / respinge (excepție: emergency ocolește fereastra)
   ▼
Automation Runs (înregistrează run + decizie: propusă → surfaced → approved → committed/failed)
   │  decizie aprobată, neexecutată →
   ▼
Rollback Service (single owner; verifică precondiții structurale ÎNAINTE de orice scriere)
   │  un singur apel →
   ▼
rollback_champion()  [RPC atomic]  (cap. 11)
   │  două scrieri cuplate, o singură tranzacție →
   ▼
Champion Manager (model_champions: campion activ degradat → istoric; predecesor → rând nou activ)
   │  pointerul activ s-a schimbat →
   ▼
Oracle Engine (la următoarea construcție de proces, _resolve_champion() citește noul rând activ)
```

Faza umană (aprobarea) e obligatorie pentru toate căile în afară de `emergency`. Execuția rollback-urilor aprobate reutilizează exact mecanismul deja existent din `continuous_learning` Faza C (decizii aprobate → execuție).

---

## 11. RPC Responsibilities — `rollback_champion()`

Doar responsabilități; fără SQL. Diviziunea Python vs. RPC urmează exact precedentul `promote_challenger` (ATOMICITY_CONTRACT).

**Rollback Service (Python), ÎNAINTE de RPC — precondiții structurale, fail-fast, zero scriere la primul eșec:**
- există un campion activ pentru `(algorithm_family, league_scope)`;
- există un predecesor (rândul pe care campionul activ l-a supersedat); altfel `no_predecessor`, refuz;
- artefactul predecesorului e re-validat funcțional (se poate încărca și produce predicții) — nu readucem un campion care e el însuși mort;
- motivul aparține setului închis de șase;
- **transmite `training_run_id`-ul predecesorului validat ca `expected_predecessor_training_run_id` către RPC** — sămânța de compare-and-swap (vezi mai jos). Astfel artefactul validat aici e EXACT cel activat de RPC, sau operația e respinsă — se elimină complet TOCTOU-ul „validează în Python → activează în RPC".

**`rollback_champion(algorithm_family, league_scope, expected_predecessor_training_run_id, reason, by)` (RPC, o singură tranzacție Postgres):**
- ia lock pe campionul activ pentru `(algorithm_family, league_scope)`; dacă nu există campion activ → refuz;
- **idempotență (stare-țintă)**: dacă campionul activ ESTE deja `expected_predecessor_training_run_id` (rollback deja aplicat, ținta atinsă) → întoarce `already_active`, nicio a doua scriere;
- derivă server-side, sub lock, predecesorul campionului activ (rândul cu `superseded_by = training_run_id`-ul campionului activ); dacă nu există → `no_predecessor`, refuz;
- **gardă compare-and-swap**: dacă predecesorul derivat server-side ≠ `expected_predecessor_training_run_id` (starea s-a schimbat concurent — ex. o promovare între citirea Python și RPC) → refuz explicit (`predecessor_mismatch`), **zero scriere**; operatorul reia cu starea actuală. Impus EXACT ca pattern-ul deja existent `update_challenger_state(expected_current_state=...)` (`challenger_manager.transition`) — niciun mecanism nou inventat;
- supersedează campionul activ curent (singura mutație permisă de triggerul de imuabilitate: activ → istoric);
- inserează un rând nou, activ, pentru `expected_predecessor_training_run_id`, cu `promoted_by = rollback:<motiv>:<by>`;
- **nu** atinge `challengers` (ambele rânduri sunt deja terminale `PROMOTED`);
- garantează atomicitatea: fie ambele scrieri, fie niciuna — nicio stare intermediară observabilă (proprietatea cerută de ATOMICITY_CONTRACT, aplicată simetric la rollback).

**Rezultat**: un tip structurat, niciodată excepție necontrolată către apelant — status `rolled_back` / `already_active` / `rejected` (+ motiv, ex. `no_predecessor`, `predecessor_mismatch`).

**Idempotență — secvențial vs. concurent (comportament real, reconciliat cu auditul pre-R1):**
- **Secvențial** (re-apel după ce un rollback anterior s-a încheiat complet): campionul activ e deja predecesorul → `already_active`, curat, zero scriere.
- **Concurent** (două rollback-uri simultane pe același `(algorithm_family, league_scope)`): garanția tare e **SIGURANȚA** — lock-ul `FOR UPDATE` pe rândul activ + indexul parțial unic `idx_model_champions_active_unique` asigură exact un câștigător, zero dublă-scriere, zero corupție. Dar pierzătorul **NU** primește garantat `already_active`: în funcție de momentul snapshot-ului de statement (READ COMMITTED), poate primi o **respingere** (`rejected` — ex. „niciun campion activ", fiindcă rândul activ pe care îl aștepta a fost supersedat concurent) și **trebuie să reia** cu starea actuală. Aceasta e exact distincția secvențial/concurent din `PROMOTION_CONTRACT.md` (secțiunea Idempotență): pe calea concurentă se garantează siguranța, nu un status uniform. Operatorul/serviciul tratează `rejected` pe această cale ca semnal de retry, nu ca eroare de corupție.

---

## 12. Failure Scenarios

| Scenariu | Comportament dorit |
|---|---|
| **Artefact lipsă** (campionul activ) | Guardian: sondă structurală → `artifact_missing` → Critical → recomandare imediată. Servirea e deja pe fallback local (RUNTIME_CONTRACT). |
| **Model corupt** (obiect încărcat dar `predict_proba` invalid / versiune incompatibilă) | Guardian: `model_error` → Critical → recomandare imediată. |
| **Date insuficiente** (fereastră sub prag) | Nicio evaluare statistică, nicio recomandare — Regula #8, niciodată aproximare. Se scrie cel mult o stare `insufficient`/Healthy-by-default fără semnal. |
| **Baseline lipsă** (fără verdict de promovare) | `baseline_source = trend_only`; deviația de la baseline sărită; doar trend. |
| **Rollback fără predecesor** | Rollback Service refuză explicit (`no_predecessor`), zero scriere. |
| **Dublu rollback** (concurent sau repetat) | RPC idempotent: al doilea apel vede predecesorul deja activ → `already_active`, nicio a doua scriere. Rollback în lanț (mai mult de un pas) e în afara scopului Stage 1. |
| **DB indisponibil** | Best-effort peste tot: Guardian nu emite recomandare, Rollback Service întoarce `rejected`; niciodată excepție propagată, niciodată scriere parțială. |
| **Champion Guardian indisponibil** | Sistemul continuă neschimbat: fără evaluare de sănătate → fără recomandări → campionul rămâne activ. Servirea nu depinde de Guardian (North Star #10). Absența Guardian-ului nu poate corupe nimic. |

---

## 13. Backward Compatibility

Demonstrație explicită că nimic din ce funcționează nu se schimbă:

- **Prediction Engine** (`oracle_engine.py`, Poisson/Monte Carlo/blend, `_cache_prediction`): zero schimbare. Guardian doar **citește** `prob_*_pred` deja scrise; nu modifică calea de predicție.
- **Promotion Engine** (`promotion_service.py`, `promote_challenger` RPC): zero schimbare — Rollback e un serviciu și un RPC separate.
- **Ownership `model_champions` (explicit — schimbare reală de la owner unic la doi scriitori coordonați)**: `model_champions` e **agregarea Champion Lifecycle**. De la R1, are **două evenimente de domeniu autorizate** care o pot modifica: **Promotion Service** (`promote_challenger`) și **Rollback Service** (`rollback_champion`). Coordonarea NU e prin owner unic — e garantată integral de invarianții de bază de date, deja existenți și **neatinși**: (1) tranzacția atomică a RPC-ului; (2) indexul parțial unic `idx_model_champions_active_unique` (un singur activ per `(algorithm_family, league_scope)`); (3) triggerul de imuabilitate `model_champions_guard` (migrarea 005, Frozen — o singură mutație activ→istoric); (4) row locking (`FOR UPDATE`) în RPC. Cei doi scriitori sunt tranzacții atomice serializate de aceleași constrângeri — fundamental diferit de o cursă cu arbitraj `COALESCE` first-writer-wins. **Nicio schimbare de design, de trigger sau de migrarea 005** — doar consemnarea explicită a acestei realități, ca un dezvoltator viitor să nu presupună owner unic.
- **Champion Loader** (`champion_loader.py`, cele 6 condiții): zero schimbare — un rând reactivat prin rollback e indistinct ca formă de unul promovat; loader-ul îl încarcă identic.
- **Oracle Engine** (`_initialize_ml`/`_resolve_champion`): zero schimbare de cod — citește rândul activ exact ca azi; rollback schimbă doar *care* rând e activ, preluat la următoarea construcție de proces (RUNTIME_CONTRACT).
- **Contracte Frozen** (`RUNTIME_CONTRACT`, `PROMOTION_CONTRACT`, `ATOMICITY_CONTRACT`, `PROMOTION_SERVICE_CONTRACT`): zero modificare — Rollback e mecanismul separat pe care `PROMOTION_CONTRACT` îl rezervă explicit. Triggerul de imuabilitate `model_champions` (migrarea 005) rămâne neatins; designul append-only respectă exact mutația unică pe care el o permite.
- **Schema existentă** (`match_history`, `model_champions`, `challengers`, `challenger_evaluations`, `training_runs`): zero `ALTER`. Se adaugă doar obiecte noi, aditive (RPC de rollback + tabela `champion_health_evaluations`).
- **Flag-uri**: totul rulează sub `learning_core_enabled` (implicit `False`); nimic nou nu pornește implicit activ (P1).

---

## 14. Stage Breakdown

Fiecare etapă e independent revizuibilă, în disciplina ADR-035 (fail-before/pass-after, gărzi AST, plan de revenire, verificare live). Numerele de migrare continuă după 013 (ultima existentă).

### R1 — Rollback Engine (declanșare manuală)
- **Scope**: mecanismul atomic de reversie + serviciul single-owner + citirea predecesorului + setul de motive. Declanșare exclusiv manuală (fără Guardian, fără orchestrare).
- **Fișiere**: `learning_core/rollback_service.py` (nou); `database/migrations/014_rollback.sql` (nou, RPC); funcții noi de acces în `supabase_client.py` (citire predecesor + apel RPC); teste noi `tests/test_rollback_service.py`, `tests/test_supabase_client_rollback.py`. Niciun fișier de producție existent modificat.
- **Teste**: predecesor găsit/absent; atomicitate (ambele scrieri sau niciuna); idempotență (`already_active`); precondiții eșuate → `rejected`, zero scriere; gardă AST — RPC-ul are un singur apelant; verificare că triggerul de imuabilitate rămâne respectat (niciun rând istoric mutat).
- **Criterii de finalizare**: după rollback, campionul activ = predecesorul; suita verde; verificare live pe o combinație reală.
- **Rollback plan (al etapei)**: migrare aditivă — se șterge funcția RPC; se șterg cele trei fișiere noi; nicio migrare de date de inversat.

### R2 — Champion Guardian (evaluare read-only)
- **Scope**: Guardian-ul + cele patru dimensiuni + Health States + `champion_health_evaluations`. Doar evaluare + persistare fapte + propunere; fără execuție.
- **Fișiere**: `learning_core/champion_guardian.py` (nou); `database/migrations/015_champion_health.sql` (nou, tabela); funcții noi de acces în `supabase_client.py` (scriere/citire health evaluations); teste noi `tests/test_champion_guardian.py`, `tests/test_champion_health_evaluations.py`.
- **Teste**: clasificare corectă a stării pe ferestre sintetice; regula ferestrelor consecutive (spike izolat → Watch, susținut → Degrading); structural → Critical imediat; `baseline_source` corect (`promotion_evaluation` vs. `trend_only`); imuabilitate/UNIQUE pe rerulare; stabilitatea = doar Watch; gardă AST — Guardian nu scrie `model_champions`.
- **Criterii de finalizare**: o degradare simulată produce recomandarea corectă; un baseline absent → `trend_only`; suita verde.
- **Rollback plan**: aditiv — se șterge tabela + funcția + fișierele; nimic existent atins.

### R3 — Orchestrare (cablare în Continuous Learning)
- **Invariant obligatoriu (documentat, respectat — fără modificarea FSM-ului)**: **un `training_run` deja retras prin rollback NU trebuie niciodată re-promovat.** Motiv verificat în cod: după rollback, rândul lui din `challengers` rămâne în starea terminală `PROMOTED`, iar `promote_challenger` (RPC, migrarea 005) are deja garda necesară — un re-apel pe acel `training_run_id` întâlnește `state='PROMOTED'` dar „nu mai e campionul activ" și ridică `RAISE 'stare neasteptata'`. Orchestrarea NU trebuie să se bazeze pe această excepție ca mecanism — trebuie să nu propună niciodată re-promovarea unui `training_run` retras (un challenger nou primește oricum un `training_run_id` nou). Nu se modifică FSM-ul, nu se modifică `promote_challenger` — doar se respectă invariantul.
- **Scope**: o fază nouă în `continuous_learning.py` care cheamă Guardian → propune T3a; extinderea Fazei C existente pentru a executa rollback-urile aprobate; motivele `regression` (guvernat), `operator`/`emergency` (direct).
- **Fișiere**: `learning_core/continuous_learning.py` (extindere); teste extinse `tests/test_continuous_learning.py`.
- **Teste**: o degradare susținută → decizie T3a surfaced; decizie aprobată → execuție prin Rollback Service; decizie neaprobată → nicio acțiune; `learning_core_enabled=False` → faza sărită complet.
- **Criterii de finalizare**: flux end-to-end (Guardian → decizie → aprobare → rollback) verificat pe date sintetice; suita verde.
- **Rollback plan**: se revine diff-ul din `continuous_learning.py`; R1+R2 rămân utilizabile.

### R4 — Activare (producție)
- **Scope**: trecerea `learning_core_enabled` pe `True`, după R1–R3 verificate. Doar configurare.
- **Fișiere**: configurare (`model_config` Supabase / `config.json`), fără cod nou.
- **Teste**: verificare live pe o singură ligă înainte de extindere.
- **Criterii de finalizare**: un ciclu real produce evaluări de sănătate persistate și (dacă e cazul) recomandări corecte, fără fals-pozitive pe ligile stabile.
- **Rollback plan**: `learning_core_enabled=False` — revenire instantanee la comportamentul de azi.

---

## 15. Future Work

Mutate explicit aici, în afara Stage 1 (ADR-037 §14/§16):
- **Auto rollback** (fără om în buclă) — cere un ADR dedicat de risc (contrazice ADR-002, ca și promovarea automată).
- **Confidence scoring** — calculul efectiv al axei Confidence (din număr meciuri, consistență ferestre, stabilitate metrici); introducere aditivă, câmpul e deja rezervat.
- **Per-model attribution** — marcarea unui `training_run_id` de model servitor pe fiecare predicție, înlocuind atribuirea temporală; potențial ADR separat.
- **Multiple comparison correction** (Bonferroni/FDR) — când numărul de campioni/challengeri monitorizați simultan crește.
- **Rollback în lanț** — semantica reversiei cu mai mult de un pas.
- **Monitoring dashboard** — UI read-only în Monitoring Layer care consumă `champion_health_evaluations`, fără a deține evaluarea.
- **Politică de retenție/arhivare** pentru `champion_health_evaluations`, dacă volumul o cere — explicit, niciodată prin ștergere tăcută.

---

## 16. Stare de implementare — R2 închis (Champion Guardian)

Consemnare a realității livrate (cod + migrare + teste). Normativ față de capitolele 1–15 la orice divergență inline. R1 (Rollback Engine) e închis separat (vezi `R1_IMPLEMENTATION_CHECKLIST.md` + `CHANGELOG.md`).

### 16.1 Artefacte livrate (R2.1–R2.8)
- **`database/migrations/015_champion_health.sql`** — tabela `champion_health_evaluations`, append-only, RLS activ, `UNIQUE(training_run_id, n_matches_evaluated)`, `CHECK health_state IN (5 valori)`, `CHECK baseline_source IN (3 valori)`, FK către `training_runs`, două indexuri. **Fără trigger de imuabilitate** — imuabilitatea e garantată de `UNIQUE + ON CONFLICT DO NOTHING` (precedent `challenger_evaluations`, ADR-018), nu de trigger.
- **`supabase_client.py`** — trei funcții noi de acces: `get_champion_served_outcomes()` (citește doar rânduri scorabile: `prob_home_pred` ȘI `actual_result` prezente, `kickoff_date ≥ since_date`, ordine totală `(kickoff_date, fixture_id)`), `record_champion_health_evaluation()` (INSERT idempotent, `on_conflict="training_run_id,n_matches_evaluated"`, `ignore_duplicates=True`), `get_recent_champion_health_evaluations()` (istoric DESC după `n_matches_evaluated`).
- **`learning_core/champion_guardian.py`** — punct unic de intrare public `evaluate_champion_health(algorithm_family, league_scope) -> ChampionHealthResult | None`; clasificare într-un singur punct de decizie `_classify_champion_health`.
- **Teste** (35 dedicate, fără rețea): `tests/test_champion_guardian.py` (21), `tests/test_supabase_client_champion_health.py` + `tests/test_champion_guardian_ownership.py` (14).

### 16.2 Constante stabilite (valori reale în cod)
| Constantă | Valoare | Rol |
|---|---|---|
| `MIN_MATCHES_FOR_HEALTH` | **30** | prag minim de meciuri scorabile; sub el → `insufficient_data`, niciodată judecată statistică |
| `BASELINE_DEGRADATION_MARGIN` | **0.10** | deviație Brier live vs. verdict de promovare peste care semnalul de baseline e degradat |
| `TREND_DEGRADATION_MARGIN` | **0.10** | `recent_mean > earlier_mean * (1 + margin)` → fereastră de trend degradată |
| `CONSECUTIVE_DEGRADED_WINDOWS` | **2** | ferestre degradate consecutive necesare pentru Degrading (spike izolat → doar Watch) |
| `STABILITY_DISPERSION_THRESHOLD` | **0.20** | dispersie a probabilității max peste care se aprinde flag-ul de instabilitate (doar informațional → plafonat la Watch) |

Prioritatea clasificării (un singur punct de decizie): **Critical (structural) > InsufficientData (n < MIN) > Degrading (consecutiv) > Watch > Healthy**.

### 16.3 Politica de persistare și regula ferestrelor consecutive
- **n == 0**: return-only — Guardian întoarce rezultatul (inclusiv un Critical structural, dacă sonda a picat), dar **NU persistă** niciun rând și nu deschide fereastră. *(F3 din audit: un Critical structural cu `n == 0` e returnat, nu scris — nu există fereastră de dovezi de imortalizat.)*
- **n ≥ 1**: persistă exact o dată per fereastră (`n_matches_evaluated`), idempotent (`ON CONFLICT DO NOTHING`).
- **Regula ferestrelor consecutive (F1 din audit)**: `_count_consecutive_degraded` exclude rândurile cu `n_matches_evaluated >= current_n`, ca o rerulare pe aceeași fereastră (același `n`) să nu dubleze numărătoarea și să escaladeze fals Watch → Degrading. Apelantul citește `limit = CONSECUTIVE_DEGRADED_WINDOWS + 1`.

### 16.4 Granița de scriere R2 vs. R3 (impusă mecanic)
Guardian scrie **exclusiv** `champion_health_evaluations` (prin unicul owner `record_champion_health_evaluation`). NU scrie `model_champions` (nu promovează, nu face rollback) și **NU scrie `automation_runs`** (nu orchestrează, nu deschide decizii T3a — aceasta e responsabilitatea R3, `continuous_learning`). Garda AST `tests/test_champion_guardian_ownership.py` impune: `champion_guardian` nu importă `promotion_service`/`rollback_service`/`oracle_engine`/`continuous_learning`, nu referențiază `rpc_promote_challenger`/`rpc_rollback_champion`/`promote_challenger`/`rollback_champion`/`automation_runs`, iar `record_champion_health_evaluation` are un singur apelant de producție (Guardian). „Propunerea T3a" din cap. 2.1/2.3/10 e deci descriere de arhitectură-țintă a fluxului R3 — Guardian-ul livrat în R2 **nu** emite propuneri, doar clasifică și persistă.

### 16.5 R2.8 — validated without state mutation
Închiderea R2 s-a validat pe DB live fără mutație de stare (oglindind R1.8): `champion_health_evaluations` = **0 rânduri**, 3 campioni activi neatinși. Calea statistică live (Healthy/Watch/Degrading) nu a putut fi exercitată pe date reale fiindcă **`scoreable = 0`** — zero rânduri din `match_history` au simultan `prob_home_pred` ȘI `actual_result`. Corectitudinea căii statistice e acoperită integral de cele 35 de teste dedicate pe ferestre sintetice; validarea live rămâne deferată (vezi limitarea de mai jos).

### 16.6 Limitare operațională
> **Limitare operațională**: Champion Guardian este complet implementat și testat, însă validarea live a căii statistice (Healthy/Watch/Degrading bazate pe meciuri scorabile) este amânată până când `match_history` conține predicții servite care au și rezultat (`scoreable > 0`). În starea actuală (`scoreable = 0`), Guardian intră în `insufficient_data` și nu produce mutații de stare.

### 16.7 Notă operațională de deployment
Migrarea 015 a fost aplicată prin **Supabase SQL Editor**, nu prin `apply_migration` (conexiunea MCP în mod read-only la momentul aplicării) — identic cu 014. Consecință: tabela nu apare în tracker-ul „Database Migrations" (oprit la 013). **Sursa canonică rămâne fișierul comitat** `database/migrations/015_champion_health.sql`.

---

## 17. Stare de implementare — R3 (Orchestrare) — cod complet, activare controlată, nemerge-uit pe `main`

Consemnare a realității livrate (cod + teste), R3.1-R3.7. Normativ față de capitolele 1-15 la orice divergență inline. Detaliile de execuție (task-uri, ordine reală, divergențe față de plan) sunt în `R3_IMPLEMENTATION_CHECKLIST.md`, reconciliat. Planul de deployment (ce/cum/când se activează) e în `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md`.

### 17.1 Artefacte livrate
- **Faza D** (`continuous_learning._phase_d_champion_health`) — evaluează campionul activ prin Champion Guardian (R2, neatins), jurnalizează, și — dacă recomandă rollback — propune o decizie T3a, cu ținta rollback-ului **înghețată** în `evidence` la propunere (`current_training_run_id`, `predecessor_training_run_id`).
- **Faza C extinsă** (`continuous_learning._phase_c_execute_rollback`) — execută rollback-ul aprobat, citind **exclusiv** ținta înghețată — niciodată recalculată la execuție.
- **`rollback_service.rollback_champion()`** — extindere aditivă, parametru opțional `expected_predecessor_training_run_id`: transmis explicit din Faza C (ținta fixă, CAS pinned); omis (`None`) pe calea manuală R1, comportament neschimbat.
- **`rollback_service.is_rollback_promoted()`** — singurul loc din proiect care interpretează formatul `promoted_by`; consumat de Faza D ca gardă anti-ping-pong.
- **Două flag-uri de deployment dedicate** (`continuous_learning.is_champion_guardian_enabled()` / `is_champion_guardian_proposals_enabled()`) — independente de `learning_core_enabled`, implicit `False` — vezi §17.4.
- **Teste**: 35 în `tests/test_continuous_learning_rollback.py` (Faza D/C, gărzi, flag-uri) + 9 noi în `tests/test_rollback_service.py` (helper + `expected_predecessor_training_run_id`) + gărzi AST actualizate.

### 17.2 Execution Contract — de ce execuția e idempotentă peste timp
Descoperire dintr-un Execution Readiness Review (cerut explicit înainte de a scrie codul de execuție): `get_champion_predecessor()` derivă predecesorul **dinamic**, din campionul activ **curent** — un retry peste timp (proces mort între RPC și `commit_decision`) ar recalcula un predecesor diferit (al campionului deja reactivat), producând un rollback în lanț neintenționat. Promotion nu are acest risc (`training_run_id` fix, capturat la propunere).

**Rezolvare**: ținta se îngheață la propunere (R3.2A.1), execuția (R3.2B) transmite `expected_predecessor_training_run_id` explicit către RPC-ul 014 (**neatins** — CAS-ul deja existent din R1 e singura sursă de adevăr pentru validare). Rezultat verificat mecanic (nu doar argumentat):
- retry după crash, nimic altceva schimbat → `already_active` (succes, convergență);
- retry după o schimbare externă de stare (alt campion activ între timp) → `predecessor_mismatch` → `rejected` → `fail_decision_commit` — **niciodată** un rollback peste o stare învechită.

### 17.3 Production Topology Audit (R3.5) — descoperire semnificativă
Verificare live, read-only, pe Supabase `Prediction`:
- `model_config.learning_core_enabled = true` în producție — **pre-existent**, susține bucla ADR-030 (Fazele A/B/C), **neînrudit** cu R3.
- Workflow-ul `.github/workflows/continuous_learning.yml` rulează pe `main` (checkout implicit, fără `ref:`, la trigger `schedule`) — `main` **nu conține deloc** codul R3 (branch-ul de lucru era, la momentul auditului, 21 commit-uri înaintea lui `main`).
- `automation_runs`/`decision_feed`/`model_champions` confirmă: zero activitate Faza D, zero decizie de rollback, zero campion activ real pentru familiile reale (`production_champion`, `xgboost_v1`) — doar fixturi de test izolate (`gate_validation_test`, din R1.8).
- **Concluzie**: zero mutație, zero efect secundar din codul R3 — pentru că nu rulase niciodată live, nu pentru că gărzile interne l-ar fi oprit. Această distincție a motivat R3.7.

### 17.4 De ce Faza D are flag-uri proprii, separate de `learning_core_enabled`
`learning_core_enabled` gatează azi, nediferențiat, tot `run_cycle()`. Fiind deja `true` în producție (§17.3), un merge simplu pe `main` ar activa Faza D automat, la prima rulare programată — încălcând separarea intenționată „R3 (cod gata) ≠ R4 (activare deliberată)". Soluție, oglindind tiparul deja stabilit de ADR-033 (`consensus_capture_enabled`/`consensus_validation_enabled` — două gate-uri pentru două etape ale aceleiași funcționalități):

| Flag | Gatează | Implicit |
|---|---|---|
| `champion_guardian_enabled` | Faza D (evaluare + persistare `champion_health_evaluations`) | `False` |
| `champion_guardian_proposals_enabled` | Propunerea T3a de rollback (în interiorul Fazei D, doar dacă primul flag e activ) | `False` |

Fazele A/B/C (training/challenger/promovare) rămân **exclusiv** sub `learning_core_enabled`, neschimbate. Detalii de secvențiere (etapele 1-5 de activare) în `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md`.

### 17.5 Ce rămâne, explicit, înainte de merge
- Merge pe `main` — **neefectuat**, blocat deliberat până la acest document + planul de deployment.
- Verificare `model_champions`/`challengers` proaspătă, la momentul merge-ului (starea din §17.3 se poate schimba între timp — Fazele A/B rulează zilnic).
- Activarea (R4) rămâne separată, în etape, per planul de deployment — nu discutată/aprobată încă.

---

## Self-review — consistență cu ADR-037

- **Fără redesign**: documentul detaliază, nu reinterpretează. Fiecare capitol mapează 1:1 pe o decizie ADR-037 (Rollback append-only, cele șase motive, Champion Guardian + ownership, Health States, patru dimensiuni, `champion_health_evaluations` + `baseline_source`, baseline live + regula `trend_only`, atribuire temporală, ciclu de viață, strategii de eșec, compatibilitate). ✔
- **Fără contradicții**: distincția Rollback ≠ opusul Promotion (cap. 2, 9, 11) e păstrată; Guardian doar propune, Rollback Service execută, RPC scrie — trei responsabilități separate, exact ca în ADR-037 §5.3/§3. ✔
- **Fără atingerea contractelor Frozen**: cap. 13 demonstrează explicit zero modificare la RUNTIME/PROMOTION/ATOMICITY/PROMOTION_SERVICE și la triggerul 005; append-only respectă mutația unică permisă. ✔
- **Fără cod, fără SQL**: contractul tabelei e prezentat ca listă de câmpuri + semnificație + invariants (fără DDL); RPC-ul e prezentat ca responsabilități (fără SQL); Health States ca descriere + tranziții (fără cod). ✔
- **Confidence**: prezentată ca axă separată, prevăzută dar neimplementată în Stage 1 — identic cu ADR-037 §6.2; nu influențează rollback. ✔
- **Prediction Stability**: strict informațional, plafonat la Watch, fără motiv propriu — identic cu ADR-037 §6.3. ✔
- **Verificat, nu presupus**: referințele la module/coloane/funcții existente (`_resolve_champion`, `champion_loader`, `promote_challenger`, `challenger_evaluations.*_experiment`, `get_latest_challenger_evaluation`, `match_history.prob_*_pred`/`actual_result`, `automation_runs` decision lifecycle, `continuous_learning` Faza C, triggerul migrării 005) corespund stării reale a repo-ului, citită direct. Numerele de migrare (014/015) continuă după 013, ultima existentă. ✔
- **Divergențe introduse**: niciuna. Singurele elemente care depășesc ADR-037 sunt detalii de nivel de implementare (indexuri, intenție de retenție, împărțirea pe fișiere, criterii de test) — permise explicit de nota de stil ADR-037 și de Change Policy (detaliile de implementare nu necesită ADR). ✔
