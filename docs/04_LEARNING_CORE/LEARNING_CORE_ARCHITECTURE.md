# LEARNING_CORE_ARCHITECTURE.md — Football Oracle

**Status**: Draft de arhitectură — Not Yet Frozen (per regula din `docs/00_GOVERNANCE/FROZEN_REGISTRY.md`, orice document nou necesită parcurgerea unui ADR dedicat înainte de a fi declarat Frozen). Persistat oficial în repository conform Directivei de Guvernanță a Proiectului — GitHub e sursa unică de adevăr, nu conversația.
**Referință**: Football Oracle v4.1 — Phase 1: Learning Core Architecture.
**Scop**: livrabil de proiectare pură — fără cod, fără modificări de fișiere de producție, fără implementare. Bază solidă pentru ca implementarea ulterioară (Etapa 3) să poată începe fără redesenarea arhitecturii. Continuat de `LEARNING_CORE_CONTRACTS.md` (Faza 2 — contracte detaliate între componente).

---

## 0. Notă metodologică — ce am verificat, nu presupus

Înainte de a proiecta orice, am citit efectiv (nu am ghicit) următoarele surse din repo:

- **ADR-urile existente**: `architecture/ADR-001` (LEAGUE_PROVIDERS canonic), `ADR-002` (shadow testing), `ADR-003` (cache 2 nivele, neimplementat), `ADR-004` (bucla de învățare continuă), `docs/00_GOVERNANCE/ADR-005`, `ADR-006` (odds persistence governance).
- **`docs/00_GOVERNANCE/FROZEN_REGISTRY.md`** — registrul de documente Frozen și regula de guvernanță (orice schimbare de model de date/contracte/responsabilități necesită un ADR nou).
- **`docs/03_ENGINE/FEATURE_ENGINEERING_ROADMAP.md`** și **`REST_DAYS_VALIDATION.md`** — disciplina de validare empirică deja aplicată în proiect.
- **Codul propriu-zis**: `shadow_testing.py`, `ml_predictor.py`, `recalibration.py`, `oracle_engine.py` (secțiunile de recalibrare/ML/shadow), `sync/run_daily.py`, `sync/sync_results.py`, `database/queries.py`, `supabase_client.py`, `database/migrations/001_odds_history.sql`, `mappings.py` (`LEAGUE_PROVIDERS`), `config.json`, `weights.json`.

**Gol de trasabilitate semnalat explicit**: `FROZEN_REGISTRY.md` declară `FROZEN` documentele `ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md` — dar **niciunul dintre acestea nu există fizic în acest repository** (verificat prin căutare completă a arborelui de fișiere, la data proiectării). Nu se poate verifica conformitatea acestei propuneri cu conținutul lor exact — doar cu tot ce e verificabil direct (ADR-urile 001–006, `ODDS_PERSISTENCE_DESIGN.md`, și codul curent). Acest gol e tratat ca risc explicit în §8, nu ascuns.

---

## 1. Obiective

1. Testare automată a modelelor/algoritmilor noi, fără intervenție manuală la fiecare candidat.
2. Istoric complet, interogabil, al tuturor experimentelor (nu doar rezultatul final).
3. Comparație formală Champion vs. Challenger, pe aceleași metrici deja standardizate în proiect (Brier, Log-loss, Accuracy).
4. Promovare automată a unui model **doar** dacă e demonstrabil mai bun statistic.
5. Extensibilitate — algoritmi noi se adaugă fără a modifica nucleul (Model Registry, nu `if/elif` în cod existent).
6. Compatibilitate deplină cu arhitectura actuală (Poisson/Monte Carlo, XGBoost, weights.json, config Supabase).
7. Respectarea tuturor ADR-urilor și documentelor Frozen existente și verificabile.
8. Extensibilitate pe termen lung (ani, nu luni).

---

## 2. Principii arhitecturale

Aceste principii nu sunt inventate — sunt **extrase din tiparele deja validate** în proiect (ADR-001…006, `shadow_testing.py`, `recalibration.py`) și aplicate consecvent Learning Core-ului.

| # | Principiu | Sursă în proiect |
|---|---|---|
| P1 | **Aditiv, niciodată invaziv.** Orice componentă nouă e opt-in prin feature flag (`*_enabled`, implicit `False`), niciodată implicită. Producția nu e afectată de un experiment activ. | ADR-002 (`shadow_mode_enabled`), ADR-004 (`auto_recalibration_enabled`, promis dar neimplementat) |
| P2 | **O singură sursă de adevăr per concept.** Nu se duplică logică sau stare — se derivă. | ADR-001 (`LEAGUE_PROVIDERS`), `experiment_registry` ("SINGURA sursă de adevăr pt status") |
| P3 | **Promovare = decizie informată, niciodată efect secundar automat al sincronizării.** | ADR-002 ("promovare — DOAR manuală"), ADR-004 |
| P4 | **Validare statistică simultană pe metrici multiple, nu una singură.** Un candidat e "mai bun" doar dacă Brier + Log-loss + Accuracy sunt *toate trei* semnificativ mai bune. | `shadow_testing.evaluate_experiment()` |
| P5 | **Interfețe înlocuibile prin registry, nu prin ramificare de cod.** Un test statistic nou, un algoritm nou, o sursă de date nouă — se adaugă o intrare într-un dict, fără să atingă logica de orchestrare. | `STATISTICAL_TESTS` (shadow_testing.py), `LEAGUE_PROVIDERS` (mappings.py) |
| P6 | **Funcții pure separate de I/O.** Logica de decizie (recalibrare, evaluare statistică) nu are dependințe de Supabase/disc — primește stare, întoarce stare nouă + rezultat structurat. I/O e responsabilitatea apelantului. | `recalibration.py` (docstring explicit) |
| P7 | **Disciplină cronologică strictă — zero scurgere temporală.** Orice antrenare/evaluare nouă respectă walk-forward (expanding window), niciodată split aleator. | `ml_predictor._walk_forward_validate()` |
| P8 | **Guvernanță prin ADR, nu editare tăcută.** Orice schimbare de model de date, contract sau responsabilitate = ADR nou. Detaliile de implementare nu necesită ADR. | `FROZEN_REGISTRY.md` — Change Policy |
| P9 | **Nu se inventează valori pentru a umple un gol.** O stare necunoscută rămâne explicit "necunoscut"/"insuficiente date", nu se presupune. | ADR-001 (`supported: "necunoscut"`), `shadow_testing` (`status="insufficient_data"`) |
| P10 | **UTC peste tot, fără excepție.** | ADR-006 (clarificarea #2) |

---

## 3. Componentele Learning Core

Toate componentele de mai jos sunt **noi**, construite ca strat suplimentar peste infrastructura deja existentă (`shadow_testing.py`, `ml_predictor.py`, `recalibration.py`) — niciuna nu o înlocuiește.

### 3.1 Model Registry (nou)

Catalog canonic al tuturor algoritmilor de predicție disponibili, analog cu tiparul deja validat `STATISTICAL_TESTS` (shadow_testing.py) și `LEAGUE_PROVIDERS` (mappings.py) — un dict populat static, niciodată prin `if/elif` distribuit în cod.

Fiecare algoritm respectă o interfață uniformă `LearningAlgorithm` (vezi §6). La lansarea v4.1, registry-ul conține **exact cei doi algoritmi deja existenți**, înveliți în adaptoare subțiri:
- `poisson_montecarlo` — adaptor peste motorul deja existent în `oracle_engine.py` (Poisson + Monte Carlo + blend ELO).
- `xgboost_v1` — adaptor peste `ml_predictor.MLPredictorEngine` deja existent (walk-forward validation inclus, neschimbat).

Adăugarea unui algoritm nou (ex. LightGBM, ELO ofensiv/defensiv separat — roadmap #5) înseamnă exclusiv o nouă intrare în acest registry — zero schimbare în Training Runner, Promotion Gate sau StatisticsEngine.

### 3.2 Training Runner / Experiment Orchestrator (nou)

Automatizează ciclul "ia un algoritm din Model Registry → antrenează-l (sau reantrenează-l) → generează predicții shadow pentru meciurile viitoare → loghează". Nu reimplementează logging-ul — apelează direct `shadow_testing.log_shadow_prediction()` deja existent, cu `experiment_group="treatment"` pentru challenger și `experiment_group="control"` pentru campionul curent (câmpul `experiment_group` există deja în schema `shadow_predictions`, dar azi e folosit doar cu valoarea implicită `"treatment"`).

Fiecare rulare de antrenare produce o intrare persistată în `training_runs` (§5) — hiperparametri, feature set folosit, dimensiune eșantion, metrici de walk-forward, durată, cod/versiune. Aceasta e diferența față de `shadow_predictions` (care loghează *predicții*, per meci) — `training_runs` loghează *antrenări*, per rulare.

### 3.3 Champion Registry (nou)

**Gol identificat în arhitectura actuală**: nu există azi un pointer explicit, versionat, interogabil, la "care e campionul curent". Campionul e azi *implicit* — starea curentă din `weights.json`/`model_config`, fără istoric formal al schimbărilor de campion (doar `baseline_model_version`, un string liber, folosit ca etichetă, nu ca referință structurată).

`model_champions` (tabelă nouă, §5) rezolvă asta: un rând per `(algorithm_family, league_scope)`, cu pointer către `training_run_id`-ul curent activ ca și campion, plus istoric (`promoted_at`, `promoted_by`, `superseded_by` — exact tiparul deja folosit în `experiment_registry.deprecate_experiment()`).

### 3.4 Promotion Gate (nou, strat subțire)

Nu reimplementează regula de promovare — o **aplică**, peste `evaluate_experiment()` deja existent. Diferența e un singur flag nou, `auto_promotion_enabled` (implicit `False`, per P1):

- `False` (implicit, comportament identic cu azi): rezultatul `evaluate_experiment()` ajunge la `candidate_for_promotion` și **se oprește acolo** — exact ca azi. Un om decide, apelează `promote_experiment()` manual.
- `True` (necesită ADR dedicat înainte de activare în producție — vezi §8, riscul R1): dacă status-ul e `candidate_for_promotion`, Promotion Gate apelează automat `promote_experiment()` **și** actualizează `model_champions` cu noul pointer. `promoted_by` se populează cu `"learning_core_auto"` (câmp deja existent în schema `experiment_registry`, folosit azi doar cu nume de om) — trasabilitatea rămâne identică, doar sursa promovării e explicit marcată ca automată, nu ascunsă.

### 3.5 Statistics Engine (reutilizat, neschimbat la v4.1)

`shadow_testing.STATISTICAL_TESTS` — deja proiectat explicit extensibil ("viitor: mcnemar, diebold_mariano, bayesian — fără schimbare de logică", comentariu deja prezent în cod). Learning Core îl consumă ca atare, fără nicio modificare la v4.1.

### 3.6 Reconciliere: recalibrarea legacy devine un algoritm din registry

**Decizie de design centrală a acestui document.** Codul curent din `sync/sync_results.py` (funcția `_recalibrate_for_result`) apelează **necondiționat** `recalibrate_weights()` la fiecare rezultat nou — exact fluxul pe care ADR-004 îl declară incompatibil cu restul arhitecturii și programează pentru dezactivare printr-un feature flag (`auto_recalibration_enabled: false`) **care nu a fost încă implementat**. Acesta nu e un gol pe care l-am inventat — e documentat explicit chiar în ADR-004 și în `CHANGELOG.md` ("cunoscut, neschimbat în această versiune").

Propunerea acestui document: în loc să tratăm asta ca pe un simplu "bug de închis", **recalibrarea per-ligă (`recalibration.py`) devine ea însăși un algoritm înregistrat în Model Registry** (`league_weights_adaptive`), rulat prin exact aceeași disciplină Champion/Challenger ca XGBoost sau Poisson/MC — nu mai are o cale de execuție separată, necondiționată, în afara buclei de învățare. Asta rezolvă simultan:
- gol-ul cunoscut din ADR-004 (flag-ul promis, niciodată scris);
- principiul P2 (o singură cale de "învățare", nu două mecanisme paralele care pot să se contrazică).

---

## 4. Fluxul complet al datelor

Extensie directă a buclei deja descrise în ADR-004 — pașii **1-6** sunt identici cu azi (neschimbați), pașii **7-9** sunt noi (Learning Core):

```
1. fixtures → results → match_history
2. → ELO (sync/calculate_elo.py) → formă → standings          [neschimbat]
3. → shadow evaluation (shadow_testing.evaluate_all_active_experiments)
                                                                 [neschimbat, reutilizat]
4. → Odds Persistence (services/odds_persistence_service.py)  [neschimbat, Frozen, în afara scope-ului]
                                                                 │
                                                                 ▼
5. ══════════════════ LEARNING CORE (nou, de la acest punct) ══════════════════

   5a. Training Runner
       pentru fiecare algoritm activ din Model Registry
       (poisson_montecarlo | xgboost_v1 | league_weights_adaptive | ...):
         → antrenează/actualizează pe date walk-forward (P7)
         → scrie o intrare nouă în training_runs
         → generează predicții pt meciuri viitoare (challenger)
         → log_shadow_prediction(experiment_group="treatment")
       campionul curent (din model_champions) generează în paralel
         → log_shadow_prediction(experiment_group="control")

   5b. Statistics Engine (shadow_testing.STATISTICAL_TESTS, neschimbat)
       compară treatment vs. control pe Brier + Log-loss + Accuracy

   5c. Promotion Gate
       evaluate_experiment() → status în experiment_registry
         "insufficient_data" → așteaptă mai multe meciuri
         "monitoring"        → așteaptă continuare
         "rejected"           → deprecate_experiment(), se oprește
         "candidate_for_promotion":
             auto_promotion_enabled == False → se oprește, așteaptă om (P3, implicit)
             auto_promotion_enabled == True  → promote_experiment()
                                                → model_champions actualizat
                                                → (§8, R1: necesită ADR dedicat)

   ════════════════════════════════════════════════════════════════════════════

6. → (doar dacă a existat o promovare, manuală SAU automată)
     aplicare efectivă: weights.json / model_config actualizat cu noul campion
```

Orchestrarea intră în `sync/run_daily.py` ca **pas nou, opțional** (`learning_core_enabled`, implicit `False` la v4.1) — între pasul actual 3 (shadow evaluation) și pasul actual 5 (ML retraining), păstrând ordinea deja stabilită de ADR-004.

---

## 5. Responsabilitatea fiecărui modul

| Modul | Responsabilitate | Nu face |
|---|---|---|
| **Model Registry** (`learning_core/registry.py`, propunere de nume) | Catalogul static al algoritmilor disponibili + adaptoarele lor la interfața comună. | Nu antrenează, nu evaluează, nu decide nimic — pur catalog. |
| **Training Runner** | Orchestrează antrenarea/regenerarea predicțiilor pentru fiecare algoritm activ; scrie `training_runs`; apelează `shadow_testing.log_shadow_prediction()` deja existent. | Nu decide promovarea. Nu atinge `weights.json`/`model_config` direct. |
| **`training_runs`** (tabelă) | Istoric complet, per rulare de antrenare: cine, când, cu ce date, ce metrici de walk-forward. | Nu ține predicții per meci (asta rămâne `shadow_predictions`). |
| **`model_champions`** (tabelă) | Pointer curent + istoric al campionilor, per `(algorithm_family, league_scope)`. | Nu recalculează metrici — doar referențiază un `training_run_id` deja evaluat. |
| **Promotion Gate** | Aplică regula de promovare (manuală sau automată, în funcție de flag) peste `evaluate_experiment()` deja existent. | Nu reimplementează testele statistice — le consumă din `StatisticsEngine`. |
| **Statistics Engine** (`shadow_testing.STATISTICAL_TESTS`) | Testul statistic propriu-zis (bootstrap, permutare, Wilcoxon, viitor: McNemar etc.). | Nu știe nimic despre algoritmi, campioni sau promovare — pur funcție matematică. |
| **`shadow_testing.py`** (existent, neschimbat) | Logging brut per predicție + agregare în `experiment_registry`. | Nu orchestrează antrenarea — doar loghează și evaluează ce i se dă. |
| **`recalibration.py`** (existent, neschimbat ca logică) | Funcția pură de ajustare a ponderilor per ligă. | Nu mai decide singură *când* rulează — decizia trece la Training Runner + Promotion Gate (§3.6). |
| **`ml_predictor.py`** (existent, neschimbat) | XGBoost + walk-forward validation. | Rămâne utilizabil manual (UI, `Setări → ML`) exact ca azi — Learning Core îl învelește, nu-l înlocuiește. |

---

## 6. Interfețele dintre module

Prezentate ca **forma contractului**, nu ca implementare (analog cu felul în care ADR-001/002 din proiect deja schițează interfețe cu `@dataclass`, fără cod funcțional complet):

```
LearningAlgorithm (protocol comun, implementat de fiecare adaptor din Model Registry)
    name: str                          # "poisson_montecarlo" | "xgboost_v1" | "league_weights_adaptive" | ...
    version: str
    league_scope: str | "all"
    fit(training_data) -> TrainingRunResult
    predict(features: dict) -> (prob_home, prob_draw, prob_away, metadata: dict)
    describe() -> dict                 # hiperparametri, feature set — pentru training_runs

TrainingRunResult
    training_run_id: str
    status: "trained" | "insufficient_data" | "error"
    samples_used: int
    walk_forward_metrics: dict         # {accuracy, log_loss, brier_score, folds: [...]}
                                        # — reutilizează exact formatul deja produs de
                                        #   ml_predictor._walk_forward_validate()

Training Runner
    run_challenger(algorithm: LearningAlgorithm, league_scope, fixtures) -> TrainingRunResult
        — apelează algorithm.fit(), scrie training_runs,
          apoi pentru fiecare fixture viitor: algorithm.predict()
          → shadow_testing.log_shadow_prediction(experiment_group="treatment")

Promotion Gate
    evaluate_and_decide(experiment_name, experiment_version, league_scope) -> PromotionDecision
        — apelează shadow_testing.evaluate_experiment() (neschimbat)
        — dacă status == "candidate_for_promotion" și auto_promotion_enabled:
              shadow_testing.promote_experiment(..., promoted_by="learning_core_auto")
              actualizează model_champions
        — întoarce oricum decizia (util pentru raportare/UI, indiferent de auto sau manual)

PromotionDecision
    status: "insufficient_data" | "monitoring" | "rejected" | "candidate_for_promotion" | "promoted"
    auto_promoted: bool
    experiment_registry_row: dict      # rândul complet, pt audit/UI
```

**Contracte cu infrastructura existentă (neschimbate)**:
- `shadow_testing.log_shadow_prediction(...)` — semnătura rămâne exact cea din §3.2.
- `shadow_testing.evaluate_experiment(...)` / `promote_experiment(...)` / `deprecate_experiment(...)` — folosite ca atare.
- `supabase_client.load_config()` / `save_config()` — sursa pentru `learning_core_enabled`, `auto_promotion_enabled` (chei noi, aditive, în `model_config`, exact pattern-ul deja folosit pentru `shadow_mode_enabled`).

---

## 7. Ce rămâne neschimbat din proiectul actual

Această secțiune e la fel de importantă ca ce se construiește — Learning Core e proiectat să **nu atingă** nimic din ce funcționează deja validat:

- **Motorul Poisson + Monte Carlo** (`oracle_engine.py`, simularea propriu-zisă) — neschimbat, doar înfășurat de un adaptor.
- **Calculul ELO** (`sync/calculate_elo.py`) — neschimbat, rămâne feature de intrare, nu parte din Learning Core.
- **`feature_engine.py`** — neschimbat (formă, H2H). Decizia despre `rest_days_modifier()` (cod existent, neapelat) rămâne exact cea din `REST_DAYS_VALIDATION.md` (verdict: NU, fără câștig măsurabil) — Learning Core nu revine asupra ei.
- **`mappings.py` / `LEAGUE_PROVIDERS`** (ADR-001) — sursă canonică neschimbată, `league_scope` din Learning Core o refolosește ca atare.
- **Cache nivel 1** (`cache_manager.py`) și **quota** (`key_manager.py`) — neschimbate; ADR-003 (nivel 2, neimplementat) rămâne un proiect separat, doar menționat ca risc de scalare la §8.
- **`services/odds_persistence_service.py`** — complet în afara scope-ului (piață de cote, nu predicție); Frozen (ADR-005/006), nu se atinge.
- **`shadow_testing.py`** ca infrastructură — reutilizat integral, nu rescris.
- **`recalibration.py`** ca funcție pură — logica de calcul (praguri, coeficienți) rămâne exact cea din v1.1; se schimbă doar *cine o declanșează și când* (§3.6).
- **`ml_predictor.py`** — `MLPredictorEngine`, walk-forward validation, `MIN_SAMPLES_TO_TRAIN=30` — toate neschimbate; rămâne accesibil manual din UI exact ca azi.
- **Schema Supabase existentă** (`match_history`, `model_weights`, `shadow_predictions`, `experiment_registry`, `odds_history`) — neschimbată; Learning Core adaugă tabele noi, aditiv, nu modifică schema existentă.
- **`weights.json` / `config.json`** — format compatibil păstrat; chei noi adăugate aditiv (pattern deja aplicat consecvent, ex. ADR-001 §Consecințe).
- **`app.py`** (Streamlit UI) — neschimbat la v4.1; un tab nou "Learning Core" e propus abia la v4.2, read-only.

---

## 8. Riscuri și compromisuri

| # | Risc | Impact | Mitigare propusă |
|---|---|---|---|
| **R1** | **Conflict direct cu ADR-002** ("promovarea reală... e întotdeauna manuală"). Obiectivul #4 al acestui document cere promovare automată. | Arhitectural — o regulă deja Frozen ar fi contrazisă de un comportament implicit activ. | `auto_promotion_enabled` implicit `False` (comportament azi neschimbat). Activarea în producție necesită **un ADR nou, dedicat**, care să suprascrie explicit ADR-002 pentru acest caz — exact procesul cerut de `FROZEN_REGISTRY.md` (schimbare de "responsabilitate a componentei"). Nu se activează tacit. |
| **R2** | **Documente Frozen referențiate dar absente din repo** (`ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md`). | Nu pot verifica 100% conformitatea acestei propuneri cu contractele lor exacte — doar cu ce e verificabil (ADR-uri + cod). | Semnalat explicit (nu ascuns). Înainte de a începe implementarea reală, aceste documente trebuie fie localizate, fie recunoscute ca lipsă și tratate separat, guvernanțial. |
| **R3** | **`sync/sync_results.py` rulează încă necondiționat recalibrarea legacy**, contrazicând ADR-004. Coexistă azi *două* căi de "învățare" (legacy automată + shadow/experiment framework), care pot intra în conflict. | Corectitudine — Champion/Challenger n-are sens dacă campionul e rescris în paralel, în afara evaluării. | §3.6: recalibrarea legacy devine ea însăși un algoritm din registry, evaluat prin aceeași disciplină — nu o cale separată. Trebuie tratat ca prioritate #1 în v4.1 (închide un gol deja documentat, nu unul nou). |
| **R4** | **Volum de date mic per ligă/algoritm.** `min_matches=200` deja cerut de `evaluate_experiment()`; ligi ca Romania SuperLiga sau World Cup 2026 pot rămâne ani în `"monitoring"`. | Promovarea automată reală va fi rară, indiferent de câtă infrastructură se construiește — nu e o problemă de design. | Se acceptă explicit; UI-ul (v4.2) trebuie să arate clar "insuficiente date", nu să sugereze eroare. |
| **R5** | **Comparații multiple.** Cu N algoritmi × M ligi rulând simultan ca challengeri, crește rata de fals-pozitiv ("semnificativ mai bun" din zgomot pur). | Statistic — promovare automată eronată, pe termen lung. | Neadresat la v4.1/v4.2 (număr mic de experimente inițial). Corecție (Bonferroni/FDR) programată explicit pentru v5.0, înainte de a extinde numărul de challengeri simultani. |
| **R6** | **Trafic Supabase suplimentar.** Fiecare challenger nou dublează aproximativ volumul de shadow logging per meci; ADR-003 (cache nivel 2) încă neimplementat. | Cost/scalare, mai ales cu multiple instanțe (telefon/PC/Actions/Cloud) rulând simultan. | Semnalat ca dependință, nu blocare — Learning Core poate porni fără ADR-003, dar costul crește liniar cu numărul de experimente active; ADR-003 devine prioritar odată ce Learning Core ajunge la 3+ challengeri simultani. |
| **R7** | **Cost de guvernanță.** Orice extindere reală (tabele noi, contracte noi) necesită ADR dedicat, per `FROZEN_REGISTRY.md`. | Viteză de dezvoltare mai mică. | Acceptat explicit — exact tradeoff-ul deja asumat în ADR-002 ("cost... acceptat ca preț al siguranței pe termen lung"). |
| **R8** | **Cold start pentru `model_champions`.** Tabela nouă trebuie populată retroactiv cu campionii impliciți curenți (Poisson/MC, XGBoost) înainte ca primul challenger să aibă față de ce să fie comparat formal. | Bootstrap unic, cost mic dar obligatoriu. | Pas explicit în v4.1 — o singură scriere inițială, analog cu `sync/bootstrap_league_learning.py` deja existent pentru `weights.json`. |

---

## 9. Ce trebuie construit — v4.1 / v4.2 / v5.0

### v4.1 — Fundația (cost mic, risc zero pentru producție, totul implicit dezactivat)
- Model Registry + interfața `LearningAlgorithm` + 2 adaptoare (Poisson/MC, XGBoost) peste codul deja existent, neschimbat.
- Tabele noi (aditive): `training_runs`, `model_champions`.
- Bootstrap unic: populare `model_champions` cu starea curentă (R8).
- **Închiderea efectivă a golului din ADR-004**: `league_weights_adaptive` intră în Model Registry; `sync/sync_results.py` nu mai apelează recalibrarea necondiționat (R3) — devine un challenger ca oricare altul, gatat de `learning_core_enabled` (implicit `False`, deci comportament identic cu azi până la activare explicită).
- Training Runner — apelabil manual (CLI, similar cu `sync/run_daily.py --no-ml`), **nu încă în bucla zilnică automată**.
- ADR nou (guvernanță) care înregistrează formal acest document + deciziile din §3.6 și §8/R1, per `FROZEN_REGISTRY.md` — **notă**: per decizia din Directiva de Guvernanță, acest ADR nu se creează încă; se decide după persistarea și revizuirea documentelor Faza 1/Faza 2.

### v4.2 — Automatizare parțială (promovare tot manuală implicit)
- Integrare Training Runner în `sync/run_daily.py`, ca pas opțional (`learning_core_enabled` flag).
- Promotion Gate complet implementat, dar `auto_promotion_enabled=False` implicit — generează `candidate_for_promotion`, promovarea rămâne manuală (identic cu ADR-002 azi).
- Al doilea algoritm real nou din Model Registry (ex. ELO ofensiv/defensiv separat, roadmap #5, sau LightGBM) — prima validare reală că un algoritm nou nu atinge nucleul.
- UI Streamlit — tab nou "Learning Core" (read-only): campion curent, challengeri activi, istoric `training_runs`/`experiment_registry`. Nicio scriere din UI.

### v5.0 — Promovare automată reală, cu toate gărzile
- Activare opțională `auto_promotion_enabled=True` — condiționată de ADR-ul dedicat cerut la R1.
- Corecție comparații multiple (Bonferroni/FDR) — R5.
- Extindere `StatisticsEngine` (McNemar, Diebold-Mariano, Bayesian — deja schițate ca plan în `shadow_testing.py`).
- ADR-003 (cache nivel 2) implementat, dacă numărul de challengeri simultani a crescut suficient să justifice costul (R6).
- Rollback automat: dacă un campion promovat degradează pe fereastra live următoare, revenire la campionul anterior din `model_champions` (mecanism simetric cu promovarea, aceleași tabele).

---

## 10. Diagramă logică a arhitecturii complete

```
                         ┌─────────────────────────────────────────────┐
                         │   Provideri externi (odds, meciuri, ELO)    │
                         └───────────────────────┬───────────────────────┘
                                                 ▼
                         ┌─────────────────────────────────────────────┐
                         │  Ingestie + normalizare (sync/, mappings.py) │
                         │  [NESCHIMBAT]                                │
                         └───────────────────────┬───────────────────────┘
                                                 ▼
                         ┌─────────────────────────────────────────────┐
                         │  match_history / ELO / formă / standings     │
                         │  [NESCHIMBAT]                                 │
                         └───────────────────────┬───────────────────────┘
                                                 ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │                    LEARNING CORE (v4.1+, nou)                       │
        │                                                                      │
        │   ┌───────────────┐        ┌──────────────────────┐                │
        │   │ Model Registry │───────▶│   Training Runner     │               │
        │   │ (catalog static)│       │ (orchestrare, nou)    │               │
        │   │                │        └──────────┬───────────┘               │
        │   │ poisson_mc     │                   │                            │
        │   │ xgboost_v1     │                   ▼                            │
        │   │ league_weights_│        ┌──────────────────────┐                │
        │   │   adaptive     │        │   training_runs       │  (tabelă nouă)│
        │   │ [+ viitori]    │        │   (istoric antrenări)  │               │
        │   └───────────────┘        └──────────┬───────────┘                │
        │                                        │                            │
        │                                        ▼                            │
        │                     ┌──────────────────────────────────┐            │
        │                     │  shadow_predictions (EXISTENT)     │            │
        │                     │  control = campion curent           │           │
        │                     │  treatment = challenger nou          │          │
        │                     └──────────────────┬──────────────────┘           │
        │                                        ▼                              │
        │                     ┌──────────────────────────────────┐             │
        │                     │  Statistics Engine (EXISTENT)      │             │
        │                     │  bootstrap / permutation / wilcoxon │            │
        │                     └──────────────────┬──────────────────┘           │
        │                                        ▼                              │
        │                     ┌──────────────────────────────────┐             │
        │                     │  experiment_registry (EXISTENT)    │             │
        │                     │  insufficient_data → monitoring →   │            │
        │                     │  candidate_for_promotion / rejected │            │
        │                     └──────────────────┬──────────────────┘           │
        │                                        ▼                              │
        │                     ┌──────────────────────────────────┐             │
        │                     │      Promotion Gate (nou)          │             │
        │                     │  auto_promotion_enabled?            │            │
        │                     │   False → oprire, așteaptă om (P3)  │            │
        │                     │   True  → promote_experiment()       │           │
        │                     └──────────────────┬──────────────────┘           │
        │                                        ▼                              │
        │                     ┌──────────────────────────────────┐             │
        │                     │   model_champions (tabelă nouă)    │             │
        │                     │   pointer curent per (algo, ligă)   │            │
        │                     └──────────────────┬──────────────────┘           │
        └────────────────────────────────────────┼──────────────────────────────┘
                                                 ▼
                         ┌─────────────────────────────────────────────┐
                         │ Aplicare efectivă: weights.json / model_config│
                         │ [doar dacă a existat promovare — manuală sau  │
                         │  automată]                                    │
                         └───────────────────────┬───────────────────────┘
                                                 ▼
                         ┌─────────────────────────────────────────────┐
                         │  Prediction live (oracle_engine.py, blend)   │
                         │  [NESCHIMBAT] → Streamlit UI → Value Betting  │
                         └─────────────────────────────────────────────┘

  Complet neatins de Learning Core: services/odds_persistence_service.py
  (Frozen, ADR-005/006 — piață de cote, nu predicție).
```

---

## 11. Rezumat pentru decizie

Acest document nu propune o rescriere — propune un **strat suplimentar, opt-in, peste infrastructura deja construită și validată** (`shadow_testing.py`, `ml_predictor.py`, `recalibration.py`). Singurul punct care necesită o decizie de guvernanță explicită, înainte de implementare, e **R1**: activarea reală a promovării automate contrazice ADR-002 așa cum e scris azi, și are nevoie de un ADR nou, dedicat, care s-o suprascrie — exact procesul pe care `FROZEN_REGISTRY.md` îl cere pentru orice schimbare de responsabilitate a unei componente.

Continuat de `LEARNING_CORE_CONTRACTS.md` (Faza 2), care detaliază contractele exacte dintre cele 18 componente ale acestui sistem. Decizia privind un eventual ADR de acceptare formală a ambelor documente se ia după persistarea și revizuirea lor completă, per Directiva de Guvernanță a Proiectului.
