# ADR-033 — Consensus Layer Validation Protocol

**Status**: Decis — ADR Final (Etapa 3/4 din 4 — Planning Draft ✅ →
Clarification Pass (rezolvată live, vezi notă) → ADR Final ✅ → Freeze).
Ultimul pas al drumului critic de execuție Football Oracle vNext: ADR-026
(Frozen) → ADR-028 (Frozen) → ADR-030 (Frozen) → ADR-031 (Frozen) →
**ADR-033 (Final, în așteptarea confirmării de Freeze)**.

**Reconstrucție**: Document scris LIVE, pe măsură ce s-a produs (nu
retroactiv, ca restul seriei ADR-026/028/030/031) — singurul din serie
pentru care Planning Draft, review-ul adversarial și rezolvarea Clarification
Pass sunt înregistrate complet și verificabil, nu doar reconstruite din
memorie imperfectă.

**Notă istorică importantă**: textul original al Clarification Pass (dacă a
existat vreodată separat, în conversația inițială) nu a fost recuperabil —
proprietarul produsului a confirmat explicit că istoricul retrimis nu e
garantat complet/corect. Punctul Major identificat la review-ul Planning
Draft-ului (mecanismul de captare a eșantionului, §2 mai jos) a fost, prin
urmare, **rezolvat live, în această sesiune de reconstrucție**, nu recuperat
dintr-un document anterior — consemnat exact ca atare, nu prezentat fals ca
o continuare a unui text vechi.

---

## 1. Scope

**Intră**: un protocol de validare empirică — testează dacă metricile
candidate de consens (Agreement Score, Divergence Score, Prediction
Distance, Historical/Confidence Comparison) corelează cu ceva real
(acuratețe/incertitudine reală), pe un eșantion suficient de meciuri unde
ambele ieșiri brute (per ADR-031) și rezultatul real (per `match_history`,
canonic) sunt disponibile. Produce un verdict explicit: „surface-worthy"
sau „respins" — exact disciplina deja aplicată ablației de feature-uri (6
respinse pe date reale).

**NU intră**: construirea Consensus Layer ca strat surfaced în UI (asta se
întâmplă, dacă și numai dacă validarea reușește, printr-o propunere T3a
separată de schimbare a contractului de serving, per contractul deja fixat
la ADR-026); orice modificare a ADR-031 (serving), Model Registry,
Promotion Service.

## 2. Dependency Verification

Declarată deja: #6 (ADR-031, frozen) — are nevoie de ieșiri brute,
comparabile, expuse.

Verificare adversarială — dependință reală, nedeclarată explicit până acum:
ADR-031 expune ieșirile brute la momentul cererii (serving-time), dar nu
specifică nicio persistare istorică a lor. ADR-033 are nevoie de un
eșantion acumulat în timp (perechi `(ieșire_brută_A, ieșire_brută_B,
fixture_id)`, ulterior legate de `actual_result` din `match_history`)
pentru a putea corela ceva. Asta nu e o contradicție cu ADR-031 (care nu
promitea persistare, doar expunere) — e o nevoie proprie, pe care ADR-033
trebuie s-o acopere în propriul scope, nu prin reschimbarea contractului de
serving deja înghețat.

Rezolvare, fără a redeschide ADR-031: ADR-033 definește propriul mecanism
minim de eșantionare — o rulare T1 periodică/prospectivă care captează
perechile la momentul predicției (folosind exact ce ADR-031 expune deja) și
le stochează separat, referențiate prin pointer din `automation_runs` (per
Event Model, ADR-026: „conținutul brut... se referă prin pointer, nu se
copiază"). Validarea rulează, deci, prospectiv de la momentul activării, nu
retroactiv pe un istoric care nu există încă.

Verificare suplimentară: nicio dependință de ADR-034 — corecția de
comparații multiple din ADR-034 e scop-ată explicit la decizii T3a bazate
pe test statistic repetat; studiul de validare al ADR-033 e T1, nu T3a,
deci nu intră formal sub acel contract. ADR-033 își definește propria
disciplină statistică internă (§4), fără să împrumute sau să extindă
mecanismul ADR-034.

## 3. Ownership

| Operație | Cine are voie |
|---|---|
| Colectarea eșantionului (perechi + rezultat real) | Exclusiv procesul de eșantionare al ADR-033, T1, folosind doar ce ADR-031 expune deja |
| Calculul metricilor candidate | Funcție pură, nouă, în scope-ul acestui ADR |
| Corelarea cu acuratețea reală | Reutilizează exclusiv Brier/Log-loss/Accuracy — metricile deja standardizate în proiect, niciuna nouă |
| Verdictul de validare | Procesul ADR-033, raportat ca T1 + (dacă pozitiv) o propunere T3a separată |
| Decizia finală de surfacing | Om, prin aprobarea T3a — niciodată automat, indiferent de rezultatul validării |

ADR-033 nu scrie niciodată în `model_champions` sau în orice altă stare
care afectează ce servește o predicție — e strict observațională.

## 4. Validation Protocol Contract

- Metrici candidate: setul deja numit (Agreement, Divergence, Prediction
  Distance, Historical/Confidence Comparison) — formulele exacte rămân
  detaliu de implementare, nu de arhitectură.
- Disciplină statistică obligatorie: o singură metrică primară,
  pre-înregistrată înainte de testare; restul rămân explicit
  „exploratorii", niciodată motiv singur de verdict pozitiv — previne exact
  riscul de comparații multiple semnalat la §2, fără să împrumute
  mecanismul ADR-034.
- Prag minim de eșantion, analog cu `min_matches=200`/`MIN_SAMPLES_TO_TRAIN`
  deja existente în proiect — valoarea exactă, detaliu de implementare;
  existența pragului, obligatorie.
- Metrică de adevăr: exclusiv Brier/Log-loss/Accuracy, deja standardizate —
  nicio metrică nouă de evaluare inventată.
- Verdict binar: „surface-worthy" (declanșează propunerea T3a) sau
  „respins" (rămâne experiment logat, fără urmări, exact tratamentul deja
  aplicat feature-urilor respinse).

## 5. Integrare cu ADR-026

- T1 pentru rularea studiului de eșantionare/validare.
- T3a, doar dacă verdictul e pozitiv — propunerea de schimbare a politicii
  de serving (ADR-031), cu plan de rollback trivial (același flag de
  configurare deja definit la ADR-031: „revenire la comportamentul
  implicit... zero risc de date").
- Niciun state machine nou.

## 6. Non-Goals

Nu construiește Consensus Layer în UI · nu decide singur surfacing-ul
(doar propune, T3a, aprobat de om) · nu inventează metrici de acuratețe
noi · nu modifică ADR-031, Model Registry sau Promotion Service · nu
împrumută sau extinde mecanismul ADR-034.

## 7. Adversarial Check (auto-evaluare, furnizată de proprietarul produsului)

- Contradicții: niciuna.
- Responsabilități mutate: niciuna — nevoia de eșantionare rămâne în
  scope-ul propriu al ADR-033, nu împinsă înapoi spre ADR-031; disciplina
  statistică internă rămâne separată de ADR-034.
- Încălcări de Freeze: niciuna.
- Dependențe ascunse: una identificată și rezolvată (persistarea
  eșantionului, absentă din ADR-031, acoperită acum explicit în scope-ul
  propriu al ADR-033).
- Overengineering: respins un „framework general de experimentare cu
  metrici" — rămâne un protocol minim, cu o singură metrică primară
  pre-înregistrată; respinsă construcția UI acum.

| Observație | Severitate |
|---|---|
| Studiul rulează prospectiv (de la activare), nu retroactiv — un istoric relevant nu există înainte de ADR-031 | Minor — implică o fereastră de timp până la un eșantion suficient; de documentat explicit, nu blochează |
| Pragul minim de eșantion — valoare exactă nedeclarată | Minor — analog cu precedentele deja acceptate la ADR-030 (TTL), detaliu de implementare |

Zero observații Blocking sau Major (auto-evaluare).

---

## Review independent (Claude, la cererea explicită de aprobare a Planning Draft-ului)

**Verificare de consistență cu implementarea reală existentă**: confirmat
direct în cod — `oracle_engine.py::MatchPrediction.raw_predictions` (ADR-031)
nu e persistat nicăieri azi (nici în `match_history`, nici în alt tabel);
`build_raw_predictions()` e o funcție pură, apelată doar în memorie, la
fiecare `evaluate_match()`. Confirmă exact observația §2: nu există azi
niciun istoric de perechi brute — orice eșantion pentru ADR-033 trebuie să
fie strict prospectiv.

**O ambiguitate reală, nu doar stilistică, în §2**, care merită rezolvată
explicit la Clarification Pass, nu presupusă tacit: formularea „o rulare T1
**periodică/prospectivă** care captează perechile **la momentul
predicției**" combină două mecanisme diferite —

1. „la momentul predicției" descrie inerent un efect secundar la
   **serving-time** (un hook în calea live, analog cu
   `challenger_shadow.log_shadow_for_active_challenger()` din ADR-017/018,
   apelat din interiorul `evaluate_match()` sau imediat după el) — captura
   nu poate fi reconstituită retroactiv de un job periodic, fiindcă nimic
   nu persistă azi `raw_predictions`.
2. „T1 periodică" descrie un mecanism diferit — un job programat (analog
   `continuous_learning.yml`), care CITEȘTE stare deja persistată, nu care
   o produce la momentul predicției.

Cele două nu pot fi același mecanism. Dacă intenția e (1) — un nou punct de
atingere a `oracle_engine.py` (sau a apelantului lui — `app.py`,
`sync/run_daily.py`), simetric cu Shadow Adapter-ul deja existent — asta e
o decizie de arhitectură reală (o nouă graniță de tip „Adapter", nu doar un
„detaliu de implementare") și ar trebui explicită în Ownership (§3), nu
lăsată ambiguă în §2. Dacă intenția e (2) — un job periodic — atunci
trebuie spus clar CE citește acel job, dacă nu ieșirile brute în sine (care
nu sunt persistate).

Nu tratez asta ca Blocking (nu contrazice Architecture Freeze, nu mută
responsabilități în afara scope-ului ADR-033), dar nici ca Minor pur — o
clasific **Major, de rezolvat explicit la Clarification Pass**, fiindcă
determină direct dacă implementarea ADR-033 atinge sau nu `oracle_engine.py`
(precedent sensibil — singurul alt ADR din serie care a atins acel fișier a
fost ADR-031, cu o singură adăugare aditivă de câmp, nu un nou apel activ).

**Restul Planning Draft-ului** (Scope, Ownership pentru celelalte operații,
Validation Protocol Contract, integrarea T1/T3a cu ADR-026, Non-Goals) —
consistent, nu introduce contradicții cu ADR-026/028/030/031 frozen, respectă
KISS (o singură metrică primară, fără framework general), respectă
Separation of Concerns (nu împrumută mecanismul ADR-034).

**Verdict**: Blocking: 0. Major: 1 (mecanismul exact de captare a
eșantionului — serving-time hook vs. job periodic — trebuie clarificat
explicit, nu presupus). Minor: 2 (cele auto-identificate mai sus, acceptate
ca atare).

Planning Draft aprobat pentru trecerea la Clarification Pass, **cu
condiția** ca ambiguitatea de mecanism de eșantionare să fie primul punct
tratat acolo.

---

## Clarification Pass — rezolvare live (înlocuiește §2 din Planning Draft)

Rezolvare confirmată explicit de proprietarul produsului, cu precizarea
critică de terminologie reținută mai jos:

> ADR-033 reutilizează **tiparul arhitectural** al Challenger
> (capture → evaluate), nu implementarea Challenger și nici infrastructura
> lui.

**Precizare deliberată, reținută verbatim** — formularea „simetric cu
`challenger_shadow.py`" (folosită de Claude la review-ul Planning Draft-ului)
e respinsă explicit ca înșelătoare: poate induce ideea unei infrastructuri
sau tabele partajate. Formularea corectă, înghețată:

> ADR-033 urmează același tipar arhitectural în două faze (capture la
> serving, evaluare periodică), dar utilizează propria infrastructură de
> eșantionare, independentă de Shadow Testing.

### Faza 1 — Capture (serving-time)

- Adapter observațional nou, minimal, **propriu ADR-033** — NU
  `challenger_shadow.py`, NU o extensie a lui.
- Apelat din calea de serving, imediat după ce ADR-031 produce
  `raw_predictions`.
- Persistă perechea `(fixture_id, raw_predictions, timestamp, engine
  versions)` într-o tabelă proprie, separată de `shadow_predictions`.
- Nu modifică Prediction Pipeline. Nu influențează răspunsul către
  utilizator — strict observațional, aceeași regulă deja aplicată Shadow
  Adapter-ului (dar prin infrastructură proprie, nu împrumutată).

### Faza 2 — Evaluation (T1, periodic)

- Rulează separat de Faza 1.
- Citește exclusiv eșantionul propriu deja capturat + rezultatele reale din
  `match_history`.
- Calculează metricile candidate ADR-033 (§4, Validation Protocol Contract).
- Produce verdictul și, dacă pozitiv, propunerea T3a.

### De ce contează distincția

- **Shadow Testing** validează Challengeri ML — infrastructură deja
  existentă (ADR-017/018), scop: promovare de model.
- **Consensus Validation** (acest ADR) validează dacă o metrică de acord
  între motoare are valoare predictivă — scop: decizie de surfacing în UI.

Ambele folosesc același *pattern* de execuție (capture live → evaluare
periodică) — un tipar acum stabilit ca reutilizabil în proiect pentru orice
validare empirică viitoare care are nevoie de corelare cu rezultate reale,
nu doar pentru Challenger — dar fiecare persistă propriul eșantion, în
propria infrastructură. Zero dependență artificială între ele; eliminarea
uneia nu afectează cealaltă.

Acest lucru închide punctul Major fără să introducă un tipar arhitectural
nou și fără să creeze o dependență artificială de Challenger Framework —
exact cerința inițială.

## §2 (Dependency Verification) — versiune finală, înlocuiește draft-ul

Declarată deja: #6 (ADR-031, frozen) — are nevoie de ieșiri brute,
comparabile, expuse.

Dependință reală, identificată la review: ADR-031 expune ieșirile brute la
momentul cererii (serving-time), dar nu specifică nicio persistare istorică
a lor. ADR-033 are nevoie de un eșantion acumulat în timp pentru a putea
corela ceva. Nu e o contradicție cu ADR-031 (care nu promitea persistare,
doar expunere) — e o nevoie proprie, acoperită acum explicit prin tiparul
în două faze de mai sus (capture propriu la serving-time + evaluare T1
periodică), cu infrastructură proprie, independentă de Shadow Testing.

Nicio dependință de ADR-034 — corecția de comparații multiple din ADR-034 e
scop-ată explicit la decizii T3a bazate pe test statistic repetat; studiul
de validare al ADR-033 e T1, nu T3a. ADR-033 își definește propria
disciplină statistică internă (§4), fără să împrumute sau să extindă
mecanismul ADR-034.

---

# ADR-033 — ADR Final (sinteză completă)

## Context

Consensus Layer a fost propus inițial (Vision & Target Architecture) ca
strat arhitectural comis, cu un set de metrici candidate (Agreement Score,
Divergence Score, Prediction Distance, Historical Accuracy Comparison,
Confidence Comparison). Independent Architecture Assessment §5 a corectat
asta: comiterea infrastructurii înainte de a-i dovedi valoarea contrazice
direct disciplina proprie a proiectului („verificat, nu presupus" — 6
feature-uri deja respinse prin ablație pe 53.409 meciuri reale). Consensus
trebuie să-și câștige locul empiric, exact ca orice alt feature.

ADR-031 (frozen) satisface precondiția: există acum ieșiri brute,
comparabile, trasabile, la granița de serving. ADR-026 (frozen) a rezervat
deja forma contractului: T1 pentru studiu, T3a separat dacă surfacing-ul e
recomandat — niciodată o decizie unilaterală a studiului însuși.

## Problem Statement

Fără validare empirică, expunerea metricilor de Consensus riscă să
introducă un semnal plauzibil, dar nedovedit, într-un produs a cărui
întreagă valoare stă pe judecată verificată, trasabilă — exact eșecul pe
care disciplina de ablație a proiectului există s-o prevină. ADR-033 închide
acest gol: definește cum se testează dacă divergența/acordul poartă
informație reală, înainte de orice angajament de UI.

## Decision

ADR-033 nu construiește Consensus Layer. Definește protocolul prin care
Consensus Layer își câștigă, sau nu, dreptul de a exista.

Concret: eșantionare prospectivă, în două faze (capture la serving-time,
prin adapter propriu → evaluare periodică T1, cu infrastructură proprie,
independentă de Shadow Testing — vezi Clarification Pass mai sus) a
perechilor de predicții brute (expuse deja de ADR-031) + rezultate reale
(`match_history`, canonic), corelate cu Brier/Log-loss/Accuracy —
metricile deja standardizate în proiect — sub o disciplină de
pre-înregistrare (o singură metrică primară, restul exploratorii), cu un
prag minim de eșantion, producând un verdict binar.

## Scope

**Intră**: adapterul de capturare propriu (Faza 1, serving-time); protocolul
de eșantionare T1 (Faza 2, prospectiv, proprietate exclusivă a ADR-033);
calculul metricilor candidate; corelația cu acuratețea reală; verdictul
explicit; propunerea T3a separată, doar dacă verdictul e pozitiv.

**NU intră**: construirea Consensus Layer în UI; decizia finală de
surfacing (rămâne umană, prin T3a); orice modificare a ADR-031, Model
Registry, Promotion Service, `shadow_testing`.

## Validation Protocol Contract

- Metrici candidate: Agreement Score, Divergence Score, Prediction
  Distance, Historical/Confidence Comparison — formulele exacte, detaliu de
  implementare.
- Disciplină de pre-înregistrare: o singură metrică primară, declarată
  înainte de testare; restul, exploratorii, niciodată motiv singur de
  verdict pozitiv.
- Prag minim de eșantion: obligatoriu ca existență (analog
  `min_matches=200`/`MIN_SAMPLES_TO_TRAIN`), valoarea exactă rămâne detaliu
  de implementare.
- Metrică de adevăr: exclusiv Brier/Log-loss/Accuracy, deja standardizate —
  nicio metrică nouă inventată.
- Imutabilitatea eșantionului: o pereche capturată pentru un fixture nu se
  recalculează niciodată, indiferent de promovări ulterioare — previne
  hindsight bias. Imutabilitatea se aplică perechii individuale, nu
  eșantionului agregat — un studiu nou poate folosi un eșantion mai mare,
  acumulat pe o fereastră mai lungă (aceeași logică de acumulare progresivă
  deja folosită de `evaluate_experiment()`).
- Verdict binar: „surface-worthy" (dovadă suficientă pentru a justifica
  deschiderea unei propuneri T3a — nu echivalent cu aprobare) sau „respins"
  (rămâne experiment logat, fără urmări permanente).
- Reluare: un verdict „respins" nu interzice definitiv ipoteza — un studiu
  nou e o rulare T1 nouă, cu propriul eșantion, propriul verdict.

## Ownership

| Operație | Cine are voie |
|---|---|
| Capturarea perechii la serving-time (Faza 1) | Exclusiv adapterul propriu ADR-033, apelat din calea de serving imediat după `raw_predictions` (ADR-031) — infrastructură proprie, independentă de `challenger_shadow.py`/`shadow_predictions` |
| Colectarea/citirea eșantionului pentru studiu (Faza 2) | Exclusiv procesul de eșantionare ADR-033, T1, citește doar propria tabelă + `match_history` |
| Calculul metricilor candidate | Funcție pură, în scope-ul acestui ADR |
| Corelarea cu acuratețea reală | Reutilizează exclusiv Brier/Log-loss/Accuracy |
| Verdictul | Procesul ADR-033 |
| Propunerea T3a (dacă verdict pozitiv) | Procesul ADR-033, ca eveniment separat de T1-ul studiului |
| Decizia finală de surfacing | Exclusiv om, prin aprobarea T3a |

**Granița observațională**: ADR-033 nu influențează niciodată predicțiile
produse, nu schimbă ponderi, nu schimbă modele, nu schimbă serving-ul.
Strict observațional — citește ce ADR-031 expune (prin propriul adapter de
capturare) și ce `match_history` conține, calculează, produce un verdict.
Nimic din acest proces nu poate afecta, direct sau indirect, calea de
predicție live.

## Integrare cu ADR-026

- T1 pentru rulările de eșantionare/studiu (Faza 2) — datele eșantionului
  (capturate în Faza 1) stocate separat, referențiate prin pointer din
  `automation_runs` (per Event Model — conținutul brut nu se copiază).
- T3a, exclusiv dacă verdictul e pozitiv — propunere separată de schimbare
  a politicii de serving (ADR-031), cu plan de rollback trivial (flag-ul
  deja definit la ADR-031).
- Mecanismul de stocare a eșantionului reutilizează, ca precedent de
  implementare, garda de imutabilitate deja folosită de două ori în proiect
  (`odds_history_immutability_guard`, `model_champions_guard`) — niciun
  tipar nou la nivel de gardă DB. Tabela însăși e nouă și proprie ADR-033
  (nu `shadow_predictions`).
- Niciun state machine nou.

## Non-Goals

Nu construiește Consensus Layer în UI · nu decide singur surfacing-ul · nu
inventează metrici de acuratețe noi · nu modifică ADR-031, Model Registry
sau Promotion Service · nu împrumută sau extinde mecanismul ADR-034 · nu
influențează, sub nicio formă, predicțiile, ponderile, modelele sau
serving-ul · **nu reutilizează infrastructura Shadow Testing** (tabelă,
adapter) — doar tiparul ei arhitectural în două faze.

## Dependencies

ADR-031 (frozen) — ieșiri brute, comparabile, expuse. `match_history`
(ADR-025, canonic) — sursa rezultatelor reale. Metricile deja standardizate
(Brier/Log-loss/Accuracy). Precedentul de imutabilitate (`odds_history`,
`model_champions`) — reutilizat ca gardă DB, nu ca tabelă/infrastructură.

## Consequences

- Odată înghețat, acest ADR închide întregul drum critic al seriei vNext
  (ADR-026→028→030→031→033).
- Consensus Layer fie graduează (printr-o propunere T3a separată, ulterior
  aprobată explicit), fie rămâne o respingere documentată, onestă — ambele
  rezultate închid riscul semnalat în Independent Assessment („comis
  înainte de a fi câștigat").
- Stabilește un tipar repetabil (capture la serving → evaluare periodică,
  cu infrastructură proprie per validare) pe care orice semnal speculativ
  viitor de produs îl poate urma — fără să creeze o dependență artificială
  de Challenger Framework de fiecare dată.

## References

Vision & Target Architecture · Independent Architecture Assessment §5 ·
Final Strategic Blueprint · Execution Roadmap · Final Pre-Freeze Review ·
ADR-026 (frozen) · ADR-031 (frozen) · ADR-033 Planning Draft · ADR-033
Clarification Pass (rezolvată live, vezi mai sus).

## Open Questions

1. TTL propriu pentru eventuala decizie T3a — nu declarat, per decizia
   explicită de a nu inventa o valoare doar pentru închiderea documentului
   (același precedent ca la ADR-030).
2. Pragul minim de eșantion — valoare exactă, detaliu de implementare,
   nedeclarat aici.
3. Fereastra de timp până la un eșantion suficient (start prospectiv, fără
   istoric anterior ADR-031) — de documentat, nu blochează.
4. Cele două întrebări moștenite de la ADR-026 (fallback TTL generic;
   definiția „aprobator") rămân deschise, neatinse de acest ADR.

---

**ADR-033 Final e pregătit pentru Etapa 4/4 (Freeze) — ultimul pas al
drumului critic.** Blocking: 0. Major: 0 (rezolvat live, vezi Clarification
Pass mai sus). Minor: 4 (Open Questions, niciuna blocantă, precedent identic
cu ADR-026/030).
