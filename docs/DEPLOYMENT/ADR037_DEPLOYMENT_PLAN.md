# ADR037_DEPLOYMENT_PLAN.md — Manualul de lansare al ADR-037 (Learning Core Orchestration)

**Tip**: plan de deployment, NU e ADR, NU e document de arhitectură. Autoritatea de arhitectură rămâne `ADR-037` + `CHAMPION_GUARDIAN_IMPLEMENTATION.md` (neatinse aici). Acest document răspunde exclusiv la „ce se merge-uiește, cu ce flag-uri, în ce ordine se activează, ce se verifică, cum se revine".

**Status la redactare**: R1 (Rollback Engine) + R2 (Champion Guardian) + R3 (Orchestrare, R3.0-R3.7) — cod complet, testat (868+ teste verzi), **nemerge-uit pe `main`**. Acest document e precondiția explicită pentru merge, cerută de arhitect.

**[ACTUALIZAT 2026-07-28]** Etapa 1 (merge pe `main`) descrisă la §4 s-a produs între timp — verificat direct, `git show origin/main:learning_core/champion_guardian.py` și restul artefactelor R1-R3 sunt toate pe `main` azi. Etapele 2-5 de mai jos rămân valabile ca procedură — §3 (feature flag-urile) și §4 (Etapa 2, activare `champion_guardian_enabled`) sunt încă neexecutate, verificat live (`model_config`: ambele flag-uri `False`). Stare curentă completă: `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` §3.

---

## 1. Production Topology Audit — ce rulează azi, verificat live (R3.5)

Verificare read-only pe Supabase `Prediction`, plus inspecție directă a repo-ului (nu presupusă):

| Întrebare | Răspuns verificat |
|---|---|
| Ce branch folosește GitHub Actions? | `main` (`git remote show origin` → `HEAD branch: main`; toate workflow-urile `schedule`-based fac `actions/checkout@v4` fără `ref:` explicit → checkout implicit pe branch-ul default) |
| Ce versiune de cod e pe `main`? | `continuous_learning.py`: **trei faze (A/B/C)**, fără Faza D. Lipsesc complet: `rollback_service.py`, `champion_guardian.py`, migrările 014/015. |
| Ce versiune e pe branch-ul de lucru? | `continuous_learning.py`: **patru faze (A/B/D/C)** — tot lanțul R1+R2+R3 |
| `learning_core_enabled` (producție) | **`true`** — pre-existent, susține bucla ADR-030 (Fazele A/B/C), setat/menținut independent de această sesiune de lucru |
| Activitate Faza D în producție azi? | **Zero** — `automation_runs` conține doar `threshold_check`/`training_run` (Faza A/B); zero `champion_health_check`/`rollback_candidate` |
| Decizii de rollback existente? | **Zero** — `decision_feed` complet gol |
| Campioni activi reali? | **Zero** pentru `production_champion`/`xgboost_v1` (familiile reale); doar 4 rânduri reziduale `gate_validation_test` (fixturi izolate, R1.8) |

**Concluzie**: codul R3 nu a rulat niciodată în producție — pentru că nu există pe `main`, nu pentru că vreo gardă internă l-ar fi oprit. Zero mutație, zero efect secundar cauzate de această sesiune de lucru.

---

## 2. Ce se merge-uiește

Tot lanțul R1-R3 (branch `claude/continua-faza-1-adr5-o52jat` → `main`), într-un singur PR:

- `database/migrations/014_rollback.sql`, `database/migrations/015_champion_health.sql` (deja aplicate pe DB live, verificate — merge-ul doar sincronizează sursa canonică din repo cu starea DB deja existentă)
- `learning_core/rollback_service.py`, `learning_core/champion_guardian.py`
- `learning_core/continuous_learning.py` (extins: Faza D, Faza C extinsă, cele două flag-uri noi)
- `learning_core/rollback_service.py` (extins: `expected_predecessor_training_run_id`, `is_rollback_promoted`)
- Toate testele aferente (~44 fișiere/teste noi sau extinse)
- Documentația: ADR-037, `CHAMPION_GUARDIAN_IMPLEMENTATION.md`, `R3_IMPLEMENTATION_CHECKLIST.md`, `R1_IMPLEMENTATION_CHECKLIST.md`, acest document, `ARCHITECTURE_STATE.md`

**Efect funcțional imediat al merge-ului, cu flag-urile în starea lor implicită (`False`)**: **zero** — identic cu §1 „Concluzie", verificat explicit prin testele de gating (`test_phase_d_produces_zero_activity_when_champion_guardian_disabled`).

---

## 3. Feature flag-uri (toate în `model_config`, Supabase)

| Flag | Domeniu | Implicit | Stare azi (producție) |
|---|---|---|---|
| `learning_core_enabled` | Fazele A/B/C (ADR-030) — training, monitorizare challenger, promovare | `False` | **`True`** (pre-existent, neatins de acest plan) |
| `champion_guardian_enabled` | Faza D — Champion Guardian evaluează + persistă sănătatea | `False` | Nu există încă în `model_config` (se comportă ca `False` — cheie absentă) |
| `champion_guardian_proposals_enabled` | Propunerea T3a de rollback (necesită și `champion_guardian_enabled=True`) | `False` | idem |

**Notă load-bearing**: `champion_guardian_enabled` și `champion_guardian_proposals_enabled` sunt **complet independente** de `learning_core_enabled` — exact tiparul deja stabilit de ADR-033 (`consensus_capture_enabled`/`consensus_validation_enabled`). Fazele A/B/C nu sunt afectate în niciun fel de cele două flag-uri noi, în nicio direcție.

---

## 4. Ordinea de activare (etape separate, verificare între fiecare)

### Etapa 1 — Merge pe `main`
- **Acțiune**: merge PR, `champion_guardian_enabled=False`, `champion_guardian_proposals_enabled=False` (implicit — nu există în `model_config`, deci `False` prin `_DEFAULT_CONFIG`).
- **Efect așteptat**: **zero modificare funcțională**. Prima rulare programată de după merge (`0 6 * * *`) execută Fazele A/B/C identic cu azi; Faza D nu rulează deloc (verificat de `is_champion_guardian_enabled()`, gate la intrarea în `_process_pair`).
- **Verificare post-activare**: după prima rulare cron de pe `main`, query read-only pe `automation_runs` — confirmă `process_type='champion_health_check'` **absent** (zero rânduri noi de acest tip).
- **Criteriu de rollback**: revert simplu de commit pe `main` (codul nu a scris nimic nou în stare canonică — Faza D nu a rulat).

### Etapa 2 — `champion_guardian_enabled=true`
- **Acțiune**: `UPDATE model_config SET data = jsonb_set(data, '{champion_guardian_enabled}', 'true')` — SQL exact arătat, confirmat explicit, per disciplina `supabase-safety`.
- **Efect așteptat**: Faza D începe să ruleze — pentru fiecare `(family, league)` din Model Registry, `champion_guardian.evaluate_champion_health()` e apelat, rezultatul jurnalizat într-un `automation_run`, iar dacă există campion activ cu suficiente meciuri scorabile, `champion_health_evaluations` capătă rânduri noi. **Zero propunere de rollback** (al doilea flag încă `False`).
- **Verificare post-activare** (zilnic, câteva zile):
  - `automation_runs` capătă rânduri `champion_health_check` (T2), status `completed`/`skipped` — niciodată `failed` neașteptat.
  - `champion_health_evaluations` — dacă apar rânduri noi, `health_state` plauzibil (nu `NULL`, nu valoare în afara celor 5 cunoscute).
  - `decision_feed` — **rămâne gol** (nicio decizie `rollback_candidate`).
  - `model_champions` — **neschimbat** (Faza D e read-only pe stare canonică).
- **Criteriu de rollback**: `champion_guardian_enabled=false` — Faza D se oprește instant la următoarea rulare; niciun rând din `champion_health_evaluations` nu se șterge (append-only, e doar jurnal, inofensiv să rămână).

### Etapa 3 — Verificare (câteva zile, fără nicio schimbare de config)
- Se observă `champion_health_evaluations` acumulând ferestre reale, pe campioni reali.
- Se verifică explicit: niciun fals-pozitiv de tip `insufficient_data`→`healthy` neplauzibil, nicio eroare repetată în `automation_runs.error_detail`.
- **Nu se trece la Etapa 4 fără o revizuire explicită a datelor acumulate** — nu doar „a trecut timpul", ci „datele arată coerent".

### Etapa 4 — `champion_guardian_proposals_enabled=true`
- **Acțiune**: `UPDATE model_config SET data = jsonb_set(data, '{champion_guardian_proposals_enabled}', 'true')` — SQL exact arătat, confirmat explicit.
- **Efect așteptat**: dacă Guardian recomandă rollback (`degrading`/`critical`) pentru un campion real, Faza D propune o decizie T3a (`rollback_candidate`, `decision_feed.status='pending'`) — **vizibilă în Decision Feed, nu executată automat**. Execuția cere aprobare umană explicită (`approve_decision`).
- **Verificare post-activare**: prima propunere reală (dacă apare) — evidence conține `current_training_run_id`/`predecessor_training_run_id`/`reason` corect populate (Execution Contract, R3.2A.1); `rollback_plan` prezent (impus și la nivel de schema, `decision_feed_t3a_requires_rollback`).
- **Criteriu de rollback**: `champion_guardian_proposals_enabled=false` — nicio propunere nouă; o decizie deja `pending` rămâne vizibilă (nu dispare), dar poate fi respinsă manual (`reject_decision`) dacă nu mai e dorită.

### Etapa 5 — Discuție separată: aprobare + execuție reală
- Prima aprobare umană (`approve_decision`) + prima execuție reală (Faza C → `rollback_service.rollback_champion` → RPC 014) rămân **DEFERATE**, discutate explicit, separat, doar după ce Etapele 2-4 au rulat stabil. Nu fac parte din acest plan de activare inițială — sunt following procedura standard de aprobare T3a, deja guvernată de ADR-026 (om în buclă, obligatoriu, exceptând `emergency`).

---

## 5. Criterii generale de rollback (valabile la orice etapă)

1. **Revert de flag > revert de cod**: fiecare etapă de activare e pur o schimbare de config (`model_config`), niciodată o schimbare de cod — revenirea la etapa anterioară e instantanee, fără deploy.
2. **Append-only respectat peste tot**: niciun rând din `champion_health_evaluations`, `decision_feed`, `model_champions` nu se șterge la rollback de flag — jurnalul rămâne, doar activitatea nouă se oprește.
3. **Niciun rollback de flag nu anulează o decizie deja `approved`/`committed`** — o decizie aprobată de om rămâne vizibilă și acționabilă (`commit`/`fail_decision_commit`) indiferent de starea flag-urilor la momentul execuției Fazei C (design deliberat — un om a decis explicit, flag-ul nu-i suprimă decizia).
4. **Emergency rămâne calea manuală directă** pe `rollback_service.rollback_champion(reason="emergency", ...)`, complet în afara buclei R3/flag-urilor — disponibilă oricând, indiferent de starea `champion_guardian_enabled`.

---

## 6. Referințe

- `docs/00_GOVERNANCE/ADR-037-learning-core-rollback-and-champion-guardian.md` — arhitectura autoritară.
- `docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md` §17 — starea de implementare R3 completă.
- `docs/04_LEARNING_CORE/R3_IMPLEMENTATION_CHECKLIST.md` — istoricul execuției, reconciliat.
- `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` — sursa unică de adevăr, actualizată la fiecare etapă majoră.
