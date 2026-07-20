# ADR-036 — Canonical Feature Ownership

**Status**: APROBAT — 2026-07-20 (aprobat de utilizator după două runde de
review arhitectural, cu corecții demonstrate pe cod și date reale).

**Data**: 2026-07-20

**Contextul care l-a declanșat**: review-ul independent al D3 (ADR-035) a
descoperit un defect structural în modelul de persistență `match_history` —
coloane canonice scrise de două căi concurente cu arbitraj „first-writer-wins".

## Context

`match_history` (66 de coloane) e scrisă de mai multe componente. Auditul
(cod + SQL read-only pe proiectul `Prediction`, 2026-07-20) a demonstrat:

1. **Cauza rădăcină**: 10 coloane de feature ML —
   `home_offensive_rating`/`home_defensive_rating`/`away_offensive_rating`/
   `away_defensive_rating`, `home_form_score`/`away_form_score`,
   `home_elo`/`away_elo`, `h2h_modifier`/`h2h_meetings` — sunt scrise de
   **două** căi:
   - `oracle_engine._cache_prediction()` (RPC `upsert_match_canonical`,
     `COALESCE` fill-once) — la momentul PREDICȚIEI, din cascada live.
   - `sync/backfill_features.run_backfill()` (`UPDATE` direct, gate NULL-only)
     — recalcul walk-forward, DUPĂ rezultat.
   Prediction Engine scrie primul (predicție înainte de meci); `COALESCE`/
   gate-NULL împiedică backfill-ul să corecteze → ML se antrenează pe
   feature-uri din cascada live, nu pe recalculul walk-forward.

2. **Amploarea reală, cuantificată**: din 53.409 rânduri de antrenare,
   **0 contaminate azi**; doar 29 fixture-uri prezise live, toate
   nefinalizate. Defectul e **latent/structural** — se materializează când
   un fixture prezis se joacă. Nu există corupție istorică de reparat.

3. **RPC-ul NU e defectul**: `upsert_match_canonical` e un contract generic
   folosit legitim de `sync/import_historical.py` pentru a scrie
   `home_elo`/`away_elo` din Kaggle (`HomeElo`/`AwayElo`). Toate cele 53.438
   de rânduri au `home_elo` scris prin acest RPC. O interdicție la nivel de
   RPC ar rupe importul. Problema e **exclusiv la apelant** (`_cache_prediction`
   trimite coloane care nu-i aparțin).

## Decizie

**Fiecare coloană canonică din `match_history` are exact un model de owner,
iar `first-writer-wins` încetează să fie mecanism de arbitraj între componente
diferite.**

### Modelul de ownership (aprobat)

| Categorie | Coloane | Owner canonic | Politică de scriere |
|---|---|---|---|
| **Prediction Outputs** | `home/away_xg_pred`, `prob_*_pred`, `mc_prob_*`, `weather_penalty`, `home/away_data_quality`, `home/away_xg_actual` | `oracle_engine._cache_prediction` | fill-once per predicție; **nu** scrie niciodată feature-uri ML |
| **Canonical FEATURE_COLUMNS** (cele 10 P0 + `home/away_elo_after` + 8 `*_avg_recent`) | vezi `sync/backfill_features.FEATURE_COLUMNS` | `sync/backfill_features.run_backfill` (trackere walk-forward) | recalcul walk-forward după rezultat; overwrite doar de owner (Reset+Replay) |
| **Canonical Import Data** | `home_elo`/`away_elo` (pentru rândurile de import) | `sync/import_historical` (Kaggle `HomeElo`/`AwayElo`) | fill-once la INSERT; **compatibil** cu backfill (mutual exclusiv per rând — backfill sare coloanele ne-NULL) |
| **Actual Results** | `actual_home_goals`, `actual_away_goals`, `actual_result` | `sync/sync_results` | overwrite permis (corecție de scor) |
| **Identitate** | `id`, `fixture_id`, `home_team`, `away_team`, `league`, `kickoff_date` | fixtures/import | imutabil după INSERT (`league`: fill-once) |
| **Control/audit** | `used_for_training`, `backfill_done`, `created_at`, `superseded_*` | flux dedicat (toggle / DB default / reconciliere) | flag-uri de proces |

**Nuanță explicită** (`home_elo`/`away_elo`): NU single-writer absolut, ci
**single-writer-per-rând cu doi owneri compatibili mutual exclusivi** (import
pentru rânduri istorice; backfill pentru restul — ambii pre-meci, fill-once).
Prediction Engine nu scrie niciodată aceste coloane. Orice procedură de „Reset
Features" trebuie scopată să NULL-eze doar coloanele exclusiv-backfill (cele
10 P0 + `*_elo_after` + `*_avg_recent`), **niciodată** `home_elo`/`away_elo`
pe rândurile de import.

### Ce se schimbă (enforcement la apelant, nu la RPC)

- **Stage 1**: `_cache_prediction()` încetează să trimită cele 10
  `FEATURE_COLUMNS` owner-ate de backfill. Rândurile prezise le lasă NULL;
  backfill le completează walk-forward după rezultat.
- **Stage 3**: eliminarea scrierii legacy `actual_*` din
  `oracle_engine.update_weights_from_result()` (cale manuală neapelată în
  fluxul automat, `COALESCE` fill-once — strict mai slabă decât `sync_results`);
  gărzi statice (AST) care previn reapariția: `FEATURE_COLUMNS` apar în payload
  de scriere DOAR în `run_backfill`/`import_historical`, niciodată în
  `_cache_prediction`; `actual_*` scrise DOAR de `sync_results`.
- **Stage 2 — Deferred Operational Task (NU parte a implementării D3.5)**:
  curățare operațională one-time a celor ≤29 rânduri prezise-nefinalizate
  (`UPDATE ... SET (cele 10) = NULL WHERE prob_home_pred IS NOT NULL AND
  actual_result IS NULL`). **Nu se execută la merge-ul D3.5.** Argument:
  (a) e mentenanță asupra datelor existente, nu corectitudine de arhitectură —
  Stage 1+3 rezolvă complet contractul de scriere; (b) numărul de înregistrări
  e foarte mic (≤29, azi 0 finalizate, deci 0 rânduri de antrenare afectate);
  (c) rândurile s-ar putea autocorecta natural — dacă rezultatul se
  sincronizează, `run_backfill` recalculează coloanele (după ce nu mai sunt
  scrise de predicție). **Se execută ulterior DOAR dacă monitorizarea confirmă
  că acele înregistrări nu se autocorectează**, cu SQL + snapshot + rollback
  arătate înainte de rulare (Supabase-safety). Până atunci: documentat, nu
  executat.

### Ce NU se schimbă

- **`upsert_match_canonical` (RPC)** — contract generic, neatins. Necesar
  legitim pentru import.
- **D1/D2/D3** (calea de CITIRE Database-First) — neatinse. D3.5 repară
  exclusiv contractul de SCRIERE. `home_elo_after` (D2) e deja single-writer
  (backfill) — confirmă corectitudinea alegerii D2.
- **Formulele ML/xG/Poisson/Monte Carlo** — neatinse.

## Consecințe

- ML se antrenează garantat pe feature-uri walk-forward (pentru rânduri noi),
  nu pe valori din cascada live înghețate de `COALESCE`.
- Enforcement-ul stă la apelant + gardă statică (ca la D1/D2/D3), nu în DB —
  fiindcă RPC-ul nu poate distinge importul (permis) de predicție (interzis).
- Costul: `update_weights_from_result` pierde scrierea `actual_*` (oricum
  neapelată automat); niciun impact pe fluxul de producție.
- Extensibilitate: orice `FEATURE_COLUMN` nou (promovat prin ablație) primește
  owner explicit în tabelul de mai sus de la introducere; niciun cod nou nu
  scrie o coloană cu owner existent — garda AST o impune.

## Ordinea de execuție (aprobată)

1. ✅ ADR-036 (acest document).
2. ✅ **Stage 1 — FINALIZAT 2026-07-20.** `_cache_prediction` nu mai trimite
   cele 10 `FEATURE_COLUMNS`. Gardă AST + fail-before/pass-after.
3. ✅ **Stage 3 — FINALIZAT 2026-07-20.** Eliminare scriere legacy `actual_*`
   din `update_weights_from_result` (verificat AST: zero apeluri reale) +
   gărzi AST Single-Writer pentru `FEATURE_COLUMNS` și `actual_*`.
4. ⏸️ **Stage 2 — DEFERRED OPERATIONAL TASK (neexecutat).** Curățarea celor
   ≤29 rânduri NU face parte din implementarea D3.5 și NU se execută la merge.
   Rămâne documentat (SQL + snapshot + rollback pregătite), de executat ulterior
   DOAR dacă monitorizarea confirmă că înregistrările nu se autocorectează —
   vezi „Ce se schimbă", Stage 2.

**Implementarea structurală D3.5 e completă cu Stage 1 + Stage 3.** Contractul
Single-Writer e impus; Prediction Engine nu mai poate contamina coloanele
canonice. Stage 2 e mentenanță de date, nu corectitudine de arhitectură.

## Dependencies

- ADR-035 (Database-First Prediction Engine) — D1/D2/D3, calea de citire;
  D3.5 repară contractul de scriere descoperit în review-ul D3.
- `docs/00_GOVERNANCE/D3.5-FEATURE_CANONICALIZATION_TASK.md` — nota inițială
  care a deschis acest task; superseded de acest ADR.
