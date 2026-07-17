# P7.1 — Implementation Plan: `shot_dominance`

**Status**: Plan operațional — zero cod scris încă. Aprobat arhitectural de Chief Architect (2026-07-15), condiționat de acest document. Referințe: `P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md` (design), `P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md` (verdict GO). Nu repet raționamentul de acolo — doar pașii de execuție.

**Disciplină de execuție, ordinea exactă**: Implementation → Tests → Temporary Workflow → Ablation → ADR Accepted/Rejected. Fiecare pas începe DOAR după ce cel anterior e verde. **P7.2 și restul familiei „Structural Match Statistics" NU se ating în această rundă.**

---

## 1. Fișiere modificate (exact, fără altele)

| Fișier | Ce se schimbă | Când |
|---|---|---|
| `sync/backfill_features.py` | `ShotCountTracker` (clasă nouă), `FEATURE_COLUMNS` +2 intrări, `fetch_all_matches()` SELECT +2 coloane brute, `run_backfill()` — instanțiere tracker + citire/scriere/`process_match()` | Implementation |
| `tests/test_shot_count_tracker.py` (nou) | Teste unitare `ShotCountTracker` | Tests |
| `tests/test_backfill_features.py` | Teste de wiring — gating pe cele 2 coloane noi (precedent: testele deja existente pentru corner/foul) | Tests |
| — | Migrare Supabase (`apply_migration`, arătată explicit înainte de rulare — `supabase-safety`) | Implementation, înainte de backfill |
| — (script temporar, șters după) | Workflow temporar de ablație | Temporary Workflow |
| `ml_predictor.py` | `FEATURE_COLUMNS` +1 (`shot_dominance`), `_fetch_training_dataframe()` — derivare | **DOAR dacă Accepted** |
| `oracle_engine.py` | `TeamProfile.avg_shots`, `_real_match_events()` +agregare shots brute, `_build_profile()` +populare, `_build_ml_features()` +derivare `shot_dominance` | **DOAR dacă Accepted** |
| `explainability.py` | `ml_detail["shot_dominance"]`, lângă `corner_dominance`/`foul_diff` (linia ~245) | **DOAR dacă Accepted** |
| `tests/test_ml_predictor_no_imputation.py` | Extins cu `shot_dominance` (precedent: `corner_dominance`/`foul_diff` deja acolo) | **DOAR dacă Accepted** |
| `docs/00_GOVERNANCE/ADR-021-shot-dominance-ml-feature.md` (nou) | ADR final, Accepted sau Rejected | ADR |
| `docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md` (nou) | Raport de ablație, exact formatul `FOULS_DOMINANCE_ABLATION_2026-07-14.md` | Ablation |
| `docs/03_ENGINE/ML_EVOLUTION_ROADMAP.md` | Status P7.1 → Accepted/Rejected, câmpurile Sumar+detaliu actualizate | ADR |

---

## 2. Coloane noi și migrare

```sql
ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS home_shot_avg_recent numeric,
  ADD COLUMN IF NOT EXISTS away_shot_avg_recent numeric;
```

- Aditivă, `IF NOT EXISTS` (idempotentă), nullable, zero impact asupra rândurilor existente sau a citirilor curente.
- Aplicată prin `mcp__Supabase__apply_migration`, SQL-ul exact arătat utilizatorului înainte de rulare (`supabase-safety`, obligatoriu).
- **Nu se atinge `home_shots`/`away_shots`** (deja există, ADR-011) — doar cele 2 coloane derivate, medie glisantă, populate ulterior de `ShotCountTracker` prin `run_backfill()` (același script, nu unul nou).
- Fără backfill imediat de date — populare prin rularea normală a `sync/backfill_features.py --dry-run` (verificare) apoi fără `--dry-run` (scriere), exact fluxul existent pentru corner/foul.

---

## 3. Clase și funcții noi

### `sync/backfill_features.py`

```python
class ShotCountTracker:
    """Medie glisantă reală de șuturi TOTALE (nu pe poartă — vezi ShotsTracker,
    care rămâne neatins) per echipă. Identică ca disciplină cu FoulsTracker."""
    def __init__(self, window: int = FORM_WINDOW): ...
    def get_avg_shots(self, team: str) -> float | None: ...
    def process_match(self, home: str, away: str,
                       home_shots: float | None, away_shots: float | None) -> None: ...
```

Plasare: imediat după `FoulsTracker` (lângă `ShotsTracker`/`CornerCardTracker`), cod identic structural cu `FoulsTracker`, doar redenumit.

**Comportamentul pentru istoricul incomplet este intenționat identic cu `CornerCardTracker` și `FoulsTracker`: media se calculează pe toate valorile disponibile (1...`FORM_WINDOW`), fără a impune minimum 10 meciuri.** Un istoric de 3 meciuri produce o medie pe 3, nu `None` și nu o valoare aproximată — `None` apare STRICT când istoricul e gol (0 meciuri cunoscute). Fereastra „completă" (10/10) nu e o precondiție de calcul, doar o cifră raportată separat în P7.1A (§1) ca informație suplimentară despre stabilitatea mediei.

Modificări în funcțiile existente (nu clase noi):
- `FEATURE_COLUMNS` (linia 87): +`"home_shot_avg_recent", "away_shot_avg_recent"`.
- `fetch_all_matches()` (linia ~133): SELECT +`"home_shots,away_shots"` (azi lipsesc — doar `home_shots_on_target`/`away_shots_on_target` sunt citite).
- `run_backfill()`: +`shot_count_tracker = ShotCountTracker()` (lângă `fouls_tracker`); +citire `home_shot_avg = shot_count_tracker.get_avg_shots(home)` / `away_shot_avg = ...` înainte de meci; +intrare în `computed`; +`shot_count_tracker.process_match(home, away, match.get("home_shots"), match.get("away_shots"))` după.

### `ml_predictor.py` (doar dacă Accepted)

```python
df["shot_dominance"] = df["home_shot_avg_recent"] - df["away_shot_avg_recent"]
```
în `_fetch_training_dataframe()`, cu gardă `if ... in df.columns else np.nan` (identic tipar cu `corner_dominance`).

### `oracle_engine.py` (doar dacă Accepted)

- `TeamProfile.avg_shots: float | None = None`.
- `_real_match_events()`: +agregare `home_shots`/`away_shots` brute (analog `avg_corners`/`avg_fouls`), returnate în același `dict`.
- `_build_profile()`: +`avg_shots=round(events["avg_shots"], 2) if ... else None`.
- `_build_ml_features()`: +`"shot_dominance": (home_p.avg_shots - away_p.avg_shots) if ambele not None else None`.

**Notă operațională**: calea live folosește `_real_match_events()` (recalcul din ultimele `last_n` meciuri brute), NU coloanele `home_shot_avg_recent`/`away_shot_avg_recent` din backfill — exact duplicarea deja existentă și acceptată pentru `corner_dominance`/`foul_diff` (semnalată, nu nouă, nu se rezolvă în acest plan).

---

## 4. Teste

### Unitare (Tests, înainte de orice ablație)

`tests/test_shot_count_tracker.py` (nou, 5 teste, oglindă `test_fouls_tracker.py`):
1. `test_no_history_returns_none_not_approximated`
2. `test_average_computed_only_from_real_values`
3. `test_none_values_not_recorded`
4. `test_pre_match_value_never_includes_current_match_zero_leakage`
5. `test_window_limits_history_like_form_tracker`

`tests/test_backfill_features.py` (extins): gating per-coloană pentru `home_shot_avg_recent`/`away_shot_avg_recent` — un rând deja populat nu e niciodată suprascris; un rând fără istoric real nu primește 0.

### Integrare (doar dacă Accepted)

`tests/test_ml_predictor_no_imputation.py` (extins): `shot_dominance` calculat corect din cele 2 coloane brute, `NaN` quand lipsesc, nu imputat înainte de walk-forward split (exact testele deja existente pentru `corner_dominance`/`foul_diff`, duplicate pentru noul feature).

**Poartă obligatorie**: `pytest tests/ -q` verde (380+ teste, fără dependință de rețea) după fiecare din cele două seturi de mai sus, înainte de a trece la pasul următor.

---

## 5. Workflow temporar pentru ablație

- Fișier: `.github/workflows/_shot_dominance_p7_1_temp.yml`, `workflow_dispatch`, exact pattern P1/P2/P3 (`_optuna_p1_1_temp.yml`, `_calibration_p2_temp.yml`, `_p3_elo_mov_temp.yml` — toate șterse deja).
- Script: `scripts/_shot_dominance_ablation_p7_1_temp.py`:
  - Citește `match_history` (5 ligi, `actual_result` cunoscut) — INCLUSIV cele 2 coloane noi, deja populate de backfill.
  - Baseline: cele 13 `FEATURE_COLUMNS` de producție curente. Extins: +`shot_dominance`.
  - `MLPredictorEngine._walk_forward_validate()`, 5 folduri, `random_state=42`, aceiași hiperparametri XGBoost — metodologie identică, reutilizată, nu reinventată.
  - Raportează Accuracy/Log Loss/Brier per fold + medie, pentru ambele seturi.
- **Zero scriere** — nu atinge `match_history`, `ml_model_status`, niciun tabel de producție. Rulează complet izolat de `ml_predictor.py`-ul de producție (import doar pentru `_walk_forward_validate`, care e pur/fără efecte secundare).
- Șters (workflow + script) imediat după ce rezultatul e documentat în `SHOT_DOMINANCE_ABLATION_2026-07-15.md` — indiferent de verdict, exact ca la P1/P2/P3.

---

## 6. Plan de rollback

| Etapă | Ce se poate întâmpla greșit | Rollback |
|---|---|---|
| Migrare (2 coloane noi) | Migrare eșuată/parțială | Aditivă, `IF NOT EXISTS` — sigură de reluat; în ultimă instanță `ALTER TABLE match_history DROP COLUMN home_shot_avg_recent, DROP COLUMN away_shot_avg_recent` (arătat explicit înainte de rulare, ca orice scriere Supabase) |
| Backfill (`run_backfill()`) | Populare greșită a celor 2 coloane | Gating per-coloană existent (Regula #13, „Protecția Writer-ilor") — nu suprascrie niciodată o valoare deja scrisă; re-rulare cu `--dry-run` întâi, ca la corner/foul. Coloanele sunt 100% informative până la pasul 7 — zero impact asupra predicțiilor live sau modelului de producție indiferent de conținutul lor |
| Cod (`ShotCountTracker`, wiring) | Bug descoperit după merge | `git revert` pe commit-ul de Implementation — sigur, pentru că nimic din calea de producție (`ml_predictor.FEATURE_COLUMNS`, `oracle_engine._build_ml_features`) nu citește încă noile coloane înainte de pasul „DOAR dacă Accepted" |
| Workflow/script temporar | — | Șters necondiționat după raportare, indiferent de verdict — nu rămâne în `main`/branch |
| Ablație → **Rejected** | — | Nu se ating `ml_predictor.py`/`oracle_engine.py`/`explainability.py`. Cele 2 coloane RĂMÂN în schemă (informative, cost zero — precedent: `home_ht_goals`/`away_ht_goals` au rămas după respingerea HT Score) — nu se face DROP automat, doar dacă utilizatorul cere explicit curățare |
| Ablație → **Accepted**, dar regresie descoperită ulterior în producție | Model retrained cu noul feature performează prost în practică | `git revert` pe commit-ul „DOAR dacă Accepted" — elimină `shot_dominance` din `FEATURE_COLUMNS`/`_build_ml_features`/`explainability.py`; următoarea re-antrenare revine automat la cele 13 feature-uri; coloanele brute rămân, fără efect |

Niciun pas din acest plan nu poate întrerupe predicțiile live existente — toată infrastructura nouă (tracker, coloane, workflow) e inertă pentru producție până la pasul explicit „DOAR dacă Accepted".

---

## 7. Criterii de Done

- [ ] Migrare aplicată (2 coloane, confirmate prin `list_tables`).
- [ ] `ShotCountTracker` implementat, wiring complet în `run_backfill()`.
- [ ] Teste unitare noi verzi (`test_shot_count_tracker.py`, extensia `test_backfill_features.py`).
- [ ] `pytest tests/ -q` 100% verde (fără regresii).
- [ ] Backfill rulat pe producție (`--dry-run` întâi, apoi real) — coverage confirmat ≥90% (consistent cu P7.1A, 92,7% așteptat).
- [ ] **Verificare de consistență post-backfill** (sanity check, SQL read-only): niciun rând cu `home_shot_avg_recent`/`away_shot_avg_recent` populat nu are valoare negativă, `NaN` sau infinită (`WHERE home_shot_avg_recent < 0 OR home_shot_avg_recent = 'NaN' ...`); numărul de rânduri populate e în linie cu auditul P7.1A (~92,7%, ±o marjă mică justificată de eventuale meciuri noi intrate în `match_history` între audit și backfill). Orice abatere semnificativă de la 92,7% sau orice valoare negativă/NaN/infinită oprește fluxul înainte de pasul de ablație — semn de bug în `ShotCountTracker`, nu de acceptat tacit.
- [ ] Workflow temporar de ablație rulat, rezultat documentat onest în `SHOT_DOMINANCE_ABLATION_2026-07-15.md` (metrici exacte, nu rotunjite optimist).
- [ ] Workflow + script temporar șterse (ambele branch-uri, dacă rulat și pe `main`).
- [ ] ADR-021 scris — **Accepted** (cu implementarea din §1/§3 marcată „DOAR dacă Accepted" aplicată complet + testele de integrare adăugate) SAU **Rejected** (motiv consemnat, coloane brute păstrate, nicio schimbare la `FEATURE_COLUMNS`).
- [ ] `ML_EVOLUTION_ROADMAP.md` actualizat cu verdictul final (Sumar + secțiunea P7.1 detaliată).
- [ ] Confirmare explicită: **P7.2 rămâne neînceput** — niciun cod, niciun tracker, nicio coloană pentru `sot_dominance` sau alt feature din familie în această rundă.

Gata de aprobare pentru începerea pasului 1 (Implementation).
