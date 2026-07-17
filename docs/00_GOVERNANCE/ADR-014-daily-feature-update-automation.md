# ADR-014 — Actualizare automată a feature-urilor derivate în `run_daily.py`

**Status**: Implementat
**Affects**: `sync/run_daily.py` (flux, nu contract de date)
**Authority**: Principal Software Architect

---

## Context

`architecture/ADR-004-continuous-learning.md` a decis deja, în 2026-07-13, ordinea corectă a buclei de învățare continuă:

```
fixtures → results → match_history → ELO → formă → standings
    → shadow evaluation → experiment_registry
    → ML retraining (dacă e cazul) → recalibrare (manuală, validată)
```

și principiul permanent: „Toate feature-urile (ELO, formă, standings) se recalculează incremental după fiecare actualizare de rezultate." Statusul ADR-004 e explicit „Parțial implementat".

Un audit de arhitectură (2026-07-14, Task 1/2 din sprintul curent — inventar surse live + hartă flux de date) a confirmat exact ce rămăsese neimplementat: `sync/run_daily.py` rula zilnic (03:00 UTC, `daily.yml`) doar recalcularea ELO internă (`sync/calculate_elo.py`, scrie într-un tabel orfan, necitit de nimeni) — formula/H2H/cornere/cartonașe/faulturi (`sync/backfill_features.py`, sursa care alimentează efectiv `ml_predictor.FEATURE_COLUMNS`) rula **doar manual**, prin declanșare `workflow_dispatch` pe `backfill.yml`. Rezultatul practic: modelul ML se putea reantrena automat (Pasul 6, deja existent) pe feature-uri neactualizate de la ultima rulare manuală — bucla nu se închidea singură.

## Decision

`sync/run_daily.py` capătă un pas nou, **Pasul 3/6 — Actualizare feature-uri derivate**, plasat între ELO (Pasul 2) și evaluarea shadow (Pasul 4, renumerotat din 3), care apelează `sync.backfill_features.run_backfill()` necondiționat (fără filtru de ligă), zilnic, automat.

Nu e o componentă nouă — e conectarea unei funcții deja existente, deja testate (252+ teste înainte de acest ADR), deja non-destructivă (gating per-coloană, Regula #13 — „Protecția Writer-ilor") într-un flux care rulează deja automat. Flag nou `--no-features` (CLI), simetric cu `--no-elo`/`--no-ml`, pentru dezactivare explicită dacă e nevoie (niciun flag nou pornește implicit activ altfel decât cel puțin la fel de sigur ca ce înlocuiește — aici flag-ul e opțiune de rollback, nu activare de comportament nou implicit periculos).

**Ce NU se schimbă prin acest ADR** (explicit, pentru evitarea confuziei cu alte discuții arhitecturale în curs):
- Sursa canonică ELO — investigație separată, epic separat, neconcluzionată încă (`docs/03_ENGINE/ELO_FIDELITY_AUDIT_2026-07-13.md`). Pasul 2 (`calculate_elo.py`) rămâne exact cum era.
- Predictorul (`oracle_engine.py`) — neatins.
- Modelul ML (`ml_predictor.py`) — neatins.
- Niciun writer nou pe `match_history` — `backfill_features.update_match_features()` era deja singurul writer al acestor coloane.
- Statisticile brute (shots/corners/cards/fouls/HT, `MatchStatsBackfillService`) — rămân manuale (`backfill_match_stats.yml`), condiționat de o verificare separată a latenței sursei football-data.co.uk (vezi `docs/00_GOVERNANCE/BACKLOG_ARHITECTURAL_AUTOMATIZARE_2026-07-14.md`, item 1.2).

## Rationale

Completează o decizie arhitecturală deja luată (ADR-004), nu introduce una nouă — de aceea nu redeschide ADR-004, ci îl documentează ca finalizat pe această dimensiune specifică. Elimină primul item de Nivel 1 din backlog-ul de automatizare (`BACKLOG_ARHITECTURAL_AUTOMATIZARE_2026-07-14.md`).

## Consequences

- `daily.yml` (03:00 UTC) scrie acum automat, zilnic, pe `match_history.home_elo/away_elo/home_form_score/.../home_corner_avg_recent/.../home_foul_avg_recent/away_foul_avg_recent` pentru toate meciurile noi cu rezultat — anterior necesita declanșare manuală separată.
- Costul marginal e mic: `run_backfill()` scanează tot `match_history`, dar scrie doar rândurile cu coloane NULL (majoritatea rândurilor vechi sunt deja complete, deci sar fără cost de rețea).
- `ADR-004` poate fi considerat implementat pe dimensiunea „feature update incremental" — statusul lui rămâne totuși „Parțial implementat" până la rezolvarea recalibrării automate (cealaltă parte nefinalizată, nelegată de acest ADR).
