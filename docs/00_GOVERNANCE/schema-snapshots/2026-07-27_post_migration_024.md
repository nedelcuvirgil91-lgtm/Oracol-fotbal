# Snapshot schemă Supabase — după migrarea 024 (`equivalence_evaluations`)

**Scop**: punct de referință pentru audit, NU pentru rollback (deosebire explicită, cerută la aprobarea migrării 024). Răspunde la întrebări de tipul „când a apărut coloana X?" fără să fie nevoie de reconstrucție din istoricul de conversații.

**Proiect**: `Prediction` (`gtlpyxzocacaqyompkwe`, `eu-central-1`).

**Migrare de referință**: `024_equivalence_evaluations` (versiune `20260727092203`), ultima aplicată la data acestui snapshot — confirmată prin `list_migrations` ca prezentă și ultima din listă.

**Data**: 2026-07-27.

---

## Tabelul nou introdus de migrarea 024

### `public.equivalence_evaluations`

RLS: **activ**, fără policy (acces exclusiv `service_role`).

| Coloană | Tip |
|---|---|
| id | bigint (PK, identity) |
| run_id | bigint (FK → `automation_runs.id`) |
| gate_key | text |
| entity | text |
| window_from | date |
| window_to | date |
| live_count | integer |
| scheduled_count | integer |
| matched_count | integer |
| missing_scheduled_count | integer |
| missing_live_count | integer |
| duplicate_key_count | integer |
| field_difference_count | integer |
| provider_id_difference_count | integer |
| accepted_exception_count | integer |
| equivalence_score | numeric |
| equivalence_state | text (CHECK: insufficient_data\|broken\|red\|yellow\|green) |
| provider_breakdown | jsonb |
| root_cause_summary | jsonb |
| sample_missing_scheduled | jsonb |
| sample_missing_live | jsonb |
| sample_field_differences | jsonb |
| sample_provider_id_diffs | jsonb |
| evaluated_at | timestamptz |

Constrângeri: `equivalence_evaluations_pkey` (PK, `id`), `equivalence_evaluations_unique_window` (UNIQUE, `gate_key, entity, window_to, matched_count`), `equivalence_evaluations_run_id_fkey` (FK → `automation_runs.id`), `equivalence_evaluations_state_check` (CHECK pe `equivalence_state`).

View asociat: `public.migration_gate_status` — compilează, interogabil (`SELECT * FROM migration_gate_status LIMIT 1` a rulat fără eroare; 0 rânduri, așteptat — `equivalence_evaluations` era goală la acest snapshot).

## Restul schemei (39 tabele, la data acestui snapshot, `public`)

Listă completă `nume | RLS | număr coloane`, din `list_tables(verbose=true)`, imediat înainte de migrarea 024 (neschimbată de migrare, cu excepția adăugării `equivalence_evaluations`):

| Tabelă | RLS | Coloane |
|---|---|---|
| api_cache | ❌ | 10 |
| api_football_league_coverage | ✅ | 11 |
| api_provider_status | ❌ | 6 |
| automation_runs | ✅ | 12 |
| challenger_evaluations | ✅ | 22 |
| challengers | ✅ | 9 |
| champion_health_evaluations | ✅ | 20 |
| consensus_capture_samples | ✅ | 8 |
| consensus_validation_verdicts | ✅ | 10 |
| decision_feed | ✅ | 13 |
| elo_history | ✅ | 7 |
| elo_ratings | ❌ | 5 |
| **equivalence_evaluations** (nou, migrarea 024) | ✅ | 24 |
| experiment_registry | ❌ | 27 |
| footballdata_team_form_snapshot | ✅ | 9 |
| freelf_team_form_snapshot | ✅ | 14 |
| league_provider_coverage | ❌ | 5 |
| match_history | ✅ | 65 |
| match_history_adr025_faza4_backup_20260716 | ❌ | 65 |
| match_history_faza3_backup_20260715 | ❌ | 60 |
| match_history_gate07_renorm_backup_20260716 | ❌ | 3 |
| match_history_mov_activation_backup_20260715 | ❌ | 7 |
| ml_model_status | ✅ | 8 |
| model_champions | ✅ | 9 |
| model_config | ✅ | 3 |
| model_weights | ✅ | 3 |
| national_team_elo_snapshot | ✅ | 6 |
| odds_api_recent_results | ✅ | 10 |
| odds_history | ✅ | 17 |
| portfolio | ✅ | 11 |
| provider_metrics | ❌ | 11 |
| recalibration_log | ✅ | 13 |
| scheduled_fixtures | ✅ | 29 |
| shadow_predictions | ❌ | 25 |
| shadow_provider_recommendations | ✅ | 12 |
| sync_status | ❌ | 6 |
| team_health_snapshot | ✅ | 7 |
| training_runs | ✅ | 10 |
| weather_forecast_cache | ✅ | 13 |

**Notă**: tabelele fără RLS (`api_cache`, `api_provider_status`, `elo_ratings`, `experiment_registry`, `league_provider_coverage`, `match_history_*_backup_*`, `provider_metrics`, `shadow_predictions`, `sync_status`) sunt preexistente acestui snapshot, neatinse de migrarea 024 — nu reprezintă o găsire nouă, doar starea documentată la acest moment de referință.

## Cum se actualizează

Acest fișier NU se întreține automat. Se regenerează manual (sau prin `migration_gate` CLI, când există, G3) după fiecare migrare viitoare care schimbă schema `public`, ca punct de referință — nu ca sursă de adevăr (sursa de adevăr rămâne Supabase însuși, interogabil prin `list_tables`/`list_migrations`).
