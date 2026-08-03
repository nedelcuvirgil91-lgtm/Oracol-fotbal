# ML Engine Audit

**Status**: AUDIT — nicio modificare de cod. Etapa 2 din EPIC „ML Activation & Oracle Evolution".

**Data**: 2026-08-03.

**Autor**: Claude, la cererea proprietarului produsului.

**Scop**: răspuns complet, verificat din cod ȘI din date live (Supabase `Prediction`), la întrebările explicite ale Etapei 2 — antrenabilitate, cadență, feature-uri, online/incremental learning, concept drift, versionare, rollback. Bază pentru Etapa 4 — acest document NU propune nicio schimbare.

**Metodologie**: citire directă de cod (`ml_predictor.py`, `learning_core/*.py`, workflow-uri GitHub Actions), verificare live a flag-urilor curente din `model_config` și a conținutului real al tabelelor `training_runs`/`challengers`/`model_champions`/`challenger_evaluations`/`champion_health_evaluations` (Supabase, proiect `Prediction`).

---

## 0. Rezumat pe o pagină

Football Oracle are **două straturi ML distincte, suprapuse doar parțial**:

1. **`ml_predictor.py`** — un antrenor XGBoost simplu, funcțional, cu walk-forward validation reală (nu train/test split aleator). Se antrenează cu succes azi (verificat live: ultima rulare **2026-08-03 18:06 UTC, 49.981 eșantioane, accuracy=0.4843, log_loss=1.032**).
2. **`learning_core/`** — o arhitectură completă Champion/Challenger/Promotion/Rollback/Guardian (ADR-016, ADR-030, ADR-037), cod complet, testat, **activă la nivel de flag** (`learning_core_enabled=true`, confirmat live) — DAR cu o verigă lipsă critică: **niciun artefact de model real nu e persistat vreodată** (`save_model_artifact()` — zero apelanți în producție). Efect: Champion Loader nu găsește niciodată un model real de încărcat, iar `oracle_engine` cade mereu pe un retrain local, efemer, la fiecare pornire de proces.

**Predicția servită azi e 100% Poisson/ELO/formă** — `ml_blending_enabled=False` (implicit, cheie absentă din `model_config`) — ML-ul rulează, se antrenează, se evaluează, dar NU influențează nicio predicție afișată utilizatorului.

---

## 1. Este modelul antrenabil?

**Da, confirmat funcțional.** `MLPredictorEngine.train()` (`ml_predictor.py:302-420`) rulează cu succes azi. Verificat live (`ml_model_status`, Supabase):

```
trained_at=2026-08-03 18:06:48 UTC, samples_used=49981, accuracy=0.4843, log_loss=1.032, model_version=1
```

`training_runs` (istoric complet, nu doar ultima rulare): **55 de rulări** înregistrate până azi.

---

## 2. Cum e antrenat?

- **Algoritm**: `XGBClassifier` (`n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85, objective="multi:softprob", random_state=42`) — 3 clase (H/D/A).
- **Validare**: walk-forward, expanding window, 5 fold-uri, ordonare cronologică strictă pe `kickoff_date` — nicio scurgere temporală (`_walk_forward_validate()`, `ml_predictor.py:239-299`). Raportează Accuracy, Log Loss, Brier Score per fold.
- **Model final de producție**: antrenat pe **ÎNTREG istoricul disponibil** (nu doar pe partiția de train a ultimului fold) — walk-forward e strict pentru evaluare onestă, nu pentru selecția datelor finale (`ml_predictor.py:352-354`, comentat explicit).
- **Feature-uri lipsă**: gestionate nativ de XGBoost (`missing`-value split), niciodată imputate — inclusiv pentru cele 4 coloane derivate cu acoperire reală de doar 17,1% (deja documentat în `ML_ACTIVATION_GATE.md`, Punctul 4 al EPIC-ului anterior).

---

## 3. Când e antrenat?

**Verificare live critică**: `.github/workflows/continuous_learning.yml` are azi **DOAR `workflow_dispatch`** (manual) — cron-ul propriu a fost eliminat deliberat, consolidat în `night_sync.yml` (comentat explicit în workflow: „a păstra un cron aici ÎN PLUS ar rula Continuous Learning de două ori pe noapte").

**Cadență reală**: `night_sync.yml` (cron zilnic, 03:00 UTC) → `sync/run_night.py` (etapa 8, „ML Refresh") → `learning_core/run_continuous_learning.py` → `learning_core/continuous_learning.py::run_cycle()`.

**Gating dublu**:
1. `is_enabled()` citește `learning_core_enabled` din `model_config` — **confirmat live: `true`** (activ azi, nu implicit oprit cum ar sugera comentariile mai vechi din cod).
2. Chiar dacă activ, antrenarea propriu-zisă rulează DOAR dacă există `>= MIN_SAMPLES_TO_TRAIN` (30) meciuri noi finalizate de la ultima rulare — nu retrenează necondiționat în fiecare noapte dacă nu sunt date noi.

**Notă de discrepanță documentară**: `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` menționează încă un cron propriu pentru `continuous_learning.yml` (`0 6 * * *`) — depășit față de starea reală de cod (consolidarea în `night_sync.yml` e ulterioară ultimei actualizări complete a acelui document, 2026-07-28). Nu afectează funcționarea, dar e o sursă de confuzie pentru orice cititor viitor.

**A doua cale de antrenare, complet separată**: la FIECARE pornire de proces (Streamlit), `oracle_engine._initialize_ml()` încearcă să încarce un Champion persistat; eșuând (§7), cade pe `self.ml.train()` local — deci modelul se re-antrenează și la fiecare restart de aplicație, nu doar în ciclul nocturn.

---

## 4. Ce feature-uri folosește?

Identic cu `FEATURE_COLUMNS` documentat exhaustiv în `ML_ACTIVATION_GATE.md` (actualizat în EPIC-ul anterior, Punctul 4) — 14 coloane, 10 „core" (99,5% acoperire) + 4 derivate (17,1% acoperire, promovate prin ablație dedicată ADR-012/013/021). Nu se repetă aici integral — vezi documentul respectiv pentru tabelul complet de acoperire.

---

## 5. Există online learning?

**Nu.** Zero rezultate pentru `partial_fit`/`incremental`/`online_learning` legate de antrenarea modelului (grep exhaustiv). Fiecare rulare de `train()` e un **retrain complet, din zero**, pe întreg `match_history` disponibil — niciun update incremental pe modelul anterior.

---

## 6. Există incremental learning?

**Nu** (identic cu §5 — nu există un mecanism distinct de „incremental" separat de „online").

---

## 7. Modelul învață continuu sau doar offline?

**Cadență „continuă" (zilnică), dar fiecare pas e antrenare OFFLINE completă** — nu există o buclă de învățare continuă în sensul tehnic (streaming/incremental). Mai grav pentru continuitate reală: **verigă de persistență lipsă, confirmată prin cod și prin date live**:

- `learning_core/model_artifact_storage.py::save_model_artifact()` — proiectat să scrie modelul serializat în Supabase Storage (bucket `model-artifacts`), dar **zero apelanți în calea de producție** (confirmat prin grep — singurul apelant e propriul test unitar). Documentat explicit chiar în proiect: „azi, zero componente apelează save_model_artifact()... Training Runner nu scrie niciodată artefacte" (`docs/04_LEARNING_CORE/MODEL_ARTIFACT_STORAGE_CONTRACT.md`).
- Efect practic, confirmat live: `model_champions` conține azi DOAR rânduri de test (`algorithm_family="gate_validation_test"`, `league_scope="happy_path_b1819092"` etc., `promoted_by="gate-validation-script"`) — **zero campion real, antrenat pe date de producție, a fost vreodată promovat și persistat**.
- Consecință: `champion_loader.load_champion_or_none()` (apelat la fiecare pornire de proces din `oracle_engine._initialize_ml()`) nu găsește niciodată un artefact real de încărcat → întoarce `None` → motorul cade pe `self.ml.train()` local, **efemer** (pierdut la următorul restart).

**Concluzie**: „modelul" pe care-l vede utilizatorul (dacă blending-ul ar fi activat) NU e continuitatea unui singur model care evoluează — e un model NOU, complet re-antrenat, de fiecare dată când procesul pornește sau când rulează ciclul nocturn. „Versiunea" lui (`model_version`) e doar un contor in-memory, resetat la fiecare restart.

---

## 8. Există concept drift handling?

**Cod complet, mecanism real, dar dorment.** `learning_core/champion_guardian.py::_trend_degradation()` — împarte fereastra de sănătate 50/50, compară Brier score mediu recent vs. mai vechi, prag `TREND_DEGRADATION_MARGIN=0.10`. Dacă degradare detectată → alimentează o PROPUNERE de rollback (Faza D, `continuous_learning.py`), niciodată un trigger automat de retrain.

**Verificat live — dormant, nu doar „cu prag ridicat"**: gatat de `champion_guardian_enabled` — **cheie absentă din `model_config` → cade pe default `False`**. Cu flag-ul oprit, Faza D nu produce nicio activitate. ADR-030 exclude explicit metodologia de drift din scopul propriu — tratată separat, prin ADR-037/Champion Guardian.

---

## 9. Există versionare modele?

**Parțial — infrastructură persistentă pentru RULĂRI de antrenare, NU pentru MODELE reale.**

- **DA** pentru rulări: fiecare `train()` primește un `training_run_id` (UUID nou), persistat via `learning_core/storage.py::save_training_run()` — local (JSON) + best-effort Supabase (`training_runs`, 55 rânduri azi). Toate rulările sunt recuperabile, nu doar ultima.
- **NU** pentru artefactul modelului propriu-zis — vezi §7, `save_model_artifact()` neapelat niciodată în producție. Nu există azi un model XGBoost serializat, versionat, reîncărcabil.
- Registrul de algoritmi (`learning_core/model_registry.py`) e un catalog IN-MEMORY al implementărilor de algoritm (cheie `(name, version)`), repopulat la fiecare pornire de proces — nu un istoric de modele antrenate.

---

## 10. Există rollback?

**Cod complet (ADR-037, Stage R1.3), niciodată executat în producție — confirmat explicit chiar în planul de deployment al proiectului.**

- `learning_core/rollback_service.py::rollback_champion()` — RPC atomic dedicat (migrația 014), simetric cu `promote_challenger()` (migrația 005) — „doi scriitori" distincți pe `model_champions`, confirmat structural.
- Execuția reală cere: (a) o propunere de la Champion Guardian (dorment, §8), (b) aprobare umană explicită într-un flux de decizie (`decision feed`, T3a) — nu automat.
- Gatat de DOUĂ flag-uri, ambele confirmate `False` azi: `champion_guardian_enabled`, `champion_guardian_proposals_enabled`.
- `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` confirmă explicit, în chiar textul proiectului: „codul R3 nu a rulat niciodată în producție".

---

## 11. Promovare Champion/Challenger — completare (relevant pentru Etapa 4)

FSM: `CREATED → WAITING → EVALUATING → SUCCEEDED → {PROMOTED, REJECTED}` (`challenger_manager.py`, ADR-016). Promovare cere: stare `SUCCEEDED` + verdict `candidate_for_promotion` din `challenger_evaluations` + revalidare funcțională a artefactului + aprobare umană explicită (`_phase_c_execute_approved`) — **niciodată automată**. `auto_promotion_enabled` e menționat în documentație (CLAUDE.md, `LEARNING_CORE_ARCHITECTURE.md`) dar **nu există ca flag citit efectiv de niciun cod** — zero referințe găsite în `.py`, doar în documente. Consistent cu ADR-002 (uman în buclă, obligatoriu).

Cele **4 rânduri „PROMOTED"** găsite live în `challengers`/`model_champions` sunt fixtures de test (`gate_validation_test`, `promoted_by="gate-validation-script"`, toate create în aceeași fereastră de 6 minute, 2026-07-14) — **nu promovări reale de producție**. Zero campion real a fost promovat vreodată.

---

## 12. Ce înseamnă asta pentru Etapa 3 (benchmark)

Given §7: nu există un „model ML persistat" cu care să se facă un benchmark realist pe termen lung — orice comparație Oracle vs. ML din Etapa 3 va folosi necesar un model antrenat AD-HOC, în procesul de benchmark însuși (aceeași cale ca `ml_predictor.train()` local, nu un Champion din `model_champions`), pe date istorice reale (`match_history`). Metrica de accuracy=0.4843 confirmată live azi e deja un semnal parțial pentru Etapa 3, dar nu înlocuiește benchmark-ul dedicat (walk-forward corect izolat de orice date folosite ulterior în Poisson/blend).

---

## 13. Rezumat pentru Etapa 4 — puncte de decizie identificate aici

1. **Verigă critică lipsă**: `save_model_artifact()` trebuie conectat undeva în pipeline (Training Runner sau Challenger Manager) pentru ca „versionarea modelelor" să fie reală, nu doar codificată. Fără asta, activarea ML blending-ului ar rula mereu pe un model efemer, nu pe un Champion validat.
2. **`ARCHITECTURE_STATE.md`** are o secțiune depășită (cron vechi pentru `continuous_learning.yml`) — corecție de documentație minoră.
3. **Concept drift / rollback**: infrastructura există complet, doar 2 flag-uri o separă de activare — decizie explicită necesară dacă se dorește pornirea Champion Guardian-ului înainte sau după activarea blending-ului.
4. **`auto_promotion_enabled`**: menționat în documentație ca un flag care există, dar nu există în cod — fie se implementează (dacă se dorește vreodată automatizare, ceea ce contrazice ADR-002 azi), fie se elimină din documentație ca să nu inducă în eroare.

Niciuna din aceste decizii nu e luată aici — acest document doar constată, cu dovadă.
