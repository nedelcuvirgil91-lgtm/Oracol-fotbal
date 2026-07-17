# ADR-031 — N-way Serving Policy

**Status**: FROZEN. Al patrulea ADR din drumul critic de execuție Football
Oracle vNext: ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030 (Frozen) →
ADR-031 (Frozen) → ADR-033.

**Implementat**: PR #6, merge-uit în `main`. Acest fișier reprezintă
contractul normativ corespunzător implementării deja existente în `main`
— nu o propunere, un document retroactiv al deciziei deja aplicate.

**Reconstrucție**: Document nescris pe disc în timp real — Frozen exclusiv
în istoricul conversației, reconstruit aici din conținutul furnizat explicit
de proprietarul produsului, fără completare sau presupunere de conținut
lipsă. **Data reconstrucției**: 2026-07-17.

## Dependencies

Niciuna către ADR-026/028/030 (independent de ele — nu depinde de
Continuous Learning sau de Model Registry pentru a expune ieșirile brute,
doar de motoarele deja existente în `oracle_engine.py`). Verificat direct
în cod: `build_raw_predictions()` nu importă nimic din `learning_core/`.

**Dependenți din drumul critic**: ADR-033 declară explicit ADR-031 ca
precondiție tehnică obligatorie (are nevoie de `raw_predictions` expuse
pentru a le putea eșantiona).

---

## Freeze Confirmation

**ADR-031 — FROZEN.** Status: Decis → Frozen. Tratat de acum ca contract
normativ.

Ce rămâne blocat permanent:

- Politica de serving N-way (fără curatoriere construită, fără meta-blender
  implicit, fără logică de Consensus).
- Contractul de ieșire byte-for-byte compatibil.
- Ordinea deterministă (familie, nume).
- Granița strictă față de ADR-033 (expune, nu interpretează).

Drum critic: `ADR-026 (Frozen) → ADR-028 (Frozen) → ADR-030 (Frozen) →
ADR-031 (Frozen) → ADR-033`. Patru din cinci componente înghețate.

---

## [Secțiuni lipsă din reconstrucție — de completat pe măsură ce sunt furnizate]

Status inițial „Decis", Context, Problem Statement, Scope, Decision (raw
predictions per motor, `build_raw_predictions()`, ordonare deterministă),
Ownership, Backward Compatibility & Rollback, Non-Goals, Dependencies,
Consequences, References, Open Questions — conținut verbatim nefurnizat
încă în această reconstrucție; nu se completează sau presupune. Vezi și
implementarea reală (`oracle_engine.py::build_raw_predictions()`,
`tests/test_n_way_serving.py`) ca sursă secundară de adevăr pentru
comportamentul efectiv, în lipsa textului ADR original.
