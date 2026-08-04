# Machine Learning Engine — Proiectare completă

**Status**: DRAFT — document de arhitectură și proiectare, NU un ADR. Nu decide, nu autorizează, nu modifică nimic din cod. Nu modifică și nu reinterpretează ADR-051.
**Precondiție**: ADR-051 (Three Independent Engines Vision, ACCEPTED) — document de referință, obligatoriu, necontestat aici.
**Precondiții tehnice deja închise, reutilizate ca atare**: ADR-048 (persistare artefact model, `main`), ADR-049 (calibrare Temperature Scaling, ACCEPTED, neimplementat încă), ADR-050 (Challenger Framework extins pt. algoritmi compuși, ACCEPTED), ADR-030 (Continuous Learning, FROZEN), Blend Engine (`blend_engine.py`, implementat, activ în producție pentru afișare).
**Metodologie**: citire directă de cod (`ml_predictor.py`, `feature_engine.py`, `learning_core/*`), citire integrală a documentelor de guvernanță existente (ADR-030/049/050, `ML_ACTIVATION_GATE.md`, `ML_ENGINE_AUDIT.md`, `ORACLE_VS_ML_REPORT.md`, `LEARNING_CORE_ARCHITECTURE.md`, `RUNTIME_CONTRACT.md`, roadmap-urile din `docs/03_ENGINE/`), verificare live a schemei și volumului de date (Supabase, proiect `Prediction`, 2026-08-04). Nicio afirmație de mai jos nu e presupusă — fiecare cifră e verificată live sau citată dintr-un document existent.

---

## 0. Rezumat executiv — ce e deja construit, ce lipsește, ce se propune

Football Oracle are deja **cea mai mare parte a infrastructurii unui motor ML complet** — nu de la zero. Ce există azi, funcțional, verificat:

| Componentă | Stare |
|---|---|
| Antrenare walk-forward, zero scurgere temporală | ✅ Funcțional, `ml_predictor._walk_forward_validate()` |
| Persistare artefact model (versionat, reîncărcabil) | ✅ Închis (ADR-048) |
| Calibrare post-hoc (Temperature Scaling) | ✅ Decis (ADR-049), **neimplementat încă** |
| Model Registry, interfață `LearningAlgorithm` pluggable | ✅ Funcțional, deja 4 adaptoare (`xgboost_v1`, `blend_v1`, `league_weights_adaptive`, `production_champion`) |
| Challenger FSM, shadow testing, evaluare statistică simultană (Brier+LogLoss+Accuracy) | ✅ Funcțional, `shadow_testing.evaluate_experiment()` |
| Promotion Engine, Champion Manager (2 scriitori, atomic prin RPC) | ✅ Funcțional |
| Champion Guardian (sănătate campion, 4 dimensiuni) + Rollback Engine | ✅ Funcțional, cod complet, **dezactivat azi** (`champion_guardian_enabled=False`) |
| Orchestrare Continuous Learning (A→B→D→C, generică peste Model Registry) | ✅ Funcțional, ADR-030 |
| Compound algorithm support (Blend ca al doilea `algorithm_family`) | ✅ Funcțional, ADR-050, precedent direct pt. extensibilitate |

Ce **lipsește real**, confirmat prin cod + date live, nu presupus:

1. **Criza de acoperire a feature-urilor** — cele 10 feature-uri „core" (rating/formă/ELO/H2H) au 99,5% acoperire, dar cele 4 feature-uri derivate (corner/card/foul/shot dominance) au doar **17,1%** (9.225/53.777, verificat live azi). ~83% din antrenare are semnal zero pe aceste 4 coloane. **Precizare verificată ulterior**: acest 17,1% vine în mare parte de la un provider mai vechi (Soccer Football Info, Sprint 1/ADR-041), NU de la Flashscore. Flashscore scrie în aceleași coloane brute (`home_shots`/`home_corners`/`home_fouls`/`home_yellow_cards`/`home_possession`, via `providers/flashscore/normalizer.py::normalize_match_statistics()`) și rulează deja automat, zi și noapte (`night_sync.yml`, zilnic 03:00 UTC; `live_sync.yml`, Delta Sync la 4h) — dar a capturat până azi pagina de statistici pentru doar **330 de meciuri** (verificat live, `flashscore_raw_extraction`, `tab_name='stats'`), din cele 53.777 din `match_history`. Motivul: ~89% din `match_history` (47.653 rânduri) provine dintr-un import istoric masiv (Kaggle/football-data.co.uk), din ani dinaintea existenței pipeline-ului Flashscore în proiect — Flashscore capturează doar meciuri NOI, de acum înainte, nu poate completa retroactiv istoricul deja importat. Coverage-ul va crește organic, zilnic, dar nu va rezolva singur golul din istoricul vechi.
2. **ELO domină covârșitor** — permutation importance pe date reale: `away_elo`=0,049, `home_elo`=0,036, toate celelalte 8 feature-uri sub 0,003 fiecare (`PREDICTOR_ROADMAP_V4.md` §2.3). Modelul e, empiric, aproape un clasificator ELO cu zgomot.
3. **Zero online/incremental learning** — fiecare antrenare e un retrain complet de la zero pe tot istoricul; „continuu" înseamnă azi doar „cadență zilnică", nu „învățare incrementală".
4. **Fragmentare identitate ligă** — verificat live: `E1`, `E2`, `E3`, `SP2`, `F2`, `I2`, `ARG`, `USA`, `EC` apar ca valori brute `league` alături de `Premier League`/`La Liga`/etc. — probabil aceleași competiții duplicate sub coduri diferite (backlog cunoscut, neînchis).
5. **ROI neverificabil azi** — `odds_history` are 1.668 rânduri vs. 53.777 în `match_history`; join fiabil meci↔cotă nerezolvat.
6. **Bug de coupling cunoscut, real**: `consensus_validation.compute_metrics()` ia necondiționat doar primele 2 motoare din `raw_predictions` (`a, b = engines[0], engines[1]`) — al treilea motor (ML) va fi ignorat silențios la validarea de consens dacă nu e reparat înainte de conectare.
7. **Confuzie de scop, de clarificat explicit** (secțiunea 9) — `ML_ACTIVATION_GATE.md` guvernează altă întrebare (blending ÎN predicția Oracle servită) decât cea relevantă azi (afișarea independentă a vocii ML, mirror exact al Blend Engine) — cele două nu trebuie confundate în roadmap.

Propunerea centrală a acestui document: **Machine Learning Engine nu se construiește de la zero** — se construiește prin (a) o interfață subțire nouă (`ml_engine.py`, simetrică cu `blend_engine.py`) peste infrastructura deja existentă și validată, (b) închiderea celor 2-3 goluri structurale reale identificate mai sus, înainte de orice extindere de feature-uri sau algoritm nou, (c) un roadmap în etape mici, reversibile, fiecare validată independent.

---

## 1. Obiectiv

### Ce trebuie să optimizeze ML Engine

**Obiectiv primar**: calitatea probabilistică a propriei predicții — Brier Score și Log Loss minime, calibrare cât mai apropiată de identitate (confidence raportată ≈ acuratețe reală), măsurate întotdeauna walk-forward, niciodată pe date văzute la antrenare.

**Obiectiv secundar, explicit subordonat**: să descopere tipare pe care Oracle nu le modelează explicit — relații neliniare/interacțiuni între feature-uri (ex. combinația formă+ELO+H2H într-un anumit interval, pe care o formulă Poisson aditivă din `calibrate_xg()` nu le poate reprezenta prin construcție). Acesta e motivul real de a avea un al doilea motor, nu doar redundanță.

**Metrică explicit NU de optimizat ca obiectiv principal**: acuratețea brută (procent de meciuri corect clasificate). Motiv: cu o distribuție reală a rezultatelor de 44,5%/25,4%/30,1% (Home/Draw/Away, verificat pe eșantionul din `ORACLE_VS_ML_REPORT.md`), un clasificator care prezice mereu „Home" atinge 44,48% — acuratețea singură nu diferențiază un model util de un model leneș. Brier/Log-loss penalizează încrederea greșită, acuratețea nu.

### Ce NU trebuie să optimizeze

- **Nu trebuie optimizat să reproducă Oracle.** Dacă un experiment viitor ar propune "adăugăm predicția Oracle ca feature de intrare pentru ML", asta ar transforma ML într-un corector marginal al lui Oracle, nu într-o a doua opinie independentă — practica actuală de a EXCLUDE `home_xg_pred`/`prob_*_pred`/`mc_prob_*` din `FEATURE_COLUMNS` (deja făcut, prin ablație reală, importanță exact 0.0000) e corectă și trebuie păstrată ca regulă permanentă, nu doar coincidență istorică.
- **Nu trebuie optimizat ROI/profitabilitate pariuri ca obiectiv de antrenare.** Motivele: (a) obiectivul de business real e calitatea probabilistică, nu maximizarea unui semnal de piață care poate fi zgomotos/manipulat de mișcări de cotă; (b) infrastructura de măsurare ROI e azi nefuncțională (§6) — nu poate fi folosită nici măcar ca metrică de validare, darămite de optimizare; (c) optimizarea directă pe ROI ar introduce un risc real de overfitting pe anomalii de piață, nu pe fotbal. ROI rămâne strict o metrică experimentală de raportare (§6), niciodată funcție obiectiv.
- **Nu trebuie optimizat separat per ligă, azi.** Mecanismul de ponderi per-ligă există (`resolve_league_weights()`) dar e inert (confirmat live, `sample_count=0` pentru toate cele 11 ligi urmărite) — orice optimizare per-ligă ar necesita mai întâi o strategie reală de acumulare a acelui semnal, tratată separat, nu implicit aici.
- **Nu trebuie optimizat prin adăugare necondiționată de feature-uri.** Regula ML deja existentă în CLAUDE.md (dovadă de ablație, nu presupunere) rămâne neschimbată — orice feature nou propus în §3 trece prin același test, nu intră implicit în `FEATURE_COLUMNS`.

---

## 2. Date

### Ce poate consuma azi (verificat live, 2026-08-04)

| Sursă | Rânduri | Stare |
|---|---|---|
| `match_history` (antrenare primară) | 53.777 total, 53.484 cu `actual_result` | Sursă primară, via `supabase_client.get_training_data()` |
| — coloane „core" (rating/formă/ELO/H2H) | 53.508/53.777 (99,5%) | Acoperire bună |
| — coloane derivate (corner/card/foul/shot dominance) | 9.225/53.777 (17,1%) | **Acoperire slabă**, gate real |
| `elo_history` | 39.575 | **Scris, niciodată citit** — zero SELECT confirmat în cod |
| `odds_history` | 1.668 | Insuficient pt. orice feature/validare bazată pe cotă |
| `flashscore_match_context` | 4.362 | Foundation Data Layer, în creștere |
| `flashscore_data_completeness` | 330 | Scor de completitudine per meci, neexploatat ca semnal ML |
| `team_health_snapshot` (accidentări) | 4 | Practic gol |
| `weather_forecast_cache` | 1 | Practic gol |

### Ce NU ar trebui să folosească

1. **Predicțiile Oracle proprii** (`home_xg_pred`, `prob_*_pred`, `mc_prob_*`) — deja exclus, cu dovadă de ablație (importanță 0.0000 pe 53.409 meciuri). Motiv arhitectural, nu doar empiric: a le include ar transforma ML într-un derivat al lui Oracle, contrar rolului de „al doilea expert independent" (ADR-051 §2.2).
2. **Orice statistică finală a meciului însuși ca predictor pentru rezultatul aceluiași meci** (`home_shots`, `home_corners`, `home_ht_goals` etc. din `match_history`) — acestea sunt cunoscute DOAR după fluierul final. `FEATURE_COLUMNS` de azi respectă deja acest principiu corect: `corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` sunt calculate din `*_avg_recent` (medii glisante din meciuri ANTERIOARE), niciodată din statisticile brute ale meciului curent. **Regulă de păstrat explicit, verificabilă mecanic** — orice feature nou propus trebuie să treacă acest test înainte de a intra în `FEATURE_COLUMNS`.
3. **Cote de închidere (closing odds)** — dacă vreodată un semnal de piață devine feature ML, doar cota de deschidere (opening odds, cunoscută înainte de meci) e validă; cota de închidere încorporează informație survenită după momentul predicției (accidentări de ultim moment, mișcări de piață) — risc real de scurgere temporală, de stabilit ca regulă ÎNAINTE să apară tentația, nu după.
4. **`used_for_training`** (coloană existentă în `match_history`, origine în pipeline-ul de import/reconciliere ADR-024/036) — nu e folosită azi de `get_training_data()` ca filtru; scopul ei exact rămâne neclar din cercetarea acestui document (posibil semantică de deduplicare istorică, nu de excludere din antrenare). **Necesită clarificare înainte de a fi eventual folosită ca semnal de includere/excludere** — nu se presupune.

### Riscuri de data leakage — verificate, nu presupuse

| Risc | Stare |
|---|---|
| Imputare cu mediană globală calculată pe tot setul (inclusiv viitor) | **Deja identificat și corectat** — cod actual nu impută deloc, lasă NaN nativ pentru XGBoost (comentariu explicit în `ml_predictor.py`, fix documentat 2026-07-14) |
| Calibrare (Temperature Scaling) antrenată pe date de antrenare, nu pe out-of-fold | **Deja prevenit prin design** — ADR-049 §5 alege explicit sursa OOF din walk-forward, opțiunea „pe date de training" explicit respinsă |
| Normalizare inconsistentă a numelor de echipe → confuzie de identitate în ELO/H2H | **Parțial rezolvat** (P3.5, Faza 1 din 3) — scriitorii zilnici normalizează acum, dar **istoricul existent (10,1% din `match_history`, 10.835 apariții „stray") nu a fost consolidat retroactiv** — risc rezidual real pentru orice feature derivat din ELO/H2H pe rândurile vechi |
| Deduplicare meciuri canonice (`superseded_by`) | Rezolvat — `get_training_data()` filtrează explicit `superseded_by IS NULL` |

### Informații care ar trebui eliminate/tratate cu atenție

- **Fragmentarea identitate ligă** (`E1`/`E2`/`E3`/`SP2`/`F2`/`I2`/`ARG`/`USA`/`EC` vs. nume complete) — afectează direct capacitatea de validare „robustețe între ligi" cerută la §6; un model per-ligă sau o metrică per-ligă calculată azi ar număra greșit aceeași competiție ca mai multe entități distincte. **Recomandare**: normalizare canonică a `league` înainte de orice analiză de robustețe per-ligă serioasă — flagat, nu rezolvat aici (backlog existent, necesită propriul task).

---

## 3. Feature Engineering

### Ce există deja (14 coloane, `ml_predictor.FEATURE_COLUMNS`)

| Grup | Feature-uri | Acoperire live |
|---|---|---|
| **Forță echipă** | `home/away_offensive_rating`, `home/away_defensive_rating` | 99,5% |
| **Formă recentă** | `home/away_form_score` | 99,5% |
| **Rating relativ (ELO)** | `home/away_elo` | 99,5% |
| **Istoric direct** | `h2h_modifier`, `h2h_meetings` | 99,5% |
| **Dominanță recentă (derivate)** | `corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance` | **17,1%** |

Fiecare din cele 4 feature-uri derivate a intrat prin ablație reală (ADR-012/013/021), cu câștig măsurat simultan pe accuracy/log-loss/Brier — disciplina e corectă. Problema nu e alegerea conceptuală (§6 din `PREDICTOR_ROADMAP_V4.md` confirmă independent: setul conceptual e rezonabil), problema e acoperirea reală în date.

### Ce lipsește — evaluat, nu doar enumerat

| Candidat | Sursă | Cost | Risc leakage | Prioritate |
|---|---|---|---|---|
| **ELO Trend** (pantă recentă, nu doar valoare curentă) | `elo_history` (39.575 rânduri, 100% scrise, 0% citite) | Scăzut — date deja există | Zero | **Cea mai bună investiție marginală disponibilă azi** — date gata, doar necalculate |
| Rest days | `feature_engine.rest_days_modifier()` deja scris | — | Zero | **Deja testat și respins** prin ablație reală (`REST_DAYS_VALIDATION.md`) — nu se reintroduce fără date noi |
| Fixture congestion | Nou | Scăzut | Zero | Neevaluat încă — aceeași sursă de date ca rest days |
| Injuries (activare din shadow) | Deja colectat, API-Football | Scăzut-mediu | Zero, dacă folosim lineup probabil (T-1), nu final | Blocat pe `shadow_mode_enabled=False`, neactivat |
| Real shots/possession (nu proxy sintetic) | **Condiționat de rezolvarea acoperirii §2** | Mediu | Zero | Fără sens până acoperirea celor 4 derivate crește |
| xG extern (Understat/FBref) | Provider nou | Ridicat | Real, de gestionat explicit | Cost mare, neaprobat |
| Odds-derived (implied probability, opening) | `odds_history` (1.668 rânduri) | — | Real dacă folosim closing | **Volumul e insuficient azi** pentru orice concluzie |

### Cum ar trebui grupate logic

Propunere de organizare pe **grupuri de feature-uri cu proveniență și cadență de refresh distincte** (nu doar o listă plată) — motiv: fiecare grup are propriul profil de acoperire/risc/cost, iar un viitor Feature Pipeline (§4) trebuie să le trateze diferit:

1. **Team Strength** (ELO, offensive/defensive rating) — actualizare per meci finalizat, acoperire aproape completă, cel mai puternic semnal (confirmat: ELO domină importanța cu 15-20×).
2. **Recent Form** (form_score, exponențial ponderat) — aceeași cadență.
3. **Head-to-Head** (h2h_modifier, h2h_meetings) — cadență per pereche de echipe, rar actualizat pentru perechi noi.
4. **Match-Context Derived Stats** (corner/card/foul/shot dominance) — grup cu acoperire structural inferioară, dependent de o sursă suplimentară de date (Match Statistics, Soccer Football Info) — trebuie tratat separat în orice raport de model, nu amestecat în agregat cu grupul 1-3 (exact observația din `ML_ACTIVATION_GATE.md` Punctul 4).
5. **[Propus, neimplementat] Trend Signals** (ELO trend) — cadență similară grupului 1, sursă deja existentă.
6. **[Propus, neimplementat] Context Situational** (rest days — respins, fixture congestion — neevaluat) — cadență per meci.
7. **[Colectat, neactivat] External Risk Signals** (accidentări) — cadență zilnică, blocat pe activare.

### Ce ar trebui generat automat

Recomandarea din `PREDICTOR_ROADMAP_V4.md` §7 Pasul 3 ("Feature Pipeline generic: Provider → Normalize → Persist → Backfill → Learning Core → Shadow Testing → Promotion Gate") rămâne validă și e reluată aici ca precondiție arhitecturală pentru §4 — nu se propune un pipeline nou, concurent, ci confirmarea acestei direcții deja documentate ca fundație pentru orice extindere viitoare de feature-uri.

---

## 4. Arhitectura internă

### Principiu central: reutilizare, nu reconstrucție

Aproape toate straturile cerute în întrebare **există deja**, doar nu sub o singură umbrelă „ML Engine". Tabelul de mai jos mapează cerința la infrastructura reală:

| Strat cerut | Infrastructură existentă | Stare |
|---|---|---|
| Data Pipeline | `supabase_client.get_training_data()`, `database/queries.py` | ✅ Există |
| Feature Pipeline | `ml_predictor._fetch_training_dataframe()` (parțial), `feature_engine.py` | ⚠️ Parțial — cuplat azi de `ml_predictor.py`, nu un modul independent |
| Training | `learning_core/training_runner.py` + `LearningAlgorithm.fit()` | ✅ Există |
| Validation | `ml_predictor._walk_forward_validate()` + `shadow_testing.evaluate_experiment()` | ✅ Există, în două etape (offline walk-forward + shadow live) |
| Calibration | ADR-049, cod parțial (`_fit_temperature`), **neintegrat încă** | ⚠️ Decis, neimplementat |
| Prediction (serving) | `champion_loader.py` + `oracle_engine._resolve_champion()` | ✅ Există, dar servește azi DOAR ca input pt. blending legacy, nu ca voce proprie |
| Monitoring | `learning_core/champion_guardian.py` | ✅ Există, complet, **dezactivat** |
| Model Registry | `learning_core/model_registry.py` | ✅ Există, deja pluggable, deja 4 implementări |
| Experiment Tracking | `training_runs` (Supabase) + `challenger_evaluations` | ✅ Există, dar **două căi de scriere paralele, ușor inconsistente** (vezi Gol #1 mai jos) |

### Ce NU există și trebuie adăugat

**1. O interfață de motor propriu-zisă** — azi `ml_predictor.MLPredictorEngine` e consumat direct de `oracle_engine.py` (`self.ml`), nu exclusiv prin abstracția `LearningAlgorithm`. Propunere: un modul nou, `ml_engine.py` (rădăcina proiectului, simetric cu `blend_engine.py`), care:
   - **Nu reimplementează** antrenare/validare/promovare — le orchestrează prin interfețele deja existente (`model_registry.get()`, `champion_loader.load_champion_or_none()`).
   - Expune un singur punct de intrare stabil: `MLEngine.predict(features: dict) -> dict | None` → aceeași formă `{"prob_home", "prob_draw", "prob_away"}` deja folosită de `BlendEngine.predict()`, ca să se conecteze direct la contractul `EngineOutput` (§9).
   - Rezolvă intern **care algoritm servește azi „vocea ML"** — la lansare, exclusiv `xgboost_v1`; pe termen lung, un alt `LearningAlgorithm` din Registry, fără schimbare de contract extern — exact tiparul deja aprobat pentru `BlendEngine`/`BlendStrategy`.
   - Zero coupling cu Champion/Shadow/Promotion direct din UI — le consumă prin interfețele existente, nu le duplică.

**2. Feature Pipeline decuplat de `ml_predictor.py`** — azi calculul feature-urilor derivate (`corner_dominance` etc.) e inline în `MLPredictorEngine._fetch_training_dataframe()`. Pe termen lung (nu urgent), separarea într-un modul propriu ar permite reutilizare de către un viitor al doilea algoritm fără duplicare — semnalat ca îmbunătățire, nu ca blocaj.

**3. Consolidarea celor două căi de înregistrare a rulărilor de antrenare** — **Gol structural real, confirmat prin cod**: `ml_predictor._record_training_run()` (calea de producție, `oracle_engine`/`sync/run_daily.py`) și `learning_core/training_runner.py::run_training()` (calea CLI/Learning Core) scriu ambele în `training_runs`, dar independent, cu conținut ușor diferit (`training_runner` nu duce mai departe `avg_brier_score`/`folds` complet). Nu e o eroare azi (ambele căi produc rânduri valide), dar e o sursă latentă de inconsistență dacă cele două căi ajung vreodată să difere mai mult. **Recomandare**: unificare la o singură cale de scriere, ca task separat, mic, cu risc redus — nu face parte din roadmap-ul §10 al acestui document (nu e blocant pentru pornirea proiectării ML Engine), dar trebuie tratat înainte ca Experiment Tracking să fie considerat „complet".

### Diagrama de dependențe propusă

```
                     ┌─────────────────┐
                     │  Model Registry  │  (existent, neschimbat)
                     │ LearningAlgorithm│
                     └────────┬─────────┘
                              │ implementează
              ┌───────────────┼───────────────┐
      ┌───────▼──────┐               ┌────────▼────────┐
      │ xgboost_v1   │               │  (viitor: LightGBM,│
      │ (existent)   │               │  ensemble, etc.)   │
      └───────┬──────┘               └─────────────────┘
              │ .fit() / .predict() / .get_trained_model()
   ┌──────────┼─────────────────────────────────┐
   │  Training Runner │ Challenger FSM │ Promotion │ Champion Guardian
   │  (existent)       │ (existent)     │ (existent) │ (existent, dezactivat)
   └──────────┬─────────────────────────────────┘
              │ champion_loader.load_champion_or_none()
      ┌───────▼────────┐
      │   ml_engine.py │  ← NOU, subțire, fără antrenare/I-O propriu
      │   .predict()   │
      └───────┬────────┘
              │ EngineOutput(engine="ml", ...)
      ┌───────▼────────┐
      │  blend_engine.py│  (existent, neschimbat)
      └────────────────┘
```

Niciun strat nou nu „intră peste" straturile existente — `ml_engine.py` e o fațadă, exact ca `blend_engine.py` a fost proiectat să fie față de strategiile lui interne.

---

## 5. Algoritmi

### XGBoost — situația actuală, evaluată critic

Hiperparametrii actuali (`n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85, random_state=42`) au fost deja optimizați prin 2 runde Optuna (120+400 trial-uri) — cel mai bun candidat a redus Log Loss cu doar -0,49% relativ, sub pragul de succes de 0,5% — **respins, nu neexplorat**. Acest lucru e important: **nu tuning-ul de hiperparametri e blocajul azi**, e acoperirea de date (§2/§3). Orice algoritm nou ar lovi aceeași limită.

### Comparație algoritmi, în contextul specific Football Oracle

| Algoritm | Potrivire pt. ~50K rânduri, 14-90 feature-uri tabulare | Avantaje | Dezavantaje în acest context |
|---|---|---|---|
| **XGBoost** (actual) | Foarte bună | Robust la NaN nativ (critic — 83% din rânduri au NaN pe feature-urile derivate), interpretabil (feature importance, deja folosit), maturitate/precedent în proiect | Niciun online-learning nativ simplu fără re-antrenare completă |
| **LightGBM** | Foarte bună | Antrenare mai rapidă pe volume mari, suport nativ categorical, histogram-based | Fără avantaj demonstrat vs. XGBoost la acest volum (~50K rânduri — LightGBM strălucește la milioane); cost de migrare nejustificat fără dovadă |
| **CatBoost** | Bună | Foarte bun cu feature-uri categorice (ex. ligă, echipă, ca embedding intern) — potențial relevant dacă identitatea echipă/ligă devine feature explicit | Mai lent la antrenare; avantaj categorical nefolosit azi (echipele nu sunt feature direct) |
| **Random Forest** | Medie | Simplu, robust la overfitting pe seturi mici | Calibrare probabilistică tipic mai slabă decât gradient boosting; fără avantaj clar față de XGBoost aici |
| **Logistic Regression** (regularizată) | Slabă ca model principal, **bună ca baseline/diagnostic** | Extrem de interpretabilă, rapidă, bun test de sanitate („cât din semnal e liniar?") | Nu captează interacțiuni neliniare — exact ce ML Engine trebuie să aducă în plus față de Oracle (obiectiv secundar, §1) |
| **Rețele neuronale (MLP/tabular)** | Slabă la acest volum | — | 50K rânduri e mic pentru rețele — risc real de overfitting, fără infrastructură de regularizare/early-stopping robustă azi; cost de dezvoltare mare, beneficiu neconfirmat |
| **TabNet** | Slabă azi | Interpretabilitate prin attention | Concepută pentru seturi mari (sute de mii+ rânduri); imaturitatea datelor (§2/§3) ar domina orice avantaj arhitectural |

### Concluzie critică

**Nu există un caz susținut de date pentru schimbarea algoritmului azi.** `ML_EVOLUTION_ROADMAP.md` are deja P9 („Benchmark LightGBM/CatBoost") ca prioritate JOASĂ, condiționat de prag de îmbunătățire &gt;1% relativ pe minim 2/3 metrici — poziționare corectă, confirmată independent aici. Investiția corectă e închiderea golurilor de date (§2/§3), nu schimbarea algoritmului.

### Strategia de evoluție pe termen lung

1. **Nu se schimbă algoritmul până acoperirea feature-urilor derivate nu trece semnificativ de 17,1%** — orice comparație de algoritm pe datele actuale ar măsura zgomot de imputare, nu diferență reală de algoritm.
2. **Logistic Regression ca diagnostic permanent, nu ca model de producție** — rulată în paralel (offline, nu servită), ca test de sanitate: dacă un algoritm mai complex nu bate semnificativ regresia logistică, semnalul e prea liniar ca să justifice complexitate suplimentară.
3. **Extensibilitatea e deja rezolvată arhitectural** — `LearningAlgorithm` (Protocol, `@runtime_checkable`) nu are nicio referință la XGBoost în `model_registry.py`; orice algoritm nou = o nouă implementare + `register()`, zero schimbare în restul Learning Core. Acesta e motivul pentru care „algoritm nou" nu trebuie tratat ca eveniment arhitectural mare — e deja o operație de extensie, nu de refactorizare.
4. **CatBoost devine relevant DOAR dacă** identitatea echipă/ligă devine vreodată feature explicit (azi nu e) — de reevaluat atunci, nu acum.

---

## 6. Validare

### Ce se măsoară deja, corect

`shadow_testing.evaluate_experiment()` implementează exact metodologia cerută, deja funcțională:
- **Brier Score** (`_brier()`, distanță pătratică standard față de one-hot) — implementat.
- **Log Loss** — implementat.
- **Accuracy** — implementat, dar niciodată singur (vezi criteriul de mai jos).
- **Calibrare** — nu ca metrică unică în `shadow_testing`, dar `ORACLE_VS_ML_REPORT.md` demonstrează deja metodologia (reliability table pe 5 bin-uri de încredere) — trebuie păstrată ca parte standard a oricărui raport de evaluare ML, nu doar ad-hoc.
- **Semnificație statistică** — 3 metode interschimbabile (`paired_bootstrap` implicit, `paired_permutation`, `wilcoxon`), toate pe DIFERENȚE ÎMPERECHEATE (același meci, două predicții) — metodologie corectă, superioară unei comparații naive de medii.
- **Criteriul de promovare** (deja implementat, `shadow_testing.py:314`): `candidate_for_promotion` necesită **Brier + Log-loss + Accuracy semnificative simultan, în direcție favorabilă** — exact regula North Star #2, verificată în cod, nu doar documentată.

### Ce lipsește sau trebuie adăugat

| Element cerut | Stare |
|---|---|
| Log Loss | ✅ Există |
| Brier Score | ✅ Există |
| Calibration | ⚠️ Metodologie demonstrată (`ORACLE_VS_ML_REPORT.md`), **neintegrată ca output standard** al `evaluate_experiment()` — propunere: adăugare reliability-table ca output secundar, informativ, fără să schimbe criteriul de promovare |
| ROI (experimental) | ❌ **Blocat structural** — `odds_history` (1.668 rânduri) insuficient, join meci↔cotă nerezolvat. Nu se calculează, nu se aproximează. Rămâne „neconcludent" explicit, per North Star #8, până se rezolvă separat |
| Stabilitate în timp | ⚠️ Parțial — Champion Guardian are deja `_trend_degradation()` (comparație 50/50 cronologică), dar dezactivat azi |
| Robustețe între ligi/sezoane | ❌ **Nu se poate face corect azi** — fragmentarea identității ligă (§2) ar produce o defalcare per-ligă falsă; `season` populat doar pe 5.756/53.777 rânduri (10,7%) — insuficient pentru o analiză per-sezon serioasă |

### Metodologia de evaluare propusă

1. **Walk-forward rămâne obligatoriu**, fără excepție — deja regulă permanentă în CLAUDE.md, reconfirmată aici fără nicio modificare.
2. **Orice pretenție de îmbunătățire raportează simultan Brier + Log-loss + Accuracy + reliability table** — nu doar unul din cele patru. Consistent cu ce ADR-020/ADR-021 deja au făcut (măsurare simultană), formalizat aici ca cerință explicită de raport, nu doar practică bună.
3. **Robustețe per-ligă/sezon rămâne explicit „nedemonstrabilă azi"** — nu se aproximează, nu se raportează pe agregat mascând fragmentarea. Orice viitor raport care ar afirma „modelul e robust cross-league" fără rezolvarea prealabilă a fragmentării de identitate ligă trebuie respins la review, nu acceptat.
4. **ROI rămâne experimental, raportat separat, niciodată ca parte a criteriului de promovare** — exact scopul cerut de utilizator ("metrică experimentală, nu obiectiv principal"), deja aliniat cu practica din `ORACLE_VS_ML_REPORT.md`.

---

## 7. Învățare continuă

### Ce există deja, funcțional (ADR-030, reutilizat integral)

Orchestrarea Continuous Learning (`learning_core/continuous_learning.py`) rulează deja 4 faze, **A → B → D → C** (ordine reală de execuție, nu A→B→C→D), generic peste orice intrare din Model Registry — zero cod nou necesar pentru un al doilea algoritm ML:

- **Faza B** (antrenare Challenger nou) — declanșată de prag de volum (`MIN_SAMPLES_TO_TRAIN=30` la prima rulare, apoi meciuri noi finalizate de la ultima antrenare).
- **Faza A** (monitorizare Challenger activ) — evaluare statistică (§6), propune promovare (T3a), niciodată automat.
- **Faza D** (sănătate Champion, ADR-037) — 4 dimensiuni (structural/baseline-deviation/trend/stability), propune rollback, niciodată automat.
- **Faza C** (execuție decizii aprobate uman) — singurul loc unde Champion-ul chiar se schimbă.

### Cum evităm degradarea / detectăm concept drift

**Deja construit, doar dezactivat**: Champion Guardian (`champion_guardian_enabled=False`, `champion_guardian_proposals_enabled=False`). Cele 4 dimensiuni (structural, baseline-deviation la prag 10%, trend la prag 10% pe fereastră 50/50, stabilitate) acoperă exact întrebarea „cum detectăm degradarea" — nu trebuie reproiectat, trebuie **activat** ca etapă de roadmap (§10), separat de orice lucru pe feature-uri/algoritm.

### Cum retrenăm

Deja: retrain complet, offline, declanșat pe volum, niciodată incremental. **Evaluare critică**: pentru volumul actual (~50K rânduri, antrenare &lt;1s per audit) retrain complet e ieftin — nu există azi o presiune reală de cost care să justifice migrarea la incremental/online learning. XGBoost suportă tehnic warm-start (`xgb_model=` la fit), dar **nu se propune aici** ca schimbare — ar introduce risc de drift necontrolat între versiuni de model fără beneficiu demonstrat la volumul actual. Semnalat ca opțiune viitoare, condiționată de creșterea reală a costului de antrenare completă, nu de acum.

### Cum validăm înainte de promovare

Deja acoperit complet la §6 — `evaluate_experiment()`, criteriul simultan, `MIN_MATCHES_FOR_EVALUATION=200`.

### Cum se integrează cu Learning Core existent

**Nu se integrează — ESTE deja Learning Core-ul existent.** ML Engine, așa cum e propus în §4, nu introduce o a doua buclă de învățare continuă — reutilizează `continuous_learning.py` neschimbat, exact cum `blend_v1` a făcut-o deja (ADR-050) fără nicio modificare la orchestrator. Singura activitate reală de „integrare" e activarea celor 2 flag-uri deja existente (Champion Guardian), tratată ca etapă de roadmap, nu ca lucru de arhitectură nou.

---

## 8. Relația cu Oracle

### Cum descoperă ML informație pe care Oracle nu o vede

Structural, deja adevărat: Oracle e o formulă aditivă/multiplicativă închisă (`calibrate_xg()` — produsul unor multiplicatori independenți). Un model gradient-boosting captează prin construcție **interacțiuni** (ex. „formă bună ÎN COMBINAȚIE cu ELO scăzut al adversarului ÎN COMBINAȚIE cu H2H favorabil" — un efect neliniar pe care o sumă/produs de termeni independenți nu-l poate reprezenta exact). Asta e valoarea reală, demonstrabilă doar empiric (feature importance nu arată interacțiuni, doar SHAP interaction values ar putea — neexplorat azi, propunere pentru un audit viitor, nu parte a roadmap-ului §10).

### Cum evităm ca ML să devină o copie a lui Oracle

Trei mecanisme, primele două deja aplicate, al treilea de menținut ca regulă explicită permanentă:

1. **Exclude explicit output-urile Oracle din feature-uri** (§2) — deja făcut, cu dovadă de ablație.
2. **Feature-urile de intrare sunt calculate din date brute, nu din decizia lui Oracle** — `offensive_rating`/`form_score`/`elo` sunt derivate independent de `feature_engine.py`, nu re-derivate din predicția Oracle.
3. **[Regulă nouă, propusă aici]**: orice viitor experiment care ar propune adăugarea predicției Oracle (sau a oricărei ieșiri Oracle) ca input direct pentru ML trebuie tratat ca **schimbare de rol arhitectural**, nu ca feature obișnuit — necesită aprobare explicită separată, exact ca regula deja existentă pentru schimbări de contract (Discovery Rule, CLAUDE.md). Motivul: ar contrazice direct ADR-051 §2.2 ("ML nu trebuie să reproducă Oracle").

### Cum folosim predicțiile Oracle fără să transformăm ML într-un imitator

Nu le folosim ca input. Singura interacțiune legitimă Oracle↔ML e **la nivel de comparație** (Champion Guardian, Blend, rapoarte de evaluare) — niciodată la nivel de feature de antrenare. Aceasta e deja practica actuală, formalizată aici ca regulă permanentă.

---

## 9. Relația cu Blend

### Contractul public de livrare

Deja definit și implementat, fără nicio modificare necesară: `blend_engine.EngineOutput(engine: str, prob_home: float, prob_draw: float, prob_away: float)`. ML Engine trebuie doar să producă acest obiect:

```python
EngineOutput(engine="ml", prob_home=..., prob_draw=..., prob_away=...)
```

Sursa acestor 3 probabilități: `ml_engine.MLEngine.predict(features) -> dict | None` (§4), la rândul lui derivat din `LearningAlgorithm.predict()` — deja aceeași formă `(prob_home, prob_draw, prob_away, metadata)`.

### Cum păstrăm independența celor trei motoare

Deja garantat structural de designul Blend Engine (aprobat, implementat): `BlendEngine.predict()` primește o LISTĂ de `EngineOutput`, fără cunoaștere despre proveniența fiecăruia. Adăugarea celui de-al doilea `EngineOutput` (ML) în `oracle_engine._get_blend_engine_prediction()` e o singură linie nouă — zero schimbare în `blend_engine.py` însuși. Acest lucru a fost deja confirmat explicit ca parte a review-ului Blend Engine.

### ⚠️ Bug de coupling real, de reparat ÎNAINTE de conectare — nu opțional

`learning_core/consensus_validation.py::compute_metrics()` (ADR-033, activ azi ca infrastructură deși `consensus_validation_enabled=False` implicit):
```python
engines = [p for p in raw_predictions if all(k in p for k in (...))]
if len(engines) < 2:
    return None
a, b = engines[0], engines[1]   # ← hardcodat la exact 2
```
Dacă `ml_engine.py` ajunge vreodată să scrie și în `raw_predictions` (ADR-031, N-way Serving — NU în `blend_engine_prediction`, care e deja izolat) alături de Oracle și Blend, acest cod va ignora silențios al treilea motor, nu va crăpa, dar va produce un rezultat greșit — mai periculos decât o eroare vizibilă. **Nu e o problemă a acestui document** dacă ML Engine e conectat DOAR la `BlendEngine` (izolat, la fel ca Blend azi) — devine o problemă reală doar dacă ML e adăugat vreodată la `raw_predictions`/ADR-031. **Recomandare**: dacă/când se decide expunerea ML în `raw_predictions`, `compute_metrics()` trebuie reparat generic (N motoare, nu 2 hardcodate) ÎNAINTE, nu descoperit după activare. Semnalat aici explicit, ca precondiție, nu ca parte a roadmap-ului imediat.

### ⚠️ Clarificare arhitecturală necesară — RUNTIME_CONTRACT.md (Frozen)

Acesta e cel mai important punct critic al acestui document, identificat deja parțial în ADR-051 §6, dar nedecis acolo — reluat aici explicit:

`docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` (**Frozen**, ADR-019) definește azi „utilizabilitatea unui Champion" exclusiv în termenii servirii **combinate** (blending legacy în predicția Oracle, controlat de `ml_blending_enabled`). Afișarea independentă a predicției ML (mirror exact al modului în care Blend Engine a fost livrat — bloc UI propriu, fără să atingă predicția Oracle servită) **este, în litera documentului, exact tipul de „servire live care expune ML ca ieșire proprie, separată"** pe care ADR-051 §6 îl semnalează ca necesitând un ADR dedicat înainte de implementare, tocmai fiindcă atinge un document Frozen.

**Diferența față de Blend Engine, care NU a necesitat asta**: `blend_engine.py` are zero dependență de Champion — e pur, fără I/O, fără citire din `champion_loader.py`. `ml_engine.py`, prin construcție, TREBUIE să citească din infrastructura Champion (`self.ml`/`champion_loader.load_champion_or_none()`) ca să aibă ceva de servit — deci intră direct sub domeniul `RUNTIME_CONTRACT.md`.

**Ce NU decide acest document**: dacă afișarea read-only a lui `self.ml.predict()` (folosind exact modelul deja încărcat, fără nicio schimbare la `_resolve_champion()`) necesită literalmente redeschiderea documentului Frozen, sau dacă poate fi tratată ca o extensie aditivă minoră (analog cu felul în care ADR-049 §6 anticipează o a 7-a condiție pentru calibrare, fără să fi redeschis încă documentul). **Recomandare fermă**: pasul „conectare ML la Blend" din roadmap-ul de mai jos (§10, Etapa 3) trebuie precedat de un ADR dedicat, mic, care decide explicit acest punct — exact procesul deja cerut de ADR-051 §6, nu o interpretare nouă inventată aici.

---

## 10. Roadmap

Fiecare etapă: implementabilă independent, testabilă izolat, reversibilă (flag default OFF sau revert simplu), risc redus. Nicio etapă nu presupune finalizarea completă a celei anterioare pentru a începe proiectarea următoarei — dar activarea în producție respectă ordinea.

| Etapă | Conținut | Risc | Reversibilitate |
|---|---|---|---|
| **0. Precondiție de guvernanță** | ADR dedicat, mic, care rezolvă explicit întrebarea RUNTIME_CONTRACT.md de la §9 — înainte de orice cod care citește Champion pentru afișare independentă | Zero (document) | N/A |
| **1. `ml_engine.py`** | Modul nou, fațadă subțire peste `LearningAlgorithm`/Champion existent, simetric cu `blend_engine.py`. Zero schimbare de comportament servit. Teste unitare izolate (mirror `test_blend_engine.py`) | Foarte scăzut — modul nou, neconectat încă | Ștergere fișier |
| **2. Afișare UI independentă „🤖 ML"** | Flag propriu (`ml_engine_display_enabled`, default False), bloc UI paralel cu „🧮 Oracle"/„🔀 Blend", populat din `ml_engine.py`, izolat de `raw_predictions` (exact tiparul Blend) | Scăzut — flag OFF implicit, zero impact pe predicția servită | Flag OFF |
| **3. Conectare ML → Blend** | A doua intrare `EngineOutput(engine="ml", ...)` în `_get_blend_engine_prediction()` | Scăzut — Blend rămâne o medie, ML Engine încă nu afectează predicția Oracle servită | O linie de revert |
| **4. Integrare calibrare (ADR-049)** | Implementare efectivă a Temperature Scaling deja decisă, neimplementată — necesară înainte ca predicția ML afișată să fie de încredere | Scăzut — decizie deja luată, doar implementare | Degradare grațioasă deja specificată în ADR-049 §9 |
| **5. Activare Champion Guardian** | `champion_guardian_enabled=True` (monitorizare read-only), apoi separat `champion_guardian_proposals_enabled=True` | Scăzut — cod deja testat, propune, nu execută automat | 2 flag-uri, revert imediat |
| **6. Rezolvare acoperire feature-uri derivate** | Investigație dedicată — de ce doar 17,1%, ce sursă suplimentară ar închide golul | Necunoscut, depinde de descoperiri | N/A — fază de investigație, nu de cod |
| **7. ELO Trend ca feature real** | Primul feature nou din `elo_history`, cu ablație reală înainte de includere în `FEATURE_COLUMNS` | Scăzut — date deja există, doar neexploatate | Feature exclus dacă ablația eșuează |
| **8. [Separat, condiționat de decizie explicită]** Activare `ml_blending_enabled` (mecanismul LEGACY, în predicția Oracle servită) | **Nu face parte din acest roadmap** — rămâne guvernat separat de `ML_ACTIVATION_GATE.md`, cele 4 condiții ale lui, și de decizia nerezolvată din ADR-051 §6 despre soarta acestui mecanism | — | — |

**Notă critică finală, de reținut explicit**: Etapele 1-5 din acest roadmap **nu ating deloc** întrebarea „activăm blending-ul ML în predicția Oracle servită" — acea întrebare rămâne complet separată, guvernată de `ML_ACTIVATION_GATE.md`, neatinsă aici. Confuzia dintre „ML capătă voce proprie, afișată independent" (ce propune acest document, risc redus, aliniat cu ADR-051) și „ML se amestecă în predicția Oracle" (mecanism legacy, risc mai mare, gate separat cu 4 condiții încă neîndeplinite) e exact genul de amestec pe care ADR-051 §6 îl semnalează ca gol nerezolvat — acest roadmap îl tratează ca doi subiecți distincți, deliberat, nu întâmplător.

---

## 11. Sumar — răspuns direct la cerințele explicite ale task-ului

- **Rolul ML rămâne exact cel din ADR-051** — al doilea expert independent, nu înlocuitor, nu modul atașat, nu imitator. Nimic din acest document nu propune schimbarea acestui rol.
- **Infrastructura Learning Core existentă (Model Registry, Challenger FSM, Promotion, Champion Guardian, Continuous Learning) e suficientă și corect proiectată** — se reutilizează integral, nu se reconstruiește.
- **Limitările reale identificate** (nu presupuse): acoperire feature-uri derivate (17,1%), ELO-dominanță, fragmentare identitate ligă, ROI nemăsurabil azi, ambiguitate RUNTIME_CONTRACT.md pentru afișare independentă, bug latent 2-motoare în `consensus_validation.py`, două căi paralele de scriere training-runs.
- **Nicio schimbare de algoritm nu e susținută de date azi** — XGBoost rămâne alegerea corectă; extensibilitatea pentru un algoritm viitor e deja rezolvată arhitectural (Model Registry).
- **Roadmap-ul propus e complet separat de activarea blending-ului legacy** — evită exact confuzia de scop pe care ADR-051 a semnalat-o ca gol deschis.

Acest document nu autorizează nicio implementare. Etapa 0 (ADR dedicat pentru clarificarea RUNTIME_CONTRACT.md) rămâne precondiția explicită înainte ca orice cod din §10 să înceapă.
