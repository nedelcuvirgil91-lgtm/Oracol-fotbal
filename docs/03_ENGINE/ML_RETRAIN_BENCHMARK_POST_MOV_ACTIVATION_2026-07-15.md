# Reantrenare ML + Benchmark — post-activare V2_damped

**Status**: Reantrenare reală, executată pe calea oficială de producție (`MLPredictorEngine.train()`, `ml_predictor.py`), pe `match_history` deja actualizat cu formula MOV V2_damped (ADR-022). Ultimul pas cerut explicit înainte de orice experiment nou (P7.2, `finishing_efficiency`, `defensive_efficiency`) — izolează efectul schimbării ELO, fără nicio altă variabilă nouă introdusă.

**Execuție**: GitHub Actions, `backfill.yml` (`retrain_ml=true`, `dry_run=false`), run `#29450931199`, 2026-07-15, succes, ~2min41s. Reutilizare exclusivă a infrastructurii existente (pasul „Retrain ML after backfill", deja prezent în workflow, folosit anterior doar cu `retrain_ml=false` pe tot parcursul migrărilor din această sesiune) — zero cod nou.

---

## 1. Rezultatul reantrenării oficiale

```
ML Status: trained
Samples:   53409
Accuracy:  0.4981
Log Loss:  1.0124
Message:   Model antrenat pe 53409 meciuri. Validare walk-forward: 5 folds, Brier mediu=0.6053.
```

Modelul final de producție s-a antrenat pe **tot istoricul disponibil** (53.409 meciuri, exact cele afectate de activarea V2_damped) — walk-forward-ul (5 folduri, expanding window) rămâne strict pentru evaluare onestă, neschimbat față de metodologia oficială deja folosită la P1/P2/P3/ADR-020.

Pasul „Run backfill" precedent (același run) a confirmat, din nou, stabilitatea stării: 53.409 meciuri încărcate, 0 procesate, 0 erori — toate cele 6 coloane ELO/rating rămân complete (niciun rescris, cum era de așteptat, Writer Protection). Cele 44.803 rânduri raportate ca „incomplete din 18 coloane" se referă la coloanele opționale (`*_avg_recent` de cornere/cartonașe/faulturi/șuturi, `None` legitim pe meciuri fără statistici reale — Regula #8), neatinse de această migrare, fenomen deja documentat separat.

---

## 2. Comparație cu benchmark-ul oficial ADR-020 (context istoric, NU o comparație validă de „câștig”)

| | ADR-020 (benchmark oficial) | Reantrenare 2026-07-15 |
|---|---:|---:|
| Accuracy | 0,4868 | 0,4981 |
| Log Loss | 1,0253 | 1,0124 |
| Brier | 0,6145 | 0,6053 |
| `FEATURE_COLUMNS` | 13 (fără `shot_dominance`) | 14 (cu `shot_dominance`, P7.1/ADR-021) |
| Identitate echipe | fragmentată (înainte de P3.5) | consolidată (P3.5 Faza 3) |
| Formula ELO | categorială (H/D/A) | MOV V2_damped (ADR-022) |

**Avertisment metodologic explicit**: diferența (+1,13pp Accuracy, −1,26% Log Loss, −1,50% Brier) **nu izolează efectul V2_damped** — între ADR-020 și acum s-au schimbat simultan 3 lucruri (P7.1 `shot_dominance`, P3.5 consolidare identitate, ADR-022 formula MOV). Cifrele sunt raportate ca reper istoric, nu ca dovadă de câștig atribuibilă unei singure cauze.

---

## 3. Comparație cu verificarea de convergență (`P3_MOV_ACTIVATION_POST_MIGRATION_REPORT_2026-07-15.md` §4) — comparație validă, izolată

Aceeași bază de date exactă (post-activare V2_damped), aceiași hiperparametri de producție, aceeași împărțire walk-forward — singura diferență e calea de execuție (script temporar read-only vs. `MLPredictorEngine.train()` oficial).

| | Verificare convergență | Reantrenare oficială |
|---|---:|---:|
| Accuracy | 0,4981 | 0,4981 |
| Log Loss | 1,0124 | 1,0124 |
| Brier | 0,6053 | 0,6053 |

**Potrivire exactă, nu doar apropiată** — confirmă, fără ambiguitate, că cele două căi de calcul (evaluare independentă vs. calea oficială de antrenare) produc exact același rezultat pe exact aceleași date. Nu e o coincidență: e aceeași metodologie, aceiași hiperparametri (`random_state=42`), aceeași sursă de date — exact ce ar trebui să se întâmple dacă totul e corect.

---

## 4. Scrieri efectuate (confirmate, informative, fără promovare automată)

`MLPredictorEngine.train()` a scris, prin calea oficială deja guvernată de proiect:

1. **`ml_model_status`** (UPDATE, rând unic `id=1`) — `trained_at`, `samples_used=53409`, `accuracy=0.4981`, `log_loss=1.0124`, `feature_names` (14 coloane), `model_version`, `notes` (fold-uri + Brier). Status curent pentru dashboard/afișare.
2. **`training_runs`** (INSERT, append-only, ADR-015) — înregistrare istorică a acestei rulări, cu `walk_forward_metrics` complete.
3. **`champion_comparison.compare_to_champion(...)`** — apelat, **strict informativ** (verificat direct în cod, `ml_predictor._record_training_run()`: *"Nu decide, nu promovează, nu întrerupe niciodată train()"*). Niciun pointer de campion activ nu a fost schimbat — Promotion Engine rămâne Not Implemented (CLAUDE.md), exact cum era înainte de această rulare.

**Niciun artefact de model persistat** (fără joblib/pickle salvat pe disc sau storage) — modelul XGBoost antrenat trăiește doar în procesul care a rulat `train()`; live serving (`oracle_engine.py`) rămâne complet neatins de această rulare, la fel ca la toate migrările precedente din această sesiune.

---

## 5. Concluzie

**Milestone-ul P3 → P3.5 → activare V2_damped → benchmark ML e complet închis.** Toate verificările sunt documentate în repo și reflectă execuția reală:

- `ADR-022-elo-margin-of-victory-v2-damped.md` — decizia formalizată.
- `P3_MOV_ACTIVATION_DESIGN_REVIEW_MIGRATION_PLAN_2026-07-15.md` — planul aprobat.
- `P3_MOV_ACTIVATION_POST_MIGRATION_REPORT_2026-07-15.md` — execuția pe producție (4 rulări, verificată, convergentă).
- **Acest document** — benchmark oficial de producție, pe calea reală de antrenare, cu rezultat identic verificării independente.

Efectul schimbării ELO e acum izolat și documentat **înainte** de orice variabilă nouă. Următorul pas logic (P7.2, `finishing_efficiency`, `defensive_efficiency`, sau orice alt experiment din roadmap) rămâne o decizie separată, neinceput automat aici.
