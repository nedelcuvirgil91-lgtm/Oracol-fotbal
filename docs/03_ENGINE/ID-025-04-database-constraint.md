# ID-025-04 — Database Constraint

## Ce este acest document

**Implementation Design, nu ADR.** Descrie exact constrângerea de bază de date care
implementează garanția structurală **A** din ADR-025 — pasul final care închide
definitiv riscul de recurență, indiferent de orice cale de scriere (existentă sau
viitoare, migrată corect sau nu).

**Scop strict**: doar (1) definiția exactă a constrângerii, (2) precondițiile care
trebuie satisfăcute înainte ca ea să poată fi adăugată, (3) interacțiunea ei cu
ID-025-03 (writeri deja migrați) și cu rândurile `superseded` (ID-025-01/02). Nu
descrie criteriul complet de acceptanță al întregii migrări (ID-025-05), nici
playbook-ul de rollback (ID-025-06).

## Secvențiere (confirmare, nu decizie nouă)

Conform notei deja stabilite în ID-025-03: acest document se execută **după**
ID-025-01, ID-025-02 (reconciliere completă) și ID-025-03 (writeri migrați,
race-safe fără constrângere). Constrângerea descrisă aici e o **garanție
structurală finală**, nu mecanismul principal de prevenire a duplicatelor —
acela e deja activ din ID-025-03 (lock advisory).

## Constatare critică: constrângerea NU poate fi necondiționată

O constrângere UNIQUE simplă pe `(home_team, away_team, kickoff_date)` ar respinge
imediat **exact rândurile pe care ID-025-01/02 le-au păstrat intenționat** —
rândurile `superseded` (necanonice) au, prin construcție, aceeași cheie naturală ca
rândul lor canonic. Ele nu au fost șterse (decizie explicită, Regula #9 North Star,
ADR-025) — deci o constrângere neconditionată ar fi imposibil de adăugat peste
datele deja reconciliate corect, sau ar forța o alegere greșită (ștergere, contrar
deciziei deja luate).

**Soluție**: constrângerea trebuie să fie un **index UNIQUE parțial**, scopat
explicit la rândurile canonice:

```sql
CREATE UNIQUE INDEX idx_match_history_natural_key_canonical
  ON match_history (home_team, away_team, kickoff_date)
  WHERE superseded_by IS NULL;
```

Clauza `WHERE superseded_by IS NULL` e ceea ce face constrângerea compatibilă cu
design-ul non-destructiv deja stabilit — impune unicitate **doar** printre rândurile
„vii" (canonice), exact aceeași condiție de filtrare deja folosită de lookup-ul din
ID-025-03 și de descoperirea de grupuri din ID-025-02. Un rând `superseded` poate
coexista, la nesfârșit, cu cheia naturală a canonicului său, fără să încalce
niciodată această constrângere.

**Această condiție (`superseded_by IS NULL`) devine, prin acest document, definiția
oficială a unui rând canonic la nivelul bazei de date** — aceeași definiție folosită
deja informal în ID-025-01/02/03, acum consacrată explicit ca invariant impus de
schemă, nu doar ca o convenție respectată de cod.

## Precondiție obligatorie: consistența normalizării la nivelul coloanelor stocate

ID-025-03 a stabilit că `normalize_team_name()` rulează exclusiv în Python, iar
writerii migrați scriu deja valoarea **normalizată** direct în `home_team`/
`away_team` (confirmat direct în cod: `supabase_client.upsert_match_history()`,
`import_historical.py::import_matches()` aplică deja `normalize_team_name()` înainte
de scriere). Constrângerea de mai sus compară șiruri stocate exact, nu recalculează
normalizarea — deci depinde structural de faptul că orice rând canonic conține
deja forma normalizată curentă.

**Risc identificat, specific acestui document**: `normalize_team_name()` are un
tabel de aliasuri care a crescut în timp (`mappings.py`, istoric CHANGES v1.2-v1.4).
Un rând scris cu ani în urmă, sub o versiune mai veche a tabelului de aliasuri, ar
putea avea o formă stocată diferită de ce ar produce normalizarea **curentă** pentru
aceleași date brute — o formă de drift, nu o eroare de scriere. ID-025-01 (Pasul 3)
nu atinge `home_team`/`away_team` la merge (nu sunt în `FEATURE_COLUMNS`) — deci
reconcilierea istorică, singură, nu garantează că valorile stocate sunt aliniate la
normalizarea curentă.

**Cerință, ca precondiție a acestui document, nu ca redeschidere a ID-025-01/02**:
înainte de a adăuga constrângerea, se rulează o trecere unică de re-normalizare —
pentru fiecare rând canonic (`superseded_by IS NULL`), se recalculează
`normalize_team_name(home_team)`/`normalize_team_name(away_team)` cu versiunea
curentă a funcției și se rescrie valoarea DOAR dacă diferă (operație idempotentă,
verificabilă separat printr-un dry-run analog celui din ID-025-02). Fără acest pas,
constrângerea ar putea fie eșua la creare (dacă drift-ul a produs coliziuni
ascunse), fie — mai grav — ar putea permite tăcut o viitoare duplicare reală, dacă
forma stocată veche nu mai coincide cu ce scrie un writer migrat azi.
**Re-normalizarea modifică exclusiv rândurile canonice** (`superseded_by IS NULL`)
— rândurile deja marcate `superseded` nu sunt atinse, consistent cu faptul că nu
mai sunt candidate la nicio scriere viitoare.

## Precondiție obligatorie: zero grupuri nereconciliate

**Ordinea exactă a precondițiilor, obligatorie**: (1) re-normalizarea de mai sus se
execută **prima**, nu în paralel și nu după verificarea de zero duplicate — fiindcă
re-normalizarea poate ea însăși produce coliziuni noi, ascunse până atunci (două
rânduri cu forme stocate diferite, care deveneau identice doar după realiniere la
normalizarea curentă); (2) abia după re-normalizare se verifică zero grupuri
duplicate rămase; (3) dacă verificarea găsește grupuri noi (produse de pasul 1), se
rulează din nou reconcilierea (ID-025-02) pe acele grupuri specifice; (4) doar după
ce (2) confirmă explicit zero grupuri, se creează constrângerea.

Constrângerea nu poate fi creată dacă mai există, la nivelul rândurilor canonice,
vreo pereche `(home_team, away_team, kickoff_date)` duplicată — adică dacă
reconcilierea (ID-025-02) nu a ajuns la 0 grupuri rămase. Aceasta e exact
verificarea deja prevăzută în ADR-025 (Faza 5) — acest document nu o redefinește,
doar o cere explicit ca precondiție tehnică a lui `CREATE UNIQUE INDEX` (care
eșuează dur, cu eroare, dacă precondiția nu e satisfăcută — comportament corect,
nu un bug).

## Interacțiunea cu writerii migrați (ID-025-03)

Niciun cod de writer nu trebuie schimbat la activarea acestei constrângeri —
RPC-ul din ID-025-03 deja: (a) scrie valori normalizate, (b) filtrează lookup-ul
pe `superseded_by IS NULL`, (c) e deja race-safe prin lock advisory, independent
de constrângere. Constrângerea devine, din acest moment, un **backstop pasiv**:
nu schimbă comportamentul normal (RPC-ul oricum nu ar fi produs un duplicat), dar
garantează structural aceeași proprietate pentru **orice** cale de scriere care ar
ocoli din greșeală RPC-ul (bug viitor, script manual, acces direct la tabelă).

## Comportament la violare

O încercare de scriere care ar viola constrângerea (ex. un INSERT direct, în afara
RPC-ului migrat, pentru o cheie naturală deja canonică) eșuează dur, cu eroare
Postgres explicită — comportament **intenționat**, nu un defect. Constrângerea nu
încearcă să recupereze silențios (nu face merge automat la nivel de index) — un
eșec la acest nivel semnalează că o cale de scriere neacoperită de ID-025-03 există
și trebuie migrată, nu că datele trebuie reparate. **Orice astfel de eșec trebuie
tratat ca defect de implementare (un writer care ocolește RPC-ul din ID-025-03),
niciodată ca situație operațională normală** — nu se adaugă retry-uri sau
gestionare tăcută a erorii în jurul acestui caz; el trebuie remediat la sursă.

## Reversibilitate

`DROP INDEX idx_match_history_natural_key_canonical;` — reversibil complet, fără
pierdere de date, indiferent de câte rânduri există la momentul respectiv (un index
parțial, ca orice index, nu deține date proprii). Consistent cu Rollback Strategy
din ADR-025.

**Precizare importantă**: `DROP INDEX` scoate doar garda structurală — nu afectează
datele deja reconciliate (rândurile rămân merge-uite/marcate exact cum au fost) și
**nu reactivează automat** riscul de duplicare dacă writerii migrați (ID-025-03)
rămân activi, fiindcă lock-ul advisory previne cursa independent de existența
acestei constrângeri. Rollback-ul acestui document elimină backstop-ul final, nu
mecanismul principal de prevenire — trecutul reconciliat rămâne neschimbat.

## Ce NU acoperă acest document

- Algoritmul de reconciliere sau motorul de execuție — ID-025-01/02 (neschimbate,
  precondiție consumată ca atare).
- Comportamentul writerilor — ID-025-03 (neschimbat, consumat ca atare).
- Criteriul complet de acceptanță al întregii migrări ADR-025 — ID-025-05.
- Playbook-ul detaliat de rollback dincolo de `DROP INDEX` — ID-025-06.

## Referințe

- ADR-025 — Match Identity Implementation Strategy (mecanismul A, Faza 5/6, Rollback
  Strategy)
- ID-025-01 — Canonical Row Selection (`superseded_by`, `FEATURE_COLUMNS` neatinse
  la merge)
- ID-025-02 — Historical Reconciliation Engine (Faza 5 — verificare zero duplicate)
- ID-025-03 — Writer Migration (normalizare exclusiv Python, RPC deja filtrează pe
  `superseded_by IS NULL`)
