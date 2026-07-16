# ID-025-06 — Rollback Playbook

## Ce este acest document

**Implementation Design, nu ADR.** Nu introduce niciun mecanism nou de reversibilitate
— orchestrează exact ce ADR-025 (Rollback Strategy), ID-025-01 (marcare non-destructivă),
ID-025-02 (reluare per grup), ID-025-03 (revert de cod) și ID-025-04 (`DROP INDEX`) au
deja stabilit, per fereastră de risc, în ordine executabilă. Singura zonă cu adevărat
nouă e criteriul obiectiv care separă „revenire logică, fără pierdere de date" de
„restaurare din backup" — o distincție pe care niciun document anterior n-a fost
nevoit s-o facă explicit, fiindcă niciunul nu trata scenariul de eșec, doar cel de
succes.

**Scop strict**: (1) playbook pas-cu-pas per fereastră de risc a migrării; (2)
criteriile obiective care declanșează fiecare tip de rollback; (3) granița exactă
dintre ce se poate recupera logic și ce necesită restaurare din backup; (4) ordinea
de escaladare, identică pentru orice fereastră. Nu redefinește niciun mecanism din
ID-025-01…05 — le consumă ca atare.

## Principiul de bază: de ce cele mai multe rollback-uri sunt deja gratuite

Mecanismul D (merge non-destructiv) + marcarea în locul ștergerii înseamnă că
majoritatea fazelor sunt reversibile fără pierdere de date, ca o **consecință directă**
a deciziilor deja luate în ADR-025/ID-025-01, nu ca rezultat al unui mecanism de
rollback construit separat. Exact observația deja făcută în ADR-025: „alegerea D
(merge, nu delete/reject)... e exact ce face rollback-ul la faza cea mai riscantă
simplu — nu există o fereastră unde date sunt pierdute ireversibil înainte de
constrângerea UNIQUE." Acest document nu contrazice acea observație — o extinde la
toate ferestrele, inclusiv cele de după UNIQUE, și tratează explicit singurul caz în
care ea nu mai e suficientă.

## Cele două categorii de rollback

| Categorie | Definiție | Cost |
|---|---|---|
| **A — Revenire logică** | Anulare prin resetarea marcajelor de audit, revert de cod, sau `DROP INDEX` — fără nicio pierdere de date, posibilă oricând, fără backup | Zero — datele rămân intacte pe disc, doar starea de audit/schemă se schimbă |
| **B — Restaurare din backup** | Necesară doar când o valoare a fost efectiv scrisă greșit pe un câmp care era `NULL` înainte, sau când Writer Protection însăși a fost încălcată — cazuri în care, **în arhitectura curentă**, nu există un jurnal per-câmp care să permită identificarea fără ambiguitate a „ce era înainte" | Restaurare țintită (nu globală) din snapshot |

**Criteriul care separă cele două categorii, precis**: revenirea logică (Categoria A)
e suficientă **doar atât timp cât fiecare câmp afectat de operația care trebuie
anulată poate fi identificat fără ambiguitate ȘI nu a fost atins ulterior de niciun
writer legitim** (ID-025-03). În orice alt caz — inclusiv, dar nu limitat la, o
valoare scrisă greșit pe un câmp anterior `NULL` prin merge (ID-025-01, Pasul 3), sau
orice caz în care Writer Protection ar fi fost demonstrat încălcată — rollback-ul
logic nu e suficient și devine obligatorie restaurarea din backup.

**De ce apare exact acest gol, în arhitectura curentă**: merge-ul (ID-025-01, Pasul 3)
e monoton (`NULL → valoare`), dar **implementarea de azi** nu păstrează un jurnal
per-câmp al „care valoare anume a fost scrisă de care operație". Marcajul de audit
(`superseded_by`/`superseded_at`/`superseded_reason`) înregistrează **alegerea
rândului canonic**, nu **valorile individuale** scrise ulterior pe el prin merge.
Resetarea marcajului aduce grupul înapoi la „nereconciliat" (Categoria A funcționează
perfect pentru alegerea greșită de canonic), dar nu anulează automat o valoare deja
scrisă printr-un merge — dacă acea valoare era greșită dintr-un motiv real (bug, nu
conflict normal SOFT), nu mai există, **azi**, cale sigură de a distinge „era `NULL`,
acum are valoarea greșită X" de „era deja X, corect, dintr-un writer legitim ulterior"
fără backup.

**Precizare de scop**: acesta nu e un gol fundamental al mecanismului D (merge
non-destructiv) — e o limitare a implementării curente a trasabilității, nu a
principiului. Dacă proiectul adaugă vreodată audit per-coloană sau event sourcing pe
`match_history` (nefăcut azi, nici planificat de niciun document din serie), Categoria
B s-ar putea reduce sau dispărea pentru acest caz specific, fără să contrazică nimic
din ID-025-01…05 — invariantul rămâne „merge-ul nu suprascrie niciodată o valoare
existentă", doar granularitatea reversibilității s-ar îmbunătăți.

## Precedentul deja folosit în acest proiect pentru Categoria B

Restaurarea din backup nu introduce un mecanism nou — reutilizează exact tiparul deja
aplicat de două ori în acest proiect: un **snapshot table** (copie a rândurilor
afectate, luată explicit înainte de un `UPDATE` riscant pe producție), nu restore
global de bază de date. Acest tipar e deja recomandat de ADR-025 („Snapshot/backup
explicit... conform `supabase-safety`") și rămâne guvernat de aceeași disciplină:
niciun `execute_sql`/`apply_migration` de restaurare fără să se arate Owner-ului,
explicit, exact ce se scrie.

## Playbook pas-cu-pas, per fereastră de risc

### Fereastra 1 — Înainte de reconciliere (Faza 0-2)

- **Ce poate merge prost**: DDL parțial la Faza 1 (coloane de audit); raport DRY-RUN
  eronat la Faza 2.
- **Categorie**: A, întotdeauna — zero scriere reală până la acest punct.
- **Pași**: (1) `DROP COLUMN` pe coloanele de audit, dacă DDL-ul a rulat parțial —
  reversibil imediat, niciun rând existent atins (pas pur aditiv, ID-025-04); (2)
  pentru DRY-RUN: fără impact, se corectează cauza și se re-rulează.
- **Criteriu de declanșare**: DDL eșuat/parțial; raport DRY-RUN cu erori de calcul
  (verificabil prin re-rulare pe același subset).
- **Backup necesar?** Nu.

### Fereastra 2 — Pilot (Faza 3)

- **Ce poate merge prost**: alegere greșită de rând canonic pe subsetul pilot (Categoria
  A); sau — separat — o valoare scrisă greșit prin merge pe un câmp anterior `NULL`
  (Categoria B, vezi criteriul de mai sus).
- **Pași, Categoria A** (alegere de canonic greșită, valorile merge-uite sunt corecte):
  (1) resetare `superseded_by`/`superseded_at`/`superseded_reason` la `NULL` pe toate
  rândurile grupurilor afectate din pilot; (2) grupurile redevin automat eligibile
  pentru procesare la următoarea rulare (criteriul „deja reconciliat", ID-025-02); (3)
  corectare cauză (ex. `SourceTrustProvider`); (4) re-rulare EXECUTE, scopată la
  același subset pilot.
- **Pași, Categoria B** (valoare greșită pe câmp anterior `NULL`): (1) oprire imediată
  a oricărei rulări ulterioare a motorului, pentru a nu scrie peste dovada problemei;
  (2) izolare exactă a rândurilor/câmpurilor afectate; (3) restaurare țintită din
  snapshot-ul luat înainte de pilot (precedentul de mai sus) — doar pentru rândurile
  identificate, nu restore global; (4) verificare, din logs, dacă vreun writer legitim
  a scris ceva pe acele rânduri specifice între snapshot și descoperirea problemei —
  dacă da, acea scriere se reaplică manual după restaurare; (5) corectare cauză; (6)
  re-validare (ID-025-05, testele de determinism/idempotență) înainte de a relua.
- **Criteriu de declanșare**: discrepanță găsită la verificarea manuală a pilotului
  (poarta Go/No-Go Faza 3 → Faza 4, ID-025-05).

### Fereastra 3 — Reconciliere completă (Faza 4)

Două moduri de eșec distincte, tratate diferit:

- **Întreruptă (timeout/crash), nu greșită**: deja complet acoperit — tranzacția per
  grup (ID-025-02) garantează că nu există stare intermediară; reluare prin rerulare
  completă fără scopare (Varianta A), fără backup. Niciun pas nou aici.
- **Completă, dar logic greșită (bug descoperit ulterior)**: identică distincției
  Categorie A/B de la Fereastra 2, aplicată la scară completă — (1) oprire completă a
  motorului ȘI a writerilor migrați (dacă rulează deja, per secvențierea ID-025-03),
  ca să nu se mai scrie nimic peste zona afectată; (2) folosind `superseded_reason`
  (trasabilitate per grup, ID-025-01) + raportul complet (ID-025-02), identificare
  exactă a tuturor grupurilor/câmpurilor atinse de cauza reală (nu doar cele
  observate întâmplător); (3) clasificare per grup — Categoria A (doar marcaj) sau
  Categoria B (valori de restaurat); (4) execuție separată pentru fiecare categorie,
  ca la Fereastra 2, dar pe întregul set afectat; (5) corectare cauză; (6) re-validare
  completă (ID-025-05) înainte de a relua migrarea.
- **Criteriu de declanșare**: raportul de validare (ID-025-05, poarta Faza 4 → Faza 5)
  arată nepotriviri, sau un audit ulterior (oricând, chiar și după ce migrarea a
  avansat) descoperă o valoare incorectă atribuibilă acestei faze.

### Fereastra 4 — Constrângere UNIQUE (Faza 6 / ID-025-04)

- **Deja complet acoperit de ID-025-04**: `DROP INDEX
  idx_match_history_natural_key_canonical` — reversibil complet, nu afectează datele
  deja reconciliate, nu reactivează cursa (lock advisory din ID-025-03 protejează
  independent). Acest playbook doar fixează pașii exacți: (1) `DROP INDEX`; (2)
  investigare cauză (aproape sigur o precondiție nesatisfăcută — grup nereconciliat
  sau drift de normalizare, ambele din ID-025-04); (3) **nu se recreează indexul**
  fără o re-verificare completă a ambelor precondiții (ID-025-05, poarta „Precondiții
  → Faza 6").
- **Caz distinct, nou aici**: dacă indexul a fost creat cu succes, dar **ulterior** se
  descoperă că trecerea de re-normalizare (precondiția ID-025-04) a rescris greșit
  `home_team`/`away_team` pe rânduri canonice — acesta e un caz de Categorie B identic
  celui de la Fereastra 3 (o valoare scrisă greșit, fără jurnal per-câmp al valorii
  dinainte), tratat cu aceiași pași: oprire, izolare, restaurare țintită din snapshot,
  re-validare. Diferența practică: `DROP INDEX` trebuie să preceadă orice restaurare
  care ar putea reintroduce temporar o cheie naturală duplicată în timpul corectării.
- **Criteriu de declanșare**: eșec la creare (Categoria A, per ID-025-04 — eșec dur,
  fără schimbare parțială de schemă); sau descoperire ulterioară a unei re-normalizări
  greșite (Categoria B).

### Fereastra 5 — Migrare writeri (ID-025-03)

- **Deja acoperit**: revert de cod (git), standard — schema/datele nu sunt afectate
  de acest pas izolat (ADR-025, Rollback Strategy).
- **Pași exacți**: (1) identificare regresie (monitorizare erori de producție, sau
  testele de concurență din ID-025-05 eșuate); (2) `git revert` la commit-ul anterior
  migrării writerului afectat, inclusiv **funcția RPC Postgres** dacă regresia era în
  ea (parte a migrării, versionată la fel ca orice schimbare de schemă, nu doar codul
  Python client); (3) redeploy; (4) verificare că intervalul afectat n-a lăsat
  duplicate noi — rulează exact interogarea de descoperire a grupurilor din ID-025-02
  pe intervalul de timp respectiv.
- **Backup necesar?** De regulă nu. Un rând nou creat greșit prin `INSERT` (cazul
  „niciun rând existent" din ID-025-03) se poate șterge direct (`DELETE`) — la
  momentul creării eronate n-are încă nicio referință externă construită peste el
  (spre deosebire de un rând canonic vechi, cu istoric acumulat). Dacă regresia a
  produs în schimb o valoare greșită pe un câmp `NULL` al unui rând **deja existent**
  (cale de `UPDATE`), se aplică identic distincția Categorie A/B de mai sus.
- **Criteriu de declanșare**: regresie confirmată în comportamentul unui writer după
  migrare.

### Fereastra 6 — Rebuild ELO/Feature Engineering (Faza 8)

- **Deja complet acoperit**: playbook „Varianta A", deja exersat de 3-4 ori în acest
  proiect (ADR-025, Rollback Strategy) — reluare idempotentă, gating per-coloană NULL
  previne corupere parțială. Niciun pas nou.

### Fereastra 7 — Reantrenare ML (Faza 9)

- **Deja complet acoperit**: `ml_model_status` păstrează istoricul modelului anterior
  — revenire fără reantrenare (ADR-025, Rollback Strategy). Niciun pas nou.

## Criterii obiective — Categorie A vs. Categorie B, rezumat

| Semnal observat | Categorie | Acțiune |
|---|---|---|
| Interogarea de descoperire arată din nou grupuri duplicate după resetarea marcajului | A | Grupul e redescoperit automat, se re-rulează motorul (ID-025-02) |
| Alegere de rând canonic greșită, dar valorile merge-uite sunt confirmate corecte | A | Reset marcaj + re-rulare, fără backup |
| O valoare pe un câmp anterior `NULL` e confirmată greșită (nu doar o alegere Source Trust discutabilă, ci o valoare care nu corespunde realității) | B | Restaurare țintită din snapshot |
| Writer Protection demonstrat încălcată (o valoare non-null a fost suprascrisă) | B, tratat ca **defect critic de arhitectură**, nu operațional | Oprire completă a migrării, restaurare, re-verificare integrală ID-025-05 înainte de orice reluare |
| Regresie de cod la un writer migrat | A | `git revert` |
| Eșec la creare a constrângerii UNIQUE | A | Eșec dur, fără schimbare parțială — se investighează precondiția, nu se forțează |
| Re-normalizare descoperită ulterior ca greșită pe rânduri canonice | B | `DROP INDEX` (dacă deja creat) + restaurare țintită |

## Ordinea exactă de escaladare (identică pentru orice fereastră)

1. **Oprire** — orice proces activ care ar putea continua să scrie peste dovada
   problemei se oprește întâi, indiferent de fereastră.
2. **Diagnostic** — folosind trasabilitatea deja garantată (`superseded_reason`,
   rapoartele ID-025-02, criteriile de validare ID-025-05, logs Supabase), se
   stabilește exact ce s-a întâmplat și de ce.
3. **Clasificare** — Categoria A sau B, per criteriul de mai sus. Niciun pas de
   execuție nu începe înainte de această clasificare.
4. **Execuție** — marcaj resetat / revert de cod / `DROP INDEX` pentru A; restaurare
   țintită din snapshot pentru B, cu SQL-ul exact arătat Owner-ului înainte de rulare
   (`supabase-safety`).
5. **Verificare** — re-rulare a testelor relevante din ID-025-05 pe zona afectată, ca
   minim.
6. **Decizie de continuare** — migrarea nu se reia automat; reluarea cere o decizie
   explicită separată, după ce verificarea de la pasul 5 confirmă starea corectă.

## Ce NU acoperă acest document

- Mecanismele de bază pe care le orchestrează — ID-025-01 (merge/marcare), ID-025-02
  (motor), ID-025-03 (writeri), ID-025-04 (constrângere): niciunul nu e redefinit
  aici.
- Criteriile de acceptanță și testele de proprietate folosite ca instrument de
  verificare la pasul 5 de mai sus — ID-025-05 (consumat ca atare).
- Autorizarea de a relua Phase 4+ din ADR-023 după finalizarea completă și validată a
  acestei migrări — decizie separată, în afara acestei serii de documente.

## Referințe

- ADR-025 — Match Identity Implementation Strategy (Rollback Strategy — precedentul
  central, tabelul de faze)
- ID-025-01 — Canonical Row Selection (marcare non-destructivă, merge monoton)
- ID-025-02 — Historical Reconciliation Engine (tranzacție per grup, reluare completă)
- ID-025-03 — Writer Migration (revert de cod, lock advisory independent de
  constrângere)
- ID-025-04 — Database Constraint (`DROP INDEX`, precondiții)
- ID-025-05 — Validation (criteriile folosite la pasul „Verificare" al escaladării)
- `supabase-safety` (skill) — disciplina de confirmare explicită pentru orice
  restaurare pe producție
