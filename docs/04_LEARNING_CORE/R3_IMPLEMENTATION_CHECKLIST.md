# R3_IMPLEMENTATION_CHECKLIST.md — Orchestration Layer (Stage R3)

**Tip**: checklist de execuție. NU e ADR, NU e document de arhitectură. Autoritatea de design rămâne `ADR-037` + `CHAMPION_GUARDIAN_IMPLEMENTATION.md` (neatinse de acest document). Oglindește `R1_IMPLEMENTATION_CHECKLIST.md`.

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

### R3.2 — Propunere T3a de rollback + gardă R3-Risk-1 + anti-ping-pong + helper
- **Descriere**: extinderea Fazei D: la `recommends_rollback == True`:
  1. **Anti-ping-pong (Stratul 3)** — citește `sb.get_active_champion(family, league)`; dacă `rollback_service.is_rollback_promoted(champion)` → `complete_run(summary={chain_rollback_suppressed: True, health_state, reason})` + `logger.warning`, STOP (nu propune).
  2. **Gardă R3-Risk-1** — dacă există deja o decizie deschisă pentru `target_key` → `skip_run("decizie deschisă deja pentru target — nu se stivuiește")`, STOP.
  3. **Propune** — `reason = _rollback_reason_from_health(result)` (Opțiunea A); `write_run(process_type='rollback_candidate', tier='T3a')`; `propose_decision(tier='T3a', rollback_plan="reactivează predecesorul campionului activ (rollback_champion, RPC 014, append-only, CAS)", evidence={decision_kind:'rollback', reason, health snapshot: health_state/brier_live/window_end/n_matches_evaluated}, correction_method="none — pre-ADR-034", ttl_hours=<TTL>)`; `surface_decision`; `summary["rollback_proposed"] += 1`.
  - **Helper decuplat** `is_rollback_promoted(champion: dict | None) -> bool` în `rollback_service.py` — încapsulează formatul `promoted_by` (azi `startswith("rollback:")`); R3 nu cunoaște formatul. Owner semantic = `rollback_service` (produce evenimentul de rollback).
  - **`_rollback_reason_from_health(result)`** (helper pur în `continuous_learning.py`): `degrading → "regression"`; `critical` + `structural_flag` → codul din `result.reason.split(":")[0]` (`artifact_missing`/`model_error`), validat ∈ `rollback_service.VALID_ROLLBACK_REASONS`; fallback `regression` dacă indeterminabil.
- **Fișiere**: `learning_core/continuous_learning.py` (extindere Faza D); `learning_core/rollback_service.py` (helper `is_rollback_promoted`, aditiv).
- **Dependențe**: R3.1.
- **DONE**: propunere T3a corectă la degrading/critical; ambele gărzi active; reason ∈ set închis; helper decuplat prezent.
- **Fail-before**: teste R3.4 (propunere, gardă, ping-pong) eșuează — funcționalitatea absentă.
- **Pass-after**: `pytest tests/` verde; testele confirmă propunerea, suprimarea ping-pong, garda idempotency, maparea reason.
- **Rollback plan**: se revine diff-ul; `is_rollback_promoted` e aditiv (fără apelanți dacă R3 e revenit) — se poate șterge.

### R3.3 — Extinderea Fazei C (execuție rollback aprobat)
- **Descriere**: în `_phase_c_execute_approved`, pentru fiecare decizie aprobată: `kind = evidence.get("decision_kind", "promotion")`. Ramura `"promotion"` — **literal neschimbată** (`promote_challenger` pe `training_run_id`). Ramura nouă `"rollback"` — `reason = evidence.get("reason")`; validează ∈ `VALID_ROLLBACK_REASONS` (altfel `fail_decision_commit`); `family, league = target_key.split("|", 1)`; `rollback_service.rollback_champion(family, league, reason, rolled_back_by="ADR-037-continuous-learning")`; `status ∈ {rolled_back, already_active}` → `commit_decision` + `summary["rollback_committed"] += 1`; altfel `fail_decision_commit(f"rollback: {status} — {reason}")`.
- **Fișiere**: `learning_core/continuous_learning.py` (ramură în funcția existentă).
- **Dependențe**: R3.2 (produce deciziile de rollback), R1 (executorul).
- **DONE**: rollback aprobat → executat prin Rollback Service; promovarea neatinsă; commit/fail corect.
- **Fail-before**: test care aprobă o decizie de rollback și rulează Faza C → nicio execuție (ramură absentă).
- **Pass-after**: `pytest tests/` verde; test end-to-end (propus → aprobat → executat) pe fake client + rollback mock; test că o decizie `promotion` (fără `decision_kind`) rămâne pe calea veche.
- **Rollback plan**: se revine diff-ul (ramura e izolată; calea promotion rămâne dacă se revine doar ramura rollback).

### R3.4 — Teste dedicate + gardă AST de ownership
- **Descriere**: `tests/test_continuous_learning_rollback.py` (fără rețea, fake client + Guardian/rollback mockuite): Faza D propune la `degrading`/`critical`; skip la `healthy`/`watch`/`insufficient_data`/`None`; garda R3-Risk-1 (decizie deschisă → skip, evidence promoției neatins); anti-ping-pong (`is_rollback_promoted=True` → suprimat); maparea reason (regression/artifact_missing/model_error); Faza C execută rollback aprobat, lasă promovarea pe calea veche; gate `learning_core_enabled=False` → ciclu sărit. Plus `tests/test_continuous_learning_rollback_ownership.py` (gardă AST): `continuous_learning` nu reimplementează Guardian/rollback (nu importă `shadow_testing`/`model_artifact_storage` pentru re-calcul; nu referențiază `rpc_rollback_champion` direct — trece prin `rollback_service`); nu scrie `model_champions`/`champion_health_evaluations`. Test unitar pentru `is_rollback_promoted` (True pe `rollback:...`, False pe promovare normală/None).
- **Fișiere**: `tests/test_continuous_learning_rollback.py` (nou), `tests/test_continuous_learning_rollback_ownership.py` (nou).
- **Dependențe**: R3.1–R3.3.
- **DONE**: toate cazurile verzi; fail-before demonstrat per caz.
- **Fail-before**: testele scrise înaintea codului eșuează la import/asserție.
- **Pass-after**: suita nouă verde; `pytest tests/` global verde.
- **Rollback plan**: se șterg fișierele de test.

### R3.5 — Verificare de integrare `validated without state mutation`
- **Descriere**: pe DB live, read-only (ca R1.8/R2.8): confirmă că `learning_core_enabled=False` ⇒ `run_cycle` sare complet (Faza D nu rulează); niciun `model_champions` mutat; nicio decizie `rollback_candidate` creată; `champion_health_evaluations` neschimbat (`scoreable=0` ⇒ Guardian în `insufficient_data`, fără propunere chiar dacă ar rula). Happy-path live (propunere reală → aprobare → rollback executat) rămâne DEFERAT — presupune modificarea unui campion activ, se execută doar într-o operație controlată (R4 / mediu dedicat).
- **Fișiere**: niciun fișier de producție nou (verificare pe DB + citire config).
- **Dependențe**: R3.1–R3.4.
- **DONE**: raport read-only care confirmă zero mutație de stare; happy-path documentat ca deferat.
- **Fail-before**: fără verificare, comportamentul real sub gate e nedemonstrat.
- **Pass-after**: raport scris; stare canonică neatinsă.
- **Rollback plan**: verificare read-only, nimic de revenit.

### R3.6 — Închidere (documentație)
- **Descriere**: `CHANGELOG.md` (secțiune R3 — Orchestration Layer, ADR-037; Faza D + Faza C extinsă; cooldown de evidență; anti-ping-pong; plafon de un pas) + „Limitare operațională" (happy-path deferat, `scoreable=0`); actualizare `CHAMPION_GUARDIAN_IMPLEMENTATION.md` §16 (R3 închis: granița de scriere respectată — R3 deține `automation_runs`, Guardian nu; **Future Work**: coliziunea de fereastră cross-domnie pe `UNIQUE(training_run_id, n_matches_evaluated)` la re-promovarea unui predecesor cu două domnii — dormantă azi, `scoreable=0`, ar atinge tabela R2 = în afara scopului R3); actualizare `CLAUDE.md` status. NU se ating ADR-037, documente Frozen.
- **Fișiere**: `CHANGELOG.md`, `docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md`, `CLAUDE.md`.
- **Dependențe**: R3.5.
- **DONE**: documentația reflectă R3 închis + limitările consemnate onest.
- **Fail-before**: docs contrazic starea reală (R3 nedocumentat).
- **Pass-after**: documentație consecventă.
- **Rollback plan**: se revine diff-ul de documentație.

---

## Graful de dependențe (aciclic)

```
R3.0 ─▶ R3.1 ─▶ R3.2 ─▶ R3.3 ─▶ R3.4 ─▶ R3.5 ─▶ R3.6
```
Strict liniar (fiecare etapă construiește pe artefactul precedentului); niciun ciclu. Muchiile secundare: R3.4 depinde de R3.1–R3.3 (testează tot lanțul); R3.2 introduce helper-ul din `rollback_service` consumat tot în R3.2.

---

## Self-review

- **Fără dependențe circulare**: graful e strict liniar aciclic. ✔
- **Oprire după orice task fără inconsistență**: după R3.0 = doc inert; după R3.1 = Faza D read-only (jurnal, zero decizie); după R3.2 = propuneri T3a care așteaptă aprobare umană (nimic nu se execută fără R3.3 + aprobare); după R3.3 = execuția aprobatelor, dar totul sub `learning_core_enabled=False` (P1); testele (R3.4) aditive; R3.5 verificare; R3.6 documentație. În niciun punct un artefact pe jumătate. ✔
- **R3 = pură orchestrare**: niciun prag/metrică/precondiție recalculată; Guardian și Rollback Service rămân owneri unici ai logicii lor; `promotion_service`/`automation_runs`/`champion_guardian` neatinse. ✔
- **Contracte Frozen**: RUNTIME/PROMOTION/ATOMICITY/PROMOTION_SERVICE + triggerul 005 neatinse; R3 nu adaugă migrare/RPC. ✔
- **Decuplare de format** (cerință de review): R3 nu cunoaște formatul `promoted_by` — trece prin `is_rollback_promoted()`, owner `rollback_service`. ✔
- **Auto-rollback interzis**: R3 doar propune; execuția cere `approved` uman; `emergency`/`operator` rămân manuale. ✔
- **Verificat, nu presupus**: toate ancorele (semnături Guardian/Rollback/automation_runs, `select("*")` în `get_active_champion`, formatul `promoted_by` din RPC 014, valorile `decision_feed.status`, idempotency-ul `propose_decision`) citite direct din repo. ✔
- **Consecvent cu ADR-037 / doc-ul Guardian §14**: R3 acoperă exact „R3 — Orchestrare (cablare în Continuous Learning)"; invariantul „un run retras nu se re-promovează" respectat; plafonul de un pas implementează „Rollback în lanț = Future Work". ✔
