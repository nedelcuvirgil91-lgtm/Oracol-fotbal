# ARCHITECTURE_STATE.md — Sursa unică de adevăr a stării proiectului

**Tip**: document viu, actualizat la fiecare etapă majoră (merge, activare de flag, închidere de ADR) — NU un ADR, NU o specificație înghețată. Scopul lui: să răspundă instant, fără să refacem o analiză, la întrebările „ce e implementat, ce e pe `main`, ce e doar pe branch, ce rulează live, ce e activat prin flag-uri, ce mai lipsește înainte de merge".

**Regulă de întreținere**: orice sesiune care merge-uiește cod, schimbă un flag de producție, sau închide un ADR **actualizează acest document în același commit** (sau imediat următor). Un „Architecture State Report" (verificat, la începutul fiecărei etape noi — vezi convenția de mai jos) citește de aici; dacă acest document e stale, se corectează întâi el, nu se lucrează pe baza memoriei conversației.

**Ultima verificare completă**: 2026-07-22, prin inspecție directă `git`/Supabase (nu presupusă) — vezi metodologia §5.

---

## 1. Topologia branch-urilor (verificat direct, `git`)

| | |
|---|---|
| Branch default (GitHub Actions rulează pe el) | `main` (verificat: `git remote show origin` → `HEAD branch: main`) |
| Branch de lucru curent | `claude/continua-faza-1-adr5-o52jat` |
| Commit-uri branch înaintea lui `main` | 22 (tot lanțul ADR-037 R1-R3, inclusiv R3.6/R3.7) |
| Commit-uri `main` înaintea branch-ului | 2 (`b1baff0` — închiderea ADR-035 D4, `e17633d` — fix UI #39; ambele neînrudite cu ADR-037; merge verificat curat, fără conflict — `git merge-tree`) |
| Ultima migrare pe `main` | `013_shadow_provider_recommendations.sql` |
| Ultima migrare pe branch | `015_champion_health.sql` (014 + 015, doar pe branch) |

## 2. Ce e pe `main` azi (implementat, live, nu doar cod)

Toate ADR-urile **până la ADR-036 inclusiv** au artefacte de cod pe `main` (verificat prin `git cat-file -e main:<fișier>` pentru fișierele-cheie ale fiecăruia — `consensus_validation.py`, `consensus_capture.py`, `shadow_config.py`, `champion_comparison.py`, `challenger_manager.py`, `promotion_service.py`, etc., toate prezente). Detalii per-ADR nu sunt reluate aici (ar duplica FROZEN_REGISTRY.md / changelog-urile individuale) — acest document tratează explicit doar granița relevantă azi: **ADR-037**.

## 3. Ce e DOAR pe branch (ADR-037 — Learning Core Rollback + Champion Guardian + Orchestrare)

| Componentă | Fișiere | Pe `main`? |
|---|---|---|
| Rollback Engine (R1) | `learning_core/rollback_service.py`, `database/migrations/014_rollback.sql` | ❌ NU |
| Champion Guardian (R2) | `learning_core/champion_guardian.py`, `database/migrations/015_champion_health.sql` | ❌ NU |
| Orchestrare (R3, Faza D + Faza C extinsă) | `learning_core/continuous_learning.py` (4 faze, vs. 3 pe `main`) | ❌ NU |
| Flag-uri dedicate (R3.7) | `champion_guardian_enabled`, `champion_guardian_proposals_enabled` | ❌ NU (nici măcar cheile în `model_config`) |

**Migrările 014/015 SUNT deja aplicate pe Supabase live** (prin SQL Editor, disciplina `supabase-safety` — vezi `CHANGELOG.md` R1/R2), deși fișierele nu sunt pe `main`. Sursa canonică rămâne fișierul comitat pe branch, până la merge.

## 4. Ce rulează efectiv în producție azi (verificat live, R3.5 — Production Topology Audit)

| Workflow | Cron | Cod executat (de pe `main`) | Gated de |
|---|---|---|---|
| `daily.yml` | zilnic | `sync/run_daily.py` — neatins de ADR-037 | — |
| `continuous_learning.yml` | `0 6 * * *` | `continuous_learning.run_cycle()` — **3 faze (A/B/C)**, fără Faza D | `learning_core_enabled` |
| `consensus_validation.yml` | `0 9 * * *` | `run_consensus_validation.py` | `consensus_validation_enabled` |

**Flag-uri active în `model_config` (Supabase `Prediction`), verificat live**:
- `learning_core_enabled = true` — pre-existent, susține Fazele A/B/C (ADR-030). **Neînrudit cu ADR-037.**
- `consensus_capture_enabled = true`, `selection_engine_shadow_enabled = true` — neînrudite cu ADR-037.
- `champion_guardian_enabled` / `champion_guardian_proposals_enabled` — **nu există încă** în `model_config` (cheile apar doar după primul merge + eventuală activare explicită; până atunci, `False` prin default de cod).

**Stare canonică relevantă** (verificat live, R3.5): zero campion activ real (`model_champions`) pentru `production_champion`/`xgboost_v1`; zero challenger activ pentru ele; zero decizie în `decision_feed`; `champion_health_evaluations` = 0 rânduri.

## 5. Ce lipsește înainte de merge (ADR-037)

1. ~~Feature flag dedicat pentru Faza D~~ — **DONE** (R3.7, `champion_guardian_enabled` + `champion_guardian_proposals_enabled`).
2. ~~Documentație reconciliată~~ — **DONE** (`R3_IMPLEMENTATION_CHECKLIST.md`, `CHAMPION_GUARDIAN_IMPLEMENTATION.md` §17, `CHANGELOG.md`).
3. ~~Plan de deployment~~ — **DONE** (`docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md`).
4. **Acest document, prezent la commit** — DONE (chiar acesta).
5. **Aprobare explicită de merge** — ⏳ ÎN AȘTEPTARE, aparține arhitectului.
6. **Verificare proaspătă a `model_champions`/`challengers`** la momentul efectiv al merge-ului (starea din §4 se poate schimba între timp — Fazele A/B rulează zilnic) — de făcut chiar înainte de merge, nu presupusă din acest document dacă a trecut timp.

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
