# ID-025-02 — Historical Reconciliation Engine

## Ce este acest document

**Implementation Design, nu ADR.** ID-025-01 a fixat algoritmul determinist de
selecție/merge/marcare pentru **un grup** de duplicate. Acest document descrie
**motorul** care aplică acel algoritm pe scară — cum se descoperă grupurile, cum
se execută în loturi, cum se comportă la eroare parțială, ce raportează — pentru
corpusul cunoscut azi (3.501 grupuri istorice + 3 active, ADR-024) și pentru orice
grup viitor descoperit prin aceeași metodă.

**Scop strict**: doar motorul de execuție. Nu redefinește algoritmul de selecție
(ID-025-01, neschimbat, consumat ca atare). Nu descrie migrarea writerilor
(ID-025-03), constrângerea de bază de date (ID-025-04), criteriul de acceptanță
(ID-025-05), sau playbook-ul de rollback (ID-025-06).

## Cele două moduri de operare (mapate direct pe ADR-025)

| Mod | Corespondență ADR-025 | Scriere pe producție? |
|---|---|---|
| **DRY-RUN** | Faza 2 | **Niciodată** — calculează tot, nu scrie nimic |
| **EXECUTE** | Faza 3 (pilot, scop limitat) și Faza 4 (complet) | Da |

Ambele moduri rulează **exact același cod** de descoperire + clasificare + decizie
— singura diferență e dacă rezultatul (merge + marcaj) se scrie sau doar se
raportează. Asta garantează că raportul DRY-RUN reflectă exact ce s-ar întâmpla la
EXECUTE, fără divergență de logică între cele două moduri.

## Descoperirea grupurilor

Un grup (definit în ID-025-01) se identifică prin interogare pe cheia naturală
normalizată: toate rândurile din `match_history` grupate după
`(normalize_team_name(home_team), normalize_team_name(away_team), kickoff_date)`,
unde mai mult de un rând fizic există pentru aceeași cheie.

Motorul **nu presupune** că toate rândurile relevante pentru un grup sunt deja
normalizate identic în coloanele stocate — aplică `normalize_team_name()` la
momentul grupării (aceeași funcție folosită deja de `match_key()`,
`normalize_and_dedupe()`, `update_results_in_supabase()`), nu se bazează pe
egalitate exactă de string pe coloanele brute.

**Criteriul explicit de „deja reconciliat"**: un grup e considerat reconciliat
**dacă și numai dacă toate rândurile lui necanonice au `superseded_by` populat
(nenul)**. Un grup cu rândul canonic parțial completat dar cu rânduri necanonice
încă nemarcate NU e considerat reconciliat — rămâne eligibil pentru procesare (vezi
și „Reluare după întrerupere" mai jos, unde tranzacția per grup garantează că
această stare intermediară nu poate exista în practică). Astfel de grupuri sunt
excluse din descoperire de la bun început — consistent cu proprietatea „nu se
re-evaluează" din ID-025-01.

## Scopare (full vs. subset)

Motorul acceptă un parametru de scopare opțional (interval de date, listă explicită
de perechi echipe+dată, sau „toate"), pentru a permite:

- **Faza 3 (pilot)**: rulare pe un subset izolat, mic, verificabil manual — analog
  pilotului IRL folosit la ADR-023 Phase 2.
- **Faza 4 (completă)**: rulare fără scopare, pe tot corpusul.

Scoparea nu schimbă logica de decizie (ID-025-01) — doar limitează ce grupuri intră
în bucla de procesare a rulării curente.

## Bucla de procesare (per grup)

Pentru fiecare grup descoperit, în ordine (ordinea exactă între grupuri e
irelevantă — grupurile sunt independente, fără stare comună). Consecință directă a
acestei independențe: ordinea de procesare poate fi **arbitrară**, rezultatul final
e **stabil** indiferent de ordine, iar procesarea grupurilor e **sigur
paralelizabilă** (fiecare grup are propria tranzacție, fără resurse partajate între
grupuri) — motorul nu e obligat să paralelizeze, dar nimic din algoritm îl
împiedică.

Motorul **nu modifică niciodată cheia naturală** (`home_normalizat`,
`away_normalizat`, `kickoff_date`) a niciunui rând, canonic sau necanonic — doar
coloanele de feature-uri/statistici (Pasul 3, ID-025-01) și coloanele de audit
(Pasul 4, ID-025-01).

Pașii per grup:

1. Verificare **HARD CONFLICT** (ID-025-01) — dacă există, grupul e exclus (fără
   efect lateral, conform ID-025-01), înregistrat în raport la secțiunea
   „excluse — HARD CONFLICT", procesarea trece la grupul următor.
2. Rezolvarea sursei fiecărui candidat (`resolve_source()`, ID-025-01) — dacă un
   candidat are sursă necunoscută, tot grupul e exclus (Regula #8), înregistrat la
   „excluse — sursă necunoscută", trece la grupul următor.
3. Selecția rândului canonic + merge non-destructiv câmp cu câmp (ID-025-01, Pașii
   1-3) — calculat întotdeauna, indiferent de mod.
4. **Doar în modul EXECUTE**: scrierea efectivă — UPDATE pe rândul canonic (câmpurile
   completate) + UPDATE pe fiecare rând necanonic (`superseded_by`/`superseded_at`/
   `superseded_reason`, ID-025-01 Pasul 4). **Toate aceste UPDATE-uri, pentru un
   singur grup, rulează într-o singură tranzacție de bază de date** — fie toate
   reușesc, fie niciuna nu se aplică. Această tranzacție per grup e exact ce
   garantează proprietatea „fie complet, fie deloc" folosită mai jos (secțiunea
   „Reluare după întrerupere") — fără ea, o întrerupere exact între scrierea
   rândului canonic și marcarea rândurilor necanonice ar produce o stare
   intermediară nesigură (rândul canonic completat, dar rândurile necanonice încă
   nemarcate — vezi și criteriul explicit din „Descoperirea grupurilor"). **Doar în
   modul DRY-RUN**: nicio scriere, doar înregistrare în raport a ce s-ar fi scris —
   nu se deschide nicio tranzacție.

## Batching și paginare

Descoperirea grupurilor și scrierea rezultatelor rulează în loturi (batch) — reutilizează
tiparul deja existent în proiect (`upsert_matches_bulk`, batch de 250;
`bulk_update_features`, batch implicit) pentru a reduce numărul de round-trip-uri
HTTP către Supabase. Dimensiunea exactă a lotului e un parametru de configurare, nu
o decizie fixată de acest document.

**Batch-ul e strict o optimizare de transport, nu o unitate de tranzacție.**
Tranzacția e per grup (vezi „Bucla de procesare" de mai sus), niciodată per batch —
un batch de N grupuri execută N tranzacții independente, nu una singură care le
acoperă pe toate. Eșecul tranzacției unui grup nu afectează, în niciun fel, celelalte
grupuri din același batch, indiferent de ordinea în care au fost trimise.

## Gestionarea erorilor

Eșecul scrierii pentru **un singur grup** (ex. eroare de rețea la UPDATE) nu oprește
procesarea celorlalte grupuri — se înregistrează în raport la secțiunea „erori",
motorul continuă cu grupul următor (același comportament fail-soft-per-item deja
folosit în `sync/backfill_features.py::run_backfill()` și în cele două servicii de
backfill existente, `MatchStatsBackfillService`/`BackfillOddsService`).

Un grup cu eroare de scriere rămâne **nereconciliat** (niciun `superseded_by` setat)
— va fi redescoperit și reîncercat la următoarea rulare, fără nicio acțiune
suplimentară necesară (idempotență, ID-025-01).

## Reluare după întrerupere (nivel motor, nu doar per-grup)

O rulare EXECUTE întreruptă la mijloc (timeout, crash, oprire manuală) e sigură de
reluat prin **rerulare completă, fără scopare** — exact tiparul „Varianta A" deja
folosit repetat în acest proiect (backfill ELO, activare MOV V2_damped, Phase 3
ADR-023). Grupurile deja reconciliate sunt excluse automat de la Descoperire (vezi
mai sus); grupurile neatinse sau întrerupte la mijloc sunt redescoperite și
reprocesate identic. Nu există o stare intermediară „pe jumătate reconciliat" la
nivel de grup — Pasul 4 din ID-025-01 scrie fie complet, fie deloc, per grup (dacă
motorul scrie mai întâi rândul canonic și apoi rândurile necanonice, o întrerupere
exact între aceste două scrieri ar lăsa un grup cu rândul canonic completat dar
rândurile necanonice nemarcate încă — sigur de reluat, fiindcă merge-ul e monoton
(ID-025-01) și marcarea `superseded_by` e idempotentă).

## Interacțiune cu writeri concurenți (limitare cunoscută, nu rezolvată aici)

Motorul rulează în timp ce alți writeri (sync zilnic, predicții live) pot scrie
concurent în `match_history`. Fiindcă ID-025-01 garantează merge non-destructiv
(niciodată suprascriere), o scriere concurentă pe un rând canonic nu poate fi
corupă de motor, și invers.

**Limitare cunoscută**: până la finalizarea ID-025-03 (Writer Migration) și Faza 6
din ADR-025 (constrângerea UNIQUE), writerii existenți pot încă crea rânduri NOI
duplicate pentru un meci deja reconciliat de acest motor (exact tiparul deja activ
azi la World Cup 2026 — `odds_`/`espn_`). Acest motor **nu previne** recurența — o
elimină doar pentru corpusul deja existent la momentul rulării. Previnerea
structurală a recurenței rămâne responsabilitatea Fazei 6/ID-025-04, nu a acestui
document. Consecință operațională: dacă trece un interval mare de timp între Faza 4
(reconciliere completă) și Faza 6 (constrângere UNIQUE), poate fi necesară o
rerulare a acestui motor imediat înainte de Faza 6, pentru a prinde orice duplicat
nou apărut între timp — decizie de secvențiere, nu de acest document.

## Raportare

Fiecare rulare (DRY-RUN sau EXECUTE) produce un raport cu, minim:

- Total grupuri descoperite (în scopul rulării curente).
- Grupuri excluse — HARD CONFLICT (număr + listă, pentru revizuire manuală).
- Grupuri excluse — sursă necunoscută (număr + listă).
- Grupuri reconciliate cu succes (număr).
- Grupuri cu eroare de scriere (număr + listă, doar în EXECUTE).
- Per coloană din `FEATURE_COLUMNS`: câte valori au fost completate prin merge
  (Pasul 3, cazurile 2 și 3 din ID-025-01) — util pentru a verifica dacă rezultatul
  se aliniază cu observația empirică din ADR-024 (`fd_` mai complet decât
  `kaggle_`).
- Durata totală a rulării.
- Grupuri procesate pe secundă (throughput, util pentru benchmark).
- Total rânduri afectate (canonice completate + necanonice marcate).

Formatul exact (fișier, tabelă Supabase, log structurat) rămâne detaliu de
implementare, nu fixat aici.

## Proprietăți garantate de acest motor

- **Idempotent la nivel de rulare completă**: rerularea motorului de la zero, de
  câte ori e nevoie, converge întotdeauna spre aceeași stare finală — moștenit
  direct din idempotența algoritmului per-grup (ID-025-01).
- **Sigur de întrerupt oricând**: nicio fereastră de timp în care o întrerupere ar
  produce o corupere de date — moștenit din monotonia merge-ului (ID-025-01).
- **DRY-RUN și EXECUTE folosesc identic codul de decizie**: elimină riscul ca
  raportul de simulare să nu reflecte realitatea rulării efective.
- **Fail-soft per grup, fail-closed per decizie**: o eroare tehnică pe un grup nu
  oprește restul rulării; o ambiguitate reală (HARD CONFLICT, sursă necunoscută)
  oprește DOAR acel grup, niciodată prin aproximare tăcută.

## Ce NU acoperă acest document

- Regula de selecție/merge/marcare în sine — ID-025-01 (neschimbată, consumată ca
  atare).
- Cum previne recurența pe termen lung (constrângere UNIQUE) — ID-025-04.
- Cum se adaptează writerii existenți să nu mai creeze duplicate noi — ID-025-03.
- Criteriul exact de acceptanță pentru „reconciliere completă" (0 grupuri rămase) —
  ID-025-05.
- Ce se face dacă acest motor a scris deja pe producție și trebuie anulat —
  ID-025-06 (Rollback Playbook, deja schițat parțial în ADR-025 — acest document
  doar confirmă că mecanismul de merge/marcare pe care îl execută e compatibil cu
  acel playbook, nu îl redefinește).

## Referințe

- ID-025-01 — Canonical Row Selection (algoritmul consumat de acest motor)
- ADR-025 — Match Identity Implementation Strategy (Fazele 2-4, Rollback Strategy)
- ADR-024 — Canonical Match Identity & Data Contract (corpusul cunoscut: 3.501 + 3
  grupuri)
- Precedent operațional: `sync/backfill_features.py::run_backfill()` (batching,
  gestionare erori fail-soft, tiparul „Varianta A" de reluare)
