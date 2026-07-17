# ADR-028 — Recalibrare (league_weights) → Model Registry

**Status**: FROZEN (anterior: Decis). Al doilea ADR din drumul critic de
execuție Football Oracle vNext: ADR-026 (Frozen) → ADR-028 (Frozen) →
ADR-030 → ADR-031 → ADR-033.

**Implementat**: PR #7, merge-uit în `main`. Acest fișier reprezintă
contractul normativ corespunzător implementării deja existente în `main`
— nu o propunere, un document retroactiv al deciziei deja aplicate.

**Reconstrucție**: Document nescris pe disc în timp real — Frozen exclusiv
în istoricul conversației, reconstruit aici din conținutul furnizat explicit
de proprietarul produsului, fără completare sau presupunere de conținut
lipsă. **Data reconstrucției**: 2026-07-17.

## Dependencies

ADR-026 (frozen) — contractul `automation_runs`/tiering, reutilizat pentru
`league_weights_adaptive` ca orice alt algoritm din Registry. Model
Registry / `LearningAlgorithm` (ADR-015…019, pre-existent, neatins) —
`league_weights_adaptive` intră prin acest contract, neschimbat.
`recalibration.py`/`sync/bootstrap_league_learning.py` (pre-existent,
reutilizat, nemodificat în logica lui internă).

**Dependenți din drumul critic**: ADR-030 (continuous_learning.py tratează
`league_weights_adaptive` generic, cu excludere explicită din Challenger
Framework via `participates_in_challenger_framework=False` — fix aplicat în
ADR-030 ca urmare directă a acestui ADR).

---

## Amendament final la secțiunea Decision (aplicat la Freeze)

### Decision

**Design Principle**: Every learning algorithm, regardless of internal
implementation, must enter the system exclusively through Model Registry.

ADR-028 nu introduce un algoritm nou. El introduce un adaptor care permite
algoritmului de recalibrare existent să participe la infrastructura
standard a Learning Core.

*[restul secțiunii Decision, neschimbat de amendament — conținut integral
nefurnizat încă în această reconstrucție; nu se completează sau presupune]*

---

## [Secțiuni lipsă din reconstrucție — de completat pe măsură ce sunt furnizate]

Restul documentului (Status inițial „Decis", Context, Problem Statement,
Scope, Migration Contract, Ownership, Tiering, Backward Compatibility &
Rollback, Non-Goals, Dependencies, Consequences, References, Open
Questions) a fost „livrat și aprobat" per declarația explicită a
proprietarului produsului la Freeze, dar conținutul verbatim nu a fost încă
furnizat în această reconstrucție — rămâne necompletat aici, nu se
inventează.

---

## Freeze Declaration

**ADR-028 — FROZEN.**

Status actualizat: Decis → Frozen. De acum tratat ca contract normativ, nu
ca document de lucru — nicio modificare arhitecturală ulterioară, decât
dacă apare o contradicție demonstrabilă cu Architecture Freeze (aceeași
regulă aplicată la ADR-026).

### Ce rămâne blocat, permanent, prin acest freeze:

- Adaptorul `league_weights_adaptive` e singura cale de intrare acceptată
  pentru recalibrare în Learning Core.
- `_recalibrate_for_result()` rămâne demovat definitiv — orice apel nou din
  cod încalcă ADR-ul, verificabil la review.
- Tiering-ul (T2 antrenare / evaluare reutilizată neschimbată / T3a
  promovare, partajat inert cu ADR-030) e fixat, nu se renegociază la
  ADR-030.
- `LearningAlgorithm`, Model Registry, Challenger FSM, Promotion Service,
  `shadow_testing`, `recalibration.py` — confirmate neatinse, rămân exact
  cum erau înainte de acest ADR.

### Drumul critic, poziție confirmată:

`ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030 → ADR-031 → ADR-033`

Doi din cinci pași ai drumului critic sunt acum înghețați. Ramurile
laterale (ADR-027, ADR-029, ADR-032, ADR-034) rămân neatinse de acest
freeze, disponibile independent.

### Următorul pas

Următoarea componentă de pe drumul critic e ADR-030 (Continuous Learning ca
funcție decuplată). Conform disciplinei stabilite, aștept aprobarea ta
explicită înainte de a începe ADR-030 Planning Draft (Etapa 1/4).
