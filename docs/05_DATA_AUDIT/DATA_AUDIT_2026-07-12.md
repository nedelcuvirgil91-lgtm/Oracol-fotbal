# DATA_AUDIT_2026-07-12.md — Football Oracle

**Status**: Audit de date — nu e document de arhitectură, nu necesită ADR, nu e Frozen. Persistat pentru că servește direct ca referință pentru Sprint 1–4 de mai jos (regulă de guvernanță: un document folosit ca referință de alte componente/decizii nu rămâne doar în conversație).
**Scop**: audit al datelor disponibile (nu al codului) — coloane istorice existente, endpoint-uri de provider folosite/nefolosite, acoperire de ligi, evaluare de feature engineering, prioritizare ROI. Metodologie: verificare directă în Supabase (schema + date reale), în cod (grep/citire directă), în istoricul GitHub Actions — nicio pretenție neverificată.
**Precede**: implementarea descrisă în Sprint 1 (`docs/05_DATA_AUDIT/` — sprinturile ulterioare vor primi propriul plan tehnic scurt înainte de cod, conform disciplinei stabilite).

---

## 1. Coloanele istorice existente

### `match_history` (53.430 rânduri) — tabela principală de antrenare ML

| Coloană | Populare | Folosită de predictor? |
|---|---|---|
| `home/away_offensive_rating`, `home/away_defensive_rating`, `home/away_form_score`, `home/away_elo`, `h2h_modifier`, `h2h_meetings` | 100% | **DA** — singurele 10 din `FEATURE_COLUMNS` (ml_predictor.py) |
| `actual_home_goals`, `actual_away_goals`, `actual_result`, `used_for_training` | 99,96% (53.409/53.430) | DA — țintă de antrenare |
| `home_xg_pred`, `away_xg_pred`, `weather_penalty`, `mc_prob_home/draw/away` | 21/53.430 (0,04%) | NU — eliminate din features prin test de ablație (deja documentat) |
| `home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`, `home_possession`, `away_possession`, `home_xg_actual`, `away_xg_actual`, `stats_source` | **0/53.430 — complet goale** | NU — coloane există, cod le referențiază conceptual, nimic nu le populează |
| `backfill_done` | 3.816/53.430 (7%) | — feature engineering complet doar pe 7% din istoric |

**Descoperirea centrală a auditului**: `oracle_api.py:454` — `get_match_statistics(event_id)` — funcție completă, funcțională, care întoarce exact `home_xg`, `away_xg`, `home_possession`, `away_possession`, `home_shots_ot`, `away_shots_ot`, `home_big_chance`, `away_big_chance` de la Free Live Football (provider deja integrat, deja plătit). **Zero apeluri către această funcție în tot codul.** La fel `has_xg_coverage()`.

### `elo_history` (39.575 rânduri)
Complet populată, dar write-only — nicio interogare `SELECT` nicăieri în cod. Tendința ELO (creștere/scădere) e semnal complet neexploatat.

### `odds_history` (0 rânduri)
Schema completă, scrisă de `services/odds_persistence_service.py` — serviciu creat recent, încă nemers în cron-ul de producție (nu e problemă de design, e problemă de deployment/merge).

### `shadow_predictions` / `experiment_registry` (0 rânduri)
Infrastructură Learning Core completă, niciodată exercitată cu un experiment real.

### Restul tabelelor
`portfolio`, `model_weights`, `model_config`, `ml_model_status`, `recalibration_log`, `api_cache`, `sync_status`, `elo_ratings`, `league_provider_coverage`, `provider_metrics`, `api_provider_status` — schemă și utilizare conforme cu așteptările, fără coloane oarbe relevante suplimentare.

---

## 2. Sursele API existente — folosit vs. nefolosit

### Odds API (`api.the-odds-api.com/v4`)
- Folosit: `/sports`, `/sports/{key}/events`, `/sports/{key}/scores`, `/sports/{key}/odds` — **doar piața `h2h`**.
- Nefolosit, dar deja cerut de cod: `oracle_engine._special_value_bets()` (linia 797) caută `over25_odds`, `under25_odds`, `btts_yes_odds`, `btts_no_odds`, `dc_home_odds`, `dc_away_odds` — niciuna nu e populată vreodată. Rezultat: „special value bets" (Over/Under, BTTS, Double Chance) e structural mort — listă goală, mereu.
- The Odds API oferă și piața `totals` alături de `h2h`; disponibilitatea `btts`/`double_chance` pe planul nostru exact — **neconfirmată**, de verificat live înainte de a scrie parsing definitiv.

### API-Football (`v3.football.api-sports.io`)
- Folosit: `/teams`, `/injuries`, `/coachs`.
- Nefolosit (catalog public v3, neconfirmat pe planul nostru): `/fixtures/statistics`, `/fixtures/lineups`, `/fixtures/events`, `/odds`, `/predictions`, `/players/statistics`.
- `mappings.LEAGUE_PROVIDERS` are `api_football: "necunoscut"` pentru toate cele 11 ligi — acoperirea per-ligă nu a fost niciodată verificată.

### Free Live Football / RapidAPI
- Folosit: meciuri pe dată, standing, `statistics/{id}` (fetch-uit, rezultat aruncat — vezi §1), `h2h/{id}`, lineup home/away.
- Nefolosit, deja fetch-uit: `get_lineup()` întoarce și `formation`/`confirmed`, parsate dar niciodată citite de `injury_manager.py` (doar `unavailable` e folosit).

### WeatherAPI.com (corectare: nu „OpenWeather" — providerul integrat e WeatherAPI.com)
- Folosit: `/current.json`, `/forecast.json`.
- Nefolosit: `/history.json` — vreme istorică reală, relevantă pentru completarea retroactivă a `weather_penalty` (azi 0,04% populat).

### football-data.org v4
- Folosit: `/matches`, `/competitions/{code}/standings`.
- Nefolosit: `/competitions/{code}/scorers`. Plan gratuit deja la limită (12 competiții, 10 req/min) — valoare marginală mică.

### ESPN (nedocumentat oficial) / TheSportsDB
- Folosit: scoreboard (ESPN), `eventsnextleague.php`/`eventslast.php` (TSDB).
- Nefolosit: endpoint `summary?event={id}` la ESPN (posesie/șuturi/cartonașe) — nedocumentat oficial, risc de instabilitate. TSDB: date detaliate doar pe cheie plătită.

---

## 3. Ligi

### Urmărite azi (11, din `LEAGUE_PROVIDERS`)
Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, Conference League, Romania SuperLiga, World Cup 2026, MLS.

### Pregătite parțial, neactive
`LEAGUE_ALIASES` conține deja Eredivisie și Primeira Liga („păstrate pentru extensibilitate") — normalizare de nume gata, fără `LeagueDefinition` completă și fără sursă de import istoric.

### Lipsă (verificat: nu apar în `LEAGUE_PROVIDERS`/`league_provider_coverage`)
Competiții feminine (Women's World Cup, UWCL, WSL), competiții de tineret (U21 EURO, U20/U17 World Cup), cupe naționale (FA Cup, Copa del Rey, DFB-Pokal, Coppa Italia, Cupa României), calificări (World Cup/Euro qualifiers), Nations League, Euro turneu final.

**Notă**: audit separat, dedicat, per decizia utilizatorului din 2026-07-12 — vezi §"Decizii" mai jos. Nu se execută în timpul sprinturilor curente.

---

## 4. Feature Engineering — evaluare per categorie

| Categorie | Efort colectare | Efort integrare | Impact plauzibil | Verdict |
|---|---|---|---|---|
| Șuturi pe poartă / posesie / xG real (FreeLF, deja fetch-uit) | Zero | Mic | Plauzibil | Sprint 1 (colectare+persistare) → Sprint 2 (ablație înainte de ML) |
| Tendință ELO (`elo_history`, deja în DB) | Zero | Mic | Plauzibil, netestat | Sprint 3, prin ablație |
| Lineup confirmat + formație (FreeLF, deja fetch-uit) | Zero | Mic | Marginal | Oportunist, cost aproape zero |
| Vreme istorică retroactivă (`/history.json`) | Mic | Mediu | Necunoscut — netestat vreodată cu date reale | Testează prin ablație, nu presupune |
| Statistici API-Football (cornere/cartonașe/faulturi) | Mediu | Mediu-Mare | Necunoscut, acoperire neconfirmată | Amânat — decizie explicită a utilizatorului |
| Piețe Odds API suplimentare (O/U, BTTS) | Mic | Mic | Nu e feature ML — activează funcționalitate UI existentă | Sprint 1 |
| Ligi/competiții noi | Mediu-Mare | Mare | Extindere acoperire, nu model | Audit separat, viitor |
| Attendance, arbitru, stadion, xA jucător | Mare | Mare | Speculativ, zero plumbing azi | Amânat explicit |

---

## 5. Prioritizare ROI (ordine inițială din audit)

| # | Feature | Sursă | Efort | Impact estimat |
|---|---|---|---|---|
| 1 | Conectează `get_match_statistics()` la backfill/sync → populează coloanele goale din `match_history` | FreeLF (deja integrat) | Foarte mic | Mare |
| 2 | Activează O/U + BTTS la Odds API → deblochează `_special_value_bets()` | The Odds API (deja integrat) | Foarte mic | Mare |
| 3 | Feature „tendință ELO" din `elo_history` | Supabase, date deja colectate | Mic | Mediu |
| 4 | Folosește `formation`/`confirmed` din lineup în raportul de accidentări | FreeLF (deja integrat) | Mic | Mic-Mediu |
| 5 | Verifică acoperirea reală API-Football per ligă | API-Football | Mic (verificare) | Necunoscut, condiționează #7 |
| 6 | Backfill vreme istorică + ablație reală pe `weather_penalty` | WeatherAPI | Mediu | Necunoscut, netestat |
| 7 | Statistici detaliate API-Football | API-Football | Mediu-Mare | Condiționat de #5 |
| 8 | Eredivisie / Primeira Liga | football-data.org / ESPN / TSDB | Mediu | Extindere acoperire |
| 9 | Cupe / calificări / feminin / tineret | Neconfirmat per-provider | Mare | Decizie de produs |
| 10 | Attendance, arbitru, stadion, xA jucător | Neconfirmat | Mare | Nerecomandat acum |

---

## Decizii și prioritizare (utilizator, 2026-07-12)

Aprobat, cu re-secvențiere:

- **Sprint 1 (obligatoriu, imediat)**: #1 (`get_match_statistics()` → `match_history`) și #2 (piețe O/U + BTTS → `_special_value_bets()`). Motivație: cost de implementare minim, zero incertitudine despre disponibilitatea datelor, câștig imediat pentru utilizator (Sprint 1, item 2) și pentru calitatea viitoare a antrenării ML (Sprint 1, item 1).
- **Sprint 2**: shots on target / possession / xG real ca feature ML — **doar** prin fluxul disciplinat: colectare → persistare în `match_history` → backfill istoric → shadow feature → test de ablație → comparare statistică → abia apoi intrare în predictor. Interzis explicit: introducerea directă a unui feature nou în ML fără acest flux.
- **Sprint 3**: ELO Trend (forma ELO pe ultimele 5 meciuri — viteza de urcare/coborâre, nu ELO absolut) — aceeași disciplină (shadow → ablație → promovare).
- **Amânat explicit**: cornere, cartonașe, faulturi, attendance, arbitri — cresc dimensionalitatea mult, informație utilă neconfirmată fără testare riguroasă.
- **Feature Pipeline (infrastructură, înainte de Sprint 2)**: orice feature nou trebuie să treacă prin același flux generic — Provider → Normalizare → Persistare → Backfill → Learning Core → Shadow Testing → Promotion Gate — construit o singură dată, reutilizat de fiecare feature ulterior, nu reinventat per feature.
- **Audit de ligi per-provider** (tabel Liga × Odds × Stats × xG × Lineup × Injury × Istoric × Recomandare): cerut explicit ca **audit separat, viitor, nu în timpul sprinturilor curente**.
