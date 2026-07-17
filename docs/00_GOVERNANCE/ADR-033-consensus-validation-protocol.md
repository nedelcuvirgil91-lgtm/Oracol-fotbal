# ADR-033 — Consensus Layer Validation Protocol

**Status**: FROZEN (Etapa 4/4 din 4 — Planning Draft ✅ → Clarification Pass
✅ → ADR Final ✅ → Freeze ✅). Ultimul pas al drumului critic de execuție
Football Oracle vNext: ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030
(Frozen) → ADR-031 (Frozen) → **ADR-033 (Frozen)** — drumul critic complet
înghețat, 5/5.

**Autor**: Claude, redactat ca lucrare proprie la cererea explicită a
proprietarului produsului — nu reconstrucție, nu dictare. Etapa anterioară
de lucru pe acest fișier (conținut primit prin dictare/reconstrucție) a fost
abandonată integral ca proces greșit; acest draft pornește de la zero,
folosind exclusiv contractele deja înghețate ale ADR-026/028/030/031
(reconstruite pe disc) și codul real al proiectului ca sursă de adevăr.

---

## Context

Independent Architecture Assessment §5 a respins comiterea directă a unui
Consensus Layer (metrici de acord/divergență între motoare, expuse în UI),
propus inițial în Vision & Target Architecture — pe motiv că infrastructura
n-ar trebui construită înainte de a-i dovedi valoarea empiric, exact
disciplina deja aplicată feature-urilor ML din proiect (6 feature-uri deja
respinse prin permutation importance, măsurată pe 53.409 meciuri reale —
vezi `docs/03_ENGINE/FEATURE_ENGINEERING_ROADMAP.md`/`REST_DAYS_VALIDATION.md`).

ADR-031 (frozen) a produs precondiția tehnică necesară: ieșiri brute per
motor de predicție, comparabile, expuse determinist la granița de serving
— confirmat direct în cod, `oracle_engine.py::build_raw_predictions()`,
funcție pură, sortare deterministă `(family, engine)`. Compoziția rămâne
disponibilă neschimbat; N-way serving nu decide și nu curatoriază — doar
expune.

## Problem Statement

Fără un protocol de validare, orice decizie de a arăta utilizatorului o
metrică derivată din acordul/divergența dintre motoare ar fi o presupunere,
nu o dovadă — exact opusul filosofiei „Verificat, nu presupus" a
proiectului (CLAUDE.md). ADR-033 trebuie să stabilească CUM se demonstrează
dacă asemenea metrici poartă informație reală despre acuratețe sau
incertitudine, înainte ca vreo linie de UI Consensus să fie scrisă.

## Scope

**Intră**: mecanism de capturare a perechilor de ieșiri brute (per ADR-031)
la momentul predicției; calculul metricilor candidate de consens; corelarea
lor cu rezultatul real, folosind exclusiv metricile de acuratețe deja
standardizate în proiect (Brier/Log-loss/Accuracy, din `shadow_testing.py`);
un verdict binar explicit; o propunere T3a separată, doar dacă verdictul e
pozitiv.

**NU intră**: construirea Consensus Layer în UI; orice decizie automată de
surfacing; orice modificare a ADR-031, Model Registry, Promotion Service,
`shadow_testing.py`.

## Dependency Verification (adversarial)

- **ADR-031 (frozen)**: furnizează `raw_predictions`, dar nu le persistă
  nicăieri — verificat direct în cod: `build_raw_predictions()` e o funcție
  pură, apelată doar în memorie, la fiecare `evaluate_match()`; niciun
  câmp `MatchPrediction.raw_predictions` nu ajunge azi în `match_history`
  sau în alt tabel. ADR-033 are nevoie de un eșantion acumulat în timp
  pentru a putea corela ceva — trebuie să-și construiască propriul
  mecanism de capturare, nu poate presupune un istoric care nu există.
  Nu e o contradicție cu ADR-031 (care promitea doar expunere, nu
  persistare) — e o nevoie proprie, de acoperit integral în scope-ul
  acestui ADR.
- **ADR-026 (frozen)**: rezervă deja forma contractului — T1 pentru
  studiu, T3a pentru propunerea de schimbare a politicii de serving, dacă
  verdictul e pozitiv. ADR-033 umple acest contract, nu-l redefinește.
- **ADR-034 (neatins, viitor)**: corecția de comparații multiple se aplică
  deciziilor T3a bazate pe test statistic repetat. Studiul ADR-033 e T1,
  nu T3a — nu intră formal sub contractul ADR-034. Dar ADR-033 trebuie să-și
  impună propria disciplină minimă (o singură metrică primară,
  pre-înregistrată) ca să nu introducă exact riscul de comparații multiple
  pe care ADR-034 urmează să-l trateze sistemic, la scara întregului
  proiect.

## Mecanism de capturare — decizie de arhitectură explicită

Punctul central al acestui Planning Draft, tratat direct (nu lăsat ambiguu):
capturarea perechilor brute NU poate fi un job pur periodic — nimic din ce
ADR-031 produce azi nu e persistat, deci un job periodic n-ar avea ce citi
retroactiv. Propunerea:

**Tipar în două faze, infrastructură proprie** (reutilizează *tiparul*
arhitectural deja verificat în producție pentru Challenger — capture la
serving-time → evaluare periodică — dar NU infrastructura Shadow Testing
însăși: tabelă proprie, adapter propriu, independent de
`challenger_shadow.py`/`shadow_predictions`):

1. **Capture (serving-time)**: un adapter observațional nou, minimal,
   propriu ADR-033. Apelat din calea de serving, imediat după ce ADR-031
   produce `raw_predictions`. Persistă `(fixture_id, raw_predictions,
   timestamp, engine versions)` într-o tabelă proprie. Nu modifică
   Prediction Pipeline, nu influențează răspunsul către utilizator — strict
   observațional, aceeași regulă deja aplicată Shadow Adapter-ului, dar
   prin infrastructură proprie.
2. **Evaluation (T1, periodic)**: rulează separat, citește exclusiv
   eșantionul propriu deja capturat + rezultatele reale apărute între timp
   în `match_history`. Calculează metricile candidate, aplică disciplina de
   pre-înregistrare, produce verdictul.

Motivul separării de Shadow Testing: cele două validează lucruri diferite
(Shadow validează Challengeri ML, spre promovare de model; Consensus
Validation validează dacă o metrică de acord are valoare predictivă, spre
decizie de surfacing în UI) — o dependență artificială între ele ar cupla
concepte fără justificare (contrazice Separation of Concerns).

## Validation Protocol Contract

- Metrici candidate: Agreement Score, Divergence Score, Prediction
  Distance — formulele exacte, detaliu de implementare, nu de arhitectură.
  (Historical/Confidence Comparison rămâne opțional — vezi Open Questions;
  nu se adaugă scop fără o justificare clară a sursei de date.)
- Disciplină de pre-înregistrare: o singură metrică primară, declarată
  înainte de testare; restul, explicit „exploratorii", niciodată motiv
  singur de verdict pozitiv.
- Metrică de adevăr: exclusiv Brier/Log-loss/Accuracy — reutilizate direct
  din `shadow_testing.py` (`evaluate_experiment()`/`STATISTICAL_TESTS`),
  nicio metrică nouă de evaluare inventată.
- Prag minim de eșantion: obligatoriu ca existență (analog
  `min_matches=200` din `challenger_evaluation.evaluate_active_challenger()`,
  `MIN_SAMPLES_TO_TRAIN` din `ml_predictor.py`) — valoarea exactă, detaliu
  de implementare.
- Imutabilitate per pereche capturată — nu se recalculează retroactiv,
  indiferent de schimbări ulterioare (precedent direct: `UNIQUE
  (training_run_id, n_matches_evaluated)` din `challenger_evaluations`,
  ADR-018). O fereastră nouă (eșantion mai mare) produce un verdict nou,
  distinct — nu o corecție a celui vechi.
- Verdict binar: „surface-worthy" (dovadă suficientă pentru a justifica
  deschiderea unei propuneri T3a — nu echivalent cu aprobare) sau „respins"
  (rămâne experiment logat, fără urmări permanente — exact tratamentul deja
  aplicat feature-urilor ML respinse).
- Reluare: un verdict „respins" nu interzice definitiv ipoteza — un studiu
  nou e o rulare T1 nouă, cu propriul eșantion.

## Ownership

| Operație | Cine are voie |
|---|---|
| Capturarea perechii la serving-time | Exclusiv adapterul propriu ADR-033, apelat din calea de serving imediat după `raw_predictions` (ADR-031) |
| Colectarea/citirea eșantionului pentru studiu | Exclusiv procesul T1 al ADR-033 — citește doar propria tabelă + `match_history` |
| Calculul metricilor candidate | Funcție pură, nouă, în scope-ul acestui ADR |
| Corelarea cu acuratețea reală | Reutilizează exclusiv Brier/Log-loss/Accuracy din `shadow_testing.py` |
| Verdictul | Procesul T1 al ADR-033 |
| Propunerea T3a (dacă verdict pozitiv) | Procesul ADR-033, ca eveniment separat de T1-ul studiului |
| Decizia finală de surfacing | Exclusiv om, prin aprobarea T3a — niciodată automat |

**Granița observațională**: ADR-033 nu influențează niciodată predicțiile
produse, nu schimbă ponderi, nu schimbă modele, nu schimbă serving-ul.
Nimic din acest proces nu poate afecta, direct sau indirect, calea de
predicție live.

## Integrare cu ADR-026

- T1 pentru rulările de eșantionare/studiu (Faza 2) — datele eșantionului
  (capturate în Faza 1) referențiate prin pointer din `automation_runs`
  (Event Model — conținutul brut nu se copiază).
- T3a, exclusiv dacă verdictul e pozitiv — propunere de schimbare a
  politicii de serving (ADR-031), cu plan de rollback trivial (flag de
  configurare, revenire la comportamentul implicit, zero risc de date).
- Mecanismul de imutabilitate a eșantionului reutilizează, ca precedent de
  implementare, garda deja folosită de două ori în proiect
  (`odds_history_immutability_guard`, `model_champions_guard` — trigger
  Postgres, nu convenție de cod) — niciun tipar nou la nivel de gardă DB.
- Niciun state machine nou.

## Non-Goals

Nu construiește Consensus Layer în UI · nu decide singur surfacing-ul (doar
propune, T3a, aprobat de om) · nu inventează metrici de acuratețe noi · nu
modifică ADR-031, Model Registry sau Promotion Service · nu împrumută sau
extinde mecanismul ADR-034 · nu reutilizează infrastructura Shadow Testing
(tabelă, adapter) — doar tiparul ei arhitectural în două faze · nu
influențează, sub nicio formă, predicțiile, ponderile, modelele sau
serving-ul.

## Adversarial Check

- **Contradicții**: niciuna identificată față de ADR-026/028/030/031
  frozen.
- **Responsabilități mutate**: niciuna — capturarea rămâne în scope-ul
  propriu al ADR-033, nu împinsă spre ADR-031; disciplina statistică
  internă rămâne separată de ADR-034.
- **Încălcări de Freeze**: niciuna — nu redeschide `oracle_engine.py`
  dincolo de un hook aditiv (simetric ca amploare cu adăugarea de câmp din
  ADR-031), nu atinge `shadow_testing.py`.
- **Dependențe ascunse**: una identificată explicit — persistarea
  eșantionului, absentă din ADR-031 — acoperită integral în scope-ul
  propriu al acestui ADR (§Mecanism de capturare).
- **Overengineering**: respins un „framework general de experimentare cu
  metrici"; rămâne un protocol minim, cu o singură metrică primară
  pre-înregistrată. Respinsă construcția UI acum.

| Observație | Severitate |
|---|---|
| Studiul rulează prospectiv (de la activare) — niciun istoric relevant nu există înainte de ADR-031 | Minor — implică o fereastră de timp până la un eșantion suficient; de documentat, nu blochează |
| Pragul minim de eșantion — valoare exactă nedeclarată | Minor — analog precedentelor deja acceptate la ADR-030 (TTL), detaliu de implementare |
| Historical/Confidence Comparison — sursă de date neclară (ce înseamnă „istoric" pentru o metrică de consens care nu a existat niciodată înainte de ADR-031?) | Minor — de clarificat la Clarification Pass: se elimină din setul de metrici candidate ale primei runde, sau se definește explicit sursa |

Zero observații Blocking sau Major.

---

## Clarification Pass (Etapa 2/4)

Rezolvare explicită a celor trei puncte Minor + verificarea suplimentară de
imutabilitate, per aprobarea condiționată primită.

### Minor #1 — Fereastra de observare, formalizată

Nu „după suficiente date" (vag) — trei momente distincte, explicite:

1. **Capturarea începe imediat după activare** a adapterului propriu ADR-033
   (flag aditiv, implicit `False`, per North Star #3 — simetric cu
   `learning_core_enabled`). Din acel moment, fiecare predicție live produce
   o încercare de capturare, indiferent de mărimea eșantionului acumulat.
2. **Evaluarea periodică (Faza 2, T1) poate rula oricând**, independent de
   câte perechi există deja — rularea în sine nu are prag; e sigură de
   rerulat oricând (idempotentă, ca orice proces T1 din ADR-026).
3. **Verdictul propriu-zis (`surface-worthy`/`respins`) e permis DOAR după
   atingerea pragului minim de eșantion** (§Minor #2). Sub prag, procesul T1
   se completează normal, dar produce status `insufficient_data` — nu un
   verdict, nu o eroare, nu un `skipped`. Precedent direct, reutilizat exact:
   `shadow_testing.evaluate_experiment()` produce deja exact acest status
   pentru cazul „date insuficiente" (confirmat în cod,
   `challenger_evaluation.py`) — ADR-033 adoptă aceeași formă, nu inventează
   una nouă.

**Corecție de precizie față de Planning Draft**: „Verdict binar" (§Validation
Protocol Contract) devine, corect: verdictul final rămâne binar
(`surface-worthy`/`respins`), dar starea INTERMEDIARĂ `insufficient_data` nu
e un al treilea verdict — e absența oricărui verdict, exact ca la Shadow
Evaluation.

### Minor #2 — Pragul minim de eșantion, decis

Prag numeric fix, nu parametru configurabil — motivul: verdictul trebuie să
fie reproductibil, nu dependent de o valoare schimbată din `model_config`
între două rulări ale aceluiași studiu (ar contrazice imutabilitatea §4/
Minor suplimentar de mai jos — un prag variabil ar face „eșantion suficient"
o proprietate mutabilă a sistemului, nu a datelor).

Valoare: **200**, identică cu `MIN_MATCHES_FOR_EVALUATION` din
`continuous_learning.py`/`challenger_evaluation.evaluate_active_challenger()`
— nu un import/reutilizare a acelei constante (domenii conceptual diferite:
evaluare Challenger vs. validare Consensus — cuplarea ar încălca Separation
of Concerns), ci o constantă proprie ADR-033
(`MIN_SAMPLES_FOR_CONSENSUS_VALIDATION = 200`), cu aceeași valoare,
justificată explicit prin același precedent statistic deja acceptat în
proiect (prag minim pentru teste pereche de tip bootstrap, deja validat
empiric la Shadow Evaluation). Nu se inventează un număr nou fără
precedent.

### Minor #3 — Historical/Confidence Comparison, limitată explicit

De acord cu observația inițială, formalizată acum ca regulă, nu doar
notă: dependință circulară reală — „istoricul de consens" pe care l-ar
compara această metrică nu poate exista înainte ca adapterul de capturare
ADR-033 însuși să fi rulat o vreme. Consecință:

- **Exclusă din setul de metrici candidate al primului studiu** — nu doar
  „exploratorie", ci absentă din §Validation Protocol Contract până când
  există un eșantion propriu ADR-033 suficient de mare cât să servească
  drept „istoric" pentru ea însăși (prag separat, viitor, nedefinit aici —
  nu se inventează acum o valoare pentru o metrică ce nu participă încă).
- Dacă/când devine eligibilă, rămâne permanent exploratorie — nu poate
  deveni niciodată metrică primară pre-înregistrată (regulă structurală, nu
  doar recomandare), fiindcă orice comparație „istorică" a unei metrici
  calculate din propriile date anterioare ale sistemului poartă risc de
  circularitate pe care disciplina de pre-înregistrare (§Validation
  Protocol Contract) există s-o prevină.

Set de metrici candidate al primului studiu, corectat: Agreement Score,
Divergence Score, Prediction Distance — trei, nu patru. Historical/Confidence
Comparison rămâne un Non-Goal explicit al ADR-033 în forma lui inițială.

### Verificare suplimentară — Imutabilitatea eșantioanelor, explicitată

Deja specificată prin analogie (`challenger_evaluations`, ADR-018) în
Planning Draft — formalizată acum ca mecanism exact, nu doar precedent
citat:

- **Faza 1 (capture)**: `UNIQUE (fixture_id)` pe tabela proprie de
  eșantionare — o pereche capturată pentru un fixture nu poate fi
  suprascrisă de o a doua încercare de capturare pentru același fixture
  (structural imposibil, nu doar convenție de cod — trigger/constraint
  Postgres, simetric cu `odds_history_immutability_guard`/
  `model_champions_guard`).
- **Faza 2 (evaluare/verdict)**: `UNIQUE (metric_name, n_samples_evaluated)`
  pe tabela de verdicte — identic ca formă cu `UNIQUE (training_run_id,
  n_matches_evaluated)` din `challenger_evaluations`. O rerulare a
  studiului cu ACEEAȘI fereastră (același `n_samples_evaluated`) nu poate
  schimba un verdict deja scris — `INSERT ... ON CONFLICT DO NOTHING`,
  aceeași tehnică deja verificată prin test
  (`test_immutability_second_write_with_same_window_is_a_noop`).
- Fiecare pereche capturată e evaluată împotriva rezultatului final al
  meciului o singură dată, în cadrul studiului care o consumă — un studiu
  nou (fereastră mai mare) produce un verdict NOU, distinct, niciodată o
  corecție a celui vechi (regulă deja stabilită în Planning Draft,
  neschimbată).

---

**Clarification Pass închide toate cele trei puncte Minor + verificarea de
imutabilitate. Zero puncte Blocking sau Major rămase.**

---

# ADR-033 — ADR Final (Etapa 3/4, sinteză completă)

Sintetizează Planning Draft + Clarification Pass, plus cinci contracte
explicite cerute suplimentar înainte de Freeze (niciunul nu contrazice ce
era deja decis — toate erau implicite; devin acum explicite, verificabile
la implementare).

## Status

Decis. Al cincilea și ultimul ADR de pe drumul critic al seriei Football
Oracle vNext, succesor direct al ADR-026, ADR-028, ADR-030, ADR-031 (toate
frozen). Drum critic: `ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030
(Frozen) → ADR-031 (Frozen) → ADR-033`.

## Context

*(neschimbat față de Planning Draft — vezi §Context mai sus)*

## Problem Statement

*(neschimbat față de Planning Draft — vezi §Problem Statement mai sus)*

## Decision

ADR-033 nu construiește Consensus Layer. Definește protocolul prin care
Consensus Layer își câștigă, sau nu, dreptul de a exista — eșantionare
prospectivă în două faze (capture la serving-time, prin adapter propriu →
evaluare periodică T1, infrastructură proprie, independentă de Shadow
Testing), corelată cu Brier/Log-loss/Accuracy, sub disciplină de
pre-înregistrare, cu prag fix de eșantion, producând un verdict.

> **Regulă normativă centrală**: Rezultatele generate de ADR-033 (metrici,
> verdicte, propuneri T3a) nu pot modifica Prediction Pipeline, Consensus
> Engine (dacă și când va exista) sau politica de serving fără un ADR
> ulterior aprobat. Verdictul studiului produce exclusiv evidență — chiar
> un verdict `surface-worthy`, aprobat prin T3a, autorizează doar o
> propunere de schimbare, nu execută el însuși schimbarea. Nicio linie de
> cod scrisă sub acest ADR nu are voie să atingă `oracle_engine.py` dincolo
> de adapterul de capturare (§1) — orice extensie a comportamentului de
> serving e, prin definiție, un ADR nou, nu o implementare a acestuia.

## Scope

*(neschimbat față de Planning Draft, cu corecția din Clarification Pass:
setul de metrici candidate al primului studiu are trei elemente — Agreement
Score, Divergence Score, Prediction Distance — nu patru)*

## Cele cinci contracte explicite (cerute înainte de Freeze)

### 1. Capturarea e strict observațională

- Adapterul nu modifică Prediction Pipeline — confirmat, neschimbat față de
  Clarification Pass.
- Nu influențează scorurile, selecția modelului, sau (viitorul) Consensus —
  extins explicit: chiar dacă un studiu viitor produce verdict
  `surface-worthy` și o propunere T3a e aprobată, capturarea în sine tot nu
  devine parte din calea de decizie — rămâne strict input pentru studiul
  T1, niciodată o cale de retroacțiune asupra predicției curente.
- **Fail-open, explicit**: dacă adapterul de capturare nu poate persista
  perechea (Supabase indisponibil, eroare de rețea, orice altă cauză),
  predicția servită utilizatorului continuă normal, neafectată — identic
  cu Regula #8 (degradare grațioasă) deja aplicată la
  `challenger_shadow.log_shadow_for_active_challenger()`: orice excepție e
  prinsă la adapter, niciodată propagată către Oracle Engine. O captură
  ratată înseamnă un eșantion mai mic, niciodată o predicție întreruptă.

### 2. Activarea e separată de Learning Core

- Flag dedicat, propriu ADR-033 (ex. `consensus_capture_enabled`), implicit
  `False` — per North Star #3, simetric ca formă cu `learning_core_enabled`,
  dar NU același flag și NU citit din același loc conceptual.
- **Independent explicit de `learning_core_enabled`** (ADR-030): cele două
  controlează sisteme diferite (Continuous Learning vs. Consensus
  Validation) — activarea unuia nu implică sau necesită activarea
  celuilalt. Un operator poate rula Continuous Learning fără capturare de
  Consensus, sau invers.
- Poate fi pornit/oprit oricând, fără nicio interacțiune cu serving-ul —
  oprirea flag-ului oprește doar Faza 1 (capturarea); Faza 2 (evaluarea T1)
  poate rula în continuare pe eșantionul deja acumulat, sau poate fi și ea
  oprită separat, fără să afecteze predicțiile live.

### 3. Protocolul statistic e imuabil

- Prag fix: **200** observații (§Minor #2, Clarification Pass) — nu
  configurabil.
- O singură metrică primară, pre-înregistrată înainte de rularea studiului.
- **Explicit, nou**: metricile exploratorii NU pot deveni primare
  retroactiv, pentru un studiu deja rulat sau în curs — metrica primară a
  unui studiu se fixează la declararea/pornirea acelui studiu (parte din
  identitatea lui, la fel ca `training_run_id` pentru o antrenare) și
  rămâne fixă indiferent de rezultate. Un studiu NOU, cu o altă metrică
  primară declarată explicit dinainte, e o rulare T1 separată, cu propriul
  eșantion — nu o reinterpretare a datelor unui studiu vechi. Previne
  exact p-hacking-ul pe care disciplina de pre-înregistrare există s-o
  prevină.

### 4. Imutabilitatea datelor

- Captura pentru un `fixture_id` nu poate fi rescrisă —
  `UNIQUE (fixture_id)`, structural, la nivel de bază de date.
- Verdictele publicate nu pot fi modificate — `UNIQUE (metric_name,
  n_samples_evaluated)`, identic ca formă cu `challenger_evaluations`
  (ADR-018). O nouă evaluare (fereastră mai mare sau metrică nouă) produce
  un verdict NOU, niciodată o suprascriere a celui vechi.

### 5. Separarea responsabilităților

| Fază | Responsabilitate exclusivă |
|---|---|
| Capturare (Faza 1) | Doar persistă perechea `(fixture_id, raw_predictions, timestamp, engine versions)` — nu calculează nimic, nu interpretează |
| Evaluare T1 (Faza 2) | Doar calculează metricile + corelația cu rezultatul real — nu decide surfacing, nu scrie verdictul ca decizie finală |
| Verdict | Doar publică rezultatul studiului (`surface-worthy`/`respins`/`insufficient_data`) — nu declanșează automat nimic dincolo de propunerea T3a (dacă pozitiv) |
| UI (viitor, în afara scope-ului ADR-033) | Dacă și când o propunere T3a e aprobată, UI-ul afișează — nu interpretează, nu recalculează, nu modifică date. Constrângere explicită pentru orice implementare viitoare, nu doar pentru ADR-033 însuși |

Niciun strat nu are voie să facă mai mult decât rândul lui din acest tabel —
regulă structurală, nu doar recomandare de stil.

## Validation Protocol Contract

*(consolidat din Planning Draft + Clarification Pass — vezi secțiunile de
mai sus pentru justificare; aici doar forma finală)*

- Metrici candidate (primul studiu): Agreement Score, Divergence Score,
  Prediction Distance. Historical/Confidence Comparison exclusă (Minor #3).
- O singură metrică primară, pre-înregistrată, fixă per studiu (§3 de mai
  sus).
- Prag fix: 200 (`MIN_SAMPLES_FOR_CONSENSUS_VALIDATION`, constantă proprie).
- Metrică de adevăr: exclusiv Brier/Log-loss/Accuracy.
- Stări posibile: `insufficient_data` (sub prag) → `surface-worthy` sau
  `respins` (peste prag) — nu binar strict, dar verdictul propriu-zis
  rămâne binar (§Minor #1).
- Imutabilitate: §4 de mai sus.
- Reluare: verdict „respins" ≠ interdicție definitivă — studiu nou, T1 nou.

## Ownership

*(neschimbat față de Planning Draft — vezi tabelul de mai sus)*

## Integrare cu ADR-026

*(neschimbat față de Planning Draft — T1 pentru studiu, T3a doar dacă
verdict pozitiv, niciun state machine nou)*

## Non-Goals

Nu construiește Consensus Layer în UI · nu decide singur surfacing-ul · nu
inventează metrici de acuratețe noi · nu modifică ADR-031, Model Registry
sau Promotion Service · nu împrumută sau extinde mecanismul ADR-034 · nu
reutilizează infrastructura Shadow Testing · nu influențează, sub nicio
formă, predicțiile, ponderile, modelele sau serving-ul · nu include
Historical/Confidence Comparison în primul studiu · nu permite unei metrici
exploratorii să devină primară retroactiv · nu leagă activarea de
`learning_core_enabled`.

## Dependencies

ADR-031 (frozen) — ieșiri brute, comparabile, expuse. `match_history`
(canonic) — sursa rezultatelor reale. Metricile deja standardizate
(Brier/Log-loss/Accuracy, `shadow_testing.py`). Precedentul de imutabilitate
(`challenger_evaluations`, ADR-018) — reutilizat ca formă de gardă, nu ca
tabelă/infrastructură.

## Consequences

- Odată înghețat, acest ADR închide întregul drum critic al seriei vNext
  (ADR-026→028→030→031→033).
- Consensus Layer fie graduează (T3a aprobat), fie rămâne o respingere
  documentată — ambele rezultate închid riscul semnalat în Independent
  Assessment §5.
- Stabilește un tipar repetabil (capture la serving → evaluare periodică,
  infrastructură proprie per validare, activare independentă) pentru orice
  semnal speculativ viitor de produs.
- Un nou punct de atingere aditivă a căii de serving (adapterul de
  capturare) — al doilea, după ADR-031, minim ca amploare.

## References

Vision & Target Architecture · Independent Architecture Assessment §5 ·
ADR-026 (frozen) · ADR-031 (frozen) · ADR-018 (precedent de imutabilitate)
· ADR-033 Planning Draft · ADR-033 Clarification Pass.

## Open Questions

1. TTL propriu pentru eventuala decizie T3a — nedeclarat, per precedent
   ADR-026/030 (detaliu de implementare, nu blochează Freeze).
2. Pragul de eșantion propriu necesar pentru ca Historical/Confidence
   Comparison să devină eligibilă ca metrică exploratorie într-un studiu
   viitor — nedefinit, intenționat (nu se inventează acum o valoare pentru
   o metrică ce nu participă la primul studiu).
3. Cele două întrebări moștenite de la ADR-026 (fallback TTL generic;
   definiția „aprobator") rămân deschise, neatinse de acest ADR.

---

## Freeze Declaration (Etapa 4/4)

**ADR-033 — FROZEN.**

Status actualizat: Decis → Frozen. Tratat de acum ca contract normativ, nu
document de lucru — nicio modificare arhitecturală ulterioară decât printr-un
ADR nou, dedicat, per aceeași regulă aplicată ADR-026/028/030/031.

Adăugare finală, la cererea explicită a proprietarului produsului: regula
normativă centrală din §Decision (interdicția de a modifica Prediction
Pipeline/Consensus Engine/politica de serving fără un ADR ulterior aprobat)
— singurul amendament dintre aprobarea ADR Final și Freeze.

### Ce rămâne blocat, permanent, prin acest freeze:

- Tiparul în două faze (capture la serving-time, adapter propriu → evaluare
  T1 periodică, infrastructură proprie) e mecanismul unic acceptat de
  eșantionare — nu se reutilizează Shadow Testing, nu se inventează un al
  treilea tipar.
- Pragul de 200 de observații, fix, neconfigurabil.
- O singură metrică primară, pre-înregistrată, fixă per studiu — niciodată
  retroactivă.
- Imutabilitatea `UNIQUE (fixture_id)` / `UNIQUE (metric_name,
  n_samples_evaluated)` — structurală, nu convenție.
- Regula normativă centrală: niciun verdict, oricât de pozitiv, nu execută
  singur o schimbare de serving — doar autorizează o propunere T3a.
- Activarea rămâne independentă de `learning_core_enabled`.

### Drumul critic — COMPLET:

`ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030 (Frozen) → ADR-031 (Frozen)
→ ADR-033 (Frozen)`

Cinci din cinci componente ale drumului critic al seriei Football Oracle
vNext sunt acum înghețate ca documente. Următorul pas, per disciplina
aplicată la fiecare ADR anterior, e implementarea separată — cod, migrare
(dacă necesară), teste, PR, review, merge — NU parte din acest document.

### Următorul pas

Aștept confirmarea ta explicită pentru a începe implementarea ADR-033,
urmând exact aceeași secvență folosită la ADR-026/028/030/031:
reconnaissance → plan + identificare dependențe ascunse → implementare
reutilizând infrastructura existentă → teste exhaustive → PR → verificare
→ merge (doar după aprobare explicită).
