# ADR-017 — Shadow Logging pentru Challenger activ (Pasul 3, flag dedicat)

**Status**: Implementat
**Affects**: `oracle_engine.py` (flux de predicție live), `learning_core/challenger_shadow.py`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

---

## Context

Pasul 2 (Challenger FSM, ADR-016) e închis — `challengers` există, dar
rămâne complet inert (zero apelanți). Pasul 3, autorizat explicit, conectează
Challenger-ul la fluxul REAL de predicție, pentru prima dată — dar exclusiv
ca observator: loghează cum ar fi prezis un Challenger activ, alături de
predicția reală de producție, fără să influențeze niciodată ce se servește
utilizatorului.

Autorizația a impus explicit două condiții, verificate strict la review:
1. Predicția servită trebuie să fie bit-identică cu cea dinaintea
   implementării, indiferent dacă există sau nu cod Shadow.
2. Shadow trebuie să fie complet eliminabil printr-un singur flag, fără
   efecte secundare și fără dependențe ascunse.

## Decision

1. **Flag nou, dedicat**: `challenger_shadow_logging_enabled` (implicit
   `False`, `oracle_engine.DEFAULT_CONFIG`). **NU reutilizează**
   `shadow_mode_enabled`, care rămâne legat exclusiv de experimentul
   preexistent `apifootball_injuries_coaches` — cele două nu au nicio
   legătură semantică; conflatarea lor ar fi însemnat că activarea unuia
   pornește accidental și pe celălalt.

2. **Punct de conectare**: `oracle_engine.FootballOracleEngine.evaluate_match()`,
   metodă nouă `_log_challenger_shadow()`, apelată o singură dată, ca
   ultima linie înainte de `return pred` — DUPĂ ce `pred` e deja complet
   construit și cache-uit. Aceeași poziție/tipar ca hook-ul deja existent
   `log_shadow_experiment()` (linia 1157 și împrejur), care a stabilit deja
   acest precedent pentru experimentul `apifootball_injuries_coaches`.

3. **Ce face, quando activ**: citește Challenger-ul activ pentru
   `(algorithm_family, league_scope)` = constantele deja existente din
   `ml_predictor` (`_ALGORITHM_FAMILY`, `_LEAGUE_SCOPE`, ADR-015) — dacă nu
   există, nu face nimic. Dacă există, încarcă artefactul lui
   (`learning_core.model_artifact_storage.load_model_artifact`, Pasul 1) —
   dacă lipsește/e corupt, nu face nimic. Altfel, calculează probabilitățile
   Challenger-ului pe exact aceleași feature-uri ML deja calculate pentru
   predicția de producție (`_build_ml_features`, funcție pură, deja
   folosită neschimbat) și le loghează prin `shadow_testing.log_shadow_prediction()`
   (infrastructură deja existentă, generică, reutilizată neschimbată) cu
   `experiment_group="treatment"`. Loghează din nou, cu `experiment_group="control"`,
   probabilitățile REALE deja servite (`pred.prob_home_win` etc.) — pereche
   necesară pentru comparația paired din `shadow_testing.evaluate_experiment()`
   (deja implementată, Pasul 4 o va reutiliza direct).

4. **Modul nou, izolat**: `learning_core/challenger_shadow.py` —
   `predict_with_challenger(features, training_run_id)`, o singură funcție
   pură de inferență. Reutilizează `ml_predictor.FEATURE_COLUMNS` (import
   read-only al unei constante — `ml_predictor.py` NU e modificat) pentru a
   garanta identitate cu setul de coloane al modelului de producție, fără
   duplicare care ar putea rămâne desincronizată la o viitoare promovare de
   feature.

5. **Garanția condiției #1 (bit-identic)**: `_log_challenger_shadow()`
   primește `pred` doar ca argument de CITIT (fixture_id, league, echipe,
   dată, probabilitățile deja calculate) — nu îi scrie niciun câmp, nu
   întoarce o valoare folosită pentru a-l reconstrui. Rezultatul metodei e
   ignorat de apelant (`self._log_challenger_shadow(...)`, fără atribuire).
   Orice excepție din interior (Challenger lipsă, artefact corupt, eroare
   Supabase) e prinsă intern — niciodată propagată către `evaluate_match()`.
   Verificat prin test dedicat: `pred` comparat bit cu bit (`==` pe
   dataclass) înainte/după apel, în toate scenariile (flag oprit, flag
   activ cu Challenger, eroare forțată în interior).

6. **Garanția condiției #2 (eliminabil printr-un singur flag)**: prima
   linie din `_log_challenger_shadow()` e gate-ul pe flag — dacă e `False`
   (implicit), `return False` imediat, ZERO import suplimentar (nici măcar
   `learning_core.challenger_manager`), zero apel Supabase. Verificat prin
   test care otrăvește (`sys.modules`) `shadow_testing` cu un modul care
   ridică excepție la orice atribut accesat — testul confirmă că flag-ul
   oprit nu-l atinge deloc. Ștergerea completă a `learning_core/challenger_shadow.py`,
   a metodei `_log_challenger_shadow()`, a apelului ei, și a cheii de
   config lasă restul aplicației 100% neschimbat — nimic altceva nu
   depinde de ele.

7. **Explicit, ce NU face acest ADR**: nu implementează Promotion, nu scrie
   în `model_champions`, nu schimbă niciodată predicția servită, nu rulează
   `evaluate_experiment()`/`evaluate_all_active_experiments()` pentru
   Challenger (asta rămâne Pasul 4 — reutilizarea directă a infrastructurii
   deja existente din `sync/run_daily.py`).

## Rationale

Fără date shadow reale pentru un Challenger, `evaluate_experiment()`
(deja implementat, generic) n-are ce compara — acesta e pasul minim care
face comparația viitoare posibilă, fără s-o implementeze încă.

## Consequences

- Cu flag-ul oprit (implicit, azi), producția e byte-identică cu starea
  dinaintea acestui ADR — verificat prin teste (`tests/test_challenger_shadow_logging.py`).
- Cu flag-ul pornit ȘI un Challenger activ (nu există încă niciunul —
  `challengers` rămâne goală, Pasul 2), fiecare predicție reală va scrie
  două rânduri suplimentare în `shadow_predictions` (deja existentă,
  neschimbată ca schemă) — cost adițional acceptat doar la activare
  explicită.
- Prima activare reală a flag-ului rămâne o decizie separată, ulterioară,
  nu implicită.
