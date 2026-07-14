# Runtime Contract — cum consumă Runtime un Champion

**Status**: FROZEN (via ADR-019)
**Scope**: Contract normativ, nu ADR — descrie o regulă permanentă, nu o decizie punctuală
**Precondiție pentru**: Pasul 6 (Champion Loading — încărcare + validare) și Pasul 7B (switch-ul real de servire, IMPLEMENTAT) din Implementation Contract al Learning Core

---

## De ce există acest document

Până la Pasul 4.5, invariantul de mai jos a existat DOAR în istoricul conversației dintre Chief Architect și Claude — niciodată transcris. Asta a fost identificat ca o lipsă reală la Architecture Gate Review (înainte de Pasul 5): un contract despre care depinde corectitudinea Promotion nu era trasabil în repo (încalcă Regula #9 CLAUDE.md — „orice rezultat trasabil complet până la sursă"). Acest document închide acel gol.

**Din Pasul 7B, Runtime CITEȘTE și SERVEȘTE din `model_champions`, când e utilizabil** — `FootballOracleEngine._resolve_champion()` (o singură dată per construcție de proces) decide `self.ml_source` (`"champion"`/`"local"`/`"none"`) și seedează `self.ml` corespunzător. Fallback-ul pe antrenare locală (comportamentul din Pasul 0-6) rămâne intact pentru orice condiție nesatisfăcută.

## Invariantul de utilizabilitate (6 condiții simultane)

Runtime poate considera un Champion „utilizabil" **doar dacă TOATE cele șase condiții sunt adevărate simultan**:

1. **Champion există** — există un rând în `model_champions` pentru `(algorithm_family, league_scope)`.
2. **Champion e activ** — `superseded_at IS NULL` pe acel rând.
3. **Artefactul există** — `model_artifact_storage.load_model_artifact(training_run_id)` găsește un obiect la calea așteptată în Storage.
4. **Artefactul e valid** — bytes-ii nu sunt corupți (deserializarea XGBoost nu ridică excepție).
5. **Deserializarea reușește** — modelul reconstruit e un `XGBClassifier` funcțional (`predict_proba` apelabil).
6. **`algorithm_version` compatibil** — adăugat la Architecture Gate 6. `training_runs.algorithm_version` al Champion-ului trebuie să fie identic cu `ml_predictor._ALGORITHM_VERSION` din codul curent. Invariant arhitectural: **Runtime nu încarcă niciodată un Champion antrenat cu o versiune incompatibilă a algoritmului**. Dacă `FEATURE_COLUMNS` s-a schimbat între momentul antrenării Champion-ului și codul curent (ex. o viitoare ablație ca ADR-012/013), un Champion vechi ar putea produce predicții eronate sau ar putea eșua silențios la potrivirea formei — tratat identic cu un artefact invalid, fără excepție specială.

Dacă **oricare singură** dintre cele șase e falsă, Runtime tratează Champion-ul ca **indisponibil în întregime** — niciodată o folosire parțială/improvizată (ex. „folosesc structura dar nu greutățile", sau „folosesc campionul vechi presupus, fără verificare"). Asta e o aplicare directă a Regulii #8 CLAUDE.md: nicio stare necunoscută nu se aproximează.

## Fallback-ul (arhitectură permanentă, nu scaffolding temporar)

```
Champion load → succes (toate 6 condiții) → servește din Champion
             → eșec (oricare condiție falsă)  → antrenează local → servește din modelul local
```

Acest fallback e o parte **permanentă** a arhitecturii — analog cascadei de fallback deja existente în `oracle_api.py` între provideri externi. Nu e un mecanism provizoriu de migrare, care dispare după ce Champion devine „stabil". Eliminarea lui ar necesita un ADR nou, dedicat, cu justificare explicită — niciodată o eliminare tăcută, silențioasă.

## Runtime State Machine — trei stări terminale (Architecture Gate 6)

Nu un state machine cu tranziții observabile în timpul rulării — încărcarea e exclusiv la construcția procesului (o singură dată, sincron, blocant), deci nu există nicio fereastră în care procesul servește cereri „în timp ce încarcă". Trei stări terminale, exclusive, decise o singură dată:

```
CHAMPION_ML   — Champion valid (toate 6 condiții), folosit pentru servire
LOCAL_ML      — Champion indisponibil/invalid, antrenare locală reușită (fallback)
NO_ML         — ambele eșuate — Poisson/Monte Carlo pur
```

„BOOTSTRAP", „CHAMPION_LOADING" și „ERROR" nu sunt stări reale — primele două sunt pași tranzitorii, neobservabili, în interiorul constructorului; „ERROR" colapsează în `NO_ML`, deja gestionat grațios azi.

## Pasul 6 vs. Pasul 7B — separare explicită de responsabilitate (istoric)

Decizie explicită Chief Architect: fiecare gate validează o singură schimbare de responsabilitate.

- **Pasul 6** (închis) — „Poate Runtime încărca și valida un Champion, în siguranță?" A introdus `learning_core/champion_loader.py` (cele 6 condiții) și seeding-ul complet al unui `MLPredictorEngine` candidat, dar rezultatul era folosit STRICT ca diagnostic — `self.ml` rămânea populat exclusiv din antrenarea locală.
- **Pasul 7B** (implementat, Architecture Gate 7B) — „Poate Runtime începe efectiv să servească din Champion?" **CHAMPION_ML e acum operațional**: `self.ml_source` poate lua valoarea `"champion"`, iar `self.ml` e seedat direct din Champion când toate 6 condiții sunt satisfăcute — vezi `FootballOracleEngine._resolve_champion()`. Invarianți impuși la acest gate:
  - **`train()` nu e apelat niciodată când Champion reușește** — nu doar rezultatul ignorat, apelul însuși lipsește (`MLPredictorEngine.train()` are efect secundar Supabase, `sb.save_ml_status`, care ar corupe `ml_model_status` cu statistici ale unei antrenări locale ce nu servește efectiv).
  - **Un singur apel** `champion_loader.load_champion_or_none()` per construcție — rezultatul alimentează simultan decizia de servire, `champion_diagnostic`, și seeding-ul (`seed_from_champion()`) — zero al doilea apel, zero cursă posibilă între diagnostic și ce chiar servește.
  - **`status_summary()` e Champion-aware** — când modelul servit provine din Champion, `accuracy`/`log_loss`/`last_trained_at` provin din datele Champion-ului (`training_runs.walk_forward_metrics`/`created_at`, transportate prin `ChampionLoadResult`), niciodată din `ml_model_status` (tabelă legacy, exclusiv locală) — altfel operatorul ar vedea statistici ale altui model decât cel care servește.

## Ce NU descrie acest document

Nu descrie polling/refresh/cache invalidation/reload manual — niciunul dintre acestea nu există și nu e cerut (YAGNI, respins explicit la Architecture Gate 6 — funcționare autonomă, fără intervenție umană necesară pentru corectitudine). Nu descrie promovare/rollback — acelea sunt „Promotion Contract" (document separat).

## Relația cu Promotion Contract

Promotion (Pasul 5) produce exact obiectul pe care acest contract îl consumă — un rând `model_champions` cu `superseded_at IS NULL` și un `training_run_id` a cărui artefact e garantat valid **la momentul promovării** (vezi `PROMOTION_CONTRACT.md`, secțiunea Precondiții). Runtime Contract nu impune nicio cerință suplimentară asupra lui Promotion — doar declară cum va fi, mai târziu, CONSUMAT rezultatul lui.
