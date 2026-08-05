# Machine Learning Platform — Arhitectură de Sistem (v4)

**Status**: DRAFT — arhitectură de sistem, nu design de implementare. NU e ADR, NU autorizează cod, NU proiectează un predictor, NU discută algoritmi.

**Diferența față de v1/v2/v3, explicit**: documentele anterioare priveau "ML Engine" — componenta care produce A TREIA voce de predicție (ADR-051 §2.2) și cum se conectează la Blend/UI (v3, §3.1: "Serving Wrapper"). Acest document schimbă unitatea de analiză: nu mai întreabă "cum servește ML Engine o predicție", ci **"ce PLATFORMĂ trebuie să existe ca SĂ POATĂ exista, în principiu, orice motor care învață — ML azi, Blend deja, un al patrulea motor mâine"**. ML Engine (v3) e un CONSUMATOR al acestei platforme, nu platforma însăși. Distincția contează pentru că, verificat direct în cod, platforma NU e construită pentru ML — e deja construită generic, pentru orice `algorithm_family`, și `blend_v1` o dovedește prin exemplu (folosește exact aceleași straturi, zero cod nou în ele, ADR-050).

**Metodologie**: fiecare afirmație verificată prin citire directă de cod în această sesiune — `feature_engine.py`, `ml_predictor.py` (parțial, din v1/v3), `supabase_client.get_training_data()`, `learning_core/model_registry.py`, `learning_core/training_runner.py`, `learning_core/challenger_*.py`, `learning_core/promotion_service.py`, `learning_core/champion_comparison.py`, `learning_core/rollback_service.py`, `learning_core/champion_loader.py`, `learning_core/champion_guardian.py`, `learning_core/consensus_validation.py`, `automation_runs.py` (ADR-026), `docs/00_GOVERNANCE/FROZEN_REGISTRY.md`, `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`, `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` — plus grep exhaustiv pentru `dataset_id` (confirmă: apare DOAR ca notă/comentariu de intenție viitoare într-un singur fișier de cod și într-un document de audit, NICIUNDE ca o coloană/schemă reală).

---

## 1. Cele opt straturi — definiție la nivel de platformă

Nu straturi de implementare — straturi de RESPONSABILITATE, fiecare cu o întrebare proprie pe care trebuie s-o poată răspunde orice sistem ML matur:

| Strat | Întrebarea la care răspunde |
|---|---|
| **Feature Layer** | Cum transformăm date brute în semnal utilizabil de un model? |
| **Dataset Layer** | Ce EXACT a văzut un model la antrenare, reproductibil, trasabil? |
| **Experimentation Layer** | Cum testăm o ipoteză/candidat împotriva realității, înainte să conteze? |
| **Training Layer** | Cum producem un model antrenat, dintr-un algoritm și un set de date? |
| **Promotion Layer** | Cine decide, și cum, că un candidat devine ceea ce servește? |
| **Serving Layer** | Cum ajunge un model antrenat să răspundă la o cerere reală? |
| **Monitoring Layer** | Cum știm dacă ce servim azi e încă sănătos? |
| **Governance Layer** | Cine aprobă, cine trasează, cine poate opri orice din cele de mai sus? |

---

## 2. Feature Layer

### Ce există deja

- `feature_engine.py` — **complet stateless, fără I/O** (verificat: `compute_form_score`, `compute_h2h_modifier`, `elo_to_offensive_multiplier`/`elo_to_defensive_multiplier`, `rest_days_modifier`, `calibrate_xg`, `resolve_league_weights`, `compute_team_offdef_rating`, `poisson_model` — 8 funcții pure, intrare→ieșire, zero citire externă). Acesta e stratul de transformare "brut → semnal" pentru Oracle, deja matur, deja disciplinat (ablație obligatorie per feature nou, per `CLAUDE.md`).
- Calculul feature-urilor specifice ML (`corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance`, ferestre `*_avg_recent`) — există, dar **cuplat**, în `ml_predictor.MLPredictorEngine._fetch_training_dataframe()` (confirmat în v1 §4), nu într-un modul independent.

### Ce poate fi reutilizat

`feature_engine.py` însuși — nu trebuie reconstruit, e deja pur, deja testat, deja disciplinat de regula de ablație. Orice extindere a Feature Layer la platformă (feature-uri noi, pentru orice algoritm viitor) ar trebui să urmeze exact acest tipar (funcție pură, fără I/O), nu tiparul cuplat din `ml_predictor.py`.

### Ce trebuie extins

Decuplarea calculului feature-urilor ML de `ml_predictor.py` într-un modul propriu, reutilizabil de orice algoritm viitor din Model Registry — deja semnalată corect ca "nu urgentă azi" în v1 §4, dar devine o precondiție reală de platformă (nu doar de motor) în momentul în care un al doilea algoritm ML (nu doar Blend, care nu are feature-uri proprii) intră în Registry.

### Ce lipsește complet

**Un Feature Store/Registry propriu-zis** — un catalog explicit al feature-urilor disponibile, cu proveniență, versiune, acoperire live documentată programatic (nu doar în tabele Markdown ca în v1 §3). Azi, "ce feature-uri există" e cunoscut doar prin citirea codului (`FEATURE_COLUMNS`) — nu există un mecanism care să răspundă programatic "ce feature-uri sunt disponibile pentru meciul X, cu ce acoperire istorică". Pentru un singur algoritm, asta nu costă nimic; pentru o platformă cu mai mulți algoritmi/experți specialiști (v2 §4), lipsa asta devine friction reală.

---

## 3. Dataset Layer

### Ce există deja

- `supabase_client.get_training_data(only_with_results: bool = True)` — citire directă, live, din `match_history`. Confirmat: parametru unic, fără versionare, fără snapshot.
- Filtrare de corectitudine deja aplicată la citire (`superseded_by IS NULL`, per v1 §2) — deduplicarea meciurilor canonice e reală și corectă.

### Ce poate fi reutilizat

Filtrele de corectitudine existente (deduplicare, excludere predicții proprii) — logica de "ce e valid să intre în antrenare" e deja acolo, corectă, doar needs to move cu orice extensie de Dataset Layer, nu de reconstruit.

### Ce trebuie extins

Fiecare apel de antrenare azi citește STAREA CURENTĂ, live, a lui `match_history` — două rulări de antrenare la momente diferite, chiar cu același `training_run_id` conceptual, pot vedea seturi de date diferite dacă în timp au intervenit backfill-uri/corecții (exact genul de eveniment documentat frecvent în acest proiect — vezi corecțiile season/football-data.org din istoricul recent). Extensia necesară: fixarea/înghețarea explicită a datelor consumate per rulare de antrenare, nu doar citirea "tot ce e valid acum".

### Ce lipsește complet

**Dataset Registry / `dataset_id` versionat** — verificat explicit prin grep: `dataset_id` NU există ca și coloană/schemă reală nicăieri în `database/` — apare o singură dată, ca notă de intenție viitoare, într-un comentariu din `learning_core/algorithms/xgboost_v1.py` ("pregătit pentru Dataset Registry (etapă ulterioară), când antrenarea va primi un dataset_id versionat explicit"). **Contradicție reală, de reținut**: `CLAUDE.md`, secțiunea "Regulile pentru Learning Core", afirmă ca regulă permanentă "Orice model identificabil unic prin `(algorithm_family, algorithm_version, training_run_id, dataset_id)`" — dar `dataset_id` nu e materializat nicăieri. Azi, identitatea unui model e de facto doar `(algorithm_family, algorithm_version, training_run_id)` — trasabilitatea EXACTĂ a datelor consumate la antrenare nu există ca artefact interogabil, doar ca presupunere ("tot ce era valid la momentul antrenării"). Aceasta e o lacună de platformă reală, nu un detaliu — afectează direct North Star #9 ("orice rezultat trasabil complet până la sursă").

---

## 4. Experimentation Layer

### Ce există deja

**Notă structurală importantă, negăsită explicit numită în v1/v2/v3**: platforma are azi **DOUĂ trasee de experimentare distincte**, cu scop diferit, care merită separate explicit la nivel de platformă:

1. **Challenger-vs-Champion (scopul de promovare)** — `challenger_runner.py`, `challenger_manager.py`, `challenger_evaluation.py`, `challenger_shadow.py`, `blend_challenger_shadow.py`, plus `shadow_testing.py` (metodologia statistică: Brier/Log-loss/Accuracy, semnificație pe perechi). Întrebarea: "e candidatul X mai bun decât Champion-ul activ, dovedit statistic?"
2. **Consensus Validation (scopul de cercetare)** — `learning_core/consensus_validation.py` + `learning_core/consensus_capture.py` (ADR-033). Întrebarea, diferită: "acordul/dezacordul dintre motoare corelează cu acuratețea reală?" — nu testează un candidat de model, testează o IPOTEZĂ despre semnal.

Ambele traseje ajung, la capăt, prin `automation_runs.py` (ADR-026) în același `decision_feed` — dar sunt independente structural (verificat: `consensus_validation.py` "nu atinge niciodată `oracle_engine.py`, Model Registry, Challenger FSM sau Promotion Service").

### Ce poate fi reutilizat

Traseul Challenger-vs-Champion, integral, pentru orice algoritm nou (deja dovedit cu `blend_v1`, ADR-050, zero cod nou). Metodologia `shadow_testing.py` — Brier/Log-loss/Accuracy simultan, teste de semnificație pe perechi — e deja platformă-nivel, nu specifică unui algoritm.

### Ce trebuie extins

Bug-ul de cuplare la exact 2 motoare din `consensus_validation.compute_metrics()` (`a, b = engines[0], engines[1]`, verificat direct) — irelevant pentru traseul Challenger (nu-l atinge), dar blochează traseul Consensus Validation de la a include vreodată un al treilea motor (ML) fără reparație explicită. Nu e o precondiție a platformei ca întreg — e o precondiție DOAR dacă se decide vreodată conectarea ML la acest traseu specific (v3 §1.5, deja scopat corect acolo).

### Ce lipsește complet

**Un traseu de experimentare pentru ipoteze de FEATURE, distinct de ipoteze de MODEL.** Azi, "testăm dacă un feature nou ajută" se face manual, ad-hoc (ablație descrisă narativ în ADR-uri, PREDICTOR_ROADMAP_V4.md), nu printr-un mecanism structurat, repetabil, cu decision_feed propriu — spre deosebire de "testăm dacă un model nou e mai bun" (Challenger FSM, foarte structurat). E o asimetrie reală de maturitate între cele două tipuri de experiment pe care platforma le tratează azi foarte diferit.

---

## 5. Training Layer

### Ce există deja

- `learning_core/model_registry.py` — catalog `Protocol`-based, verificat zero referință hardcodată la XGBoost.
- `learning_core/training_runner.py` — orchestrează `fit()`, produce `TrainingRunResult`.
- `learning_core/algorithms/` — patru implementări deja înregistrate: `xgboost_v1.py`, `production_champion.py`, `league_weights_adaptive.py`, `blend_v1.py`.

### Ce poate fi reutilizat

Tot — verificat empiric, nu doar teoretic: al doilea `algorithm_family` (`blend_v1`) a intrat fără nicio modificare a `model_registry.py`/`training_runner.py`. Acesta e cel mai matur strat al platformei.

### Ce trebuie extins

Cele două căi paralele de scriere `training_runs` (`ml_predictor._record_training_run()` vs. `learning_core/training_runner.py::run_training()`, deja semnalat în v1 §4 punctul 3) — igienă, nu blocaj.

### Ce lipsește complet

Nimic structural — singura lipsă reală (Dataset Registry, §3) aparține Dataset Layer, nu Training Layer însuși; Training Layer doar CONSUMĂ acea lipsă indirect (antrenează pe date nesnapshot-uite).

---

## 6. Promotion Layer

### Ce există deja

- `learning_core/promotion_service.py` — singurul scriitor autorizat #1 al `model_champions`, validare genericã pe `algorithm_family`/`league_scope` (verificat direct).
- `learning_core/champion_comparison.py` — raport PUR INFORMATIV (verificat: "NU decide, NU promovează, NU face rollback") care compară metrici walk-forward model-nou-vs-Champion — util ca diagnostic dinaintea unei decizii umane de promovare.
- `learning_core/rollback_service.py` — scriitorul autorizat #2, append-only, CAS-guarded (ADR-037 R1).
- `model_champions` — sursa de adevăr, un rând per `(algorithm_family, league_scope)` activ.

### Ce poate fi reutilizat

Tot — la fel ca Training Layer, deja validat generic prin precedentul `blend_v1`.

### Ce trebuie extins

Nimic identificat ca blocaj structural — stratul e complet pentru scopul lui declarat (promovare/rollback manuale, cu dovadă statistică simultană).

### Ce lipsește complet

Auto-promovare/auto-rollback — **deliberat lipsă**, nu un gol de completat, contrazice explicit ADR-002 (North Star #2, "promovare cere dovadă statistică ... niciodată intuiție", implicit uman-în-buclă). Menționat aici doar pentru completitudine — nu e un "de construit".

---

## 7. Serving Layer

### Ce există deja

- `learning_core/champion_loader.py` — cele 6 condiții `RUNTIME_CONTRACT.md`, fail-fast, verificat: consumat EXCLUSIV de `oracle_engine._resolve_champion()`.
- `oracle_engine._resolve_champion()` — un singur apel per construcție de proces, atomicitate garantată (Pasul 7B).
- `blend_engine.py` — motor de combinare, zero I/O, zero cuplaj (verificat: singurele importuri sunt `dataclasses`/`typing`).

### Ce poate fi reutilizat

Toată infrastructura de mai sus — deja detaliată exhaustiv în v3 (§3.6-3.12 acolo). Nu se repetă aici.

### Ce trebuie extins

Serving Wrapper-ul pentru vocea ML (v3 §3.1) — deja proiectat acolo, corecție față de v1, nu se re-derivă aici.

### Ce lipsește complet

La nivel de PLATFORMĂ (nu de motor individual): **niciun mecanism de servire pentru mai mult de un `league_scope` simultan cu strategii diferite per ligă** — azi `_resolve_champion()` rezolvă un singur Champion per `algorithm_family`, cu `league_scope` ca parte a cheii, dar orchestrarea la nivel de `oracle_engine.py` nu are un concept explicit de "servesc Champion diferit per ligă, în același proces, simultan" dincolo de ce oferă cheia compusă — suficient azi (un singur `league_scope="all"` folosit de facto), dar un gol real dacă v2 §4 (modele specialist per-ligă) devine relevant.

---

## 8. Monitoring Layer

### Ce există deja

- `learning_core/champion_guardian.py` — sănătatea Champion-ului ACTIV, 4 dimensiuni (structural/baseline-deviation/trend/stabilitate), read-only, generic pe `algorithm_family` — verificat, dezactivat azi (`champion_guardian_enabled=False`), dar complet, testat.
- Monitorizare adiacentă, NU de model — Provider Health Dashboard (Sprint 1.1: rate 24h/7zile, breakdown erori 429/403/timeout/5xx, cost per provider) și `flashscore_data_completeness` (scor per meci) — utile, dar despre SĂNĂTATEA INGESTIEI DE DATE, nu despre sănătatea unui model servit. Aparțin, de fapt, monitorizării Dataset/Feature Layer, nu Monitoring Layer al modelului.

### Ce poate fi reutilizat

Champion Guardian — complet, doar de activat (flag), pentru orice `algorithm_family`, inclusiv un viitor ML Engine cu voce proprie.

### Ce trebuie extins

Nimic la Champion Guardian însuși — e deja generic. Ce trebuie extins e SFERA monitorizării: azi acoperă doar "e campionul activ sănătos" — nu acoperă drift-ul la nivel de intrare (feature-uri), doar la nivel de ieșire/performanță (ce compară Champion Guardian sunt predicții vs. rezultate, nu distribuția feature-urilor de intrare).

### Ce lipsește complet

**Monitorizare de tip data/feature/prediction drift, distinctă de sănătatea unui singur Champion** — exact taxonomia descrisă în v2 §8 (data drift, concept drift, feature drift, prediction drift, calibration drift, confidence drift) — Champion Guardian acoperă parțial doar "calibration/trend drift" indirect, prin comparație cu rezultate reale. Nu există azi niciun mecanism care să compare distribuția feature-urilor de ANTRENARE cu cele văzute LIVE — un gol real de platformă, separat de orice motor anume, care ar beneficia deopotrivă Oracle (dacă vreodată monitorizat), ML, și Blend.

---

## 9. Governance Layer

### Ce există deja

- **`automation_runs.py` (ADR-026)** — substratul comun, deja generic, pentru ORICE proces autonom din platformă: două state machine-uri legate (`automation_runs`: execuție; `decision_feed`: decizie), tiering T3a (cere plan de rollback explicit, impus la nivel de schema DB) / T3b (semnal, fără decizie de execuție), sweep de staleness (`expired`/`orphaned`, niciodată aprobare tacită), Activity Log + Decision Feed read-only. Verificat: deja reutilizat de `consensus_validation.py` fără nicio modificare a `automation_runs.py` — al doilea precedent de generalitate reală, alături de `blend_v1` pentru Training/Promotion.
- **Documente Frozen** (`FROZEN_REGISTRY.md`) — `RUNTIME_CONTRACT.md`, `PROMOTION_CONTRACT.md`, `ATOMICITY_CONTRACT.md`, `PROMOTION_SERVICE_CONTRACT.md` — toate patru specifice Learning Core, toate patru înghețate prin ADR-019, modificabile doar prin ADR nou.
- **`ML_ACTIVATION_GATE.md`** — gate specific, separat, pentru mecanismul LEGACY de blending (`ml_blending_enabled`) — patru condiții obligatorii, distinct de gate-ul de guvernanță identificat de ADR-051 §6/v3 pentru afișarea independentă.
- **Disciplina ADR + `model_config`/flag-uri** (North Star #3, "niciun flag nou nu pornește implicit activ") — deja regulă mecanică aplicată consecvent (verificat pe fiecare flag citat în v1/v3: `blend_engine_display_enabled`, `champion_guardian_enabled`, `consensus_validation_enabled` — toate `False` implicit).

### Ce poate fi reutilizat

Tot — `automation_runs.py` e, verificat, deja platformă-nivel (nu ML-specific, folosit deja de un track complet diferit, Consensus Validation). Orice proces nou de platformă (inclusiv un viitor Monitoring Layer extins, §8) ar trebui să raporteze prin acest substrat, nu să inventeze un mecanism paralel de logging/decizie.

### Ce trebuie extins

Nimic structural în `automation_runs.py` însuși. Ce trebuie extins e ACOPERIREA lui — azi doar `consensus_validation.py` și (indirect, prin `ADR-030`) `continuous_learning.py` par să-l folosească explicit; un viitor Serving Wrapper ML (v3 §3.1) sau un viitor Monitoring extins (§8) ar trebui să raporteze prin el, nu să inventeze propriul jurnal.

### Ce lipsește complet

**Un singur punct de guvernanță neînchis, deja identificat de trei documente separate (ADR-051 §6, v1 §9, v3 §0/§9)**: decizia explicită, printr-un ADR mic, dacă citirea Champion-ului pentru afișare independentă (nu doar blending legacy) intră sub `RUNTIME_CONTRACT.md` ca extensie aditivă sau cere redeschidere. Rămâne, la acest al patrulea document, EXACT ACELAȘI blocaj — nu s-a găsit un al doilea gol de guvernanță în această trecere suplimentară prin cod.

---

## 10. Diagrama de platformă — toate cele opt straturi

```
┌─────────────── GOVERNANCE LAYER (automation_runs.py, ADR-uri, Frozen Registry) ───────────────┐
│   Decision Feed · Activity Log · flag-uri model_config · documente Frozen                       │
│   Traversează TOATE straturile de mai jos — nu e "deasupra", e prezent în fiecare graniță        │
└───────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   ┌───────────────┐
│ FEATURE LAYER│   │ DATASET LAYER│   │ EXPERIMENTATION   │   │ TRAINING LAYER│
│ feature_     │   │ get_training_│   │ LAYER              │   │ Model Registry│
│ engine.py    │──▶│ data() (live,│──▶│ Challenger FSM     │──▶│ Training      │
│ (pur)        │   │ fără dataset_│   │ + Shadow Testing   │   │ Runner        │
│ [lipsă:      │   │ id — LIPSĂ)  │   │ (promovare)        │   │ + algorithms/*│
│ Feature Store]│  │ [lipsă:      │   │ Consensus Valid.   │   │               │
└──────────────┘   │ Dataset      │   │ (cercetare, separat)│  └───────┬───────┘
                    │ Registry]    │   └────────────────────┘          │
                    └──────────────┘                                    ▼
                                                              ┌───────────────────┐
                                                              │  PROMOTION LAYER   │
                                                              │ Promotion Engine   │
                                                              │ Champion Comparison│
                                                              │ Rollback Engine    │
                                                              │  → model_champions │
                                                              └─────────┬──────────┘
                                                                        │
                                                                        ▼
                                                              ┌───────────────────┐
                                                              │   SERVING LAYER    │
                                                              │ Champion Loader    │
                                                              │ (RUNTIME_CONTRACT) │
                                                              │ Blend Engine       │
                                                              │ [ext: ML wrapper]  │
                                                              └─────────┬──────────┘
                                                                        │
                                                                        ▼
                                                              ┌───────────────────┐
                                                              │  MONITORING LAYER  │
                                                              │ Champion Guardian  │
                                                              │ [lipsă: data/      │
                                                              │  feature/prediction│
                                                              │  drift monitoring] │
                                                              └────────────────────┘
```

---

## 11. Observație centrală de platformă

Verificat, nu presupus, de trei ori independent în această sesiune (Training Layer cu `blend_v1`, Governance Layer cu `automation_runs.py` reutilizat de Consensus Validation, Promotion Layer generic pe `algorithm_family`): **platforma nu a fost construită pentru ML — a fost construită generic, iar ML e doar al doilea client care beneficiază de ea** (primul fiind `production_champion`/`league_weights_adaptive`, al treilea fiind deja `blend_v1`). Asta înseamnă că întrebarea corectă de arhitectură nu e "ce trebuie construit ca ML să funcționeze" (răspunsul, per v3, e aproape nimic) — e **"ce trebuie construit ca platforma să rămână generică și pentru un al patrulea, al cincilea client viitor, fără ca fiecare să repete aceleași lacune"** — și acolo se află cele patru lipsuri reale identificate aici: Dataset Registry (§3), Feature Store (§2), traseu de experimentare pentru feature-uri (§4), monitorizare de drift dincolo de sănătatea unui singur Champion (§8). Niciuna dintre ele nu e specifică lui ML — toate patru beneficiază la fel de mult orice motor viitor, exact motivul pentru care aparțin platformei, nu unui singur motor.

---

## 12. Sumar — clasificare finală, pe cele opt straturi

| Strat | Maturitate | Ce lipsește complet (singurul lucru de reținut per strat) |
|---|---|---|
| Feature Layer | Matur pentru Oracle, cuplat pentru ML | Feature Store/Registry programatic |
| Dataset Layer | Funcțional, dar fără reproductibilitate garantată | Dataset Registry / `dataset_id` versionat (declarat în CLAUDE.md, nematerializat) |
| Experimentation Layer | Matur pe traseul Challenger, imatur pe traseul feature-uri | Traseu structurat de experimentare a IPOTEZELOR de feature, distinct de model |
| Training Layer | Matur, generic, validat empiric (2 clienți) | Nimic structural |
| Promotion Layer | Matur, complet pentru scopul declarat | Nimic (auto-promovare exclusă deliberat) |
| Serving Layer | Matur, corectat în v3 | Servire multi-league simultană cu strategii diferite (relevant doar dacă apar experți per-ligă) |
| Monitoring Layer | Matur pentru sănătatea unui Champion, absent pentru drift | Monitorizare data/feature/prediction/calibration drift |
| Governance Layer | Matur, generic, validat empiric (2 clienți) | Nimic nou — un singur blocaj, deja cunoscut din 3 documente anterioare (RUNTIME_CONTRACT.md) |

Acest document nu autorizează nicio implementare.
