# Etapa 3 — Re-rulare după ADR-049 (Pasul 11, EPIC "ML Activation & Oracle Evolution")

**Status**: Analiză READ-ONLY, completă. Niciun fișier de producție nu a fost modificat, niciun flag de producție activat, Supabase nu a fost scris.
**Data**: 2026-08-04
**Precondiție**: ADR-049 complet implementat (Pasul 10a @ `cd5d45e`, Pasul 10b @ `82ac2ff`).
**Tooling**: `scripts/rerun_etapa3_benchmark.py` (committed, reutilizabil — `python scripts/rerun_etapa3_benchmark.py`).
**Plan**: `docs/00_GOVERNANCE/PASUL11_IMPLEMENTATION_PLAN.md` (APPROVED, 2026-08-04).

**⚠️ Acesta NU este un benchmark de reproducere a Etapei 3, ci un benchmark de REVALIDARE.** Fereastra de date diferă de Etapa 3 (vezi §2) — nu se pretinde identitate numerică cu `ORACLE_VS_ML_REPORT.md`, ci se confirmă (sau infirmă) aceeași concluzie calitativă, pe date curente. `ORACLE_VS_ML_REPORT.md` rămâne complet neatins — document istoric, imuabil.

---

## 1. Rezumat pe o pagină

| Model | n | Accuracy | Brier Score | Log Loss | ECE |
|---|---|---|---|---|---|
| **Oracle** (Poisson/ELO/Formă, ponderi globale) | 1250 | 0.5016 | 0.6070 | 1.0146 | 0.0176 |
| **ML necalibrat** (XGBoost, walk-forward) | 1250 | 0.4656 | 0.6696 | 1.1552 | 0.1576 |
| **ML calibrat** (Temperature Scaling, T=2.638) | 1250 | 0.4656 | 0.6246 | 1.0403 | 0.0265 |
| **Blend cu ML calibrat** (`ml_weight=0.35`) | 1250 | **0.5104** | **0.6058** | **1.0130** | — |
| Blend cu ML necalibrat (stil Etapa 3) | 1250 | 0.5040 | 0.6090 | 1.0191 | — |

**Concluzia centrală**: Calibrarea (ADR-049) își atinge exact obiectivul declarat — corectează sever supraîncrederea sistematică a ML fără să schimbe accuracy (invariant `argmax`, confirmat empiric, nu doar teoretic) și fără cost de runtime măsurabil (+1.81%, măsurat exclusiv pentru apelul `predict()` al ML, nu pentru întreg pipeline-ul Oracle — vezi §3.3). Gap-ul de calibrare pe bin-ul de încredere mare `[0.70, 1.01)` scade de la **22.0pp la 1.1pp** — o reducere de peste 95%, depășind cu mult ținta de ≤12pp fixată în Implementation Plan. Toate cele 5 criterii de succes pe comparația primară (§4 din plan) **TREC**. Pe context (comparația secundară, **pe benchmark-ul curent** — vezi nota de mai jos): Oracle rămâne mai bun decât ML calibrat singur pe toate cele 3 metrici — consecvent cu Etapa 3, Oracle rămâne motorul principal — dar Blend-ul cu ML calibrat depășește acum Oracle pur pe toate cele 3 metrici simultan (nu doar accuracy, cum se observase pe eșantionul din Etapa 3).

**[PRECIZARE — review]** Toate afirmațiile despre Blend din acest document (aici și în §3.2/§5) sunt valabile **exclusiv pe benchmark-ul curent** (§2.1) — Etapa 3 și Pasul 11 folosesc ferestre temporale diferite, deci nu constituie o comparație directă, cap-la-cap, între „Blend din Etapa 3" și „Blend din Pasul 11" pe același eșantion. Concluzia corectă e strict: pe eșantionul curent, Blend cu ML calibrat depășește atât Oracle cât și Blend cu ML necalibrat — nu „Blend-ul calibrat e mai bun decât Blend-ul din Etapa 3".

---

## 2. Metodologie

### 2.1 Diferențe explicite față de Etapa 3 (transparență obligatorie)

- **Fereastră de date**: Etapa 3 a folosit 2025-11-28 → 2026-07-31 (1500 rânduri). Această re-rulare folosește **2025-08-23 → 2026-08-03** (1500 rânduri, cele mai recente disponibile la data execuției) — fereastră mai largă și mai recentă, fiindcă între timp au fost sincronizate mai multe date istorice în `match_history`. Aceasta e motivul explicit pentru care numerele Oracle diferă de Etapa 3 (0.5016 vs. 0.4888 accuracy). **Oracle a fost recalculat exclusiv pentru consistența experimentală a tabelului din acest raport (§2.2) — algoritmul Oracle (`feature_engine.calibrate_xg()`/`poisson_model()`, ponderile globale) nu s-a modificat între Etapa 3 și Pasul 11; diferența de numere vine STRICT din eșantionul de evaluare diferit, nu din vreo schimbare de cod.**
- **Sursa de date**: aceeași interogare/filtrare ca Etapa 3 §2.1 (toate coloanele core ne-nule), cu adăugarea unui tiebreaker (`fixture_id`) pentru determinism — Etapa 3 nu specifica un tiebreaker, ceea ce ar fi putut produce o ordonare nedeterministă la limita celor 1500 rânduri.
- **Cod real, nu reimplementat**: identic Etapa 3 §2.2 — `feature_engine.calibrate_xg()`/`poisson_model()` pentru Oracle, `ml_predictor.MLPredictorEngine`/hiperparametri identici pentru ML, `ml_predictor._multiclass_brier()`/`sklearn.metrics.log_loss` pentru metrici. Suplimentar față de Etapa 3: `ml_predictor._fit_temperature()`/`_softmax_with_temperature()` (Pasul 10a) pentru calea calibrată.
- **Disciplina walk-forward**: identică Etapa 3 §2.3 — 5 fold-uri expanding-window, aceleași granițe (`np.linspace`), 1250 din 1500 rânduri evaluate (primul fold folosit doar la antrenare).

### 2.2 Comparație primară vs. secundară

- **Primară (controlată)**: ML necalibrat vs. ML calibrat, din **exact aceleași margini brute ale aceleiași rulări** de antrenare walk-forward — zero confound din date diferite sau reantrenare separată. Aceasta e comparația care răspunde direct la întrebarea Pasului 11.
- **Secundară (contextuală)**: Oracle, ML calibrat, Blend (cu ML calibrat și, pentru comparație, cu ML necalibrat stil Etapa 3) — toate recalculate pe **același eșantion nou** (inclusiv Oracle, deși codul lui e neschimbat — recalcularea garantează că tot tabelul provine din același experiment, cerință explicită de la review).

---

## 3. Rezultate detaliate

### 3.1 Comparație primară — ML necalibrat vs. ML calibrat (n=1250, aceleași fold-uri)

```
ML necalibrat    acc=0.4656  brier=0.6696  log_loss=1.1552  ECE=0.1576
ML calibrat      acc=0.4656  brier=0.6246  log_loss=1.0403  ECE=0.0265
Temperatura fitată (OOF, gardă baseline aplicată): T = 2.6377
```

**Reliability — ML necalibrat**:

| Interval încredere | n | Încredere medie | Acuratețe reală | Gap |
|---|---|---|---|---|
| [0.00, 0.40) | 56 | 0.372 | 0.232 | 14.0pp |
| [0.40, 0.50) | 309 | 0.454 | 0.353 | 10.1pp |
| [0.50, 0.60) | 282 | 0.550 | 0.418 | 13.2pp |
| [0.60, 0.70) | 214 | 0.650 | 0.486 | 16.4pp |
| [0.70, 1.01) | 389 | 0.832 | 0.612 | **22.0pp** |

**Reliability — ML calibrat**:

| Interval încredere | n | Încredere medie | Acuratețe reală | Gap |
|---|---|---|---|---|
| [0.00, 0.40) | 373 | 0.376 | 0.343 | 3.3pp |
| [0.40, 0.50) | 571 | 0.444 | 0.466 | 2.2pp |
| [0.50, 0.60) | 196 | 0.542 | 0.577 | 3.5pp |
| [0.60, 0.70) | 79 | 0.644 | 0.658 | 1.4pp |
| [0.70, 1.01) | 31 | 0.753 | 0.742 | **1.1pp** |

Notă: distribuția `n` per bin se schimbă masiv între necalibrat/calibrat (389→31 în bin-ul de sus) — comportament AȘTEPTAT, nu o anomalie: `T=2.638` reduce sistematic încrederea raportată, deci multe predicții anterior "peste 0.70" coboară sub acel prag după calibrare. Modelul nu devine mai puțin sigur pe rezultatul prezis (`argmax` neschimbat) — devine mai onest despre cât de sigur ar trebui să fie.

### 3.2 Comparație secundară — context (Oracle, ML calibrat, Blend)

```
Oracle (recalculat, aceeași fereastră)     acc=0.5016  brier=0.6070  log_loss=1.0146  ECE=0.0176
ML calibrat                                acc=0.4656  brier=0.6246  log_loss=1.0403
Blend cu ML calibrat (ml_weight=0.35)      acc=0.5104  brier=0.6058  log_loss=1.0130
Blend cu ML necalibrat (stil Etapa 3)      acc=0.5040  brier=0.6090  log_loss=1.0191
```

Oracle rămâne mai bun decât ML calibrat singur pe toate cele 3 metrici — consecvent cu Etapa 3 și cu viziunea permanentă a proiectului (Oracle rămâne motorul principal). **Pe benchmark-ul curent** (nu ca o comparație directă cu eșantionul din Etapa 3 — vezi precizarea din §1): Blend-ul cu ML calibrat depășește Oracle pur pe **toate cele 3 metrici simultan** (accuracy +0.88pp, brier -0.0012, log_loss -0.0016). Calibrarea propagată prin blend produce, tot pe acest eșantion, un câștig mic dar consistent față de blend-ul cu ML necalibrat (acc +0.64pp, brier -0.0032, log_loss -0.0061).

### 3.3 ECE și timp de inferență (metrici noi față de Etapa 3)

ECE (Expected Calibration Error, medie ponderată a gap-ului pe cele 5 bin-uri — **cu cât mai aproape de 0, cu atât calibrarea e mai bună**; 0 ar însemna încredere raportată identică cu acuratețea reală pe fiecare bin): ML necalibrat 0.1576, ML calibrat 0.0265 (o reducere de 83%), Oracle 0.0176 (rămâne cel mai bine calibrat, dar ML calibrat se apropie considerabil).

Timp de inferență (`predict()`, mediat pe 200 apeluri repetate): necalibrat 1.553ms, calibrat 1.581ms — **overhead +1.81%**, neglijabil (adaugă un singur `predict(output_margin=True)` + o funcție softmax pe 3 numere). **Precizare**: măsurătoarea acoperă exclusiv apelul `MLPredictorEngine.predict()` — NU întreg pipeline-ul de servire (Oracle/Poisson + blend + orice alt pas din `oracle_engine.py`), care are propriul cost, nemăsurat aici.

---

## 4. Verdict pe criteriile de succes (Implementation Plan §4)

Pe comparația PRIMARĂ:

| Criteriu | Prag | Rezultat | Verdict |
|---|---|---|---|
| Accuracy identică | exact egal | 0.4656 == 0.4656 | **PASS** |
| Log-loss nu se degradează | calibrat ≤ necalibrat + 0.005 | 1.0403 ≤ 1.1552+0.005 | **PASS** (îmbunătățire -0.1149) |
| Brier se îmbunătățește/stabil | calibrat ≤ necalibrat + 0.005 | 0.6246 ≤ 0.6696+0.005 | **PASS** (îmbunătățire -0.0450) |
| Gap calibrare `[0.70,1.01)` scade la ≤12pp | ≤12pp | 22.0pp → 1.1pp | **PASS** (cu marjă largă) |
| Overhead runtime <10% | <10% | 1.81% | **PASS** |

**Toate cele 5 criterii TREC.** Concluzia Pasului 11: calibrarea introdusă de ADR-049 își demonstrează empiric beneficiul declarat, pe date curente, fără regresii pe niciun criteriu prestabilit.

Pe comparațiile SECUNDARE (context, fără prag): Oracle rămâne superior lui ML calibrat singur (neschimbat față de Etapa 3); pe benchmark-ul curent, Blend cu ML calibrat depășește Oracle pur pe toate cele 3 metrici simultan — nu o comparație directă de magnitudine cu Etapa 3 (eșantion diferit, vezi §1).

---

## 5. Legătură cu Etapa 3/4

- **Punctul 1 din Etapa 3 §7** ("ML singur nu are dovadă suficientă pentru a înlocui sau domina Oracle") **rămâne valabil** — ML calibrat, deși mult mai bine calibrat, tot nu depășește Oracle pe accuracy/brier/log-loss, singur.
- **Punctul 2 din Etapa 3 §7** ("Blend slab ponderat nu produce regresie măsurabilă și aduce un câștig marginal") **rămâne consecvent, întărit pe benchmark-ul curent**: cu ML calibrat, blend-ul nu mai e doar "nu strică nimic" — pe acest eșantion, depășește Oracle pur pe toate cele 3 metrici simultan (nu o comparație directă cu magnitudinea câștigului din Etapa 3, care a folosit alt eșantion — vezi §1). Rămâne totuși un candidat pentru testare graduală sub shadow testing (Pasul 12/13), nu o dovadă suficientă pentru activare directă — un singur benchmark, fără interval de încredere statistic pe diferență, nu constituie validare completă (aceeași limitare metodologică ca Etapa 3 §6).
- **Punctul 3 din Etapa 3 §7** (ROI, gol de date) **rămâne neschimbat** — nu a fost în scope-ul Pasului 11.

## 6. Limitări metodologice (transparență explicită, consecvent cu Etapa 3 §6)

- Fereastră de date diferită de Etapa 3 (§2.1) — comparațiile absolute cu numerele publicate în `ORACLE_VS_ML_REPORT.md` trebuie citite cu această rezervă; comparația PRIMARĂ (ML necalibrat vs. calibrat) nu e afectată, fiind internă aceleiași rulări.
- Benchmark rulat o singură dată (aceeași limitare ca Etapa 3 §6) — diferențele mici (ex. Blend vs. Oracle pe Brier/log-loss) sunt raportate descriptiv, nu ca dovadă statistică tare.
- Acest benchmark simulează Blend, nu-l activează — `ml_blending_enabled` rămâne `False`/`NULL` în `model_config`, neatins.
- Temperatura folosită (T=2.638) e specifică acestei rulări (acest set de fold-uri/date) — nu identică neapărat cu temperatura pe care ar produce-o o antrenare de producție reală pe alt set de date; asta e comportament AȘTEPTAT (calibrarea e specifică fiecărui `training_run_id`, ADR-049 §7), nu o eroare.

---

## 7. Reproductibilitate

```bash
python scripts/rerun_etapa3_benchmark.py
```

Necesită `SUPABASE_URL`/`SUPABASE_SECRET_KEY` (citire read-only din `match_history`). Pentru validare offline/fără acces live: `--dataset-json <cale>` (format: listă JSON de rânduri cu coloanele din `RAW_COLUMNS`).
