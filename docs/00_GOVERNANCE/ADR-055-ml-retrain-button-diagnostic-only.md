# ADR-055 — Butonul manual „Antrenează ML acum" devine strict diagnostic

**Status**: **ACCEPTAT** (2026-08-06) — aprobat explicit de proprietarul produsului ("daca zici ca e mai bine sa il transformi in diagnoastic, fa asa. aprob"), pe baza recomandării Claude, în urma investigării unei breșe reale de guvernanță descoperite azi.

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-06.

**Companion**: ADR-002 (om în buclă, promovare manuală), ADR-030 (Continuous Learning), ADR-051/052 (ML Engine, Champion serving).

---

## Context

Investigând butonul „🎓 Antrenează ML acum" din `app.py` (tab „Stare model ML"), am găsit o breșă reală: `engine.retrain_ml_model()` (`oracle_engine.py`) apela `self.ml.train()` — **exact același obiect `self.ml`** populat la pornirea aplicației prin `_resolve_champion()` → `seed_from_champion()` cu greutățile Campionului real, promovat, validat.

`engine` e o instanță unică, `@st.cache_resource` (`app.py:133`) — **partajată între toți utilizatorii aplicației**, nu per-sesiune. Apăsarea butonului suprascria, live, modelul care servește predicții tuturor — un model antrenat local, necalibrat prin fluxul oficial, nepersistat ca artefact, neevaluat în shadow — ocolind complet Challenger Framework/Promotion Engine/ADR-002, până la următorul restart/redeploy.

Până azi, gaura era latentă (`model_champions` nu avea niciun Campion real `xgboost_v1` — vezi investigația din aceeași sesiune care a dus la fix-ul din `continuous_learning.py`, `commit 0072d16`). De azi, cu primul Challenger real în evaluare shadow, gaura devine activă din momentul primei promovări reale.

## Decizie

1. `retrain_ml_model()` antrenează de acum o **instanță nouă, aruncată**, `MLPredictorEngine()` — nu mai atinge niciodată `self.ml` (obiectul folosit de `_get_ml_engine_prediction()` pentru servire live).
2. Rezultatul (accuracy, log-loss, samples, status) rămâne afișat identic în UI — funcția rămâne utilă ca diagnostic („dacă aș antrena acum, ce accuracy aș obține?"), dar fără niciun efect asupra modelului activ.
3. Panoul de status persistent de sub buton (`engine.get_ml_status()`) continuă să citească `self.ml` — starea REALĂ, live-serving — nu instanța aruncată de la ultimul diagnostic.
4. Antrenarea diagnostic tot scrie un rând în `training_runs` (efect secundar deja existent, intern lui `MLPredictorEngine.train()`, neschimbat) — util pentru trasabilitate, nu dăunător.
5. Nicio schimbare la Learning Core (`continuous_learning.py`), la Champion/Challenger, sau la calea reală de antrenare guvernată — acelea rămân singura cale prin care un model nou poate deveni campion.

## Consecințe

**Pozitive**:
- Închide o breșă reală de guvernanță — un click accidental (sau din curiozitate) nu mai poate suprascrie modelul care servește predicții live.
- Zero pierdere de funcționalitate reală — butonul continuă să răspundă la întrebarea „cum ar arăta o antrenare acum", singurul scop pentru care era folosit de fapt.

**Negative / riscuri acceptate**:
- Nimic — schimbarea e strict de izolare (o instanță nouă în loc de cea partajată), fără reducere de informație afișată utilizatorului.

## Alternative respinse

- **Eliminarea completă a butonului** — respinsă: valoarea diagnostic (accuracy pe cerere) rămâne reală și utilă; problema era doar efectul secundar asupra `self.ml`, nu existența funcției.
- **Gate de confirmare explicită înainte de antrenare** — respinsă: nu rezolvă cauza (tot ar suprascrie modelul live, doar cu un pas de confirmare în plus) — mai bine eliminată complet posibilitatea, nu doar îngreunată.
