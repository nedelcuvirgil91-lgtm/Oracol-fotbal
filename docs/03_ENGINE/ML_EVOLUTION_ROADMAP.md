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
| P1 | Hyperparameter Tuning (Optuna) | Reduce Log Loss fără schimbare de date/algoritm | Log Loss | Planned |
| P2 | Probability Calibration (Isotonic) | Reduce Log Loss/Brier, Accuracy neschimbată | Log Loss + Brier | Planned |
| P3 | Goal Difference ELO (MOV) | Crește fidelitatea ELO → crește Accuracy | Accuracy | Planned |
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
- **Status**: Planned.

### P2 — Probability Calibration (Isotonic)

- **Motiv**: dovadă empirică deja existentă de supraîncredere sistematică (`ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md` — -4,6pp în bin-ul de încredere maximă pentru o variantă de model testată). Motorul de Value Betting depinde de acuratețea probabilității, nu doar de clasa prezisă.
- **Ipoteză**: calibrare isotonic, fitată STRICT fold-local (aceeași disciplină deja aplicată la eliminarea leakage-ului de imputare — fit doar pe segmentul de train al fiecărui fold, aplicat pe segmentul de validare), reduce Log Loss/Brier fără să afecteze Accuracy.
- **Metrică urmărită**: Log Loss + Brier (principal); Accuracy trebuie să rămână neschimbată (calibrarea nu schimbă clasa prezisă, doar probabilitatea atașată).
- **Benchmark oficial**: idem.
- **Criteriu de succes**: Log Loss și/sau Brier reduse cu ≥0,5% relativ, Accuracy neschimbată (±0,001).
- **Criteriu de abandon**: nicio reducere măsurabilă de Log Loss/Brier, sau reducere însoțită de schimbare a Accuracy peste prag.
- **Status**: Planned.

## Etapa 2 — Îmbunătățim informația dominantă (ELO)

*Context: ELO produce ~15-20× mai mult semnal (permutation importance) decât orice alt feature — orice investiție în calitatea lui are efect de levier asupra întregului model.*

### P3 — Goal Difference ELO (MOV — Margin of Victory)

- **Motiv**: `ELOTracker` (`sync/backfill_features.py`) folosește azi exclusiv rezultatul categorial (H/D/A) la actualizarea ratingului — un 5-0 și un 1-0 produc identică actualizare. Standard în implementările Elo moderne (FiveThirtyEight, ClubElo).
- **Ipoteză**: un multiplicator de diferență de goluri produce un ELO mai fidel, care îmbunătățește la rândul lui predicțiile modelului.
- **Metrică urmărită**: Accuracy (principal — precedent direct în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, unde variante ELO diferite au mutat Accuracy cu +4,3pp); Log Loss/Brier raportate, regula de simultaneitate (CLAUDE.md) se aplică.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: Accuracy crescută cu ≥0,3pp, fără regres simultan pe Log Loss ȘI Brier.
- **Criteriu de abandon**: nicio îmbunătățire simultană pe minim 2 din 3 metrici, sau regres pe oricare dintre ele.
- **Precondiție tehnică**: necesită recalculul complet al replay-ului istoric ELO (nu e o schimbare incrementală) — de rulat izolat, comparat cap-la-cap cu ELO-ul actual, nu de suprascris direct.
- **Status**: Planned.

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
