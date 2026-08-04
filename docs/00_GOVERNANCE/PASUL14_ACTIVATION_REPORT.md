# Pasul 14 — Raport de activare Shadow Blend (T1 → T4)

Continuă `docs/00_GOVERNANCE/PASUL14_BASELINE.md` (T0). Documentează, cu
dovadă directă pentru fiecare tranziție de stare (nu doar rezultatul
final), activarea reală a shadow logging-ului pentru Challenger-ul Blend
în producție. Toate acțiunile de scriere au fost executate live, pe
proiectul Supabase `Prediction`, prin `mcp__Supabase__execute_sql` (SQL
arătat explicit înainte de execuție) și GitHub Actions (secretele reale
de producție) — niciodată prin aproximare sau simulare.

**Obiectiv respectat, per cerințele explicite ale proprietarului
produsului**: (1) activare controlată a flag-ului; (2) verificare că
mecanismul shadow chiar loghează; (3) validare că Champion-ul live rămâne
neschimbat; (4) validare că `shadow_predictions` acumulează intrări reale
pentru `blend_v1`; (5) documentare completă; (6) NU s-a evaluat performanța
statistică și NU s-a propus promovarea Blend — rămâne exclusiv scopul
Pasului 14, viitor, „Evaluare shadow → decizie de promovare".

## T1 — Flag activat

SQL executat (merge JSONB, păstrează toate celelalte chei neatinse):

```sql
UPDATE model_config
SET data = data || '{"blend_challenger_shadow_logging_enabled": true}'::jsonb,
    updated_at = now()
WHERE id = 1
RETURNING jsonb_pretty(data), updated_at;
```

Rezultat confirmat live: `blend_challenger_shadow_logging_enabled: true`
adăugat, toate cele 20 de chei preexistente (`learning_core_enabled`,
`challenger_shadow_logging_enabled`, etc.) neatinse. `updated_at`:
2026-08-04 14:31:09 UTC.

**Verificat din nou la finalul secvenței** (după T2/T3/T4): flag-ul rămâne
`true` — **nu a fost coborât**, per instrucțiunea explicită a proprietarului
produsului („nu m-ai coborî flag-ul... îl las: `blend_challenger_shadow_logging_enabled = true`,
pentru că shadow e read-only, costul e aproape zero, nu afectează
Champion").

## T2 — Prima antrenare `blend_v1`

Declanșată prin `continuous_learning.yml` (`workflow_dispatch`, ref `main`,
commit `c28fd87`) — GitHub Actions run
[`30920552509`](https://github.com/nedelcuvirgil91-lgtm/Oracol-fotbal/actions/runs/30920552509),
`conclusion: success`, 2026-08-04 14:45:05 → 14:46:47 UTC.

Tranziții complete, verificate în `automation_runs` (`target_key='blend_v1|all'`):

| process_type | status | detaliu |
|---|---|---|
| `threshold_check` | completed | „prima antrenare — 1000 meciuri disponibile (prag 30)", decizie: `train` |
| `training_run` | completed | `samples_used=49983`, `training_run_id=8ac89c70-8727-459f-aa42-08a2edd16431` |
| `artifact_persistence` | completed | `result=SUCCESS`, `artifact_path=8ac89c70-8727-459f-aa42-08a2edd16431.json` |
| `calibration_persistence` | completed | `result=SUCCESS`, `temperature=1.2199539470179952` |

Confirmat și în `training_runs`: `algorithm_name=blend_v1`, `league_scope=all`,
`status=trained`, `samples_used=49983`,
`walk_forward_metrics={"accuracy": 0.4828, "log_loss": 1.0329}`.

## T3 — Challenger `blend_v1` creat

Confirmat live în `challengers`:

```
training_run_id: 8ac89c70-8727-459f-aa42-08a2edd16431
algorithm_family: blend_v1
league_scope: all
state: EVALUATING
created_at: 2026-08-04 14:46:39
updated_at: 2026-08-04 14:46:40
```

Tranziție completă `CREATED → WAITING → EVALUATING` (confirmată de codul
`continuous_learning._phase_b_train_new()`, executat prin pipeline-ul
generic, neatins de Pasul 13 — vezi ADR-050 §4/§7.1). `EVALUATING` e stare
non-terminală → `get_active_challenger("blend_v1", "all")` îl găsește,
exact precondiția necesară pentru T4.

## T4 — Prima dovadă reală: `shadow_predictions` acumulează pentru `blend_v1`

Declanșat prin `scripts/shadow_probe.py` (`--confirm`), via
`.github/workflows/shadow_probe.yml` (`workflow_dispatch`, ref `main`,
commit `f61c946`) — GitHub Actions run
[`30920929435`](https://github.com/nedelcuvirgil91-lgtm/Oracol-fotbal/actions/runs/30920929435),
`conclusion: success`, 2026-08-04 14:49:30 → 14:51:55 UTC. 3 meciuri reale
probate, prin `oracle_engine.evaluate_match()` (calea reală, neschimbată).

| fixture_id | Meci | Ligă | Oracle (control) | Blend (treatment) |
|---|---|---|---|---|
| `shadow-probe-d7954f76` | Farul Constanța vs Metaloglobus Bucharest | Romania SuperLiga | H=0.4058 D=0.2679 A=0.3263 | H=0.4300 D=0.2658 A=0.3042 |
| `shadow-probe-c6602e41` | Bologna vs Inter Milan | Serie A | H=0.2806 D=0.2235 A=0.4958 | H=0.2777 D=0.2334 A=0.4889 |
| `shadow-probe-d2b0d9e2` | Benfica (POR) vs St. Gallen (SUI) | Europa League | H=0.3409 D=0.3700 A=0.2891 | H=0.3593 D=0.3587 A=0.2820 |

Verificat direct în `shadow_predictions` (SQL, nu doar log-ul job-ului):

```sql
SELECT fixture_id, home_team, away_team, league, experiment_name,
       experiment_group, prob_home, prob_draw, prob_away, created_at
FROM shadow_predictions
WHERE fixture_id LIKE 'shadow-probe-%' AND experiment_name = 'blend_v1'
ORDER BY fixture_id, experiment_group;
```

→ **6 rânduri** (3 fixture-uri × `treatment`+`control`), toate confirmate,
probabilitățile `control` identice cu predicția Oracle raportată de
`evaluate_match()` (perechea necesară pentru comparația paired din
`shadow_testing.evaluate_experiment()`, ADR-017/ADR-050). Coloana
`experiment_group='treatment'` reprezintă blend-ul Oracle+ML calculat de
`learning_core.blend_challenger_shadow.predict_with_blend_challenger()`.

Confirmat și în log-ul job-ului (per meci, imediat după `evaluate_match()`):
`shadow_predictions pentru acest fixture_id: 3 rând(uri)` (al treilea rând,
`flashscore_team_dna/treatment`, e un experiment shadow pre-existent,
neînrudit, declanșat identic de `evaluate_match()` — confirmă că proba
exercită corect TOATE mecanismele shadow active, generic, exact cum e
proiectat tool-ul).

## Invariant ADR-050 §7.1 — Champion live neschimbat (confirmat, nu presupus)

Verificat de tool-ul însuși, direct în log:
```
Champion activ (xgboost_v1/all) înainte: None
Champion activ (xgboost_v1/all) după:     None
Invariant 'Champion neschimbat': OK
```

Verificat independent prin SQL (după toată secvența T1-T4):
```sql
SELECT count(*) FROM model_champions
WHERE algorithm_family='xgboost_v1' AND league_scope='all' AND superseded_at IS NULL;
-- → 0
```

Identic cu T0 (`docs/00_GOVERNANCE/PASUL14_BASELINE.md`, §T0.4) — nu a
existat NICIODATĂ un Champion `xgboost_v1` promovat în producție, nici
înainte, nici după Pasul 14. Servirea live rulează 100% Oracle, complet
neafectată de existența Challenger-ului `blend_v1` sau de shadow logging-ul
lui — consistent cu faptul că `oracle_engine._resolve_champion()` (cod
neatins, `git diff` gol pe Pasul 13/14) nu citește niciodată
`challengers`/`model_config.blend_challenger_shadow_logging_enabled`.

## Stare finală (T4, confirmată live)

| Componentă | T0 | T4 |
|---|---|---|
| `blend_challenger_shadow_logging_enabled` | absent (efectiv `False`) | **`true`**, explicit, permanent |
| Challenger `blend_v1` activ | nu exista | **`EVALUATING`**, `training_run_id=8ac89c70…` |
| `shadow_predictions` pentru `blend_v1` | 0 rânduri | **6 rânduri** (probă controlată) + acumulare organică de acum înainte, din trafic real Streamlit |
| Champion `xgboost_v1` activ (servire live) | 0 (None) | **0 (None), neschimbat** |
| Decizii T3a în așteptare | 0 | 0 (neatins de Pasul 14) |

## Ce urmează (explicit în afara scopului acestui pas)

- **Evaluarea statistică** a Challenger-ului `blend_v1` (verdict
  `candidate_for_promotion`/`rejected`) — necesită acumulare organică de
  trafic real (min. 200 meciuri evaluate, `challenger_evaluation.py`,
  `MIN_MATCHES_FOR_EVALUATION`) — Pasul 14 viitor ("Evaluare shadow →
  decizie de promovare"), NU acest document.
- **Nicio decizie de promovare** nu a fost luată sau propusă aici.
- Shadow Probe (`scripts/shadow_probe.py`) rămâne disponibil permanent
  pentru orice verificare operațională viitoare — vezi
  `docs/00_GOVERNANCE/SHADOW_PROBE_OPERATIONAL_GUIDE.md`.
