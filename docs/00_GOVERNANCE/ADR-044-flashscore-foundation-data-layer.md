# ADR-044 — Flashscore Foundation Data Layer + Data Trust Layer

**Status**: **ACCEPTAT** (2026-07-29) — aprobat explicit de proprietarul produsului ("TASK APROBAT — Foundation Data Layer (Flashscore) + Data Trust Layer... Poți începe implementarea conform acestei arhitecturi"). Schema (migrațiile 035/036) și stratul de persistență (`providers/flashscore/persistence.py`, `database/queries.py`, `udal_validation.validate_flat_identity`) sunt implementate și acoperite de teste (pytest, fără rețea, contra fixture-ului real `docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/`). **Scriere live rămâne neactivată** — `tos_reviewed=False` neatins, `providers/flashscore/adapter.py.fetch()` rămâne `NotImplementedError` (Faza 4, ADR-042 §16.2). Acest ADR autorizează arhitectura și schema; activarea scrierii live rămâne o decizie separată, ulterioară.

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-07-29.

**Companion**: ADR-042 (`universal-data-acquisition-layer.md`, contractul UDAL), ADR-043 (`flashscore-odds-fallback.md`, precedent direct de „provider auxiliar cu scriere separată, niciodată amestecată”), `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md` (design-ul inițial, auxiliar), `docs/06_UDAL/UDAL_FLASHSCORE_FULL_TABS_POC_REPORT.md` (dovada tehnică — toate cele 7 tab-uri, câmpuri reale confirmate), `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md` (Predictor/ML rămân neatinse de acest ADR).

---

## Context

Sesiunea de lucru curentă a evoluat prin mai multe decizii succesive:

1. POC-ul inițial (10 meciuri, Playwright standard, fără evaziune) a confirmat Flashscore ca provider **auxiliar** viabil, fără protecții active.
2. R-SYNC-FLASH-01 a proiectat Flashscore ca sursă auxiliară — completare de câmpuri lipsă, niciodată înlocuire a providerilor API existenți (API-Football, Soccer Football Info, ESPN, TheSportsDB, football-data.org).
3. Un POC live suplimentar (1 meci, toate cele 7 tab-uri reale — Sumar/Statistici/Formații/Statistici jucători/Cote/H2H/Clasamente), declanșat de o captură de ecran a proprietarului produsului care a demonstrat direct că datele "Statistici" (cornere, pase, cartonașe) EXISTĂ real pe un tab niciodată vizitat până atunci (`/summary/stats/`), a arătat că bogăția reală de date Flashscore e semnificativ mai mare decât scope-ul M0 inițial: **36 de categorii de statistici de meci** (nu 5), un tabel dedicat de **statistici per jucător cu rating** (32 rânduri), **H2H segmentat pe 3 categorii reale** (30 rânduri), **clasament complet** (16 echipe).
4. Proprietarul produsului a decis explicit, pe baza acestei descoperiri: Flashscore devine sursa care **completează** (nu înlocuiește) providerii API existenți pentru date bogate de meci — filosofia „nu pierde nicio informație”: orice câmp robust, repetabil, stabil descoperit în POC trebuie salvat, indiferent dacă algoritmul curent îl folosește azi.
5. Cerința arhitecturală explicită, nouă: un **Data Trust Layer** — `RAW → VALIDATED → CANONICAL → Oracle → ML`, cu regula „nu există bypass”: nicio scriere directă în tabele canonice fără să treacă prin validare; Oracle Engine și ML citesc EXCLUSIV din tabele canonice, niciodată direct din Flashscore.

Acest ADR formalizează rezultatul acelor decizii: schema Supabase finală, fluxul de scriere, și granițele stricte față de Predictor/ML/Oracle Engine (neatinse).

## Decizie

### 1. Flashscore completează, nu înlocuiește

API-Football, Soccer Football Info, ESPN, TheSportsDB, football-data.org **rămân** responsabile pentru fixtures, rezultate, scoruri, status meci și sincronizarea curentă (ADR-034/041, Selection Engine). Flashscore adaugă informații bogate (statistici extinse, statistici per jucător, context H2H/formă, clasament) pe care providerii existenți nu le oferă azi. **Supabase rămâne Single Source of Truth** — niciun consumator (Oracle Engine, ML, UI) nu citește vreodată direct de la un provider extern; totul trece prin tabelele canonice.

### 2. Data Trust Layer — RAW → VALIDATED → CANONICAL

```
Flashscore (HTML) → normalize_*() [pur, fără I/O] → RAW → VALIDATED → CANONICAL → Oracle Engine / ML
```

- **RAW** (`flashscore_raw_extraction`, migrația 035): output-ul exact al funcțiilor `normalize_*()` (`providers/flashscore/normalizer.py`), înainte de orice decizie de validare, cheiat pe `(match_ref, tab_name)` — `match_ref` fiind identitatea stabilă PRE-canonică (URL/mid Flashscore), independentă de rezolvarea ulterioară a `match_history.id`. **Se scrie INDIFERENT de rezultatul validării** — un meci respins tot lasă o dovadă RAW completă (North Star #9, trasabilitate). Coloanele `validation_status`/`validation_errors`/`canonical_written` fac starea vizibilă pe același rând, nu într-un tabel separat de audit.
- **VALIDATED**: `udal_validation.validate_flat_identity()` (nou, aditiv) — verifică prezența cheii naturale (`home_team`/`away_team`/`kickoff_date`). `validate_records()` existent (Faza 1 UDAL) **nu a fost reutilizat direct**: `REQUIRED_FIELDS` al lui e fix, specific unui pilot anterior cu formă plată îngustă (`home_cards`/`away_cards` combinate) — nu se potrivește formei reale, bogate, Flashscore (`home_yellow_cards`/`home_red_cards` separate, 20+ câmpuri variabile). Aplicarea directă ar fi respins fals-negativ orice rând valid. `validate_flat_identity()` păstrează același contract de ieșire (`ValidationResult`, proveniență obligatorie `source_tier`/`source_id`/`fetched_at`/`confidence`) — extensie, nu duplicare paralelă.
- **CANONICAL**: `providers/flashscore/persistence.persist_match_foundation_data()` scrie DOAR dacă validarea trece. Niciun bypass — `persist_match_with_data_trust_layer()` (punctul de intrare oficial) apelează scrierea canonică condiționat de `validation.valid`, nu necondiționat.

### 3. Schema Supabase (migrațiile 035/036)

**Coloane noi pe `match_history`** (owner: `upsert_match_canonical`, COALESCE-only, ADR-036): `attendance`, `capacity`.

**Gol închis (migrația 036)**: migrațiile 032/035 adăugaseră `home/away_goalkeeper_saves` și `attendance`/`capacity`, dar RPC-ul canonic `_upsert_match_canonical_locked` nu fusese extins să le scrie — găsit prin citire de cod în timpul implementării acestui ADR, corectat aditiv (CREATE OR REPLACE, același contract).

**4 tabele noi**, toate RLS activ, `UNIQUE` pe cheia lor naturală, scriere prin `ON CONFLICT DO UPDATE` (idempotent, verificat explicit prin teste parametrizate 1/2/10 rulări — zero duplicate, id-uri stabile între rulări):

| Tabelă | Cheie UNIQUE | Conținut |
|---|---|---|
| `match_statistics_extended` | `(match_id, stat_key)` | EAV — ~26 categorii de statistici FĂRĂ coloană dedicată în `match_history` (xGOT, blocked shots, duels won, tackles, etc.) |
| `player_match_stats_extended` | `(player_match_stats_id, stat_key)` | EAV per jucător — 7 statistici avansate (total shots, xG, accurate passes, touches, touches in opposition box, successful dribbles, duels) |
| `flashscore_match_context` | `(context_match_id, category, meeting_order)` | H2H + formă recentă, segmentate pe 3 categorii reale (`h2h_overall`/`recent_form_home`/`recent_form_away`) |
| `flashscore_standings_snapshot` | `(competition, team)` | Clasament curent (snapshot, nu istoric acumulat) |
| `flashscore_raw_extraction` | `(match_ref, tab_name)` | Stratul RAW al Data Trust Layer-ului |

**Justificare schemă EAV** (nu coloane fixe noi per statistică): cerință explicită a proprietarului produsului — „peste un an putem folosi 200 [statistici]... prefer să colectăm date o singură dată... decât să modificăm continuu colectarea datelor”. O schemă EAV absoarbe orice statistică nouă descoperită de Flashscore fără migrare nouă.

### 4. `player_match_stats` — îmbogățire, nu duplicare

Tabelul existent (migrația 032) capătă acum `position`/`rating` populate (deferred în M0, blocat de lipsa unei surse curate — rezolvat de tab-ul dedicat „Statistici jucători”). Rândurile de roster brut (nume/număr/echipă, din Lineups) și rândurile îmbogățite (rating/poziție, din tabelul Player Stats) se scriu prin ACELAȘI `on_conflict=(match_id,team,player_name)` — PostgREST generează `UPDATE SET` doar pentru coloanele prezente în payload, deci scrierea roster-ului nu suprascrie cu `NULL` o îmbogățire scrisă anterior (sau invers). Rezoluția `team` pentru tabelul Player Stats (care nu are coloană de echipă) se face prin join pe nume cu roster-ul din Lineups, la persist(), nu la normalizare — limitare cunoscută, documentată (`providers/flashscore/persistence._join_player_stats_with_roster`).

### 5. Oracle Engine / ML — graniță neatinsă

Acest ADR **nu modifică** `oracle_engine.py`, `ml_predictor.py`, sau vreun flux de blending/confidence. Tabelele noi există, dar niciun consumator nu citește din ele încă — activarea citirii (Oracle Engine → tabele canonice noi) e un task separat, ulterior, condiționat de „Garanțiile obligatorii” de mai jos. `ml_blending_enabled=False` (R-ARCH-REVIEW-01) și ML Activation Gate rămân neatinse.

## Garanții obligatorii înainte de orice integrare Predictor/ML

(cerute explicit de proprietarul produsului, verificate în acest ADR)

1. **Date brute salvate** — ✅ `flashscore_raw_extraction`, scris indiferent de rezultatul validării.
2. **Validarea funcționează** — ✅ `validate_flat_identity()`, testat (accept/reject pe cheie naturală).
3. **Tabele canonice populate corect** — ✅ verificat contra fixture-ului real (36 statistici, 32 jucători, 15 rânduri H2H/formă, 16 echipe clasament — toate valorile verificate manual contra capturii trimise de proprietarul produsului).
4. **Rerun-uri fără duplicate** — ✅ demonstrat explicit, teste parametrizate 1/2/10 rulări (`test_providers_flashscore_persistence_idempotency.py`), inclusiv stabilitatea id-urilor între rulări.
5. **Niciun provider extern nu poate afecta direct modelele** — ✅ prin construcție: Oracle Engine/ML nu citesc din tabelele noi (secțiunea 5); orice integrare viitoare rămâne un task separat, cu propria decizie explicită.

## Consecințe

**Pozitive**:
- Football Oracle capătă o infrastructură de date semnificativ mai bogată (statistici avansate, rating per jucător, context H2H/formă, clasament) fără nicio schimbare de comportament al Predictorului azi.
- Schema EAV absoarbe extensii viitoare fără migrări repetate.
- Trasabilitate completă (RAW păstrat chiar și pentru meciuri respinse) — North Star #9.
- Gol real de RPC (goalkeeper_saves/attendance/capacity) descoperit și închis ca parte a acestei implementări, nu lăsat latent.

**Negative / riscuri acceptate**:
- 4 tabele noi + o funcție RPC redefinită = suprafață de întreținere suplimentară.
- Join-ul nume↔echipă pentru tabelul Player Stats (fără coloană de echipă nativă) e o dependență de calitate a datelor Flashscore — nume ușor diferite între tab-uri ar rupe silențios îmbogățirea (loghează un warning, exclude rândul, nu ghicește — comportament acceptat, nu eliminat).
- Standings folosește clase CSS, nu `data-testid` (mai fragil potențial la schimbări de build Flashscore) — risc documentat explicit în `normalizer.py`, nu ascuns.
- Scrierea live rămâne neactivată (`tos_reviewed=False`) — acest ADR autorizează arhitectura și schema, nu operarea live.

## Alternative respinse

- **Coloane fixe noi per statistică în `match_history`** — respinsă: contrazice explicit filosofia proiectului declarată de proprietarul produsului (colectare o singură dată, fără migrări repetate pe măsură ce apar statistici noi).
- **Reutilizarea directă a `validate_records()`** — respinsă: schema lui fixă ar respinge fals-negativ orice rând real Flashscore (vezi secțiunea 2).
- **Citire directă Oracle Engine → Flashscore** (bypass complet al Data Trust Layer-ului) — respinsă explicit de proprietarul produsului: „Oracle Engine NU citește niciodată din Flashscore direct”.

---

## Addendum (2026-07-29) — „TASK APROBAT — Flashscore Foundation Data Layer (M1)” + „Răspuns oficial — clarificări finale”

Extensie aprobată explicit peste decizia inițială de mai sus, aceeași sesiune. Status: **implementat, testat, nemerge-uit pe `main`**, aceleași garanții (scriere live neactivată, `tos_reviewed=False`).

### A1. Flashscore rămâne sursa principală pentru Foundation Data Layer

Reconfirmă explicit secțiunea „Decizie” §1: providerii API existenți deservesc Discovery Layer și sincronizarea meciurilor; Flashscore e sursa principală pentru **îmbogățirea** bazei de date (statistici extinse, context, clasament, cote).

### A2. Odds — gol închis

`normalize_odds()` (nou) extrage cota curentă 1X2 per bookmaker din tab-ul dedicat, structură verificată pe fixture (`.oddsCell__bookmakerPart`/`.oddsCell__odd`, ordine confirmată prin `data-analytics-label`, nu presupusă din poziție DOM). Inclus în stratul RAW (`flashscore_raw_extraction`). **Scrierea CANONICĂ în `odds_fallback_flashscore` (ADR-043) rămâne deliberat neimplementată** — necesită rezolvarea identității `fixture_id` cross-provider (aceeași valoare folosită de The Odds API/alți provideri), un task separat, documentat deja de ADR-043 ca „ulterior”; scrierea cu o cheie greșită ar rupe silențios regula de fallback a Predictorului (ar scrie rânduri pe care Predictorul nu le-ar găsi niciodată).

### A3. `flashscore_match_context.competition_code` — gol închis

Populat acum din elementul real `.h2h__event` (text scurt, ex. „SL” pentru SuperLiga) — verificat direct pe fixture, era documentat explicit ca gol de populare în raportul anterior.

### A4. Data Completeness Score (regulă nouă, persistat, neconsumat)

Tabelă nouă `flashscore_data_completeness` (migrația 037) — 7 flag-uri boolean (unul per tab confirmat în POC: Summary/Statistics/Lineups/PlayerStats/Odds/H2H/Standings) + `coverage_percent`. Calculat de `compute_data_completeness()` la nivel de FETCH (pagina a fost adusă sau nu), nu la nivel de succes al extracției — definiție simplă, robustă, verificabilă direct din `pages`. Scris **indiferent** de rezultatul validării Data Trust Layer (proprietate a colectării, nu a validării). **Nu e citit de Oracle Engine azi** — doar persistat pentru folosire viitoare, exact cum a cerut proprietarul produsului.

### A5. Modelul de sezon (migrația 038)

Coloană nouă `season` (TEXT, nullable) pe `match_history` și toate cele 7 tabele Foundation Data Layer. Regulă strictă, neechivocă: **`season` se scrie DOAR dacă providerul apelant îl oferă explicit — niciodată dedus din reguli calendaristice proprii.** Verificat direct pe fixture: Flashscore nu expune un sezon robust în niciunul din cele 7 tab-uri confirmate azi (breadcrumbs au doar „Superliga - Round 2”, fără an) — `normalize_*()` rămân neschimbate; `season` e parametru explicit la `persist_match_foundation_data()`/`persist_match_with_data_trust_layer()`, propagat uniform la toate scrierile FK-dependente ale unui meci, niciodată derivat în interiorul modulului. O tabelă de configurare per competiție (calendarul real per ligă) rămâne un task viitor, separat, neînceput.

Motivația explicită a proprietarului produsului: Oracle și ML vor pondera istoricul pe sezon (ex. sezon curent 100%, precedent 70%, acum doi ani 40%) — logică **neimplementată acă**, dar coloana trebuie să existe din Foundation Data Layer ca fundația să nu ceară un al doilea val de migrări.

### A6. Season Cleanup — infrastructură DOAR, fără ștergere

Fluxul oficial complet: `Discovery → Validation → Cleanup Report → Backup → Delete → Integrity Check → Final Report`. **În această etapă se implementează DOAR primii doi pași** (`providers/flashscore/season_cleanup.py`):

- `discover_seasons()` — pură, calculează candidații de cleanup sub politica de retenție (**6 sezoane: curent + 5 istorice**), sortare lexicală pe formatul `"YYYY-YYYY"` (coincide cu ordinea cronologică). Rândurile fără sezon (`NULL`) sunt raportate separat, niciodată tratate ca sezon real.
- `build_cleanup_dry_run_report()` — interoghează Supabase, agregă pe cele 6 tabele din scope.

**Scope explicit, restrâns** (răspunsul proprietarului produsului la întrebarea de clarificare): **EXCLUSIV** tabelele Foundation Data Layer (`match_statistics_extended`, `player_match_stats_extended`, `flashscore_match_context`, `flashscore_standings_snapshot`, `flashscore_raw_extraction`, `flashscore_data_completeness`). **NU** `match_history`/`match_events`/`player_match_stats` de bază (ar afecta direct istoricul ML, `used_for_training`, și North Star #9). **NU** `odds_history` — document Frozen (ADR-005/006/010), orice atingere cere ADR dedicat, nu poate intra tacit în scope-ul acestui job.

**Garanție explicită, verificabilă direct în cod**: `delete_executed` e mereu `False` — acest modul nu conține nicio operație `DELETE`, niciun cron, nicio activare automată. Ștergerea reală (pașii Backup/Delete/Integrity Check/Final Report) rămâne neimplementată, activabilă ulterior printr-un flag dedicat, separat, cu propria aprobare explicită.

---

## Addendum 2 (2026-07-29) — Corecție arhitecturală: timeline-ul de evenimente a fost afirmat greșit ca neextractibil

**Context**: în timpul construirii `docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md` (cerută explicit de proprietarul produsului, ca reacție la un raport de câmpuri considerat insuficient de riguros), s-a descoperit că `providers/flashscore/normalizer.py` conținea, în docstring-ul modulului (moștenit din faza M0), afirmația:

> „goluri/cartonase NU au minut vizibil in structura verificata — deferred, nu ghicit"

**Această afirmație era falsă.** Verificat direct pe fixture (`docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/summary.html`): tab-ul Summary conține un timeline complet, curat, structurat (`.smv__participantRow`, 21 evenimente reale pe fixture-ul principal) — minut, tip eveniment (identificat robust: `data-testid` pe SVG pentru gol/penalty/schimbare/VAR; clasă CSS pe SVG pentru cartonașe, care NU au `data-testid`), jucător, echipă, și pentru fiecare tip context suplimentar (assist la goluri, jucătorul care iese la schimbări, motivul la cartonașe, textul deciziei la VAR).

**De ce s-a întâmplat**: concluzia inițială a fost formulată probabil pe baza unui widget diferit („Match Momentum", un grafic vizual real, corect exclus) și generalizată greșit la întregul timeline de evenimente, care e text structurat, nu grafic. Nu a fost re-verificată ulterior, deși scope-ul M0/Foundation Data Layer s-a extins semnificativ față de verificarea inițială.

**Corecție aplicată** (implementată, testată, aplicată live — nu doar documentată):
- `normalize_match_events()` rescrisă complet — citește acum din tab-ul Summary, nu din tab-ul Lineups (sursă veche, mai fragilă, doar substituții).
- Migrația 039: `match_events.event_type` extins la 9 valori (`goal`, `own_goal`, `penalty_goal`, `penalty_missed`, `yellow_card`, `red_card`, `second_yellow_card`, `substitution`, `var`); `player_name` cu sentinel `''` (nu `NULL`) pentru evenimente fără jucător asociat (VAR); coloană nouă `detail` (motiv cartonaș/text decizie VAR); cheie naturală extinsă pentru identitate unică fără jucător.
- Scor final (`actual_home_goals`/`actual_away_goals`) și scor la pauză (`home_ht_goals`/`away_ht_goals`) — coloane deja existente în `match_history` (migrația 008), la fel niciodată extrase, corectat în același efort.
- Toate scrise prin `persist_match_foundation_data()`, verificate idempotent (1/2/10 rulări, 0 duplicate) — vezi `docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md` secțiunea 0 pentru dovada completă.

**Ce rămâne, explicit, neconfirmat** (nu ascuns): `own_goal`/`penalty_missed`/`second_yellow_card` — mecanismul de clasificare există și e identic cu cel al celorlalte 6 tipuri, dar niciunul din aceste 3 tipuri nu a apărut în cele 11 fixture-uri capturate până acum — selectorul lor exact rămâne neconfirmat, cod pregătit să le accepte imediat ce apare un fixture real cu unul din ele.

**Lecția de guvernanță**: acest ADR reflectă acum starea reală — o afirmație arhitecturală infirmată nu rămâne nedocumentată. Vezi `docs/06_UDAL/FLASHSCORE_FIELD_MAPPING_MATRIX.md` pentru matricea completă, cu fiecare câmp nemapat clasificat explicit (Parser oversight / Schema gap / Cross-provider dependency / Decizie ADR) — nicio categorie generică „nu există sursă curată".
