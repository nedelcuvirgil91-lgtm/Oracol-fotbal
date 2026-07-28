# R-Sync-7b — Raport de dovezi (Match Discovery, shadow evaluation)

Livrabil Sprint 3 — cerut explicit cu metrici măsurate, nu concluzii. Toate cifrele de mai jos vin direct din Supabase (`equivalence_evaluations`, `provider_call_log`), citite după prima rulare reală, nu simulate.

## 0. Ce am activat (infrastructură deja existentă, niciodată pornită)

Codul pentru R-Sync-7b exista deja complet, verificat prin citire: `scheduled_fixtures_shadow.py` (evaluator pur), hook-ul `oracle_api.FootballOracleAPI._shadow_evaluate_scheduled_fixtures()` (apelat automat la finalul fiecărui `get_matches_for_week()`), `equivalence_governance.py` (clasificare + persistare), `migration_gate.py` (ADR-040, gate generic PASS/FAIL/GRAY). Singurul lucru lipsă: flag-ul era implicit `False` (Regula #3 — niciun flag nou pornit implicit).

**Scriere Supabase, arătată exact înainte de execuție:**
```sql
UPDATE model_config
SET data = data || '{"scheduled_fixtures_shadow_enabled": true}'::jsonb
WHERE id = 1;
```
Executat. Efect: de acum, ORICE apel real `get_matches_for_week()` (din `app.py`, sau din orice alt cod care-l invocă) produce automat o evaluare shadow, persistată — fără nicio modificare suplimentară de cod necesară, acumulare continuă de acum înainte.

Am declanșat o rulare reală (POC izolat, șters după confirmare), identică cu apelul din `app.py` (`COMPETITIONS_META`, 9 ligi, `days_ahead=7`).

## 1. Prima evaluare reală — `equivalence_evaluations`, id=7

| Metrică | Valoare măsurată |
|---|---|
| Fereastră | `2026-07-28` → `2026-08-04` |
| `live_count` (calea veche) | **6** |
| `scheduled_count` (calea nouă) | **28** |
| `matched_count` | **6** |
| **Coverage nou vs vechi** (matched/live) | **100,0%** (6/6) |
| **Fixture matching rate** | **100,0%** — toate meciurile găsite de calea live au fost găsite și de `scheduled_fixtures` |
| **Missing fixtures** (`missing_scheduled_count` — găsite live, lipsă din nou) | **0** |
| **Duplicate rate** (`duplicate_key_count`) | **0** |
| **Potențiali "false positives"** (`missing_live_count` — în nou, absente din vechi) | **22** — vezi §2, cauza reală identificată, nu doar numărată |
| `field_difference_count` (din câmpurile guvernate: league/kickoff_utc/venue_city) | 6 |
| `accepted_exception_count` (diferențe cunoscute, tolerate — `KNOWN_EXCEPTIONS`) | **6/6** — toate diferențele găsite sunt deja clasificate SAFE/EXPECTED |
| `provider_id_difference_count` | **0** |
| `equivalence_state` | `insufficient_data` (Nivel A — vezi §3) |

**`provider_breakdown`** (măsurat, nu presupus):
```json
{"thesportsdb": {"matched": 6, "field_diff": 0, "id_diff": 0, "missing_scheduled": 0}}
```
Toate cele 6 meciuri găsite de calea live, în această fereastră, au venit de la TheSportsDB (fallback-ul de nivel 5 al vechii cascade) — celelalte 5 provideri din cascada veche (FreeLF, Odds API, football-data.org, ESPN, API-Football) nu au produs niciun meci live în această fereastră specifică.

**`root_cause_summary`**: `{"UNKNOWN": 22, "KICKOFF_CONFLICT": 6}` — cele 22 de "missing_live" nu au încă o categorie de cauză mai specifică decât UNKNOWN (clasificator îmbunătățibil, vezi §2); cele 6 diferențe de câmp sunt toate `KICKOFF_CONFLICT` (deja acceptate, tie-break determinist, fără impact).

## 2. Investigație directă — cele 22 "missing_live" (în nou, absente din vechi)

Verificat direct: `scheduled_fixtures` conține 97 de rânduri, 10 ligi, populate de cei 6 adaptori (Odds API + FreeLF + football-data.org + ESPN + TheSportsDB + API-Football) — o rulare mult mai largă (7 zile, 9 ligi) decât apelul live comparat (care a produs doar 6 meciuri, toate de la TheSportsDB). **Nu sunt duplicate și nu sunt erori** — sunt meciuri reale pe care Discovery-ul nou le-a găsit (via Odds API/FreeLF/etc., providerii care AU date pentru această fereastră) dar pe care calea live NU le-a raportat în acest apel specific, cel mai probabil din cauza propriei cascade interne (calea veche se oprește la primul provider care produce suficiente rezultate per ligă, nu agregă toți cei 6 ca noul strat). Această diferență e, dacă se confirmă, un **avantaj** al noului Discovery (acoperire mai largă), nu un defect — dar rămâne needeterminat cu o singură evaluare; se clarifică prin acumulare (mai multe ferestre, mai multe zile).

## 3. De ce `equivalence_state = insufficient_data` (GRAY, nu eroare)

`equivalence_governance.MIN_LIVE_FOR_EVALUATION = 30` — o evaluare individuală devine „eligibilă" statistic doar dacă `live_count >= 30`. Rularea reală de azi a găsit 6 meciuri live — sub prag. **Motiv confirmat, nu presupus**: 2026-07-28 e adânc în off-season pentru majoritatea ligilor mari europene (aceeași cauză documentată deja la Prioritatea 1 — ultimul meci cu rezultat real: 2026-06-01). Nu e un defect al Discovery-ului nou sau vechi — e calendarul competițiilor.

`migration_gate status R-Sync-7b` → interogare directă `migration_gate_status` (view): **niciun rând eligibil încă** → verdict **GRAY** (`"Nicio evaluare eligibilă încă — sistem în acumulare de dovezi (GRAY, nu eroare)."`). Pragurile pentru PASS (ADR-040, implicite, configurabile în `model_config.migration_gate_thresholds`): **500 meciuri potrivite cumulate** ȘI **minim 50 per provider** ȘI ultima evaluare eligibilă GREEN/YELLOW. Cu 6 meciuri live într-o singură rulare, acumularea necesară nu poate fi produsă artificial într-o singură sesiune — cere zile reale de trafic, acum că shadow-ul e pornit permanent.

## 4. Reliability / latență / cost per provider (măsurat direct, `provider_call_log`, ultimele 30 min)

| Provider | Endpoint-uri | Apeluri | Reliability | Latență medie | Latență max | Cost class (ADR-034) |
|---|---|---|---|---|---|---|
| `espn` | 11 endpoint-uri (per ligă) | 77 | **100,0%** | 11-89 ms | 486 ms (1 outlier) | FREE_UNLIMITED |
| `thesportsdb` | 3 endpoint-uri | 27 | **100,0%** | 94-105 ms | 206 ms | FREE_UNLIMITED |
| `footballdata` | `matches` | 2 | **100,0%** | 1.281 ms | 1.416 ms | RATE_LIMITED |
| `oddsapi` | `sports` | 22 | **81,8%** (18/22 OK) | 78 ms | 254 ms | MONTHLY_QUOTA |
| `freelivefootball` | `football-get-matches-by-date` | 2 | **0,0%** (0/2 OK, HTTP 429) | 3.197 ms | 3.200 ms | MONTHLY_QUOTA |
| `apifootball` | — | 0 apeluri în această fereastră | — | — | — | MONTHLY_QUOTA |

**Observații directe, nu presupuse:**
- `freelivefootball`: 0% reliability, HTTP 429 — confirmă din nou golul deja documentat în CLAUDE.md („Cotă FreeLF/RapidAPI cronic epuizată") — nu e o descoperire nouă, e re-confirmare live.
- `oddsapi`: 81,8% reliability (4 din 22 eșecuri) — de investigat separat dacă persistă (posibil rate-limiting pe sport-key-uri multiple în aceeași rulare).
- `espn`/`thesportsdb`: gratuite, rapide, 100% fiabile — cei mai buni performeri operaționali din cei 6, deși NU sunt provider principal (rămân pe pozițiile 4-5 în cascada veche).

## 5. Verdict, onest

**R-Sync-7b NU e închis.** Mecanismul e complet, activat, verificat funcțional end-to-end pe un caz real (coverage 100%, 0 missing fixtures, 0 duplicate, 0 provider ID mismatches, toate diferențele de câmp deja acceptate) — dar volumul acumulat e 6/500 meciuri potrivite, sub pragul de eligibilitate (30 live/evaluare) pentru orice evaluare de până acum. Gate-ul rămâne **GRAY** (acumulare de dovezi), nu FAIL. Nu poate deveni PASS printr-o singură sesiune — cere zile reale de rulare, acum că flag-ul e pornit permanent și fiecare apel real la `get_matches_for_week()` (din `app.py`, folosire normală a aplicației) contribuie automat câte o evaluare.

**R-Sync-7c (tăierea căii vechi din Oracle) rămâne blocată explicit** de `tests/test_migration_gate_blocks_r_sync_7c.py` — nici nu a fost atinsă, nici nu va fi atinsă până la un verdict PASS real, verificat.

Oracle Engine neatins pe tot parcursul acestui pas.
