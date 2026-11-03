# ADR-069 — Retenția Foundation Data Layer se numără pe sezoane, ancorate în date reale

**Status**: Aprobat și **executat** (2026-08-26) — prima rulare reală, varianta A
**Atinge contractul**: `providers/flashscore/season_cleanup.py` (cheia de retenție), fluxul oficial Discovery → … → Final Report din ADR-044
**Nu atinge**: `match_history`, `match_events`, `player_match_stats` (excluse explicit de ADR-044 — istoricul ML), `odds_history` (Frozen, ADR-005/006/010), niciun criteriu de promovare, niciun motor de predicție

---

## Context

ADR-044 a stabilit politica: **6 sezoane — cel curent plus 5 istorice**, cu scop
restrâns la cele 6 tabele Foundation Data Layer. Politica e scrisă, corectă și
neaplicată niciodată.

Două motive, ambele verificate în cod și pe date reale (2026-08-26):

**1. Ștergerea nu există.** Din fluxul oficial `Discovery → Validation →
Cleanup Report → Backup → Delete → Integrity Check → Final Report`, sunt
implementați **primii doi pași**. `season_cleanup.py` nu conține nicio operație
`DELETE`, returnează mereu `delete_executed: False` și rulează în fiecare noapte
din `run_night.py` doar ca raport.

**2. Cheia de retenție e o coloană goală.** `discover_seasons()` grupează pe
coloana `season`. Măsurat azi:

| Tabelă | Rânduri | Cu `season` |
|---|---:|---:|
| `flashscore_match_context` | 12.573 | **0** |
| `player_match_stats_extended` | 94.766 | 3.997 |
| `flashscore_raw_extraction` | 4.553 | 101 |
| `flashscore_data_completeness` | 1.092 | 18 |
| `match_statistics_extended` | 11.582 | 11.582 |
| `flashscore_standings_snapshot` | 248 | 248 |

Rândurile cu `season = NULL` intră în `unknown_season_row_counts` și sunt
excluse explicit din candidații la ștergere — corect sub North Star #8, dar
consecința practică e că retenția nu ar acționa niciodată, chiar dacă `DELETE`
ar exista mâine.

### Ce s-a descoperit măsurând, și restrânge mult problema

**Foundation Data Layer a început să colecteze pe 2026-07-29.** Cel mai vechi
meci descris de fiecare tabelă:

| Tabelă | Cel mai vechi meci descris |
|---|---|
| `match_statistics_extended` | 2026-07-14 |
| `player_match_stats_extended` | 2026-07-14 |
| `flashscore_data_completeness` | 2026-07-14 |
| `flashscore_raw_extraction` | prima captură 2026-07-29 |
| `flashscore_standings_snapshot` | clasamente curente |
| **`flashscore_match_context`** | **1967-11-10** |

Cinci din șase tabele conțin **exclusiv sezonul curent**. Zero candidați la
retenție, azi și încă ~5 ani de acum înainte.

Singura excepție e `flashscore_match_context`, și nu pentru că ar colecta
istoric: **rândurile ei descriu ALTE meciuri.** Distribuția pe categorii:

| Categorie | În ultimii 5 ani | Mai vechi | Cel mai vechi |
|---|---:|---:|---|
| `h2h_overall` | 3.839 | **486** | 1967-11-10 |
| `recent_form_home` | 3.967 | **0** | 2022-08-11 |
| `recent_form_away` | 3.970 | **0** | 2022-08-11 |

**Niciun rând de formă nu depășește 5 ani.** Tot ce e vechi sunt confruntări
directe. Rândul din 1967 e `Coventry – Fulham`, `h2h_overall`, colectat
2026-07-30 — nu „forma lui Coventry din 1967".

Mecanismul: Flashscore listează ultimele ~10 întâlniri dintre două cluburi.
Pentru rivali care joacă de două ori pe an, 10 întâlniri acoperă 5 ani. Pentru
cluburi care se întâlnesc rar (Coventry–Fulham prin divizii diferite, Paris
FC–Lyon), aceleași 10 întâlniri ajung în anii '60–'70. Adâncimea vine din
raritatea confruntării, nu dintr-o colectare istorică.

---

## Problema de decis

`flashscore_match_context.season` e `NULL` pe toate cele 12.573 de rânduri, iar
completarea ei s-a măsurat separat (2026-08-26) și **nu e o opțiune onestă**:

- derivare prin join cu `match_history` (același meci, fapt deja verificat):
  3.999 din 12.262 de rânduri cu dată găsesc rând canonic, 3.722 au sezon —
  **29,6%**;
- derivare din calendarul `competition_season` (ADR-067): plafon teoretic 72,7%,
  dar calendarul conține **doar 2026-2027**, deci rândurile istorice n-au reper;
- regula calendaristică „iulie": **interzisă explicit** în `season_cleanup.py`
  și de North Star #8;
- `CF` = Club Friendlies — 3.050 rânduri (24,3%), confirmat prin conținut
  (Tottenham–Sydney FC, Man City–Inter, Man Utd–Leeds, Cordoba–Sevilla). Un
  amical **nu aparține unui sezon**: `NULL` e răspunsul corect, nu unul lipsă.

O retenție care ar acționa pe 30% din rânduri, aleși după disponibilitatea unei
etichete derivate, ar fi mai rea decât niciuna: ar arăta autoritară exact acolo
unde e parțială.

---

## Decizie propusă

**1. Retenția se cheamă pe data reală a rândului, nu pe eticheta `season`.**

| Tabelă | Data care decide |
|---|---|
| `flashscore_match_context` | `meeting_date` (populată 97,5% — 12.262/12.573) |
| `match_statistics_extended` | `match_history.kickoff_date` prin `match_id` |
| `flashscore_data_completeness` | `match_history.kickoff_date` prin `match_id` |
| `player_match_stats_extended` | `match_history.kickoff_date` prin `player_match_stats` |
| `flashscore_raw_extraction` | **rămâne în afara scopului** (vezi decizia 5) |
| `flashscore_standings_snapshot` | **rămâne în afara scopului** (vezi decizia 5) |

`captured_at` **nu** se folosește niciodată ca dată de retenție. Un rând
capturat pe 2026-07-30 descrie un meci din 1967 — `captured_at` spune când am
văzut noi pagina, nu la ce sezon aparține faptul.

**2. Numărătoarea rămâne pe SEZOANE, nu pe ani calendaristici** (decizie
explicită a proprietarului produsului, 2026-08-26). Un rând din septembrie 2021
aparține sezonului 2021-2022; sezonul iese întreg sau nu iese deloc. Nu se taie
la mijloc de sezon.

**3. Pragul se ancorează în date reale, nu într-o regulă inventată.**
`competition_season` (ADR-067) conține startul REAL al sezonului curent pentru
17 competiții — de la 2026-02-21 (MLS) la 2026-08-28 (Bundesliga).

Pragul de retenție = **cel mai devreme start de sezon observat, minus 5 ani**:

```
min(start_date) = 2026-02-21   →   prag = 2021-02-21
```

Un rând mai vechi decât acest prag e în afara ferestrei de 6 sezoane în
**ORICE** competiție urmărită — nu doar în a lui. Nu e nevoie de o hartă
cod→competiție pentru cele 51 de coduri, și nu se aproximează apartenența
niciunui rând la vreun sezon.

**4. Când nu e sigur, se păstrează.** Rândurile dintre pragul global conservator
și pragul propriu al competiției lor rămân neatinse. Costul măsurat e mic:

```
sub pragul conservator global (2021-02-21):  459 rânduri
sub pragul Premier League      (2021-08-21):  499 rânduri
banda de ambiguitate păstrată deliberat:       40 rânduri
```

Rândurile fără dată (311) rămân necunoscute și neatinse, exact ca azi — North
Star #8, neschimbat.

**5. Scopul efectiv de azi e o singură tabelă.** Celelalte cinci conțin exclusiv
sezonul curent, deci retenția pe ele e cod care n-ar avea ce șterge. Se
implementează cheia de dată pentru cele patru care o pot avea (decizia 1), dar
ștergerea se rulează întâi și numai pe `flashscore_match_context`.

`flashscore_raw_extraction` și `flashscore_standings_snapshot` rămân în afara
scopului: prima are data doar în slug-ul `match_ref`, a doua e un snapshot al
clasamentului curent și nu descrie un meci. Ambele cer o decizie proprie, nu
una moștenită tacit din acest ADR.

**6. Ștergerea se implementează, dar pornește DEZACTIVATĂ** (North Star #3).
Pașii lipsă din ADR-044 — Backup → Delete → Integrity Check → Final Report — se
construiesc în ordinea aceea. Prima rulare reală se face doar după ce lista
exactă (câte rânduri, din ce tabelă, ce interval) e arătată și aprobată
separat, cu backup înainte.

**7. Pe măsură ce trec sezoanele, aproximarea dispare singură.** Discovery scrie
în `competition_season` startul real al fiecărui sezon pe care îl observă
(ADR-067). Peste câțiva ani, pragul nu va mai fi „minus 5 ani" — va fi startul
real, observat, al celui de-al șaselea sezon. Regula de azi e proiectată să fie
înlocuită de fapte, nu să rămână permanentă.

---

## Argumente PRO

- **Face executabilă o politică deja aprobată.** ADR-044 spune „6 sezoane";
  azi nu e aplicată nici măcar pe hârtie, fiindcă se cheamă pe o coloană goală.
- **Elimină dependența de o etichetă derivată.** `meeting_date` e un fapt
  observat, populat 97,5%; `season` pe această tabelă e derivabil onest doar
  29,6%.
- **Nu cere harta celor 51 de coduri** și nu aproximează apartenența niciunui
  rând la vreun sezon — pragul conservator global ocolește ambele.
- **Costul erorii e cunoscut și mic**: banda de ambiguitate păstrată e de 40 de
  rânduri din 12.573.
- **Închide un subiect amânat de trei ori** (`flashscore_match_context.season`),
  arătând că era o întrebare greșită: retenția nu are nevoie de coloana aceea.

## Argumente CONTRA, asumate

- **Nu rezolvă o presiune reală.** Toate cele 6 tabele FDL însumează ~32 MB;
  `flashscore_match_context` are 3 MB, iar cele 459 de rânduri vizate sunt
  neglijabile ca spațiu. E disciplină, nu necesitate — deci se poate face
  încet și corect, dar nu se poate justifica prin urgență.
- **Introduce ștergere într-un sistem care azi nu șterge nimic.** Riscul unei
  ștergeri greșite e permanent, spre deosebire de riscul de a păstra prea mult.
  Mitigat prin: flag stins implicit, backup obligatoriu, aprobare separată per
  prima rulare, prag conservator.
- **Pragul „minus 5 ani" e o proiecție**, nu un fapt observat, până când
  `competition_season` acumulează sezoane reale. Mitigat prin decizia 4
  (conservatorism) și 7 (înlocuire cu fapte).
- **Ștergerea unui H2H vechi taie exact perechile cu istoric rar.** Coventry–
  Fulham are 10 întâlniri în 60 de ani; retenția i-ar lăsa mai puține.
  Consecință practică azi: **niciuna** — `_build_h2h()` nu citește această
  tabelă (verificat: folosește `get_h2h_from_history` din `match_history`, plus
  `freelf_h2h_snapshot`). Dacă vreodată o va citi, această consecință trebuie
  reevaluată explicit.

## Alternative respinse

- **Umplerea coloanei `season`** — respinsă: acoperire onestă 29,6%, iar 24,3%
  (amicalele) trebuie să rămână `NULL` prin definiție.
- **Retenție pe `captured_at`** — respinsă: descrie când am văzut pagina, nu la
  ce sezon aparține faptul. Ar șterge după data colectării noastre, ceea ce
  pentru H2H e complet nelegat de vechimea meciului.
- **Retenție pe ani calendaristici** — respinsă explicit de proprietarul
  produsului: ar tăia la mijloc de sezon.
- **Prag per competiție, din hartă cod→competiție** — respinsă pentru acum:
  cere o hartă verificată pentru 51 de coduri și câștigă 40 de rânduri.

---

## Consecințe

**Pozitive**
- Politica de retenție din ADR-044 devine aplicabilă, pe o cheie verificabilă.
- Subiectul `flashscore_match_context.season` se închide argumentat, nu prin
  amânare — nu e nevoie de coloană pentru retenție.
- Cele cinci tabele „curate" sunt documentate ca atare, cu cifre, deci nimeni
  nu mai caută retenție acolo unde n-are ce șterge.

**Negative, acceptate**
- Un al doilea mecanism de ștergere în sistem, cu riscul lui permanent.
- Pragul rămâne o proiecție câțiva ani.
- Perechile cu H2H rar pierd adâncime — fără consecință azi, de reevaluat dacă
  tabela ajunge vreodată în cascada H2H.

---

## Prima rulare reală — 2026-08-26, varianta A

Prag recalculat live: **2021-02-21** (min `start_date` = 2026-02-21, MLS).
Cifrele au coincis exact cu cele codificate în teste.

### Ce s-a găsit uitându-ne la rânduri, nu la sume

Cele 459 de rânduri atingeau 175 de meciuri. Pentru **25 dintre ele ștergerea
însemna zero H2H rămas** — și nu meciuri oarecare, ci **meciuri VIITOARE**
(august–noiembrie 2026): Manchester City–Coventry, Real Madrid–Málaga,
Arsenal–Hull City, Nice–Le Mans, Mainz–Paderborn și încă 20.

Tiparul: **echipe nou-promovate**. Nu s-au întâlnit cu adversarii lor de 5+ ani
tocmai pentru că erau în divizii diferite, deci singurul lor H2H era cel vechi.
Exact contra-argumentul scris mai sus („taie perechile cu istoric rar"), apărut
cu nume și date.

S-a oprit execuția și s-au prezentat trei variante (Discovery Rule): (A) ștergere
completă, 459 rânduri; (B) retenția scoate surplusul dar cruță ultima
înregistrare — 343 rânduri, 25 de meciuri neatinse; (C) amânare.

### Decizia proprietarului produsului: varianta A

Recomandarea mea fusese (B). Argumentul care a decis (A), și care e mai bun:
**forma recentă acoperă deja nevoia** — chiar fără H2H între cele două echipe
nou-promovate, avem meciurile lor din ultimele etape ale campionatelor proprii,
din care se deduce forma. Un H2H vechi de 10–30 de ani e **cosmetic, nu util**.

Rândurile `recent_form_*` nu erau oricum atinse (toate cele 459 erau
`h2h_overall`) — deci exact informația pe care se bazează argumentul a rămas
intactă, verificat: 8.150 înainte, 8.150 după.

### Execuție

1. **Backup** — `flashscore_match_context_retention_backup_20260826`, tabelă
   creată prin `CREATE TABLE ... AS SELECT`. Verificată înainte de ștergere:
   459 rânduri, 459 ID-uri distincte, 1967-11-10 → 2021-02-20, zero categorii
   greșite.
2. **Delete** — pe ID-uri luate **din backup**, nu re-evaluând condiția de dată:
   `DELETE ... WHERE id IN (SELECT id FROM <backup>)`. Prin construcție nu putea
   șterge nimic ce nu era deja salvat.
3. **Integrity Check** — rulat prin `retention.verify_integrity()`, funcția
   reală din modul, nu o verificare ad-hoc:

```
randuri_inainte      12.573
randuri_sterse          459
randuri_dupa         12.114   (asteptat 12.114)   ✔
fara_data      311  ->   311   protejate, intacte  ✔
recent_form  8.150  -> 8.150   neatinse            ✔
ramase sub prag           0                        ✔
cea mai veche ramasa   2021-02-23                  ✔
```

Flagul `fdl_retention_delete_enabled` **nu a fost activat** — rularea s-a făcut
prin SQL explicit, arătat integral înainte de execuție, cu aprobare separată pe
lista exactă. Flagul rămâne pentru automatizarea viitoare, dacă se decide.

### Backup — decizie de retenție (2026-08-26)

`flashscore_match_context_retention_backup_20260826` — tabelă Postgres simplă
(`CREATE TABLE ... AS SELECT`), instantaneu static al celor 459 de rânduri
șterse, 72 kB. Verificat: **zero referințe** în tot repo-ul (`.py`/`.sql`) —
nu e citită de niciun cod, niciun consumator, nicio cascadă de predicție.
Impact asupra Oracle: zero.

Același precedent ca `ADR-060` (`match_history_backfill_backup_20260822`):
**păstrare 30 de zile de la creare, cu revizuire la ~2026-09-25** (nu ștergere
imediată, nu păstrare pe termen nelimitat fără termen). Proprietarul produsului
a aprobat explicit acest tratament (2026-08-26).

Ca și la ADR-060: fără reminder automat programat — `send_later` a eșuat acolo
din motive de aprobare inobtenabile din sesiune, deci termenul rămâne doar
notat aici, de readus în discuție manual la revizuire.

---

## Notă — automatizare completă, NEÎNCEPUTĂ (2026-08-26)

Discutat cu proprietarul produsului după prima rulare: activarea flagului
`fdl_retention_delete_enabled` **nu** e suficientă, singură, ca să facă
ștergerea automată. `night_sync._stage_cleanup()` are o gardă AST care îl
obligă azi să cheme `execute_retention(dry_run=True)` — codat direct, nu
citește flagul. Deci chiar cu flagul pornit, rularea de noapte tot produce doar
raport.

Ca ștergerea să ruleze singură, fără verificare manuală de fiecare dată, ar
trebui **amândouă**: flagul activat ȘI o schimbare de cod care cere
`night_sync` să apeleze `dry_run=False`, plus slăbirea gărzii AST care azi
interzice exact asta.

**Nu se face acum, deliberat.** Rularea de azi a arătat de ce contează pasul de
verificare manuală: agregatul (`459 candidați`) nu arăta ce a ieșit la iveală
abia uitându-ne la rândurile individuale — 25 de meciuri VIITOARE ale unor
echipe nou-promovate, care ar fi rămas fără niciun H2H. Decizia finală (varianta
A, cu un argument diferit de recomandarea inițială) a necesitat judecată umană,
nu doar cifre.

**De făcut altă dată, cu plan propriu, dacă se decide vreodată:**
1. Discuție explicită dacă merită — retenția rulează rar (nu zilnic), deci
   câștigul de timp al automatizării complete e mic; costul e pierderea
   verificării manuale care a prins cazul de mai sus.
2. Dacă da: ADR nou (schimbare de contract — retenția devine un proces automat,
   nu unul supravegheat), nu un amendament tacit la acesta.
3. Implementare: relaxarea gărzii AST din `test_fdl_retention.py` (deliberat, cu
   motiv scris, nu ștearsă), schimbarea `_stage_cleanup()` să citească flagul în
   loc să cheme mereu `dry_run=True`, plus un mecanism de raportare a ce s-a
   șters automat (log dedicat sau tabelă), ca nicio ștergere automată să nu
   treacă neobservată (North Star #9).
4. Testare + mutații, ca la restul modulului `retention.py`.

Până atunci: flagul rămâne stins, orice ștergere reală trece prin SQL explicit,
arătat integral, cu aprobare separată — exact fluxul de azi.

---

**Ce NU face acest ADR**
- Nu atinge `match_history`/`match_events`/`player_match_stats` — istoricul ML
  rămâne intact, cu adâncimea lui deliberată.
- Nu atinge `odds_history` (Frozen).
- Nu activează ștergerea — o construiește stinsă.
- Nu decide retenția pentru `flashscore_raw_extraction` și
  `flashscore_standings_snapshot`.
- Nu schimbă `RETENTION_SEASON_COUNT = 6`.
- Nu automatizează ștergerea recurentă — vezi nota de mai sus.

---

## Amendamentul 1 (2026-11-03) — o premisă a acestui ADR era FALSĂ, iar backup-ul se păstrează

**Aprobat explicit** (varianta (b) din cele trei oferite de Discovery Rule:
amendament la acest ADR, nu ADR nou și nu „în afara scopului"). Pornit din
revizuirea restantă a backup-ului (intrarea **D-6** din `CLAUDE.md`, ajunsă la
**39 de zile** de întârziere), nu dintr-un simptom.

### Premisa infirmată

§„Argumente CONTRA" afirma:

> *„Ștergerea unui H2H vechi taie exact perechile cu istoric rar. Coventry–
> Fulham are 10 întâlniri în 60 de ani; retenția i-ar lăsa mai puține."*

Afirmația e **falsă ca descriere a tabelei**, iar exemplul alege chiar fixture-ul
care o infirmă. Măsurat pe producție, 2026-11-03:

`flashscore_match_context` ține **maximum 5 rânduri per (fixture, categorie)** —
`meeting_order` ia valori **0..4** pe toate cele trei categorii
(`h2h_overall`, `recent_form_home`, `recent_form_away`), verificat pe toate
cele 33.856 de rânduri. Deci tabela **nu a ținut niciodată istoric H2H adânc**
și nu avea de unde să-l piardă. Nu „retenția i-a lăsat mai puține": niciodată nu
a avut mai mult de cinci.

### Cauza reală: cheia unică nu e o identitate

`(context_match_id, category, meeting_order)` e cheia unică declarată
(`flashscore_match_context_context_match_id_category_meeting__key`). Dar
`meeting_order` e o **POZIȚIE** — 0 = cel mai recent. Când cele două cluburi se
întâlnesc din nou, fiecare meci mai vechi se deplasează cu o poziție, iar
`upsert ... on conflict` **rescrie slotul cu alt meci**.

Exemplul e tocmai Coventry City – Fulham, fixture `126852`:

| slot | backup (26 aug) | viu (24 oct) |
|---:|---|---|
| 0 | — | **2026-10-24**, 0-1 ← întâlnire nouă |
| 1 | — | 2022-04-10 |
| 2 | 1968-04-05, **1-1** | 2021-10-02 |
| 3 | 1967-11-10, **0-3** | 1968-04-05, **1-1** |
| 4 | — | 1967-11-10, **0-3** |

Tot s-a deplasat cu exact unu. Cuantificat pe tot backup-ul: din **285** de
rânduri care împart cheia unică cu un rând viu, **274 descriu altă dată** și
**236** altă pereche gazdă/oaspete. Doar **2 din 459** au conținut identic.

Consecința de reținut: `captured_at` se împrospătează, rândul arată **plin și
proaspăt**, și descrie **alt meci** decât descria înainte. E clasa deja numită în
`CLAUDE.md` („un indicator care COLAPSEAZĂ lucruri distincte, citit ca și cum
le-ar distinge"), cu un nivel mai jos: aici e **cheia** care nu e identitate,
deci scrierea rescrie corect după contract și totuși pierde informație.

### Pagubă azi: ZERO, verificat pe toți consumatorii

Cei trei cititori de producție ai tabelei, verificați individual:

| cititor | ce face | depinde de stabilitatea slotului? |
|---|---|---|
| `is_flashscore_h2h_context_present()` (`queries.py:3066`) | test de prezență, boolean, `.eq("category","h2h_overall")` | **nu** |
| `get_match_context_segments()` (`queries.py:3150`) | segmentele unui meci, pentru afișare | **nu** — citește conținutul curent |
| `get_team_recent_form_context()` (`queries.py:3772`) | Level FS2, forma recentă | **nu** |

`_build_h2h()` **nu** citește această tabelă (folosește
`get_h2h_from_history()` din `match_history`, plus `freelf_h2h_snapshot`) —
reconfirmat, aceeași verificare ca în §„Argumente CONTRA".

Iar pentru `recent_form_home`/`recent_form_away` poziția e **semantica
corectă**: „al N-lea meci cel mai recent" e exact ce trebuie. Defectul e îngust
și atinge numai `h2h_overall`, numai în rolul de arhivă — rol pe care nimeni nu
i-l cere.

### Decizie: NU se schimbă cheia

Pagubă zero la toți consumatorii, iar o cheie nouă ar cere o migrare pe 33.856
de rânduri pentru un beneficiu pe care niciun cititor nu-l folosește. Se
corectează **premisa**, nu schema. Dacă vreodată un consumator va avea nevoie de
H2H adânc din această tabelă, consecința trebuie reevaluată explicit — exact
formularea folosită deja în §„Argumente CONTRA" pentru `_build_h2h()`.

### Backup-ul se PĂSTREAZĂ, cu cifra corectată

`flashscore_match_context_retention_backup_20260826` — **se păstrează**, decizie
explicită a proprietarului produsului (2026-11-03), **fără termen nou**: e
singura copie a unor date pe care tabela vie nu le poate ține prin construcție.

Cifra din revizuire a fost greșită de trei ori înainte de a fi corectă, și
procesul merită consemnat ca metodă:

| test | rezultat | ce dovedea |
|---|---:|---|
| pe `id` | 0 / 459 | **nimic** — `id` se reemite la re-inserare |
| pe `context_match_id` | 459 / 459 | **nimic** — identifică *fixture-ul*; 13,25 rânduri fiecare |
| pe cheia unică reală | 285 / 459 | doar **2** au același conținut |
| **pe meci** (fixture + `meeting_date`) | 192 prezente · 13 la alt fixture | **254 nu există nicăieri** |

Deci backup-ul e singura copie a **254** de rânduri (1967-11-10 → 2021-02-20),
nu a tuturor celor 459 cum s-a afirmat la începutul revizuirii. Prima
măsurătoare a nimerit concluzia corectă **din noroc, nu prin construcție**.

### Reparație colaterală: RLS activat

Aceeași revizuire a măsurat că backup-ul era **singura tabelă din `public` fără
RLS** (1 din 62), cu `anon` având `SELECT, INSERT, UPDATE, DELETE, TRUNCATE`.
Deci „o păstrăm ca plasă de siguranță" era **fals în practică**: oricine deține
cheia publicabilă putea goli plasa. Cauza: `CREATE TABLE ... AS SELECT` nu
moștenește RLS de la sursă — exact tiparul pe care garda
`tests/test_migration_grants.py` îl numește în docstring-ul ei.

Executat 2026-11-03, cu aprobare explicită:

```sql
ALTER TABLE flashscore_match_context_retention_backup_20260826
  ENABLE ROW LEVEL SECURITY;
```

Verificat după, din două surse independente: `relrowsecurity = true`, 0 politici,
**0 tabele în `public` fără RLS** (era 1), 459 de rânduri intacte, tabela vie
neatinsă (33.856); iar lint-ul propriu al Supabase, `rls_disabled_in_public`
(nivel **ERROR**), **nu mai apare** în raportul de securitate.

**Lecția de mecanism**: acel lint exista și era de nivel ERROR — ar fi semnalat
tabela **din 26 august**, ziua creării. N-a lipsit detectorul; a lipsit faptul că
nimic din proiect nu citește advisor-ul Supabase.
