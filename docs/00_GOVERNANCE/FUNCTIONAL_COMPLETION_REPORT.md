# Functional Completion Report — Engine Completion (EPIC 1–5)

**Status**: Final review completed. Implementation status:
- P1 ✅ Implemented
- P2 ✅ Implemented
- P3 🟡 Deferred after architectural review — necesită `FOLLOW-UP-P3-01` înainte de orice implementare
- P4 ✅ Implemented
- P5 ✅ Implemented

**Perioadă**: 2026-08-03 (sesiune unică).

**Autor**: Claude, la cererea proprietarului produsului.

**Scop**: raport formal de status pentru cele 5 puncte ale EPIC-ului „Functional Completion" (audit de bază: `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md`) — deschis explicit după închiderea Master Repair Plan-ului, cu ordine strictă de execuție impusă de proprietarul produsului: „Lucrăm strict în această ordine, fără să sărim peste pași." **Statusul final NU e uniform** — 4 din cele 5 puncte sunt închise (`IMPLEMENTED`), unul (Punctul 3) rămâne explicit **`DEFERRED`**, nu închis — vezi Rezumatul executiv de mai jos.

---

## Rezumat executiv

| Punct | Titlu | Status |
|---|---|---|
| **P1** | Eliminarea fail-open din RateLimitManager | ✅ **IMPLEMENTED** |
| **P2** | Predictor Regression Suite | ✅ **IMPLEMENTED** |
| **P3** | `flashscore_data_completeness` ca semnal de încredere | 🟡 **DEFERRED AFTER ARCHITECTURAL REVIEW** — vezi `FOLLOW-UP-P3-01` |
| **P4** | Documentarea acoperirii reale a feature-urilor ML derivate | ✅ **IMPLEMENTED** |
| **P5** | Curățare/îmbunătățire UI (Team DNA, Poisson vs. Monte Carlo) | ✅ **IMPLEMENTED** |

**Stare globală „Engine Completion"**: **4 din 5 puncte închise complet** (P1, P2, P4, P5) — infrastructură de protecție reală (rate-limiting), infrastructură de verificare reală (regression suite), documentație de guvernanță actualizată cu date live, și prezentare UI îmbunătățită pentru date deja calculate. **1 punct amânat explicit, nu eșuat** (P3) — investigația a demonstrat că premisa inițială a EPIC-ului era invalidă, iar decizia corectă a fost să NU se implementeze nimic pe un semnal fără valoare informațională, nu să se forțeze o integrare. Zero regresie introdusă în cele 4 puncte implementate (1903→1976 teste trecute, +73 exact cât s-a adăugat — P5 n-a adăugat teste automate, vezi secțiunea proprie). Oracle Engine, Predictorul și ML rămân complet neatinse pe tot parcursul EPIC-ului P1–P5 — singurele schimbări de cod au fost în stratul de acces la provideri externi (`oracle_api.py`, `rate_limit_manager.py`), în infrastructura de testare, și, la P5, strict în prezentarea UI (`app.py`).

---

## Punctul 1 — Eliminarea fail-open din RateLimitManager

**Status**: ✅ IMPLEMENTED.

### Problema inițială

`RateLimitManager` (introdus ADR-038, R4.1) recunoștea DOAR convenția de header-e API-Football (`x-ratelimit-*`). `can_request()` e fail-open prin design cât timp niciun header cunoscut nu a fost citit — plasă de siguranță corectă ca principiu, dar devenită bug real pentru cei 5 provideri care nu foloseau niciodată acea convenție: TheSportsDB, WeatherAPI, The Odds API, eloratings.net, football-data.org. Pentru aceștia, gating-ul de buget nu se activa NICIODATĂ — fail-open PERMANENT, nu temporar.

### Dovada că exista

- Cod: `rate_limit_manager.py` (înainte de fix) — `_DAILY_LIMIT_HEADER`/`_DAILY_REMAINING_HEADER`/`_MINUTE_LIMIT_HEADER`/`_MINUTE_REMAINING_HEADER` hardcodate la o singură schemă de nume.
- Live: POC dedicat (`sync/poc_rate_limit_headers_check.py`, temporar, șters după închidere), un singur apel HTTP real per provider prin exact punctul de intrare de producție (`FootballOracleAPI._get()`), rulare GitHub Actions **`30831280759`** (2026-08-03):
  - The Odds API → `x-requests-remaining: 484`, `x-requests-used: 16` (header real, nerecunoscut).
  - WeatherAPI → `x-weatherapi-qpm-left: 999999` (header real, nerecunoscut).
  - TheSportsDB → zero header-e de rate-limit (confirmat, nu presupus).
  - eloratings.net → zero header-e de rate-limit (confirmat).
- Verificare încrucișată live (`provider_call_log`, Supabase): un prim run al POC-ului a arătat inițial 401 fals pentru WeatherAPI/Odds API — investigat, dovedit bug propriu al POC-ului (dict de cheie trimis brut în loc de string, corectat commit `48bb3e5`), NU o problemă de producție — 181 apeluri reale reușite Odds API confirmate în aceeași fereastră.

### Soluția implementată

- `rate_limit_manager.py`: `_PROVIDER_SCHEMES` — mapare explicită, per provider, header real → slot intern (`daily_limit`/`daily_remaining`/`minute_limit`/`minute_remaining`). `_DEFAULT_SCHEME` (API-Football) rămâne neschimbată pentru `apifootball`/`soccerfootballinfo`.
- `oracle_api.py::_get()`: gating (`should_request`) + înregistrare (`record_response_headers`) devin **universale**, aplicate automat pe baza providerului detectat din URL (`_detect_provider_endpoint()`) — orice provider nou capătă automat același gating.
- TheSportsDB: throttling static documentat (1.0s/cerere, interval conservator — nicio documentație oficială confirmată găsită, notat explicit ca atare).
- eloratings.net: protecție structurală documentată (scrape unic + cache 24h deja existent) — fără enforcement suplimentar necesar.
- football-data.org: deja rezolvat anterior (`REQUEST_INTERVAL=6.1s`, `sync/sources/football_data.py`) — neatins.
- Eliminată înregistrarea manuală duplicată din `_free_lf_get()` (redundantă față de gating-ul universal).
- Documentație: `docs/00_GOVERNANCE/ADR-046-provider-rate-limit-protection-matrix.md` — matricea completă provider/header/mecanism/motiv.

### Commit-uri relevante

- `9f18133` — POC inițial (temporar).
- `48bb3e5` — fix bug propriu POC (cheie brută vs. string).
- `4e4eec1` — **implementarea reală**: `Fix universal RateLimitManager integration and remove fail-open for supported providers`.

### Modul de validare

- 12 teste noi (`tests/test_rate_limit_manager.py` — scheme per provider; `tests/test_oracle_api_rate_limit_gating.py`, fișier nou — gating universal, fail-open păstrat pentru dubluri de test, throttling TheSportsDB).
- Suită completă la momentul commit-ului: 1915 passed / 2 skipped / aceleași 3 eșecuri preexistente și necorelate (`test_oracle_api_tsdb_per_league_gate.py`) — baseline neschimbat față de dinaintea EPIC-ului (1903 passed).

### Riscuri rămase

- Intervalul static pentru TheSportsDB (1.0s) e o alegere internă conservatoare, nu dintr-o documentație oficială confirmată — poate necesita ajustare dacă apare o sursă oficială.
- The Odds API/WeatherAPI nu au header explicit de „limit" (doar „remaining") — `RateLimitManager` urmărește doar epuizarea, fără vizibilitate asupra plafonului total configurat pe cheie.

### Follow-up

- Niciun follow-up obligatoriu — punctul e considerat complet închis.

---

## Punctul 2 — Predictor Regression Suite

**Status**: ✅ IMPLEMENTED.

### Problema inițială

Nicio schimbare la `oracle_engine.py`, `feature_engine.py` sau la structura bazei de date nu putea fi verificată automat pentru drift. Testele existente acopereau bucăți interne (`_build_profile`, `_build_h2h`, cascade individuale) — niciunul nu rula punctul de intrare real de producție (`evaluate_match()`) capăt-la-capăt, comparând ieșirea numerică finală cu o bază de referință.

### Dovada că exista

- Grep exhaustiv în `tests/` pentru `.evaluate_match(` → un singur rezultat, într-un docstring — zero test real care rulează funcția capăt-la-capăt.
- Niciun fișier `golden`/`fixture`/snapshot pentru predicții găsit în repo înainte de acest punct.

### Soluția implementată

**Acoperire explicită — ce testează suita, ce NU testează**: suita verifică strict **calea de bază a Oracle Engine** — Poisson (`_poisson_model`), Monte Carlo (`_monte_carlo`), ELO (`_elo_to_multiplier`/`_elo_to_defensive_multiplier`), Formă (`compute_form_score`) și H2H (`_build_h2h`/`compute_h2h_modifier`) — exact combinația care produce `home_xg`/`away_xg`/`ph`/`pd`/`pa`, ieșirile din snapshot. **NU** testează și **NU** acoperă: blending ML (`self.ml=None` în toate cele 20 de scenarii, `ml_blending_enabled` rămâne oricum `False` implicit), Team DNA Flashscore (`FLASHSCORE_TEAM_DNA_AVAILABLE=False`, mock-uit explicit oprit), injurii sau vreme (dezactivate uniform). O schimbare viitoare izolată în blending ML sau în Team DNA NU ar fi detectată de această suită — dacă/când acele căi devin active în producție, ele vor necesita propriile scenarii de regresie, separate.

- `tests/predictor_regression_scenarios.py` — 20 de meciuri golden, input complet mock-uit (formă recentă, ELO, H2H), acoperind deliberat 10 ligi, cele 3 niveluri de calitate a datelor (ADR-035 D4: LIVE/ELO-only/NEUTRAL) și dinamici variate (favorit clar, meciuri strânse, semnale contradictorii ELO-vs-formă, istoric H2H real vs. inexistent). Rulează `FootballOracleEngine.evaluate_match()` REAL, mock-uind exact pe tiparul deja folosit în `test_oracle_engine_db_first_*.py` (patch pe namespace-ul `oracle_engine`) — zero rețea/Supabase reală.
- `tests/predictor_regression_golden.json` — snapshot înghețat (`home_xg`, `away_xg`, `ph`, `pd`, `pa`) pentru cele 20 de scenarii.
- `tests/test_predictor_regression_suite.py` — compară fiecare rulare nouă cu snapshot-ul (toleranță 1e-6) + gărzi de sanitate (probabilități însumate ≈1, xG pozitiv).
- `scripts/generate_predictor_regression_golden.py` — singurul mod acceptat de regenerare, explicit NU automat.
- `docs/00_GOVERNANCE/PREDICTOR_REGRESSION_SUITE.md` — documentează scopul, regula de regenerare („un test picat NU justifică regenerarea"), și ce NU acoperă suita.
- `.github/workflows/predictor_regression_suite.yml` — primul workflow din repo declanșat pe `push`/`pull_request` către `main` (restul sunt `workflow_dispatch`/`schedule`) — obligatoriu la merge, scop deliberat îngust (doar acest fișier de test).

### Commit-uri relevante

- `9192526` — `Add golden predictor regression suite for FootballOracleEngine`.

### Modul de validare

- 61 teste noi (1 test de integritate a dataset-ului + 20 comparații golden + 20 gărzi „sum≈1" + 20 gărzi „xG pozitiv").
- Determinism verificat explicit: două rulări consecutive ale suitei, rezultate bit-identice (seed fix `np.random.default_rng(seed=42)`, deja existent în `_monte_carlo`, confirmat nu doar presupus).
- Zero fișiere scrise pe disc în timpul testelor (`_save_json` mock-uit) — verificat prin `git status` gol pe `predictions/` după rulare.
- Suită completă la momentul commit-ului: 1976 passed / 2 skipped / aceleași 3 eșecuri preexistente și necorelate.

### Riscuri rămase

- Suita acoperă doar calea de bază Poisson/ELO/formă — injurii, vreme, Team DNA Flashscore, blend ML sunt dezactivate uniform în toate cele 20 de scenarii (decizie deliberată, documentată explicit în `PREDICTOR_REGRESSION_SUITE.md`, nu ascunsă). O schimbare care afectează DOAR acele căi secundare nu ar fi prinsă de suita actuală.
- CI-ul (`predictor_regression_suite.yml`) rulează DOAR acest fișier de test, nu `pytest tests/` complet — decizie deliberată (suita completă are 3 eșecuri preexistente necorelate care ar face un gate complet permanent roșu), dar înseamnă că alte regresii (în afara Predictorului) nu sunt încă blocate la merge prin acest mecanism.

### Follow-up

- Dacă se dorește un gate CI pe întreaga suită `pytest tests/`, cele 3 eșecuri preexistente din `test_oracle_api_tsdb_per_league_gate.py` trebuie întâi investigate/reparate — decizie și task separate, neaprobate încă.

---

## Punctul 3 — `flashscore_data_completeness` ca semnal de încredere

**Status**: 🟡 **DEFERRED AFTER ARCHITECTURAL REVIEW.**

**Acest punct NU este „Implemented"** — nu s-a scris și nu s-a implementat niciun cod de integrare. Investigația e completă; decizia e de amânare, nu de finalizare.

### Problema inițială (cerința EPIC-ului)

„Analizează integrarea `flashscore_data_completeness` în Oracle Engine ca semnal de încredere (confidence), fără a modifica încă algoritmul de predicție. Prezintă opțiunile și impactul." — explicit analiză, nu implementare.

### Dovada — investigația completă, live

- Schema (`database/migrations/037_flashscore_data_completeness.sql`): 7 flag-uri booleene per meci (summary/stats/lineups/player_stats/odds/h2h/standings) + `coverage_percent`. Docstring propriu: „persistat DOAR — NU consumat de Oracle Engine/ML azi."
- Singurul consum real azi: `get_match_ids_with_complete_flashscore_stats()`, folosit de `sync/sync_match_statistics.py` pentru rutare Single Owner (ADR-045) — nimic din Oracle Engine îl citește.
- **Descoperire live, decisivă** (query direct pe `Prediction`, 2026-08-03): 328/328 rânduri au `coverage_percent = 100.00%` — **zero variație, niciodată**. `count(DISTINCT coverage_percent) = 1`.
- Cauza structurală (confirmată din cod, nu presupusă): `providers/flashscore/adapter.py::fetch()` scrie `pages[tab_name] = page.content()` pentru toate cele 7 tab-uri într-un singur loop; dacă orice tab eșuează, toată funcția aruncă excepție și meciul nu ajunge NICIODATĂ la `persist()` — nu există cale de cod care produce un `pages` parțial. `compute_data_completeness()` verifică doar `bool(pages.get(tab))`, iar `page.content()` returnează HTML nevid aproape mereu (chiar și pentru o pagină de eroare încărcată cu succes).

### Decizia luată (nu o soluție implementată)

Proprietarul produsului a confirmat explicit concluzia analizei: **„Oracle Engine nu trebuie modificat până când `flashscore_data_completeness` devine un semnal cu varianță reală și valoare informațională demonstrată."** Premisa inițială a EPIC-ului („acest semnal poate fi integrat ca proxy de încredere") **s-a dovedit invalidă** — semnalul, așa cum e definit și generat azi, e o constantă structurală, nu o măsură discriminatorie a calității datelor. Integrarea lui în forma actuală ar adăuga zgomot și complexitate, nu informație.

**Oracle Engine nu a fost modificat — intenționat, ca urmare directă a acestei descoperiri**, nu ca omisiune.

Din cele 5 opțiuni prezentate (A–E, integrare directă / reparare definiție / semnal agregat per echipă / extindere rol Single Owner / câmp UI pur informativ), niciuna nu a fost aprobată pentru implementare — toate rămân condiționate de reproiectarea semnalului la sursă.

### Commit-uri relevante

**Niciunul.** Punctul a produs exclusiv analiză prezentată în conversație — nu s-a creat, modificat sau șters niciun fișier din repo pentru acest punct.

### Modul de validare

- Query live direct pe Supabase (`Prediction`, proiect producție) — 2 interogări (agregat + distribuție per flag), rezultate reproductibile, citate exact mai sus.
- Citire directă de cod (`adapter.py::fetch()`, `persistence.py::compute_data_completeness()`) pentru cauza structurală — nu presupunere.

### Riscuri rămase

- Dacă cineva integrează acest semnal în viitor FĂRĂ să repare mai întâi definiția, riscul concret e exact cel descris: un „confidence" fals, constant, care pare informativ dar nu discriminează nimic — risc documentat explicit aici ca să nu fie redescoperit de la zero.

### Follow-up — EPIC separat necesar

**Identificator**: **`FOLLOW-UP-P3-01` — „Flashscore Data Completeness Signal Redesign"**. Orice referire viitoară la acest follow-up (planificare, alt document de guvernanță, discuție) ar trebui să folosească acest identificator, ca să rămână trasabil direct la Punctul 3 din acest raport.

**Un EPIC nou, dedicat, e necesar înainte de orice reevaluare a integrării**, acoperind minim:
1. Redefinirea `compute_data_completeness()` — verificare de conținut minim relevant per tab, nu doar `bool(html)`.
2. Modificarea `fetch()` (scraper) să permită persistarea unui `pages` parțial la eșecul unui tab individual, nu doar all-or-nothing.
3. Acumularea de date reale cu variație demonstrată (nu presupusă) înainte de a propune din nou o integrare în Oracle Engine.

Acest EPIC separat (`FOLLOW-UP-P3-01`) NU e autorizat de acest raport — necesită aprobare explicită, distinctă, a proprietarului produsului. Punctul 3 rămâne **DEFERRED**, niciodată „închis" — se consideră rezolvat abia când `FOLLOW-UP-P3-01` e finalizat și o nouă evaluare de integrare e făcută pe baza lui.

---

## Punctul 4 — Documentarea acoperirii reale a feature-urilor ML derivate

**Status**: ✅ IMPLEMENTED.

### Problema inițială

`docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md` nu documenta acoperirea reală per feature ML — condiția #3 a gate-ului („test de ablație măsurat") nu putea fi interpretată corect de un cititor viitor fără acest context, riscând o evaluare optimistă a unei activări de blending bazate pe metrici agregate care ascund o acoperire foarte inegală între feature-uri.

### Dovada că exista

- Identificat inițial în `FUNCTIONAL_COMPLETION_MASTER_PLAN.md` (finding P5-01, 🟠 Major).
- Re-verificat live, aceeași zi (`Prediction`, `match_history`, 2026-08-03): total=53.769 rânduri; 10 coloane „core" (ratinguri/formă/ELO/H2H) = 53.486 populate (99,5%); 4 coloane derivate (`corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance`, promovate prin ADR-012/013/021) = 9.215 populate (**17,1%**) — aceleași 9.215 rânduri gatează toate patru simultan.
- `git log`/`grep` pe `ML_ACTIVATION_GATE.md` înainte de acest punct → zero mențiune a celor 4 coloane derivate sau a procentelor de acoperire.

### Soluția implementată

Secțiune nouă în `ML_ACTIVATION_GATE.md`, „Acoperirea reală a feature-urilor derivate (parte a condiției #3)":
- Tabel comparativ core (99,5%) vs. derivate (17,1%), cu sursa SQL exactă.
- Explicație tehnică: valorile lipsă devin `NaN` explicit, gestionat nativ de XGBoost (missing-value split) — niciodată aproximate, comportament deja corect în cod, doar nedocumentat.
- Clarificare explicită, cerută separat de proprietarul produsului: secțiunea e **pur informativă**, NU o a 5-a condiție obligatorie — cele 4 condiții din gate rămân neschimbate.
- Clarificare explicită, cerută separat: măsurătoarea e datată (2026-08-03), NEînghețată — orice reevaluare viitoare trebuie să re-verifice live procentele.

### Commit-uri relevante

- `3335508` — `docs: document real derived-feature coverage in ML_ACTIVATION_GATE.md`.

### Modul de validare

- Verificare live directă (query SQL, re-rulată, aceleași cifre ca în auditul anterior din aceeași zi — confirmă stabilitatea datelor, nu doar o singură măsurătoare izolată).
- Zero cod atins — validare = revizuire de conținut, nu pytest.

### Riscuri rămase

- Niciunul funcțional — document-only. Risc rezidual pur documentar: cifrele vor deveni depășite pe măsură ce se acumulează date noi (bootstrap SuperLiga, sync continuu) — motiv pentru care documentul avertizează explicit să nu fie tratate ca înghețate.

### Follow-up

- Niciun follow-up obligatoriu pentru acest punct. Când (dacă) va exista vreodată un test de ablație nou pentru re-evaluarea condiției #3, trebuie raportat separat pe cele două grupe de acoperire (core vs. derivate) — deja specificat explicit în documentul actualizat.

---

## Punctul 5 — Curățare/îmbunătățire UI (Team DNA, Poisson vs. Monte Carlo)

**Status**: ✅ IMPLEMENTED.

### Problema inițială

Două findings 🟡 Minor / 🔵 Cosmetic din `FUNCTIONAL_COMPLETION_MASTER_PLAN.md`: (1) `flashscore_team_dna.py` calculează 12+ câmpuri per echipă, dar `app.py` extrăgea explicit doar 7 pentru afișare — date reale, colectate, nefolosite vizibil; (2) panoul „Poisson vs. Monte Carlo" afișa două seturi de probabilități fără niciun context, risc de confuzie („două motoare independente" vs. realitatea — Monte Carlo verifică Poisson, nu îl contrazice).

### Dovada că exista

- `grep -n "matches_sampled\|players_sampled\|avg_goals_for\|avg_goals_against" app.py` → zero rezultate înainte de acest punct.
- Din 8 câmpuri de clasament calculate (`rank`/`played`/`won`/`drawn`/`lost`/`goals_for`/`goals_against`/`goal_diff`/`points`), doar `rank` era afișat.
- `app.py` (secțiunea Monte Carlo/Poisson, înainte de acest punct) — zero text explicativ, doar cifre brute.

### Soluția implementată (aprobată explicit, cu ajustări, în `docs/00_GOVERNANCE/UI_IMPROVEMENT_PROPOSAL.md`)

**Zona 1 — Team DNA Flashscore** (Opțiunea B, separare în 3 grupuri logice, plus 2 ajustări cerute explicit):
- Tabelul de statistici extins cu `avg_goals_for`/`avg_goals_against` (rămâne omogen — toate rânduri „X per meci").
- Caption nou, **adaptiv** (ascuns complet dacă nu există nicio dată): eșantion cu indicator vizual al încrederii datelor (`matches_sampled`) — 🟢 25+, 🟡 10–24, 🔴 sub 10 (ajustare cerută explicit, nu era în propunerea inițială).
- Tabel nou, adaptiv, „Clasament complet" (9 câmpuri) — înlocuiește vechiul rând unic „Clasament" (doar rank).
- Adaptivitate: fiecare grup nou dispare complet dacă ambele echipe nu au deloc date pentru el (nu secțiuni goale) — cerință explicită.

**Zona 2 — Poisson vs. Monte Carlo** (Opțiunea A, caption static):
- Text neutru, reformulat explicit la cerere pentru a evita implicația „diferență mare = eroare": *„Poisson calculează probabilitățile direct din xG. Monte Carlo simulează 10.000 de meciuri folosind aceleași valori xG, ca verificare a stabilității rezultatului. Valorile ar trebui să fie apropiate."*

### Commit-uri relevante

- `12fefa8` — `Implement UI improvements for Team DNA Flashscore and Poisson/Monte Carlo panel`.

### Modul de validare

- Sintaxă: `python -m py_compile app.py` — validă.
- Logică de randare/adaptivitate testată izolat (script Python standalone, nu pytest): 4 cazuri — date complete, date complet goale, date parțiale, praguri exacte ale badge-ului (0/None/1/9/10/24/25/100) — toate corecte.
- **Confirmare vizuală reală în browser** (nu doar cod citit): Streamlit rulat izolat, cu date sintetice, în afara aplicației principale (fără dependență de rețea/Supabase live), capturi de ecran Playwright pentru toate cele 3 cazuri (date complete ambele echipe, o echipă fără date Flashscore, ambele fără date) — comportamentul adaptiv și textul caption-ului confirmate exact ca în specificație.
- Suită completă `pytest tests/` (după commit): 1976 passed / 2 skipped, aceleași 3 eșecuri preexistente și necorelate, neschimbate — `app.py` nu e atins de niciun test automat existent.

### Riscuri rămase

- `app.py` nu are acoperire de test automată (nu e un modul importabil testat de `pytest tests/`, e un script Streamlit) — validarea s-a bazat pe verificare vizuală manuală + logică izolată, nu pe o suită de regresie UI persistentă. O schimbare viitoare la acest fișier ar putea reintroduce o regresie vizuală neobservată dacă nu se repetă verificarea manuală.

### Follow-up

- Niciun follow-up obligatoriu — punctul e considerat complet închis.

---

## Sumar final

### Fișiere modificate/create/șterse (agregat, toate cele 4 puncte)

| Fișier | Punct | Tip |
|---|---|---|
| `rate_limit_manager.py` | 1 | Modificat |
| `oracle_api.py` | 1 | Modificat |
| `tests/test_rate_limit_manager.py` | 1 | Modificat (+6 teste) |
| `tests/test_oracle_api_rate_limit_gating.py` | 1 | Nou (+6 teste) |
| `docs/00_GOVERNANCE/ADR-046-provider-rate-limit-protection-matrix.md` | 1 | Nou |
| `sync/poc_rate_limit_headers_check.py` | 1 | Șters (POC temporar) |
| `.github/workflows/poc_rate_limit_headers_check.yml` | 1 | Șters (POC temporar) |
| `tests/predictor_regression_scenarios.py` | 2 | Nou |
| `tests/predictor_regression_golden.json` | 2 | Nou |
| `tests/test_predictor_regression_suite.py` | 2 | Nou (+61 teste) |
| `scripts/generate_predictor_regression_golden.py` | 2 | Nou |
| `docs/00_GOVERNANCE/PREDICTOR_REGRESSION_SUITE.md` | 2 | Nou |
| `.github/workflows/predictor_regression_suite.yml` | 2 | Nou |
| *(niciunul)* | 3 | — |
| `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md` | 4 | Modificat |
| `docs/00_GOVERNANCE/UI_IMPROVEMENT_PROPOSAL.md` | 5 | Nou |
| `app.py` | 5 | Modificat |

**Notă**: `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md` (auditul de bază al întregului EPIC) și acest raport nu sunt incluse în tabel — sunt documentele-cadru, nu livrabile ale unui punct individual.

### Teste adăugate

- Punctul 1: **12** teste noi.
- Punctul 2: **61** teste noi.
- Punctul 3: 0 (analiză, fără cod).
- Punctul 4: 0 (document, fără cod).
- Punctul 5: 0 teste automate noi (`app.py` nu e acoperit de `pytest tests/`) — validat prin logică izolată + confirmare vizuală reală în browser (Playwright), nu prin suită de regresie persistentă.
- **Total adăugat în acest EPIC: 73 teste automate** (P1+P2).

### Numărul total de teste după modificări

**1976 passed / 2 skipped / 3 failed** (pre-existente, necorelate — `tests/test_oracle_api_tsdb_per_league_gate.py`, confirmate independent, neschimbate față de baseline-ul dinaintea acestui EPIC). Baseline dinainte de EPIC: 1903 passed / 2 skipped / aceleași 3 eșecuri. Delta: +73 passed, exact suma testelor adăugate — zero regresie introdusă.

### ADR-uri afectate

- **ADR-046** (nou) — `provider-rate-limit-protection-matrix.md` (Punctul 1).
- Niciun ADR existent modificat — toate schimbările au fost aditive sau documentate separat, fără să atingă un document Frozen sau un ADR deja acceptat.

### Follow-up EPIC-uri

1. **`FOLLOW-UP-P3-01` — Reproiectarea `flashscore_data_completeness` în Data Trust Layer** (rezultat direct al Punctului 3, obligatoriu înainte de orice integrare viitoare în Oracle Engine ca semnal de încredere) — neaprobat, neînceput.
2. **(Opțional, neaprobat, fără identificator alocat)** Investigare/reparare a celor 3 eșecuri preexistente din `test_oracle_api_tsdb_per_league_gate.py`, dacă se dorește extinderea gate-ului CI de la Punctul 2 la întreaga suită `pytest tests/`.

---

## Lessons Learned

- **Verificarea live a răsturnat o premisă a EPIC-ului, nu doar a confirmat-o.** Punctul 3 pornea de la ipoteza implicită că `flashscore_data_completeness` e un semnal util, doar neconectat. Un singur query live (`count(DISTINCT coverage_percent) = 1`) a arătat că semnalul e o constantă structurală — filozofia „Verificat, nu presupus" (CLAUDE.md) și-a dovedit valoarea direct: fără acel query, riscul real era implementarea unei integrări care ar fi părut funcțională, dar fără conținut informațional.
- **Un POC temporar cu dovadă live a găsit exact bug-ul pe care revizuirea de cod, singură, nu l-ar fi confirmat cu aceeași certitudine** (Punctul 1) — header-ele reale trimise de The Odds API/WeatherAPI nu puteau fi cunoscute din citirea codului sau din documentație presupusă, doar dintr-un apel HTTP real, prin exact punctul de intrare de producție.
- **Urmărirea strictă a baseline-ului de teste (număr exact, nu aproximat) a făcut posibilă o afirmație fermă de „zero regresie"** la fiecare din cele 3 commit-uri de cod — fără acest obicei, „am rulat testele și au trecut" ar fi fost o afirmație mai slabă, ne-cuantificată.
- **Separarea strictă „analiză" vs. „implementare" (Punctul 3) a prevenit o decizie prematură** — dacă implementarea ar fi fost făcută în aceeași sesiune cu analiza, presiunea de a „termina EPIC-ul" ar fi putut duce la integrarea semnalului constant doar ca să existe un rezultat de arătat.
- **Documentarea explicită a limitelor unei soluții (ce NU acoperă) s-a dovedit la fel de valoroasă ca documentarea a ce acoperă** — atât `PREDICTOR_REGRESSION_SUITE.md` cât și `ML_ACTIVATION_GATE.md` au necesitat clarificări suplimentare, cerute explicit de proprietarul produsului, tocmai pentru că absența unei limite explicite lasă loc de interpretare optimistă ulterioară.

---

## Navigare rapidă — commit-uri principale per punct

| Punct | Commit |
|---|---|
| P1 | `4e4eec1` |
| P2 | `9192526` |
| P3 | — (Deferred, niciun commit de cod) |
| P4 | `3335508` |
| P5 | `12fefa8` |

---

## Ce urmează

EPIC „Functional Completion" (P1–P5) e închis, conform statusului din Rezumatul executiv: **4 puncte `IMPLEMENTED`** (P1, P2, P4, P5), **1 punct `DEFERRED`** (P3, urmărit prin `FOLLOW-UP-P3-01`, neaprobat, neînceput). Niciun nou EPIC nu pornește fără aprobarea explicită, separată, a proprietarului produsului.
