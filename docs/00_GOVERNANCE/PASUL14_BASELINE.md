# Pasul 14 — Baseline producție (T0), înainte de orice scriere

Snapshot complet, read-only, al stării relevante din Supabase (`Prediction`,
`eu-central-1`) **înainte** de orice acțiune a Pasului 14 (activare shadow
Blend). Scop: reper T0 fix, comparabil cu stările ulterioare (T1 — flag
activ, T2 — prima antrenare, T3 — primul Challenger, T4 — primele
`shadow_predictions`), per cererea explicită a proprietarului produsului.

Data capturii: 2026-08-04, imediat înainte de orice `UPDATE`/scriere din
Pasul 14. Toate interogările de mai jos sunt `SELECT`, executate prin
`mcp__Supabase__execute_sql` (citire directă pe proiectul live).

## T0.1 — `model_config` (id=1), blob complet

```json
{
    "h2h_weight": 0.15,
    "elo_reference": 1500,
    "stake_default": 10,
    "kelly_fraction": 0.25,
    "last_n_fixtures": 5,
    "ml_blend_weight": 0.35,
    "elo_blend_weight": 0.35,
    "elo_sigmoid_scale": 400,
    "h2h_lookback_days": 1095,
    "max_goals_poisson": 8,
    "learning_core_enabled": true,
    "recency_half_life_days": 365,
    "monte_carlo_simulations": 10000,
    "recalibration_max_delta": 0.15,
    "value_bet_threshold_pct": 5,
    "consensus_capture_enabled": true,
    "recalibration_learning_rate": 0.05,
    "selection_engine_shadow_enabled": true,
    "challenger_shadow_logging_enabled": true,
    "flashscore_shadow_logging_enabled": true,
    "scheduled_fixtures_shadow_enabled": true
}
```

**Observație critică**: cheia `blend_challenger_shadow_logging_enabled`
**lipsește complet** din blob — nu apare deloc, nici `true`, nici `false`.
`supabase_client.load_config()` face *replace* cu acest blob (nu *merge* cu
`DEFAULT_CONFIG`), deci `self.config.get("blend_challenger_shadow_logging_enabled", False)`
cade pe fallback-ul `False` din codul `oracle_engine.py` însuși — flag-ul e
efectiv oprit azi, dar prin fallback de cod, nu printr-o valoare explicită
în `model_config`. Pasul 13 e deci **deployat, dar neoperațional** la T0.

Chei absente similar (context, neatinse de Pasul 14): `champion_guardian_enabled`,
`champion_guardian_proposals_enabled`, `consensus_validation_enabled`.

## T0.2 — `challengers` (toate rândurile, orice familie)

| training_run_id | algorithm_family | league_scope | state | created_at |
|---|---|---|---|---|
| 13a9ac01… | gate_validation_test | corrupted_artifact_b1819092 | PROMOTED | 2026-07-14 16:44:52 |
| fccedde2… | gate_validation_test | version_mismatch_b1819092 | PROMOTED | 2026-07-14 16:44:48 |
| a7f695da… | gate_validation_test | happy_path_b1819092 | PROMOTED | 2026-07-14 16:44:43 |
| 9217d1dd… | gate_validation_test | happy_path_b1819092 | PROMOTED | 2026-07-14 16:44:39 |
| 6b0ff296… | gate_validation_test | happy_path | SUCCEEDED | 2026-07-14 16:36:39 |

**Toate 5 rândurile sunt artefacte ale unui script de validare a gărzilor
de infrastructură (`gate_validation_test`, 2026-07-14), nu Challengeri
reali.** Zero rânduri pentru `algorithm_family='xgboost_v1'`. Zero rânduri
pentru `algorithm_family='blend_v1'`.

## T0.3 — `training_runs`, sumar pe (algorithm_name, league_scope, status)

| algorithm_name | league_scope | status | count | ultima rulare |
|---|---|---|---|---|
| xgboost_v1 | all | trained | 47 | 2026-08-03 18:06:49 |
| production_champion | all | not_applicable | 2 | 2026-08-03 12:18:23 |
| gate_validation_test | (3 scope-uri) | trained | 6 | 2026-07-14 16:44:51 |

**Zero rânduri pentru `blend_v1`** — algoritmul nu a fost antrenat
niciodată până la T0. Cele 47 rulări `xgboost_v1` sunt orfane față de
`challengers` (create direct prin `run_training()`/CLI, în afara
orchestratorului `continuous_learning.py`, în sesiuni anterioare de
validare — Pasul 9/10a/11 din acest proiect — nu prin Faza B a ciclului
decuplat, care nu a creat niciodată un Challenger real pentru `xgboost_v1`).

## T0.4 — `model_champions`, campion activ per familie

Interogare exactă: `algorithm_family='xgboost_v1' AND league_scope='all' AND superseded_at IS NULL`
→ **0 rânduri**. Interogare extinsă (`algorithm_family='xgboost_v1'`, orice
stare) → **0 rânduri, niciodată** — nu a fost promovat NICIODATĂ un
Champion real în producție. Singurele rânduri din `model_champions` cu
`superseded_at IS NULL` aparțin, similar, testelor `gate_validation_test`.

**Consecință directă pentru invariantul ADR-050 ("Champion live
neschimbat")**: `oracle_engine._resolve_champion()` întoarce azi `None`
pentru orice cerere — servirea live rulează 100% Oracle (Poisson/Elo/xG),
fără nicio contribuție ML, indiferent de orice se întâmplă cu Blend. Acesta
e reperul T0 exact față de care se verifică "neschimbat" la final.

## T0.5 — `decision_feed`, decizii `pending`/`approved`

**0 rânduri** cu `status IN ('pending', 'approved')` — nicio decizie T3a
(promovare sau rollback) în așteptare, pentru nicio familie de algoritm.
Relevant pentru siguranța rulării `continuous_learning.run_cycle()`: Faza C
(execuție decizii aprobate) nu are nimic de executat azi, pentru niciun
`target_key` — rularea ciclului nu poate declanșa o promovare/rollback
neașteptat(ă), indiferent de familie.

## T0.6 — `shadow_predictions`, sumar pe (experiment_name, experiment_group)

| experiment_name | experiment_group | count | prima intrare | ultima intrare |
|---|---|---|---|---|
| flashscore_team_dna | treatment | 3 | 2026-08-03 18:10:45 | 2026-08-04 13:53:15 |

**Zero rânduri pentru `xgboost_v1` sau `blend_v1`.** Confirmă empiric
concluzia de la T0.2: `challenger_shadow_logging_enabled=true` de pe
2026-07-28 nu a produs niciodată o intrare pentru `xgboost_v1`, exact
pentru că nu a existat niciodată un Challenger activ de verificat (`get_active_challenger()`
întoarce `None`, `log_shadow_for_active_challenger()` face `return False`
imediat, fără nicio scriere). Aceeași mecanică se aplică identic pentru
`blend_v1` — o dovadă directă, nu doar teoretică, a motivului pentru care
Pasul 14 trebuie să creeze efectiv un Challenger, nu doar să activeze
flag-ul.

## Concluzie T0

| Componentă | Stare T0 |
|---|---|
| `blend_challenger_shadow_logging_enabled` | Absent din `model_config` → efectiv `False` (fallback de cod) |
| Challenger `blend_v1` activ | Nu există |
| Champion `xgboost_v1` activ (servire live) | Nu există — servire 100% Oracle |
| Decizii T3a în așteptare (orice familie) | Zero |
| `shadow_predictions` pentru `xgboost_v1`/`blend_v1` | Zero rânduri, pentru ambele |

Următorul document din serie (`PASUL14_ACTIVATION_REPORT.md`) documentează
T1→T4, cu dovadă explicită pentru fiecare tranziție de stare, per cererea
proprietarului produsului.
