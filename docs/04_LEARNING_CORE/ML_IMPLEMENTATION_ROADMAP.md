# ML Implementation Roadmap — Plan de Execuție

**Acesta NU e un ADR. NU e un document de design. NU e o explicație.** E un plan de execuție, fază cu fază, derivat 100% din `ADR-051`, `ML_ENGINE_SYSTEM_ARCHITECTURE_V3.md` (v3), `ML_PLATFORM_ARCHITECTURE_V4.md` (v4) și review-ul Principal Architect (`ML_PLATFORM_ARCHITECTURE_REVIEW_STAFF.md`). Nicio decizie nouă de arhitectură nu se ia în acest document — unde sursele nu decid ceva explicit, faza respectivă marchează golul, nu îl umple.

**Ce NU face acest document**: nu modifică `ADR-051`, `v3`, `v4` sau review-ul. Nu rezolvă nicio contradicție găsită — le marchează explicit, într-o secțiune dedicată (§8) și, unde e relevant, inline la faza afectată.

---

## Phase 0 — Preconditions

### Scop

Confirmă că baza arhitecturală e stabilă înainte ca orice fază executabilă să înceapă.

### Ce se confirmă

- **ADR-051** — status document: `ACCEPTED` (2026-08-04, proprietarul produsului). Notă de precizie terminologică (flagată, nu rezolvată): `ACCEPTED` e o categorie de guvernanță distinctă de `FROZEN` — `FROZEN` (per `FROZEN_REGISTRY.md`) e rezervat documentelor din registru (`RUNTIME_CONTRACT.md`, `PROMOTION_CONTRACT.md`, `ATOMICITY_CONTRACT.md`, `PROMOTION_SERVICE_CONTRACT.md`), nu ADR-urilor de viziune. ADR-051 e tratat aici drept bază stabilă, imuabilă pentru scopul acestui roadmap, indiferent de eticheta tehnică exactă.
- **v3** (`ML_ENGINE_SYSTEM_ARCHITECTURE_V3.md`) — status document, la momentul scrierii lui: `DRAFT`. Acest roadmap îl tratează ca bază stabilă pentru execuție, ca urmare a deciziei explicite a proprietarului produsului de a trece la faza de implementare — dar fișierul sursă însuși nu a fost editat pentru a reflecta o promovare formală de status. **Flagat, nu rezolvat.**
- **v4** (`ML_PLATFORM_ARCHITECTURE_V4.md`) — aceeași observație: status `DRAFT` în fișierul sursă, tratat aici ca bază stabilă prin decizie explicită a proprietarului produsului, fără editare a fișierului sursă. **Flagat, nu rezolvat.**

### Precondiție blocantă, nerezolvată — obligatorie înainte de Phase 1

**v3 §0 și §9, ADR-051 §6** identifică deja, independent, un blocaj real, neînchis: `RUNTIME_CONTRACT.md` (Frozen, ADR-019) nu decide explicit dacă citirea Champion-ului pentru **afișare independentă** (Phase 5 din acest roadmap) intră sub contractul deja existent (citit azi doar pentru blending legacy) sau cere o extensie formală. v3 numește asta explicit "Etapa 0: Precondiție de guvernanță — ADR dedicat, mic".

**Acest roadmap nu conține acel ADR și nu-l scrie.** Phase 0, aici, doar CONFIRMĂ necesitatea lui ca poartă de intrare pentru Phase 1 — scrierea lui efectivă rămâne un pas separat, în afara scopului acestui document (care nu produce ADR-uri).

### Componente afectate

Niciunul de cod — document-only.

### Fișiere implicate

Niciunul de cod. Documentul viitor de guvernanță (ADR dedicat RUNTIME_CONTRACT.md) — neexistent încă, neprodus aici.

### Dependențe

Niciuna în amonte — acesta e punctul de start.

### Criterii de acceptare

- ADR-051, v3, v4 confirmate explicit ca bază stabilă (făcut, mai sus).
- ADR-ul dedicat RUNTIME_CONTRACT.md (menționat, nu scris aici) există și e `ACCEPTED`.

### Ce NU se implementează în această fază

Niciun cod. Niciun flag. Niciun fișier nou. Inclusiv ADR-ul de guvernanță menționat mai sus rămâne, deliberat, în afara acestui document.

---

## Phase 1 — Infrastructure

### Scop

Serving Wrapper pentru vocea ML — citire read-only a predicției deja calculate, fără antrenare, fără feature-uri noi, fără model nou. Corectare aplicată, per v3 §1.2/§3.1: **NU un modul `ml_engine.py` separat** — un modul separat a fost respins explicit în v3 ca prematur (justificat abia când există >1 algoritm de combinat intern, condiție nesatisfăcută de acest roadmap, vezi §8).

### Componente afectate

- **Serving Wrapper** — metodă nouă, în interiorul orchestratorului existent (`oracle_engine.py`), structural identică cu `_get_blend_engine_prediction()` deja existentă — nu re-rezolvă Champion, citește predicția deja calculată de `self.ml`.
- **Protocol integration** — verificare de conformitate față de `learning_core.model_registry.LearningAlgorithm`, nu construcție nouă — protocolul există deja.
- **Champion loading** — reutilizare directă, neschimbată, a `learning_core/champion_loader.py` prin `_resolve_champion()` deja existent. **Zero al doilea apel** — invariantul „un singur apel per construcție de proces" (RUNTIME_CONTRACT.md, Pasul 7B) rămâne, obligatoriu, neatins.
- **Wiring în Oracle** — apelul noii metode din fluxul existent `evaluate_match()`, aditiv, gatat de flag.
- **Runtime Contract** — consumat, nu modificat; extensia lui (dacă e necesară) e responsabilitatea ADR-ului din Phase 0, nu a acestei faze.

### Fișiere implicate

- `oracle_engine.py` — metodă nouă (Serving Wrapper), câmp nou izolat pe `MatchPrediction` (mirror al `blend_engine_prediction`), citire flag nou din `model_config`.
- `model_config` (Supabase, live) — flag nou, `ml_engine_display_enabled`-echivalent la nivel de rezoluție internă (implicit `False`, North Star #3) — NOTĂ: activarea UI propriu-zisă e Phase 5; Phase 1 poate introduce flag-ul de rezoluție fără să activeze afișarea.
- Teste noi — mirror structural al testelor existente pentru `_get_blend_engine_prediction()`.

### Dependențe

- **Phase 0 închisă** — inclusiv ADR-ul de guvernanță RUNTIME_CONTRACT.md, `ACCEPTED`.

### Risc de implementare cunoscut, moștenit din v3 §1.2.A — de ținut cont, nerezolvat aici

`champion_loader.load_champion_or_none()` întoarce un model brut (`XGBClassifier`), nu o instanță `LearningAlgorithm.predict(features: dict)`-compatibilă. Serving Wrapper-ul din această fază **evită** problema prin construcție (citește `self.ml`, deja capabil să facă traducerea context→feature→predicție, nu re-rezolvă Champion-ul brut direct) — dar acest lucru trebuie verificat explicit la implementare, nu presupus. **Flagat ca risc de verificat la Phase 1, nu ca decizie de design nouă luată aici.**

### Criterii de acceptare

- Wrapper-ul întoarce fie o predicție validă, fie `None` cu motiv explicit de indisponibilitate (per v3 §3.1) — niciodată o excepție propagată.
- Zero schimbare a predicției Oracle servite azi.
- Zero al doilea apel `champion_loader.load_champion_or_none()` per proces — verificat, nu presupus.
- Flag nou, implicit `False`.
- `pytest tests/` rămâne verde, integral.

### Ce NU se implementează în această fază

- Niciun `ml_engine.py` ca modul separat.
- Niciun bloc UI (Phase 5).
- Nicio conectare la Blend Engine (nicio fază din acest roadmap nu o conține — vezi §8).
- Niciun feature nou, niciun model nou antrenat.

---

## Phase 2 — Feature Layer extraction

### Scop

Mutarea calculului feature-urilor derivate (`corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` etc.) din `ml_predictor.py` (unde e azi inline, cuplat) într-un modul reutilizabil, separat. **Fără feature-uri noi. Doar decuplare — refactorizare comportament-identică.**

### ⚠️ Tensiune directă cu sursele, flagată explicit, nerezolvată

`v3 §7` ("Ce NU trebuie construit") și `v4 §2` ("Ce trebuie extins") sunt amândouă explicite: decuplarea Feature Pipeline de `ml_predictor.py` **"devine o precondiție reală abia când un al doilea algoritm ML... intră în Registry"** — condiție care NU e satisfăcută de acest roadmap (singurul `algorithm_family` prezent în toate cele 6 faze e `xgboost_v1`, Phase 3). Task-ul curent cere totuși această fază necondiționat, înaintea oricărei nevoi de al doilea algoritm. **Acest document nu decide dacă Phase 2 se execută totuși (poate avea valoare independentă de igienă/testabilitate) sau se amână — doar marchează tensiunea, per instrucțiune explicită de a nu rezolva contradicții aici.**

### Componente afectate

- Sursă: `ml_predictor.MLPredictorEngine._fetch_training_dataframe()` (calculul inline).
- Destinație: nespecificată de nicio sursă existentă — v1/v3/v4 nu decid dacă noul modul extinde `feature_engine.py` existent (deja pur, deja disciplinat) sau e un fișier complet nou. **Gol de design, flagat, nerezolvat aici** (rezolvarea lui ar fi design, în afara scopului acestui document).

### Fișiere implicate

- `ml_predictor.py` (sursă, de modificat pentru a consuma noul modul în loc de calcul inline).
- Modul destinație — nume/locație nedecisă (vezi mai sus).
- Teste de echivalență (regresie) — valorile calculate înainte/după extracție trebuie identice bit-cu-bit pe un eșantion fixat.

### Dependențe

Tehnic, independentă de Phase 1 (Phase 1 atinge servirea, Phase 2 atinge antrenarea) — **dependentă doar de Phase 0**. Secvențierea 0→1→2 din acest document e a task-ului, nu o dependență tehnică obligatorie; flagat ca observație, nu schimbat.

**Dependență reală, în aval**: Phase 3 (Training) consumă orice iese din Phase 2, dacă Phase 2 se execută.

### Criterii de acceptare

- Feature-uri calculate identic, verificat prin test de echivalență, nu presupus.
- `ml_predictor.py` consumă noul modul, zero logică de calcul feature rămasă inline.
- Zero schimbare la `FEATURE_COLUMNS`.
- `pytest tests/` verde, integral.

### Ce NU se implementează în această fază

- Feature-uri noi (interzis explicit de task).
- Ablații noi.
- Feature Store/Registry (explicit în afara scopului global, §8/§9 din v4, exclus și aici).

---

## Phase 3 — Training

### Scop

Primul `algorithm_family` — `xgboost_v1` — conectat la Model Registry și la Training Runner.

### ⚠️ Observație factuală, nu presupunere: cea mai mare parte a acestei faze e deja construită

Verificat direct în cod, în sesiunile anterioare de arhitectură: `learning_core/algorithms/xgboost_v1.py` **există deja**, e **deja înregistrat** în `learning_core/model_registry.py` (verificat: 4 implementări deja înregistrate, inclusiv `xgboost_v1`), și `learning_core/training_runner.py` orchestrează deja `fit()`/`TrainingRunResult` pentru el. v3 §5 conclude explicit: "Ce lipsește complet? Nimic structural." **Această fază, așa cum e cerută de task, e în cea mai mare parte o poartă de VERIFICARE, nu de construcție nouă.**

### Componente afectate

- `learning_core/model_registry.py` (existent, reutilizat, neschimbat).
- `learning_core/training_runner.py` (existent, reutilizat, neschimbat).
- `learning_core/algorithms/xgboost_v1.py` (existent, reutilizat, neschimbat).

### Fișiere implicate

Niciunul nou de scris, cu o excepție condiționată: dacă Phase 2 s-a executat, `xgboost_v1.py`/`training_runner.py` trebuie confirmate că citesc feature-urile din noul modul, nu din calea veche.

### Dependențe

- Phase 2 (dacă executată) — pentru sursa de feature-uri.
- Phase 0 închisă.

### Criterii de acceptare

- Rulare de confirmare (nu construcție): `training_runner` produce `TrainingRunResult` cu status `trained`, metrici walk-forward populate, artefact persistat prin `model_artifact_storage` — verificat printr-o rulare reală sau prin suita de teste deja existentă, nu presupus.
- Zero regresie față de comportamentul deja documentat (Optuna deja aplicat, hiperparametri deja fixați — v1 §5, „nicio schimbare de algoritm susținută de date azi").

### Ce NU se implementează în această fază

- Optimizare de hiperparametri (deja respinsă, sub prag, v1 §5).
- Schimbare de algoritm.
- Dataset Registry / `dataset_id` (explicit în afara scopului global).

---

## Phase 4 — Shadow

### Scop

Integrare completă în Challenger FSM — shadow testing, eligibilitate de promovare.

### ⚠️ Observație factuală: infrastructura există deja, validată empiric

`challenger_runner.py`, `challenger_manager.py`, `challenger_evaluation.py`, `challenger_shadow.py`, `shadow_testing.py`, orchestrarea `continuous_learning.py` (A→B→D→C) — toate deja funcționale, deja generice pe `algorithm_family`, deja validate empiric printr-un al doilea client real (`blend_v1`, ADR-050, zero cod nou la acel moment). **Această fază e, ca și Phase 3, în principal o poartă de verificare pentru linia `xgboost_v1`, nu construcție de infrastructură nouă.**

### Componente afectate

Toate cele de mai sus — existente, reutilizate, neschimbate.

### Fișiere implicate

Niciunul nou, cu excepția eventualelor teste de confirmare a ciclului complet pentru `xgboost_v1`.

### Dependențe

Phase 3 confirmată funcțională.

### Criterii de acceptare

- Un ciclu Challenger pentru linia `xgboost_v1` atinge un status terminal (`candidate_for_promotion` sau respins), prin pipeline-ul existent, neschimbat.
- Criteriul de promovare aplicat corect: Brier + Log-loss + Accuracy semnificative SIMULTAN, în direcție favorabilă (`shadow_testing.py`, linia deja citată în v1 §6) — North Star #2.
- `MIN_MATCHES_FOR_EVALUATION` (200) respectat, nu scurtcircuitat.

### Ce NU se implementează în această fază

- Auto-promovare (exclus explicit, ADR-002).
- Activarea Champion Guardian — **notă**: v3 §10 (Etapa 5, roadmap-ul anterior) include activarea Champion Guardian ca pas separat; task-ul curent NU o menționează nici ca fază, nici explicit în lista „în afara scopului". **Flagat ca gol de acoperire între acest roadmap și v3, nerezolvat aici** — vezi §8.
- Metrici noi de evaluare.

---

## Phase 5 — Display

### Scop

Activarea celei de-a treia voci — afișare independentă a predicției ML, conform ADR-051. Fără modificarea Blend Engine.

### Componente afectate

- Serving Wrapper (Phase 1) — consumat, nu reconstruit.
- UI Display Layer — bloc nou, paralel cu „🧮 Oracle"/„🔀 Blend" deja existente.
- `MatchPrediction` — câmp nou, izolat (`pred.ml_engine_prediction` sau echivalent), mirror exact al `pred.blend_engine_prediction` deja existent — NU `raw_predictions`, NU `shadow_predictions`.

### Fișiere implicate

- `app.py` — bloc UI nou, gatat de flag.
- `oracle_engine.py` — populare câmp nou pe `MatchPrediction`, apel Serving Wrapper din Phase 1.
- `model_config` — flag nou de afișare (implicit `False`).

### Dependențe

- Phase 1 (Serving Wrapper trebuie să existe).
- **Notă de secvențiere**: NU depinde tehnic de Phase 3/4 fiind "finalizate" în sensul unui NOU Champion promovat — `self.ml` rezolvă deja o predicție (Champion existent, fallback local, sau `none`) indiferent de un ciclu Challenger nou. Ordinea 0→5 din task e a livrării dorite, nu o dependență tehnică strictă la acest pas. Flagat ca observație.

### Criterii de acceptare

- Bloc UI „🤖 ML" apare doar cu flag activ, afișează predicție SAU motiv explicit de indisponibilitate (per v3 §3.1).
- Zero schimbare a predicției Oracle servite.
- Zero schimbare a valorii afișate azi la „🔀 Blend" — **rămâne, deliberat, neatinsă** (vezi §8 pentru observația că asta lasă Blend un pass-through inert, per v3 §1.3).
- `pytest tests/` verde, integral.

### Ce NU se implementează în această fază

- Conectarea ML → Blend (exclus explicit de task: „Fără modificarea Blend"; niciun pas ulterior din acest roadmap o adaugă — vezi §8).
- Wiring în `raw_predictions`/ADR-031.
- Explicabilitate (SHAP/counterfactual) în UI.

---

## Phase 6 — Production Gate

### Scop

Checklist complet, obligatoriu, înainte de orice activare cu impact vizibil dincolo de flag-uri implicit oprite.

### Componente afectate

Niciuna de cod — poartă de decizie/guvernanță.

### Checklist obligatoriu

- [ ] **Shadow completed** — ciclul Challenger pentru `xgboost_v1` (Phase 4) a atins un status terminal, cu `MIN_MATCHES_FOR_EVALUATION` (200) atins, nu aproximat.
- [ ] **Statistical significance** — Brier + Log-loss + Accuracy semnificative simultan, verificat prin cel puțin una din cele 3 metode existente (`paired_bootstrap`/`paired_permutation`/`wilcoxon`), în direcție favorabilă.
- [ ] **Runtime Contract** — toate cele 6 condiții din `RUNTIME_CONTRACT.md` satisfăcute pentru Champion-ul care alimentează vocea ML afișată (existență, activ, artefact existent și valid, deserializare reușită, `algorithm_version` compatibil).
- [ ] **Promotion Contract** — dacă activarea acestei faze implică o promovare NOUĂ (nu doar afișarea Champion-ului deja activ), precondițiile din `PROMOTION_CONTRACT.md` verificate explicit, separat.
- [ ] **Rollback readiness** — `learning_core/rollback_service.py` disponibil și testat pentru linia `xgboost_v1`/`(algorithm_family, league_scope)` relevantă. **Notă flagată**: fără Champion Guardian activ (§Phase 4, gol nerezolvat), detectarea degradării vocii ML nou-afișate depinde de monitorizare manuală/externă, nu de un mecanism automat de propunere de rollback — acest gate NU blochează pe asta (Champion Guardian nu e cerut de task), dar trebuie citit cunoscând limitarea.
- [ ] Flag-urile din Phase 1/5 rămân implicit `False` până la decizie explicită separată de activare (North Star #3).
- [ ] Invariantul de independență ADR-051 reverificat mecanic: Serving Wrapper-ul nu primește niciun parametru derivat din predicția Oracle a aceluiași meci (v3 §5, punctul 4).
- [ ] `pytest tests/` verde, integral, pe toată durata celor 5 faze anterioare.

### Fișiere implicate

Niciunul — document de checklist, aplicat la starea produsă de Phase 1-5.

### Dependențe

Phase 1-5, toate, confirmate.

### Ce NU se implementează în această fază

Niciun cod nou. Această fază nu produce artefacte — produce o decizie DA/NU, umană, explicită.

---

## 7. În afara scope-ului acestui roadmap — explicit, global

Următoarele rămân roadmap de PLATFORMĂ (v4), nu parte a acestui plan de execuție pentru ML Engine:

- **Dataset Registry** (`dataset_id` versionat — v4 §3, gol confirmat, contract declarat în CLAUDE.md dar nematerializat).
- **Feature Store** (v4 §2, catalog programatic de feature-uri).
- **Drift Monitoring** (v4 §8 — data/feature/prediction/calibration/confidence drift, dincolo de Champion Guardian).
- **Multi-league Serving** cu strategii diferite per ligă simultan (v4 §7).
- **Feature Experimentation** — traseu structurat de testare a ipotezelor de feature, distinct de Challenger-vs-Champion (v4 §4).
- **Auto Promotion** — exclus explicit, ADR-002.
- **Auto Rollback** — exclus explicit, ADR-002.

---

## 8. Contradicții și goluri observate — marcate, nerezolvate

Per instrucțiune explicită: fiecare element de mai jos e o observație, nu o decizie. Niciunul nu e rezolvat în acest document.

1. **v3 și v4 poartă status `DRAFT` în propriile fișiere** — acest roadmap le tratează ca bază stabilă prin decizia explicită a proprietarului produsului de a trece la execuție, nu printr-o promovare formală de status vizibilă în fișierele sursă (neatinse, per instrucțiune).
2. **Phase 0 depinde de un ADR de guvernanță (RUNTIME_CONTRACT.md) care nu există încă** — acest roadmap confirmă necesitatea lui, nu-l produce; Phase 1 nu poate începe legitim înainte ca acel ADR să fie `ACCEPTED`.
3. **Phase 2 (Feature Layer extraction) e cerută necondiționat, dar v3 §7/v4 §2 leagă explicit valoarea ei de apariția unui AL DOILEA algoritm ML** — condiție nesatisfăcută de acest roadmap (un singur `algorithm_family`, `xgboost_v1`, în toate cele 6 faze).
4. **Locația exactă a modulului rezultat din Phase 2 nu e decisă de nicio sursă** — extensie a `feature_engine.py` existent, sau fișier complet nou — gol de design, nu de execuție.
5. **Phase 3 și Phase 4, așa cum sunt formulate de task, descriu în cea mai mare parte infrastructură deja existentă** (verificat: `xgboost_v1` deja înregistrat, Challenger FSM deja validat cu `blend_v1`) — natura reală a acestor faze e verificare, nu construcție, deși task-ul le formulează ca „Conectare la Registry"/„Integrare completă" (limbaj de construcție nouă).
6. **Champion Guardian și Calibrarea (ADR-049) apar în roadmap-ul propriu al v3 (§10, Etapele 4-5) dar NU apar nici ca fază, nici în lista explicită „în afara scopului" a task-ului curent** — statut ambiguu, nerezolvat aici.
7. **Nicio fază din acest roadmap nu conectează ML la Blend Engine** (v3 §10, Etapa 3, absentă complet de aici) — Phase 5 exclude explicit modificarea Blend. Consecință directă, per v3 §1.3: Blend rămâne, chiar și după Phase 6, un pass-through matematic inert al Oracle (un singur `EngineOutput`) — viziunea ADR-051 §2.3 ("Blend combină informația Oracle+ML") **nu e atinsă de acest roadmap**, rămâne complet neprogramată.
8. **Riscul de proiectare din v3 §1.2.A** (Champion Loader întoarce un model brut, incompatibil direct cu `LearningAlgorithm.predict(features: dict)`) e relevant direct pentru Phase 1 ("Champion loading", "Protocol integration") — semnalat ca risc de verificat la implementare, nu ca decizie luată aici.
9. **`dataset_id`**, declarat obligatoriu în identitatea unui model per CLAUDE.md ("Regulile pentru Learning Core"), rămâne nematerializat (v4 §3) — Dataset Registry e explicit exclus din acest roadmap (§7) — tensiune între regula de trasabilitate completă (North Star #9) și decizia de scop a acestui document, nerezolvată.
10. **Review-ul Principal Architect** (`ML_PLATFORM_ARCHITECTURE_REVIEW_STAFF.md`, §6.1) identifică riscul ca `oracle_engine.py`, ca orchestrator unic pentru un număr crescând de metode `_get_X_engine_prediction()`, să devină punctul de rupere la scalare (5+ algoritmi) — acest roadmap adaugă exact un asemenea punct nou (Phase 1) fără să adreseze riscul semnalat, pentru că adresarea lui ar fi design, nu execuție a arhitecturii deja acceptate.
