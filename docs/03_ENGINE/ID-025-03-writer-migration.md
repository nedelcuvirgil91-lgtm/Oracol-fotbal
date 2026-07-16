# ID-025-03 — Writer Migration

## Ce este acest document

**Implementation Design, nu ADR.** Descrie cum trebuie schimbați writerii care pot
crea rânduri noi în `match_history`, astfel încât să nu mai producă niciodată un al
doilea rând fizic pentru un meci deja existent — implementarea mecanismului **D**
(upsert-merge non-destructiv) din ADR-025, la sursă, nu retroactiv.

**Scop strict**: doar (1) cum caută un writer un meci existent înainte de a scrie,
(2) când decide UPDATE vs. INSERT, (3) cum evită cursele (race conditions) între
writeri concurenți. Nu descrie validarea rezultatului migrării (ID-025-05), nici
playbook-ul de rollback (ID-025-06), nici reconcilierea duplicatelor deja existente
(ID-025-01/ID-025-02, document separat, nemodificat de acesta), nici constrângerea
UNIQUE în sine (ID-025-04).

## Notă de secvențiere (răspuns explicit la observația Owner-ului)

Tabelul de faze din ADR-025 listează Faza 6 (constrângere UNIQUE) înaintea Fazei 7
(actualizare writeri). Owner-ul a semnalat corect că ordinea operațională corectă e
inversă: **writerii trebuie migrați înainte ca baza de date să înceapă să respingă
duplicate**, altfel writerii nemigrați ar începe să eșueze dur (erori de scriere în
producție) din momentul activării constrângerii, nu doar să fie „mai puțin
eleganți".

Acest document **nu redeschide ADR-025** și nu schimbă mecanismul (D rămâne
mecanismul, A rămâne garanția structurală) — doar rafinează ordinea de execuție
dintre ID-025-03 și ID-025-04, exact genul de detaliu de secvențiere pe care
ID-025-02 îl semnalase deja explicit ca nefixat („decizie de secvențiere, nu de
acest document"). Ordinea de aici: **ID-025-03 (acest document) se execută înaintea
ID-025-04 (constrângerea UNIQUE)**.

## Distincție critică față de ID-025-01/ID-025-02

ID-025-01/02 **reconciliază** duplicate deja scrise fizic (două rânduri există,
se aleg/marchează/contopesc). Acest document **previne** apariția unui al doilea
rând fizic **de la momentul migrării încolo** — un writer migrat, când găsește un
meci deja existent, face direct UPDATE în rândul canonic existent; nu se creează
niciodată un al doilea rând de reconciliat ulterior. Cele două mecanisme sunt
complementare, nu redundante: ID-025-01/02 curăță trecutul, acest document
închide viitorul.

## Writeri care necesită migrare

Doar writerii care pot **crea** un rând nou în `match_history` (nu doar actualiza
unul existent găsit prin altă cale) sunt în scopul acestui document:

| Writer | Fișier | Folosit de |
|---|---|---|
| `upsert_matches_bulk()` | `database/queries.py` | `sync/sync_matches.py` (sync live), `sync/import_historical.py` (import istoric) |
| `upsert_match_history()` | `supabase_client.py` | `oracle_engine.py` (salvare predicție live, introducere manuală rezultat) |

**Nu necesită migrare** (verificat, nu presupus): `services/match_stats_backfill_service.py`,
`services/odds_backfill_service.py` — ambele fac doar UPDATE pe rânduri deja
găsite printr-un lookup existent, niciodată INSERT. `sync/backfill_features.py`
— la fel, doar UPDATE (`bulk_update_features`). `sync/sync_results.py::update_results_in_supabase()`
— la fel, nu creează rânduri; **totuși**, lookup-ul lui actual (`(home_team, away_team,
league EXACT, kickoff_date)`, nenormalizat, ADR-024) e exact tiparul care a ratat
detectarea perechilor `fd_`/`kaggle_` istorice. Recomand alinierea lookup-ului lui
la aceeași cheie naturală normalizată descrisă mai jos — nu schimbă scopul acestui
document (nu adaugă un caz de INSERT), doar corectează o sursă latentă de
inconsistență deja documentată.

**Această listă trebuie revizuită explicit dacă apare vreodată un writer nou** care
poate crea rânduri în `match_history` (ex. un provider suplimentar, similar cazului
`odds_`/`espn_` deja documentat în ADR-024/025) — un writer nou care nu trece prin
mecanismul descris în acest document reintroduce exact riscul de duplicare pe care
migrarea îl închide.

## Cum caută un writer un meci existent

Normalizarea `(home_team, away_team)` prin `normalize_team_name()` se întâmplă
**exclusiv în aplicație (Python)**, folosind aceeași funcție deja folosită de
`match_key()`, `normalize_and_dedupe()`, ID-025-01/02 — **niciodată reimplementată
în SQL**. Motiv: `normalize_team_name()` conține logică de normalizare Unicode +
tabel de aliasuri + strip de prefixe/sufixe (`mappings.py`) — o reimplementare
separată în plpgsql ar putea diverge subtil de originalul Python, recreând exact
clasa de problemă pe care acest document o rezolvă (două chei considerate identice
de aplicație, diferite în baza de date). RPC-ul (mai jos) primește **valorile deja
normalizate** ca parametri de intrare — SQL-ul face doar egalitate exactă de
string pe ce a primit, nu normalizare proprie.

Cu cheia naturală normalizată (calculată în Python, trimisă ca parametru), writerul
caută un rând existent în `match_history` cu această cheie, **excluzând rândurile
cu `superseded_by` populat** (doar rândul canonic al unui meci e un candidat valid
de actualizat — un rând deja marcat necanonic de ID-025-01/02 nu trebuie niciodată
reînviat printr-o scriere nouă).

## Decizia UPDATE vs. INSERT

- **Rând existent găsit** (canonic, nemarcat superseded) → **UPDATE**, aplicând
  Writer Protection necondiționat: completează doar câmpurile NULL ale rândului
  existent; niciodată nu suprascrie o valoare deja prezentă. Payload-ul primit de
  la writer devine, conceptual, „încă un candidat" pentru grupul deja existent —
  dar nu se materializează fizic ca rând separat (spre deosebire de reconciliere,
  unde ambele rânduri există deja fizic la momentul procesării).

  **Precizare importantă (răspuns la „cine execută `SourceTrustProvider`?")**: în
  calea de scriere continuă, cazul SOFT CONFLICT al ID-025-01 (Pasul 3, cazul 3 —
  alegere între **mai multe** valori non-null concurente pentru același câmp) **nu
  se aplică**, fiindcă lock-ul advisory (mai jos) serializează strict toate
  scrierile pentru aceeași cheie naturală — la orice moment, decizia e mereu
  binară: „un câmp gol vs. o singură valoare nou-venită", niciodată „mai multe
  candidați simultan" (acela e exclusiv un scenariu de reconciliere în lot,
  ID-025-02, unde toate rândurile candidate există deja fizic în același timp).
  Consecință: pentru un câmp gol pe rândul canonic, **primul writer care obține
  lock-ul și trimite o valoare non-null îl completează** — determinat de ordinea de
  sosire sub lock, nu de rangul de încredere al sursei. `SourceTrustProvider`
  rămâne un concept exclusiv al ID-025-02 (reconciliere în lot); acest document nu
  are nevoie să-l calculeze sau să-l transmită deloc către RPC.

  **Aceasta e o alegere intenționată de arhitectură, nu doar o consecință tehnică a
  lock-ului**: în calea de scriere continuă, ordinea de sosire sub lock determină
  primul completator al unui câmp NULL; selecția pe baza Source Trust rămâne
  rezervată exclusiv reconcilierii istorice (ID-025-02). Nu există, deci, o
  întrebare validă de tipul „dar poate ar fi trebuit să câștige football-data în
  loc de ESPN" pentru calea de scriere continuă — regula e „primul sosit", nu
  „sursa cu rang mai bun", prin decizie explicită, nu prin omisiune.
- **Niciun rând existent** → **INSERT** — acesta devine rândul canonic (unic) al
  meciului, de la acest moment înainte.
- **HARD CONFLICT la scriere** (payload-ul are `actual_result`/goluri diferite de
  rândul existent găsit) → **nu se scrie** — comportament identic cu ID-025-01;
  writerul înregistrează/raportează conflictul, nu-l rezolvă tăcut.

## Cum se evită cursele (race conditions)

**De ce o simplă verificare la nivel de aplicație nu e suficientă**: „caută, apoi
scrie" din doi pași separați (SELECT, urmat de INSERT/UPDATE) lasă o fereastră
(time-of-check-to-time-of-use) în care doi writeri concurenți (ex. sync-ul zilnic
și o predicție live salvată în același moment) pot ambii găsi „niciun rând
existent" și ambii încerca INSERT — recreând exact problema pe care ADR-024/025 o
rezolvă. Această fereastră **nu poate fi închisă doar din aplicație**, indiferent
cât de atent e scris codul client.

**Mecanismul**: lookup-ul + decizia UPDATE-vs-INSERT + scrierea efectivă rulează
**într-o singură funcție Postgres atomică (RPC)**, nu ca pași separați din client
— reutilizează exact precedentul deja stabilit în acest proiect
(`upsert_odds_snapshot`, `services/odds_persistence_service.py`; `promote_challenger`,
`database/migrations/005_promotion.sql`), nu introduce un tipar nou.

**De ce `pg_advisory_xact_lock`, nu alte variante**:
- `SELECT ... FOR UPDATE` nu ajută la cursa de INSERT — blochează concurența doar
  pe un rând care **există deja**; când cheia naturală încă nu are niciun rând
  (cazul exact al cursei), nu există nimic de blocat prin `FOR UPDATE`.
- Retry logic (reîncercare după eșec) reduce probabilitatea cursei, dar nu o
  închide — două tranzacții pot tot eșua/reuși simultan la fiecare reîncercare,
  fără o garanție tare.
- `ON CONFLICT` (upsert nativ Postgres) ar rezolva elegant cursa, dar **necesită
  exact constrângerea UNIQUE pe care acest document o precede** (ID-025-04) — nu e
  disponibilă la momentul migrării writerilor, conform notei de secvențiere.

`pg_advisory_xact_lock`, scopat pe durata tranzacției, serializează orice alte
apeluri concurente pentru **aceeași cheie naturală**, indiferent dacă rândul
există deja sau nu — un al doilea writer care încearcă să scrie pentru același
meci, în același timp, așteaptă (blocat) până când primul finalizează tranzacția,
apoi vede rândul deja inserat/actualizat de primul și procedează corect (UPDATE,
nu INSERT dublu). Writeri pentru meciuri **diferite** nu se blochează reciproc —
lock-ul e scopat strict pe hash-ul cheii naturale a meciului curent. Lock-ul e
**eliberat automat la finalul tranzacției** (`pg_advisory_xact_lock` e
transaction-scoped prin definiție Postgres) — nu necesită eliberare explicită, nu
poate rămâne „agățat" după un commit sau rollback.

**Important**: acest mecanism închide cursa **independent de existența
constrângerii UNIQUE** (ID-025-04) — motiv pentru care writerii pot fi migrați
înaintea constrângerii, conform notei de secvențiere de mai sus, fără o fereastră
de risc de duplicare în producție. **După** ID-025-04, constrângerea UNIQUE devine
un backstop complementar (nu redundant, nu contradictoriu) — lock-ul previne
cursa la nivel de aplicație, constrângerea garantează structural aceeași
proprietate chiar și pentru orice cale de scriere care ar ocoli din greșeală RPC-ul.

Caz particular, util de reținut: dacă două payload-uri **identice** (aceleași
valori) ajung aproape simultan pentru aceeași cheie naturală, al doilea writer
(cel care așteaptă după lock) execută un UPDATE care nu găsește niciun câmp NULL
de completat — un no-op idempotent, nu o eroare.

## Ce se întâmplă cu `fixture_id`-ul unui payload absorbit prin UPDATE

Dacă writerul face UPDATE (meci deja existent), `fixture_id`-ul propriu al
payload-ului primit (ex. un `espn_...` nou, pentru un meci deja tracked ca
`fd_...`) **nu se scrie niciodată ca rând separat** — nu există crosswalk (decizie
deja luată în ADR-025, B respinsă). Acesta e un compromis deja acceptat explicit:
niciun consumator identificat nu are nevoie să știe „ce alte fixture_id-uri au mai
raportat vreodată acest meci", doar valorile efective ale câmpurilor, care sunt
absorbite prin merge.

## Proprietăți garantate de writerii migrați

- **Zero duplicate noi, de la momentul migrării**: orice scriere pentru un meci deja
  existent devine UPDATE, niciodată un al doilea INSERT — indiferent de sursă.
- **Race-safe fără constrângere DB**: lock-ul advisory închide cursa la nivel de
  aplicație/tranzacție, independent de ID-025-04.
- **Merge non-destructiv identic cu ID-025-01 (Writer Protection)**: aceeași regulă
  de bază — niciodată nu se suprascrie o valoare existentă, doar se completează
  NULL. Rezolvarea de tip Source Trust (Pasul 3, cazul 3 din ID-025-01) rămâne
  exclusivă reconcilierii în lot (ID-025-02) — în scrierea continuă, ordinea de
  sosire sub lock decide, prin alegere explicită de arhitectură (vezi „Decizia
  UPDATE vs. INSERT" mai sus), nu rangul sursei.
- **Compatibil cu constrângerea UNIQUE ulterioară** (ID-025-04): odată adăugată,
  constrângerea devine o garanție structurală redundantă cu lock-ul advisory (nu
  contradictorie) — un backstop pentru orice cale de scriere neacoperită de acest
  document, nu mecanismul principal de prevenire.

## Ce NU acoperă acest document

- Regula de merge/decizie în sine — ID-025-01 (reutilizată identic, nu redefinită).
- Reconcilierea duplicatelor deja existente în producție — ID-025-01/02
  (independent, nemodificat).
- Constrângerea UNIQUE efectivă — ID-025-04 (executată DUPĂ acest document, conform
  notei de secvențiere).
- Criteriul de acceptanță că migrarea a reușit — ID-025-05.
- Ce se face dacă migrarea produce un rezultat greșit după deploy — ID-025-06.

## Referințe

- ID-025-01 — Canonical Row Selection (regula de merge reutilizată identic aici)
- ID-025-02 — Historical Reconciliation Engine (nota de secvențiere deja flagată
  acolo, rezolvată explicit aici)
- ADR-025 — Match Identity Implementation Strategy (mecanismul D, Source Trust
  Policy)
- Precedent RPC atomic: `services/odds_persistence_service.py` (`upsert_odds_snapshot`),
  `database/migrations/005_promotion.sql` (`promote_challenger`)
