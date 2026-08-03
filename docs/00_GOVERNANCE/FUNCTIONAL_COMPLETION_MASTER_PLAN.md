# FUNCTIONAL COMPLETION MASTER PLAN — Football Oracle

**Data**: 2026-08-03 · **Tip document**: audit, nu plan de execuție — **niciun cod, ADR, schemă Supabase, Oracle Engine, Predictor, ML sau UI nu a fost modificat pentru a produce acest document.**

**Metodologie**: verificare independentă, de la zero — fiecare afirmație de mai jos e susținută de o dovadă obiectivă citată explicit (fișier:linie, query SQL rulat live pe proiectul `Prediction`, `git log`/`git show`, `grep`). Nu s-au reluat concluziile Master Repair Plan-ului anterior fără re-verificare; unde re-verificarea a confirmat un fix real, e marcat ca atare; unde a găsit o discrepanță (inclusiv una care contrazice propriile mele rapoarte din sesiunea de audit anterioară a acestei conversații), e raportată explicit, cu corecția.

**Master Repair Plan (infrastructură + bază de date)**: închis. Acest document acoperă etapa următoare — completitudine funcțională (P2–P6).

---

## Sumar — toate problemele găsite, ordonate după severitate

| # | Severitate | Domeniu | Titlu |
|---|---|---|---|
| 1 | 🔴 Critic | P2 | `RateLimitManager` fail-open real pentru 5 provideri — protecția e cablată dar nu primește niciodată date |
| 2 | 🟠 Major | P4 | Nicio verificare de non-regresie cu ieșiri fixe pentru Predictor — imposibil de demonstrat că migrările P1 nu au schimbat vreo predicție |
| 3 | 🟠 Major | P3 | `flashscore_data_completeness` — scris, niciodată citit de Oracle Engine |
| 4 | 🟠 Major | P5 | Acoperire reală derivate ML (`corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance`): 17,1% din `match_history`, nedocumentat în `ML_ACTIVATION_GATE.md` |
| 5 | 🟡 Minor | P2 | `poc_api_football_league_lookup.yml` — workflow redundant, confirmat prin diff |
| 6 | 🟡 Minor | P2 | `scheduled_fixtures.status` — o singură valoare posibilă în date, mecanism de tranziție neexercitat |
| 7 | 🟡 Minor | P2 | `sportapi` — provider înregistrat, zero adaptor, decizie nefăcută (dar fără risc de crash, verificat) |
| 8 | 🟡 Minor | P3 | Team DNA — 12+ câmpuri calculate, niciodată afișate în UI (`avg_goals_for/against`, `matches_sampled`, `players_sampled`, restul standings) |
| 9 | 🟡 Minor | P6 | 5 tabele Supabase cu schemă completă, RLS activ, zero rând scris vreodată (`upcoming_matches`/`upcoming_lineups`/`upcoming_match_features`/`flashscore_acquisition_queue`/`odds_fallback_flashscore`) |
| 10 | 🔵 Cosmetic | P6 | Panoul „Poisson vs. Monte Carlo" nu are notă explicativă — poate induce impresia de două motoare independente |
| 11 | 🔵 Cosmetic | P3 | `shadow_predictions`/`experiment_registry` goale — cauză acum confirmată (flag oprit implicit), nu eroare silențioasă cum specula auditul anterior |

**Notă despre severități**: #11 a fost retrogradat de la 🟠 Major (cum apărea în auditul precedent) la 🔵 Cosmetic, pentru că investigația din acest document a demonstrat cauza exactă și benignă — nu mai e o necunoscută care ar putea ascunde o eroare reală.

---

## P2 — Data Collection

### 2.1 — `RateLimitManager` fail-open real pentru 5 provideri
**Severitate**: 🔴 Critic

**Dovadă**:
- `sync_orchestrator.py:120` → `if not self._request_manager.should_request(task.provider): return False, "buget epuizat"` — gate-ul există și e apelat real, pentru orice task înregistrat.
- `request_manager.py:82-88` → `should_request()` delegă la `self._rate_limiter.can_request(provider)`.
- `rate_limit_manager.py:106-113` → `can_request()`: `state = self._state.get(provider); if state is None: return True`. Fail-open explicit, documentat chiar în docstring (linia 13-15): „Fail-open pana atunci: niciun comportament de azi nu se schimba pentru un provider care nu trimite niciodata aceste header-e".
- `self._state` se populează DOAR prin `record_response_headers()`. `grep -rn "record_response_headers"` pe tot proiectul → apare exclusiv în `oracle_api.py`, `football_providers.py` (API-Football) și `soccerfootballinfo_client.py` (Soccer Football Info). **Zero apel** din `sync/sync_team_form_footballdata.py`, `sync/sync_team_stats_tsdb.py`, `sync/sync_national_team_elo.py`, `sync/sync_weather_forecast.py`, `sync/sync_odds_recent_results.py` sau din vreun modul HTTP folosit de acestea.

**Impact**: pentru football-data.org, TheSportsDB, eloratings.net, WeatherAPI și Odds API, `can_request()` va întoarce `True` la infinit — protecția reală de buget nu există pentru acești 5 provideri, deși codul „pare" conectat (task-ul e înregistrat, gate-ul e apelat). Eloratings.net e scraping HTML static — foarte probabil nu trimite niciodată header-e `x-ratelimit-*`, deci gate-ul e structural imposibil de activat pentru el, indiferent de cod viitor adăugat în providerul respectiv.

**Recomandare**: fie se implementează `record_response_headers()` pentru fiecare din cei 5 provideri (dacă header-ele lor reale de rate-limit au alt nume, `_first_int()` din `rate_limit_manager.py` trebuie extins să le recunoască — verificare live necesară per provider), fie se documentează explicit că aceștia rămân neprotejați și se evaluează un mecanism alternativ (throttling static, de exemplu). Nu implementat aici, doar semnalat.

---

### 2.2 — `poc_api_football_league_lookup.yml` redundant
**Severitate**: 🟡 Minor

**Dovadă**: `diff .github/workflows/poc_api_football_league_lookup.yml .github/workflows/poc_api_football_statistics.yml` — al doilea fișier conține deja un pas condiționat (`if: github.event.inputs.lookup_country != ''`) care rulează exact `python sync/poc_api_football_league_lookup.py --country ...`, identic cu singurul pas al primului fișier (32 linii). Primul fișier există încă în `.github/workflows/`.

**Impact**: zero — workflow POC, fără efect asupra producției, doar zgomot de întreținere.

**Recomandare**: ștergere directă, fără risc.

---

### 2.3 — `scheduled_fixtures.status` blocat pe o singură valoare
**Severitate**: 🟡 Minor

**Dovadă**: query live (`Prediction`, 2026-08-03): `SELECT count(DISTINCT status) FROM scheduled_fixtures` → **1**, pe **136** rânduri totale.

**Impact**: fie tabelul nu urmărește starea reală a unui meci programat (finalizat/anulat/amânat), fie mecanismul de tranziție de stare există în cod dar nu a fost niciodată exercitat live. Nedeterminat fără investigație suplimentară de cod.

**Recomandare**: investigație separată (read-only) — găsește codul care ar trebui să scrie o altă valoare de `status` și verifică de ce nu se declanșează.

---

### 2.4 — `sportapi`: provider înregistrat, zero adaptor — dar fără risc de crash
**Severitate**: 🟡 Minor

**Dovadă**:
- `sync_provider_manager.py:56` → `"match_statistics": ("soccerfootballinfo", "freelivefootball", "sportapi")` — face parte activ din lanțul de fallback.
- `Glob *sportapi*` → doar `sync/poc_sportapi_check.py`, `sync/poc_sportapi_deep_check.py`, `sync/poc_sportapi_season_call_check.py` (POC-uri). Zero fișier adaptor real.
- **Verificare de siguranță**, făcută explicit ca să nu se raporteze un risc inexistent: `sync/sync_match_statistics.py:140-143` → `adapter = _get_adapter(provider_id); if adapter is None: logger.debug(...); continue`. Cazul „provider fără adaptor" e gestionat explicit, cu skip elegant, nu excepție.

**Impact**: zero risc funcțional (dovedit, nu presupus). Rămâne doar o decizie de curățenie neluată — cod „fantomă" în lanțul de fallback, care nu va fi niciodată selectat cu efect.

**Recomandare**: decizie simplă — elimină `"sportapi"` din tuple sau implementează adaptorul. Fără urgență.

---

### 2.5 — Restul P2 (acquisition queue, provider ownership, duplicate fetch, polling inutil)
**Verificat, fără constatări suplimentare demonstrabile**:
- `flashscore_acquisition_queue` — 0 rânduri, schemă completă, cod de scriere/citire există dar nedeclanșat (vezi §6.2, secțiunea P6, pentru clasificarea completă „tabelă neutilizată").
- Polling FreeLF (`sync_lineup_freelf.py`) — cadență redusă la 30 min (confirmat, `lineup_sync.yml:21`), dar fără detectare de schimbare a lotului — `grep` pentru orice hash/comparație de payload în fișier → zero rezultat. Nu e o problemă nouă față de ce a fost deja documentat, deci nu o repet ca item separat de severitate.

> Nu am găsit probleme demonstrabile suplimentare pentru „provider ownership" (rolul fiecărui provider e documentat explicit în `sync_provider_manager.py` prin tuple-urile de fallback, verificat prin cod, nu presupus) sau „duplicate fetch" dincolo de ce e deja acoperit în §2.1 și în Master Repair Plan (P1-02, deja închis, re-confirmat live: 0 duplicate).

---

## P3 — Oracle Engine

### 3.1 — `flashscore_data_completeness`: scris, niciodată citit de Oracle Engine
**Severitate**: 🟠 Major

**Dovadă**:
- Query live: `SELECT count(*) FROM flashscore_data_completeness` → **328** rânduri (date reale, scrise).
- `grep -n "flashscore_data_completeness\|data_completeness_score" oracle_engine.py` → **zero rezultate**.

**Impact**: un semnal de încredere per meci (cât de complet e setul de date Flashscore pentru acel meci) există, calculat, dar nu influențează în niciun fel predicția sau vreo decizie de rating — pur „write-only" la nivelul motorului de predicție.

**Recomandare**: decizie explicită (integrare ca semnal de încredere în Oracle Engine, sau documentare că rămâne doar diagnostic UI). Nu implementat aici.

---

### 3.2 — `match_events` / `player_match_stats`: consumate de UI, NU de motorul de predicție (corecție față de auditul precedent)
**Severitate**: informativ — nu e o problemă nouă, e o corecție de acuratețe

**Dovadă**:
- `app.py:1331` → `events = fdl_queries.get_match_events(match_id)`, afișat ca tabel „Marcatori" + „Timeline evenimente" (linii 1333-1360).
- `app.py:1363` → `players = fdl_queries.get_player_match_stats(match_id)`, afișat ca „Roster + rating" (linia 1362-1367).
- Ambele apar într-un tab de diagnostic per-meci (detaliu al unui meci deja jucat), nu în fluxul de generare a predicției.
- În `oracle_engine.py:835`, `build_team_dna(advanced_rows, extended_rows, player_rows, standings_row, canonical)` construiește Team DNA folosind și date din `player_match_stats` — **dar** rezultatul (`home_flashscore_dna`/`away_flashscore_dna`) e folosit DOAR pentru shadow logging (`oracle_engine.py:1668-1674`, `experiment_name="flashscore_team_dna"`), niciodată pentru a schimba `home_xg`/`away_xg`/`ph`/`pd`/`pa` — confirmat prin citirea directă a codului din jurul liniei 1655 (predicția finală e deja calculată înainte de acest bloc).

**Concluzie**: afirmația „scrise canonic, niciodată agregate" (din auditul anterior) e **falsă parțial** — sunt agregate (Team DNA) și afișate (UI diagnostic), dar corect NU alimentează predicția reală, exact conform regulii „Predictorul rămâne neatins". Nu e un defect — comportamentul e cel intenționat.

---

### 3.3 — `shadow_predictions`/`experiment_registry` goale — cauză acum confirmată, nu mai e necunoscută
**Severitate**: 🔵 Cosmetic (retrogradat față de auditul anterior)

**Dovadă**:
- Query live: `shadow_predictions` = **0** rânduri, `experiment_registry` = **0** rânduri.
- `oracle_engine.py:171` → `"flashscore_shadow_logging_enabled": False` (implicit oprit, în `DEFAULT_CONFIG`).
- Codul de la §3.2 (`oracle_engine.py:1668-1674`) apelează `log_shadow_experiment(...)` DOAR dacă acest flag e pornit — și nu e, implicit, nicăieri.

**Impact**: comportament corect, nu bug. Auditul precedent specula „cauză neconfirmată... eșec silențios" — fals; cauza e un flag explicit oprit, exact conform Regulii North Star #3 („niciun flag nou nu pornește implicit activ"). Tabelele rămân goale pentru că nimeni nu a decis încă să activeze shadow logging-ul, nu pentru că ceva e stricat.

**Recomandare**: dacă se dorește vreodată ablație reală pe Team DNA Flashscore, activarea `flashscore_shadow_logging_enabled=True` e singurul pas necesar — infrastructura există și funcționează (verificat prin citire de cod, nu testat live în acest audit, pentru că ar necesita o schimbare de flag = modificare de comportament, în afara mandatului „doar audit").

---

### 3.4 — Team DNA: 12+ câmpuri calculate, niciodată afișate în UI
**Severitate**: 🟡 Minor

**Dovadă**: `grep -n "matches_sampled\|players_sampled\|avg_goals_for\|avg_goals_against" app.py` → **zero rezultate**. Aceste câmpuri sunt calculate de `flashscore_team_dna.py` (confirmat prin apelul de la `oracle_engine.py:835`) și există în structura `home_flashscore_dna`/`away_flashscore_dna` folosită la §3.2/§3.3, dar UI-ul (`app.py:517`, unde `pred.home_flashscore_dna` chiar e citit) nu le extrage individual pentru afișare.

**Impact**: date reale, calculate, plătite (request-uri Flashscore reale), nefolosite nicăieri vizibil utilizatorului.

**Recomandare**: extinde cardul Team DNA din UI să afișeze aceste câmpuri, dacă se consideră valoare pentru utilizator. Nu implementat aici.

---

## P4 — Predictor

### 4.1 — Nicio verificare de non-regresie cu ieșiri fixe
**Severitate**: 🟠 Major

**Dovadă**: `ls tests/ | grep -i "snapshot\|golden\|regression"` → zero fișier dedicat. Singurul test cu „compat" în nume, `tests/test_oracle_engine_compat.py`, verifică DOAR integritatea cheilor din `DEFAULT_CONFIG` (linia 10-20) și comportamentul flag-urilor de shadow logging — **nu compară niciun `home_xg`/`away_xg`/`prob_home`/`prob_draw`/`prob_away` produs efectiv pentru un set fix de meciuri, înainte și după o migrare de date**.

**Impact**: Master Repair Plan a executat migrări reale de date pe `match_history` (normalizare nume ligă, deduplicare, backfill `season`/`stats_source`, DROP tabele backup) — toate verificate să nu schimbe *schema* sau *codul* Predictorului, dar **nu există nicio dovadă automatizată că valorile efective ale predicțiilor servite azi sunt identice cu cele de dinainte de migrări**, pentru meciuri care ar fi fost afectate de deduplicare sau de schimbarea numelui de ligă (de exemplu, un meci care exista dublat sub `kaggle_*`/`fd_*` înainte de P1-02 ar fi putut influența diferit un calcul de formă/ELO recent, față de acum, cu un singur rând canonic).

**Recomandare**: construiește un set fix de 10-20 meciuri reale (cu rezultat cunoscut), rulează Predictorul înainte/după orice migrare viitoare de date, compară exact `home_xg`/`away_xg`/`ph`/`pd`/`pa`. Pentru migrările deja executate (P1-01/02 în special), acest control a rămas neefectuat — nu mai poate fi reconstituit retroactiv „înainte", pentru că starea „înainte" nu mai există în producție (doar în arhivele SQL din `docs/00_GOVERNANCE/archive/sql_backups/`, care ar putea servi ca bază pentru un test retroactiv, dacă se dorește).

---

### 4.2 — Restul P4 (feature pipeline, diferențe de output, consistență)
**Verificat, fără constatări suplimentare demonstrabile**: `FEATURE_COLUMNS` (`ml_predictor.py:86-121`) e neschimbat față de ultima intrare documentată în cod (ADR-021/P7.1), nicio urmă de modificare recentă necomunicată. `pytest tests/` rulează verde (1903 passed, 2 skipped, aceleași 3 eșecuri preexistente `test_oracle_api_tsdb_per_league_gate.py`, nelegate de Predictor) — dar, așa cum arată §4.1, testele verzi nu demonstrează absența unei regresii de *valoare*, doar absența unei erori de *execuție*.

---

## P5 — ML

### 5.1 — Acoperire reală derivate ML: 17,1%, nedocumentată
**Severitate**: 🟠 Major

**Dovadă**: query live (`Prediction`, 2026-08-03):
```sql
SELECT count(*) AS total,
       count(*) FILTER (WHERE home_corner_avg_recent IS NOT NULL) AS corner_avg_present
FROM match_history;
-- total=53.769, corner_avg_present=9.215 (17,1%)
```
Aceleași 9.215 rânduri gatează toate cele 4 feature-uri derivate (`corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance` — toate calculate din `home/away_corner_avg_recent`, `home/away_card_avg_recent`, `home/away_foul_avg_recent`, `home/away_shot_avg_recent`, per `ml_predictor.py:100-120`).

`git log -3 -- docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md` → ultima modificare e `2129cbb` („Faza 3: flashscore_team_dna shadow experiment"), înainte de tot Master Repair Plan-ul. `grep` pentru `corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` în acest document → zero rezultate.

**Impact**: 4 din cele 14 `FEATURE_COLUMNS` (promovate anterior prin teste de ablație reale, documentate riguros — `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`, `FOULS_DOMINANCE_ABLATION_2026-07-14.md`, `SHOT_DOMINANCE_ABLATION_2026-07-15.md`) sunt `NULL` pentru 82,9% din setul de antrenare azi. Modelul se antrenează parțial „orb" pe acele coloane pentru majoritatea rândurilor — comportament corect al `ml_predictor.py` (nicio aproximare, valorile lipsă rămân `NULL`), dar `ML_ACTIVATION_GATE.md` nu documentează explicit această limitare structurală pentru cititorul viitor care ar evalua o nouă activare de blending.

**Recomandare**: adaugă o secțiune în `ML_ACTIVATION_GATE.md` care documentează explicit acoperirea reală per feature derivat, ca parte a condiției #3 (test de ablație măsurat) — cerință deja identificată în Master Repair Plan (P5-01), încă neînchisă.

---

### 5.2 — Restul P5 (feature engineering, training pipeline, ablation docs)
**Verificat, fără constatări suplimentare demonstrabile**: cele 3 documente de ablație citate în comentariile din `ml_predictor.py` există (`docs/03_ENGINE/`), walk-forward validation rămâne singura cale de antrenare (`ml_predictor._walk_forward_validate()`, neatinsă). Deduplicarea (P1-02) fiind confirmată live rezolvată (0 duplicate), premisa riscului „teste de ablație anterioare afectate de duplicate" (P5-02 din Master Repair Plan) a dispărut — dar, la fel ca P5-01, faptul că a dispărut nu e documentat explicit nicăieri pentru cititorul viitor.

> Nu am găsit probleme demonstrabile în pipeline-ul de training propriu-zis dincolo de golul de documentare de mai sus.

---

## P6 — UI (Streamlit)

### 6.1 — Panoul „Poisson vs. Monte Carlo" fără notă explicativă
**Severitate**: 🔵 Cosmetic

**Dovadă**: neschimbat față de constatarea inițială — panoul afișează două seturi de probabilități fără context textual care să clarifice că nu compară două motoare independente. Nu am găsit nicio adăugare de tooltip/notă în `app.py` legată de acest panou.

**Impact**: posibilă confuzie a utilizatorului, zero impact funcțional.

**Recomandare**: notă/tooltip scurt. Nu implementat aici.

---

### 6.2 — 5 tabele Supabase cu schemă completă, zero rând scris vreodată
**Severitate**: 🟡 Minor

**Dovadă**: verificat live, din auditul Master Repair Plan anterior, re-confirmat aici ca fiind încă adevărat (nicio scriere nouă între timp): `upcoming_matches`, `upcoming_lineups`, `upcoming_match_features`, `flashscore_acquisition_queue`, `odds_fallback_flashscore` — toate 0 rânduri, `n_tup_ins=0` în `pg_stat_user_tables`, schema aplicată live (migrația 032), RLS activ.

**Impact**: nu sunt „tabele moarte" în sensul de abandonate fără scop — au acoperire explicită în ADR-043 (ACCEPTAT) și în design-ul R-Sync-FLASH-01 (Pre-Match Sync, coadă de bootstrap), deliberat amânate, nu uitate. Includerea lor aici e pentru completitudine față de cerința explicită „tabele nefolosite", nu pentru a semnala o problemă nouă.

**Recomandare**: niciuna — status corect, documentat, decizie deja luată explicit în sesiunea Master Repair Plan (P1-09).

---

### 6.3 — Restul P6 (informații duplicate, informații moarte)
**Verificat, fără constatări suplimentare demonstrabile** dincolo de §3.4 (Team DNA write-only) și §6.1/§6.2 de mai sus.

> Nu am găsit informații duplicate demonstrabile în UI (fiecare panou afișează o sursă de date distinctă, verificat prin `grep` pe apelurile `fdl_queries.*`/`sb.*` din `app.py`).

---

## Ce NU a fost verificat exhaustiv în acest document (limitări onestă)

- **P2-04** (dacă `oracle_engine.py`/`app.py` mai depind de `get_matches_for_week()` pentru descoperirea de meciuri live, în paralel cu `scheduled_fixtures`) — am găsit infrastructură de shadow/migration-gate (`scheduled_fixtures_shadow.py`) mai avansată decât presupunea auditul inițial, dar nu am trasat complet calea de execuție. Rămâne un gol de verificare explicit, nu o concluzie.
- **Cifra exactă „6.111 scanări complete"** din raportul de performanță original — nu am reușit să o reproduc identic din `pg_stat_statements`/`pg_stat_user_tables` live; diagnosticul de fond (paginare OFFSET costisitoare în `get_training_data()`) rămâne solid și verificat separat prin `EXPLAIN ANALYZE`.
- **Testarea efectivă a activării `flashscore_shadow_logging_enabled`** — nu a fost pornită, pentru că ar constitui o schimbare de comportament, în afara mandatului strict „doar audit" al acestui document.

---

## Confirmare finală

Niciun fișier de cod, ADR, schemă Supabase sau configurație nu a fost modificat pentru a produce acest document. Toate query-urile SQL rulate au fost exclusiv `SELECT`/`EXPLAIN`, read-only, pe proiectul `Prediction`.
