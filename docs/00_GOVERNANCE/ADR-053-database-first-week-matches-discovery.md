# ADR-053 — Database-First pentru `get_matches_for_week()` (lista de meciuri, aplicație live)

**Status**: **ACCEPTAT** (2026-08-06) — aprobat explicit de proprietarul produsului ("aprob propunerea ta. incepe adr-ul si implementarea"), pornind de la propunerea Claude, în urma investigării unui raport real de pornire lentă a aplicației (log Streamlit Cloud, 4+ minute, aceeași cascadă live completă repetată de 7 ori într-o singură sesiune de ~4 minute).

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-06.

**Companion**: `oracle_api.py::get_matches_for_week()` (cod existent, neșters — devine fallback), `ADR-023`/`ADR-035` (precedent Database-First pentru ELO/H2H/team stats), `ADR-043` (Flashscore odds fallback, neatins de acest ADR), `ADR-044`/`ADR-045` (Foundation Data Layer + Single Owner — sursa reală a datelor pe care se bazează acest ADR).

---

## Context

`get_matches_for_week()` (`oracle_api.py`) e cascada live originală de descoperire meciuri (Odds API → Free Live Football → football-data.org → ESPN → TheSportsDB → API-Football, în această ordine, cu fallback-uri per ligă) — apelată din `app.py` (ecranele „Meciuri" și „Value Bets") la fiecare sesiune de utilizator fără date deja în `st.session_state`.

Deși există deja 2 niveluri de cache (session_state per sesiune de browser + `CacheManager`, TTL 1 oră pentru categoria „matches"), un raport real de pornire lentă (log Streamlit Cloud, 21:47:27→21:51:43, atașat de proprietarul produsului) a arătat cascada completă rulând de **7 ori** în aceeași fereastră de ~4 minute — fiecare rulare completă durând zeci de secunde, dominată de bucla FreeLF (secvențială, deliberat neparalelizată — are stare reală de rate-limiting; FreeLF e documentat cronic epuizat, `CLAUDE.md`, „Goluri cunoscute").

În aceeași zi (această sesiune), `match_history` a devenit o sursă de discovery solidă pentru toate cele 14 ligi urmărite de Flashscore — alimentată automat de `night_sync.yml` (zilnic), `live_sync.yml` (3x/zi, meciuri terminate) și noul `flashscore_weekly_fixtures.yml` (2x/săptămână, meciuri viitoare — vezi acel workflow pentru istoricul cadenței). Verificat live: pe 12 din 14 ligi, Flashscore găsește egal sau (majoritar) net mai mult decât toți providerii API la un loc pentru aceeași fereastră de o săptămână.

Proprietarul produsului a conectat explicit cele două fire: „parcă așa rămăsese ca singura sursă de adevăr să fie Supabase" — consistent cu Database-First deja aplicat la ELO de club (D2), H2H (D3) și team stats (R-Sync-8).

## Decizie

1. `get_matches_for_week()` interoghează **întâi** `match_history` (funcție nouă, `database.queries.get_matches_for_week_from_history()`), pentru fereastra cerută (`azi` → `azi + days_ahead`) și ligile cerute — zero apel live.
2. Pentru fiecare ligă cu **cel puțin un rând** găsit în fereastră → servită direct din DB, fără niciun apel către provideri live.
3. Pentru o ligă cu **zero rânduri** în fereastră (gaură reală sau, mai rar, săptămână genuin liniștită — cele două nu se pot distinge doar din informația locală, deci ambele primesc același tratament, sigur) → cascada live **existentă, neschimbată**, dar apelată **doar pentru acea ligă**, nu pentru toate cele 14. Cod extras într-o metodă privată nouă, `_fetch_live_week_matches()`, identică logic cu ce exista înainte — niciun provider, ordine sau condiție de fallback schimbată.
4. **Cotele rămân complet neatinse** — `_attach_odds()`/`_attach_flashscore_odds_fallback()` rulează, ca și până acum, o singură dată, la finalul funcției, peste rezultatul combinat (DB + live fallback), indiferent de sursa fiecărui meci. Niciun cod nou de cote, nicio schimbare de cadență la sincronizarea cotelor.
5. Meciurile din DB primesc aceeași formă de dicționar (`fixture_id`, `home_team`, `away_team`, `kickoff_utc`, `kickoff_date`, `league`, `season`, `status`, câmpuri de cotă goale) ca și cele din cascada live — niciun cod din `app.py`/`oracle_engine.py`/`value_dashboard.py` nu are nevoie de nicio schimbare.
6. `home_team_id`/`away_team_id` rămân goale (`""`) pentru meciurile din DB — verificat direct în cod (`oracle_engine._build_profile()`): sursa PRIMARĂ de profil echipă e deja Database-First, pe **nume** de echipă, nu pe `team_id`; `team_id` e folosit doar de nivelurile de fallback (FreeLF/Odds API/etc.), care oricum nu mai rulează când Level DB reușește.
7. Cascada live veche rămâne cod activ, testat, neșters — devine fallback per-ligă, nu calea implicită.

## Consecințe

**Pozitive**:
- Cazul comun (o ligă cu acoperire deja bună în `match_history` — majoritatea, după migrarea Flashscore de azi) devine aproape instant, fără niciun apel live.
- Reduce presiunea reală pe FreeLF (deja cronic epuizat) și pe restul providerilor, indiferent câte sesiuni de utilizator se deschid.
- Consistent cu restul arhitecturii (Database-First deja aplicat la ELO/H2H/team stats) — nu introduce un pattern nou.
- Reversibil fără migrare de schemă — cascada live rămâne intactă, disponibilă oricând ca fallback.

**Negative / riscuri acceptate**:
- Depinde direct de prospețimea `match_history` — motivul explicit pentru care `flashscore_weekly_fixtures.yml` a trecut la 2x/săptămână (luni + joi) în aceeași decizie, ca fereastra maximă de învechire să scadă de la 7 la ~3-4 zile.
- O ligă cu meciuri reale dar temporar 0 rânduri în DB (întârziere de sincronizare, nu gaură permanentă) declanșează un fallback live — cost real, dar corect (nu pierde meciuri), auto-corectabil la următoarea rulare de discovery.
- `status`-ul meciurilor din DB e derivat simplu (`"finished"` dacă `actual_result` există, altfel `"scheduled"`) — mai puțin granular decât `SCHEDULED`/`TIMED`/etc. din football-data.org; acceptat, niciun consumator existent nu diferențiază la acest nivel de detaliu.

## Alternative respinse

- **Swap complet, fără fallback live** — respinsă: risc real de gaură nedetectată pentru o ligă nou-adăugată sau cu întârziere de sincronizare, încalcă direct „Regula 2 — zero regresii funcționale" (aceeași disciplină aplicată azi la evaluarea migrării Flashscore).
- **Doar creșterea TTL-ului de cache existent** — respinsă: nu rezolvă cauza reală (prima încărcare a unei sesiuni noi — reconectare mobilă, sau apăsarea butonului „Reîncarcă meciuri" — tot declanșează cascada completă), doar amână problema, nu o elimină.

## Addendum — fallback de ultimă instanță pe `scheduled_fixtures`, 2026-08-10

**Incident live confirmat**: raport al proprietarului produsului ("au disparut iar o mare parte din meciurile descoperite pt toata saptamana... cate 1 rstacit per competitie"). Investigație directă (interogări live `api_cache`): ESPN a întors **zero rezultate pe toate cele 98 de interogări** ale cascadei live din acea fereastră (toate intrările de cache cu `array_len: 0`), în timp ce tabela separată `scheduled_fixtures` (populată de R-Sync-7a, discovery pe 6 provideri) avea deja **76 de meciuri** pentru aceeași fereastră — un ultim query de echivalență (`equivalence_evaluations`, gate `R-Sync-7b`) a confirmat `live_count=14, scheduled_count=76, matched_count=14, missing_live_count=62`: `scheduled_fixtures` conținea strict tot ce găsise cascada live, plus 62 de meciuri reale pierdute complet.

Cauza rădăcină: `get_matches_for_week()` (Decizia #3 de mai sus) consultă `match_history` apoi cascada live per-ligă, dar **nu consultă niciodată** `scheduled_fixtures` — deși acel tabel există și e populat independent, pentru exact acest scop (descoperire), din 2026-07 (R-Sync-7a).

**De ce nu s-a folosit direct gate-ul de echivalență R-Sync-7b ca să promoveze `scheduled_fixtures` la sursă generală**: starea `equivalence_state` din evaluările recente e predominant `"red"`/`"insufficient_data"`, niciodată `"green"` — nu există încă certificare formală că `scheduled_fixtures` poate înlocui cascada live ca sursă echivalentă (gate-ul blocant AST, `tests/test_migration_gate_blocks_r_sync_7c.py`, impune exact această disciplină — R-Sync-7c, swap complet, rămâne neîncepută deliberat).

**Decizie adăugată** (fallback ÎNGUST, nu o extindere a Deciziei #3): pentru o ligă rămasă cu **zero meciuri** după ATÂT Level DB (`match_history`) CÂT ȘI cascada live (`_fetch_live_week_matches()`) — nu pentru nicio altă ligă — se consultă `scheduled_fixtures` (funcție nouă, `database.queries.get_matches_for_week_from_scheduled_fixtures()`) ca ultimă instanță. Nu pretinde echivalență generală (nu înlocuiește nicio sursă care a funcționat deja) — logica e strict "un meci real găsit e mai bun decât zero", nu o migrare de sursă. Implementare: `oracle_api.py::get_matches_for_week()`, blocul `still_gap` de după `_add(live_matches)`.

Testat: `tests/test_database_queries_matches_for_week_from_scheduled_fixtures.py` (7 teste, funcția de query izolată) + `tests/test_oracle_api_scheduled_fixtures_last_resort_fallback.py` (6 teste, wiring-ul din `get_matches_for_week()` — confirmă explicit că fallback-ul NU se declanșează când Level DB sau cascada live acoperă deja o ligă, și că se declanșează STRICT pentru ligile rămase în `still_gap`). Confirmat separat (`tests/test_migration_gate_blocks_r_sync_7c.py`, 2 teste) că adăugarea nu atinge/eludează gate-ul R-Sync-7c — toate cele 6 apeluri de discovery live rămân prezente în sursă, neschimbate.
