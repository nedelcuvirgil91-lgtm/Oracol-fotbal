# P3 Revalidation — ELO Margin of Victory (MOV), post-P3.5

**Status**: Raport final, măsurat pe producție (date consolidate). Zero implementare, zero promovare — răspunde strict la întrebarea Chief Architect: *„Consolidarea identității echipelor (P3.5 Faza 3) schimbă suficient fidelitatea ELO încât MOV să devină acum un experiment Accepted?"*

**Metodologie**: identică cu P3/P3.1 original (`scripts/_p3_elo_mov_replay_temp.py`, commit `5fea9b9`, recuperat integral din git history), extinsă strict aditiv (5 variante unificate într-o singură trecere, tabel complet per-echipă, ECE, feature importance) — vezi `scripts/_p3_revalidation_replay_temp.py`. Nicio constantă, formulă sau împărțire walk-forward modificată. Rulare: GitHub Actions, workflow temporar (`_p3_revalidation_temp.yml`, înregistrat pe `main` prin excepție aprobată explicit — commit creare `2e2a6ee`, commit ștergere `7f489b7`), run `#29429218631`, 2026-07-15, succes, **79,6s total**. 100% read-only față de Supabase.

**Date de intrare**: `match_history`, 53.409 meciuri cu rezultat real — aceleași ca în P3/P3.1 original (numărul total de meciuri nu s-a schimbat prin P3.5, doar identitatea echipelor — vezi `P3_5_FAZA3_POST_MIGRATION_REPORT_2026-07-15.md`).

**Notă de onestitate metodologică, obligatorie înainte de cifre**: `FEATURE_COLUMNS` conține azi 14 coloane (a 14-a, `shot_dominance`, promovată prin P7.1/ADR-021, DUPĂ închiderea P3/P3.1) față de cele 11 din experimentul original. Această diferență afectează comparabilitatea **absolută** a cifrelor de predictor cu benchmark-ul oficial ADR-020 și cu Replay A din rundele originale — dar **nu afectează comparabilitatea relativă Replay A vs. variantele B din această rulare** (toate 6 configurații din acest run folosesc aceleași 14 coloane, doar `home_elo`/`away_elo` diferă între ele). Semnalat explicit, nu ascuns.

---

## 1. Replay complet pe baza consolidată

6 replay-uri complete (Replay A control + 5 variante MOV), rulate într-o singură trecere unificată (nu 2 runde separate ca originalul — același Replay A pentru toate 5, comparabilitate mai bună):

| Variantă | c | d | Origine |
|---|---:|---:|---|
| V1_baseline | 2,2 | 0,001 | P3 runda 1 (document P3.0) |
| V2_damped | 4,4 | 0,0005 | P3 runda 1 |
| V3_amplified | 1,1 | 0,002 | P3 runda 1 |
| V4_more_amplified | 0,8 | 0,0025 | P3.1 (recuperat din log-uri GitHub Actions — nu era comis nicăieri) |
| V5_mild_amplified | 1,5 | 0,0015 | P3.1 (idem) |

Replay complet: 53.409 meciuri, 6 configurații, **29,7s**. Walk-forward predictor (5 folduri × 6 configurații = 30 antrenări XGBoost): restul timpului (~50s).

---

## 2. Comparație directă — P3 original vs. P3.1 vs. P3 după P3.5

### 2.1 Fidelitate ELO (mean_abs_pct_diff vs. `ELO_RATINGS_FALLBACK`, 16 echipe)

| | Replay A | V1 | V2 | V3 | V4 | V5 |
|---|---:|---:|---:|---:|---:|---:|
| **P3 runda 1** (fragmentat) | 11,23% | 10,99% | 10,35% | 13,13% | — | — |
| **P3.1** (fragmentat, aceleași date) | 11,23% | — | — | 13,13% | 14,0% | 11,9% |
| **P3 după P3.5** (consolidat) | **6,84%** | **6,65%** | **6,10%** | 9,68% | 20,84% | 7,83% |

**Reducere Replay A: 11,23% → 6,84% (−39% relativ)** — cea mai mare îmbunătățire de fidelitate ELO măsurată în tot proiectul, exact efectul pe care consolidarea identității echipelor era proiectată să-l producă (P3.5, motivul original al deschiderii).

### 2.2 Spearman rank correlation vs. referință

| | Replay A | V1 | V2 | V3 | V4 | V5 |
|---|---:|---:|---:|---:|---:|---:|
| **P3 runda 1** | 0,755 | 0,7373 | 0,7226 | 0,7815 | — | — |
| **P3.1** | 0,755 | — | — | 0,7815 | 0,7373 | 0,752 |
| **P3 după P3.5** | **0,6608** | **0,6902** | **0,7005** | 0,6681 | 0,5754 | 0,6873 |

**Descoperire contraintuitivă, raportată onest, nu ascunsă**: Spearman al Replay A ÎNSUȘI a scăzut (0,755→0,6608) — consolidarea a redus eroarea absolută (§2.1) dar nu a păstrat automat ordinea de clasament față de cele 16 echipe din referință. Cauza plauzibilă (neconfirmată exhaustiv): corecția nu e uniformă — unele echipe (ex. Bayern Munich, eroare 8,17%→0,29%) se apropie aproape perfect de referință, altele (Tottenham, Chelsea) rămân cu erori de 13-14%, schimbând ordinea relativă. Nu blochează verdictul de mai jos — afectează IDENTIC toate cele 6 configurații din această rulare, deci comparația relativă A-vs-variante rămâne validă.

### 2.3 Predictor — Accuracy (walk-forward, 5 folduri)

| | Replay A | V1 | V2 | V3 | V4 | V5 |
|---|---:|---:|---:|---:|---:|---:|
| **P3 runda 1** | 0,4842 | 0,4864 (+0,22pp) | 0,4852 (+0,10pp) | 0,4862 (+0,20pp) | — | — |
| **P3.1** | 0,4842 | — | — | 0,4862 (+0,20pp) | 0,4832 (−0,10pp) | 0,4871 (+0,29pp) |
| **P3 după P3.5** | **0,4967** | 0,4985 (+0,18pp) | 0,4992 (**+0,25pp**) | 0,4989 (+0,22pp) | 0,4966 (−0,01pp) | 0,4990 (+0,23pp) |

Niciun candidat, în nicio rundă (inclusiv aceasta), nu atinge pragul strict de +0,30pp. Cel mai apropiat de-a lungul întregului proiect rămâne V5 din P3.1 (+0,29pp, pe date fragmentate) — pe date consolidate, cel mai bun e V2 (+0,25pp).

### 2.4 Semnale finale de decizie (criteriul compus, calculat automat, neschimbat)

| Variantă | P3 runda 1 | P3.1 | P3 după P3.5 |
|---|---|---|---|
| V1 | POZITIV (eroare↓) | — | **POZITIV (eroare↓ ȘI rang↑ — ambele simultan)** |
| V2 | POZITIV (eroare↓) | — | **POZITIV (eroare↓ ȘI rang↑ — ambele simultan)** |
| V3 | POZITIV (rang↑) | POZITIV (rang↑) | POZITIV (rang↑ marginal) |
| V4 | — | NEGATIV | NEGATIV (confirmat, mai grav — vezi §3) |
| V5 | — | NEGATIV | POZITIV (rang↑) |

**Schimbarea calitativă centrală**: în P3 original (ambele runde), FIECARE variantă avea un compromis intern între eroare și rang (una îmbunătățea o axă, o înrăutățea pe cealaltă) — exact motivul verdictului Inconclusive („niciun candidat nu câștigă clar pe ambele axe de fidelitate simultan", roadmap). **Pe date consolidate, V1 și V2 îmbunătățesc SIMULTAN ambele axe** — eroare absolută ȘI rang de clasament — pentru prima dată în tot istoricul P3. Acesta e exact mecanismul pe care P3.5 fusese proiectat să-l activeze.

---

## 3. Stabilitate sezon-cu-sezon

| | Replay A | V1 | V2 | V3 | V4 | V5 |
|---|---:|---:|---:|---:|---:|---:|
| **yoy_std, P3.1 (fragmentat)** | 65,96 | — | — | 61,65 | 105,87 | 63,39 |
| **yoy_std, după P3.5** | 70,54 | 69,19 | 70,63 | 65,3 | **135,62** | 67,31 |

V4 arăta deja instabilitate dublă în P3.1 (105,87 vs. 65,96 control) — pe date consolidate, instabilitatea **se agravează** (135,62) și produce o **explozie numerică reală**: `Inter Milan` ajunge la rating **4040** (referință 1898, +112,85%), `Manchester City` la 2582,8 (+32,45%), `Liverpool` la 2474,2 (+28,07%) — valori absurde, absente la toate celelalte 5 configurații (care rămân în intervalul 1500-2000, plauzibil). Cauza plauzibilă: constantele V4 (c=0,8 — cel mai mic; d=0,0025 — cel mai mare) fac multiplicatorul `c/(d·elo_diff+c)` sensibil la valori mari negative de `elo_diff` (surprize mari) — iar consolidarea, prin corectarea istoricului, produce acum diferențe ELO reale mai mari (mai puțin comprimate de fragmentare) decât înainte, expunând o instabilitate a formulei care era deja vizibilă, dar mai blândă, pe datele fragmentate. **Nu e o eroare de implementare a acestei rulări** (formula e identică, necopiată greșit) — e o proprietate reală a constantelor V4, agravată de date mai fidele. Confirmă, nu schimbă, verdictul deja stabilit pentru V4 (regresie clară).

---

## 4. Distribuția MOV (rating final, B-vs-A)

| Variantă | n echipe comune | Medie diff | Std diff | Crescute / Scăzute / Neschimbate |
|---|---:|---:|---:|---|
| V1 | 939 | −0,01 | 13,39 | 473 / 459 / 7 |
| V2 | 939 | −0,04 | 15,05 | 457 / 475 / 7 |
| V3 | 939 | 0,10 | 23,11 | 489 / 443 / 7 |
| V4 | 939 | 0,13 | **198,60** | 499 / 433 / 7 |
| V5 | 939 | 0,03 | 15,26 | 465 / 467 / 7 |

V1/V2/V5 arată distribuții simetrice, std moderat (13-15) — MOV diferențiază echipele fără să le deplaseze sistematic într-o singură direcție (semn bun: nu e un bias, e o redistribuire pe formă reală). V4: std=198,6, de 13× mai mare decât V1 — dominat de outlier-ii din §3, nu de un efect distribuit.

---

## 5. Calibrare (Expected Calibration Error, 10 bin-uri, 44.508 predicții pooled)

Funcție identică cu P2 (`scripts/_calibration_study_p2_temp.py`), pentru comparabilitate directă cu „baseline ECE=0,0161" deja raportat.

| Configurație | ECE | Δ vs. Replay A |
|---|---:|---|
| Replay A (control) | 0,0168 | — |
| V1_baseline | 0,0182 | −0,0014 (mai slab) |
| V2_damped | 0,0168 | ±0,0000 (egal) |
| V3_amplified | 0,0137 | +0,0031 (mai bun) |
| V4_more_amplified | 0,0118 | +0,0050 (mai bun) |
| V5_mild_amplified | 0,0157 | +0,0011 (mai bun) |

Nicio variantă nu produce o supraîncredere sistematică nouă — toate rămân în vecinătatea ECE 0,012-0,018, comparabil cu baseline-ul P2 (0,0161). V4 are cel mai bun ECE dintre toate, dar e irelevant dat fiind instabilitatea de rating de la §3 (un ECE bun calculat pe un model antrenat cu feature-uri corupte de outlieri nu susține promovarea). ECE nu diferențiază decisiv între V1/V2/V3/V5 — informativ, nu decisiv pentru verdict.

---

## 6. Feature importance (XGBoost, mediat pe 5 folduri, top 3 din 14)

| Configurație | #1 | #2 | #3 |
|---|---|---|---|
| Replay A | away_elo (0,1667) | home_elo (0,1665) | h2h_modifier (0,0838) |
| V1 | away_elo (0,1768) | home_elo (0,1706) | h2h_modifier (0,0816) |
| V2 | away_elo (0,1728) | home_elo (0,1722) | h2h_modifier (0,0824) |
| V3 | away_elo (0,1783) | home_elo (0,1653) | h2h_modifier (0,0842) |
| V4 | away_elo (0,1646) | home_elo (0,1610) | h2h_modifier (0,0941) |
| V5 | away_elo (0,1765) | home_elo (0,1700) | h2h_modifier (0,0813) |

`home_elo`/`away_elo` rămân dominante (~33% din importanța totală combinată) la toate configurațiile, consistent cu precedentul deja documentat (ELO domină de 15-20× — `PREDICTOR_ROADMAP_V4.md`). MOV nu schimbă structura de importanță a modelului — doar calitatea celor 2 feature-uri dominante.

---

## 7. Concluzie statistică

**Criteriul folosit — identic, neschimbat, din `P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md` §6:**
```
(fidelitatea ELO crește — eroare relativă vs. referință scade ȘI/SAU Spearman rank correlation crește)
                              SAU
(predictorul crește clar — Accuracy ≥+0,3pp FĂRĂ regres simultan pe Log Loss ȘI Brier)
```

**V1_baseline** și **V2_damped** îndeplinesc explicit prima ramură a criteriului (SAU-ul), **simultan pe ambele sub-condiții** (eroare scade ȘI rang crește) — pentru prima dată în tot istoricul P3/P3.1. Nu există niciun regres pe cealaltă ramură (predictor): ambele variante îmbunătățesc și Accuracy, și Log Loss, și Brier față de Replay A, deși sub pragul de +0,3pp. Criteriul de abandon („fidelitatea scade ȘI câștigul de predictor e marginal") **nu se aplică** — fidelitatea nu scade, crește clar.

**V3** și **V5** rămân în zona ambiguă deja cunoscută (o singură axă de fidelitate îmbunătățită, cealaltă înrăutățită) — consistent cu tot istoricul P3, nesolicitate de acest raport ca și candidați primari.

**V4** confirmă și agravează verdictul deja stabilit — regresie pe toate metricile plus o instabilitate numerică nouă, demonstrată (§3). Exclus explicit din orice recomandare de promovare.

### Decizie finală

## **ACCEPTED — pentru V1_baseline și V2_damped, pe axa fidelitate ELO.**

Susținere exclusiv pe cifre măsurate: consolidarea identității echipelor (P3.5) a produs exact mecanismul prezis în roadmap („dacă acel audit repară fragmentarea istoricului, V5 (sau formula A în general) poate fi re-testată, fără reinventarea metodologiei") — reducerea erorii relative cu 39% a eliminat compromisul intern eroare-vs-rang care bloca fiecare variantă anterior. **V2_damped** e candidatul recomandat (marja de îmbunătățire cea mai mare pe ambele axe de fidelitate — 6,10% vs. 6,84% eroare, 0,7005 vs. 0,6608 rang — plus cea mai apropiată Accuracy de pragul strict, +0,25pp, plus stabilitate sezon-cu-sezon practic neschimbată). **V1_baseline** rămâne alternativă mai simplă (constantele originale din document, fără tuning suplimentar), cu o marjă de îmbunătățire mai mică dar tot curată.

**Ce NU afirmă acest verdict**: nu spune că predictorul câștigă clar (ramura Accuracy a criteriului rămâne neîndeplinită la toate variantele) — spune că fidelitatea ELO, obiectivul explicit al P3, crește acum fără compromis intern, ceea ce criteriul deja stabilit tratează ca suficient pentru promovare.

---

## 8. Ce NU face acest document

- **Nu implementează nimic în producție.** `ELOTracker` de producție (`sync/backfill_features.py`) rămâne complet neatins.
- **Nu declanșează automat P7.2** sau orice alt experiment din roadmap — per instrucțiune explicită.
- **Nu alege singur între V1 și V2** ca formulă finală de implementare — recomandă V2 ca prim candidat, dar decizia de promovare + planul de implementare (similar ca disciplină cu Migration Plan-ul P3.5) rămân la Chief Architect.
- **Nu investighează cauza regresiei Spearman a Replay A** (§2.2) — semnalată explicit ca observație deschisă, nu ca blocaj al verdictului.

**Se oprește aici — așteaptă review-ul arhitectural înainte de orice implementare nouă, conform instrucțiunii explicite.**
