# ADR-016 — Challenger FSM (bookkeeping izolat, Pasul 2)

**Status**: Implementat
**Affects**: schema Supabase (`challengers`), `supabase_client.py`, `learning_core/challenger_manager.py`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

---

## Context

Pasul 1 din Implementation Contract (persistare/reîncărcare artefact model)
e închis — `docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md`.
Pasul 2, autorizat explicit, introduce starea și tranzițiile unui
**Challenger** — un `training_run` selectat pentru evaluare live/shadow în
vederea promovării — fără nicio conectare la Shadow Evaluation, Promotion,
sau Runtime. Bookkeeping pur: doar entitatea, invariantele ei, și tranzițiile
valide.

Contractul Challenger (reprezentare, lifecycle, ownership, condiții de
moarte, invarianți) a fost negociat și înghețat într-o sesiune anterioară de
Architecture Review (design pur, fără cod) — acest ADR îl transpune în
schema de date reală.

## Decision

1. **Training Run ≠ Challenger, dar identitate 1:1.** Un `training_run`
   (deja implementat, ADR-015) e o înregistrare necondiționată a oricărei
   încercări de antrenare. Un Challenger e o decizie separată — DOAR
   training_run-urile care trec de `champion_comparison` (sau nu au
   Champion de comparat) devin candidați pentru starea de Challenger,
   conform Variantei B deja înghețate: `train → compare → DACĂ îmbunătățire
   simultană → persist artefact → devine Challenger`.

   Identitatea unui Challenger e exact `training_run_id`-ul pe care îl
   reprezintă — nu se mintuiește un UUID separat. Un `training_run` odată
   respins nu e retestat sub aceeași identitate; o reîncercare înseamnă
   întotdeauna un `training_run` nou. `challengers.training_run_id` e
   `UNIQUE`, `REFERENCES training_runs(training_run_id)`.

2. **Tabela nouă `challengers`** — `database/migrations/003_challenger.sql`,
   idempotentă, RLS activ, scriere doar prin `service_role`, exact tiparul
   `001_odds_history.sql`/`002_learning_core.sql`.

3. **FSM** (`state`, `CHECK` constraint la nivel de bază de date):

   ```
   CREATED → WAITING → EVALUATING → SUCCEEDED → PROMOTED   (terminal)
       ↓         ↓           ↓            ↓
   REJECTED  REJECTED   REJECTED     REJECTED               (terminal)
   ```

   `REJECTED` e accesibil din orice stare non-terminală, cu un motiv
   obligatoriu din mulțimea închisă `{verdict_negative, expired,
   superseded, artifact_dead}` — impus prin `CHECK` (motiv obligatoriu DOAR
   la `REJECTED`, interzis în orice altă stare). `PROMOTED` e accesibil
   exclusiv din `SUCCEEDED`. Ambele stări terminale (`PROMOTED`,
   `REJECTED`) nu au nicio tranziție de ieșire.

4. **Invariant load-bearing, impus la nivel de bază de date**: cel mult UN
   Challenger activ (stare non-terminală) per `(algorithm_family,
   league_scope)` — index unic parțial `idx_challengers_active_unique`,
   `WHERE state NOT IN ('PROMOTED', 'REJECTED')`. Identic ca tipar cu
   invariantul deja aplicat pe `model_champions` (ADR-015).

5. **`learning_core/challenger_manager.py`** — singurul modul care scrie în
   `challengers`. Expune `create_challenger()`, `transition()`,
   `get_challenger()`, `get_active_challenger()`. Fiecare tranziție e
   verificată de DOUĂ ori: (a) în Python, contra hărții explicite de
   tranziții valide (`ALLOWED_TRANSITIONS`) — pentru un mesaj de eroare
   clar; (b) la nivel de bază de date, printr-un `UPDATE ... WHERE state =
   <starea_citită>` (compare-and-swap) — garanția reală împotriva
   curselor, nu presupunere pe o citire anterioară (Regula bazelor de
   date: „scriere atomică, niciodată check-then-act").

6. **Eșecul e explicit, nu aproximat.** Spre deosebire de
   `model_artifact_storage.py` (Pasul 1 — best-effort, degradare
   grațioasă, fiindcă persistarea artefactului rulează în paralel cu un
   flux garantat de producție), `challenger_manager.py` ridică excepție
   (`ChallengerManagerError`) la orice eșec de creare/tranziție — o
   tranziție care nu se poate confirma NU e raportată drept succes tăcut.
   Corect, fiindcă bookkeeping-ul Challenger e sursa unică de adevăr a
   propriei stări (Regula #8 CLAUDE.md — nicio stare necunoscută nu se
   aproximează), nu un jurnal opțional în paralel cu altceva garantat.

7. **Explicit, ce NU face acest ADR**: nu implementează Shadow Evaluation,
   nu implementează Promotion, nu citește/scrie `model_champions`, nu
   creează niciun apelant real (Training Runner, Comparison, Orchestrator
   nu apelează încă `challenger_manager.py` — zero consumatori, verificat
   prin grep, identic ca disciplină cu Pasul 1). Nu afectează Runtime,
   Prediction Flow, sau Champion.

## Rationale

Fără o entitate Challenger persistată, cu invariante impuse la nivel de
bază de date, orice implementare viitoare a Shadow Evaluation/Promotion ar
trebui să reinventeze aceleași garanții ad-hoc, sau ar risca stări
imposibile (doi Challengeri activi simultan pentru aceeași pereche
algoritm/ligă) nedetectate până la producție.

## Consequences

- `challengers` rămâne goală până la primul apel real din Comparison/
  Orchestrator (o decizie viitoare, separată, nu implicită — identic cu
  `model_champions` după ADR-015).
- Niciun flux de producție existent nu e atins — verificat prin suita
  completă de teste (0 regresii) și prin absența oricărui import nou din
  `challenger_manager` în afara propriilor teste.
- Prima conectare reală (Pasul 5+, Promotion, per Implementation Contract)
  va reutiliza direct acest modul, fără schimbare de schemă.
