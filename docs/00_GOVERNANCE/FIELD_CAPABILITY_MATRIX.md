# FIELD CAPABILITY MATRIX — Sprint 3.0

Livrabil de audit, cerut explicit înainte de orice modificare de cod (Sprint 3, Regula 2). Nu implementează nimic — verifică, per câmp, cine poate furniza acel câmp azi, prin citire directă de cod (adaptoare, capability registry, `oracle_engine.py`, `ml_predictor.py`), nu prin presupunere.

Metodologie: pentru fiecare câmp — provider principal, fallback 1/2/3 (dacă există REAL, nu doar înregistrat), endpoint exact, sursă istorică sau live, existență în Supabase, folosire în `FEATURE_COLUMNS` (ML), folosire în Oracle Engine (predicție live), stare de valorificare azi.

**Convenție**: „✅ REAL" = adaptor complet (fetch→normalize→validate→persist) există și a fost rulat. „⚠️ ÎNREGISTRAT, NEIMPLEMENTAT" = apare în `provider_capabilities.py` sau în lanțul static din `sync_provider_manager.py`, dar nu există niciun adaptor funcțional — apelarea lui ar eșua sau ar necesita cod nou. „❌ INEXISTENT" = nu există nicio cale de cod, azi.

---

## 0. Corecție critică la premisa Sprint 3 (Regula 3, verificat concret)

Specificația Sprint 3 presupune lanțul `Match Statistics: SFI → FreeLF → API-Football → TheSportsDB`. Verificat direct în `provider_capabilities.py` (Capability Registry, sursa de adevăr declarativă) — **acest lanț e parțial fals**:

| Provider | `DataType.STATISTICS`/`XG`/`LINEUPS` înregistrat? | Adaptor real existent? |
|---|---|---|
| `soccerfootballinfo` | DA (STATISTICS, XG, LINEUPS, MANAGERS, STANDINGS) | ✅ DA — `soccerfootballinfo_match_statistics_adapter.py`, endpoint `matches/view/full` |
| `freelivefootball` | DA (STATISTICS, LINEUPS, H2H) | ⚠️ PARȚIAL — `match_statistics_adapter.py` scrie DOAR possession+xG (scope limitat explicit, Sprint 1) |
| `apifootball` | **NU** — capabilitățile declarate sunt DOAR `FIXTURES, INJURIES, MANAGERS` | ❌ Niciun adaptor de match statistics — nu poate fi folosit pentru xG/shots/corners/etc |
| `sportapi` | DA (STATISTICS, XG, LINEUPS, H2H, MANAGERS, ODDS, STANDINGS, PLAYER_RATINGS) — pe hârtie, cel mai complet provider din tot registry-ul | ⚠️ **ÎNREGISTRAT, NEIMPLEMENTAT** — există doar `sync/poc_sportapi_check.py`/`poc_sportapi_deep_check.py` (discovery, NU integrare, docstring explicit: „Discovery, NU integrare"). Cotă plan Free: **50 cereri/LUNĂ** — inutilizabil la scară reală chiar dacă s-ar implementa un adaptor. |
| `thesportsdb` | **NU** — capabilitatea declarată e DOAR `FIXTURES` | ❌ Niciun cod nu folosește TheSportsDB pentru statistici de meci, azi sau vreodată |

**Concluzie verificată**: lanțul real de fallback pentru match statistics, folosind DOAR ce există azi ca adaptor funcțional, e **SFI (complet) → FreeLF (doar possession+xG) → NIMIC** (al treilea nivel din `_STATIC_FALLBACK_CHAINS["match_statistics"]` de azi, `sportapi`, e neimplementat; TheSportsDB nu a fost niciodată o opțiune reală pentru acest domeniu). Orice extindere a lanțului static la 4 nivele necesită FIE implementarea unui adaptor SportAPI nou (blocat practic de cota de 50/lună) FIE renunțarea la ideea de al 4-lea nivel pentru acest domeniu — decizie care așteaptă aprobarea ta explicită, nu e luată aici.

---

## 1. Matricea completă, câmp cu câmp

### xG (actual, post-meci)
- **Coloană Supabase**: `match_history.home_xg_actual` / `away_xg_actual` — EXISTĂ (migrarea `add_match_statistics_extended_fields`, Sprint 1)
- **Provider principal**: `soccerfootballinfo` — endpoint `matches/view/full`, câmp `teamA.xG.live` (fallback intern pe `.kickoff` dacă live lipsește) — ✅ REAL, cod confirmat (`_team_stats()`)
- **Fallback 1**: `freelivefootball` — `MatchStatisticsAdapter`, `get_match_statistics(event_id)` → `home_xg`/`away_xg` — ✅ REAL, dar scope limitat (doar 4 coloane: possession+xG)
- **Fallback 2**: niciunul funcțional — `apifootball` nu are XG înregistrat; `sportapi` are XG înregistrat dar neimplementat (vezi §0)
- **Fallback 3**: niciunul
- **Motivul alegerii**: SFI e singurul provider cu adaptor complet care extrage xG live (mai precis decât estimarea pre-meci)
- **Sursă**: LIVE (post-meci) — Kaggle/football-data.co.uk NU au xG (confirmat, `sync/bootstrap_league_learning.py` docstring: „absente 100% din dataset-ul Kaggle")
- **Folosit în `FEATURE_COLUMNS` (ML)**: **NU** — `home_xg_pred`/`away_xg_pred` au fost ELIMINATE explicit din `FEATURE_COLUMNS` (permutation importance = 0.0000 pe 53.409 meciuri, 100% goale istoric). Notă: acelea sunt coloanele de PREDICȚIE (`_pred`), nu `_actual` — `home_xg_actual`/`away_xg_actual` nu au fost NICIODATĂ testate ca feature ML, pentru că nu au existat date populate până acum.
- **Folosit în Oracle Engine (live)**: NU — zero referințe la `xg_actual` în `oracle_engine.py`
- **Stare**: 0/53.409 meciuri populate azi (confirmat live, Supabase). Complet nevalorificat.

### Possession
- **Coloană**: `home_possession`/`away_possession` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`matches/view/full`, `team.possession`) — ✅ REAL
- **Fallback 1**: `freelivefootball` (`MatchStatisticsAdapter`) — ✅ REAL, scope limitat (possession+xG)
- **Fallback 2/3**: niciunul funcțional (aceeași limitare ca xG)
- **Sursă**: LIVE — football-data.co.uk mirror NU are possession (confirmat, `_MATCH_STATS_FIELDS` din `sync/sources/football_data_co_uk.py` nu include possession)
- **Folosit în `FEATURE_COLUMNS`**: NU
- **Folosit în Oracle Engine**: **DA, dar NU din date reale** — `oracle_engine.py:868/953/980` folosește `possession: 50.0` ca valoare NEUTRĂ hardcodată de fallback în cascada de rating ofensiv/defensiv (`_build_profile()`), niciodată citită dintr-o coloană reală `home_possession`/`away_possession`. Acest lucru rămâne corect arhitectural (Oracle nu are voie să citească live), dar înseamnă că ODATĂ populată coloana în Supabase, Oracle tot nu o va folosi fără o schimbare explicită de cod (schimbare de Oracle Engine — interzisă azi de Sprint 3, vezi §2).
- **Stare**: 0/53.409 populate. Nevalorificat.

### Shots (total)
- **Coloană**: `home_shots`/`away_shots` — EXISTĂ
- **Principal (LIVE)**: `soccerfootballinfo` (`matches/view/full`, `shoots.t`) — ✅ REAL
- **Principal (ISTORIC)**: `football-data.co.uk` mirror (`sync/backfill_match_stats.py`, grup `shots`) — ✅ REAL, deja rulat pentru 5 ligi (Premier League, La Liga, Serie A, Bundesliga, Ligue 1), fereastră 2023-2025
- **Fallback 1 (live)**: niciunul funcțional (FreeLF nu scrie shots — scope explicit exclus, vezi docstring `match_statistics_adapter.py`: „NU scrie home/away_shots_on_target — owner PRIMAR rămâne mirror-ul football_data_co_uk")
- **Sursă**: AMBELE — istoric (backfill CSV) ȘI live (SFI), owneri diferiți dar ambii scriu prin COALESCE (ADR-036, niciun conflict)
- **Folosit în `FEATURE_COLUMNS`**: DA, indirect — `shot_dominance` (ADR-021), calculat din `home_shot_avg_recent`/`away_shot_avg_recent` (coloane derivate, populate de `sync/backfill_features.py`, nu direct din `home_shots`/`away_shots`)
- **Folosit în Oracle Engine (live)**: NU — zero referințe la `shot_avg_recent`/`home_shots` în `oracle_engine.py` (feature-ul `shot_dominance` e consumat DOAR de pipeline-ul ML, `ml_predictor._fetch_training_dataframe()`, nu de motorul de predicție live Poisson/blend)
- **Stare**: 3.501/53.409 populate (6,5%), doar 5 ligi mari, fereastră 2023-2025. Parțial valorificat (ML training), nu în serving live.

### Shots on target / Shots off target
- **Coloană**: `home_shots_on_target`/`away_shots_on_target`, `home_shots_off_target`/`away_shots_off_target` — EXISTĂ
- **Principal (LIVE)**: `soccerfootballinfo` (`shoots.on`/`shoots.off`) — ✅ REAL
- **Principal (ISTORIC, doar on_target)**: `football-data.co.uk` mirror — ✅ REAL, rulat (aceeași fereastră ca shots)
- **off_target istoric**: ❌ INEXISTENT — mirror-ul CSV nu are coloană separată pentru shots off target
- **Folosit în `FEATURE_COLUMNS`**: NU direct — `shots_ot_weight` există în `weights.json` (ponderea de blend Poisson), dar acela e un PARAMETRU de model, nu un feature citit din `match_history`; `_build_profile()` calculează `avg_shots_ot` din statistici recente proxy (`avg_goals_for * 0.45` când lipsesc datele reale — cascada Level 5/6), nu din `home_shots_on_target` stocat
- **Folosit în Oracle Engine**: proxy, nu date reale (aceeași cascadă ca possession)
- **Stare**: on_target parțial în cele 3.501 rânduri istorice; off_target 0%.

### Corners
- **Coloană**: `home_corners`/`away_corners` — EXISTĂ
- **Principal (LIVE)**: `soccerfootballinfo` (`corners.t`) — ✅ REAL
- **Principal (ISTORIC)**: `football-data.co.uk` mirror (`sync/backfill_match_stats.py`, grup `match_events`) — ✅ REAL, deja rulat
- **Folosit în `FEATURE_COLUMNS`**: DA, indirect — `corner_dominance` (ADR-012), din `home_corner_avg_recent`/`away_corner_avg_recent` (derivate, `sync/backfill_features.py`)
- **Folosit în Oracle Engine (live)**: NU (identic cu shots — doar ML training)
- **Stare**: 3.501/53.409 (6,5%), aceeași fereastră ca shots.

### Fouls
- **Coloană**: `home_fouls`/`away_fouls` — EXISTĂ
- **Principal (LIVE)**: `soccerfootballinfo` (`fouls.t`) — ✅ REAL
- **Principal (ISTORIC)**: `football-data.co.uk` mirror — ✅ REAL, rulat
- **Folosit în `FEATURE_COLUMNS`**: DA, indirect — `foul_diff` (ADR-013), din `home_foul_avg_recent`/`away_foul_avg_recent`
- **Folosit în Oracle Engine (live)**: NU
- **Stare**: 3.501/53.409, ML-only.

### Yellow cards / Red cards
- **Coloană**: `home_yellow_cards`/`away_yellow_cards`, `home_red_cards`/`away_red_cards` — EXISTĂ
- **Principal (LIVE)**: `soccerfootballinfo` (`fouls.y_c`/`fouls.r_c`) — ✅ REAL
- **Principal (ISTORIC)**: `football-data.co.uk` mirror — ✅ REAL, rulat
- **Folosit în `FEATURE_COLUMNS`**: DA, indirect — `card_diff` (ADR-012), din `home_card_avg_recent`/`away_card_avg_recent` (combină yellow+red, verifică `sync/backfill_features.py` pentru formula exactă)
- **Folosit în Oracle Engine (live)**: NU
- **Stare**: 3.501/53.409, ML-only.

### Offsides
- **Coloană**: `home_offsides`/`away_offsides` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`attacks.o_s`) — ✅ REAL
- **Fallback**: niciunul — nici football-data.co.uk mirror, nici FreeLF nu au offsides
- **Folosit în `FEATURE_COLUMNS`**: NU
- **Folosit în Oracle Engine**: NU
- **Stare**: 0/53.409. Complet nevalorificat, fără nicio cale istorică de recuperare.

### Penalties
- **Coloană**: `home_penalties`/`away_penalties` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`team.penalties`) — ✅ REAL
- **Fallback**: niciunul
- **Folosit în `FEATURE_COLUMNS`**: NU
- **Folosit în Oracle Engine**: NU
- **Stare**: 0/53.409. Nevalorificat.

### Substitutions
- **Coloană**: `home_substitutions`/`away_substitutions` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`team.substitutions`) — ✅ REAL
- **Fallback**: niciunul
- **Folosit**: NU (nici ML, nici Oracle)
- **Stare**: 0/53.409. Nevalorificat.

### Referee
- **Coloană**: `match_history.referee` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`detail.referee.name`) — ✅ REAL
- **Fallback**: niciunul funcțional (FreeLF/API-Football nu au adaptor de referee; `_STATIC_FALLBACK_CHAINS["referees"] = ("soccerfootballinfo",)` — un singur nivel, deja documentat corect în cod, nu o omisiune)
- **Folosit**: NU (nici ML, nici Oracle)
- **Stare**: 0/53.409. Nevalorificat.

### Lineups
- **Coloană**: `home_lineup`/`away_lineup` (jsonb, structură brută netratată) — EXISTĂ
- **Principal**: `soccerfootballinfo` (`detail.teamA/teamB.lineup`, pass-through brut) — ✅ REAL
- **Fallback 1**: `freelivefootball` — ÎNREGISTRAT în capability registry (LINEUPS), dar **niciun adaptor nu scrie `home_lineup`/`away_lineup`** — `match_statistics_adapter.py` (FreeLF) scrie DOAR possession+xG, nu lineup. ⚠️ ÎNREGISTRAT, NEIMPLEMENTAT pentru acest câmp specific.
- **Folosit**: NU (nici ML, nici Oracle — și structura jsonb brută nu ar putea fi consumată direct de ML fără parsare dedicată, netratată încă)
- **Stare**: 0/53.409. Nevalorificat.

### Managers
- **Coloană**: `home_manager`/`away_manager` (text) — EXISTĂ
- **Principal**: `soccerfootballinfo` (`detail.teamA/teamB.manager.name`) — ✅ REAL
- **Fallback 1**: `apifootball` — ✅ REAL, DAR pe o cale COMPLET SEPARATĂ: `ApiFootballHealthAdapter.fetch()` → `get_coaches()` → tabela `team_health_snapshot` (NU `match_history.home_manager`/`away_manager`). Sunt două reprezentări diferite ale conceptului „antrenor" în două tabele diferite, cu owneri diferiți — nu un fallback automat unul pentru celălalt azi.
- **Folosit**: NU pentru `match_history.home_manager`/`away_manager`. DA pentru `team_health_snapshot.coaches` — citit Database-First de `oracle_engine.py` (`get_team_health()`), alimentează un experiment shadow (`apifootball_injuries_coaches`), NU afectează predicția de producție direct.
- **Stare**: `match_history.home_manager`/`away_manager`: 0/53.409, nevalorificat. `team_health_snapshot.coaches`: populat activ (R-Sync-2), consumat în shadow, nu în producție.

### Stadium
- **Coloană**: `match_history.stadium` — EXISTĂ
- **Principal**: `soccerfootballinfo` (`detail.stadium.name`) — ✅ REAL
- **Fallback**: niciunul
- **Folosit**: NU
- **Stare**: 0/53.409. Nevalorificat. Notă: distinct de `venue_city` (folosit de Weather, vezi mai jos), care are propria sursă (ESPN/Odds API/TheSportsDB discovery) și propriul gol cunoscut documentat în CLAUDE.md (§Goluri cunoscute).

### Weather
- **Tabelă**: `weather_forecast_cache` (nu `match_history`) — EXISTĂ
- **Principal**: WeatherAPI (`WeatherForecastAdapter`, `oracle_api.get_weather(city, kickoff_date)`) — ✅ REAL, Database-First (R-Sync-5), `oracle_engine.py` citește exclusiv din cache, niciodată live
- **Fallback**: niciunul (WeatherAPI e „gratuit, universal", conform docstring adaptorului)
- **Folosit în Oracle Engine**: DA, prin `weather_penalty` (calculat la sync, citit din cache)
- **Folosit în `FEATURE_COLUMNS`**: NU — `weather_penalty` a fost ELIMINAT explicit (100% gol istoric la momentul ablației, importanță 0.0000)
- **Stare**: gol cunoscut, activ (CLAUDE.md): majoritatea meciurilor nu au `venue_city` populat (discovery ESPN nu-l furnizează), deci `weather_forecast_cache` nu se populează pentru majoritatea meciurilor — problemă de DISCOVERY (fixtures), nu de providerul de vreme în sine.

### Injuries
- **Tabelă**: `team_health_snapshot` (nu `match_history`) — EXISTĂ
- **Principal**: `apifootball` (`ApiFootballHealthAdapter`, `get_injuries()`) — ✅ REAL, Database-First (R-Sync-2)
- **Fallback**: **niciunul** — INJURIES e înregistrat DOAR pentru `apifootball` în capability registry; niciun alt provider din registry are acest DataType. Punct unic de eșec, documentat, nu ascuns.
- **Folosit**: shadow experiment (`apifootball_injuries_coaches`), Database-First, nu afectează predicția de producție direct azi (verifică `oracle_engine.py:1549` — flux de experiment, nu de blend principal)
- **Stare**: populat activ pentru echipele acoperite de League Mapping v2 / plan API-Football.

### Coaches
- Vezi „Managers" mai sus — aceeași cale (`team_health_snapshot.coaches`, `apifootball`, Database-First, shadow experiment).

### Odds
- **Tabelă**: `odds_history` (Frozen, ADR-005/006) — EXISTĂ
- **Principal (LIVE)**: The Odds API (`oddsapi`) — ✅ REAL, Frozen (`ODDS_PERSISTENCE_DESIGN.md`), orice atingere necesită ADR nou explicit — **NU modificat aici, per interdicția Sprint 3**
- **Principal (ISTORIC)**: `football-data.co.uk` mirror (`fetch_football_data_co_uk_rows()`, folosit de `services/odds_backfill_service.py`) — ✅ REAL, dar limitări documentate (un singur preț per bookmaker, fără distincție opening/closing reală, se oprește la finalul sezonului 2024/25)
- **Fallback**: `sportapi` are `DataType.ODDS` înregistrat, dar ⚠️ ÎNREGISTRAT, NEIMPLEMENTAT (aceeași limitare generală, §0)
- **Folosit în Oracle Engine**: DA — cotele sunt consumate direct pentru value betting (calea Frozen, neatinsă)
- **Stare**: activ, funcțional, în afara scopului de modificare al acestui sprint (Frozen).

### ELO
- **Coloană**: `match_history.home_elo_after`/`away_elo_after` (club, canonic) — EXISTĂ, Database-First (ADR-023/ADR-035 D2)
- **Principal (club)**: calculat intern (`ELOTracker`, actualizat din rezultate reale — nu e „furnizat" de un API extern, e derivat)
- **Fallback (echipe fără meciuri de club sincronizate, tipic naționale)**: `oracle_api.get_elo_rating()` → eloratings.net (`elo_ratings_adapter.py`, R-Sync-4) — ✅ REAL, Database-First
- **Folosit în `FEATURE_COLUMNS`**: DA — `home_elo`/`away_elo`
- **Folosit în Oracle Engine**: DA, direct — `database.queries.get_latest_team_elo()`, sursa PRIMARĂ, fallback la `oracle_api.get_elo_rating()` doar pentru echipe fără istoric de club
- **Stare**: valorificat complet, calea live conformă cu Regula 1 (Database-First).

### Standings / Team form
- **Tabele**: `team_form_freelf_snapshot`, `team_form_footballdata_snapshot` — EXISTĂ
- **Principal**: `freelivefootball` (`FreeLfFormAdapter`, standings/formă) — ✅ REAL, Database-First (R-Sync-6)
- **Fallback 1**: `footballdata` (`footballdata_form_adapter.py`) — ✅ REAL, Database-First (R-Sync-3)
- **Fallback 2**: `soccerfootballinfo` are `DataType.STANDINGS` ÎNREGISTRAT (confirmat live prin `championships/view`, comentariu în cod din 2026-07-27), dar ⚠️ ÎNREGISTRAT, NEIMPLEMENTAT — `soccerfootballinfo_client.py` are DOAR `get_matches_for_day()`/`get_match_detail()`, nicio metodă de standings. Gol capabilitate-vs-implementare, documentat corect în cod (nu ascuns).
- **Câmpul `"form"` (FreeLF)**: bug preexistent documentat — `get_freelf_standings()` nu copiază niciodată câmpul `"form"` din răspunsul brut, deci `freelf_team_form_snapshot.form` e mereu gol (task R-Sync-6a, neînceput, deja pe lista de task-uri)
- **Folosit în Oracle Engine**: DA, direct — cascada Level 0+1 (FreeLF) → Level 3 (football-data.org), ambele Database-First
- **Stare**: valorificat, cu un bug cunoscut (form gol) și o cotă FreeLF cronic epuizată (gol cunoscut, CLAUDE.md).

---

## 2. Rezumat — ce e deja conform Regulii 1 (Oracle citește EXCLUSIV din Supabase)

Verificat direct în `oracle_engine.py`: ELO, team form/standings, team health (injuries+coaches), weather sunt DEJA Database-First — zero apel live din Oracle Engine pentru aceste domenii (R-Sync-2/3/4/5/6, confirmate anterior). Rămân, per lista de task-uri deschise deja existentă (#16, #17), **3 apeluri live reziduale în `oracle_engine.py`** neatinse de acest audit — `self.api.get_h2h()`, `self.api.get_team_stats()`, `get_matches_for_week()`/`get_matches_for_date()` — task R-Sync-9/R-Sync-8, deja pe listă, NU modificate aici (Sprint 3 interzice explicit modificarea Oracle Engine până la o decizie separată).

## 3. Rezumat — coloane `match_history` extinse (Sprint 1) încă 0% populate azi

`home/away_xg_actual`, `home/away_possession`, `home/away_shots_off_target`, `home/away_offsides`, `home/away_penalties`, `home/away_substitutions`, `home/away_lineup`, `home/away_manager`, `referee`, `stadium`, `provider_raw_json` — toate au coloană + adaptor SFI complet (`soccerfootballinfo_match_statistics_adapter.py`), dar 0 rânduri populate live azi. Cauza probabilă (neconfirmată încă, verificare necesară înainte de implementare): rata de rezoluție `match_id` a resolver-ului (`soccerfootballinfo_event_resolver.py`) și/sau cota strictă (200/zi, cea mai mică dintre providerii cu STATISTICS) și/sau lipsa de rulare la scară a orchestratorului (`sync/sync_match_statistics.py`) — de investigat explicit ca prim pas al Priorității 1, nu presupus.

## 4. Ce NU s-a schimbat în acest pas

Zero modificări de cod. Zero scrieri Supabase. `sync_provider_manager.py` neatins. Acest document e strict de audit/decizie.

---

**Aștept aprobarea ta explicită pe acest document înainte de a începe implementarea Priorității 1.**
