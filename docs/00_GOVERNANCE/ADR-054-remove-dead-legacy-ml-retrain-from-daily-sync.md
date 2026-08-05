# ADR-054 — Eliminarea pasului legacy „ml_retrain" din `sync/run_daily.py`

**Status**: **ACCEPTAT** (2026-08-06) — aprobat explicit de proprietarul produsului ("porneste", în continuarea aprobării generale "aprob tot ce ai zis"), în urma investigării directe (live, Supabase) a cauzei pentru care niciun Challenger `xgboost_v1` nu fusese promovat vreodată în producție.

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-06.

**Companion**: ADR-030 (Continuous Learning), ADR-048 (Model Artifact Persistence Ownership), `learning_core/continuous_learning.py` (mecanismul real, neatins de acest ADR).

---

## Context

Investigând de ce `model_champions` nu avea niciodată un rând real pentru `xgboost_v1` (doar 3 rânduri de test, `gate_validation_test`), deși `training_runs` arăta antrenări reușite frecvente, am găsit doi pipeline-uri de antrenare ML complet separate, rulând în paralel:

1. **`learning_core/continuous_learning.py`** (ADR-030) — singurul care poate crea un Challenger real, evalua în shadow, și propune promovare. Rulează ca etapa 8 din `night_sync.yml`.
2. **`sync/run_daily.py`, Pasul 6/6 ("ml_retrain")** — cod mult mai vechi, dinainte de Learning Core: antrenează `MLPredictorEngine` direct, în fiecare noapte (prag propriu, 20 meciuri noi, diferit de pragul Challenger-ului, 30), doar ca să **logheze accuracy și să arunce modelul** — nu salvează artefact, nu creează Challenger, nu are niciun efect de servire live.

Efectul secundar real, dăunător: fiindcă (2) scria constant în `training_runs`, iar (1) — înainte de fix-ul din aceeași sesiune (`commit 0072d16`, "Fix Continuous Learning contamination bug") — își ancora propriul ceas de „meciuri noi de la ultima antrenare" pe `training_runs` (orice sursă), ceasul se reseta în fiecare noapte, indiferent de sursă. Pragul de 30 de meciuri noi nu era atins **niciodată** pentru Challenger — confirmat live, `automation_runs` arăta „prag de volum neatins" zilnic, din 17 iulie până azi dimineață.

Fix-ul din `0072d16` a rezolvat contaminarea (Challenger-ul se ancorează acum pe `challengers`, nu pe `training_runs`) — verificat live, chiar azi: primul Challenger real `xgboost_v1` a fost creat cu succes (`state=EVALUATING`) la prima rulare manuală după fix. Dar Pasul 6/6 din `run_daily.py` **rămâne cod activ, fără niciun scop practic** — antrenează, măsoară, aruncă, în fiecare noapte, consumând timp de execuție și continuând să scrie zgomot în `training_runs` fără niciun beneficiu, acum că Learning Core e mecanismul real.

## Decizie

1. Se elimină complet Pasul 6/6 din `sync/run_daily.py` — blocul de cod (liniile ~586-619), intrarea `PipelineStep("ml_retrain", depends_on=("feature_update",))` din `PIPELINE_STEPS`, funcția `_print_ml_report()` (folosită exclusiv de acest pas), și parametrul `skip_ml`/flag-ul CLI `--no-ml` din `run()`/`main()` (existau exclusiv ca să controleze acest pas — fără el, nu mai au niciun efect).
2. **Nu se ating** `database.queries.should_retrain_ml()`/`get_ml_sample_count()` — `get_ml_sample_count()` e folosit și de butonul manual „Retrain ML" din `app.py` (investigare separată, neinclusă în acest ADR). `should_retrain_ml()` rămâne cod mort pentru moment, dar eliminarea lui e scop separat (nu creează niciun risc lăsat neatins).
3. **Nu se atinge** `oracle_engine.retrain_ml_model()` / butonul manual din UI — capăt separat, identificat explicit ca task ulterior, propriul lui audit.
4. **Nu se atinge** `learning_core/continuous_learning.py` — mecanismul real rămâne exact cum a fost fixat azi (`0072d16`), fără nicio schimbare suplimentară aici.
5. Niciun tabel, migrare sau contract de date nu se schimbă — eliminarea e strict de cod aplicativ (un pas de orchestrare mort), nu o schimbare de model de date.

## Consecințe

**Pozitive**:
- Elimină ultima sursă activă de zgomot în `training_runs` care ar putea, teoretic, reconfuzia orice viitoare logică de tip „ultima antrenare" (chiar dacă fix-ul de azi a eliminat deja dependența directă, o sursă moartă rămasă activă e un risc de regresie viitoare, nu doar cosmetic).
- `night_sync.yml` scapă de un pas de execuție complet inutil (antrenare XGBoost pe 50.000+ meciuri, aruncată imediat) — timp de execuție economisit, fără pierdere funcțională (nimic nu consumă azi rezultatul acelui pas).
- Clarifică arhitectura: un singur loc unde ML se antrenează cu scop real (Learning Core), nu două.

**Negative / riscuri acceptate**:
- Raportul zilnic de sincronizare (`_print_ml_report`, afișat în log-ul `run_daily.py`) nu va mai conține o secțiune „🤖 ML MODEL" — pierdere strict de vizibilitate în log, nu funcțională (Learning Core are propriul raport, prin `automation_runs`/decision feed).
- Dacă cineva se obișnuise să citească accuracy-ul din acest raport ca semnal informal de sănătate a modelului, semnalul dispare — acceptat, pentru că era oricum un artefact aruncat imediat după măsurare, nu o evaluare reală comparabilă cu Champion-ul activ (asta face corect Challenger Framework-ul, prin shadow evaluation).

## Alternative respinse

- **Doar creșterea pragului lui (2) la 30, ca să se alinieze cu Challenger-ul** — respinsă: nu rezolvă cauza reală (existența unui al doilea pipeline de antrenare fără scop), doar ascunde simptomul; ar rămâne cod mort, doar mai rar executat.
- **Păstrarea pasului dar fără scriere în `training_runs`** — respinsă: ar cere o cale de antrenare separată de `MLPredictorEngine.train()` (care persistă intern prin `storage.save_training_run()`) doar pentru acest caz — complexitate nejustificată pentru un pas care oricum nu produce nimic util.
