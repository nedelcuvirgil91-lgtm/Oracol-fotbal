# ID-025-05 — Validation

## Ce este acest document

**Implementation Design, nu ADR.** ID-025-01…04 au definit patru mecanisme —
selecție canonică, motor de reconciliere, migrare writeri, constrângere de bază de
date — fiecare cu propriile „Proprietăți garantate". Acest document **nu introduce
nicio proprietate nouă**: descrie exclusiv cum se demonstrează, cu dovezi
verificabile, că fiecare proprietate deja promisă chiar se ține, și cum se decide,
la fiecare tranziție de fază, dacă migrarea poate continua.

**Scop strict**: (1) criteriile Go/No-Go dintre fazele ADR-025, în ordinea reală de
execuție (nu ordinea brută a tabelului ADR-025 — vezi mai jos); (2) planul de
verificare a proprietăților promise de ID-025-01/02/03/04, prin teste de idempotență
și concurență; (3) formatul minim al rapoartelor de validare. Nu descrie ce se face
dacă o validare eșuează după ce s-a scris deja pe producție — asta e ID-025-06
(Rollback Playbook).

## Ordinea reală validată de acest document

ADR-025 listează Faza 6 (constrângere UNIQUE) înaintea Fazei 7 (actualizare
writeri). ID-025-03 a semnalat deja că ordinea operațională corectă e inversă și a
fixat-o explicit: writerii se migrează **înainte** ca baza de date să înceapă să
respingă duplicate. Acest document validează ordinea reală de execuție (reconciliere
→ writeri → constrângere), nu ordinea brută a tabelului — consecvent cu nota deja
stabilită în ID-025-03, fără să redeschidă ADR-025 sau să-i renumeroteze fazele.

## Cele două clase de validare

| Clasă | Întrebare | Ce verifică | Când rulează |
|---|---|---|---|
| **1 — Rezultatul migrării** | „S-a produs efectul așteptat al acestei faze?" | Stare de date/schemă, one-time, per tranziție de fază | O singură dată, la fiecare Phase Gate |
| **2 — Proprietăți promise** | „Se ține garanția deja declarată de ID-025-01/02/03/04?" | Comportament, prin teste dedicate (idempotență, concurență, fail-closed) | Cel puțin o dată înainte de Faza 10, repetabil oricând ulterior (regression) |

Clasa 1 nu redefinește nimic — doar confirmă, cu o interogare/verificare exactă, că
o fază și-a produs efectul. Clasa 2 nu redefinește nicio garanție — doar demonstrează
empiric o proprietate deja afirmată în documentul care o deține.

## Clasa 1 — Criterii Go/No-Go, per tranziție

Fiecare rând = o poartă. „Go" înseamnă că faza următoare poate începe; „No-Go"
oprește migrarea la faza curentă, fără a trece mai departe.

| ID | Tranziție | Criteriu Go | Ce declanșează No-Go |
|---|---|---|---|
| **Gate-01** | Faza 1 → Faza 2 | Coloanele de audit (`superseded_by`, `superseded_at`, `superseded_reason`) există, sunt nullable, DDL-ul a rulat aditiv fără a atinge rânduri existente | DDL parțial/eșuat; orice rând existent modificat de acest pas (nu ar trebui — pas pur aditiv) |
| **Gate-02** | Faza 2 → Faza 3 | Raportul DRY-RUN (ID-025-02) există, acoperă tot corpusul cunoscut (3.501 + 3 grupuri, ADR-024), zero scriere confirmată (verificare directă: nicio coloană de audit populată după rulare) | Raport incomplet; orice scriere detectată în modul DRY-RUN (contradicție cu ID-025-02) |
| **Gate-03** | Faza 3 → Faza 4 | Subsetul pilot verificat manual de Owner — fiecare rând canonic/superseded din pilot inspectat, corespunde exact cu ce a prezis DRY-RUN pentru același subset. Comparația se face **exclusiv asupra rezultatului final** (rândul canonic ales, valorile merge-uite, marcajele `superseded`) — ordinea internă în care motorul a procesat grupurile nu face parte din criteriu, fiind deja declarată irelevantă de ID-025-02 | Orice discrepanță de rezultat final între predicția DRY-RUN și EXECUTE pe pilot (ar însemna divergență de logică între moduri, contrazicând garanția explicită din ID-025-02) |
| **Gate-04** | Faza 4 → Faza 5 | Rularea completă (ID-025-02) s-a încheiat — raport final produs, inclusiv secțiunile „excluse — HARD CONFLICT" și „excluse — sursă necunoscută" | Rulare încă în curs sau întreruptă fără raport final (reluabilă per „Reluare după întrerupere", ID-025-02 — nu e un eșec, doar o stare „nu încă gata") |
| **Gate-05** | **Faza 5 → migrare writeri (ID-025-03)** | **Zero grupuri rămase, definit strict**: (a) zero grupuri cu >1 rând canonic pe cheia naturală normalizată, ȘI (b) toate grupurile rămase în stare HARD CONFLICT au fost rezolvate explicit înainte de activarea constrângerii — fie printr-o corecție de date urmată de re-rulare cu succes prin motor, fie printr-o decizie explicită, semnată de Owner, de excepție documentată (vezi observație critică mai jos). Criteriul e formulat pe starea datelor, independent de cum anume raportează un anumit motor de execuție grupurile excluse | Orice grup HARD CONFLICT nerezolvat, tratat tacit ca „acceptabil" fără decizie explicită; orice grup cu sursă necunoscută nerezolvat (provider nou neînregistrat în `SourceTrustProvider`) |
| **Gate-06** | Migrare writeri → precondiții ID-025-04 | Toți writerii din tabelul ID-025-03 (`upsert_matches_bulk`, `upsert_match_history`) rulează prin RPC-ul cu `pg_advisory_xact_lock`; verificat prin inspecție de cod + testul de concurență din Clasa 2 de mai jos | Orice writer din listă încă scriind prin calea veche (INSERT direct, fără lock) |
| **Gate-07** | Precondiții → Faza 6 (ID-025-04) | (1) re-normalizarea rândurilor canonice s-a rulat și confirmat idempotentă la a doua trecere (zero rânduri modificate la re-rulare); (2) verificare zero duplicate rulată **după** re-normalizare, nu înainte (ordinea exactă din ID-025-04); (3) orice coliziune nouă produsă de re-normalizare a fost reconciliată prin ID-025-02 și reverificată | Verificarea de zero duplicate rulată înainte de re-normalizare (ordine greșită, per ID-025-04); orice coliziune nouă nereconciliată |
| **Gate-08** | Faza 6 → Faza 8 | `CREATE UNIQUE INDEX idx_match_history_natural_key_canonical` a rulat cu succes (verificabil: indexul apare în `pg_indexes`, `pg_index.indisvalid = true`) | Eșec la creare (semn direct că o precondiție de mai sus nu era de fapt satisfăcută — tratat ca eșec de verificare, nu se forțează recreare fără a re-investiga cauza) |
| **Gate-09** | Faza 8 → Faza 9 | Rebuild ELO/Feature Engineering („Varianta A") finalizat, raport de rulare fără erori nereconciliate | Rulare eșuată/parțială, per playbook-ul deja exersat |
| **Gate-10** | Faza 9 → Faza 10 | Model ML reantrenat, `ml_model_status` actualizat | Antrenare eșuată sau model nou cu metrici sub pragul existent (decizie deja acoperită de disciplina Champion/Challenger) |
| **Gate-11** | Faza 10 → Faza 11 | Validarea finală (secțiunea următoare) confirmă toate criteriile Clasei 1 ȘI Clasei 2 simultan | Orice criteriu nesatisfăcut — Faza 11 (reluare ADR-023 Phase 4+) rămâne blocată, necesită autorizare separată oricum |

**Observație critică, nouă în acest document**: niciunul dintre ID-025-01/02 nu
închide explicit ce se întâmplă cu un grup HARD CONFLICT înainte de constrângerea
UNIQUE. Fiindcă un grup HARD CONFLICT rămâne, prin definiție, cu mai multe rânduri
nemarcate `superseded_by` (excluderea „nu produce niciun efect lateral", ID-025-01)
pe aceeași cheie naturală, el ar viola direct indexul parțial din ID-025-04 dacă
rămâne nerezolvat. Deci „zero grupuri" ca precondiție a Fazei 6 nu poate fi doar
„zero grupuri procesate automat cu succes" — trebuie să fie literal zero grupuri
duplicate rămase, ceea ce forțează o rezoluție manuală explicită (nu doar o
excludere raportată) pentru orice HARD CONFLICT găsit, înainte ca migrarea să poată
ajunge la Faza 6. Pe corpusul cunoscut azi (ADR-024/ID-025-01: zero grupuri HARD
CONFLICT observate), acest caz e teoretic, dar **Gate-05** de mai sus îl tratează
explicit, nu implicit.

## Clasa 2 — Validarea proprietăților promise

Fiecare test de mai jos verifică o proprietate deja afirmată într-un document
anterior — citată explicit, nu reformulată.

### Idempotență (ID-025-01: „rularea algoritmului a doua oară... nu produce nicio schimbare"; ID-025-02: „idempotent la nivel de rulare completă")

- **V-01 — Test motor complet**: rulează ID-025-02 (EXECUTE) o dată pe tot corpusul, apoi
  rulează din nou, imediat, fără nicio scriere externă între cele două rulări.
  Criteriu: a doua rulare raportează zero grupuri descoperite eligibile pentru
  procesare (toate deja excluse, per criteriul „deja reconciliat" din ID-025-02),
  zero rânduri modificate.
- **V-02 — Test re-normalizare** (ID-025-04): rulează trecerea de re-normalizare a doua
  oară, imediat după prima. Criteriu: zero rânduri modificate la a doua trecere.

### Determinism (ID-025-01: „aceleași rânduri de intrare produc întotdeauna aceeași alegere")

- **V-03 — Test pe fixture cunoscut**: pentru un subset fix de grupuri (ex. subsetul folosit
  la pilotul Fazei 3), rulează algoritmul de selecție de mai multe ori, cu ordinea de
  procesare a rândurilor necanonice permutată explicit între rulări. Criteriu:
  rândul canonic ales și rezultatul merge-ului sunt identice, indiferent de ordine.

### Fail-closed pe HARD CONFLICT (ID-025-01: „un grup cu scoruri contradictorii nu e niciodată reconciliat automat")

- **V-04 — Test cu grup sintetic**: construiește (doar în mediu de test, niciodată pe
  producție) un grup cu `actual_result` divergent între rânduri. Criteriu: motorul
  raportează grupul la „excluse — HARD CONFLICT", zero coloane de audit populate pe
  niciun rând al grupului, zero efect lateral — exact per ID-025-01.

### Sursă necunoscută → excludere, nu presupunere (ID-025-01, Regula #8)

- **V-05 — Test cu prefix necunoscut**: grup sintetic cu un `fixture_id` cu prefix
  nerecunoscut de `resolve_source()`. Criteriu: grupul e exclus, raportat la „sursă
  necunoscută", nu i se atribuie implicit ultimul rang sau orice altă aproximare.

### Concurență — race condition la scriere (ID-025-03: „race-safe fără constrângere DB")

- **V-06 — Test cu doi writeri concurenți, payload-uri diferite**: declanșează, simultan (sau
  cât mai aproape de simultan posibil în mediul de test), două scrieri pentru
  **aceeași** cheie naturală, cu payload-uri care completează câmpuri NULL diferite
  (fără suprapunere). Criteriu: exact un rând fizic există după ambele scrieri;
  ambele câmpuri sunt completate (niciunul pierdut); ordinea de finalizare determină
  doar care scriere a trecut prima prin lock, nu care date au „câștigat" (nu există
  conflict real în acest caz — câmpuri diferite).
- **V-07 — Test cu payload-uri identice** (cazul particular deja documentat în ID-025-03):
  două scrieri simultane cu valori identice pentru aceeași cheie naturală. Criteriu:
  a doua scriere (cea care așteaptă după lock) execută un no-op — zero eroare, zero
  rând al doilea creat.
- **V-08 — Test „niciun rând existent" simultan**: doi writeri, ambii pentru un meci complet
  nou (fără rând existent), aceeași cheie naturală, simultan. Criteriu: exact un
  INSERT reușește să creeze rândul; al doilea writer, după ce obține lock-ul, îl
  găsește deja creat de primul și face UPDATE — nu apare niciodată un al doilea rând
  fizic. Acesta e exact scenariul pentru care a fost ales `pg_advisory_xact_lock` în
  ID-025-03 (motivul explicit pentru care `SELECT ... FOR UPDATE` a fost respins) —
  testul trebuie să confirme empiric alegerea, nu doar argumentul teoretic.

### Comportament la conflict real în scriere continuă (ID-025-03: „primul sosit", nu Source Trust)

- **V-09 — Test cu trei writeri concurenți, același câmp NULL**: trei scrieri simultane
  pentru aceeași cheie naturală, toate încercând să completeze **același** câmp NULL
  cu valori diferite. Criteriu: **exact o valoare** dintre cele trei rămâne
  persistată pe câmp la finalul celor trei tranzacții; celelalte două scrieri, când
  ajung la rândul lor sub lock, găsesc câmpul deja non-null și nu-l ating (Writer
  Protection necondiționat) — indiferent de rangul de încredere al surselor
  implicate. **Care anume dintre cele trei valori câștigă (ordinea exactă de sosire
  sub lock) nu face parte din criteriul de acceptanță** — un test de concurență nu
  poate controla fiabil care thread ajunge primul la lock, deci nu trebuie să
  pretindă că poate. Proprietatea validată e „exact o valoare persistată, restul
  no-op", nu identitatea câștigătorului; regula „primul sosit, nu Source Trust" din
  ID-025-03 se confirmă prin faptul că rezultatul nu corelează cu rangul de
  încredere al surselor, nu prin fixarea unui thread anume ca „primul".

### Backstop-ul constrângerii (ID-025-04: „backstop pasiv... pentru orice cale de scriere care ar ocoli din greșeală RPC-ul")

- **V-10 — Test cu scriere directă, ocolind RPC-ul** (doar în mediu de test): încearcă un
  INSERT direct pentru o cheie naturală deja canonică, fără să treacă prin RPC-ul
  ID-025-03. Criteriu: eșuează dur, cu eroare Postgres de violare a indexului unic
  parțial — exact comportamentul descris în ID-025-04 „Comportament la violare".

### Validarea proprietății „writerii migrați nu mai produc duplicate" (proprietate compusă, deja afirmată de ID-025-03 — validată aici la nivel de integrare)

- **V-11**: nu un test unitar separat — e concluzia combinată a testelor V-06…V-08 de mai
  sus, rulate pe fiecare dintre cei doi writeri din tabelul ID-025-03
  (`upsert_matches_bulk`, `upsert_match_history`) individual, apoi încrucișat (un
  writer din fiecare, concurent, pe aceeași cheie naturală) — cazul realist pentru
  World Cup 2026 (sync live prin `upsert_matches_bulk` concurent cu o salvare de
  predicție prin `upsert_match_history`).

## Metrici și rapoarte de validare

Raportul final de validare (produs înainte de Faza 10) conține, minim:

- Rezultatul fiecărei porți Go/No-Go din Clasa 1 (`Gate-01`…`Gate-11`), cu timestamp
  UTC și, unde e aplicabil, interogarea exactă folosită pentru verificare
  (trasabilitate, Regula #9 North Star).
- Rezultatul fiecărui test din Clasa 2 (`V-01`…`V-11`, trecut/eșuat), cu numărul de
  rulări dacă testul a fost repetat.
- Numărul de grupuri HARD CONFLICT rezolvate manual înainte de Faza 6, cu referință
  la decizia explicită a Owner-ului pentru fiecare.
- Numărul de rânduri modificate de trecerea de re-normalizare (ID-025-04).
- Reutilizează metricile deja produse de rapoartele ID-025-02 (throughput, rânduri
  afectate per coloană) ca parte a dovezii pentru Faza 4 → Faza 5, fără a le
  reproduce separat.
- **Metrici de audit, independente de nevoile algoritmului**: numărul total de
  rânduri canonice (`superseded_by IS NULL`), numărul total de rânduri superseded,
  procentul reconciliat (superseded / total). Nu servesc niciunei decizii Go/No-Go
  și nu sunt consumate de niciun mecanism din ID-025-01…04 — sunt păstrate exclusiv
  pentru trasabilitate pe termen lung (Regula #9 North Star), astfel încât o
  întrebare de tipul „câte meciuri au fost absorbite prin reconciliere" să aibă
  răspuns direct din raport, oricând în viitor, fără a re-rula nimic.

Formatul exact (fișier, tabelă Supabase, log structurat) rămâne detaliu de
implementare, nu fixat aici — consecvent cu aceeași decizie luată în ID-025-02.

## Ce NU acoperă acest document

- Algoritmul de selecție, motorul de reconciliere, migrarea writerilor, constrângerea
  în sine — ID-025-01/02/03/04 (neschimbate, consumate ca atare; acest document
  verifică, nu redefinește).
- Ce se face dacă o poartă Go/No-Go raportează No-Go după ce s-a scris deja pe
  producție, sau dacă un test din Clasa 2 descoperă o încălcare reală a unei
  garanții promise — ID-025-06 (Rollback Playbook).
- Restaurarea din backup și criteriile pentru acea decizie — ID-025-06 (zonă nouă,
  neacoperită de niciun document anterior).

## Referințe

- ADR-025 — Match Identity Implementation Strategy (tabelul de faze, Faza 5/10 —
  „Verificare"/„Validare finală")
- ID-025-01 — Canonical Row Selection (proprietățile testate: determinism,
  idempotență, fail-closed pe HARD CONFLICT)
- ID-025-02 — Historical Reconciliation Engine (proprietățile testate: idempotență
  la nivel de motor, DRY-RUN/EXECUTE identice, fail-soft per grup)
- ID-025-03 — Writer Migration (proprietățile testate: race-safety, „primul sosit",
  no-op idempotent)
- ID-025-04 — Database Constraint (precondiții validate, backstop-ul testat direct)
