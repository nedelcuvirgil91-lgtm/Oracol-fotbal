# ADR-050 — Extinderea Challenger Framework pentru algoritmi compuși (Blend)

**Status**: ACCEPTED
**Precondiție**: `docs/00_GOVERNANCE/PASUL12_AUDIT_SHADOW_BLEND_CAPABILITY.md` (audit read-only, înghețat, 2026-08-04) — sursa de adevăr factuală pentru acest ADR. Acest document decide, nu re-investighează.
**Precedent normativ**: ADR-028 (FROZEN) — `league_weights_adaptive`, exact aceeași clasă de problemă, deja rezolvată o dată.

---

## 1. Problema (recap din audit, nu re-investigată aici)

Challenger Framework-ul (`shadow_testing.py` → `learning_core/challenger_shadow.py` → `learning_core/model_artifact_storage.py` → `learning_core/promotion_service.py`/`champion_loader.py`) suportă azi **exclusiv algoritmi reprezentabili ca artefact XGBoost persistabil**:

- `learning_core/model_registry.LearningAlgorithm.get_trained_model()` — contract explicit: *"compatibil cu backend-ul curent de persistență (XGBClassifier `.save_model()`/`.load_model()`/`.predict_proba()`) — NU orice obiect Python arbitrar"*.
- `learning_core/challenger_shadow.predict_with_challenger()` — nu trece prin `LearningAlgorithm.predict()`; încarcă artefactul brut și apelează direct `model.predict_proba()`/`model.predict(output_margin=True)` — API nativ XGBoost/sklearn, bypass complet al abstracției Model Registry.
- `oracle_engine._log_challenger_shadow()` — verifică un singur `algorithm_family` hardcodat (`ml_predictor._ALGORITHM_FAMILY = "xgboost_v1"`), nu iterează peste Model Registry.

Un Challenger de tip **Blend** (Oracle, determinist/neantrenat, combinat cu un submodel ML via `ml_predictor.blend_predictions()`) nu se încadrează în acest contract: nu e un obiect XGBoost unic, ci o compunere de (a) o formulă Poisson calculată live din `feature_engine` și (b) un submodel ML antrenat.

**Verdict audit, verbatim**: contractele `shadow_testing.py`/`training_runner.py`/`challenger_manager.py` sunt suficiente și generice; `learning_core/challenger_shadow.py` și domeniul de valori al `get_trained_model()` **nu sunt suficiente** pentru un Challenger compus.

## 2. Context — precedentul ADR-028

`learning_core/algorithms/league_weights_adaptive.py` a lovit exact aceeași barieră structurală și documentează explicit: *"generalizarea acelui lanț pentru algoritmi non-artifact ar fi o extindere de scope reală, nu o migrare... și ar necesita un ADR nou dedicat."* Decizia luată atunci (ADR-028, FROZEN) a fost excluderea totală (`participates_in_challenger_framework: False`) — algoritmul nu produce deloc probabilități 1X2 proprii, deci excluderea e naturală, fără cost.

**Blend nu e cazul `league_weights_adaptive`.** Are un submodel ML real (compatibil `get_trained_model()`), și rezultatul lui final e o probabilitate 1X2 validă, evaluabilă. Excluderea totală, ca la `league_weights_adaptive`, ar elimina definitiv orice cale prin care Blend ar putea acumula dovadă statistică din trafic live (`shadow_testing.evaluate_experiment()`, testele pereche Brier/log-loss/accuracy) — singura cale prin care North Star #2 din `CLAUDE.md` („dovadă statistică simultană pe metrici multiple") poate fi satisfăcută azi în proiect. Un benchmark punctual (ca Pasul 11) rămâne, prin propria lui declarație de limitări, „rulat o singură dată... nu dovadă statistică tare" — nu poate înlocui shadow testing-ul ca bază de promovare.

Acest ADR decide **dacă și cum** se generalizează Challenger Framework-ul pentru algoritmi compuși — nu dacă Blend „e mai bun" (întrebare separată, Pasul 11/14).

## 3. Alternative analizate

### 3.1 Alternativa A — Excludere totală (mirror exact al `league_weights_adaptive`)

`describe()["participates_in_challenger_framework"] = False` pentru orice viitor adaptor Blend.

- **Pro**: zero risc, zero cod nou, consecvent cu precedentul deja acceptat.
- **Contra**: elimină definitiv posibilitatea ca Blend să fie vreodată evaluat prin shadow testing/promovat prin Challenger Framework — Pasul 14 din roadmap-ul curent („Evaluare shadow → decizie de promovare") ar deveni imposibil de executat pentru Blend, contrazicând intenția explicită deja exprimată în structura pașilor 12-14.

### 3.2 Alternativa B — Generalizare completă: toate Challenger-ii, inclusiv `xgboost_v1`, evaluați prin `LearningAlgorithm.predict()`

Rutare unică prin abstracția Model Registry, eliminând calea directă pe artefact din `challenger_shadow.py`.

- **Pro**: o singură cale de inferență, abstracție curată.
- **Contra**: (1) necesită un mecanism nou, azi inexistent, care să reconstruiască o instanță `LearningAlgorithm` complet „hidratată" (model încărcat, temperatură de calibrare seedată) dintr-un `training_run_id` — nu doar pentru un viitor adaptor Blend, ci pentru TOȚI algoritmii; (2) **schimbă comportamentul deja verificat al Challenger-ului `xgboost_v1` existent** (risc de regresie pe un cod care funcționează azi, semnalat explicit în audit) — orice diferență ar trebui tratată ca regresie, nu ca îmbunătățire; (3) contrazice disciplina „blast radius minim" respectată consecvent la Pașii 9/10a/10b/11 (fiecare a evitat explicit atingerea unui cod deja funcțional pentru a livra o funcționalitate nouă).

### 3.3 Alternativa C — Extindere care păstrează integral compatibilitatea cu fluxul actual

Framework-ul Challenger se extinde pentru a suporta algoritmi compuși, cu o singură condiție obligatorie: comportamentul actual al Challenger-ului XGBoost (`xgboost_v1`) rămâne neschimbat. Forma tehnică exactă a extensiei — modul nou, ramură condiționată, sau altă structură — nu e decisă aici, rămâne responsabilitatea Implementation Plan-ului (§5).

- **Pro**: zero risc de regresie pe `xgboost_v1` — condiție structurală, nu doar testată ulterior; deschide o cale reală spre Pasul 14 pentru Blend; consecvent cu filosofia „niciun flag nou nu pornește implicit activ" (North Star #3) — orice extensie ar fi opt-in explicit per algoritm.
- **Contra**: posibil cost de întreținere dacă extensia introduce o cale de evaluare separată de cea actuală — magnitudinea exactă depinde de forma aleasă la Implementation Plan.

## 4. Decizia

**Framework-ul Challenger se extinde fără modificarea comportamentului existent al Challenger-ului XGBoost. Orice suport pentru algoritmi compuși trebuie introdus astfel încât compatibilitatea cu fluxul actual să fie păstrată integral. Forma concretă a extensiei rămâne responsabilitatea Implementation Plan-ului.**

Motivare, în ordine de prioritate:

1. **Zero regresie pe Challenger-ul ML existent** — singurul criteriu absolut din cele trei alternative care garantează, prin construcție (nu prin testare ulterioară), că `xgboost_v1` continuă să funcționeze exact ca azi. Alternativa B face acest risc dependent de calitatea testelor de regresie; Alternativa C îl elimină structural, indiferent de forma tehnică aleasă ulterior.
2. **Consecvență cu întregul istoric ADR-048/049** — fiecare decizie anterioară din acest fir (persistare artefact, calibrare) a ales explicit varianta cu blast radius minim față de o generalizare mai „curată" arhitectural, de fiecare dată motivat de riscul asupra codului deja funcțional. Alternativa C continuă acest tipar, nu îl întrerupe.
3. **Excluderea totală (Alternativa A) ar bloca permanent Pasul 14**, deja anticipat explicit în structura curentă a EPIC-ului — o decizie ce ar trebui luată conștient, nu ca efect secundar al celei mai simple opțiuni tehnice.

## 5. Ce NU decide acest ADR (rămâne pentru Implementation Plan)

Consecvent cu tiparul deja stabilit la ADR-049 (separarea explicită decizie/mecanism, §5): acest ADR fixează **CE** se întâmplă la nivel de contract, nu **CUM** se implementează tehnic. Următoarele rămân decizii de Implementation Plan, nu de arhitectură:

- Forma exactă a mecanismului aditiv din §3.3/§4 (nu se presupune `LearningAlgorithm.predict()`, nici orice altă formă specifică) — Implementation Plan-ul evaluează opțiuni tehnice concrete.
- Cum obține mecanismul nou probabilitățile Oracle live (`poisson_probs`) fără a duplica `feature_engine.calibrate_xg()`/`poisson_model()` — risc semnalat explicit în audit, de rezolvat tehnic la Implementation Plan.
- Cum rezolvă `oracle_engine._log_challenger_shadow()` verificarea mai multor familii de algoritm simultan (azi hardcodat pe una singură) — decizie de implementare, nu de contract.
- **Interacțiunea calibrare↔blend** (întrebare ridicată explicit în audit, §4 „Riscuri"): dacă Temperature Scaling (ADR-049) se aplică pe probabilitățile submodelului ML înainte de combinarea cu Oracle, sau pe rezultatul blend-ului — rămâne explicit deschisă, de rezolvat la Implementation Plan, nu presupusă aici.
- Ce înseamnă exact „artefact persistat" pentru un Challenger compus (probabil doar submodelul ML, dar neconfirmat aici ca decizie finală).

## 6. Impact asupra componentelor

### 6.1 Normativ (impus direct de acest ADR)

| Componentă | Impact |
|---|---|
| `learning_core/challenger_shadow.py` | Calea existentă (`predict_with_challenger()` pe artefact XGBoost) își păstrează **comportamentul neschimbat** — orice extindere pentru algoritmi compuși nu modifică felul în care e evaluat azi un Challenger `xgboost_v1`. |
| `oracle_engine.py` | Implementarea va trebui să permită evaluarea Challenger-ilor din mai multe familii de algoritmi, păstrând compatibilitatea cu fluxul actual — forma exactă (cum anume se extinde verificarea azi limitată la o singură familie) rămâne la Implementation Plan. |
| `learning_core/model_registry.py` | `get_trained_model()` — contractul actual (XGBoost-only) **rămâne valabil pentru algoritmii existenți**; un algoritm compus poate avea un contract suplimentar, definit la Implementation Plan, dar nu prin slăbirea contractului actual. |
| `docs/00_GOVERNANCE/ADR-028-league-weights-model-registry.md` | Neatins — precedentul rămâne valabil pentru `league_weights_adaptive`; acest ADR nu-l suprascrie, îl extinde pentru un caz diferit (algoritm compus cu submodel ML real, nu algoritm fără ieșire proprie). |

### 6.2 Neatinse, confirmat

`shadow_testing.py`, `learning_core/model_artifact_storage.py`, `learning_core/calibration_artifact_storage.py`, `learning_core/training_runner.py`, `learning_core/challenger_manager.py`, `ml_predictor.blend_predictions()` — toate deja suficiente/generice per audit, niciun motiv de schimbare.

## 7. Backward compatibility

Garantat structural, nu doar testat: orice extindere e opt-in explicit per `algorithm_family` — niciun Challenger existent, niciun cod existent de evaluare `xgboost_v1` nu e atins. Consecvent cu North Star #3 (`CLAUDE.md`): niciun flag/comportament nou nu pornește implicit activ.

## 7.1 Invariant arhitectural

Acesta e contractul real pe care acest ADR îl protejează, indiferent de forma tehnică aleasă la Implementation Plan:

- **Evaluarea Champion-ului live rămâne neschimbată** — nicio extindere a Challenger Framework-ului nu atinge `champion_loader.py`/`oracle_engine._resolve_champion()`.
- **Niciun Challenger nu poate influența predicția live** — shadow-ul rămâne, ca azi, un side effect al predicției, niciodată parte din calea care construiește răspunsul servit utilizatorului.
- **Shadow testing continuă să fie strict read-only** — nicio scriere în `match_history`/`weights.json`/`model_config` din calea de evaluare shadow.
- **Promovarea rămâne singurul mecanism care poate schimba Champion-ul** — `promotion_service.py`, neatins de acest ADR, rămâne unica poartă, exact ca azi.

## 8. Ce NU acoperă acest ADR

- Nu decide dacă Blend „câștigă" vs. Oracle/ML — răspuns deja parțial dat de Pasul 11 (benchmark), rămâne subiect al Pasului 14 (decizie de promovare, bazată pe shadow testing real, nu pe acest ADR).
- Nu atinge `promotion_service.py`/`champion_loader.py`/`RUNTIME_CONTRACT.md` (servire live) — echivalentul „Pasul 10b" pentru Blend rămâne un pas separat, ulterior, DUPĂ ce Blend ar trece prin shadow testing și ar fi promovat.
- Nu modifică `ADR-028` — rămâne FROZEN, valabil pentru `league_weights_adaptive`.

## 9. Consecințe

- **Pozitive**: Pasul 14 rămâne posibil pentru Blend; zero risc pentru Challenger-ul ML existent; disciplina „blast radius minim" a proiectului rămâne intactă pe tot firul ADR-048→049→050.
- **Negative/costuri acceptate**: posibil cost de întreținere suplimentar dacă extensia introduce o cale de evaluare distinctă de cea actuală (magnitudinea exactă depinde de forma aleasă la Implementation Plan); complexitate suplimentară în verificarea multi-familie din `oracle_engine._log_challenger_shadow()`.
- **Amânate, deliberat**: forma tehnică exactă a mecanismului, interacțiunea calibrare↔blend, formatul artefactului compus — toate la Implementation Plan.

---

**Status**: **ACCEPTED** — 2026-08-04, de proprietarul produsului, după integrarea a 4 clarificări de formulare cerute la review (fără impact conceptual): (1) §3.3/§4, decizia reformulată la nivel de contract ("comportament neschimbat", nu o formă tehnică specifică precum "mecanism nou, separat"); (2) §6.1, limbaj imperativ înlocuit cu formulare orientată pe rezultat, nu pe implementare; (3) §7.1, secțiune nouă "Invariant arhitectural" (4 invarianți: Champion live neschimbat, niciun Challenger nu influențează predicția live, shadow strict read-only, promovarea rămâne singurul mecanism de schimbare a Champion-ului); (4) eliminarea expresiei „byte-identic" în favoarea „comportament neschimbat"/"compatibilitate funcțională completă". Se poate trece la redactarea Implementation Plan-ului pentru Pasul 13, fără cod și fără commit până la aprobare separată.
