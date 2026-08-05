# Phase 1 — Blueprint Tehnic Final (ML Engine Serving Wrapper)

**Status**: blueprint de implementare — nu e cod, nu e ADR, nu e design nou. Derivat exclusiv din auditul de dependențe deja verificat (`ML_IMPLEMENTATION_ROADMAP.md` Phase 1, corectat față de `ML_ENGINE_SYSTEM_ARCHITECTURE_V3.md` §3.1 pe baza citirii directe de cod). Fiecare decizie de mai jos e mecanică — o consecință directă a unui fapt deja verificat, nu o alegere nouă de arhitectură.

**Precondiție neschimbată**: acest blueprint NU autorizează implementare. Rămâne condiționat de închiderea Phase 0 (ADR dedicat, RUNTIME_CONTRACT.md) — vezi `ML_IMPLEMENTATION_ROADMAP.md`.

---

## 1. Lista exactă a modificărilor în `oracle_engine.py`

Patru și numai patru puncte de atingere, toate în același fișier. Niciun alt fișier de cod nu se modifică (Blend Engine, Champion Loader, Promotion, Model Registry rămân byte-identice).

| # | Locație | Tip de modificare |
|---|---|---|
| 1.1 | `DEFAULT_CONFIG` (blocul de flag-uri, lângă linia 184) | O intrare nouă, aditivă |
| 1.2 | `class MatchPrediction` (lângă linia 434) | Un câmp nou, aditiv, cu default |
| 1.3 | `class FootballOracleEngine` (lângă linia 1989, imediat după `_get_blend_engine_prediction()`) | O metodă nouă |
| 1.4 | `evaluate_match()` (lângă linia 1773, înainte de `return pred`) | Un apel nou, o singură linie de atribuire |

Plus, în afara codului Python: o actualizare a rândului live `model_config` din Supabase, cu noua cheie de flag (SQL arătat explicit înainte de rulare, per `supabase-safety`).

---

## 2. Modificarea în `MatchPrediction`

Câmp nou, poziționat imediat după `blend_engine_prediction` (linia 434), în aceeași secțiune comentată „Blend Engine (ADR-051/ADR-052, Vision Shift)" — sau într-o secțiune proprie nouă, „ML Engine (ADR-051, Phase 1)", imediat sub ea.

- **Nume**: `ml_engine_prediction`
- **Tip**: `dict | None`
- **Default**: `None`
- **Semantică**: câmp izolat, fără alt cititor în afara UI-ului viitor (Phase 5) — NU intră în `raw_predictions` (ADR-031), NU intră în `shadow_predictions`, exact tratamentul deja aplicat lui `blend_engine_prediction`.
- **Formă a dict-ului când nu e `None`** (vezi §5 pentru detaliu complet):
  - succes: chei `available` (`True`), `prob_home`, `prob_draw`, `prob_away`.
  - indisponibil (dar flag-ul activ): chei `available` (`False`), `reason`.

Niciun alt câmp din `MatchPrediction` nu se modifică. `blend_engine_prediction`, `raw_predictions`, `prob_home_win`/`prob_draw`/`prob_away_win` rămân byte-identice.

---

## 3. Noul flow `evaluate_match()`

Flow-ul existent (linia 1454-1775) rămâne neschimbat de la primul rând până la `return pred` — o singură inserție, la finalul funcției, simetrică cu cea deja existentă pentru Blend:

```
... (tot ce există azi, neschimbat)
pred = MatchPrediction(...)                                    # linia 1662, neschimbat
self._cache_prediction(pred, ...)                               # neschimbat
[4× shadow logging, niciunul nu modifică pred]                  # neschimbat
pred.blend_engine_prediction = self._get_blend_engine_prediction(pred)   # linia 1773, neschimbat
pred.ml_engine_prediction = self._get_ml_engine_prediction(pred)         # ← INSERȚIE NOUĂ, imediat după
return pred                                                     # neschimbat
```

Ordinea relativă între cele două inserții (Blend vs. ML) nu contează funcțional — sunt complet independente, niciuna nu citește ieșirea celeilalte. Poziția „imediat după Blend" e aleasă doar pentru lizibilitate (grupare vizuală a celor două motoare de afișare independentă), nu e o dependință.

Niciun alt punct din `evaluate_match()` nu se atinge — inclusiv blocul legacy `ml_blending_enabled` (1588-1617) rămâne complet neschimbat, cod separat, flag separat, scop separat.

---

## 4. Unde se apelează `self.ml.predict()`

**Un singur loc nou**: în interiorul metodei noi `_get_ml_engine_prediction()` (§1.3), NICĂIERI altundeva.

**Condiții exacte, verificate în ordine, fail-fast** (mirror `_get_blend_engine_prediction()`, linia 1977-1980, extins):

1. Dacă `self.config.get("ml_engine_display_enabled", False)` e `False` → `return None` imediat. Zero cost, zero calcul, zero apel.
2. Dacă `self.ml` e `None` sau `self.ml.is_trained` e `False` → `return {"available": False, "reason": "model_indisponibil"}`.
3. Altfel: apelează `self._build_ml_features(...)` — **exact aceiași parametri ca la blocul legacy** (linia 1603-1605: `home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen`) — apoi `self.ml.predict(ml_features)`.
4. Dacă `self.ml.predict(...)` întoarce `None` (predicție eșuată pentru acest meci specific — vezi `ml_predictor.py:549`, cazul `not self.is_trained or self.model is None`, sau excepția internă prinsă la linia 576) → `return {"available": False, "reason": "predictie_esuata"}`.
5. Dacă întoarce un `MLPrediction` valid → `return {"available": True, "prob_home": ..., "prob_draw": ..., "prob_away": ...}` (rotunjire deja aplicată de `MLPrediction`, nu se rotunjește a doua oară).

**Verificare explicită, obligatorie la implementare**: acest apel e complet INDEPENDENT de `ml_blending_enabled` (linia 1601) — nu-l citește, nu-l influențează, nu e influențat de el. Cele două blocuri (legacy la 1588-1617, wrapper-ul nou lângă 1773) pot fi ambele active, ambele inactive, sau în orice combinație, fără interacțiune.

**Ce NU se schimbă**: `self.ml.predict()` însuși (`ml_predictor.py`), `self._build_ml_features()` (`oracle_engine.py:1409`) — ambele reutilizate EXACT ca azi, zero linie modificată în ele.

---

## 5. Cum se construiește `ml_engine_prediction`

Metoda nouă `_get_ml_engine_prediction(self, pred: MatchPrediction) -> dict | None`:

- **Semnătură**: identică ca formă cu `_get_blend_engine_prediction(self, pred: MatchPrediction) -> dict | None` (linia 1967) — primește `pred` deja construit complet, pentru consecvență de tipar, deși strict tehnic n-are nevoie decât de valorile intermediare deja disponibile în `evaluate_match()` (`home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen`) — **acestea trebuie pasate ca parametri suplimentari** (spre deosebire de `_get_blend_engine_prediction()`, care le derivă din `pred` — `ml_engine_prediction` nu poate, pentru că `_build_ml_features()` are nevoie de obiectele intermediare `home_p`/`away_p`/`h2h`/`mc`, nu doar de câmpurile finale din `pred`). **Decizie mecanică, nu de design**: semnătura reală trebuie să fie `_get_ml_engine_prediction(self, pred, home_p, away_p, h2h, home_xg, away_xg, ph, pd, pa, mc, w_pen)`, apelată din `evaluate_match()` cu exact aceleași variabile locale deja folosite la linia 1603-1605.
- **Try/except propriu**, la fel ca `_get_blend_engine_prediction()` (1981-1989) — orice excepție internă neașteptată e prinsă, logată la nivel `debug`, și rezultă în `return None` (nu în dict-ul cu `reason` — un `None` brut aici înseamnă eroare de infrastructură neprevăzută, distinctă de „model indisponibil"/„predicție eșuată", care sunt stări cunoscute, așteptate).
- **Forma finală a valorii întoarse** (rezumat din §4):

| Caz | Valoare întoarsă |
|---|---|
| Flag oprit | `None` |
| Excepție internă neprevăzută | `None` |
| Flag activ, `self.ml` indisponibil/netrenuit | `{"available": False, "reason": "model_indisponibil"}` |
| Flag activ, `self.ml.predict()` întoarce `None` pentru acest meci | `{"available": False, "reason": "predictie_esuata"}` |
| Flag activ, succes | `{"available": True, "prob_home": float, "prob_draw": float, "prob_away": float}` |

Cele două șiruri `"model_indisponibil"`/`"predictie_esuata"` sunt identificatori interni, stabili, consumabili mecanic de UI-ul viitor (Phase 5) — nu texte de afișat direct, exact tiparul deja folosit în proiect pentru coduri de stare (`ml_source`: `"champion"/"local"/"none"`).

---

## 6. Flag-ul nou

- **Nume**: `ml_engine_display_enabled`
- **Valoare implicită**: `False` (North Star #3, CLAUDE.md — niciun flag nou nu pornește implicit activ)
- **Locație în cod**: `DEFAULT_CONFIG`, lângă `blend_engine_display_enabled` (linia 184), cu comentariu simetric care explică scopul (populează exclusiv `pred.ml_engine_prediction`, neînrudit cu `ml_blending_enabled`).
- **Locație live**: rândul `model_config` din Supabase (proiect `Prediction`) — trebuie adăugat explicit prin UPDATE aditiv, altfel flag-ul din cod nu are efect (rândul live există deja, `load_config()` întoarce rândul întreg, nu îl combină cu `DEFAULT_CONFIG` — lecție deja confirmată de două ori în această sesiune).
- **Ce NU controlează**: nu influențează `ml_blending_enabled`, nu influențează `blend_engine_display_enabled`, nu influențează conectarea ML→Blend (care nu există în acest roadmap, per `ML_IMPLEMENTATION_ROADMAP.md` §8, punctul 7).

---

## 7. Teste care trebuie scrise

Fișier nou, mirror structural `tests/test_blend_engine_orchestration.py` (fișierul real, verificat — nu `test_blend_engine_ui_display.py`, care nu există ca sursă).

Cazuri obligatorii, fiecare un test separat:

1. Flag `ml_engine_display_enabled=False` → `pred.ml_engine_prediction is None`, zero apel către `self.ml.predict()` (verificat prin mock/spy, nu doar prin rezultat).
2. Flag `True`, `self.ml is None` → `{"available": False, "reason": "model_indisponibil"}`.
3. Flag `True`, `self.ml.is_trained is False` → `{"available": False, "reason": "model_indisponibil"}`.
4. Flag `True`, `self.ml.is_trained is True`, `self.ml.predict()` mock-uit să întoarcă `None` → `{"available": False, "reason": "predictie_esuata"}`.
5. Flag `True`, `self.ml.predict()` mock-uit să întoarcă un `MLPrediction` valid → `{"available": True, "prob_home": ..., "prob_draw": ..., "prob_away": ...}` cu valorile exacte transportate corect.
6. Excepție internă forțată (ex. `_build_ml_features` aruncă) → `None`, nu propagă, nu crapă `evaluate_match()`.
7. **Test de regresie obligatoriu**: `pred.blend_engine_prediction` și `pred.prob_home_win`/`prob_draw`/`prob_away_win` rămân byte-identice cu/fără flag-ul nou activ — dovedește zero interferență cu predicția Oracle servită.
8. **Test de izolare obligatoriu**: activarea `ml_engine_display_enabled` cu `ml_blending_enabled` simultan oprit (și viceversa) nu produce nicio diferență în comportamentul celuilalt flag — cele două căi rămân independente.
9. **Test de atomicitate** (regresie asupra invariantului RUNTIME_CONTRACT.md): mock pe `champion_loader.load_champion_or_none()` cu un counter — verifică exact 1 apel per construcție de `FootballOracleEngine`, indiferent de câte predicții/`evaluate_match()` se rulează după, indiferent de flag-ul nou.

Suita completă `pytest tests/` trebuie să rămână verde, integral, după adăugare — fără nicio modificare a testelor existente pentru Blend/Champion Loader/Promotion.

---

## 8. Invariantele ADR-051 care trebuie păstrate, verificabile mecanic

1. **Independență de intrare** — `_get_ml_engine_prediction()` nu primește, în semnătura ei, niciun parametru derivat din `pred.prob_home_win`/`pred.prob_draw`/`pred.prob_away_win`/`pred.blend_engine_prediction` (ieșirile Oracle/Blend deja calculate). Verificare mecanică la review: grep pe semnătura metodei pentru orice referință la `pred.prob_*`/`pred.blend_*` folosită ca INPUT de calcul (folosirea lui `pred` doar ca „obiect purtător" pentru identificare meci, dacă rămâne în semnătură, e admisă — folosirea valorilor lui ca feature de intrare pentru ML NU e admisă).
2. **`_build_ml_features()` neschimbată** — feature-urile calculate pentru ML rămân exact cele deja folosite de blocul legacy, derivate din date brute (`home_p`, `away_p`, `h2h`, `mc`), niciodată din decizia finală a lui Oracle.
3. **`FEATURE_COLUMNS` neschimbat** — Phase 1 nu adaugă, nu elimină, nu reordonează niciun feature. `self.ml.predict()` continuă să ignore cheile din `ml_features` care nu sunt în `FEATURE_COLUMNS` (`home_xg_pred`, `mc_prob_*` rămân prezente în dict, dar neconsumate de model — comportament deja verificat, neschimbat).
4. **Zero al doilea apel Champion** — `champion_loader.load_champion_or_none()` rămâne apelat exact o dată per proces, exclusiv din `_resolve_champion()`. Wrapper-ul nou NU importă `champion_loader`, NU importă `model_artifact_storage`, nu citește Champion-ul direct în niciun fel.
5. **Zero modificare a predicției Oracle servite** — `ph`, `pd`, `pa` (folosite pentru `prob_home_win`/etc.) nu sunt atinse de noul cod în niciun fel; wrapper-ul rulează strict DUPĂ ce `pred` e deja construit complet.
6. **Zero modificare a Blend Engine** — `blend_engine.py` rămâne fișier neatins; `_get_blend_engine_prediction()` rămâne neschimbată; conectarea ML→Blend NU face parte din Phase 1 (confirmat, absentă din roadmap).
7. **Zero modificare a Promotion/Champion Manager** — niciun cod din Phase 1 scrie în `model_champions`/`challengers`/`training_runs`.
8. **Flag implicit oprit** — `ml_engine_display_enabled=False` până la o decizie explicită separată de activare (North Star #3).
9. **Nicio stare necunoscută aproximată** — `{"available": False, "reason": ...}` există exact ca să nu se confunde „ML indisponibil, motiv cunoscut" cu „eroare neprevăzută" (`None`) sau cu „ML dezactivat" (tot `None`, dar din alt motiv) — cele trei stări rămân distincte în cod, chiar dacă Phase 5 (UI) le va afișa diferit abia mai târziu.

---

Acest blueprint nu autorizează implementare. Rămâne condiționat de închiderea Phase 0.
