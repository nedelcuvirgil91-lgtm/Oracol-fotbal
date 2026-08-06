# ADR-056 — Logare shadow în batch pentru Challenger, independent de vizionare

**Status**: **ACCEPTAT** (2026-08-06) — aprobat explicit de proprietarul produsului ("aprob viteza, daca rezultatul final este acelasi"), ca alternativă la scăderea pragului `MIN_MATCHES_FOR_EVALUATION` (respinsă explicit, ar fi slăbit rigoarea statistică).

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-06.

**Companion**: ADR-030 (Continuous Learning), ADR-017/addendum Chief Architect Review (`learning_core/challenger_shadow.py`, frontiera Oracle Engine → Shadow Adapter), ADR-053 (Database-First discovery — precondiție reală pentru acest ADR).

---

## Context

Promovarea Challenger-ului activ (`xgboost_v1`) cere `MIN_MATCHES_FOR_EVALUATION = 200` meciuri evaluate în shadow ȘI terminate (`continuous_learning.py`). Proprietarul produsului a întrebat dacă pragul poate scădea la 30 — respins explicit: cu doar 30 de eșantioane, testul `paired_bootstrap` (Brier + log-loss + accuracy simultan, North Star #2) ar avea intervale de încredere prea largi pentru o decizie de promovare reală, exact genul de „dovadă statistică slabă" pe care North Star #2 există ca s-o blocheze.

Investigând cauza reală a lentorii, am găsit: `_log_challenger_shadow()` (`oracle_engine.py`) rulează DOAR ca side-effect al `evaluate_match()` — apelat azi doar când cineva (proprietarul produsului, singurul utilizator) deschide efectiv un meci în aplicație. Cu Database-First (ADR-053), lista completă de meciuri descoperite există deja în `match_history`, indiferent dacă cineva le vizionează sau nu — deci bottleneck-ul real era viteza de vizionare manuală, nu vreo limitare tehnică reală.

## Decizie

1. Metodă nouă, `FootballOracleEngine.log_challenger_shadow_for_week(days_ahead=7)` (`oracle_engine.py`) — apelă `self.api.get_matches_for_week(days_ahead)` (Database-First, ADR-053, cost aproape zero) și `self.evaluate_match(m)` pentru FIECARE meci descoperit, indiferent dacă userul îl vizionează. `evaluate_match()` rămâne complet neschimbat — shadow logging-ul rulează exact pe același traseu ca la o vizionare manuală (`_log_challenger_shadow()`, gatat de `challenger_shadow_logging_enabled`, deja True).
2. Etapă nouă în `sync/run_night.py`, `_stage_challenger_shadow_batch()`, rulată **înainte** de etapa Continuous Learning (ADR-030) — shadow predictions proaspete există deja când `_phase_a_monitor_existing()` evaluează Challenger-ul activ, în aceeași rulare nocturnă.
3. **Niciun prag, algoritm sau criteriu de promovare nu se schimbă** — `MIN_MATCHES_FOR_EVALUATION` rămâne 200, testul statistic rămâne `paired_bootstrap` pe 3 metrici simultan. Se accelerează doar ACUMULAREA datelor necesare testului, nu se relaxează testul însuși.
4. Idempotent prin construcție — `shadow_testing.log_shadow_prediction()` face deja `upsert` pe `(fixture_id, experiment_name, experiment_version, experiment_group, processing_stage)` (neschimbat aici) — rularea zilnică pentru un meci încă nejucat doar reîmprospătează predicția (normal și corect, pe măsură ce se apropie kickoff-ul), nu creează duplicate.
5. Orice eșec per meci (profil echipă indisponibil, eroare de rețea etc.) e izolat — o excepție la un meci nu oprește restul batch-ului (același tipar ca restul `run_night.py`).

## Consecințe

**Pozitive**:
- Acumularea celor 200 de meciuri necesare devine independentă de cât de des se folosește aplicația — creștere predictibilă, zilnică, pe toate meciurile reale din cele 14 ligi urmărite.
- Zero schimbare de rigoare statistică — testul de promovare rămâne exact la fel de strict.
- Cost mic — `evaluate_match()` e deja 100% Database-First (ELO/H2H/formă/accidentări/vreme), fără apeluri live noi.

**Negative / riscuri acceptate**:
- Volum mai mare de scriere în `shadow_predictions`/`match_history` (predicții reîmprospătate zilnic pentru fiecare meci viitor) — acceptat, tabelă dedicată acestui scop, fără impact asupra tabelelor canonice.
- Timpul de execuție al `run_night.py` crește cu durata evaluării a ~50-100 meciuri/săptămână — acceptat, rulare nocturnă, fără constrângere de timp real.

## Alternative respinse

- **Scăderea pragului la 30** — respinsă explicit, motivul complet documentat mai sus (rigoare statistică).
- **Logare shadow doar pentru meciurile din liga curentă vizualizată** — respinsă: ar rezolva parțial problema, tot dependentă de comportamentul userului, nu de un mecanism determinist.
