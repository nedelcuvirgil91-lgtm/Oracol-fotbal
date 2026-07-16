# ADR-025 — Implementarea Contractului de Identitate Canonică (ADR-024)

## Status

**Propus / Changes Requested** — 2026-07-16. Revizie aplicată conform observațiilor
Owner-ului (separarea contract/mecanism/plan operațional, extragerea Source Trust
Policy, adăugarea Rollback Strategy și Canonical Row Definition, eliminarea unei
reguli de implementare fixate prematur în ADR). Răspunde exclusiv la întrebarea: *cum
implementăm contractul formal stabilit de ADR-024, fără a compromite datele istorice
și fără a introduce regresii?* Nu execută nimic — necesită aprobare explicită înainte
de orice scriere pe producție.

## Context

ADR-024 a stabilit contractul (7 puncte) fără a alege un mecanism tehnic. Orice
variantă tehnică trebuie să satisfacă, demonstrat pe baza dovezilor din ADR-024:

1. Vizibilă la punctele cu zero conștiință de identitate azi — `ELOTracker`/
   `fetch_all_matches()` și `ml_predictor.get_training_data()`.
2. Reconciliază 4 scheme independente de `fixture_id` (`fd_`, `kaggle_`, `odds_`,
   `espn_`), niciuna derivabilă din alta.
3. Nu depinde de eticheta brută de ligă (cauza demonstrată a corupției istorice).
4. Derivată din câmpuri deja normalizate (`normalize_team_name()`).
5. O singură sursă de adevăr, nu reimplementată per consumator (azi: 6 definiții
   concurente).
6. Nu compromite date istorice — orice remediere trebuie să păstreze trasabilitatea
   (Regula #9 North Star), nu doar să șteargă.
7. Previne recurența la scriere — riscul World Cup 2026 (`odds_`/`espn_`) e activ azi,
   nu doar istoric.

## Obiectiv arhitectural

**Sistemul va utiliza o identitate canonică unică pentru fiecare meci real. Toți
writerii identificați în ADR-024 vor converga asupra acelei identități — nu vor mai
menține fiecare propria noțiune de „același meci".**

Acest obiectiv e independent de orice mecanism tehnic ales pentru a-l atinge. Restul
documentului descrie, în ordine: mecanismul recomandat pentru convergență, politica
(separată, evolutivă) care alimentează acel mecanism, garanțiile de siguranță
(rollback), și abia la final planul operațional de migrare.

## Opțiuni tehnice comparate

### A. Constrângere UNIQUE pe cheie naturală normalizată `(home_normalizat, away_normalizat, kickoff_date)`, fără ligă în cheie
Rol: **mecanism de enforcement**, nu soluție de sine stătătoare — vezi „Decizie".
- **Avantaje**: impusă de DB, închide recurența la sursă, definitiv; simplă conceptual.
- **Riscuri**: nu poate fi adăugată direct — schema conține deja 3.504 grupuri duplicate;
  necesită reconciliere PRIMA. Singură, cu reject-on-conflict, ar pierde datele
  complementare ale rândului respins (ex. shots/corners din `fd_`, dacă `kaggle_`
  ajunge al doilea).
- **Notă pe includerea ligii**: `match_key()` exclude liga, `normalize_and_dedupe()`/
  `update_results_in_supabase()` o includ (exact) — divergență deja documentată în
  ADR-024. Recomand explicit **excluderea** ligii din cheie: includerea ei ar
  reproduce exact defectul demonstrat (Premier League vs. E0 sunt același meci,
  etichete diferite).

### B. Tabelă de crosswalk/identitate (N `fixture_id` → 1 `match_id` canonic)
- **Avantaje**: păstrează toată proveniența per-sursă, auditabil, non-destructiv prin
  construcție.
- **Riscuri**: cere rescrierea tuturor celor minimum 6 consumatori identificați în
  ADR-024 (join prin crosswalk în loc de `SELECT *` direct) — cost de implementare
  mult mai mare, suprafață de regresie mult mai largă exact pe componentele deja
  fragile (`ELOTracker`, `ml_predictor`).

### C. Regulă de precedență de provider
Notă: acest conținut a fost extras ca **Source Trust Policy**, separată de decizia
acestui ADR — vezi secțiunea dedicată mai jos. Rămâne listată aici doar ca variantă
tehnică comparată în matrice, pentru completitudinea comparației.
- **Avantaje**: formalizează ce `sync/sync_matches.py` deja declară parțial
  („Surse în ordine de prioritate: 1. football-data.org, 2. openfootball") — extins la
  toate cele 4 scheme.
- **Riscuri**: singură, nu rezolvă duplicatele deja scrise; nu ține de identitatea
  meciului, ci de politica de încredere în surse — motiv pentru extragere.

### D. Upsert idempotent pe cheie naturală, cu merge non-destructiv (nu reject)
Rol: **mecanismul principal de convergență** — vezi „Decizie".
- **Avantaje**: reutilizează exact disciplina deja dovedită în proiect — Writer
  Protection / gating per-coloană NULL (Regula #13, `sync/backfill_features.py`,
  testat direct în Phase 2-3 ADR-023). Nicio valoare existentă nu e pierdută;
  rândurile complementare (`fd_` cu shots/corners, `kaggle_` cu ce a avut el) se
  contopesc într-un singur rând fizic, fără pierdere de informație.
- **Riscuri**: necesită modificarea punctului de scriere (`ON CONFLICT` pe cheia
  naturală, nu doar pe `fixture_id`) la toate cele 4+ writeri identificați în
  ADR-024.

### E. Matching fuzzy/probabilistic + coadă de revizuire manuală
- **Avantaje**: ar acoperi variații de nume/dată nesurprinse de cheia exactă.
- **Riscuri**: cost de inginerie semnificativ mai mare, introduce un bottleneck uman.
  **Nejustificat empiric** — ADR-024, punctul 7: 100% din cele 3.504 grupuri găsite
  se potrivesc exact pe cheia normalizată; zero cazuri de variație care ar necesita
  fuzzy matching.

## Decision Matrix

Fiecare variantă (A-E, definite mai sus) evaluată pe aceleași 11 criterii, cu
justificare per celulă — nicio celulă nu e o notă fără motivare.

| Criteriu | A — UNIQUE pe cheie naturală | B — Crosswalk table | C — Precedență provider | D — Upsert-merge non-destructiv | E — Fuzzy matching + review |
|---|---|---|---|---|---|
| **Complexitate implementare** | Medie — un DDL, dar precondiționat de reconciliere completă | Ridicată — tabelă nouă + rescriere query la toți consumatorii | Scăzută — regulă de configurare, fără schemă nouă | Medie — schimbă semantica de scriere la 4+ writeri, tipar deja existent | Ridicată — algoritm de similaritate + prag + flux de revizuire, inexistent azi |
| **Impact asupra codului existent** | Scăzut — o constrângere DB, restul neschimbat | Ridicat — atinge toți cei 6 consumatori identificați (ADR-024) | Scăzut — o funcție/tabel de configurare, consultată doar la conflict | Mediu — 4+ puncte de scriere (`upsert_matches_bulk`, `upsert_match_history`, `update_results_in_supabase`, cei 2 servicii de backfill) | Ridicat — cod nou de scoring + flux de review, fără precedent |
| **Compatibilitate Writer Protection (#13)** | Parțial — nu contrazice, dar nu o implementează singură | Parțial — Writer Protection ar trebui aplicată separat, la rândul canonic din crosswalk | Nu se aplică direct — regulă de deznodământ, nu mecanism de scriere | **Da, direct** — D *este* Writer Protection extinsă la cheia naturală (tipar deja testat, `_missing_feature_columns()`) | Nu se aplică direct — problemă ortogonală |
| **Compatibilitate ADR-022** | Da — `ELOTracker` primește o secvență unică, formula MOV neschimbată | Necesită modificarea `fetch_all_matches()` — risc de regresie pe modul deja verificat riguros | Indirect — doar combinată cu A/D | Da — un singur rând fizic per meci, `fetch_all_matches()` structural neschimbat | Parțial — cazurile ambigue nerezolvate rămân duplicate în replay |
| **Compatibilitate ADR-023** | Da — identic cu ADR-022 (aceeași sursă `fetch_all_matches()`) | Necesită aceeași modificare ca la ADR-022 | Indirect | Da | Parțial |
| **Compatibilitate replay ELO** | Da — fiecare meci procesat o singură dată | Risc de a reintroduce eroare de ordine cronologică (zero-scurgere-temporală) dacă bucla de replay e rescrisă greșit | Nu rezolvă singură | Da — un singur rând fizic, bucla de replay neschimbată structural | Parțial — funcționează doar pentru cazurile rezolvate automat |
| **Compatibilitate ML** | Da — `get_training_data()` rămâne `SELECT *`, fără duplicate fizice | Necesită modificarea `get_training_data()` — risc de a uita viitori consumatori | Nu rezolvă singură | Da — identic cu A, fără cost suplimentar de query | Parțial — identic cu rândul de mai sus |
| **Risc operațional** | Mediu — constrângerea eșuează dur dacă reconcilierea nu e completă | Ridicat — suprafață mare de regresie, module multiple simultan | Scăzut — testabilă izolat | Mediu — risc de scriere parțială dacă un writer nu e actualizat corect (mitigat de tipar deja dovedit) | Ridicat — algoritm netestat pe acest dataset, risc de fals-pozitive (unificare greșită a 2 meciuri diferite) |
| **Reversibilitate** | Ridicată — `DROP CONSTRAINT`, fără pierdere de date | Ridicată — crosswalk eliminabil fără a atinge `match_history` | Ridicată — configurare, ușor de schimbat | **Ridicată prin construcție** — reconcilierea marchează, nu șterge | Medie — merge-uri greșite mai greu de inversat fără audit exact al provenienței |
| **Cost de migrare** | Concentrat — reconciliere completă înainte de aplicare, într-un pas mare | Mare, dar distribuit incremental per consumator | Scăzut — o configurare nouă | Mediu — reconciliere o singură dată + adaptare incrementală a writerilor | Ridicat — dezvoltare algoritm + rulare pe tot istoricul + revizuire manuală |
| **Cost de mentenanță** | Scăzut — întreținut de motorul DB | Ridicat — risc de desincronizare crosswalk↔`match_history` (tipar deja documentat ca eșuat o dată — `mappings.py`, comentariu liniile 345-349, dictionare manuale desincronizate) | Scăzut — listă actualizată rar | Scăzut-Mediu — reutilizează tipar deja întreținut (Writer Protection) | Ridicat — recalibrare periodică a algoritmului + proces uman continuu |

### Sinteză

**Avantaje** (D ca mecanism principal + A ca garanție structurală): fiecare
componentă reutilizează un tipar deja dovedit în acest proiect (Writer Protection
pentru D, constrângere DB standard pentru A) — zero concepte noi neverificate;
compatibilitate directă cu ADR-022, ADR-023, replay-ul ELO și ML pe toate cele patru
rânduri relevante ale matricei; reversibilă prin construcție.

**Dezavantaje**: suprafață de cod atinsă (4+ writeri) mai mare decât o soluție de
configurare izolată; cere o etapă de reconciliere istorică obligatorie înainte ca A
să poată fi aplicată — nu e o soluție „dintr-o mișcare".

**Riscuri**: cel mai mare risc operațional e la faza de reconciliere istorică
(scriere pe producție, pe ~3.500 grupuri) — vezi „Rollback Strategy" mai jos pentru
tratarea explicită a acestui risc.

**Motivul preferinței, independent de contextul acestei conversații**: din matrice,
B (crosswalk) și E (fuzzy matching) sunt singurele variante care ating „Ridicat" pe
minimum trei criterii de cost/risc simultan — B pentru că mută costul din faza de
migrare în faza de mentenanță perpetuă (risc deja materializat o dată în acest
proiect), E pentru că introduce incertitudine algoritmică nejustificată de dovezi
(ADR-024, punctul 7: 100% din duplicate găsite se potrivesc exact pe cheie
normalizată). D e singura variantă care atinge compatibilitate directă pe toate cele
4 rânduri de compatibilitate funcțională și reversibilitate ridicată — de aceea e
mecanismul principal de convergență. A completează D ca garanție structurală finală,
nu ca soluție alternativă.

## Canonical Row Definition

Contractul ADR-024 cere: *pentru fiecare meci real, trebuie să existe exact un rând
canonic în `match_history`.*

Acest ADR stabilește **doar invariantul**, nu regula de selecție:

- **Cum e ales**: regulă de implementare, definită la momentul migrării (Faza 3-4 din
  strategia de mai jos), NU fixată aici. Candidați posibili, niciunul ales prin acest
  document: rândul cel mai vechi (`id` minim — precedent deja folosit informal de
  `normalize_and_dedupe()`/`update_results_in_supabase()`), rândul din sursa cu
  încredere mai mare (Source Trust Policy, vezi mai jos), sau rândul cu cele mai
  complete date. Alegerea exactă rămâne o decizie de implementare, revizuibilă fără a
  redeschide acest ADR.
- **De ce e ales**: motivul selecției trebuie înregistrat per grup reconciliat (nu
  doar aplicat tăcut) — face parte din cerința de trasabilitate (Regula #9 North
  Star), indiferent de regula exactă aleasă.
- **Stabilitate**: odată desemnat, rândul canonic al unui meci nu se schimbă retroactiv
  fără o operație explicită, auditabilă (nu se re-evaluează silențios la fiecare
  rulare de backfill).
- **Poate fi schimbată regula de selecție?** Da — fiindcă nu e fixată în acest ADR, ci
  în implementare/Source Trust Policy, poate evolua fără a necesita un ADR nou.

## Decizie

Din obiectivul arhitectural de mai sus, și din matricea de comparație — nu dintr-o
alegere intuitivă:

**D (upsert-merge non-destructiv) este mecanismul principal** prin care toți writerii
converg asupra identității canonice — la fiecare scriere, dacă cheia naturală
normalizată `(home_normalizat, away_normalizat, kickoff_date)` există deja, se
completează DOAR câmpurile NULL ale rândului canonic existent (tiparul Writer
Protection deja verificat), niciodată nu se suprascrie o valoare reală.

**A (constrângere UNIQUE pe cheia naturală, fără ligă) este garanția structurală**,
adăugată DUPĂ ce reconcilierea istorică a redus duplicatele la zero — nu e o soluție
alternativă la D, e mecanismul prin care D devine imposibil de ocolit (previne
recurența, inclusiv cazul activ World Cup 2026).

**C (precedența de provider) nu mai e parte a acestei decizii** — a fost extrasă ca
Source Trust Policy, consultată de D doar în cazurile rare de conflict real (ambele
surse au o valoare non-null diferită pentru același câmp).

**B (crosswalk) e respinsă ca soluție primară** — cost de implementare mult mai mare
pentru un beneficiu deja obținut, mai simplu, prin proveniența implicită a upsert-ului
non-destructiv. Rămâne notă de rezervă doar dacă apare vreodată o cerință reală de
audit „ce sursă exactă a scris fiecare valoare" — niciun consumator identificat în
ADR-024 nu cere asta azi.

**E (fuzzy matching) e respinsă** — nejustificată de dovezi.

### Tratarea datelor istorice deja duplicate (3.501 + 3 grupuri)

Nu ștergere. **Reconciliere trasabilă**: pentru fiecare grup, se desemnează un rând
canonic (regulă de selecție definită în implementare, conform „Canonical Row
Definition" de mai sus — nu fixată în acest ADR); câmpurile complementare din
rândul(rândurile) necanonic(e) se contopesc non-destructiv în cel canonic (același
gating per-coloană din `backfill_features.py`); rândul necanonic nu se șterge — se
marchează explicit (o coloană nouă, de audit) ca superseded, păstrând trasabilitatea
completă cerută de Regula #9 North Star.

## Source Trust Policy (politică separată, evolutivă — nu parte fixă a acestui ADR)

Ordinea de încredere între surse (folosită de mecanismul D doar pentru conflicte
reale — ambele valori non-null, diferite) e o politică operațională, nu un contract
de identitate. Se poate schimba în timp (ex. la adăugarea unui provider nou) **fără
a redeschide acest ADR**.

Conținut de referință (nu fixat aici, ilustrativ — reflectă ordinea deja parțial
declarată în `sync/sync_matches.py`): football-data.org (`fd_`) > ESPN (`espn_`) >
Odds API (`odds_`) > import istoric Kaggle (`kaggle_`), justificat de completitudinea
demonstrată (100% din rândurile `fd_` au shots/corners populate vs. 0% din
`kaggle_`, per ADR-024). Ordinea exactă, formatul de stocare (config/tabelă) și
mecanismul de actualizare rămân decizii de implementare, externalizate din acest ADR.

## Rollback Strategy

Fiecare fază riscantă din strategia de migrare (mai jos) are un răspuns explicit la
„cum revii dacă eșuează":

| Fază | Ce se întâmplă dacă eșuează | Rollback |
|---|---|---|
| Schemă pregătitoare (coloană de audit) | DDL aditiv eșuat/parțial | `DROP COLUMN` — nicio dată atinsă, reversibil imediat |
| Dry-run de reconciliere | Raport incomplet/eronat | Fără impact — zero scriere reală în această fază |
| Pilot de reconciliere (subset izolat) | Merge greșit pe un subset mic | Rândurile necanonice sunt doar marcate `superseded`, nu șterse — se poate reveni prin ștergerea marcajului, fără pierdere de date. Subsetul izolat limitează blast radius-ul la un interval mic |
| **Reconciliere completă (după pilot, înainte de constrângerea UNIQUE)** | Eroare parțială pe un subset din cele ~3.500 grupuri | **Exact scenariul semnalat**: fiindcă D nu șterge niciodată, ci doar completează NULL-uri și marchează, revenirea nu necesită restaurare din backup — se poate: (a) opri procesul, (b) inspecta exact ce grupuri au fost procesate (marcajul `superseded` + audit „de ce a fost ales" din Canonical Row Definition oferă trasabilitate completă), (c) relua doar grupurile neprocesate. Constrângerea UNIQUE (Faza următoare) încă nu există în acest punct — deci baza de date acceptă în continuare scrieri fără blocaj dur, ceea ce face acest punct sigur pentru pauză/inspecție nelimitată. Snapshot/backup explicit (conform `supabase-safety`) rămâne recomandat înainte de start, ca plasă suplimentară, nu ca unic mecanism de revenire |
| Adăugare constrângere UNIQUE | Eșuează la creare (mai există duplicate nereconciliate) | Eșec dur, dar sigur — `ALTER TABLE` eșuat nu aplică nimic parțial; se revine la Faza de verificare, fără nicio schimbare de schemă efectivă |
| Actualizare writeri | Regresie într-un writer | Revert de cod (git), standard — schema/date nu sunt afectate de acest pas izolat |
| Rebuild ELO/Feature Engineering | Rulare eșuată/parțială | Playbook „Varianta A" deja exersat de 3-4 ori în acest proiect — reluare idempotentă, gating per-coloană NULL previne corupere parțială |
| Reantrenare ML | Model nou mai slab | `ml_model_status` păstrează istoricul — se poate reveni la referirea modelului anterior fără reantrenare |

Observație structurală: alegerea D (merge, nu delete/reject) în secțiunea „Decizie"
e exact ce face rollback-ul la faza cea mai riscantă (reconcilierea istorică) simplu
— nu există o fereastră unde date sunt pierdute ireversibil înainte de constrângerea
UNIQUE.

## Strategie de migrare (fazată, cu Phase Gate obligatoriu între fiecare pas — identic disciplinei din ADR-023)

| Fază | Conținut | Scriere pe producție? |
|---|---|---|
| **0** | Acest ADR | Nu |
| **1** | Schemă pregătitoare — coloană nouă de audit (`superseded_by`/echivalent) + definirea inițială a Source Trust Policy (config, nu schemă). **Fără** constrângerea UNIQUE încă. | Da, DDL aditiv, non-distructiv |
| **2** | Raport de reconciliere DRY-RUN — identifică toate grupurile, arată exact ce s-ar contopi/marca conform Canonical Row Definition, **zero scriere reală** | Nu |
| **3** | Pilot de reconciliere pe un subset izolat, verificat manual (analog pilotului IRL din ADR-023 Phase 2) | Da, scop limitat |
| **4** | Reconciliere completă, supravegheată, cu snapshot/backup explicit înainte (conform `supabase-safety`) — vezi Rollback Strategy pentru tratarea eșecului parțial | Da, integral |
| **5** | Verificare — zero duplicate rămase pe cheia naturală (criteriu de acceptanță, analog Phase 3 ADR-023) | Nu (doar SELECT) |
| **6** | Adăugare constrângere UNIQUE pe cheia naturală — abia posibilă acum | Da, DDL |
| **7** | Actualizare writeri (toate punctele identificate în ADR-024) la upsert-merge pe cheia naturală, consultând Source Trust Policy pentru conflicte | Da, cod |
| **8** | Rebuild ELO + Feature Engineering (playbook „Varianta A", deja exersat) | Da |
| **9** | Reantrenare ML | Da |
| **10** | Validare finală (metodologie reutilizată din Phase 3 ADR-023) | Nu |
| **11** | Reluare Phase 4+ din ADR-023 (Read Path → Dual Run → Oracle Switch) | — (altă autorizare) |

Fiecare fază necesită aprobare explicită separată, conform disciplinei „un pas per
instrucțiune" deja stabilite în acest proiect. Architecture Freeze rămâne activ pe
Phase 4+ din ADR-023 până la finalizarea Fazei 9 de mai sus.

## Consecințe

- Suprafața de cod atinsă e mai mare decât o soluție cu o singură variantă izolată,
  dar fiecare componentă adăugată reutilizează tipare deja dovedite în proiect
  (Writer Protection) — nu introduce concepte noi neverificate.
- Nicio pierdere de date — reconcilierea e aditivă/de marcare, nu de ștergere.
- Riscul de recurență (World Cup 2026 și orice caz viitor similar) e închis structural
  abia la Faza 6 — până atunci rămâne activ, exact ca azi.
- Source Trust Policy și regula exactă de selecție a rândului canonic rămân
  externalizate din acest ADR — pot evolua fără un ADR nou, atât timp cât invariantul
  („exact un rând canonic per meci") nu e încălcat.

## Referințe

- ADR-024 — Canonical Match Identity & Data Contract
- ADR-023 — Canonical Live ELO Source (precedent de disciplină fazată + Phase Gates)
- Regula #13 (Writer Protection) — precedent tehnic direct reutilizat pentru mecanismul D
