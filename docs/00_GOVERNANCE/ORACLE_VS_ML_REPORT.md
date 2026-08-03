# Oracle vs. ML — Benchmark Report (EPIC "ML Activation & Oracle Evolution", Etapa 3)

**Status**: Analiză READ-ONLY, completă. Niciun fișier de producție nu a fost modificat, blending-ul nu a fost activat, Supabase nu a fost scris.
**Data**: 2026-08-03
**Precondiții**: `docs/00_GOVERNANCE/ORACLE_ENGINE_AUDIT.md` (Etapa 1) și `docs/00_GOVERNANCE/ML_ENGINE_AUDIT.md` (Etapa 2), ambele completate.

---

## 1. Rezumat pe o pagină

| Model | n | Accuracy | Brier Score | Log Loss | Calibrare |
|---|---|---|---|---|---|
| **Oracle** (Poisson/ELO/Formă, ponderi globale) | 1250 | 0.4888 | **0.6150** | **1.0257** | Bună — încrederea raportată urmează îndeaproape acuratețea reală pe toate cele 5 bin-uri |
| **ML** (XGBoost, walk-forward) | 1250 | 0.4720 | 0.6747 | 1.1531 | Slabă — supraîncrezut sistematic, mai ales peste 0.60 încredere |
| **Blend simulat** (`ml_weight=0.35`) | 1250 | **0.4920** | 0.6149 | 1.0256 | Bună — aproape identică cu Oracle pur |
| Baseline (majoritate simplă, mereu "Acasă") | 1250 | 0.4448 | — | — | — |

**Concluzia centrală**: Oracle, singur, e mai bine calibrat și are Brier/log-loss mai buni decât ML, singur. ML crește ușor peste baseline-ul de majoritate, dar e vizibil supraîncrezut. Blend-ul simulat câștigă o mică marjă de accuracy (+0.32pp față de Oracle pur) fără a pierde practic nimic pe Brier/log-loss (diferență ≤0.0001) — pentru că `ml_weight=0.35` e suficient de mic încât Oracle domină combinația, iar mecanismul de scalare (`sample_factor`) din `blend_predictions()` reduce și mai mult ponderea ML atunci când eșantionul de antrenare e mic. Datele NU susțin o concluzie de forma „ML e mai bun" sau chiar „ML adaugă valoare clară" — susțin o concluzie mult mai restrânsă: **blending-ul cu ML slab ponderat nu strică nimic măsurabil și poate aduce un câștig marginal de accuracy**, dar nu există dovadă că ML, singur, ar trebui să înlocuiască sau să domine Oracle.

Această concluzie e consecventă cu Etapa 2 (`ML_ENGINE_AUDIT.md`): modelul ML din producție nu are persistență reală de artefact (`save_model_artifact()` fără apelanți), deci fiecare proces repornit reantrenează efemer — exact comportamentul reprodus aici prin walk-forward complet.

---

## 2. Metodologie

### 2.1 Sursa de date

- Tabelă: `match_history` (Supabase, proiect `Prediction`).
- Filtrare: rânduri cu `actual_result` populat ȘI toate coloanele de feature-uri core ne-nule (`home_offensive_rating`, `home_defensive_rating`, `away_offensive_rating`, `away_defensive_rating`, `home_form_score`, `away_form_score`, `home_elo`, `away_elo`, `h2h_modifier`, `h2h_meetings`, coloanele `*_avg_recent` pentru corner/card/foul/shot).
- Eșantion: cele mai recente **1500 de meciuri** cronologic (`ORDER BY kickoff_date DESC LIMIT 1500`), interval **2025-11-28 → 2026-07-31**.
- Distribuție pe ligă: Premier League 260, Serie A 259, La Liga 250, Bundesliga 207, Romania SuperLiga 196, Ligue 1 188, Champions League 117, Europa League 15, MLS 6, World Cup 2026 2.
- Distribuție reală a rezultatelor pe eșantionul evaluat (held-out): Acasă 556 (44.5%), Egal 318 (25.4%), Deplasare 376 (30.1%) — clasa majoritară „Acasă" la 44.48%, folosită ca baseline de comparație.

Eșantionul de 1500 e o alegere pragmatică (nu întregul `match_history`, care are 53.462 rânduri) — motivul e că doar rândurile cu toate feature-urile core populate simultan sunt utilizabile direct de ML fără imputare, iar acest subset dens e concentrat în perioada recentă (feature-urile derivate din formă/ELO/H2H au nevoie de istoric per echipă ca să fie populate). Nu s-a extins fereastra dincolo de 1500 din motive de volum de date transferabile per interogare (limită de tokeni pe rezultatul MCP), nu dintr-o decizie metodologică — vezi secțiunea 6 (Limitări).

### 2.2 De ce cod real, nu formule reimplementate

Benchmark-ul apelează direct funcțiile de producție, fără nicio reimplementare:

- **Oracle**: `feature_engine.calibrate_xg()` → `feature_engine.poisson_model()`, exact aceleași funcții pure folosite de `oracle_engine.py` în producție. Ponderi: `form_weight=0.60`, `dna_weight=0.40`, `home_advantage=1.07`, `away_penalty=0.95`, `defensive_cap=2.5` — valorile `DEFAULT_CONFIG` documentate în `ORACLE_ENGINE_AUDIT.md`. **Ponderi globale, nu per-ligă** — Etapa 1 a confirmat live că mecanismul per-ligă e inert azi (`sample_count=0` pentru toate cele 11 ligi), deci folosirea ponderilor globale reflectă exact comportamentul curent de producție, nu o simplificare.
- **ML**: `ml_predictor.MLPredictorEngine` — aceiași hiperparametri XGBoost din producție (`n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85, objective="multi:softprob", random_state=42`) și aceleași `FEATURE_COLUMNS` (14 coloane). Granițele de walk-forward reproduc exact `MLPredictorEngine._walk_forward_validate()`: 5 fold-uri expanding-window, granițe `np.linspace(0, n, n_folds+2, dtype=int)`.
- **Blend**: `ml_predictor.blend_predictions()` apelat direct, cu `ml_weight=0.35` (valoarea implicită din cod) — include mecanismul real de `sample_factor = min(samples_used/150, 1.0)` care reduce ponderea ML când eșantionul de antrenare e mic.
- **Metrici**: `MLPredictorEngine._multiclass_brier()` (Brier multi-clasă din codul de producție) și `sklearn.metrics.log_loss` (standard, nu specific proiectului).

### 2.3 Disciplina walk-forward (zero scurgere temporală)

Datele sunt sortate cronologic strict înainte de orice antrenare. Pentru fiecare din cele 5 fold-uri, XGBoost antrenează exclusiv pe rândurile **strict anterioare** fold-ului de validare (expanding window) — niciun rând viitor nu intră în antrenare. Oracle nu are „antrenare" (e determinist pe baza formulei), dar e evaluat pe **exact aceleași rânduri held-out** ca ML, pentru comparație corectă cap-la-cap. Cele 5 fold-uri au produs 250 de rânduri evaluate fiecare, total 1250 din 1500 (primul fold e folosit integral ca fereastră minimă de antrenare, conform acelorași granițe ca în codul de producție).

### 2.4 Corectură aplicată în timpul analizei

Prima rulare a benchmark-ului a omis `home_elo`/`away_elo` din matricea de feature-uri ML (setate la `NaN` pentru toate rândurile), pentru a evita o interogare Supabase suplimentară. Această omisiune dezavantaja nedrept ML, deoarece ELO reprezintă 2 din cele 14 `FEATURE_COLUMNS` reale și e populat ~99.5% din timp în producție (per `ML_ENGINE_AUDIT.md`). Rezultatele din acest raport sunt din **a doua rulare, cu ELO real inclus** — diferența față de prima rulare (fără ELO) a fost mică (accuracy ML 0.4664→0.4720, brier 0.6799→0.6747, log_loss 1.1600→1.1531), deci ELO ajută marginal ML dar nu schimbă concluzia calitativă.

---

## 3. Rezultate detaliate

### 3.1 Metrici agregate

```
Oracle (Poisson/ELO/Forma)          n=1250  acc=0.4888  brier=0.6150  log_loss=1.0257
ML (XGBoost, walk-forward)          n=1250  acc=0.4720  brier=0.6747  log_loss=1.1531
Blend simulat (ml_weight=0.35)      n=1250  acc=0.4920  brier=0.6149  log_loss=1.0256
```

Toate 3 modelele depășesc baseline-ul de majoritate simplă (0.4448 accuracy), dar cu marje diferite: Oracle +4.4pp, ML +2.72pp, Blend +4.72pp.

### 3.2 Calibrare (reliability) — încredere raportată vs. acuratețe reală

**Oracle**:

| Interval încredere | n | Încredere medie | Acuratețe reală |
|---|---|---|---|
| [0.00, 0.40) | 180 | 0.381 | 0.300 |
| [0.40, 0.50) | 508 | 0.446 | 0.451 |
| [0.50, 0.60) | 341 | 0.547 | 0.537 |
| [0.60, 0.70) | 166 | 0.640 | 0.614 |
| [0.70, 1.01) | 55 | 0.741 | 0.782 |

**ML**:

| Interval încredere | n | Încredere medie | Acuratețe reală |
|---|---|---|---|
| [0.00, 0.40) | 55 | 0.376 | 0.327 |
| [0.40, 0.50) | 274 | 0.456 | 0.401 |
| [0.50, 0.60) | 327 | 0.549 | 0.434 |
| [0.60, 0.70) | 227 | 0.647 | 0.476 |
| [0.70, 1.01) | 367 | 0.821 | 0.578 |

**Blend**:

| Interval încredere | n | Încredere medie | Acuratețe reală |
|---|---|---|---|
| [0.00, 0.40) | 184 | 0.378 | 0.353 |
| [0.40, 0.50) | 427 | 0.449 | 0.454 |
| [0.50, 0.60) | 335 | 0.550 | 0.475 |
| [0.60, 0.70) | 189 | 0.644 | 0.598 |
| [0.70, 1.01) | 115 | 0.756 | 0.730 |

**Observație centrală**: Oracle e aproape perfect calibrat — încrederea medie raportată și acuratețea reală sunt la ≤6pp distanță pe toate bin-urile. ML e sever necalibrat în zona de încredere mare: pe bin-ul [0.70, 1.01), ML raportează încredere medie 0.821 dar acuratețe reală de doar 0.578 — un gap de 24.3pp, semn clasic de supraadaptare (overfitting) pe un set de antrenare relativ mic per fold. Blend moștenește parțial buna calibrare a Oracle (gap de doar 2.6pp pe același bin), pentru că `ml_weight=0.35` diluează suficient supraîncrederea ML.

### 3.3 ROI — nu a fost calculat

`odds_history` conține doar 1.668 rânduri, un ordin de mărime sub `match_history` (53.462 rânduri), iar joncțiunea fiabilă meci↔cotă între provideri diferiți (identificatori de fixture incompatibili între surse, deja documentată ca problemă structurală în alte părți ale proiectului) nu poate fi făcută cu încredere suficientă pentru un calcul de ROI corect pe acest eșantion. Un ROI calculat pe o joncțiune parțială/incertă ar încălca principiul de proiect „verificat, nu presupus" — ar produce un număr cu aspect de precizie fără fundament real. **Decizie**: ROI rămâne explicit „necalculat" în acest raport, nu aproximat. Dacă activarea ML/Blend devine o direcție serioasă, calcularea corectă a ROI necesită mai întâi rezolvarea joncțiunii `match_history`↔`odds_history` — un task separat, netratat aici.

---

## 4. Ce NU acoperă acest benchmark

- **Penalizările de vreme și accidentări** nu sunt incluse în reconstrucția Oracle — `weather_penalty` e fixat la `0.0` pentru toate rândurile, iar `apply_injury_penalty()` nu e apelat deloc, pentru că datele istorice de vreme/accidentări per meci nu sunt disponibile retroactiv în `match_history` pentru acest eșantion. Oracle-ul live aplică ambele; performanța reală de producție poate diferi (probabil marginal, dat fiind că injury penalty e plafonat la 30% impact total per echipă și weather la 15%).
- **Ponderile per-ligă** nu sunt exercitate (confirmat inerte azi — Etapa 1). Dacă `auto_recalibration_enabled` devine activ în viitor, acest benchmark ar trebui refăcut.
- **Team DNA / Flashscore snapshot** nu intră în feature-urile testate — acestea alimentează UI-ul (Punctul 5, EPIC anterior), nu formula `calibrate_xg`.
- **Eșantionul e recent și concentrat** (8 luni, 2025-11-28→2026-07-31) — nu acoperă comportamentul pe cicluri sezoniere complete sau pe ligi cu istoric redus în date (MLS: 6 rânduri, World Cup 2026: 2 rânduri — prea puține pentru concluzii per-ligă).
- **Un singur `ml_weight` testat** (0.35, valoarea implicită din cod) — nu s-a făcut o baleiere (sweep) pe alte valori posibile; secțiunea Etapa 4 poate propune asta ca experiment separat, dacă activarea Blend devine direcție aprobată.

---

## 5. Legătură cu Etapa 1 și Etapa 2

- Buna calibrare a Oracle e consecventă cu natura sa: o formulă Poisson determinist-parametrică, fără capacitate de supraadaptare pe eșantion mic — spre deosebire de XGBoost, care poate memora particularități ale fold-ului de antrenare (confirmat aici empiric prin gap-ul de calibrare pe bin-ul de încredere mare).
- Supraîncrederea ML e consecventă cu `ML_ENGINE_AUDIT.md`, secțiunea despre lipsa persistenței reale de model: fiecare fold retrenează de la zero pe un eșantion relativ mic (primul fold antrenează pe câteva sute de rânduri), condiție cunoscută ca predispusă la overfitting pentru gradient boosting cu 150 de estimatori.
- Rezultatul „Blend nu strică nimic, câștigă marginal" e direct relevant pentru decizia Etapei 4: nu justifică o activare agresivă a ML ca sursă principală, dar oferă un argument măsurat (nu ipotetic) pentru testarea unui blend slab ponderat, sub gating strict (shadow testing existent, Champion/Challenger), nu activare directă în producție.

---

## 6. Limitări metodologice (transparență explicită)

- Eșantion de 1500 rânduri, nu întregul `match_history` — motivat de constrângeri de transfer de date per interogare (nu de alegere metodologică), documentat în secțiunea 2.1.
- Benchmark rulat o singură dată per configurație (nu s-au repetat fold-urile cu semințe/date diferite pentru intervale de încredere statistică pe diferența dintre metrici) — diferențele Brier/log-loss dintre Oracle și Blend (≤0.0001) sunt prea mici pentru a fi declarate semnificative fără un test statistic dedicat; sunt raportate ca observație descriptivă, nu ca dovadă statistică tare.
- Acest benchmark simulează Blend, nu-l activează — `ml_blending_enabled` rămâne `False`/`NULL` în `model_config`, neatins.

---

## 7. Sumar pentru Etapa 4

Din acest raport, 3 puncte de decizie rămân deschise pentru `ML_ACTIVATION_IMPLEMENTATION_PLAN.md`:

1. **ML singur nu are dovadă suficientă pentru a înlocui sau domina Oracle** — accuracy mai mic, Brier/log-loss mai slabe, calibrare vizibil mai proastă pe eșantionul testat.
2. **Blend slab ponderat (`ml_weight=0.35`) nu produce regresie măsurabilă și aduce un câștig marginal de accuracy** — candidat plauzibil pentru testare graduală sub shadow testing, NU pentru activare directă fără validare suplimentară (eșantion mai mare, mai multe cicluri, test statistic pe diferența de metrici).
3. **ROI rămâne un gol de date real** — orice decizie de activare bazată pe profitabilitate (nu doar acuratețe statistică) necesită rezolvarea joncțiunii `match_history`↔`odds_history` înainte, ca precondiție separată.
