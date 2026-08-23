# ADR-061 — Servirea live a Campionului `blend_v1` (a doua familie consumată de Runtime)

**Status**: Accepted (2026-08-23, aprobat explicit de proprietarul produsului — „aprob ADR nou și implementarea")
**Autor**: Claude (arhitect principal, sesiune delegată explicit)
**Context declanșator**: prima promovare reală din istoria proiectului — `blend_v1` (training_run_id `8ac89c70-8727-459f-aa42-08a2edd16431`), promovat 2026-08-23 09:36:27 UTC, prin ciclul complet Challenger→evaluare statistică→Decision Feed→aprobare umană (ADR-030/037). Verificat imediat după promovare: Campionul nou **nu alimentează nimic vizibil** — `model_champions` a devenit doar bookkeeping fără consumator. Proprietarul produsului a semnalat explicit că asta anulează practic munca de guvernanță deja construită.

## Context

Runtime consumă azi UN singur Campion — `xgboost_v1`, prin `learning_core/champion_loader.py` + `FootballOracleEngine._resolve_champion()`, guvernat de `docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` (**FROZEN**, via ADR-019). Acel document e scris explicit la singular („cum consumă Runtime **un** Champion") și descrie strict starea `self.ml`/`MLPredictorEngine` — trei stări terminale (`CHAMPION_ML`/`LOCAL_ML`/`NO_ML`), cu fallback pe antrenare locală.

`blend_v1` (ADR-050) e o familie de algoritm structurală DIFERITĂ, deja cu propriul ciclu Challenger/shadow (`learning_core/blend_challenger_shadow.py`, decizie explicită §2.3: „inferența reconstruiește direct din artefacte, NU generic peste mai multe familii compuse — YAGNI, un singur algoritm compus există azi"). Investigație directă înainte de a scrie acest ADR (verificat, nu presupus):

- Submodelul ML al `blend_v1` e literal un `MLPredictorEngine` (`learning_core/algorithms/blend_v1.py`) — aceeași clasă, același `ml_predictor.FEATURE_COLUMNS`, ca `xgboost_v1`. Structural identic ca artefact.
- Predicția finală „blend" nu vine din `LearningAlgorithm.predict()` (nefolosit de calea reală, doar conformitate de Protocol) — vine din `blend_challenger_shadow.predict_with_blend_challenger(oracle_probs, features, training_run_id)`, deja scrisă, deja testată prin shadow logging: încarcă artefactul, aplică Temperature Scaling, combină cu Oracle prin `ml_predictor.blend_predictions()` (35% pondere ML, scalată de volum).
- **`champion_loader.py` NU e cu adevărat generic**, deși semnătura (`algorithm_family: str`) sugerează asta. Condiția 6 (RUNTIME_CONTRACT.md) compară `training_run.algorithm_version` cu `ml_predictor._ALGORITHM_VERSION` — o constantă legată explicit de `xgboost_v1`, nu de familia primită ca parametru. Funcționează azi „din întâmplare" pentru `blend_v1` doar pentru că ambele au `version="1"` — o coincidență, nu o garanție arhitecturală. `RUNTIME_CONTRACT.md` fiind FROZEN, acest comportament e literă de contract, nu bug de reparat tacit.
- „Blend Engine" afișat azi în UI (`pred.blend_engine_prediction`, flag `blend_engine_display_enabled`) e un motor COMPLET SEPARAT (`blend_engine.py`, `WeightedAverageStrategy`, algoritm static, zero legătură cu Model Registry) — verificat direct: `self.blend = BlendEngine(BlendConfig.from_dict(...))`, fără nicio citire din `model_champions`. Confuzie de nume reală, de evitat explicit în implementare (naming distinct).

## Decizie

1. **Nu se modifică `champion_loader.py` și nu se reinterpretează `RUNTIME_CONTRACT.md`.** Documentul rămâne exact ce e — scopat la `self.ml`/`xgboost_v1`. Se construiește un mecanism NOU, paralel, dedicat — exact tiparul deja ales de proiect pentru `blend_challenger_shadow.py` față de `challenger_shadow.py` (fișier separat, nu generalizare prematură).
2. **`learning_core/blend_v1_champion_loader.py`** (fișier nou) — aceleași 6 condiții de utilizabilitate ca `champion_loader.py` (există + activ + artefact există + artefact valid + deserializare funcțională + versiune compatibilă), dar condiția 6 compară față de **`learning_core.algorithms.blend_v1.BlendV1Algorithm.version`** — versiunea proprie a familiei, nu una împrumutată. `load_blend_v1_champion_or_none(league_scope)` — semnătură mai restrânsă intenționat (algorithm_family implicit `"blend_v1"`, hardcodat, exact ca `blend_challenger_shadow.py`, YAGNI explicit).
3. **Câmp nou, izolat**: `MatchPrediction.blend_v1_champion_prediction` — NU reutilizează `blend_engine_prediction` (motor diferit, ar produce confuzie: două numere diferite sub aceeași etichetă). Trei stări, niciodată aproximate: `None` (flag oprit / Campion indisponibil la nivel de infrastructură), `{"available": False, "reason": ...}` (Campion absent/artefact invalid pentru acest league_scope), `{"available": True, "prob_home"/"prob_draw"/"prob_away": ...}`.
4. **Flag nou, implicit OPRIT** (North Star #3): `blend_v1_champion_display_enabled`. Activarea în producție e pas separat, explicit, DUPĂ ce codul e verificat complet (teste + rulare reală) — niciodată bundle-uit tacit cu merge-ul.
5. **Zero schimbare la Oracle/ML pur** — `prob_home_win`/`prob_draw`/`prob_away_win` rămân neatinse, exact ca la `blend_engine_prediction`/`ml_engine_prediction`. Zero scriere nouă în `raw_predictions` (ADR-031, presupune explicit 2 motoare — neatins), zero scriere nouă în `shadow_predictions` (asta rămâne exclusiv `blend_challenger_shadow.py`, neschimbat — de altfel, promovarea de azi a oprit deja acumularea shadow pentru `blend_v1`, efect secundar constatat, nu cauzat de acest ADR).
6. **Fallback**: dacă Campionul `blend_v1` devine indisponibil (superseded, artefact corupt, etc.), câmpul devine `{"available": False, ...}` sau `None` — **niciun fallback pe antrenare locală** (spre deosebire de `self.ml`/RUNTIME_CONTRACT.md) — nu există un „`blend_v1` local" cu sens; nu se aproximează.

## Ce NU declanșează acest ADR

- Nu schimbă `RUNTIME_CONTRACT.md` (rămâne FROZEN, neatins).
- Nu promovează automat viitorii Champion `blend_v1` — promovarea rămâne exclusiv guvernată de ADR-030/037 (om în buclă).
- Nu face din `blend_v1` motorul primar — rămâne o a patra voce afișată, alături de Oracle/ML/Blend static, per viziunea ADR-051 (niciun motor primar prin construcție).
- Nu elimină „Blend Engine" static existent — cele două rămân vizibile simultan, etichetate distinct.

## Consecințe

- Runtime consumă acum DOUĂ familii independente de Champion, prin DOUĂ mecanisme paralele, deliberat neunificate (YAGNI — o generalizare prematură ar fi presupus o a treia familie viitoare, neconfirmată). Dacă apare o a treia familie compusă, decizia de generalizare se ia atunci, cu dovadă, nu acum.
- Prima dată când o predicție Champion `blend_v1` devine vizibilă în UI, altfel decât prin shadow logging intern.

## Jurnal de execuție

Executat 2026-08-23, cu aprobare explicită („aprob ADR nou și implementarea", condițiile: verificare permanentă, oricâte teste/audituri necesare).

**Fișiere noi**:
- `learning_core/blend_v1_champion_loader.py` — loader dedicat, 6 condiții de utilizabilitate, condiția 6 verificată față de `BlendV1Algorithm.version` (NU `ml_predictor._ALGORITHM_VERSION`). Zero import din `champion_loader.py` (verificat printr-o gardă AST dedicată).
- `tests/test_blend_v1_champion_loader.py` — 14 teste, mirror `test_champion_loader.py`, plus 2 teste specifice ADR-061 care simulează explicit o DIVERGENȚĂ între `ml_predictor._ALGORITHM_VERSION` și `BlendV1Algorithm.version`, ca gardă de regresie reală (nu doar coincidență de valori).
- `tests/test_blend_v1_champion_serving.py` — 11 teste, mirror `test_blend_engine_orchestration.py`, pentru frontiera `oracle_engine._get_blend_v1_champion_prediction()`.

**Fișiere modificate**: `oracle_engine.py` (câmp nou `blend_v1_champion_prediction` pe `MatchPrediction`, flag nou `blend_v1_champion_display_enabled` implicit False, metodă nouă `_get_blend_v1_champion_prediction()`, apelată o singură dată în `evaluate_match()`), `app.py` (secțiune UI nouă, etichetată explicit „🏆 Blend v1 (Campion promovat)", distinctă de „🔀 Blend" static).

**Verificare că nu se atinge RUNTIME_CONTRACT.md (FROZEN)**: confirmat — `champion_loader.py` neschimbat, `RUNTIME_CONTRACT.md` neschimbat, self.ml/`_resolve_champion()` neatinse.

**Verificare că nu se scrie accidental o coloană nouă în `match_history`**: confirmat prin citire directă a `_cache_prediction()` — construiește un dict explicit, cu chei numite, apelat ÎNAINTE ca `blend_v1_champion_prediction` să fie populat pe `pred`; zero risc de scurgere într-o coloană necunoscută (ADR-036/D3.5, Canonical Feature Ownership, neatins).

**Teste de mutație, nu doar teste care trec** (cerut explicit): prima versiune a testului de gating pe flag (`test_returns_none_when_flag_disabled`) folosea un mock care ridică `AssertionError` dacă e apelat — verificare directă a arătat că acel `AssertionError` e prins de `except Exception` din interiorul metodei și transformat tot în `None`, deci testul trecea „din întâmplare" chiar și cu garda de flag ȘTEARSĂ din cod (mutație aplicată local, confirmată, apoi revertită). Corectat cu un numărător explicit de apeluri. A doua mutație (eliminarea ramurii „predicție eșuată") a fost prinsă corect de testul existent, fără nicio corecție necesară — verificat separat, nu presupus.

**Rulare completă**: `pytest tests/` — **2.585 passed** (2.560 + 25 noi), **2 skipped** — nicio regresie.

**CI**: „Predictor Regression Suite (obligatoriu la merge)" — verde pe commit-ul `d98b659` (`run 32632743940`), declanșat automat de push-ul pe `main`.

**Activare în producție** (2026-08-23, confirmare separată, per `supabase-safety`): `UPDATE model_config SET data = jsonb_set(data, '{blend_v1_champion_display_enabled}', 'true') WHERE id=1` — operație minimă (`jsonb_set`, nu suprascrie restul configurației). Verificat direct, înainte și după: toate celelalte flag-uri (`learning_core_enabled`, `blend_engine_display_enabled`, `ml_engine_display_enabled`) rămase neatinse (`true`, cum erau). Reversibil oricând (revenire la `'false'`).

**Verificare live, capăt la capăt** (2026-08-23) — mediul de dezvoltare nu are acces direct la aplicația Streamlit Cloud (`streamlit.app` blocat de politica de rețea a mediului) și nici la credențialele Supabase locale, deci verificarea vizuală directă în browser nu a fost posibilă. Alternativă la fel de riguroasă: `scripts/verify_blend_v1_champion_serving.py` (nou, read-only, reutilizabil — reproduce exact lanțul din `_get_blend_v1_champion_prediction()`), rulat prin `verify_blend_v1_champion_serving.yml`, contra Supabase de producție reală. Rezultat confirmat: Campionul găsit (`training_run_id=8ac89c70...`, exact cel promovat azi), predicție calculată cu succes pe feature-uri sintetice (`home=0.4835 draw=0.2695 away=0.2469`, sumă 0,9999), **„Lanț complet funcțional: True"**.
