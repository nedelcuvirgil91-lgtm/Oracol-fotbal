# ADR-033 — Consensus Layer Validation Protocol

**Status**: Planning Draft (Etapa 1/4 din 4 — Planning Draft → Clarification
Pass → ADR Final → Freeze). Ultimul pas al drumului critic de execuție
Football Oracle vNext: ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030
(Frozen) → ADR-031 (Frozen) → **ADR-033 (în lucru)**.

**Reconstrucție**: Document nescris pe disc în timp real până acum — de
această dată scris LIVE, pe măsură ce se produce (nu retroactiv, ca restul
seriei), exact pentru a închide golul sistemic descoperit la începutul
acestei etape. Nu redactează ADR-ul final — doar Planning Draft.

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
