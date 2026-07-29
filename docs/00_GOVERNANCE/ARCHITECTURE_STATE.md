# ARCHITECTURE_STATE.md — Sursa unică de adevăr a stării proiectului

**Tip**: document viu, actualizat la fiecare etapă majoră (merge, activare de flag, închidere de ADR) — NU un ADR, NU o specificație înghețată. Scopul lui: să răspundă instant, fără să refacem o analiză, la întrebările „ce e implementat, ce e pe `main`, ce e doar pe branch, ce rulează live, ce e activat prin flag-uri, ce mai lipsește înainte de merge".

**Regulă de întreținere**: orice sesiune care merge-uiește cod, schimbă un flag de producție, sau închide un ADR **actualizează acest document în același commit** (sau imediat următor). Un „Architecture State Report" (verificat, la începutul fiecărei etape noi — vezi convenția de mai jos) citește de aici; dacă acest document e stale, se corectează întâi el, nu se lucrează pe baza memoriei conversației.

**Ultima verificare completă**: 2026-07-28, prin inspecție directă `git`/Supabase (nu presupusă) — vezi metodologia §5. **Corecție majoră față de versiunea anterioară (verificată 2026-07-22)**: acel document afirma că tot lanțul ADR-037 R1-R3 era „doar pe branch, nemerge-uit" — verificat direct azi (`git show origin/main:learning_core/champion_guardian.py` etc.), **merge-ul s-a produs între timp**. Secțiunile 1-5 de mai jos sunt rescrise complet pe baza stării reale de azi, nu corectate punctual.

---

## 0. Critical Path oficial curent (2026-07-29)

Prioritatea de dezvoltare a întregului proiect, declarată oficial: `M0 → M1 → M2 → M3 → M4` — provider Flashscore funcțional, până la primul Night Sync complet. Detalii, analiza de dependențe, ce s-a amânat (nu abandonat): `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md` (secțiunea "CRITICAL PATH OFICIAL" + §15). Consecință directă: niciun task nou privind Predictor/ML/Blending/Confidence nu începe înainte de M4 fără aprobare explicită separată — `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`.

---

## 1. Topologia branch-urilor (verificat direct, `git`, 2026-07-28)

| | |
|---|---|
| Branch default (GitHub Actions rulează pe el) | `main` (verificat: `git remote show origin` → `HEAD branch: main`) |
| `main` HEAD | `af77758` |
| Branch de lucru curent | `claude/sprint0-stabilizare-feedback-loop` |
| Commit-uri branch înaintea lui `main` | 37 |
| Commit-uri `main` înaintea branch-ului | 0 (branch-ul curent conține tot istoricul `main`) |
| Ultima migrare pe `main` | `029_freelf_h2h_snapshot` (include 014/015, verificat `git show origin/main:database/migrations/01{4,5}_*.sql`) |

## 2. Ce e pe `main` azi (implementat, live, nu doar cod) — ADR-037 MERGE-UIT

Tot lanțul R1 (Rollback Engine) + R2 (Champion Guardian) + R3 (Orchestrare, Faza D + Faza C extinsă) e confirmat pe `main` (`git show origin/main:<fișier>`, nu presupus):

| Componentă | Fișiere | Pe `main`? |
|---|---|---|
| Rollback Engine (R1) | `learning_core/rollback_service.py`, `database/migrations/014_rollback.sql` | ✅ DA |
| Champion Guardian (R2) | `learning_core/champion_guardian.py`, `database/migrations/015_champion_health.sql` | ✅ DA |
| Orchestrare (R3, Faza D + Faza C extinsă) | `learning_core/continuous_learning.py` (4 faze — `_phase_d_champion_health` prezentă, `is_champion_guardian_enabled()` prezentă) | ✅ DA |
| Flag-uri dedicate (R3.7) | `champion_guardian_enabled`, `champion_guardian_proposals_enabled` (cod care le citește) | ✅ DA (codul citește; valorile în `model_config` rămân `False`, vezi §4) |

Migrările 014/015 sunt aplicate pe Supabase live de mult (`champion_health_evaluations` există, schema verificată coloană-cu-coloană împotriva `record_champion_health_evaluation()` de pe `main`, 2026-07-28).

## 3. Learning Core — flag-uri, două familii independente

**ADR-030 (Fazele A/B/C — training, monitorizare challenger, promovare)**:
- `learning_core_enabled = true` — pre-existent, activ.

**ADR-037 (Faza D — Champion Guardian)**, independent de `learning_core_enabled`:
- `champion_guardian_enabled` = **`False`** (cheie absentă din `model_config`, verificat live 2026-07-28) — Faza D nu rulează încă, deși codul e pe `main`. Etapa 2 din `ADR037_DEPLOYMENT_PLAN.md` (activare monitorizare read-only) rămâne o decizie deliberată, neexecutată — nu un blocaj de cod.
- `champion_guardian_proposals_enabled` = **`False`** — neatins, Etapa 4.

**ADR-017 (Challenger Shadow Logging)**, independent de ambele de mai sus:
- `challenger_shadow_logging_enabled` = **`True`** — **activat 2026-07-28** (Sprint 3, audit complet). Verificat live: `oracle_engine._log_challenger_shadow()` scrie exclusiv în `shadow_predictions`, nu modifică predicția servită, nu atinge `model_champions`/`weights.json` (before/after Supabase confirmat: `model_champions`/`challengers`/`model_weights` neschimbate). Suita `test_challenger_shadow_logging.py` + `test_challenger_shadow_adapter.py` (15/15 verde) confirmă comportamentul.

## 4. Ce rulează efectiv în producție azi (verificat live)

| Workflow | Cron | Cod executat (de pe `main`) | Gated de |
|---|---|---|---|
| `daily.yml` | zilnic 03:00 UTC | `sync/run_daily.py` — neatins de ADR-037 | — |
| `continuous_learning.yml` | `0 6 * * *` | `continuous_learning.run_cycle()` — 4 faze (A/B/D/C), Faza D gatată separat | `learning_core_enabled` (A/B/C), `champion_guardian_enabled` (D) |
| `consensus_validation.yml` | `0 9 * * *` | `run_consensus_validation.py` | `consensus_validation_enabled` |

**Stare canonică relevantă** (verificat live, 2026-07-28): `model_champions` — 4 rânduri, toate `gate_validation_test` (fixturi R1.8, niciun campion real `production_champion`/`xgboost_v1`); `challengers` — 5 rânduri, toate `gate_validation_test`, toate în stare terminală/test, zero challenger real activ; `decision_feed` = 0; `champion_health_evaluations` = 0; `shadow_predictions` = 0 (infrastructură activată azi, în așteptare de trafic real + un challenger real activ — vezi §3); `recalibration_log` = 0 (`auto_recalibration_enabled=False`, deliberat, neatins azi).

## 5. Ce mai rămâne (nu „înainte de merge" — merge-ul s-a închis; rămâne activarea graduală)

1. ~~Merge R1-R3 pe `main`~~ — **DONE**, confirmat 2026-07-28.
2. **Activare `champion_guardian_enabled` (Etapa 2, monitorizare read-only)** — decizie deliberată, neexecutată; cod verificat safe/reversibil, în așteptarea unui Champion real de evaluat.
3. **Feedback Loop end-to-end cu date reale** (predicție → rezultat real → shadow → evaluare → promovare) — blocat azi de lipsa traficului real de utilizator (`total_predictions=37`, `closed_loop_rows=0`), nu de vreun cod nescris.
4. **Verificare proaspătă a `model_champions`/`challengers`** înainte de orice activare suplimentară de flag — Fazele A/B rulează zilnic, starea se poate schimba.

## 6. Metodologia de verificare (ce înseamnă „verificat", nu „presupus", aici)

- **Topologie branch**: `git remote show origin`, `git log --oneline branch..main` / `main..branch`, `git cat-file -e <branch>:<fișier>`.
- **Producție live**: `mcp__Supabase__execute_sql` cu `SELECT`, strict read-only, pe proiectul `Prediction` (`gtlpyxzocacaqyompkwe`).
- **Cod pe `main` vs. branch**: `git show <branch>:<fișier>`, niciodată presupus din memoria conversației.
- **Când se re-verifică**: la orice merge, la orice schimbare de flag în producție, la orice închidere de etapă/ADR, sau când a trecut suficient timp încât starea live s-ar putea fi schimbat (Fazele A/B rulează zilnic).

---

## Architecture State Report — convenția de raportare la începutul fiecărei etape

De la ADR-037/R3.5 încolo, orice etapă nouă începe cu acest raport minimal (patru linii, citite din acest document + `git`/Supabase, nu din memorie):

```
- Commit curent: <SHA>
- Ultimul punct de restaurare confirmat: <SHA> pe <branch>, HEAD local == HEAD remote
- Etapa ADR curentă: <ADR-XXX, sub-etapă>
- Etapa precedentă închisă oficial: DA/NU
```
