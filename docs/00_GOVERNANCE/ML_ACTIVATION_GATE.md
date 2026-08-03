# ML Activation Gate — Predictor + ML Blending

**Status**: checkpoint activ, obligatoriu. Document-only (R-ML-GATE-01) — nu schimbă cod, nu schimbă configurație, nu atinge `ml_blending_enabled`/`ml_blend_weight`.
**Creat**: 2026-07-29, ca răspuns direct la riscul semnalat explicit: "peste câteva săptămâni nimeni nu mai ține minte că blending-ul pornește automat după primul model antrenat."

**[ACTUALIZAT 2026-07-29, Critical Path oficial]** — înghețarea s-a extins: nu doar "nu se activează blending-ul", ci **niciun task nou** privind Predictor/ML/Blending/Confidence/alte optimizări nu începe până la finalizarea **M4** (primul Night Sync Flashscore complet — vezi `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md`, secțiunea "CRITICAL PATH OFICIAL" + §15), cu o singură excepție: aprobare explicită, separată, a proprietarului produsului. Condițiile din secțiunea de mai jos rămân valabile neschimbate pentru **activare**; această actualizare adaugă condiția suplimentară, mai largă, pentru simpla **începere** a oricărui task nou în zonă.

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

## Acoperirea reală a feature-urilor derivate (parte a condiției #3)

**[ADAUGAT — EPIC „Functional Completion", Punctul 4, 2026-08-03]** Golul identificat de `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md` (P5-01, 🟠 Major): acest document nu documenta explicit acoperirea reală per feature — cerință necesară pentru ca oricine evaluează condiția #3 ("test de ablație măsurat") să interpreteze corect metricile, nu doar procentul agregat de accuracy/log-loss.

**Statut — pur informativ, NU o a 5-a condiție obligatorie.** Secțiunea de mai jos nu adaugă o nouă căsuță la lista din „Condiții obligatorii" de mai sus și nu blochează nimic prin ea însăși — e context necesar pentru interpretarea corectă a condiției #3, deja existentă, atunci când un test de ablație nou va fi rulat. Cele 4 condiții obligatorii rămân exact patru, neschimbate.

**Măsurătoare din 2026-08-03 — cifrele de mai jos NU sunt înghețate.** Acoperirea (în special cea de 17,1% a coloanelor derivate) se poate schimba pe măsură ce se acumulează date noi (bootstrap SuperLiga, sync continuu, backfill de statistici) — orice reevaluare viitoare a condiției #3 trebuie să re-verifice live procentele, nu să presupună că rămân cele de aici.

`ml_predictor.FEATURE_COLUMNS` are azi 14 coloane, în două grupe cu acoperire foarte diferită. Verificat live (`Prediction`, `match_history`, 2026-08-03):

```sql
SELECT count(*) AS total,
       count(*) FILTER (WHERE home_offensive_rating IS NOT NULL) AS off_rating,
       count(*) FILTER (WHERE home_corner_avg_recent IS NOT NULL) AS corner_avg
FROM match_history;
-- total=53.769, off_rating=53.486 (99,5%), corner_avg=9.215 (17,1%)
```

| Grup | Coloane | Rânduri populate | Acoperire |
|---|---|---|---|
| **Core** (ADR original, ratinguri/formă/ELO/H2H) | `home/away_offensive_rating`, `home/away_defensive_rating`, `home/away_form_score`, `home/away_elo`, `h2h_modifier`, `h2h_meetings` (10 coloane) | 53.486 / 53.769 | **99,5%** |
| **Derivate** (promovate ulterior prin ablație dedicată) | `corner_dominance`, `card_diff` (ADR-012), `foul_diff` (ADR-013), `shot_dominance` (ADR-021/P7.1) | 9.215 / 53.769 | **17,1%** |

Toate cele 4 coloane derivate sunt calculate din aceleași 4 perechi de coloane brute (`home/away_corner_avg_recent`, `home/away_card_avg_recent`, `home/away_foul_avg_recent`, `home/away_shot_avg_recent`) — de aceea cele 4 procente de acoperire sunt identice (aceleași 9.215 rânduri gatează toate patru simultan, `ml_predictor.py:198-215`).

**Cum gestionează antrenarea lipsa acestor date — corect, nu o aproximare** (`ml_predictor.py::_fetch_training_dataframe()`, liniile 194-218): dacă rândurile brute lipsesc, coloana derivată devine `NaN` explicit (niciodată 0 sau o valoare medie presupusă) și trece nativ către XGBoost, care are propriul mecanism de split pe valori lipsă (`missing-value split`) — comportament documentat explicit în cod, nu descoperit acum. Singurul `dropna()` din pipeline e pe `actual_result` (eticheta), nu pe feature-uri.

**De ce contează pentru condiția #3**: cele 4 feature-uri derivate au fost promovate prin teste de ablație reale (`docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`, `FOULS_DOMINANCE_ABLATION_2026-07-14.md`, `SHOT_DOMINANCE_ABLATION_2026-07-15.md`) — câștigul măsurat acolo a fost obținut pe eșantionul disponibil la acel moment, nu pe întreg `match_history`. Orice evaluare viitoare a activării blending-ului trebuie să țină cont explicit că, azi, ~83% din rândurile de antrenare nu au deloc semnal de la aceste 4 coloane (XGBoost le tratează ca "lipsă", nu ca "zero" sau "neutru") — un test de ablație nou, măsurat pe volumul curent, ar trebui raportat separat pe cele două grupe de acoperire, nu doar ca o singură cifră agregată de accuracy.

**Limitare suplimentară a setului de antrenare** (context, nu blocaj): `MIN_SAMPLES_TO_TRAIN = 30` (`ml_predictor.py:36`) — prag ușor depășit de volumul actual (53.769 rânduri totale, 53.482 cu `actual_result` populat), deci antrenarea zilnică rulează fără probleme; limitarea de mai sus e despre **calitatea semnalului per feature**, nu despre volumul brut de rânduri antrenabile.

## Starea curentă, până la bifarea completă

- **Predictorul** (Poisson/ELO/formă) rămâne sistemul principal de decizie — neschimbat, activ, servește predicții azi.
- **ML continuă să se antreneze zilnic** (`PipelineStep("ml_retrain")`, `continuous_learning.yml`) — complet neafectat de acest gate, per R-ARCH-REVIEW-01.
- **ML poate fi analizat și comparat** — modelele, metricile (`training_runs`, Champion/Challenger) rămân disponibile pentru observare, fără să influențeze predicția finală servită.
- **Activarea blending-ului pentru producție NU se face automat** — nici la un număr de meciuri atins, nici la o dată calendaristică, nici implicit la vreun alt task — doar prin bifarea explicită a celor 4 condiții de mai sus + schimbarea manuală a `ml_blending_enabled`.

## Things to review before Production

- [ ] **ML Activation Gate** (acest document) — toate cele 4 condiții bifate, cu dovadă (nu presupunere), înainte de a seta `ml_blending_enabled=true` în `model_config`.

*(Listă deschisă pentru extindere — alte verificări de pre-producție se adaugă aici pe măsură ce apar, fiecare cu propriul criteriu explicit de bifare.)*

## Excepție acordată explicit (2026-07-29) — începere task-uri Faza 3 înainte de M4

Proprietarul produsului a aprobat explicit, separat, excepția prevăzută la linia 6 mai sus: task-urile Faza 3 (Team DNA/Oracle Data Layer — deja complete în Faza 2 — plus integrarea în Predictor) pot **începe** înainte de finalizarea M4 (Night Sync complet, nerulat încă la data aprobării).

**Ce acoperă excepția**: doar dreptul de a ÎNCEPE lucrul în zona Predictor/ML — NU elimină nicio condiție din secțiunea „Condiții obligatorii" de mai sus pentru **activarea** propriu-zisă (`ml_blending_enabled=true`). Acelea rămân neschimbate, toate patru, nebifate.

**Implementare concretă a excepției**: experiment shadow nou, `flashscore_team_dna` (`oracle_engine.py`, flag dedicat `flashscore_shadow_logging_enabled`, implicit OPRIT) — identic ca mecanism cu `apifootball_injuries_coaches` deja existent (ADR-002): capturează Team DNA Flashscore ca `feature_metadata` alături de probabilitățile de PRODUCȚIE, nu propune (încă) o variantă alternativă de xG/blend. Zero atingere a Predictorului/blending-ului/confidence-ului servit — pur observațional, pentru acumularea datelor necesare unui test de ablație real (cerut oricum de a treia condiție de mai sus), odată ce volumul de meciuri Flashscore colectate e suficient.

## Notă despre `docs/00_GOVERNANCE/DEFINITION_OF_DONE.md`

Acel document declară explicit propria regulă de schimbare: "se modifică DOAR printr-un ADR motivat" — nu a fost editat direct aici, ca să nu se încalce acea regulă în numele unei cereri de documentare ușoară. Dacă se dorește ca acest checkpoint să apară literal în checklist-ul Product DoD de acolo, e nevoie de un ADR mic, dedicat — neînceput, la cerere separată.
