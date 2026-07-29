# ML Activation Gate — Predictor + ML Blending

**Status**: checkpoint activ, obligatoriu. Document-only (R-ML-GATE-01) — nu schimbă cod, nu schimbă configurație, nu atinge `ml_blending_enabled`/`ml_blend_weight`.
**Creat**: 2026-07-29, ca răspuns direct la riscul semnalat explicit: "peste câteva săptămâni nimeni nu mai ține minte că blending-ul pornește automat după primul model antrenat."

## Scop

Acest document e locul unic, permanent, care răspunde la o singură întrebare: **e permisă activarea blending-ului Predictor+ML în producție?** Răspunsul e "nu" până toate condițiile de mai jos sunt bifate — nu prin memorie sau presupunere, ci prin verificare directă a acestui fișier.

## Mecanismul de aplicare (deja în cod, neschimbat de acest document)

R-ARCH-REVIEW-01 a mutat controlul blend-ului de la `is_trained` (avea ML un model?) la `model_config.ml_blending_enabled` (decizie manuală explicită), implicit `False` — `oracle_engine.py::evaluate_match()`:

```python
if self.ml and self.ml.is_trained and self.config.get("ml_blending_enabled", False):
```

Acest document **nu modifică acel cod** — descrie DOAR condițiile sub care cineva (Product Owner) ar trebui, în viitor, să schimbe `ml_blending_enabled` la `true` în `model_config` (Supabase).

## Condiții obligatorii, toate simultan, înainte de activare

```
□ Bootstrap complet pentru SuperLiga (ultimul sezon complet — vezi
  docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md §10.3/§10.4)
□ Suficiente date reale acumulate din sezonul curent (Night Sync, în
  regim de croazieră — vezi §10.5 din același document)
□ Validare de performanță ML pe date reale (nu presupusă) — un test de
  ablație/evaluare dedicat, măsurat, nu un procent estimat (vezi
  recomandarea din docs/06_UDAL/R-SYNC-FLASH-01_PREDICTOR_IMPACT_ANALYSIS.md §3)
□ Aprobare explicită a Product Owner-ului — separată, nu implicită în
  aprobarea unui alt task
```

Nicio bifă parțială — la fel ca disciplina `DEFINITION_OF_DONE.md` ("O căsuță rămâne goală... până la rezolvare"), o condiție neîndeplinită nu se rotunjește optimist.

## Starea curentă, până la bifarea completă

- **Predictorul** (Poisson/ELO/formă) rămâne sistemul principal de decizie — neschimbat, activ, servește predicții azi.
- **ML continuă să se antreneze zilnic** (`PipelineStep("ml_retrain")`, `continuous_learning.yml`) — complet neafectat de acest gate, per R-ARCH-REVIEW-01.
- **ML poate fi analizat și comparat** — modelele, metricile (`training_runs`, Champion/Challenger) rămân disponibile pentru observare, fără să influențeze predicția finală servită.
- **Activarea blending-ului pentru producție NU se face automat** — nici la un număr de meciuri atins, nici la o dată calendaristică, nici implicit la vreun alt task — doar prin bifarea explicită a celor 4 condiții de mai sus + schimbarea manuală a `ml_blending_enabled`.

## Things to review before Production

- [ ] **ML Activation Gate** (acest document) — toate cele 4 condiții bifate, cu dovadă (nu presupunere), înainte de a seta `ml_blending_enabled=true` în `model_config`.

*(Listă deschisă pentru extindere — alte verificări de pre-producție se adaugă aici pe măsură ce apar, fiecare cu propriul criteriu explicit de bifare.)*

## Notă despre `docs/00_GOVERNANCE/DEFINITION_OF_DONE.md`

Acel document declară explicit propria regulă de schimbare: "se modifică DOAR printr-un ADR motivat" — nu a fost editat direct aici, ca să nu se încalce acea regulă în numele unei cereri de documentare ușoară. Dacă se dorește ca acest checkpoint să apară literal în checklist-ul Product DoD de acolo, e nevoie de un ADR mic, dedicat — neînceput, la cerere separată.
