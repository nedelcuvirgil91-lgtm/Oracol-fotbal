# Football Oracle Data Warehouse — Arhitectură (Etapa B, 2026-07-27)

**Status**: **Living Architecture Document.** Acest document reprezintă referința oficială pentru proiectarea Data Warehouse-ului Football Oracle și va fi actualizat pe măsură ce sunt integrate noi surse de date, noi domenii și noi politici de ownership — nu se creează documente paralele pentru extinderi viitoare ale aceluiași domeniu. La data acestei versiuni: document de arhitectură — **zero migrare, zero SQL, zero cod, zero implementare**. Răspunde la o singură întrebare: *ce date trebuie să existe în Supabase ca Predictorul și motorul ML să funcționeze la potențial maxim, cu cât mai puține apeluri live?*

**Bază**: `DATA_WAREHOUSE_CURRENT_STATE_2026-07-27.md`, cele 4 audituri referențiate acolo, ADR-039, ADR-040, schema Supabase curentă (39 tabele, verificată direct, nu presupusă), cercetarea de provideri deja efectuată (Etapa A). **Nu se propune nicio sursă externă nouă** — doar provideri deja integrați (FreeLF, Odds API, API-Football, football-data.org, ESPN, TheSportsDB, WeatherAPI.com, Kaggle/football_data_co_uk). Domeniile fără sursă curată azi (xA, PPDA, referee) sunt marcate „necunoscut/lipsă", nu inventate.

**Principiu obligatoriu, aplicat la fiecare câmp**: owner, fallback, politică de merge, motiv de persistare, consumator — niciun câmp nu intră în acest document fără toate cele cinci.

**Regulă de includere, valabilă și pentru orice extindere viitoare a acestui document** (decizie explicită proprietar produs): înainte ca un tabel sau un câmp nou să intre în Data Warehouse, răspunsul la *„ce feature ML sau ce logică din Predictor consumă această informație?"* trebuie să existe și să fie concret. Dacă nu există încă un consumator clar, câmpul se amână — nu se persistă „ar putea fi util cândva". Coloana „Impact Predictor"/„Clasificare ML" din fiecare tabel de mai jos e exact acest test, aplicat.

---

## 0. Tiparul de guvernanță — standard OBLIGATORIU pentru tot proiectul, nu doar un precedent reutilizat

**Decizie de arhitect, aplicată explicit aici**: **FixtureMergePolicy** (`scheduled_fixtures`, migrarea 023) devine singurul model de ownership acceptat în tot Football Oracle — SourcePriority per câmp guvernat + `field_provenance` (JSONB, cine deține azi valoarea) + coloane deținute de provider (COALESCE-only, niciodată suprascrise de altcineva). **Niciun domeniu nou din acest document nu are voie să introducă un mecanism de merge diferit** — nu „câte un tipar per domeniu care pare mai simplu", un singur tipar, peste tot. Orice domeniu de mai jos cu >1 sursă potențială reutilizează ACEST tipar, nu inventează unul nou:

- **Câmp cu un singur owner posibil, niciodată** (ex. `stats_source` deja există în `match_history` ca slot dedicat exact pentru asta) → `stats_source` marchează owner-ul curent al rândului, nu JSONB nou.
- **Câmp guvernat, mai mulți provideri concurenți** (ex. formă echipă: football-data.org ȘI FreeLF) → SourcePriority explicit, ca la `league`/`venue_city`/`kickoff_utc`.
- **Identificatori proprii de provider** → coloane prefixate per-provider, COALESCE-only, niciodată șterse de alt provider (tiparul `freelf_event_id`/`odds_api_event_id`/etc.).
- **Fără first-wins nicăieri** — orice tabelă nouă propusă mai jos care agregă mai mulți provideri e proiectată field-level, nu row-level, de la început (lecția R-Sync-7).

---

## 1. Match Statistics

**Scop**: statistici numerice per meci (nu per echipă agregat — vezi §8 pentru asta). **Tabel Supabase**: continuă `match_history` (coloanele deja există pentru majoritatea câmpurilor) — **nu se propune tabelă nouă** pentru acest domeniu, spre deosebire de celelalte de mai jos, ca să nu se dubleze o schemă deja construită și parțial populată.

**Politică de cache/sync, la nivel de domeniu**: date POST-meci, imuabile odată scrise (un meci jucat nu-și schimbă scorul din Aprilie în Iunie) — deci **fără TTL, fără expirare, scriere o singură dată per meci** (spre deosebire de weather/odds, care sunt prospective și expiră). Sincronizare: **zilnic** (după ce meciurile din ziua precedentă s-au încheiat, imediat după `sync_yesterday_results` în ordinea din `run_daily.py`) pentru meciurile recente; **backfill istoric** separat, o singură rulare per extindere de acoperire (nu recurent).

| Câmp | Descriere | Provider principal | Fallback | Owner (scriitor) | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|---|
| `home/away_shots`, `home/away_shots_on_target` | Șuturi totale/pe poartă | football_data_co_uk mirror (istoric, 5 ligi, până 2025-05) | FreeLF `get_match_statistics()` (live, neconectat) | `stats_source` marchează care | ✅ coloane există, 6,5% populate | Direct — înlocuiește o valoare azi sintetică în profilul echipei | Feature critic ML (candidat, ablație neefectuată încă) | **P0** |
| `home/away_corners`, `home/away_fouls`, `home/away_yellow_cards`, `home/away_red_cards` | Cornere/faulturi/cartonașe | football_data_co_uk mirror (istoric) | — (FreeLF nu le oferă) | `stats_source` | ✅ coloane există, 6,5% populate | **Deja feature ML în producție** (`corner_dominance`/`card_diff`/`foul_diff`, ADR-012/013) | Feature critic ML (confirmat) | **P0** — risc de calitate silențios azi |
| `home/away_ht_goals` | Scor la pauză | football_data_co_uk mirror | — | `stats_source` | ✅ coloană există, 6,5% | Doar istoric (echipei), NICIODATĂ al meciului curent — scurgere temporală dacă greșit | Feature analitic (neexplorat) | P2 |
| `home/away_possession` | Posesie % | FreeLF `get_match_statistics()` (live, neconectat) | — | FreeLF (nou) | ✅ coloană există, 0% populată | Înlocuiește default hardcodat 50.0 din `oracle_engine.py` | Feature critic ML (candidat) | **P0** |
| `home/away_xg_actual` | xG real, post-meci | FreeLF `get_match_statistics()` (live, neconectat) | — | FreeLF (nou) | ✅ coloană există, 0% populată | Înlocuiește `home_xg_pred` (deja eliminat din ML, 100% gol istoric) | Feature critic ML (candidat) | **P0** |
| `home/away_big_chance` | Ocazii mari | FreeLF `get_match_statistics()` | — | FreeLF (nou) | ❌ nicio coloană azi | Nou, neexplorat | Feature analitic | P2 |
| xA (assist așteptat) | — | **Nicio sursă existentă** (Understat/StatsBomb — risc ToS, cf. `KNOWLEDGE_ENGINE_SOURCES_AUDIT`) | — | — | ❌ | — | Necunoscut | P3, blocat de sursă |
| PPDA/pressing | — | **Nicio sursă existentă** | — | — | ❌ | — | Necunoscut | P3, blocat de sursă |

**Gol de design explicit, nerezolvat aici, semnalat**: mirror-ul istoric se oprește la 2025-05; FreeLF (live) ar deveni owner de acum înainte — rămâne o **fereastră neacoperită** (2025-05 → azi) dacă FreeLF nu poate interoga retroactiv acea perioadă. **Necesită verificare live** înainte de Etapa C — nu presupun capacitatea FreeLF aici.

---

## 2. Team Form

**Scop**: formă recentă agregată per echipă (nu per meci). **Tabele Supabase, deja existente**: `footballdata_team_form_snapshot` (R-Sync-3), `freelf_team_form_snapshot` (R-Sync-6) — **două tabele separate, un owner per tabelă, fără merge între ele azi**.

**Politică cache/sync**: formă = fereastră glisantă, se schimbă după fiecare meci al echipei — TTL scurt (recomandare: re-sincronizare zilnică, invalidare la fiecare rulare `run_daily.py`, consistent cu cadența deja aleasă la R-Sync-3/6).

| Câmp | Provider principal | Fallback | Owner | Tabel | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|---|
| `played/wins/draws/losses/goals_for/against/points/position` | FreeLF (`freelf_team_form_snapshot`) | football-data.org (`footballdata_team_form_snapshot`) | **Gol**: două tabele, fără SourcePriority documentată | ambele, existente | ✅ cod gata, **0 rânduri** (neorchestrat) | Direct — `home/away_form_score` deja ML feature | Feature critic ML (deja confirmat) | **P0** — orchestrare, nu date noi |
| `form` (text, ultimele N rezultate) | football-data.org | FreeLF | Idem gol de merge | idem | ✅ coloană există, **cunoscut bug**: `get_freelf_standings()` nu copiază `form` — rămâne mereu gol (task R-Sync-6a, neînceput) | Analitic/explainability | Feature informațional | P1 — necesită verificare live a numelui real de câmp înainte de fix |

**Decizie de design cerută aici, nu doar semnalată** (implementarea rămâne pentru Etapa C, dar decizia de principiu se ia acum, nu se amână):

- **Owner propus**: FreeLF (`freelf_team_form_snapshot`).
- **Fallback propus**: football-data.org (`footballdata_team_form_snapshot`).
- **Motiv**: FreeLF e deja sursă PRIMARĂ de discovery (ADR-039, pasul 2 din `get_matches_for_week()`, rang 1 la `venue_city`/`league` în FixtureMergePolicy) — consecvent să rămână owner și aici, nu doar la identitatea meciului. football-data.org rămâne fallback exact cum e azi la `venue_city`/`league` (rang 2, gap confirmat de `normalize_league_name()` lipsă, §11).
- Cele două tabele trebuie să capete o SourcePriority explicită (tiparul §0) înainte ca oricare feature „formă" din ele să fie considerat de încredere pentru ML. Fără asta, orice consum viitor riscă exact genul de first-wins implicit deja corectat la `scheduled_fixtures`.

---

## 3. Lineups

**Scop**: aliniere de start, formație, status confirmat. **Tabel Supabase propus (nou, doar design)**: `lineup_snapshot` — `home_team_canonical`, `away_team_canonical`, `kickoff_date`, `team_side` (home/away), `formation` (text), `confirmed` (boolean), `source_provider`, `synced_at`.

**Politică cache/sync**: lineup-urile se confirmă de obicei ~1h înainte de meci — **live, cu TTL scurt** (nu zilnic, nu static) — cadență diferită de toate celelalte domenii din acest document, aproape de timp real doar în fereastra pre-meci.

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| `formation`, `confirmed` | FreeLF `get_lineup()` (deja apelat pentru accidentări, câmpurile parsate și aruncate) | — | FreeLF | 🟡 parsat, aruncat, nicio coloană Supabase | Marginal (per audit 12 iulie) | Feature analitic/informațional | P2 |
| Jucători titulari (listă) | FreeLF `get_lineup()` | — | FreeLF | ❌ nicio persistare | Prerequizit pentru Player Statistics (§10) dacă se dorește vreodată | Necunoscut | P3 |

---

## 4. Injuries

**Scop**: deja funcțional, singurul domeniu din acest document cu 2 surse ACTIVE simultan, fără politică de merge documentată. **Tabel Supabase existent**: `team_health_snapshot` (R-Sync-2, JSONB `injuries`).

**Politică cache/sync**: deja implementată, zilnic, consistentă cu restul R-Sync-2.

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| `injuries` (JSONB) | API-Football (R-Sync-2) | FreeLF `unavailable[]` (folosit direct în `injury_manager.py`, NU prin `team_health_snapshot`) | **Gol real**: 2 căi paralele, nu 2 surse cu fallback — API-Football scrie `team_health_snapshot`, FreeLF alimentează `injury_manager` direct, live, ocolind tabela | ✅ ambele funcționale, dar necoordonate | Deja folosit activ, dublu | Feature critic Predictor (deja) | **P1** — unifică cele 2 căi, nu doar documentează |

**Owner propus/fallback propus/motiv** (decizie de principiu, implementare la Etapa C):

- **Owner propus**: `team_health_snapshot` (API-Football, R-Sync-2) — devine tabela canonică unică pentru accidentări, nu doar una din două căi.
- **Fallback propus**: FreeLF `unavailable[]` — **NU mai citit direct, live, de `injury_manager.py`** — trebuie să scrie în `team_health_snapshot`, ca al doilea contribuitor field-level (tiparul §0), nu ca o cale paralelă care ocolește DB-ul.
- **Motiv**: azi FreeLF ocolește complet Supabase pentru accidentări — exact anti-tiparul „Database First" pe care ADR-035/ADR-039 l-au eliminat peste tot altundeva în proiect. Consolidarea într-un singur tabel canonic e mai importantă aici decât alegerea exactă a priorității dintre cele două surse.

---

## 5. Referees

**Scop**: complet lipsă. **Tabel Supabase propus**: niciunul — **fără sursă confirmată azi, nu se proiectează o tabelă pentru date inexistente** (Regula #8: necunoscut rămâne necunoscut, nu se pregătește schemă pentru o ipoteză).

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| Nume arbitru | **Nicio sursă confirmată** (o singură mențiune TODO în tot codul; football-data.org nu-l are; mirror-ul de 48 coloane nu-l are; varianta de 133 coloane a football-data.co.uk l-ar avea, dar acces blocat în mediul curent, neconfirmat) | — | — | ❌ | Necunoscut | Necunoscut | P3, blocat de sursă |

---

## 6. Weather

**Scop**: deja proiectat corect (R-Sync-5), doar neorchestrat. **Tabel Supabase existent**: `weather_forecast_cache`.

**Politică cache/sync, deja documentată la R-Sync-5, reconfirmată aici**: cheie `(city, kickoff_date)`, validare strictă (oraș necunoscut → skip, niciodată ghicit), TTL derivat din `synced_at`+`kickoff_date`, fără coloană TTL separată.

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| `temp_c/condition/wind_kph/precip_mm/humidity/xg_penalty` | WeatherAPI.com (R-Sync-5) | — | WeatherAPI.com | ✅ cod gata, **0 rânduri** (neorchestrat) | Direct — `weather_penalty` folosit în blend | Feature critic Predictor (deja) | **P0** — orchestrare, nu date noi |
| Vreme istorică (retroactivă) | WeatherAPI.com `/history.json` (nefolosit) | — | — | ❌ | Ar completa 99,94% din istoric azi gol | Feature analitic (netestat) | P2 |

---

## 7. Betting Markets

**Scop**: 1X2 deja Frozen și complet; restul pieței fetch-uit dar nepersistat (decizie de scop ADR-006, nu gol tehnic). **Tabel Supabase existent**: `odds_history` (1X2). **Tabel propus (nou, doar design), dacă se decide extinderea**: `odds_market_extended` — `fixture_id`, `market` (`over_under_25`/`btts`/`asian_handicap`), `selection`, `price`, `bookmaker`, `fetched_at`.

**Cerință de design obligatorie, cerută explicit**: schema trebuie să permită adăugarea unei piețe noi **fără nicio migrare**. `market` e `TEXT`, nu un `ENUM`/`CHECK` fix pe o listă închisă de piețe — o piață nouă (ex. „over_under_35" mâine) e o valoare NOUĂ în coloana `market`, un rând nou, zero `ALTER TABLE`. Singura constrângere structurală rămâne forma `(fixture_id, market, selection, bookmaker)` — generică pe orice piață, nu o coloană nouă per piață, exact opusul tiparului `odds_history` (unde `opening_home`/`opening_draw`/`opening_away` sunt coloane fixe, acceptabil DOAR pentru 1X2 pentru că acea piață are exact 3 selecții invariante — nu se generalizează la piețe cu număr variabil de selecții, ex. Handicap Asiatic).

**Politică cache/sync**: identică cu 1X2 deja Frozen — opening/closing, imuabil odată închis meciul.

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| 1X2 (open/close) | Odds API | — | Odds API | ✅ Frozen, complet | Direct — de-vig, value betting | Feature critic Predictor (deja) | — (deja rezolvat) |
| Over/Under 2.5 | Odds API (fetch-uit, nepersistat) | — | Odds API (dacă activat) | 🟡 în memorie, nepersistat | Activează `_special_value_bets()`, azi structural mort | Feature informațional (UI), nu ML | **P1** — decizie de produs |
| BTTS | Odds API (fetch-uit, nepersistat) | — | idem | 🟡 idem | idem | idem | **P1** |
| Handicap asiatic | **Nefetch-uit deloc** azi | — | — | ❌ | Doar dacă scope-ul de predicție se extinde dincolo de 1X2 | Necunoscut | P3 |
| Market movement (>2 puncte) | Odds API (necesită polling repetat, nu doar open/close) | — | — | ❌ doar 2 puncte azi | Semnal posibil, netestat | Feature analitic (ipoteză) | P2 |

---

## 8. Team Strength

**Scop**: deja cel mai matur domeniu din tot proiectul. **Tabele existente**: ELO în `match_history` (club, pre/post) + `national_team_elo_snapshot` (R-Sync-4) + `elo_history` (write-only, 39.575 rânduri, niciodată citit).

| Câmp | Provider principal | Fallback | Owner | Există azi? | Impact Predictor | Clasificare ML | Prioritate |
|---|---|---|---|---|---|---|---|
| ELO club pre/post meci | Import istoric + ELOTracker live | — | Unic, ADR-023 | ✅ ~100% | Direct | Feature critic ML (deja) | — |
| ELO național | eloratings.net (R-Sync-4) | `ELO_RATINGS_FALLBACK` (**temporar**, ADR-039) | eloratings.net | ✅ | Direct | Feature critic ML (deja) | — |
| Tendință ELO (trend, nu valoare absolută) | `elo_history` (deja în DB, 39.575 rânduri) | — | — | 🟡 date există, niciodată citite | Semnal complet neexploatat — deja recomandat Sprint 3 în auditul din 12 iulie | Feature analitic (candidat puternic — date deja gratuite) | **P1** — zero cost de colectare |
| `home/away_offensive_rating`, `defensive_rating` | `feature_engine.py` (calculat intern) | — | Intern | ✅ 100% | Direct | Feature critic ML (deja) | — |

---

## 9. Historical Performance (H2H)

**Deja rezolvat** — DB-first (ADR-035 D3), ~100% populat, folosit direct în ML (`h2h_modifier`/`h2h_meetings`). Singurul gol rămas: FreeLF H2H (event-based) cuplat structural la discovery, blocat până la R-Sync-8 — deja documentat, nu se repetă aici.

| Câmp | Owner | Există azi? | Prioritate |
|---|---|---|---|
| `h2h_modifier`, `h2h_meetings` | `match_history` (recalculat din `actual_result`) | ✅ ~100% | — |

---

## 10. Player Statistics

**Scop**: complet lipsă, posibil în afara scope-ului de produs (Football Oracle prezice rezultate de ECHIPĂ, nu performanță individuală). **Niciun tabel propus** — nu se proiectează schemă pentru un domeniu fără decizie de scop de produs confirmată.

| Câmp | Sursă potențială | Există azi? | Impact Predictor | Prioritate |
|---|---|---|---|---|
| Orice statistică per jucător | API-Football `/players/statistics` (nefolosit), FreeLF lineup (nume, fără statistici agregate) | ❌ | Necunoscut — decizie de scop de produs, nu tehnică | **P3, condiționat de o decizie explicită separată** dacă produsul se extinde vreodată la nivel de jucător |

---

## 11. Competition Metadata

**Scop**: identitate canonică ligă/competiție — deja parțial rezolvat (`mappings.LEAGUE_PROVIDERS`), dar cu un gol confirmat.

| Câmp | Provider principal | Owner | Există azi? | Impact Predictor | Prioritate |
|---|---|---|---|---|---|
| Nume canonic ligă | `mappings.LEAGUE_PROVIDERS` (sursă unică, ADR-001) | Static, în cod | ✅ | Direct — folosit peste tot | — |
| `normalize_league_name()` aplicat consecvent | — | **Gol confirmat**: `_fetch_matches_fd()` nu-l aplică niciodată (găsit la R-Sync-7a, motivul SourcePriority mai mică pentru football-data.org) | 🟡 | Cauzează exact tipul de discrepanță pe care Migration Gate (ADR-040) e proiectat să-l detecteze | **P1** — bug confirmat, nu doar gol de date |

---

## 12. Strategia de completare a golurilor istorice

Pentru fiecare domeniu cu split temporal istoric/live: până unde acoperă sursa istorică, de unde începe sursa live, dacă se suprapun, ce gol rămâne.

| Domeniu | Sursă istorică | Acoperă până la | Sursă live/curentă | Începe de la | Suprapunere? | Gol identificat? |
|---|---|---|---|---|---|---|
| Match Statistics (șuturi/cornere/cartonașe/faulturi/HT) | football_data_co_uk mirror (backfill manual) | 2025-05-25 (5 ligi majore) | FreeLF `get_match_statistics()` (neconectat) | Necunoscut — depinde de fereastra retroactivă reală a FreeLF | **Necunoscut, necesită verificare live** | **DA, confirmat**: ~14 luni negestionate (2025-05 → azi), până la conectare |
| xG/posesie/big chances | Niciodată colectat istoric | N/A (0%) | FreeLF `get_match_statistics()` (neconectat) | De la activare | N/A — nu exista înainte | Nu e „suprapunere" — istoricul pre-activare rămâne permanent gol, doar meciurile viitoare vor avea aceste date |
| ELO național | `ELO_RATINGS_FALLBACK` (static, `mappings.py`) | Permanent, ca fallback | eloratings.net (R-Sync-4, live) | De la R-Sync-4 | **DA** — merge explicit documentat (live câștigă) | Nu e gol — tranziție deja planificată, marcată TEMPORAR de eliminat (ADR-039) |
| Odds istorice 1X2 | Niciodată colectat înainte de activarea Odds Infrastructure | N/A | Odds API (live, ADR-005, Frozen) | 2026-07-13 | N/A | Gol permanent pentru meciuri anterioare — football-data.co.uk ar putea completa parțial (singurul beneficiu „demonstrat", nu doar probabil, în `FOOTBALL_DATA_CO_UK_AUDIT`), neexecutat |
| Weather istoric | Aproape inexistent (0,06%, 34/53.443) | — | `weather_forecast_cache` (R-Sync-5, strict prospectiv, neorchestrat) | De la orchestrare (Sprint 1) | **Nu** — infrastructura nouă nu completează retroactiv | Gol permanent istoric; doar `/history.json` (nefolosit, P2) ar putea completa |
| Team Form | N/A — nu are semantică „istoric vs. live", e stare curentă recalculată continuu | — | FreeLF/football-data.org (neorchestrate) | — | — | N/A |

---

## 13. Known Structural Problems (backlog tehnic consolidat)

Toate problemele structurale găsite în acest document și în `DATA_WAREHOUSE_CURRENT_STATE_2026-07-27.md`, într-un singur loc — nu împrăștiate pe secțiuni:

1. **Sync Layer construit, neorchestrat** — `sync/run_daily.py` nu apelează R-Sync-3→7a (cel mai mare gol valoric din tot proiectul, §1 din `DATA_WAREHOUSE_CURRENT_STATE`).
2. **Match Statistics — gol temporal 2025-05 → azi**, fereastră retroactivă FreeLF necunoscută (§1, §12).
3. **Team Form — două surse fără SourcePriority documentată** (§2).
4. **Injuries — două căi paralele, una ocolește Supabase complet** (`injury_manager.py` citește FreeLF direct, live — anti-tipar Database First) (§4).
5. **`normalize_league_name()` lipsă la `_fetch_matches_fd()`** — bug confirmat, cauza rangului mai mic al football-data.org în FixtureMergePolicy (§11).
6. **`form` mereu gol la FreeLF standings** — bug cunoscut, task R-Sync-6a deschis, neînceput (§2).
7. **`elo_history` write-only** — 39.575 rânduri, niciodată citite, niciun consumator (§8).
8. **8 tabele fără RLS** (`sync_status`, `elo_ratings`, `api_cache`, `league_provider_coverage`, `api_provider_status`, `provider_metrics`, `shadow_predictions`, `experiment_registry`) — semnalat 13 iulie, absent din `CLAUDE.md`.
9. **`get_lineup()` parsează `formation`/`confirmed`, le aruncă** — zero persistare (§3).
10. **Fără strat de „raw staging"** pentru niciun domeniu — vezi §15, Data Lineage.

---

## 14. Data Freshness

Pentru fiecare domeniu: cât de veche poate deveni informația, când expiră, cine o actualizează, iar expirarea produce doar WARNING sau blochează servirea.

| Domeniu | Cât de veche poate deveni | Când expiră | Cine actualizează | Expirare → WARNING sau BLOCARE? |
|---|---|---|---|---|
| Match Statistics | Permanentă — imuabilă odată scrisă (fapt istoric) | Nu expiră | Backfill/live sync (owner per §1) | N/A |
| Team Form | Max. 1 zi (recalculat zilnic) | La următoarea rulare `run_daily.py` | R-Sync-3/6 (neorchestrate azi) | **WARNING** — formă veche degradează calitatea, nu blochează servirea |
| Injuries | Max. 1 zi | La următoarea rulare | R-Sync-2 (deja activ) | **WARNING** |
| Weather | Fereastră scurtă, cheie `(city, kickoff_date)` | La kickoff | R-Sync-5 (neorchestrat) | **WARNING** — `validate()` deja respinge date necunoscute, niciodată aproximate |
| Odds 1X2 | Opening imuabil; closing valabil până la kickoff | La kickoff | Odds API (activ, Frozen) | Opening: N/A. Closing: ar trebui **BLOCARE** dacă nu sosește înainte de kickoff (regulă deja în ADR-006, „no-retry") |
| ELO club/național | Actualizat per meci jucat | Niciodată — istoric cumulativ | ELOTracker / eloratings.net | N/A |
| `scheduled_fixtures` | Poate deveni stale dacă un meci se reprogramează | Niciodată explicit (merge continuu îl menține curent) | Sync Layer discovery, continuu | **WARNING** — exact ce Migration Gate (ADR-040) e proiectat să detecteze (meciuri „fantomă") |
| Lineup | Foarte scurtă — ore înainte de meci | La kickoff | FreeLF (neconectat pentru persistare) | **BLOCARE** dacă folosit ca feature de ultim moment fără status `confirmed` |

---

## 15. Data Lineage

Șablon cerut: `API → Raw staging → Canonical table → Feature table → Predictor → ML`.

**Observație de design, onestă, nu ascunsă**: **„Raw staging" nu există azi în NICIUN domeniu** — pipeline-ul normalizează direct la ingest (`Provider → Sync Adapter → Normalize → Persist`, ADR-039 §3), fără un jurnal intermediar al payload-ului brut. `api_cache` e cache TTL (dedup/performanță), **NU** un audit trail — dacă un provider schimbă formatul răspunsului, nu există un „raw" de reprocesat retroactiv. Marcat ca observație de design pentru acest document, nu ca recomandare de a adăuga acum un strat nou — decizie separată, doar dacă se dorește vreodată reprocesare istorică fără re-fetch.

| Domeniu | API (sursă) | Raw staging | Canonical table (Supabase) | Feature/derivare | Predictor | ML |
|---|---|---|---|---|---|---|
| Match Statistics | football_data_co_uk / FreeLF | ❌ nu există | `match_history` | `corner_dominance`/`card_diff`/`foul_diff` (calculate din `*_avg_recent`) | `oracle_engine._build_profile()` | `ml_predictor.FEATURE_COLUMNS` |
| Team Form | FreeLF / football-data.org | ❌ | `freelf_team_form_snapshot` / `footballdata_team_form_snapshot` | `home/away_form_score` (`feature_engine.py`) | `oracle_engine` | `ml_predictor` |
| Weather | WeatherAPI.com | ❌ | `weather_forecast_cache` | `weather_penalty` | `oracle_engine.evaluate_match()` | Candidat, ablație neefectuată pe versiunea reală |
| `scheduled_fixtures` | 6 provideri | ❌ | `scheduled_fixtures` | — (identitate, nu feature) | `oracle_engine` (viitor, R-Sync-7b/c) | — |
| Odds 1X2 | Odds API | ❌ | `odds_history` | De-vig (`oracle_engine`) | Value betting | Nu e feature ML, e output de produs |
| ELO | eloratings.net / ELOTracker | ❌ | `match_history` / `national_team_elo_snapshot` | `home/away_elo` | `oracle_engine` | `ml_predictor` |

---

## 16. Matrice finală de prioritizare (P0–P3 + Business Impact)

| # | Item | Domeniu | Prioritate | Business Impact |
|---|---|---|---|---|
| 1 | Orchestrare `run_daily.py` → cele 6 scripturi R-Sync-3→7a | Transversal | **P0** | **Foarte mare** — deblochează tot restul, zero cost de fetch nou |
| 2 | Conectare `get_match_statistics()` → xG/posesie/șuturi reale | Match Statistics | **P0** | **Foarte mare** — înlocuiește o valoare azi sintetică/falsă |
| 3 | Stabilizare/extindere backfill Match Statistics (cornere/cartonașe/faulturi) | Match Statistics | **P0** | **Foarte mare** — deja feature ML în producție, risc de calitate azi |
| 4 | SourcePriority explicită Team Form | Team Form | P1 | Mediu |
| 5 | Unificare cale Injuries (Supabase-only) | Injuries | P1 | Mediu |
| 6 | Tendință ELO din `elo_history` | Team Strength | P1 | Mediu — cost de colectare zero, date deja gratuite |
| 7 | Fix `normalize_league_name()` lipsă la fd.org | Competition Metadata | P1 | Mediu — bug de calitate date, nu doar gol |
| 8 | O/U + BTTS persistate | Betting Markets | P1 | Redus — UI, nu ML |
| 9 | R-Sync-6a — verificare live `form` FreeLF | Team Form | P1 | Redus |
| 10 | Scor la pauză (HT) ca feature istoric | Match Statistics | P2 | Redus-mediu |
| 11 | `formation`/`confirmed` lineup persistat | Lineups | P2 | Redus |
| 12 | Vreme istorică retroactivă | Weather | P2 | Redus |
| 13 | Market movement granular | Betting Markets | P2 | Redus |
| 14 | Big chances | Match Statistics | P2 | Redus |
| 15 | Referee | Referees | P3 | Redus — blocat de lipsă de sursă |
| 16 | Handicap asiatic | Betting Markets | P3 | Redus |
| 17 | xA/PPDA | Match Statistics | P3 | **Mediu potențial, disponibilitate zero** — blocat de lipsă de sursă curată ToS |
| 18 | Player Statistics | Player Statistics | P3 | Necunoscut — condiționat de decizie de scop de produs |

---

## 17. Compatibilitate cu principiile arhitecturale (verificare explicită)

- **Supabase = Single Source of Truth**: toate tabelele propuse/existente sunt citite exclusiv prin Sync Layer → Supabase → Oracle Engine, niciun consum direct de provider propus aici.
- **Ownership clar**: fiecare câmp de mai sus are un owner numit; acolo unde nu are (Team Form §2, Injuries §4), e marcat explicit ca gol de rezolvat, nu ignorat.
- **Merge determinist, fără first-wins**: orice domeniu cu >1 sursă reutilizează SourcePriority + `field_provenance`/`stats_source`, tiparul deja validat la `scheduled_fixtures` (§0) — niciun tabel nou propus aici introduce un mecanism de merge alternativ.
- **Fără câmpuri orfane**: fiecare câmp din acest document are un consumator numit (Predictor/ML/explainability) sau e marcat explicit „necunoscut" — niciun câmp „ar putea fi util cândva" fără destinatar concret.

---

*Acest document nu propune și nu autorizează nicio implementare, migrare sau schimbare de schemă. Etapa C (populare efectivă) necesită aprobare explicită separată, per domeniu, conform disciplinei proiectului.*
