# ML_EVOLUTION_ROADMAP.md — Football Oracle

## Scop

Registru **viu** de experimente pentru evoluția modelului ML, deschis după închiderea studiului de ablație (ADR-020) și a auditului tehnic de performanță (2026-07-14). Nu e un document static de intenții — e actualizat după fiecare experiment, cu statusul lui real. Peste șase luni, acest fișier trebuie să răspundă singur la întrebarea „ce s-a încercat, și cu ce rezultat?", fără să fie nevoie de arheologie în conversații vechi.

Fiecare experiment se raportează la **benchmark-ul oficial** (ADR-020, walk-forward, 53.409 meciuri, fără leakage cunoscut):

```
Accuracy   : 0.4868
Log Loss   : 1.0253
Brier Score: 0.6145
```

Orice modificare de `FEATURE_COLUMNS`, hiperparametri sau algoritm rămâne guvernată de disciplina deja stabilită în `CLAUDE.md` — walk-forward obligatoriu, `random_state` fixat, dovadă de ablație/experiment pe date reale, niciodată intuiție. Un experiment care ajunge la `Accepted` produce commit-ul de cod corespunzător (și, dacă schimbă un contract, un ADR nou) separat de acest document — acest fișier urmărește STATUSUL experimentului, nu înlocuiește disciplina de implementare.

## Legendă status

- **Idea** — capturată, fără ipoteză testabilă formulată încă, neprogramată.
- **Planned** — ipoteză formulată, criterii de succes/abandon definite, neînceput.
- **Running** — experiment activ (workflow temporar rulat sau în curs).
- **Accepted** — criteriul de succes îndeplinit, schimbarea a fost/urmează să fie integrată permanent.
- **Rejected** — criteriul de abandon îndeplinit, motivul consemnat, nu se reîncearcă fără o schimbare reală de metodologie.

---

## Sumar

| Prioritate | Experiment | Ipoteză (scurt) | Metrică principală | Status |
|---|---|---|---|---|
| P1 | Hyperparameter Tuning (Optuna) | Reduce Log Loss fără schimbare de date/algoritm | Log Loss | Rejected |
| P2 | Probability Calibration (baseline vs Platt vs Isotonic) | Reduce Log Loss/Brier, Accuracy neschimbată | Log Loss + Brier | Rejected |
| P3.0 | Design Review — formula MOV ELO | Alegerea formulei greșit ar propaga eroarea în tot sistemul (ELO domină modelul) | N/A (document) | Awaiting decision |
| P3 | Goal Difference ELO (MOV) | Crește fidelitatea ELO → crește Accuracy | Accuracy + fidelitate ELO | Blocked (așteaptă P3.0) |
| P4 | ELO Trend | Direcția recentă a ELO conține informație suplimentară | Accuracy / Log Loss | Planned |
| P5 | Schedule Strength | Nivelul adversarilor recenți conține informație suplimentară | Accuracy / Log Loss | Planned |
| P6 | Home Advantage per ligă | Avantaj de teren calibrat &gt; constantă fixă globală | Accuracy | Planned |
| P7 | Backfill complet + Shots on Target / Finishing / Defensive Efficiency | Structura statistică (șuturi, eficiență) conține informație dincolo de goluri brute | Accuracy / Log Loss | Planned |
| P8 | Injuries ca feature ML | Accidentările curente (informație contextuală) conțin semnal neexploatat | Accuracy / Log Loss | Planned |
| P9 | Benchmark LightGBM/CatBoost | XGBoost rămâne optim la scara actuală | toate 3 | Planned, prioritate joasă |
| — | Confidence Quality Index | Scor general de încredere al modelului — nu doar pentru Value Betting | N/A | Idea |

---

## Etapa 1 — Extragem tot din ce avem deja

### P1 — Hyperparameter Tuning (Optuna)

- **Motiv**: hiperparametrii XGBoost curenți (`n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85`) au fost stabiliți o singură dată, în primul commit al `ml_predictor.py`, fără nicio căutare sistematică ulterioară — confirmat prin audit (zero urmă de grid search/Optuna/comparație în tot repo-ul).
- **Ipoteză**: o căutare sistematică (Optuna, funcție obiectiv = metrica walk-forward pe date reale) găsește o combinație cu Log Loss mai mic decât configurația actuală, fără nicio schimbare de date sau algoritm.
- **Metrică urmărită**: Log Loss (principal); Accuracy și Brier raportate secundar, nu trebuie să regreseze.
- **Benchmark oficial**: Accuracy 0.4868 / Log Loss 1.0253 / Brier 0.6145.
- **Criteriu de succes**: Log Loss redus cu ≥0,5% relativ (≤1,0202), fără degradare &gt;0,001 pe Accuracy sau Brier, pe aceleași 5 folduri walk-forward.
- **Criteriu de abandon**: nicio combinație testată nu reduce Log Loss cu ≥0,3% relativ, sau reducerea vine cu degradare peste prag pe Accuracy/Brier.
- **Status**: **Rejected** (închis definitiv, două runde executate, ambele contra infrastructurii reale, walk-forward, 53.409 meciuri).

**Rezultate reale:**

*Runda 1 (2026-07-14/15) — 120 trial-uri, spațiu de căutare larg (9 hiperparametri, `TPESampler(seed=42)`), obiectiv = `avg_log_loss`.*

```
Log Loss : 1.0253 -> ~1.0206  (-0,46% relativ, cel mai bun candidat)
```
Cel mai bun candidat din runda 1 a redus Log Loss, dar sub pragul oficial de 0,5% relativ (0,46% < 0,50%). Deviația standard între folduri a candidatului câștigător (0,0055) a depășit chiar îmbunătățirea absolută (0,0047), iar acesta pierdea pe unul din cele 5 folduri — nuanță semnalată explicit la raportare, nu doar eticheta automată „OK" a scriptului. Verdict: **REJECTED** conform criteriului oficial de succes (nu a fost atins pragul de abandon de -0,3%, dar nici pragul de succes de -0,5%). Convergență netâmplătoare observată totuși: majoritatea trial-urilor de top se grupau strâns în jurul `max_depth=2-3`, `learning_rate≈0,03-0,04`, `n_estimators≈300-400`, regularizare pozitivă puternică (`reg_lambda`/`gamma` mari) — un semnal clar, nu zgomot, motiv pentru care s-a decis o rundă focalizată (P1.1) în loc de închidere imediată.

*Runda 2 — P1.1 (2026-07-15) — 400 trial-uri, spațiu de căutare restrâns la zona de convergență a rundei 1, `MedianPruner` (early stopping, 227/400 complete, 173 întrerupte), obiectiv de căutare = `avg_log_loss + 0,3×std_log_loss` (accent pe stabilitate), clasament final tot după `avg_log_loss` pur, pentru comparabilitate directă cu benchmark-ul și runda 1.*

```
Log Loss : 1.0253 -> 1.0203  (-0,0050, -0,4877% relativ)
Accuracy : 0.4868 -> 0.4891  (+0,0023)
Brier    : 0.6145 -> 0.6115  (-0,0030)
Folduri individuale care bat benchmark-ul: 4/5 (foldul 1 rămâne singurul punct slab: 1,0261 > 1,0253)
```

Cel mai bun candidat (`n_estimators=350, max_depth=3, learning_rate≈0,0296, subsample≈0,624, colsample_bytree≈0,775, min_child_weight=7, reg_alpha≈0,001, reg_lambda≈3,36, gamma≈2,80`) ratează pragul oficial de 0,5% relativ cu **0,0123 puncte procentuale** — la limită, dar sub prag. Accuracy și Brier s-au îmbunătățit fără nicio degradare, însă checkul suplimentar de stabilitate (câștig pe toate cele 5 folduri) nu trece. Convergența identică pe două runde independente (120 și 400 trial-uri, spații de căutare diferite) confirmă un optim local real, nu artefact statistic — dar pragul de succes a fost stabilit înainte de rezultat și nu se schimbă retroactiv.

**Concluzie**: conform deciziei explicite a Chief Architect, Hyperparameter Tuning se închide definitiv. Configurația de producție (`n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85`) rămâne neschimbată. Nu se reia investigația decât dacă se schimbă feature-urile, ELO-ul, sau datele de antrenare.

### P2 — Probability Calibration (baseline vs Platt vs Isotonic)

- **Motiv**: dovadă empirică deja existentă de supraîncredere sistematică (`ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md` — -4,6pp în bin-ul de încredere maximă pentru o variantă de model testată). Motorul de Value Betting depinde de acuratețea probabilității, nu doar de clasa prezisă.
- **Ipoteză**: o calibrare (Platt/sigmoid sau Isotonic), fitată STRICT fold-local, reduce Log Loss/Brier fără să afecteze Accuracy. Nu se presupune din start că Isotonic câștigă — se compară explicit împotriva Platt Scaling ȘI împotriva unui baseline fără nicio calibrare, toate trei pe aceleași folduri, aceleași date.
- **Metodologie fold-local (rafinată față de formularea inițială)**: segmentul de TRAIN al fiecărui fold walk-forward e împărțit mai departe, strict cronologic, în `clf-fit` (~85%, partea mai veche — antrenează XGBoost) și `calib` (~15%, partea mai recentă — antrenează calibratorul). VALIDATION rămâne complet neatinsă de orice antrenare. Motivul split-ului: Isotonic Regression, fitată direct pe predicțiile XGBoost pe propriile date de antrenare (in-sample), ar produce o calibrare artificial de optimistă — problemă documentată, motiv pentru care `sklearn.CalibratedClassifierCV` cere explicit un set de calibrare disjunct de antrenarea de bază. Split-ul rămâne 100% cronologic (zero leakage temporal, aceeași disciplină ca la eliminarea imputării).
- **Metrică urmărită**: Log Loss + Brier (principal); Accuracy monitorizată, nu e obiectiv — nu trebuie să regreseze peste prag.
- **Benchmark oficial**: idem, plus comparație internă baseline-din-experiment (control corect, izolează exact efectul calibrării, fără confuzie cu efectul reducerii volumului de date de antrenare al clasificatorului).
- **Calibrare — diagnostic suplimentar**: Expected Calibration Error (ECE) + reliability diagram (10 bin-uri de încredere), calculate pe predicțiile concatenate din toate cele 5 folduri de validare, pentru fiecare din cele 3 variante — răspunde explicit la întrebarea „modelul e overconfident, underconfident, sau bine calibrat?", nu doar la cifrele agregate de Log Loss/Brier.
- **Criteriu de succes**: Log Loss și/sau Brier reduse cu ≥0,5% relativ (față de baseline-ul din experiment), Accuracy neschimbată (±0,001).
- **Criteriu de abandon**: nicio reducere măsurabilă de Log Loss/Brier, sau reducere însoțită de schimbare a Accuracy peste prag.
- **Condiție de promovare (dacă Accepted)**: NU se promovează direct în producție. Se validează întâi impactul asupra motorului de Value Betting — o calibrare poate reduce Log Loss dar comprima probabilitățile suficient încât să scadă numărul de value bets identificate; acesta e un pas separat, ulterior, înainte de orice integrare în `ml_predictor.py`.
- **Status**: **Rejected** (rulat integral pe date reale, 53.409 meciuri, 5 folduri walk-forward, split clf/calib 85/15 cronologic în fiecare fold).

**Rezultate reale (2026-07-15):**

```
                Log Loss    Brier    Accuracy    ECE (pe 44.508 predicții din validare, pooled)
baseline        1.0277      0.6159   0.4842      0.0161
Platt           1.0254      0.6149   0.4867      0.0092   (-0,22% Log Loss, -0,16% Brier)
Isotonic        1.0631      0.6158   0.4865      0.0074   (+3,44% Log Loss -- MAI RĂU, -0,02% Brier)
```

Nicio variantă nu atinge pragul de 0,5% relativ (criteriul oficial) pe Log Loss sau Brier. Accuracy nu s-a degradat la nicio variantă (ambele au crescut ușor, sub pragul de semnificație urmărit). Verdict: **REJECTED**.

**Observație notabilă** (exact tipul de nuanță pe care cerința de Reliability Diagram + ECE a fost menită să o scoată la iveală, nu doar cifrele agregate): Isotonic îmbunătățește vizibil calibrarea propriu-zisă (ECE 0,0074 față de 0,0161 la baseline, reliability diagram cu mai multe bin-uri „calibrat" și mai puține „overconfident") — dar înrăutățește Log Loss cu 3,44% relativ, opus intuiției. Cauza: Isotonic Regression e o funcție treaptă (nu netedă); pe seturi de calibrare relativ mici per fold (1.336-6.677 meciuri), poate produce probabilități extreme (apropiate de 0/1) în bin-uri sparse din cozile distribuției — o singură predicție greșită acolo e penalizată sever de Log Loss (logaritmul unei probabilități aproape de 0). Platt Scaling (sigmoid, doar 2 parametri per clasă, funcție netedă) e mult mai robust pe seturi de calibrare de această dimensiune — de aceea câștigă marginal pe toate 3 metricile, dar insuficient pentru pragul de 0,5%.

**Concluzie**: modelul de producție e deja rezonabil de bine calibrat nativ (baseline ECE=0,0161, discrepanțe mici, majoritatea bin-urilor „calibrat"), motiv plauzibil pentru care nicio recalibrare nu produce un câștig suficient de mare. Nu se promovează nicio variantă în producție. Nu se declanșează pasul de validare Value Betting (condiționat explicit de Accepted). P2 se închide — nu se reia decât dacă apare o schimbare reală (feature-uri noi, volum de date mult mai mare, sau dovadă nouă de supraîncredere sistematică).

## Etapa 2 — Îmbunătățim informația dominantă (ELO)

*Context: ELO produce ~15-20× mai mult semnal (permutation importance) decât orice alt feature — orice investiție în calitatea lui are efect de levier asupra întregului model.*

### P3.0 — Design Review: formula MOV ELO (precondiție obligatorie pentru P3)

- **Motiv**: P3 nu e o optimizare peste o informație fixată (ca P1/P2) — schimbă informația însăși pe care modelul o învață. ELO domină importanța feature-urilor de 15-20× (`PREDICTOR_ROADMAP_V4.md`) — o formulă greșit aleasă se propagă în predictor, Learning Core, viitorul Confidence Engine, Value Betting. Decizie explicită a Chief Architect: nu se implementează P3 fără un document de proiectare aprobat în prealabil.
- **Document**: `docs/03_ENGINE/P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md` — compară 3 formule candidate (FiveThirtyEight-style logaritmică, ClubElo/eloratings.net-style treaptă, Pi Ratings), recomandă varianta FiveThirtyEight-style (logaritmică + corecție de surpriză pe elo_diff, constante supuse validării empirice) și recomandă scoaterea Pi Ratings din scopul P3 (sistem de rating diferit, nu o extensie a Elo). Propune metodologie de fidelitate în 3 straturi (comparație relativă vs. `ELO_RATINGS_FALLBACK`, stabilitate sezon-cu-sezon — 100% internă, distribuția diferențelor), cu avertisment explicit: nu există date reale ClubElo (clubelo.com) în proiect — singura referință externă e `ELO_RATINGS_FALLBACK` (stil eloratings.net, deja auditat în `ELO_FIDELITY_AUDIT_2026-07-13.md`, cu eroare sistematică de cold-start de 9,4% independentă de formula MOV). Propune design Replay A/B (independent, zero scriere, zero atingere producție) și un criteriu de succes compus (fidelitate ELO SAU predictor clar mai bun, nu doar unul singur marginal).
- **Status**: **Awaiting decision** — document livrat, așteaptă alegerea formulei (A/B) și confirmarea metodologiei de la Chief Architect înainte ca P3 să poată începe.

### P3 — Goal Difference ELO (MOV — Margin of Victory)

- **Motiv**: `ELOTracker` (`sync/backfill_features.py`) folosește azi exclusiv rezultatul categorial (H/D/A) la actualizarea ratingului — un 5-0 și un 1-0 produc identică actualizare. Standard în implementările Elo moderne (FiveThirtyEight, ClubElo).
- **Ipoteză**: un multiplicator de diferență de goluri produce un ELO mai fidel, care îmbunătățește la rândul lui predicțiile modelului.
- **Metrică urmărită**: Accuracy (principal — precedent direct în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, unde variante ELO diferite au mutat Accuracy cu +4,3pp); Log Loss/Brier raportate, regula de simultaneitate (CLAUDE.md) se aplică; fidelitatea ELO (§3, P3.0) raportată și ea, nu doar predictorul.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: (fidelitatea ELO crește LA §3 din P3.0) SAU (Accuracy crescută cu ≥0,3pp, fără regres simultan pe Log Loss ȘI Brier) — criteriu compus, formalizat în P3.0 §6, nu doar predictorul izolat.
- **Criteriu de abandon**: fidelitatea ELO scade ȘI câștigul de predictor e doar marginal (sub pragul de mai sus) — nu se promovează un ELO mai puțin fidel pentru un câștig mic.
- **Precondiție tehnică**: necesită recalculul complet al replay-ului istoric ELO (nu e o schimbare incrementală) — de rulat izolat, comparat cap-la-cap cu ELO-ul actual, nu de suprascris direct.
- **Status**: **Blocked** — așteaptă finalizarea P3.0 (alegerea formulei).

### P4 — ELO Trend

- **Motiv**: identificat deja în `PREDICTOR_ROADMAP_V4.md` (§7, Pasul 2) ca prim candidat testabil imediat — `elo_history` conține date 100% disponibile, neexploatate (tabelă write-only, zero interogare SELECT confirmată), niciodată implementat.
- **Ipoteză**: direcția recentă a ELO-ului (urcă/coboară în ultimele N meciuri) conține informație pe care valoarea instantanee n-o capturează.
- **Metrică urmărită**: Accuracy / Log Loss.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: îmbunătățire simultană pe minim 2 din 3 metrici.
- **Criteriu de abandon**: fără câștig măsurabil — precedent direct: `REST_DAYS_VALIDATION.md` (feature cu fundament teoretic solid, respins după test real fără câștig).
- **Status**: Planned.

### P5 — Schedule Strength

- **Motiv**: 100% derivabil din ELO deja existent al adversarilor recenți — zero colectare de date noi.
- **Ipoteză**: o victorie contra unui adversar puternic conține mai multă informație decât una contra unui adversar slab — azi indistinse de model.
- **Metrică urmărită**: Accuracy / Log Loss.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: îmbunătățire simultană pe minim 2 din 3 metrici.
- **Criteriu de abandon**: fără câștig măsurabil.
- **Status**: Planned.

### P6 — Home Advantage per ligă

- **Motiv**: `HOME_ADVANTAGE = 50` e o constantă fixă, aplicată identic tuturor ligilor (`sync/backfill_features.py:73`), deși Romania SuperLiga (22,3% acoperire ELO) probabil diferă structural de Premier League.
- **Ipoteză**: o valoare calibrată per ligă (regresie simplă pe rezultate istorice reale) produce un ELO mai fidel decât constanta globală.
- **Metrică urmărită**: Accuracy.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: îmbunătățire simultană pe minim 2 din 3 metrici, FĂRĂ regres pe ligile mari (deja bine calibrate implicit de valoarea actuală, dat fiind volumul lor mare de date).
- **Criteriu de abandon**: overfitting vizibil pe ligile mici (varianță mare între folduri) fără câștig pe ligile mari.
- **Status**: Planned.

## Etapa 3 — Date noi

*Ordine deliberată: structura statistică (P7) înaintea contextului (P8) — accidentările sunt informație contextuală, șuturile/eficiența sunt informație structurală. Structura vine înaintea contextului: aș vrea baza statistică cât mai completă înainte să introducem accidentările în ML.*

### P7 — Backfill complet + Shots on Target / Finishing Efficiency / Defensive Efficiency

- **Motiv**: date parțial disponibile extern (75-100% acoperire pe 6/7 ligi mari, `DATASET_CAPABILITY_AUDIT_2026-07-13.md`), dar 0% populate în producție — gap de backfill demonstrat, nu problemă de disponibilitate.
- **Ipoteză**: rata de conversie șut→gol (proxy ieftin pentru calitatea atacului, fără să aștepte xG extern) și echivalentul defensiv conțin informație pe care volumul brut de goluri istorice n-o capturează.
- **Metrică urmărită**: Accuracy / Log Loss.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: îmbunătățire simultană pe minim 2 din 3 metrici.
- **Criteriu de abandon**: fără câștig măsurabil, sau backfill-ul nu poate fi completat la o acoperire suficientă pentru un test statistic relevant.
- **Precondiție**: necesită completarea gap-ului de backfill shots/shots_on_target pentru ligile mari (infrastructură deja parțial existentă, `ShotsTracker`, `sync/backfill_features.py`) — de tratat ca pas separat, înainte de ablația propriu-zisă. Candidat direct pentru primul domeniu de aplicare al Football Data Harvester (vezi `FOOTBALL_DATA_HARVESTER_ARCHITECTURE_AUDIT.md`), odată ce acela e pregătit.
- **Status**: Planned, condiționat de precondiția de mai sus.

### P8 — Injuries ca feature ML

- **Motiv**: singura sursă cu date REALE deja colectate integral (API-Football, `injury_manager.py`, `football_providers.ApiFootballProvider.get_injuries()`) — azi folosită doar ca shadow logging dezactivat (`shadow_mode_enabled=False`) și aplicată multiplicativ pe xG pre-blend, niciodată ca input direct XGBoost.
- **Ipoteză**: informația de accidentări curente, aplicată STRICT point-in-time (cunoscută înainte de kickoff, nu retroactiv), conține semnal predictiv neexploatat azi de model.
- **Metrică urmărită**: Accuracy / Log Loss.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: îmbunătățire simultană pe minim 2 din 3 metrici, ȘI verificare explicită de zero leakage temporal (test dedicat, nu presupunere).
- **Criteriu de abandon**: fără câștig măsurabil, SAU imposibilitatea de a garanta disciplina point-in-time la scară (date de accidentări istorice incomplete/nesigure temporal).
- **Status**: Planned.

## Prioritate joasă — după epuizarea Etapelor 1-3

### P9 — Benchmark LightGBM/CatBoost

- **Motiv**: XGBoost nu a fost niciodată comparat empiric cu alt algoritm de gradient boosting.
- **Ipoteză**: la scara actuală (53k rânduri, 13 feature-uri), diferența e probabil neglijabilă — dar merită eliminarea incertitudinii, cost redus.
- **Metrică urmărită**: toate 3 (Accuracy, Log Loss, Brier).
- **Benchmark oficial**: idem.
- **Criteriu de succes**: &gt;1% relativ mai bun, simultan pe minim 2 din 3 metrici (prag mai mare decât la celelalte experimente, dat fiind costul de schimbare a dependinței de producție).
- **Criteriu de abandon**: diferență sub prag → rămânem pe XGBoost.
- **Status**: Planned, prioritate joasă — rulat abia după epuizarea experimentală a P1-P8.

---

## Backlog — idei capturate, neprogramate

### Confidence Quality Index

- **Motiv**: modelul produce o probabilitate, dar nu o estimare a cât de sigură e acea probabilitate. Situații ca echipă nou-promovată, antrenor nou, puține meciuri disponibile, multe valori lipsă — toate produc azi o probabilitate cu aceeași „greutate" aparentă ca una dintr-o situație bine cunoscută.
- **Viziune extinsă (Chief Architect)**: nu doar pentru Value Betting — un scor general de încredere al modelului, afișat alături de orice predicție. Două meciuri pot avea probabilități similare (ex. 61/23/16 vs. 42/31/27) dar încredere complet diferită — un scor separat (ex. „94/100" vs. „47/100") comunică asta explicit, unde probabilitatea singură nu poate.
- **Ipoteză**: neformulată încă — necesită proiectare separată (ce intră în index, cum se combină cu probabilitatea, cum consumă motorul de Value Betting și UI-ul acest semnal).
- **Nu schimbă predicția** — e un meta-semnal pentru motorul de decizie/UI, nu un input al modelului de clasificare.
- **Status**: Idea — capturată explicit, nu Planned (nu are încă ipoteză testabilă/criterii de succes formulate). Orizont: peste câteva luni, nu în P1-P9.

---

## Idei explicit amânate (nu respinse — doar neprioritizate azi)

Glicko/Glicko-2, TrueSkill, Pi Ratings, CatBoost/LightGBM (înainte de P9), PPDA, Possession, Travel/distanță, Competition weighting, rolling xG/xGA — vezi raportul de audit tehnic din 2026-07-14 (consemnat în conversație) pentru argumentarea completă avantaj/dezavantaj/complexitate/câștig estimat a fiecăreia. Niciuna nu e respinsă pe merit — sunt amânate până la epuizarea experimentală a P1-P9, conform deciziei explicite a Chief Architect.
