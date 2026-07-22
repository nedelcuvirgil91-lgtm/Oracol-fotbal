# R3_IMPLEMENTATION_CHECKLIST.md — Orchestration Layer (Stage R3)

**Tip**: checklist de execuție. NU e ADR, NU e document de arhitectură. Autoritatea de design rămâne `ADR-037` + `CHAMPION_GUARDIAN_IMPLEMENTATION.md` (neatinse de acest document). Oglindește `R1_IMPLEMENTATION_CHECKLIST.md`.

**Notă de reconciliere (R3.6)**: granularitatea reală de execuție a divergat de planul inițial de mai jos, în bine — un Execution Readiness Review (cerut înainte de a scrie cod pentru execuția rollback-ului) a găsit un gol real de idempotență, tratat ca task nou (**R3.2A.1**), iar auditul live R3.5 a găsit o discrepanță de topologie de producție, tratată tot ca task nou (**R3.7**). Secțiunea „Task-uri" de mai jos reflectă **execuția reală**, nu planul original — orice divergență e semnalată explicit inline, nu ascunsă.

**Scop R3**: cablarea în bucla de Continuous Learning (ADR-030) a lanțului deja construit — Champion Guardian (R2, evaluează) → propunere T3a de rollback (decision feed, ADR-026) → aprobare umană → execuție prin Rollback Service (R1). R3 este **pură orchestrare**: decide CÂND se cheamă fiecare componentă owned, fără să adauge, dubleze sau mute vreo capacitate de business. Fără activare (R4).

**Reguli**: Verificat, nu presupus · fără redesign · ADR-037 și doc-ul Guardian neatinse (excepție: §16, secțiunea de consemnare a stării, actualizată la închidere) · fiecare etapă fail-before/pass-after, verde, cu plan de revenire · niciun contract Frozen atins.

**Ancore verificate în repo** (citite direct, nu presupuse):
- `continuous_learning.run_cycle()` / `_process_pair()` — Fazele A (monitor) / B (train) / C (execuție decizii aprobate), gate `is_enabled()` (`learning_core_enabled`, implicit False). `_phase_c_execute_approved` iterează `ar.list_approved_decisions_for_target(target_key)` și cheamă `promote_challenger` pe `evidence.training_run_id`.
- `champion_guardian.evaluate_champion_health(family, league) -> ChampionHealthResult | None` — câmpuri consumate: `health_state`, `recommends_rollback` (True ⇔ `degrading`/`critical`), `structural_flag`, `reason` (prefixată cu `artifact_missing:` / `model_error:`).
- `rollback_service.rollback_champion(family, league, reason, rolled_back_by) -> RollbackResult(status ∈ {rolled_back, already_active, rejected})` — re-derivă predecesorul intern (CAS); NU cere predecesorul în evidence.
- `automation_runs`: `write_run(producer, process_type, tier, target_key)` (`process_type` = TEXT liber, fără CHECK — migrarea 011), `propose_decision(run_id, tier, rollback_plan, evidence, correction_method, ttl_hours)` (T3a cere `rollback_plan`; **idempotency: reutilizează ORICE decizie deschisă pe target_key și îi suprascrie evidence** — `automation_runs.py:184-216`), `surface_decision`, `list_approved_decisions_for_target`, `commit_decision`, `fail_decision_commit`, `skip_run`, `complete_run`.
- `supabase_client.get_active_champion(family, league)` → `select("*")` (deci întoarce `promoted_at` ȘI `promoted_by`).
- RPC 014 setează `promoted_by = 'rollback:' || reason || ':' || by`.
- `decision_feed.status` ∈ {proposed, pending, approved, rejected, committed, commit_failed, expired, withdrawn, orphaned, flagged, acknowledged, resolved} (migrarea 011).

---

## Decizii de design înghețate în review (înainte de orice cod)

1. **R3 = un singur fișier de producție modificat** — `continuous_learning.py` (locul canonic de orchestrare, ADR-030). Zero migrare nouă, zero RPC nou, zero funcție nouă în `supabase_client`, zero atingere `automation_runs.py` / `promotion_service.py` / `champion_guardian.py` / `oracle_engine.py`. Excepție punctuală: un helper `is_rollback_promoted()` în `rollback_service.py` (vezi §5).

2. **Discriminator `decision_kind` în evidence** — deciziile de rollback poartă `evidence.decision_kind = "rollback"`; promovările existente NU au câmpul → tratate ca `"promotion"` (backward-compatible, evidence vechi neatins). Faza C ramifică pe acest câmp.

3. **R3-Risk-1 (garda „o singură decizie deschisă per target")** — `propose_decision` suprascrie evidence-ul oricărei decizii deschise pe același `target_key`. Deci Faza D **NU** propune rollback dacă există deja o decizie deschisă pentru target (`proposed`/`pending`/`approved`) — `skip_run`, semnalul rămâne persistat de Guardian, propunerea se re-încearcă în ciclul în care target-ul e liber. Se sprijină pe invariantul ADR-026 „cel mult o decizie deschisă per target".

4. **Auto-rollback interzis (ADR-002, North Star P2/P3)** — R3 DOAR propune (T3a); execuția din Faza C rulează exclusiv decizii deja `approved` de OM. `emergency`/`operator`/`data_error` rămân căi MANUALE directe pe `rollback_service`, în afara buclei R3.

5. **Maparea reason (Opțiunea A, aprobată)** — R3 derivă `reason` din `health_state` + codul structural citit din `result.reason` (`degrading → regression`; `critical` + structural → `artifact_missing`/`model_error`). R2 rămâne înghețat — R3 consumă rezultatul Guardian fără să-i modifice contractul.

6. **Cooldown bazat pe evidență (fără timer)** — după rollback, noul `promoted_at` resetează fereastra de atribuire; Guardian numără doar meciuri scorabile de la rollback → `insufficient_data` până la ≥`MIN_MATCHES_FOR_HEALTH` (30) meciuri noi. Mecanism deja existent (R2), niciun cod nou.

7. **Anti-ping-pong / plafon de un pas (Stratul 3)** — dacă campionul activ a fost el însuși activat prin rollback (detectat DECUPLAT prin `rollback_service.is_rollback_promoted(champion)`, NU prin cunoașterea formatului `promoted_by` în R3) și ar recomanda un nou rollback, R3 **NU** propune — `complete_run(summary={chain_rollback_suppressed: True})` + `logger.warning`. Lanțul automat plafonat la exact un pas; pasul doi = intervenție manuală de operator (implementează mecanic „Rollback în lanț = Future Work", ADR-037 §14).

8. **Ordinea fazelor** — `A|B → D (health check + propunere) → C (execuție aprobate)`. Aprobarea e out-of-band; un rollback propus într-un ciclu nu poate fi aprobat+executat în același ciclu.

---

## Task-uri

### R3.0 — Doc de execuție (acest fișier)
- **Descriere**: transcrierea design-ului aprobat într-un checklist executabil. Doc-only.
- **Fișiere**: `docs/04_LEARNING_CORE/R3_IMPLEMENTATION_CHECKLIST.md` (nou).
- **Dependențe**: niciuna.
- **DONE**: checklist prezent, revizuit; oglindește R1; conține cele 8 decizii de design + graful de dependențe.
- **Fail-before**: fișierul nu există.
- **Pass-after**: fișierul prezent; niciun cod atins.
- **Rollback plan**: se șterge fișierul.

### R3.1 — Faza D read-only (Guardian check, fără propunere)
- **Descriere**: `_phase_d_champion_health(family, league, target_key, summary)` — `write_run(process_type='champion_health_check', tier='T2')` → `start_run` → `champion_guardian.evaluate_champion_health(family, league)`. Ramuri: `None` → `skip_run` (fără campion activ); orice stare → `complete_run(summary={health_state, recommends_rollback, reason})`. **NU propune încă nimic** (nici măcar la `degrading`/`critical` — doar loghează recomandarea). Apel adăugat în `_process_pair`, după A/B, înaintea C. Guardian persistă evaluarea intern (neatins de R3).
- **Fișiere**: `learning_core/continuous_learning.py` (adăugire funcție + un apel).
- **Dependențe**: R3.0.
- **DONE**: Faza D rulează Guardian în buclă, jurnalizează, fără niciun efect de decizie; Fazele A/B/C bit-neatinse.
- **Fail-before**: grep `_phase_d_champion_health` → 0; testul R3.4 care exercită Faza D eșuează (funcție absentă).
- **Pass-after**: `pytest tests/` verde; test care confirmă că Faza D cheamă Guardian și NU atinge decision feed.
- **Rollback plan**: se revine diff-ul (funcție + apel izolate).

### R3.2A — Propunere T3a de rollback + gardă R3-Risk-1 + anti-ping-pong + helper
*(în planul inițial: „R3.2")*
- **Descriere**: extinderea Fazei D: la `recommends_rollback == True`:
  1. **Anti-ping-pong (Stratul 3)** — citește `sb.get_active_champion(family, league)`; dacă `rollback_service.is_rollback_promoted(champion)` → `complete_run(summary={chain_rollback_suppressed: True, health_state, reason})` + `logger.warning`, STOP (nu propune).
  2. **Gardă R3-Risk-1** — dacă există deja o decizie deschisă pentru `target_key` → `skip_run("decizie deschisă deja pentru target — nu se stivuiește")`, STOP.
  3. **Propune** — `reason = _rollback_reason_from_health(result)` (Opțiunea A); `write_run(process_type='rollback_candidate', tier='T3a')`; `propose_decision(...)`; `surface_decision`; `summary["rollback_proposed"] += 1`.
  - **Helper decuplat** `is_rollback_promoted(champion: dict | None) -> bool` în `rollback_service.py` — încapsulează formatul `promoted_by`; R3 nu cunoaște formatul.
  - **`_rollback_reason_from_health(result)`** (helper pur în `continuous_learning.py`): `degrading → "regression"`; `critical` + structural → codul din `result.reason` (`artifact_missing`/`model_error`); fallback `regression`.
- **Fișiere**: `learning_core/continuous_learning.py`, `learning_core/rollback_service.py` (helper aditiv).
- **Status real**: ✅ DONE — commit `231ceba`.

### R3.2A.1 — Îngheață ținta rollback-ului în evidence (Execution Contract)
*(task NOU, absent din planul inițial — apărut dintr-un Execution Readiness Review cerut explicit înainte de a scrie codul de execuție)*
- **Descriere**: `evidence` capătă, la propunere, `current_training_run_id` (din `sb.get_active_champion`) și `predecessor_training_run_id` (din `sb.get_champion_predecessor`) — ținta rollback-ului **fixată la momentul propunerii**, simetric cu `promote_challenger` (target fix, nu recalculat). Dacă nu există predecesor de înghețat → `skip_run`, nicio propunere.
- **Motiv**: `get_champion_predecessor()` citește DINAMIC predecesorul campionului activ CURENT — fără înghețare, un retry peste timp (proces mort între RPC și `commit_decision`) ar recalcula un predecesor diferit (al campionului deja reactivat), producând un rollback în lanț neintenționat. Promotion nu are acest risc — operează pe `training_run_id` fix, capturat la propunere.
- **Fișiere**: `learning_core/continuous_learning.py`.
- **Status real**: ✅ DONE — commit `b04afba` (bloc atomic cu R3.2B).

### R3.2B — Execuția rollback-ului cu țintă fixă (CAS pinned)
*(în planul inițial: „R3.3" — dar reproiectată complet de Execution Contract, nu doar „extindere simplă")*
- **Descriere**: în `_phase_c_execute_approved`, `decision_kind = evidence.get("decision_kind", "promotion")`. Ramura `"promotion"` — **literal neschimbată**. Ramura nouă `"rollback"` (`_phase_c_execute_rollback`) — citește **exclusiv** `evidence["predecessor_training_run_id"]`/`evidence["reason"]` (înghețate la R3.2A.1, **niciodată recalculate**); `rollback_service.rollback_champion(family, league, reason, rolled_back_by, expected_predecessor_training_run_id=predecessor_training_run_id)`; `status ∈ {rolled_back, already_active}` → `commit_decision` + `summary["rollback_committed"] += 1`; altfel `fail_decision_commit`.
- **Extensie R1 necesară** (aprobată explicit, nume impus): `rollback_service.rollback_champion()` primește parametrul opțional `expected_predecessor_training_run_id` — dacă transmis, folosit direct ca sămânța CAS (fără re-derivare); dacă omis (`None`), comportamentul R1 (cale manuală) rămâne neschimbat. `rollback_service` rămâne simplu — nu citește `decision_feed`, primește doar valori.
- **Fișiere**: `learning_core/continuous_learning.py`, `learning_core/rollback_service.py` (parametru opțional, aditiv).
- **Status real**: ✅ DONE — commit `b04afba`, testat explicit cu scenariul „rollback → crash → schimbare externă de stare → retry → `predecessor_mismatch`, nu rollback greșit" (`test_retry_after_external_state_change_yields_predecessor_mismatch_not_wrong_rollback`).

### R3.3 (plan inițial) — ABSORBIT în R3.2B
Nu există ca task separat — execuția Fazei C a fost proiectată de la început cu ținta fixă (R3.2A.1 + R3.2B ca bloc atomic, aprobat explicit așa), nu implementată simplu și reparată ulterior.

### R3.4 — Teste dedicate + gărzi AST de ownership
*(distribuit incremental în R3.1/R3.2A/R3.2A.1/R3.2B, nu ca task separat — dar acoperirea intenționată există)*
- **Status real**: ✅ DONE, incremental. Total teste dedicate R3 (R3.1-R3.2B): **26** în `tests/test_continuous_learning_rollback.py` + **9** noi în `tests/test_rollback_service.py` (helper `is_rollback_promoted` + `expected_predecessor_training_run_id`, inclusiv testul de convergență idempotentă și cel de `predecessor_mismatch`) + gărzi AST actualizate în `tests/test_rollback_ownership.py` / `tests/test_champion_guardian_ownership.py` (whitelist `continuous_learning.py` ca importator legitim). Gărzi mecanice pe sursă (nu doar comportamentale): `test_phase_d_never_executes_rollback`, `test_phase_c_execute_rollback_uses_frozen_target_explicitly`, `test_is_rollback_promoted_not_reimplemented_locally`.

### R3.5 — Verificare de integrare live, read-only
- **Descriere**: pe DB live (`Prediction`), read-only.
- **Status real**: ✅ DONE — cu o descoperire semnificativă, netrivial anticipată în planul inițial: **`learning_core_enabled=true` în producție** (pre-existent, susține bucla ADR-030/Faze A/B/C, neînrudit cu R3), iar workflow-ul `continuous_learning.yml` rulează pe `main` — care **nu conține deloc** codul R3 (21 commit-uri în urmă). Concluzie verificată: **zero mutație, zero efect secundar** din cod R3 — pentru că el nu a rulat niciodată în producție, nu pentru că gărzile interne l-ar fi oprit. Detalii complete în `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` (Production Topology Audit).
- **Consecință**: task nou R3.7 (deployment gating), neanticipat în planul inițial.

### R3.7 — Deployment gating: flag-uri dedicate pentru Faza D
*(task NOU, absent din planul inițial — decizie de arhitectură luată direct ca urmare a R3.5)*
- **Descriere**: `learning_core_enabled` gatează azi, nediferențiat, ÎNTREG `run_cycle()` — inclusiv, după merge, Faza D. Asta ar însemna „merge = activare", încălcând separarea `R3 (cod gata)` / `R4 (activare deliberată)`. Soluție, oglindind tiparul deja stabilit de ADR-033 (`consensus_capture_enabled` vs `consensus_validation_enabled`, două gate-uri pentru două etape ale aceleiași funcționalități): două flag-uri dedicate, ambele implicit `False`:
  - `champion_guardian_enabled` — gatează EXCLUSIV Faza D (evaluare + persistare sănătate). Fazele A/B/C rămân sub `learning_core_enabled`, neschimbate.
  - `champion_guardian_proposals_enabled` — gate SEPARAT, în interiorul Fazei D: permite propunerea T3a efectivă. Cu doar primul flag activ, Guardian evaluează și jurnalizează (`proposals_disabled: True` în summary), dar nu propune nimic.
- **Fișiere**: `learning_core/continuous_learning.py` (`is_champion_guardian_enabled()`, `is_champion_guardian_proposals_enabled()`, gărzi în `_process_pair`/`_phase_d_champion_health`).
- **Status real**: ✅ DONE.

### R3.6 — Închidere (documentație, reconciliată)
- **Descriere**: `CHANGELOG.md` (secțiune R3 completă R3.1-R3.7); actualizare `CHAMPION_GUARDIAN_IMPLEMENTATION.md`; **acest fișier**, reconciliat cu execuția reală; document nou `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` (manual de lansare: ce se merge-uiește, ce flag-uri există, ordinea de activare, verificări post-activare, criterii de rollback); document nou `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` (sursă unică de adevăr, actualizată permanent). NU se ating ADR-037, documente Frozen.
- **Fișiere**: `CHANGELOG.md`, `docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md`, `docs/04_LEARNING_CORE/R3_IMPLEMENTATION_CHECKLIST.md` (acest fișier), `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` (nou), `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` (nou).
- **Dependențe**: R3.5, R3.7.
- **Status real**: ✅ DONE — commit `7e0d380`.

---

## Graful de dependențe (aciclic, reconciliat)

```
R3.0 ─▶ R3.1 ─▶ R3.2A ─▶ R3.2A.1 ─▶ R3.2B ─▶ R3.5 ─▶ R3.7 ─▶ R3.6
```
Strict liniar. R3.3 (plan inițial) absorbit în R3.2B — nu apare ca nod separat. R3.4 (teste) distribuit pe R3.1-R3.2B, nu un nod separat cu dependențe proprii.

---

## Self-review (reconciliat)

- **Fără dependențe circulare**: graful rămâne strict liniar aciclic, chiar și după reconciliere. ✔
- **Oprire după orice task fără inconsistență**: valabil identic ca în planul inițial — fiecare task DONE lasă un artefact complet, nu pe jumătate; R3.2A.1+R3.2B au fost tratate explicit ca „un singur commit, fără intermediar" tocmai ca să nu existe o stare pe jumătate (evidence înghețat dar neconsumat). ✔
- **R3 = pură orchestrare**: neschimbat — nici gărzile de deployment (R3.7) nu ating logica Guardian/Rollback, doar decid CÂND se cheamă. ✔
- **Contracte Frozen**: RUNTIME/PROMOTION/ATOMICITY/PROMOTION_SERVICE + triggerul 005 neatinse; RPC 014 neatins de-a lungul întregului R3 (inclusiv R3.2B — CAS-ul deja existent a fost suficient). ✔
- **Verificat, nu presupus**: divergențele de plan (R3.2A.1, R3.7) au apărut din audituri explicite (Execution Readiness Review, Production Topology Audit), nu din presupuneri — fiecare a fost cerută, executată, verificată pe cod/DB live înainte de a fi acceptată ca task. ✔
- **Onestitate de reconciliere**: acest document nu mai pretinde că planul inițial a fost urmat exact — orice divergență (R3.2A.1 nou, R3.3 absorbit, R3.4 distribuit, R3.7 nou) e semnalată explicit, cu motivul ei. ✔
