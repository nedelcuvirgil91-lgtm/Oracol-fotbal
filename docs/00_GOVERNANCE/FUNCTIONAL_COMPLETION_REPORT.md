# Functional Completion Report — Engine Completion (EPIC 1–4)

**Status**: RAPORT DE ÎNCHIDERE, oficial.

**Perioadă**: 2026-08-03 (sesiune unică).

**Autor**: Claude, la cererea proprietarului produsului.

**Scop**: raport formal de închidere pentru cele 4 puncte ale EPIC-ului „Functional Completion" (audit de bază: `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md`) — deschis explicit după închiderea Master Repair Plan-ului, cu ordine strictă de execuție impusă de proprietarul produsului: „Lucrăm strict în această ordine, fără să sărim peste pași."

**Ce NU acoperă acest raport**: Punctul 5 (curățare/îmbunătățire UI) — neînceput, condiționat explicit de aprobarea acestui document.

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

**Un EPIC nou, dedicat, e necesar înainte de orice reevaluare a integrării**, acoperind minim:
1. Redefinirea `compute_data_completeness()` — verificare de conținut minim relevant per tab, nu doar `bool(html)`.
2. Modificarea `fetch()` (scraper) să permită persistarea unui `pages` parțial la eșecul unui tab individual, nu doar all-or-nothing.
3. Acumularea de date reale cu variație demonstrată (nu presupusă) înainte de a propune din nou o integrare în Oracle Engine.

Acest EPIC separat NU e autorizat de acest raport — necesită aprobare explicită, distinctă, a proprietarului produsului.

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

**Notă**: `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md` (auditul de bază al întregului EPIC) și acest raport nu sunt incluse în tabel — sunt documentele-cadru, nu livrabile ale unui punct individual.

### Teste adăugate

- Punctul 1: **12** teste noi.
- Punctul 2: **61** teste noi.
- Punctul 3: 0 (analiză, fără cod).
- Punctul 4: 0 (document, fără cod).
- **Total adăugat în acest EPIC: 73 teste.**

### Numărul total de teste după modificări

**1976 passed / 2 skipped / 3 failed** (pre-existente, necorelate — `tests/test_oracle_api_tsdb_per_league_gate.py`, confirmate independent, neschimbate față de baseline-ul dinaintea acestui EPIC). Baseline dinainte de EPIC: 1903 passed / 2 skipped / aceleași 3 eșecuri. Delta: +73 passed, exact suma testelor adăugate — zero regresie introdusă.

### ADR-uri afectate

- **ADR-046** (nou) — `provider-rate-limit-protection-matrix.md` (Punctul 1).
- Niciun ADR existent modificat — toate schimbările au fost aditive sau documentate separat, fără să atingă un document Frozen sau un ADR deja acceptat.

### Follow-up EPIC-uri

1. **EPIC — Reproiectarea `flashscore_data_completeness` în Data Trust Layer** (Punctul 3, obligatoriu înainte de orice integrare viitoare în Oracle Engine ca semnal de încredere) — neaprobat, neînceput.
2. **(Opțional, neaprobat)** Investigare/reparare a celor 3 eșecuri preexistente din `test_oracle_api_tsdb_per_league_gate.py`, dacă se dorește extinderea gate-ului CI de la Punctul 2 la întreaga suită `pytest tests/`.

---

## Ce urmează

**Punctul 5** (curățare/îmbunătățire propunere UI — Team DNA, explicații Poisson vs. Monte Carlo, fără modificarea logicii Predictorului) rămâne neînceput, condiționat explicit de aprobarea acestui raport de către proprietarul produsului.
