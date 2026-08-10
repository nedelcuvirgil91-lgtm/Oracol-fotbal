# ADR-039 — Universal Synchronization Architecture & Supabase First

**Status**: FROZEN — arhitectură aprobată oficial de proprietarul produsului, 2026-07-22. Devine baza oficială pentru implementarea Universal Synchronization Architecture. Tratat de acum ca contract normativ — nicio modificare arhitecturală ulterioară decât printr-un ADR nou, dedicat, sau o problemă demonstrată în implementare (nu o preferință), per aceeași disciplină aplicată ADR-030…038.

**Autor**: Claude, audit + design, la cererea explicită a proprietarului produsului. Companion: `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` (evidența completă, per provider).

**Data**: 2026-07-22.

---

## Context

ADR-038 a rezolvat sincronizarea pentru un singur provider (API-Football), stabilind explicit o excepție rămasă deschisă: Oracle Engine continua să apeleze providerul direct (prin Request Manager, dar tot direct), iar politica generală a proiectului (ADR-035) permitea explicit „apel direct la provider, excepție, nu regulă" atunci când Supabase nu are date suficiente.

Discuția ulterioară (proprietar produs, sesiunea curentă) a stabilit o decizie fundamentală: **excepția se elimină, pentru toți providerii, nu doar pentru API-Football.** Regula devine universală:

> Orice provider extern există EXCLUSIV pentru sincronizarea și îmbogățirea bazei de date Supabase. Oracle Engine, Prediction Engine, ML și Feature Engineering nu mai au voie să cunoască existența niciunui provider extern — citesc exclusiv din Supabase.

Auditul companion (§1) a demonstrat că 7 provideri reali (API-Football, Odds API, Weather API, football-data.org, FreeLF, ESPN, TheSportsDB) plus unul deja conform (Kaggle) sunt afectați, cu roluri și riscuri diferite — nu toți sunt „fallback-uri" (FreeLF și Odds API sunt surse PRIMARE de descoperire a meciurilor).

## Decizie

### North Star (extins, nu contrazis)

Regula ADR-035 („Niciun provider extern nu poate avea prioritate asupra unei informații deja sincronizate și validate în baza canonică Supabase") devine literă de lege, fără excepție de tip „date insuficiente → apel live". Dacă Supabase nu are încă o informație, răspunsul e „necunoscut" (Regula #8, CLAUDE.md), niciodată un apel live de completare.

### Principii arhitecturale

1. **Un singur strat poate vorbi cu providerii externi: Universal Sync Layer.** Niciun alt modul (Oracle Engine, ML, Feature Engineering, Prediction Engine) nu importă, nu instanțiază, nu apelează direct sau indirect vreun adaptor de provider.
2. **Sync Layer e generic, nu per-provider.** Scheduler (Sync Orchestrator), Request Manager, Rate Limit Manager sunt deja construite generic (R4.1) — rămân neschimbate, reutilizate de orice adaptor nou.
3. **Fiecare provider capătă un adaptor formal** (`SyncAdapter`: fetch/normalize/validate/persist/coverage_check opțional) — extensie directă a tiparului deja dovedit (`FootballDataProvider`, `football_providers.py`), nu un concept nou.
4. **Niciun cod deja funcțional nu se rescrie fără migrare testată per pas.** Odds persistence (Frozen, ADR-005/006) și `match_history` Database-First (ADR-035 D1-D3) rămân neatinse — ele deja satisfac regula, nu sunt obiectul acestui ADR.
5. **Migrare provider-cu-provider, niciodată big-bang.** Secvențiere pe risc (audit §6, **corectată post-R-Sync-2** — audit §6b — **și din nou post-R-Sync-3** — audit §6c, pentru dovada/justificarea fiecărei corecții): API-Football injuries/coaches (**finalizat, R-Sync-2**) → football-data.org formă/standings, **exclus explicit fixtures** (**finalizat, R-Sync-3**) → **eloratings.net, ELO național** (R-Sync-4 — **corectat, audit §6c: NU e TheSportsDB, provider distinct — eroare de clasificare demonstrată și corectată prin cod, nu presupusă**) → Weather (**finalizat, R-Sync-5**) → FreeLF formă/standings + Odds API fallback H2H/formă, exclus explicit orice rol de descoperire (R-Sync-6) → **Universal Match Discovery Layer** (R-Sync-7, TOȚI providerii de fixtures într-un singur pas: FreeLF, Odds API, football-data.org, ESPN, TheSportsDB, **și API-Football** — niciun provider de fixtures nu rămâne tratat separat sau privilegiat) → **TheSportsDB team stats** (R-Sync-8 — **mutat aici, audit §6c: cuplat structural la `team_id` `tsdb_`-prefixat, produs DOAR de Match Discovery; migrare curată abia posibilă după R-Sync-7, fără introducerea unei rezoluții de identitate noi și neaprobate**) → eliminarea finală a `self.api` din Oracle Engine (R-Sync-9).
6. **Supabase e Football Data Warehouse-ul proiectului** — denumire formală a ceea ce principiile 1-2 și fluxul din audit §3 deja stabilesc: singurul depozit canonic pe care Oracle Engine/ML/Feature Engineering/Prediction Engine îl citesc, alimentat exclusiv prin fluxul `Provider → Sync Adapter → Normalize → Validate → Persist → Supabase`. Nu e un concept nou — e numele conceptului deja definit.
7. **Identitatea canonică a entităților (Team/Match/Competition) e deja rezolvată, prin nume normalizat, nu prin ID numeric de provider.** Sync Adapters (principiul 3) nu inventează identificatori noi — folosesc exclusiv mecanismele deja existente: `ADR-024`/`ADR-025` (Match, Frozen — cheie `(echipe normalizate, dată)`, fără ligă în cheie, crosswalk-ul de ID-uri explicit respins acolo), `mappings.TEAM_ALIASES`/`normalize_team_name()` (Team), `mappings.LEAGUE_PROVIDERS` (Competition, cheie = nume canonic, `provider_ids` per provider dedesubt — exact tiparul deja folosit de Coverage Cache, ADR-038). Niciun adaptor nou nu are voie să introducă o a doua sursă de identitate paralelă.

### Scope-ul acestui ADR

**În scope**: definirea Universal Sync Layer, interfața `SyncAdapter`, modelul de persistare Supabase per tip nou de date (`team_health_snapshot`, `scheduled_fixtures`, `weather_forecast_cache`), politica de sincronizare per provider, strategia de migrare secvențială.

**În afara scope-ului, explicit**:
- Nu redeschide ADR-034 (Provider Capability Selection) — Sync Layer consumă providerii, nu decide între ei; Selection Engine rămâne subiectul lui ADR-034, neatins.
- Nu redeschide ADR-005/006 (Odds Persistence, Frozen) — cotele pre-meci rămân pe calea existentă.
- Nu implementează încă niciun adaptor — acest ADR e contract, nu cod.
- Nu elimină încă `self.api`/`self.apifootball` din `oracle_engine.py` — asta e ultimul pas al roadmap-ului (audit §8), condiționat de finalizarea migrării tuturor providerilor.

## Consecințe

- **Pozitive**: Oracle Engine devine, odată finalizată migrarea, complet independent de disponibilitatea oricărui provider extern — North Star-ul „oprești un provider o săptămână, Oracle continuă din Supabase" devine adevărat universal, nu doar pentru API-Football.
- **Neutre**: infrastructura deja construită în R4.1 (Scheduler, Request Manager, Rate Limit Manager) rămâne complet reutilizabilă — zero regresie de arhitectură deja funcțională.
- **Risc acceptat, documentat**: descoperirea meciurilor (FreeLF/Odds/football-data/ESPN) e o migrare structural mai mare decât oricare fallback individual — afectează calea prin care se află *ce meciuri există*, nu doar *ce date are un meci deja cunoscut*. Tratată explicit ca etapă proprie, ultima, nu subestimată prin includere tacită în pașii anteriori.
- **Cost real, numit**: cadența de sincronizare diferă masiv per provider (Kaggle: o dată; injuries: ore; descoperire meciuri: posibil ore; vreme: de câteva ori/zi) — nu există o cadență universală unică, fiecare adaptor își declară propria politică.
- **Debt temporar, numit explicit (R-Sync-4)**: `ELO_RATINGS_FALLBACK` (`mappings.py`) e fuzionat cu scrape-ul live eloratings.net în `national_team_elo_snapshot`, ca soluție de tranziție — evită o regresie imediată (echipe prezente doar în fallback ar deveni „necunoscute" altfel), NU o decizie permanentă. Se elimină (sau se reduce strict la echipele fără acoperire live confirmată) odată ce sincronizarea live demonstrează acoperire completă — nu se păstrează din inerție.
- **Principiu confirmat, R-Sync-5**: Weather synchronization persists only validated locations — unknown locations are intentionally skipped rather than guessed.

## Referințe

- `docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md` — evidența completă.
- `docs/00_GOVERNANCE/ADR-038-api-football-synchronization-architecture-v2.md` — primul pas, API-Football, neatins, extins acum.
- `docs/00_GOVERNANCE/ADR-035-database-first-prediction-engine.md` — principiul de bază pe care acest ADR îl extinde, eliminând excepția de fallback live.
- `docs/00_GOVERNANCE/ADR-034-provider-capability-selection-architecture.md` — strat de abstractizare peste care Sync Layer se construiește, neatins.
- `docs/00_GOVERNANCE/ADR-036-canonical-feature-ownership.md` — precedentul de ownership unic de scriere, reaplicat la fiecare tabelă nouă.
- `docs/00_GOVERNANCE/ADR-024-canonical-match-identity-data-contract.md` + `docs/00_GOVERNANCE/ADR-025-match-identity-implementation-strategy.md` (Frozen) — identitatea canonică a unui meci, deja decisă; sursa pentru principiul 7.
- `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` — identitatea canonică a unei echipe, `TEAM_ALIASES`/`normalize_team_name()`; documentează și un gol de wiring cunoscut (nu toți writerii aplică normalizarea la scriere), în afara scope-ului acestui ADR.

---

## Addendum — corectare mecanism R-Sync-4 (2026-08-10)

**Nu e o schimbare de decizie** — implementarea `EloRatingsAdapter.fetch()` (`elo_ratings_adapter.py`) nu a funcționat niciodată real, de la crearea sincronizării. Confirmat live (audit infrastructură, 2026-08-10, POC izolat în doi pași): eloratings.net randază tabelul de ratinguri 100% client-side prin SlickGrid (`slick.grid.js`) — răspunsul HTTP brut (ce citea `requests`+`BeautifulSoup`) are ~1.8KB, zero `<table>`, zero date. `national_team_elo_snapshot` a persistat de la început, în fiecare rulare săptămânală, EXACT `ELO_RATINGS_FALLBACK` (`mappings.py`) — 47 de valori statice, nemodificate niciodată — fără nicio eroare vizibilă în loguri (fallback-ul mascase tăcut eșecul).

**Corectare**: `fetch()` randază acum pagina real (Playwright, Chromium headless — deja dependință activă a proiectului, folosită pentru Flashscore) și parsează HTML-ul RANDAT, nu răspunsul HTTP brut — vezi `elo_ratings_adapter.parse_elo_ratings_html()`/`_fetch_rendered_html()`. Confirmat live, a doua etapă a POC-ului: 244 echipe naționale reale, cu ratinguri curente (ex. Spain 2259, Argentina 2173 — diferite de aproximările statice vechi).

**Actualizare directă a §Consecințe, „Debt temporar (R-Sync-4)"**: acel paragraf presupunea că fuziunea cu `ELO_RATINGS_FALLBACK` avea să rămână necesară „până la acoperire live completă". În practică, sincronizarea reală (244 echipe, acoperire mult mai largă decât cele 47 din fallback) elimină nevoia fuziunii altfel decât prin dispariția ei naturală: `EloRatingsAdapter.fetch()` nu mai atinge deloc `oracle_api.get_national_elo_ratings_raw()`/`ELO_RATINGS_FALLBACK` — acel cod de fuziune a rămas neatins, dar a devenit orfan (niciun apelant de producție). Curățarea lui explicită (eliminarea codului mort din `oracle_api.py`) rămâne o decizie separată, nu bundle-uită tacit aici — semnalată proprietarului produsului ca descoperire, nu executată automat.

**FREEZE CONFIRMAT.** Nicio linie de cod scrisă sub acest ADR. Arhitectura de mai sus (Universal Sync Layer, `SyncAdapter`, modelul de persistare, politica de migrare provider-cu-provider, identitatea canonică prin nume normalizat) devine contractul normativ pentru orice sincronizare externă a proiectului. Implementarea urmează roadmap-ul din audit companion (§8), incremental, pas cu pas, fiecare cu aprobare explicită separată — fără extindere de scope, fără redesign suplimentar decât la o problemă demonstrată în implementare.

---

## Addendum 2 — eliminare cod mort ELO orfan + contaminare de date (2026-08-10)

**Context**: la verificarea live a POC-ului Playwright (addendum de mai sus), a fost semnalat separat, ca discovery, un defect de calitate a datelor preexistent în `ELO_RATINGS_FALLBACK` (`mappings.py`): dict-ul, gândit exclusiv pentru echipe naționale, conținea și 16 nume de club (Manchester City, Real Madrid, Bayern Munich, Liverpool, FC Barcelona, Paris Saint-Germain, Arsenal, Chelsea, Manchester United, Juventus, Inter Milan, AC Milan, Atletico Madrid, Borussia Dortmund, Napoli, Tottenham Hotspur) amestecate în același tabel. Semnalat, dar neatins la momentul respectiv, conform Discovery Rule.

**Decizie explicită a proprietarului produsului**: eliminare completă a mecanismului mort, nu doar curățarea datelor. Verificat înainte de execuție (grep + AST): `oracle_api._fetch_elo_ratings()`, `get_elo_rating()`, `get_national_elo_ratings_raw()` nu mai aveau niciun apelant de producție rămas — `EloRatingsAdapter.fetch()` (post-corectare Playwright) randază azi direct, fără să mai treacă prin `oracle_api`, iar servirea live citește exclusiv `database.queries.get_national_team_elo()`.

**Ce s-a șters**: `ELO_RATINGS_FALLBACK` (`mappings.py`, dict-ul contaminat inclus), `_fetch_elo_ratings()`/`get_elo_rating()`/`get_national_elo_ratings_raw()` (`oracle_api.py`), constanta `ELO_URL` și intrarea aferentă din `_PROVIDER_HOST_MAP` (`oracle_api.py` — deveniseră orfane odată cu funcțiile care le foloseau), importul `BeautifulSoup`/`BS4_AVAILABLE` din `oracle_api.py` (folosit STRICT de codul șters — `bs4` rămâne dependință reală a proiectului, folosită în continuare de `providers/flashscore/`, `udal_extraction.py`, `elo_ratings_adapter.py` — nicio schimbare la `requirements.txt`). Teste actualizate: `tests/test_mappings.py` (import + assert eliminate), `tests/test_oracle_engine_single_profile_construction_point.py` (docstring-ul gărzii `test_get_elo_rating_never_called_from_oracle_engine` actualizat — garda rămâne, ca insurance ieftină contra reintroducerii, dar nu mai descrie o funcție încă existentă în `oracle_api.py`). Suită completă rulată după eliminare: 2288 trecute, aceleași 3 eșecuri preexistente, nelegate (`tests/test_oracle_api_tsdb_per_league_gate.py`, cauză cunoscută: dată hardcodată).

**Rezultat**: contaminarea de nume de club dispare prin eliminarea completă a codului care o expunea, nu prin editarea datelor dintr-un dict păstrat — nu mai există niciun dict `ELO_RATINGS_FALLBACK` de curățat.
