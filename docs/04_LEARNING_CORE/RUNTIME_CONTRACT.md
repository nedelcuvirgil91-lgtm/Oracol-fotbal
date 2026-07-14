# Runtime Contract — cum consumă Runtime un Champion

**Status**: FROZEN (via ADR-019)
**Scope**: Contract normativ, nu ADR — descrie o regulă permanentă, nu o decizie punctuală
**Precondiție pentru**: Pasul 6/7 (Runtime gains read capability) din Implementation Contract al Learning Core

---

## De ce există acest document

Până la Pasul 4.5, invariantul de mai jos a existat DOAR în istoricul conversației dintre Chief Architect și Claude — niciodată transcris. Asta a fost identificat ca o lipsă reală la Architecture Gate Review (înainte de Pasul 5): un contract despre care depinde corectitudinea Promotion nu era trasabil în repo (încalcă Regula #9 CLAUDE.md — „orice rezultat trasabil complet până la sursă"). Acest document închide acel gol.

**Runtime, azi (după Pasul 1-4), NU citește `model_champions` în niciun fel** — verificat exhaustiv, zero hit-uri în `oracle_engine.py` pentru `model_champions`/`challenger_manager`/`champion_comparison`, dincolo de hook-ul de Shadow Logging deja auditat (ADR-017). `FootballOracleEngine.__init__()` apelează necondiționat `self.ml.train()` la fiecare pornire de proces — complet neconștient de conceptul de Champion.

Acest document NU implementează schimbarea asta acum. Descrie contractul pe care Runtime trebuie să-l respecte **atunci când** o va face (Pasul 6/7) — scris acum, ca precondiție pentru Promotion (Pasul 5), fiindcă Promotion produce exact obiectul pe care acest contract îl guvernează.

## Invariantul de utilizabilitate (5 condiții simultane)

Runtime poate considera un Champion „utilizabil" (și-l poate încărca pentru servire) **doar dacă TOATE cele cinci condiții sunt adevărate simultan**:

1. **Champion există** — există un rând în `model_champions` pentru `(algorithm_family, league_scope)`.
2. **Champion e activ** — `superseded_at IS NULL` pe acel rând.
3. **Artefactul există** — `model_artifact_storage.load_model_artifact(training_run_id)` găsește un obiect la calea așteptată în Storage.
4. **Artefactul e valid** — bytes-ii nu sunt corupți (deserializarea XGBoost nu ridică excepție).
5. **Deserializarea reușește** — modelul reconstruit e un `XGBClassifier` funcțional (`predict_proba` apelabil).

Dacă **oricare singură** dintre cele cinci e falsă, Runtime tratează Champion-ul ca **indisponibil în întregime** — niciodată o folosire parțială/improvizată (ex. „folosesc structura dar nu greutățile", sau „folosesc campionul vechi presupus, fără verificare"). Asta e o aplicare directă a Regulii #8 CLAUDE.md: nicio stare necunoscută nu se aproximează.

## Fallback-ul (arhitectură permanentă, nu scaffolding temporar)

```
Champion load → succes (toate 5 condiții) → servește din Champion
             → eșec (oricare condiție falsă)  → antrenează local → servește din modelul local
```

Acest fallback e o parte **permanentă** a arhitecturii — analog cascadei de fallback deja existente în `oracle_api.py` între provideri externi. Nu e un mecanism provizoriu de migrare, care dispare după ce Champion devine „stabil". Eliminarea lui ar necesita un ADR nou, dedicat, cu justificare explicită — niciodată o eliminare tăcută, silențioasă.

## Ce NU descrie acest document

Nu descrie CUM Runtime ajunge să citească `model_champions` (asta e implementarea Pasului 6/7, nescrisă încă). Nu descrie polling/refresh/cache invalidation — niciunul dintre acestea nu există și nu e cerut azi (YAGNI). Nu descrie promovare/rollback — acelea sunt „Promotion Contract" (document separat).

## Relația cu Promotion Contract

Promotion (Pasul 5) produce exact obiectul pe care acest contract îl consumă — un rând `model_champions` cu `superseded_at IS NULL` și un `training_run_id` a cărui artefact e garantat valid **la momentul promovării** (vezi `PROMOTION_CONTRACT.md`, secțiunea Precondiții). Runtime Contract nu impune nicio cerință suplimentară asupra lui Promotion — doar declară cum va fi, mai târziu, CONSUMAT rezultatul lui.
