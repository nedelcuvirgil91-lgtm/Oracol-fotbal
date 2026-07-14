# ADR-018 — Shadow Evaluation pentru Challenger (Pasul 4, verdict imuabil)

**Status**: Implementat
**Affects**: schema Supabase (`challenger_evaluations`), `supabase_client.py`, `learning_core/challenger_evaluation.py`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

---

## Context

Pasul 3 (Shadow Logging, ADR-017) e închis — un Challenger activ (dacă
există) are acum, pentru fiecare predicție reală, un rând `treatment`
(predicția lui) și un rând `control` (predicția reală servită) în
`shadow_predictions`. Pasul 4, autorizat explicit, transformă acele
observații brute într-un VERDICT — folosind infrastructura de evaluare
statistică deja existentă și generică (`shadow_testing.evaluate_experiment()`,
`shadow_testing.STATISTICAL_TESTS`), fără s-o modifice.

Autorizația a impus explicit: nicio schimbare de Runtime/Champion/Challenger
FSM, nicio declanșare de Promotion, verdict determinist derivat din
rezultate reale — plus o cerință suplimentară: **verdictul trebuie să fie
imuabil**. Odată calculat pentru un experiment și un set de rezultate dat,
nu trebuie recalculat sau schimbat printr-o simplă rerulare a job-ului —
doar printr-un proces explicit de corecție, separat.

## Decision

1. **Reutilizare completă, zero modificare a `shadow_testing.py`.**
   `shadow_testing.evaluate_experiment()` (deja implementat: Brier/Log-loss/
   Accuracy, teste statistice pereche, verdict `candidate_for_promotion` /
   `rejected` / `monitoring` / `insufficient_data`) rămâne EXACT cum era —
   folosit ca funcție pură de calcul, apelată cu `experiment_name=
   algorithm_family`, `experiment_version=training_run_id` (convenția deja
   stabilită în ADR-017). `experiment_registry` (ținta scrierii lui
   `evaluate_experiment()`, un rând MUTABIL per experiment — folosit și de
   alte experimente, ex. `apifootball_injuries_coaches`) rămâne neatinsă —
   acest ADR nu schimbă comportamentul ei existent pentru alte experimente.

2. **Tabelă nouă, separată**: `challenger_evaluations` —
   `database/migrations/004_challenger_evaluations.sql`, idempotentă, RLS
   activ, scriere doar prin `service_role`. NU înlocuiește
   `experiment_registry` — o completează, specific pentru cerința de
   imuabilitate a Learning Core (celelalte experimente nu au nevoie de ea
   azi; introducerea ei pentru toate experimentele ar fi infrastructură
   pentru un viitor speculativ, neconstruită aici).

3. **Imuabilitate impusă la nivel de bază de date, nu prin convenție de
   cod**: `UNIQUE (training_run_id, n_matches_evaluated)`. Scrierea
   (`supabase_client.record_challenger_evaluation()`) folosește
   `upsert(..., on_conflict="training_run_id,n_matches_evaluated",
   ignore_duplicates=True)` — echivalent Postgres cu `INSERT ... ON CONFLICT
   DO NOTHING`. O rerulare a job-ului cu ACEEAȘI fereastră de evaluare
   (același `n_matches_evaluated`) nu poate scrie un rând nou și nu poate
   modifica rândul existent — garanție structurală, demonstrată prin test
   (`tests/test_challenger_evaluation.py::test_immutability_second_write_with_same_window_is_a_noop`):
   simulează exact scenariul cerut — o a doua rulare care ar fi produs un
   verdict DIFERIT (bug ipotetic în statistică) nu schimbă rândul deja
   scris.

4. **O fereastră nouă = un fapt nou, nu o corecție.** Când se acumulează
   mai multe meciuri cu rezultat real (`n_matches_evaluated` crește),
   evaluarea produce un rând NOU, distinct — istoricul complet al
   verdictelor unui Challenger, de-a lungul timpului, rămâne trasabil
   (Regula #9 CLAUDE.md), fiecare rând un fapt istoric valid la momentul
   lui, niciodată suprascris.

5. **`learning_core/challenger_evaluation.py`** (nou, izolat) —
   `evaluate_active_challenger(algorithm_family, league_scope, ...)`:
   citește Challenger-ul activ (prin `challenger_manager`, la fel ca
   Shadow Adapter-ul din ADR-017), apelează `shadow_testing.evaluate_experiment()`,
   persistă verdictul imuabil. Best-effort — orice eșec întoarce `None`,
   niciodată excepție.

6. **Zero wiring, zero apelanți reali** — identic ca disciplină cu Pasul 1
   și 2. Acest modul NU e apelat din `sync/run_daily.py`,
   `oracle_engine.py`, sau oriunde altundeva — verificat prin test AST,
   la fel ca `challenger_manager` la închiderea Pasului 2. Wiring-ul
   într-un flux orchestrator (Learning Orchestrator, per designul înghețat)
   rămâne o decizie viitoare, separată, explicită.

7. **Explicit, ce NU face acest ADR**: nu apelează `challenger_manager.transition()`
   — un verdict `candidate_for_promotion` e doar informație persistată, nu
   o tranziție de stare a Challenger-ului. Nu scrie în `model_champions`.
   Nu declanșează nicio Promotion. Nu modifică `experiment_registry` sau
   comportamentul lui pentru alte experimente.

## Rationale

Fără un verdict persistat separat de starea mutabilă `experiment_registry`,
orice decizie viitoare de Promotion (Pasul 5) ar depinde de o valoare care
se poate schimba sub ea la următoarea rulare a job-ului zilnic — exact
opusul cerinței „fapt istoric stabil, nu răspuns dependent de momentul
execuției".

## Consequences

- `challenger_evaluations` rămâne goală până la prima evaluare reală a
  unui Challenger activ (nu există încă niciunul — `challengers` rămâne
  goală, Pasul 2).
- Comportamentul `experiment_registry`/`evaluate_experiment()` pentru
  celelalte experimente (`apifootball_injuries_coaches`) rămâne complet
  neschimbat.
- Prima conectare reală într-un orchestrator (apel automat, periodic)
  rămâne o decizie viitoare, separată, nu implicită.
