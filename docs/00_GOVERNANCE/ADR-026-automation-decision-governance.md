# ADR-026 — Substrat de guvernanță pentru automatizare (automation_runs + decision_feed)

**Status**: FROZEN. Primul ADR din drumul critic de execuție Football
Oracle vNext: **ADR-026 (Frozen)** → ADR-028 (Frozen) → ADR-030 (Frozen) →
ADR-031 (Frozen) → ADR-033 (Frozen).

**Implementat**: PR #4, merge-uit în `main`. Acest fișier reprezintă
contractul normativ corespunzător implementării deja existente în `main`
— nu o propunere, un document retroactiv al deciziei deja aplicate.

**Reconstrucție**: Document nescris pe disc în timp real — declarat Frozen
exclusiv în istoricul conversației. Descoperit ca gol sistemic
(`docs/00_GOVERNANCE/` nu conținea niciun fișier `ADR-026`...`ADR-033`,
deși seria a fost tratată ca Frozen) în etapa de pregătire a ADR-033.
Reconstruit secțiune cu secțiune, exact cum a fost furnizat de
proprietarul produsului — nu se completează sau presupune conținut lipsă.
**Data reconstrucției**: 2026-07-17.

## Dependencies

Niciuna în cadrul drumului critic vNext — ADR-026 e fundația (primul).
Presupune infrastructura Learning Core pre-existentă (ADR-015…019) și
tiparele de stare deja folosite în proiect (ex. `sync_status`), reutilizate
ca precedent pentru `automation_runs`/`decision_feed` (detaliu menționat în
istoricul de proiect, nu confirmat verbatim în acest fragment reconstruit).

**Dependenți din drumul critic** (verificat prin referințe încrucișate în
celelalte documente reconstruite): ADR-028, ADR-030 și ADR-033 declară
explicit ADR-026 ca dependință (contractul `automation_runs` + tiering
T1/T2/T3a/T3b).

---

## Planning Draft — Final Clarification Pass

Doar cele trei răspunsuri cerute. Nimic altceva din Planning Draft nu se modifică.

### 1. Producer Failure

Regulă: doar subsistemul proprietar poate produce `approved → committed` sau
`approved → commit_failed` (deja stabilit în §2/§4). Dacă acel subsistem
dispare definitiv, nimeni nu preia dreptul de a produce acele tranziții în
locul lui — ar însemna să se pretindă cunoaștere despre o scriere care nu
s-a confirmat niciodată, ceea ce încalcă direct regula North Star #6
(nicio afirmație despre stare canonică fără confirmare explicită, adevărată).

În schimb, contractul extinde mecanismul de staleness deja definit la §6
(care azi monitorizează doar `pending`) să monitorizeze și starea
`approved`: dacă o decizie rămâne `approved` peste un TTL de execuție
(distinct de TTL-ul de decizie din §6), tranziția automată produsă e
`approved → orphaned` — niciodată `committed` (nimeni nu poate confirma
fals succesul) și niciodată o expirare silențioasă echivalentă cu
`pending → expired` (aceea ar șterge urma unei aprobări reale, care chiar
a avut loc).

`orphaned` nu e stare terminală silențioasă — rămâne activ vizibilă
(tratament echivalent cu T3b, „necesită acknowledgment") până un om o
închide explicit prin exact una din două căi: (a) declanșează un ciclu nou
de propunere — cu run/decizie noi, conform regulii deja stabilite de
non-resurrectare (§4: nicio tranziție înapoi dintr-o stare
terminală/blocată), sau (b) marchează explicit „abandonat, nu se mai
urmărește". Responsabilul detectării e mecanismul de staleness însuși
(singura parte structural garantată să existe indiferent de sănătatea
vreunui producător individual) — nu un nou component, extensia aceluiași
mecanism din §6.

### 2. Idempotency

Regulă generală, aplicabilă uniform tuturor categoriilor: fiecare producer
ADR declară o cheie de identitate stabilă pentru propriile tipuri de
rulare/decizie (ex. `(algorithm_family, league_scope)` pentru retraining,
`(schema_object_identifier)` pentru drift, `(dataset_source, cutoff_window)`
pentru reconciliere) — ADR-026 nu definește cheile per-domeniu (rămân
responsabilitatea fiecărui producător, consistent cu granularitatea deja
delegată lui ADR-032), dar impune ca ele să existe, ca regula de mai jos să
fie mecanic aplicabilă:

- **Reuse (rulare nouă respinsă)**: dacă există deja un run în
  `queued`/`running` pentru aceeași cheie, noul declanșator produce
  `skipped` (motiv: „duplicat concurent") — nu se creează un run nou, nu se
  execută de două ori aceeași lucrare.
- **New run, dar nu neapărat decizie nouă**: dacă ultima rulare pentru
  aceeași cheie s-a încheiat (`completed`/`failed`), o rulare nouă e
  permisă (starea reală s-ar putea fi schimbat între timp). Dacă însă
  rularea anterioară a produs deja o decizie încă deschisă
  (`proposed`/`pending`/`approved`) pentru aceeași cheie, rularea nouă nu
  creează un al doilea element în Decision Feed — actualizează dovada
  celui existent, cu tranziția/jurnalizarea schimbării (nu suprascriere
  silențioasă — orice actualizare rămâne o tranziție logată, per §7).
- **Ignore**: dacă nu există nimic nou de raportat față de ultima stare
  cunoscută și nu există nicio decizie deschisă în așteptare, procesul
  poate să nu producă niciun rând nou. Nu e o a patra categorie separată —
  e un caz particular al lui `skipped`, cu motiv „stare identică, nimic de
  raportat" (respectă KISS: reutilizează o stare deja definită, nu
  introduce una nouă).

### 3. Atomicitate

Cele două state machine-uri nu sunt atomice împreună — fiecare e atomic
separat, legate prin referință (`run_id`), reconciliate prin retry
idempotent, nu prin tranzacție distribuită.

Justificare: a forța atomicitate cross-machine între „istoricul execuției"
și „fluxul de aprobare" ar cupla artificial două preocupări conceptual
distincte (Separation of Concerns, cerută explicit) pentru un câștig
marginal de siguranță, cu cost real de complexitate (KISS).

Contractul exact pentru scenariul „execuția reușește, crearea deciziei
eșuează":

- Rularea rămâne `completed`, fără decizie asociată — aceasta e o stare
  intermediară definită, detectabilă, nu o corupție și nu o pierdere
  silențioasă.
- Fără rollback al rândului de execuție — execuția chiar a avut loc; a-l
  retrage ar fi o minciună în jurnal.
- Retry, nu tranzacție: crearea deciziei pentru o rulare `completed`,
  clasificată T3, fără decizie asociată e ea însăși o operație idempotentă,
  reîncercabilă (folosește exact regula de idempotency de la §2 — nu
  creează un al doilea element dacă unul există deja, îl creează dacă
  lipsește).
- Detectabilitate structurală: o rulare `completed` de tip T3 fără decizie
  asociată e o anomalie interogabilă direct (aceeași capacitate de „count
  by status" deja cerută la §6 pentru backlog) — nu depinde de un mecanism
  nou, doar de interogarea deja impusă tabelului.
- Runurile `failed` nu produc niciodată decizie (deja stabilit) — deci
  acest scenariu nu se aplică lor; ambiguitatea era exclusiv pentru cazul
  `completed` fără decizie.

Aceste trei clarificări închid gap-urile de reziliență fără să adauge
componente, fără să mute responsabilități, fără să atingă drumul critic
sau Architecture Freeze — extind mecanismele deja definite (staleness,
idempotency, jurnalizare) la cazurile de margine semnalate, nu introduc
altele noi.

Nu identific niciun risc Blocking sau Major rămas.

**ADR-026 Planning Draft is frozen and ready for final ADR drafting.**

---

## [Secțiuni lipsă — de completat pe măsură ce sunt furnizate]

- Planning Draft inițial (Context/§1-§7 referite mai sus)
- Clarification Pass
- ADR Final (Status/Context/Decizie/Consecințe)
- Freeze
