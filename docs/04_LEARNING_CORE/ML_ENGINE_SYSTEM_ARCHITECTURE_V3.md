# Machine Learning Engine — Arhitectură de Sistem + Design Review (v3)

**Status**: DRAFT — document de arhitectură de sistem și critică. NU e ADR, NU autorizează implementare, NU descrie algoritmi/feature-uri/XGBoost. Răspunde strict la întrebarea: **poate infrastructura EXISTENTĂ (plus extensii realiste ale ei) susține un ML Engine conform ADR-051, și dacă da, cum arată sistemul, componentă cu componentă?**

**Metodologie, obligatoriu diferită de v1/v2**: nu s-a presupus că v1 (`ML_ENGINE_ARCHITECTURE_DESIGN.md`) sau v2 (`ML_ENGINE_WORLD_CLASS_VISION_V2.md`) sunt corecte. Fiecare afirmație de infrastructură de mai jos a fost verificată prin citire directă de cod în această sesiune: `learning_core/model_registry.py`, `learning_core/champion_loader.py`, `learning_core/consensus_validation.py`, `blend_engine.py`, `oracle_engine.py` (secțiunile `_resolve_champion`, `_get_blend_engine_prediction`, `MatchPrediction`), `learning_core/promotion_service.py`, `learning_core/challenger_runner.py`, `app.py` (blocul UI Blend), plus `ADR-051` și `RUNTIME_CONTRACT.md` integral. Unde v1 avea dreptate, se confirmă explicit cu sursa. Unde v1 avea o lacună reală, se identifică exact, cu linia de cod care o dovedește — nu cu impresie.

---

## 0. Verdict direct: poate infrastructura existentă susține un ML Engine conform ADR-051?

**DA, cu o singură precondiție de guvernanță neînchisă și o singură corecție de proiectare** (nu de infrastructură — o corecție a modului în care componentele existente ar trebui compuse, nu o piesă nouă de construit).

Nu e un "da" necondiționat, ieftin de spus fără verificare — e verificat direct în cod: `model_registry.py` e genuinely agnostic de algoritm (`Protocol`, zero referință XGBoost), `promotion_service.py` e generic pe `algorithm_family` (verificat: nicio ramură de cod specifică unui algoritm), `blend_engine.py` are, verificat prin citirea fișierului, zero import din `oracle_engine`/`ml_predictor`/`learning_core.*` — chiar docstring-ul o afirmă și codul o confirmă. Acestea sunt exact cele trei proprietăți structurale necesare pentru ca ADR-051 să fie respectabil mecanic, nu doar declarat: extensibilitate algoritm, independență de contract, zero cuplaj invers.

**Precondiția neînchisă** (deja identificată corect de ADR-051 §6 și v1 §9, reconfirmată aici prin citirea integrală a `RUNTIME_CONTRACT.md`): documentul Frozen definește "utilizabilitatea unui Champion" fără să distingă între "citit pentru blending legacy în predicția servită" și "citit pentru afișare independentă, read-only". Un ADR mic, dedicat, trebuie să decidă explicit dacă a doua utilizare intră sub același contract sau cere o extensie — **acesta rămâne singurul blocaj real de guvernanță**, neschimbat față de ce v1 a identificat deja corect.

**Corecția de proiectare** (NU identificată explicit de v1 — găsită prin citirea directă a `champion_loader.py` vs. `model_registry.LearningAlgorithm`, detaliată în §3.1 mai jos): diagrama propusă de v1 §4 pentru `ml_engine.py` nu poate funcționa exact așa cum e desenată. Nu pentru că lipsește infrastructură — pentru că diagrama compune greșit infrastructura deja existentă.

---

## 1. Critica documentelor existente

Cerința explicită a task-ului: nu presupune că v1/v2 sunt corecte. Iată ce a rezistat verificării, ce nu a rezistat, și ce lipsește.

### 1.1 Ce e corect în v1, verificat independent (nu doar repetat)

- Tabelul de mapare infrastructură (§4) e, în mare, exact — verificat separat pentru Model Registry, Promotion, Champion Loader.
- Bug-ul de cuplare la 2 motoare în `consensus_validation.compute_metrics()` (§9) e real, confirmat literal: linia `a, b = engines[0], engines[1]` există exact așa. **Dar v1 îl scopează deja corect** — nu e blocant dacă ML nu intră în `raw_predictions`/ADR-031, doar dacă intră. Nu repet asta ca pe o descoperire nouă; e deja corect poziționat.
- Faptul că `blend_engine.py` e pur, fără I/O — verificat direct: fișierul nu importă nimic din afara `dataclasses`/`typing`.
- Faptul că `RUNTIME_CONTRACT.md` (Frozen) e ambiguu pentru afișare independentă — verificat prin citirea integrală a documentului: cele 6 condiții sunt scrise generic ("Runtime poate considera un Champion utilizabil"), nu leagă explicit utilizabilitatea de UN SINGUR consumator — deci nici nu exclude explicit un al doilea consumator (afișare), nici nu-l autorizează explicit. Ambiguitatea e reală, nu inventată.

### 1.2 Ce e greșit sau incomplet în v1 — găsit prin verificare, nu presupus

**(A) Diagrama `ml_engine.py` (§4) nu poate funcționa cum e desenată — contradicție de tip între componente.**

v1 desenează: `champion_loader.load_champion_or_none()` → `ml_engine.py.predict()`. Dar `champion_loader.load_champion_or_none()` întoarce un `ChampionLoadResult` al cărui câmp `model` e, verificat direct în cod (`champion_loader.py:99-110` + testul de deserializare de la linia 87, `model.predict_proba(probe)`), un **`XGBClassifier` brut** — nu o instanță care implementează `LearningAlgorithm.predict(features: dict) -> tuple[float, float, float, dict]`. Un `XGBClassifier` brut nu știe să transforme un dict de context de meci în feature-uri ordonate, nu aplică `FEATURE_COLUMNS`, nu aplică temperatura de calibrare (`ChampionLoadResult.temperature`, câmp separat, netransportat automat).

Traducerea "context brut de meci → vector de feature-uri ordonat → `predict_proba()` → aplicare temperatură → tuple `(prob_home, prob_draw, prob_away, metadata)`" există deja azi, dar trăiește în `ml_predictor.MLPredictorEngine` (calea locală de antrenare) și în orice ar face `seed_from_champion()` (menționat în docstring-ul `champion_loader.py`, linia 43) pentru calea Champion. Un `ml_engine.py` nou care ar apela `champion_loader` DIRECT, așa cum arată diagrama v1, ar trebui fie să reimplementeze această traducere (duplicare de logică, exact ce v1 spune explicit că vrea să evite — "Nu reimplementează antrenare/validare/promovare"), fie să depindă oricum de `ml_predictor.py`/`oracle_engine.py`, ceea ce contrazice cadrul de "fațadă subțire, simetrică cu `blend_engine.py`" — pentru că `blend_engine.py` NU are această problemă (primește `EngineOutput` deja calculat, nu calculează nimic el însuși).

**Concluzie**: `ml_engine.py`, așa cum e proiectat în v1, nu e simetric cu `blend_engine.py` în privința purității — nu poate fi. `blend_engine.py` e pur prin construcție (nu citește nimic, primește totul gata calculat). Un modul care citește Champion-ul e, prin natura lucrului pe care-l face, un consumator de I/O — asimetria asta nu e menționată explicit în v1 și are consecințe reale (vezi §3.1 pentru soluție).

**(B) v1 nu răspunde clar la întrebarea "cine calculează feature-urile pentru predicția LIVE folosită de `ml_engine.py`?"** — §4 mapează "Feature Pipeline" la funcția de ANTRENARE (`_fetch_training_dataframe()`), nu la calea de SERVIRE. Calea de servire a feature-urilor pentru o predicție ML live există deja (e folosită azi pentru varianta locală de fallback din `self.ml`), dar v1 nu o identifică explicit ca dependință a lui `ml_engine.py` — o omisiune reală de diagramă, nu doar un detaliu.

**(C) v1 nu discută dacă un `ml_engine.py` NOU e chiar necesar azi**, sau dacă adaugă suprafață fără beneficiu imediat, dat fiind că `self.ml` (deja existent în `oracle_engine.py`, deja Champion-aware prin `_resolve_champion()`) rezolvă deja exact același lucru pentru consumul intern (blending legacy). Propunerea de a construi un modul separat, nou, e justificată pe termen lung (când ML Engine combină intern mai mulți algoritmi — exact scenariul din v2 §4, ansamblu specialist+stacking), dar e prematură ca prim pas, dacă azi există un singur algoritm servit. Aceasta e o corecție de secvențiere, detaliată în §5.

### 1.3 Ce e corect, dar nespus suficient de răspicat — un fapt care schimbă percepția riscului

**Blend Engine, azi, în producție, nu combină nimic.** Verificat direct: `oracle_engine._get_blend_engine_prediction()` (linia 1967) construiește azi exact UN SINGUR `EngineOutput` (`engine="oracle"`), din predicția deja calculată de Oracle. `WeightedAverageStrategy.combine()` aplicat pe o listă cu un singur element întoarce, matematic, exact acele probabilități, nemodificate (ponderea unui singur element normalizată la 1.0 e identitate). Blocul UI „🔀 Blend" afișat azi în `app.py` (linia 321) e, deci, **byte-identic cu predicția Oracle, sub altă etichetă** — nu o eroare, e exact cum a fost proiectat (aditiv, ML încă neconectat), dar niciun document existent nu spune asta atât de direct pentru un cititor care se uită azi la UI și vede două casete separate, "Oracle" și "Blend", crezând că a doua e deja o combinație reală.

**De ce contează pentru arhitectura propusă mai jos**: pasul "conectare ML → Blend" (v1 §10, Etapa 3) nu e "adăugăm o a doua intrare la un blend care deja funcționează" — e "facem Blend să înceapă să blendeze pentru prima dată". Asta schimbă cum ar trebui comunicat/testat pasul: primul test funcțional real al `WeightedAverageStrategy` cu 2+ intrări diferite se întâmplă abia atunci, nu mai devreme — un fapt de reținut pentru orice plan de testare viitor.

### 1.4 v2 — nicio contradicție găsită, dar scop diferit, de reținut explicit

v2 (Vision) e, prin cerința explicită a utilizatorului la momentul scrierii ei, un document de cercetare pe termen lung, nu de arhitectură de sistem curentă — nu pretinde să răspundă „poate infrastructura de azi susține asta" și nu trebuie criticat pentru asta, ar fi o critică nedreaptă la adresa scopului ei declarat. Un singur punct de aliniere de verificat: v2 §4 (Ensemble intern ML) presupune implicit exact componenta pe care v1 o propune prematur (§1.2.C de mai sus) — un `ml_engine.py` propriu, capabil să orchestreze mai mulți `LearningAlgorithm` intern. Asta confirmă, retroactiv, că `ml_engine.py` ca modul separat E justificat — dar abia când v2 §4 devine relevant (mai mult de un algoritm de combinat), nu azi. Cele două documente nu se contrazic; se ordonează greșit dacă sunt citite ca „construiește ml_engine.py acum" (v1) fără trigger-ul din v2 §4.

### 1.5 Componente inutile / supra-reprezentate în discuția existentă

- **`consensus_validation.py`/ADR-033 nu e infrastructură necesară pentru ca ML să capete voce independentă conform ADR-051.** E un track de cercetare separat, orientat spre altă întrebare ("acordul dintre motoare corelează cu acuratețea?"). Bug-ul lui de 2 motoare a primit, în ambele documente anterioare, atenție proporțională cu cât de "periculos sună", nu cu cât de relevant e pentru task-ul curent — corect scopat de v1, dar merită spus explicit aici: **nu face parte din arhitectura propusă mai jos și nu trebuie atins pentru ca ML să devină a treia voce afișată**.
- **Cele două căi paralele de scriere `training_runs`** (v1 §4, punctul 3) sunt un gol real de igienă, dar nu blochează arhitectural nimic din ce se cere aici — o mențin ca element minor, separat, nu ca parte a arhitecturii de sistem propuse.

---

## 2. De ce infrastructura EXISTENTĂ e, structural, suficientă (verificare, nu presupunere)

Trei proprietăți, fiecare verificată direct în cod, nu doar citată din documentație:

1. **Extensibilitate de algoritm fără schimbare de Learning Core** — `LearningAlgorithm` e un `Protocol` (`@runtime_checkable`), fără nicio referință hardcodată la XGBoost în `model_registry.py`. `register()` adaugă la un dict cheiat pe `(name, version)`. Deja demonstrat empiric, nu doar teoretic: `blend_v1` (ADR-050) a intrat în acest registru fără nicio modificare a `model_registry.py`, `promotion_service.py`, `challenger_runner.py` — precedent direct, verificabil în `learning_core/algorithms/blend_v1.py` existent alături de `xgboost_v1.py`.
2. **Independență de contract la nivelul de combinare** — `blend_engine.py` nu cunoaște, prin construcție, cum a fost calculat un `EngineOutput`. Verificat: singurul import al fișierului e `dataclasses`/`typing`. Orice al doilea motor (ML) se conectează prin ACELAȘI contract, fără ca `blend_engine.py` să știe sau să-i pese.
3. **Ciclul de viață complet deja generic** — Training Runner, Challenger FSM, Promotion, Champion Manager, Champion Guardian, Rollback, orchestrare Continuous Learning (A→B→D→C) — toate scopate pe `algorithm_family`, nu pe un algoritm anume. Verificat direct în `promotion_service.py` (validarea `challenger["algorithm_family"] != algorithm_family`, generică).

Aceste trei proprietăți sunt exact ce ADR-051 cere structural de la infrastructură ca să fie posibilă independența — și sunt deja adevărate, nu ipotetice.

**Ce NU e încă adevărat, și de ce nu e o problemă de infrastructură**: azi există un singur consumator care citește Champion-ul pentru afișare (calea legacy, `ml_blending_enabled`, care amestecă ML ÎN Oracle) — nu există încă un al doilea consumator care să-l citească pentru afișare INDEPENDENTĂ. Asta nu lipsește pentru că infrastructura n-o permite — lipsește pentru că nimeni n-a scris încă acea a doua citire (aditivă, cu risc redus, exact tiparul deja folosit de `_get_blend_engine_prediction()` pentru Oracle).

---

## 3. Arhitectura de sistem propusă — componentă cu componentă

Niciun element de mai jos nu e nou de construit de la zero — cu o singură excepție explicit marcată (§3.1, componenta de servire ML), care e o recompunere mică a codului existent, nu infrastructură nouă.

### 3.1 [DE CONSTRUIT — mic, aditiv] Serving Wrapper pentru vocea ML

**Responsabilitate**: produce, pentru meciul curent, deja-evaluat de Oracle, o valoare `EngineOutput(engine="ml", ...)` din predicția PE CARE `self.ml` A CALCULAT-O DEJA pentru acel meci — fără o a doua rezolvare de Champion, fără reimplementarea traducerii context→feature→predicție.

**Intrări**: predicția deja calculată de `self.ml` pentru meciul curent (indiferent dacă provine din Champion sau din antrenare locală — `RUNTIME_CONTRACT.md` decide asta, mai devreme, o singură dată per proces, la `_resolve_champion()`) + `self.ml_source` (pentru a distinge "indisponibil pentru că nu există model" de "indisponibil pentru că a eșuat calculul pentru acest meci specific").

**Ieșiri**: `EngineOutput(engine="ml", prob_home=..., prob_draw=..., prob_away=...)` sau `None` — și, spre deosebire de `_get_blend_engine_prediction()` de azi, **un motiv explicit de indisponibilitate** atunci când returnează `None` (`ml_source == "none"` → "model insuficient antrenat pentru această ligă"; predicție eșuată pentru acest meci specific → motiv distinct) — pentru ca UI-ul să poată afișa "ML: indisponibil (X)" în loc de o casetă goală/lipsă, exact genul de transparență pe care principiul „nicio stare necunoscută aproximată" îl cere deja pentru alte părți ale sistemului (ELO/H2H „necunoscut").

**Dependențe**: EXCLUSIV `self.ml` deja existent în `oracle_engine.py` (deja Champion-aware) — zero dependență nouă de `champion_loader.py` direct, zero dependență de `model_registry.py` direct. Corectarea explicită față de diagrama v1 §4: acest wrapper NU re-rezolvă Champion-ul — citește rezultatul deja rezolvat o singură dată la construcția procesului, exact regula de atomicitate deja impusă de `RUNTIME_CONTRACT.md`/Pasul 7B ("Un singur apel `champion_loader.load_champion_or_none()` per construcție").

**Relația cu celelalte componente**: structural identică cu `_get_blend_engine_prediction()` — o metodă mică, read-only, gatată de flag propriu (`ml_engine_display_enabled`, implicit False, North Star #3), care nu scrie nimic în `shadow_predictions`/`raw_predictions`. Trăiește lângă `_get_blend_engine_prediction()` în `oracle_engine.py`, nu într-un modul separat — pentru că, spre deosebire de Blend, nu are nimic de orchestrat intern (azi, un singur algoritm servit).

**Când devine insuficient acest design, și ce-l înlocuiește**: în momentul în care ML Engine trebuie să combine intern mai mult de un `LearningAlgorithm` (v2 §4 — specialiști pe ligă, stacking) — abia atunci acest wrapper mic se mută/evoluează într-un modul dedicat (`ml_engine.py`, exact ideea v1, dar declanșată de nevoie reală, nu construită preventiv). La acel moment, ȘI DOAR ATUNCI, traducerea context→feature→predicție trebuie într-adevăr extrasă într-un loc propriu (rezolvând §1.2.B), pentru că un modul care combină mai mulți algoritmi nu mai poate delega totul unui singur `self.ml`.

### 3.2 [REUTILIZAT, neschimbat] Model Registry

**Responsabilitate**: catalog static al algoritmilor disponibili, cheiat `(name, version)`.
**Intrări**: apel `register(algorithm)` la bootstrap.
**Ieșiri**: `get(name, version) -> LearningAlgorithm`, `list_available()`.
**Dependențe**: nimic — pur, fără I/O (`_REGISTRY` e un dict în memorie de proces).
**Relația cu restul**: sursa de adevăr pentru "ce algoritmi există"; consumat de Training Runner și indirect de Champion Loader (prin `algorithm_family`/`algorithm_version`, nu prin apel direct la Registry).

### 3.3 [REUTILIZAT, neschimbat] Training Runner + implementările `LearningAlgorithm`

**Responsabilitate**: orchestrează `fit()` pentru un algoritm dat, produce `TrainingRunResult`.
**Intrări**: date de antrenare (deja disponibile prin `supabase_client.get_training_data()`).
**Ieșiri**: `TrainingRunResult` (status, metrici walk-forward) + artefact model persistat (`model_artifact_storage`).
**Dependențe**: Model Registry (pentru a obține instanța de algoritm), sursa de date de antrenare.
**Relația cu restul**: alimentează Challenger FSM cu un candidat nou antrenat; nu decide singur nimic despre promovare.

### 3.4 [REUTILIZAT, neschimbat] Challenger FSM (challenger_runner/manager/evaluation/shadow)

**Responsabilitate**: ciclul de viață al unui candidat — creat, evaluat statistic (shadow, în paralel cu Champion-ul activ), propus pentru promovare sau respins.
**Intrări**: candidatul din Training Runner, fluxul continuu de meciuri reale (pentru shadow evaluation).
**Ieșiri**: status challenger (`candidate_for_promotion`/`rejected`/etc.), evaluări persistate.
**Dependențe**: Model Registry (pentru identitate algoritm), Shadow Testing (pentru metodologia de evaluare).
**Relația cu restul**: NU atinge niciodată servirea live — pur infrastructură de evaluare offline/shadow.

### 3.5 [REUTILIZAT, neschimbat] Shadow Testing / Statistics Engine

**Responsabilitate**: metodologie statistică — Brier, Log-loss, Accuracy, semnificație pe diferențe împerecheate.
**Intrări**: perechi (predicție Champion, predicție Challenger) pe același meci.
**Ieșiri**: verdict statistic (`evaluate_experiment()`), criteriu de promovare (simultan pe 3 metrici).
**Dependențe**: nimic extern — funcții statistice pure peste date deja colectate.
**Relația cu restul**: consumat de Challenger FSM; e sursa criteriului obligatoriu North Star #2 (dovadă simultană, nu o singură metrică).

### 3.6 [REUTILIZAT, neschimbat] Promotion Engine

**Responsabilitate**: singurul punct care poate schimba Champion-ul activ, DOAR din statusul `candidate_for_promotion`, niciodată automat.
**Intrări**: decizie umană explicită + `training_run_id` al candidatului.
**Ieșiri**: rând nou în `model_champions` (Champion nou activ, cel vechi `superseded_at` setat).
**Dependențe**: validare `algorithm_family`/`league_scope` (verificat generic, nu hardcodat).
**Relația cu restul**: singurul scriitor autorizat #1 al Champion Manager (celălalt fiind Rollback Engine).

### 3.7 [REUTILIZAT, neschimbat] Champion Manager (`model_champions`)

**Responsabilitate**: sursa de adevăr pentru "care e Champion-ul activ, per `(algorithm_family, league_scope)`".
**Intrări**: scrieri exclusiv de la Promotion Engine sau Rollback Engine.
**Ieșiri**: citire prin `sb.get_active_champion(algorithm_family, league_scope)`.
**Dependențe**: Supabase, `service_role`, RLS activ (per regulile de bază de date din `CLAUDE.md`).
**Relația cu restul**: citit de Champion Loader; scris DOAR de cei doi scriitori autorizați — niciun consumator de servire nu scrie aici.

### 3.8 [REUTILIZAT, neschimbat] Champion Loader (`champion_loader.py`)

**Responsabilitate**: aplică cele 6 condiții `RUNTIME_CONTRACT.md`, fail-fast, fără folosire parțială.
**Intrări**: `(algorithm_family, league_scope)`.
**Ieșiri**: `ChampionLoadResult` (model brut + metadate) sau `None`.
**Dependențe**: Champion Manager, `model_artifact_storage`, `calibration_artifact_storage`, `ml_predictor._ALGORITHM_VERSION` (verificare compatibilitate).
**Relația cu restul**: consumat EXCLUSIV de `oracle_engine._resolve_champion()` — verificat, niciun alt fișier din proiect nu-l importă (afirmație din propriul docstring al modulului, consistentă cu grep-ul făcut). **Rămâne așa** — wrapper-ul de la §3.1 nu-l apelează a doua oară.

### 3.9 [REUTILIZAT, dezactivat azi] Champion Guardian

**Responsabilitate**: evaluator read-only al sănătății Champion-ului activ, 4 dimensiuni (structural/baseline-deviation/trend/stabilitate).
**Intrări**: fluxul de rezultate reale comparat cu predicțiile Champion-ului deja servite.
**Ieșiri**: propunere de rollback (niciodată execuție automată).
**Dependențe**: date deja colectate de servire — zero dependență nouă.
**Relația cu restul**: generic per `algorithm_family` — activarea lui (flag existent) nu are nicio legătură cu câte motoare sunt afișate în UI; e ortogonală arhitecturii propuse aici, nu o precondiție a ei.

### 3.10 [REUTILIZAT, neschimbat] Rollback Engine

**Responsabilitate**: al doilea scriitor autorizat al Champion Manager — revenire la un Champion anterior, append-only, CAS-guarded.
**Intrări**: propunere de la Champion Guardian sau decizie umană directă.
**Ieșiri**: rând nou în `model_champions` (revenire).
**Dependențe**: Champion Manager.
**Relația cu restul**: simetric cu Promotion Engine — niciodată o scriere directă, mereu prin acest scriitor dedicat.

### 3.11 [REUTILIZAT, neschimbat] Continuous Learning Orchestrator

**Responsabilitate**: leagă fazele A (monitorizare Challenger) → B (antrenare Challenger nou) → D (sănătate Champion) → C (execuție decizii aprobate uman) — generic peste orice intrare din Model Registry.
**Intrări**: cadență (declanșator zilnic/prag de volum).
**Ieșiri**: efecte compuse din componentele de mai sus (nimic nou propriu).
**Dependențe**: toate componentele 3.2-3.10.
**Relația cu restul**: deja validat empiric pentru un al doilea `algorithm_family` (`blend_v1`, ADR-050) fără nicio modificare — exact precedentul care demonstrează că un al treilea (sau al patrulea) `algorithm_family` viitor ar intra la fel, gratuit.

### 3.12 [REUTILIZAT, neschimbat] Blend Engine

**Responsabilitate**: combină N `EngineOutput` într-o singură predicție — azi doar 1 intrare (Oracle), deci identitate, nu combinare reală (§1.3).
**Intrări**: listă de `EngineOutput`, fără cunoaștere despre proveniența lor.
**Ieșiri**: `{"prob_home", "prob_draw", "prob_away"}`.
**Dependențe**: ZERO — verificat, singurul modul din tot sistemul cu adevărat fără nicio dependență de alt cod de producție.
**Relația cu restul**: consumatorul final al `EngineOutput`-urilor Oracle ȘI ML — punctul unde independența celor două se păstrează mecanic (Blend nu poate favoriza unul față de altul pe baza a ceva ce nu vede, pentru că nu vede nimic despre proveniență în afara etichetei `engine`).

### 3.13 [DE CONSTRUIT — mic, aditiv, mirror al blocului Blend existent] UI Display Layer

**Responsabilitate**: afișează separat, simultan, "🧮 Oracle" / "🤖 ML" / "🔀 Blend" — al treilea bloc, gatat de propriul flag (`ml_engine_display_enabled`).
**Intrări**: `pred.ml_engine_prediction` (câmp nou, izolat, exact tiparul `pred.blend_engine_prediction` deja existent — NU `raw_predictions`, NU `shadow_predictions`).
**Ieșiri**: randare Streamlit, read-only.
**Dependențe**: wrapper-ul de la §3.1.
**Relația cu restul**: pur de prezentare — zero logică de decizie.

---

## 4. Cum comunică componentele — regula unică, deja adevărată, de păstrat

Verificat, nu presupus: TOATE componentele de mai sus comunică prin exact unul din două canale, niciodată printr-un al treilea:

1. **Tabele Supabase, ca sursă de adevăr asincronă** (`training_runs`, `model_champions`, `challenger_evaluations`, artefacte) — componentele de antrenare/evaluare/promovare NU se apelează direct între ele prin funcție Python peste procese; comunică prin ce scriu/citesc din aceste tabele. Decuplare temporală reală (Training Runner poate rula ore înainte ca Promotion să citească rezultatul).
2. **Compunere de funcții Python, sincronă, în interiorul unui singur proces de servire** (`oracle_engine.py` ca orchestrator unic) — la momentul unei predicții live, `self.ml` (deja rezolvat), wrapper-ul ML (§3.1), și `self.blend` (deja instanțiat) se compun direct, în ordine, într-un singur apel `evaluate_match()`. Niciodată peer-to-peer — orchestratorul e mereu singurul care cunoaște toate piesele; nicio componentă nu apelează altă componentă de servire direct (`blend_engine.py` nu cunoaște `oracle_engine.py`, nici invers, nici `ml`-ul).

**Regulă de păstrat explicit pentru orice extensie viitoare**: dacă o componentă nouă are nevoie să comunice cu alta altfel decât prin aceste două canale (ex. un apel RPC direct, un shared-memory cache, un event bus), asta e prin definiție o schimbare de contract — trece prin ADR, nu se adaugă tacit.

---

## 5. Cum rămâne independent conform ADR-051 — mecanic, nu declarativ

Patru garanții, trei deja adevărate azi (verificate), una de menținut activ pentru orice cod viitor:

1. **Feature-urile ML nu includ ieșirile Oracle** — deja adevărat, cu dovadă de ablație (`FEATURE_COLUMNS`, importanță 0.0000 pentru `home_xg_pred`/`prob_*_pred`/`mc_prob_*`).
2. **`blend_engine.py` nu cunoaște proveniența** — deja adevărat, verificat prin lipsa oricărui import relevant.
3. **`model_registry.py`/`LearningAlgorithm` nu au nicio referință la Oracle** — deja adevărat, verificat.
4. **[De menținut, nu de construit]** Wrapper-ul propus (§3.1) trebuie să rămână o citire PURĂ a predicției deja calculate de `self.ml` — niciodată să nu primească vreun parametru derivat din predicția Oracle a aceluiași meci. Testul mecanic de verificat la orice code review viitor pe acest wrapper: funcția nu trebuie să aibă, în semnătura ei, niciun parametru care conține cuvântul `oracle`/`pred.prob_*` — dacă apare, e o violare de contract, nu un detaliu de implementare.

---

## 6. Cum evoluează fără refactorizări majore

- **Un algoritm nou** (CatBoost, LightGBM, un ansamblu) = o nouă implementare `LearningAlgorithm` + `register()` — zero schimbare în Training Runner, Challenger FSM, Promotion, Champion Manager, Champion Guardian, Rollback, Continuous Learning. Deja demonstrat empiric o dată (`blend_v1`), nu doar teoretic posibil.
- **Combinare internă a mai multor algoritmi sub aceeași "voce ML"** (v2 §4) = momentul exact în care wrapper-ul de la §3.1 se extrage într-un modul propriu (`ml_engine.py`) — o mutare de cod, nu o reconstrucție; contractul extern (`EngineOutput(engine="ml", ...)`) nu se schimbă, deci `blend_engine.py`/UI nu simt nimic.
- **Activarea Champion Guardian** = flip de flag, infrastructură deja completă și testată — independent de orice altă etapă din arhitectura de mai sus.
- **Un al patrulea motor, ipotetic, viitor** = ar respecta exact același tipar (`EngineOutput` propriu, Model Registry propriu `algorithm_family`) — arhitectura nu are un plafon hardcodat la "trei", doar Blend Engine ar primi o listă mai lungă de `EngineOutput`, fără nicio schimbare de cod în `blend_engine.py` însuși (deja generic pe listă, nu pe număr fix).

---

## 7. Ce NU trebuie construit (explicit, ca să nu se întâmple tacit)

- **Nicio wiring nouă în `raw_predictions`/ADR-031 (N-way Serving)** ca parte a acestei arhitecturi — asta e o problemă diferită (participarea ML în Consensus Validation, ADR-033), cu propriul risc (bug-ul de 2 motoare, §1.5) și propria decizie separată, viitoare. Confuzia asta a fost deja semnalată ca risc de v1 însuși — reafirmată aici ca regulă explicită de excludere din scopul acestei arhitecturi.
- **Niciun `ml_engine.py` separat, azi** — prematur față de nevoia reală (un singur algoritm servit azi); vezi §3.1 pentru declanșatorul corect al momentului în care devine justificat.
- **Niciun Feature Pipeline nou, separat** — aceeași logică: valoare reală abia când există un al doilea algoritm cu nevoi de feature-uri diferite de `ml_predictor.py`.
- **Nicio schimbare de schemă/tabelă nouă** — `model_champions`/`training_runs`/`model_artifact_storage` sunt deja scopate pe `algorithm_family`, suficiente.
- **Nicio activare de auto-promovare/auto-rollback** — exclus explicit de ADR-002, nu parte a acestei discuții.
- **Nicio rezolvare a bug-ului `consensus_validation.py`** ca precondiție a acestei arhitecturi — irelevant până la o decizie separată de a conecta ML la `raw_predictions`.

---

## 8. Diagrama de sistem completă

```
┌─────────────────────────── DATA LAYER (Supabase) ───────────────────────────┐
│ match_history · training_runs · model_champions · challenger_evaluations    │
│ model_artifact_storage · calibration_artifact_storage                       │
└──────────────┬────────────────────────────────────────────┬─────────────────┘
               │ scriere/citire                              │ scriere/citire
               ▼                                              ▼
┌──────────────────────────────────────┐   ┌──────────────────────────────────┐
│         LEARNING CORE (fabrica)       │   │      CHAMPION LIFECYCLE          │
│  Model Registry → Training Runner     │   │  Promotion Engine ─┐             │
│  → Challenger FSM → Shadow Testing    │──▶│  Rollback Engine  ─┼─▶ model_champions
│  → Continuous Learning Orchestrator   │   │  (2 scriitori, exclusivi)        │
│  (A→B→D→C, generic pe algorithm_family)│   │  Champion Guardian (read-only, monitorizare)
└──────────────────────────────────────┘   └───────────────┬──────────────────┘
                                                              │ citire (o dată/proces)
                                                              ▼
                                                  ┌────────────────────────┐
                                                  │   Champion Loader       │
                                                  │  (6 condiții, RUNTIME_  │
                                                  │   CONTRACT.md, Frozen)  │
                                                  └───────────┬─────────────┘
                                                              │ seed_from_champion()
┌──────────────────────────── SERVING (oracle_engine.py, orchestrator unic) ───────────────┐
│                                                                                            │
│   self.ml (rezolvat o dată)  ──▶  [§3.1 Serving Wrapper]  ──▶ EngineOutput(engine="ml")   │
│                                                                        │                   │
│   Oracle (calcul intern)     ──▶  EngineOutput(engine="oracle")       │                   │
│                                                    │                   │                   │
│                                                    ▼                   ▼                   │
│                                            ┌──────────────────────────────┐                │
│                                            │      blend_engine.py         │                │
│                                            │  (zero I/O, zero coupling)   │                │
│                                            └───────────────┬──────────────┘                │
│                                                             │                               │
└─────────────────────────────────────────────────────────────┼───────────────────────────────┘
                                                              ▼
                                          ┌──────────────────────────────────┐
                                          │   UI Display Layer (app.py)      │
                                          │  🧮 Oracle │ 🤖 ML │ 🔀 Blend    │
                                          └──────────────────────────────────┘
```

---

## 9. Roadmap de implementare, în ordinea corectă (arhitectural, nu de cod)

Fiecare etapă: independentă, reversibilă, risc explicit — corectat față de v1 §10 unde diverge (motivul diverjenței notat la fiecare etapă relevantă).

| Etapă | Conținut | Corectare față de v1 | Risc |
|---|---|---|---|
| **0. Precondiție de guvernanță** | ADR mic, dedicat: decide dacă citirea read-only a `self.ml` pentru afișare independentă intră sub `RUNTIME_CONTRACT.md` ca extensie aditivă, sau cere redeschiderea documentului | Neschimbat față de v1 — rămâne blocajul real | Zero (document) |
| **1. Serving Wrapper (§3.1)** | Metodă mică în `oracle_engine.py`, NU modul nou separat — citește `self.ml` deja rezolvat, nu re-rezolvă Champion | **Corectat față de v1**: elimină `ml_engine.py` ca prim pas (§1.2.A/C) | Foarte scăzut |
| **2. Afișare UI „🤖 ML"** | Flag propriu, bloc paralel cu Oracle/Blend, populat din wrapper-ul de la Etapa 1, cu motiv explicit de indisponibilitate (§3.1) | Adaugă față de v1: câmpul de motiv, absent din diagrama originală | Scăzut |
| **3. Conectare ML → Blend** | A doua intrare `EngineOutput` în `_get_blend_engine_prediction()` — **primul moment în care Blend chiar combină ceva** (§1.3) | Recontextualizat: nu „adăugăm a doua intrare", ci „Blend devine funcțional pentru prima dată" — schimbă ce trebuie testat | Scăzut, dar testare funcțională obligatorie, nu doar structurală |
| **4+.** | Restul roadmap-ului v1 (calibrare ADR-049, Champion Guardian, ELO Trend etc.) rămâne valid, neschimbat de acest document | — | — |
| **[Explicit exclus]** `ml_engine.py` ca modul separat, `raw_predictions`/ADR-031 wiring | Amânat până la declanșatorul din §3.1/§6 (>1 algoritm de combinat intern) | Nou față de v1 — v1 nu avea acest declanșator explicit | N/A |

---

## 10. Sumar — răspuns direct la întrebările din task

- **Ce există deja?** Tot ciclul de viață al unui model — Registry, Training, Challenger, Shadow, Promotion, Champion Manager, Champion Guardian, Rollback, orchestrare continuă — generic, verificat, nu doar afirmat.
- **Ce poate fi reutilizat?** Absolut tot ce e la §3.2-3.12, neschimbat.
- **Ce lipsește?** Un ADR mic de guvernanță (§9, Etapa 0) — singurul blocaj real.
- **Ce trebuie construit?** Două piese mici, aditive: wrapper-ul de servire (§3.1, în `oracle_engine.py`, NU un modul nou) și blocul UI (§3.13) — nimic altceva.
- **Ce nu trebuie construit?** `ml_engine.py` separat (prematur azi), Feature Pipeline separat (prematur azi), orice wiring în `raw_predictions`/ADR-031, orice schimbare de schemă, orice auto-promovare.
- **Cum comunică componentele?** Exact două canale (§4): tabele Supabase asincron, sau compunere de funcții sincronă în orchestratorul unic — niciodată peer-to-peer.
- **Cum rămâne independent?** Trei garanții deja adevărate în cod + o a patra de menținut mecanic la orice review viitor (§5).
- **Cum evoluează fără refactorizări majore?** Fiecare axă de extindere (algoritm nou, combinare internă, al patrulea motor) are deja un tipar demonstrat sau un declanșator explicit definit (§6) — nimic nu cere o reconstrucție.

Acest document nu autorizează nicio implementare. Etapa 0 rămâne precondiția explicită înainte ca orice cod din §9 să înceapă.
