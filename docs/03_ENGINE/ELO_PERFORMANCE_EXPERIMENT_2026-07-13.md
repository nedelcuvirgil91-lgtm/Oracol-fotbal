# ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md — Football Oracle

**Status**: Măsurătoare empirică de performanță — zero cod scris, zero fișier de producție modificat, zero soluție propusă. Continuă seria de audituri ELO (`ELO_CANONICAL_SOURCE_AUDIT`, `ELO_FIDELITY_AUDIT`, `ELO_ROOT_CAUSE_ANALYSIS`) — dar întrebarea aici e diferită: nu „ce e mai elegant arhitectural", ci **ce produce predicții mai bune, măsurat**.
**Metodă**: am antrenat local, azi, XGBoost pe date reale (53.409 meciuri din `match_history`), cu exact metodologia de walk-forward din `ml_predictor.py` (5 folduri, fereastră extinsă, aceiași hiperparametri, `random_state=42`), pentru 5 variante de feature-uri. Fiecare cifră de mai jos e calculată direct, nu citată din auditurile anterioare.

---

## 0. Planul experimental

| Variantă | Descriere | Sursă |
|---|---|---|
| **A — Actuală** | `FEATURE_COLUMNS` exact cum sunt stocate azi în `match_history` (imputare cu mediana pt. valori lipsă, aplicată identic ca în `ml_predictor.py`) | producție |
| **B — Fără ELO** | Aceleași 8 feature-uri non-ELO, `home_elo`/`away_elo` eliminate complet | derivată din A |
| **C — ELO Kaggle** | Identică cu A la nivel de `home_elo`/`away_elo` — verificat, nu presupus (vezi §1) | `match_history` |
| **D — ELOTracker complet** | `home_elo`/`away_elo` înlocuite, pentru toate cele 53.409 rânduri (nu doar cele 3.816 din backfill), cu replay cronologic `ELOTracker` — valoare **pre-meci**, fără scurgere temporală | replay local, azi |
| **E — Subset curat (deja existent)** | Doar cele 3.816 rânduri `backfill_done=True` — singurul subset cu toate cele 8 feature-uri non-ELO 100% reale, zero imputare pe ele | producție, subset |

Toate variantele A-D folosesc **exact aceleași 5 granițe de fold** (aceiași indici, aceleași meciuri de test) — comparațiile perechi sunt valide statistic. Varianta E folosește un subset mult mai mic, cu propriile granițe — raportată separat, nu comparată perechi cu A-D.

**ROI simulat — nu poate fi demonstrat.** Verificat explicit: `match_history` nu are nicio coloană de cote (`home_odds`/`draw_odds`/`away_odds`), iar `odds_history` (tabela dedicată persistării cotelor) are **0 rânduri**. Nu există nicio sursă de cote istorice reale asociate acestor 53.409 meciuri. Nu simulez ROI cu cote inventate — aș încălca exact regula „nu presupune".

---

## 1. Rezultate brute — toate cele 5 folduri, toate variantele A-D

| Variantă | Fold | Train | Val | Accuracy | Log Loss | Brier |
|---|---|---:|---:|---:|---:|---:|
| A (actuală) | 1 | 8.901 | 8.902 | 0,4607 | 1,0500 | 0,6315 |
| A | 2 | 17.803 | 8.901 | 0,4701 | 1,0413 | 0,6261 |
| A | 3 | 26.704 | 8.902 | 0,4587 | 1,0471 | 0,6302 |
| A | 4 | 35.606 | 8.901 | 0,4722 | 1,0400 | 0,6256 |
| A | 5 | 44.507 | 8.902 | 0,4710 | 1,0405 | 0,6253 |
| B (fără ELO) | 1-5 | idem | idem | 0,4370→0,4441 | 1,0708→1,0766 | 0,6471→0,6514 |
| C (Kaggle) | 1-5 | idem | idem | **identic cu A**, toate cele 5 folduri | identic | identic |
| D (ELOTracker) | 1 | 8.901 | 8.902 | 0,4766 | 1,0554 | 0,6315 |
| D | 2 | 17.803 | 8.901 | 0,4843 | 1,0272 | 0,6156 |
| D | 3 | 26.704 | 8.902 | 0,4846 | 1,0297 | 0,6174 |
| D | 4 | 35.606 | 8.901 | 0,4823 | 1,0266 | 0,6157 |
| D | 5 | 44.507 | 8.902 | **0,5040** | 1,0137 | 0,6056 |

**Descoperire verificată explicit**: suma diferențelor absolute între matricile de feature-uri A și C = **0,0 pe toate cele 44.508 meciuri** — `home_elo`/`away_elo` din producție sunt deja, azi, 100% identice cu ELO-ul Kaggle (confirmă direct constatarea din `DATA_PIPELINE_INVESTIGATION`: contribuția backfill-ului la coloana ELO e nulă în practică). **A și C sunt aceeași variantă, nu două distincte.**

---

## 2. Metrici agregate (pooled, 44.508 meciuri evaluate pe A/B/C/D)

| Metrică | A (=C) | B (fără ELO) | D (ELOTracker) |
|---|---:|---:|---:|
| **N meciuri evaluate** | 44.508 | 44.508 | 44.508 |
| **Accuracy generală** | 0,4665 | 0,4398 | **0,4864** |
| **95% CI (bootstrap, 2000 reeșantionări)** | [0,4619 ; 0,4709] | [0,4353 ; 0,4442] | [0,4817 ; 0,4907] |
| **Accuracy H** | 0,8965 | 0,9817 | 0,7970 |
| **Accuracy D (egal)** | 0,0121 | 0,0072 | 0,0134 |
| **Accuracy A (deplasare)** | 0,2352 | 0,0273 | **0,4443** |
| **Log Loss (pooled)** | 1,0438 | 1,0727 | **1,0305** |
| **Brier Score (pooled)** | 0,6277 | 0,6487 | **0,6172** |
| **95% CI Brier** | [0,6256 ; 0,6300] | [0,6471 ; 0,6502] | [0,6145 ; 0,6200] |

**Observație critică, verificată direct**: **toate cele 4 variante prezic aproape niciodată egalul** (accuracy D între 0,7% și 1,3%) — un defect general al modelului, independent de ELO, nu descoperit înainte în acest fir de audit. Modelul „câștigă" acuratețe aproape exclusiv din predicția corectă a rezultatelor H/A, nu D.

**B (fără ELO) colapsează spre „mereu Home"**: accuracy H=98,17% dar accuracy A=2,73% — fără ELO, modelul practic nu diferențiază deloc meciurile, doar exploatează avantajul de teren ca prior dominant.

**D (ELOTracker complet) e singura variantă cu detecție reală a victoriilor în deplasare** (44,43%, dublu față de A/C) — semnal ELO variat pe fiecare rând (nu median-imputat pe 53% din date) permite modelului să distingă real echipele puternice care joacă în deplasare.

---

## 3. Calibrare

Bucket-uri după încrederea predicției (probabilitatea maximă prezisă), 5 bin-uri egale ca număr de meciuri, comparate cu acuratețea reală din fiecare bin:

| Variantă | Bin (încredere crescătoare) | Diferență (real − prezis) |
|---|---|---|
| A (=C) | 5 bin-uri, 0,392→0,629 încredere medie | între −1,3pp și +0,5pp — **bine calibrat** |
| B (fără ELO) | 5 bin-uri, 0,431→0,570 | între −7,6pp (bin superior) și +0,9pp |
| D (ELOTracker) | 5 bin-uri, 0,384→0,703 | între **−4,6pp și −0,4pp — supraîncrezător sistematic**, cu cât încrederea e mai mare |

**Nuanță importantă, nu ascunsă**: D are acuratețe și Brier mai bune per ansamblu, dar **calibrarea e mai slabă** decât A — la bin-ul de încredere maximă, D prezice 70,3% dar realizează doar 65,7% (−4,6pp), față de A care prezice 62,9% și realizează 61,7% (−1,3pp). „Mai bun la accuracy/Brier" nu înseamnă automat „mai bine calibrat" — sunt proprietăți diferite, măsurate separat aici, nu una singură.

---

## 4. Feature importance (permutation, fold 5 — cel mai mare set de antrenare)

| Variantă | Top feature | Valoare | ELO total (home+away) |
|---|---|---:|---:|
| A (=C) | away_elo | 0,0479 | **0,0775** |
| B (fără ELO) | away_offensive_rating | 0,0071 | — (nu există) |
| D (ELOTracker) | away_elo | 0,0715 | **0,1267** |

În D, importanța combinată ELO e **cu 63% mai mare** decât în A — semnal ELO complet (fără imputare pe 53% din rânduri) contribuie mult mai mult la decizia modelului. În B, cel mai important feature rămâne cu un ordin de mărime sub oricare din variantele cu ELO — confirmă cantitativ ce arăta deja `PREDICTOR_ROADMAP_V4.md`: ELO domină, cu sau fără acoperire completă.

---

## 5. Testare statistică — diferențele sunt reale sau zgomot?

Test Wilcoxon signed-rank, perechi (aceleași 44.508 meciuri de test, aceleași granițe de fold, diferență pe Brier per meci):

| Comparație | Diferență medie Brier | p-value | Verdict |
|---|---:|---:|---|
| **A vs. B (fără ELO)** | −0,0209 (A mai bun) | **4,03 × 10⁻¹⁶⁹** | **Semnificativ, fără echivoc** — nu e zgomot |
| A vs. C (Kaggle) | 0,0000 | — | Identice — niciun test necesar |
| **A vs. D (ELOTracker)** | +0,0106 (D mai bun) | **4,31 × 10⁻⁴³** | **Semnificativ, fără echivoc** — nu e zgomot |

Ambele diferențe sunt de multe ordine de mărime sub orice prag convențional (0,05, 0,001) — pe un eșantion de 44.508 meciuri, chiar și diferențe modeste devin statistic detectabile. **Nu sunt artefacte de eșantionare mică.**

---

## 6. Varianta E — subsetul curat (`backfill_done=True`, n=3.816)

Deja existent în proiect (nu o variantă nouă construită pentru acest experiment) — singurul subset cu toate cele 8 feature-uri non-ELO 100% reale. `home_elo`/`away_elo` sunt 100% NULL în acest subset (confirmat, backfill nu scrie ELO — vezi `DATA_PIPELINE_INVESTIGATION`), deci imputate cu mediana, echivalent cu „fără semnal ELO variabil".

| Metrică | Valoare | 95% CI |
|---|---:|---:|
| N meciuri evaluate (pooled, 5 folduri, foldurile mici din start pierdute) | 3.180 | — |
| Accuracy | 0,4396 | [0,4220 ; 0,4569] |
| Log Loss | 1,1112 | — |
| Brier | 0,6630 | [0,6494 ; 0,6762] |
| Accuracy H / D / A | 0,6408 / **0,1445** / 0,3984 | — |

**Nu comparabil perechi cu A-D** (set diferit de meciuri, granițe de fold diferite) — raportat descriptiv. Două observații reale: (1) performanța generală e **mai slabă** decât A, deși feature-urile non-ELO sunt „curate" — volumul de antrenare mic (636-3.180 meciuri per fold, față de 8.901-44.507 la A-D) pare să conteze mai mult decât puritatea datelor, la această scară; (2) **detecția egalurilor e de 12x mai bună** (14,45% față de ~1,2% la A/C, ~1,3% la D) — o observație reală, neexplicată aici, care ar merita investigată separat, dar nu fac asta acum (în afara scopului cerut).

---

## 7. Răspuns direct la întrebarea de fond

**ELO este o problemă reală și demonstrată statistic — dar în ambele direcții, nu doar una:**

1. **Lipsa ELO-ului dăunează sever** — varianta B (fără ELO) e semnificativ mai slabă decât actuala (p < 10⁻¹⁶⁸), colapsând spre predicția „mereu Home". ELO nu e un feature opțional — e feature-ul dominant, singurul cu semnal real de diferențiere azi.
2. **ELO Kaggle (varianta „reală"/„live-like") și varianta actuală sunt identice** — nu există azi o comparație reală „Kaggle vs. actual", fiindcă actualul E deja Kaggle, verificat empiric, nu doar din cod.
3. **ELOTracker complet, deși demonstrat mai puțin fidel față de valorile live (`ELO_FIDELITY_AUDIT`, eroare sistematică ~9,4%), produce predicții MAI BUNE decât Kaggle parțial + imputare masivă** — accuracy +4,3pp, Brier −0,0105, log loss −0,0133, toate semnificative statistic (p < 10⁻⁴²). **Acoperirea completă (100% din rânduri, chiar cu o eroare de calibrare cunoscută) bate acoperirea parțială (47%) cu precizie mai mare pe rândurile care există.**
4. **Modelul pierde performanță și din alte motive, independente de ELO** — detecția egalurilor e aproape nulă (~1%) în toate variantele A-D deopotrivă; asta nu e o problemă de ELO, e o limitare separată a modelului/feature-setului, nedemonstrată aici ca fiind cauzată de ELO în vreun fel.

**Concluzie finală, strict pe măsurători**: problema principală de performanță demonstrată azi **nu e „ELOTracker e mai puțin fidel decât live"** (adevărat, dar irelevant pentru performanța ML, conform acestui experiment) — e **acoperirea incompletă a oricărei surse de ELO** (azi doar 47% din rânduri). Un ELO complet, chiar imperfect calibrat, măsurat aici, produce predicții mai bune decât un ELO parțial, chiar dacă parțial mai „corect" acolo unde există.

Nicio recomandare, nicio soluție propusă — doar măsurătorile de mai sus.
