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
- **Inconclusive / Needs refinement** — nici criteriul de succes, nici cel de abandon nu e clar îndeplinit (ex. toate metricile se mișcă în direcția bună, dar sub pragul de semnificație stabilit, sau semnale contradictorii între sub-metrici). Nu se declară nici Accepted, nici Rejected — se cere o rundă scurtă, explicit delimitată, de rafinare (nu o căutare nouă) înainte de verdict final. **Poate rămâne starea finală, permanentă** (nu se escaladează automat la Rejected) când dovada arată un efect real dar prea mic pentru costul schimbării — distincție explicită, importantă: „Rejected" înseamnă „ideea nu funcționează"; „Inconclusive, fără promovare" înseamnă „ideea funcționează, dar câștigul nu justifică schimbarea, azi". Un experiment închis astfel poate fi reluat, fără reinventarea metodologiei, dacă o precondiție semnalată explicit (ex. o problemă de calitate a datelor) se rezolvă separat.

---

## Sumar

| Prioritate | Experiment | Ipoteză (scurt) | Metrică principală | Status |
|---|---|---|---|---|
| P1 | Hyperparameter Tuning (Optuna) | Reduce Log Loss fără schimbare de date/algoritm | Log Loss | Rejected |
| P2 | Probability Calibration (baseline vs Platt vs Isotonic) | Reduce Log Loss/Brier, Accuracy neschimbată | Log Loss + Brier | Rejected |
| P3.0 | Design Review — formula MOV ELO | Alegerea formulei greșit ar propaga eroarea în tot sistemul (ELO domină modelul) | N/A (document) | Accepted |
| P3 | Goal Difference ELO (MOV) | Crește fidelitatea ELO → crește Accuracy | Accuracy + fidelitate ELO + Spearman | **Inconclusive (fără promovare în producție)** |
| P3.1 | Rafinare P3 — reproductibilitate + rundă scurtă în jurul V3 | Rezolvă discrepanța de reproductibilitate + testează dacă o corecție de surpriză mai puternică produce câștig clar | Accuracy + Log Loss + Brier + fidelitate | Done (a informat verdictul final P3) |
| P3.5 | Team Identity Audit & Historical Normalization | Discrepanțele uriașe per-echipă găsite în P3.1 (unele echipe aproape identice cu referința, altele diferă cu 100-240 puncte) sunt semnătura unei probleme de normalizare a numelui de echipă, nu a formulei ELO | N/A (audit de date, nu experiment ML) | **Done** — 137 echipe, 10,1% din match_history afectat, cauza rădăcină identificată; consolidare istoric executată pe producție (Faza 3, 2026-07-15) |
| P3 Revalidation | Re-test MOV (V1-V5) pe baza consolidată de P3.5 | Consolidarea reduce eroarea de fidelitate suficient încât compromisul eroare-vs-rang (motivul Inconclusive original) să dispară | Fidelitate ELO + Spearman + Accuracy/Log Loss/Brier | **Accepted (V1_baseline, V2_damped — axa fidelitate)** |
| P4 | ELO Trend | Direcția recentă a ELO conține informație suplimentară | Accuracy / Log Loss | Planned (după decizia de implementare P3 Revalidation) |
| P5 | Schedule Strength | Nivelul adversarilor recenți conține informație suplimentară | Accuracy / Log Loss | Planned |
| P6 | Home Advantage per ligă | Avantaj de teren calibrat &gt; constantă fixă globală | Accuracy | Planned |
| P7.1 | `shot_dominance` (Structural Match Statistics, rundă 1) | Diferența de șuturi totale recente conține informație de formă imediată, complementară ELO-ului (rating pe termen lung) | Accuracy / Log Loss / Brier | **Accepted** |
| P7.2 | `sot_dominance` (Structural Match Statistics, rundă 2) | Idem, pe șuturi pe poartă — condiționat explicit de verdictul P7.1 | Accuracy / Log Loss / Brier | Planned, condiționat (P7.1 Accepted — poate începe la aprobare explicită, nu automat) |
| P8 | Injuries ca feature ML | Accidentările curente (informație contextuală) conțin semnal neexploatat | Accuracy / Log Loss | Planned |
| P9 | Benchmark LightGBM/CatBoost | XGBoost rămâne optim la scara actuală | toate 3 | Planned, prioritate joasă |
| P10 | Pi Rating Evaluation | Sistem de rating alternativ (Constantinou & Fenton 2013) — nu o variantă MOV, un sistem diferit, scos explicit din P3 | Accuracy / Log Loss / Brier | Idea |
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
- **Decizie finală (Chief Architect, 2026-07-15)**: Formula **A** (FiveThirtyEight-style) aleasă — motivată explicit prin cele două proprietăți cerute (efect descrescător logaritmic + „surprise factor" pe elo_diff, absent din varianta B). Constantele (2,2 / 0,001) **nu se îngheață** — tratate ca hiperparametri ai sistemului ELO, testate în 3 variante rezonabile la replay (nu căutare exhaustivă tip Optuna — doar verificare de direcție). **Pi Ratings confirmat în afara scopului P3** — devine **P10 — Pi Rating Evaluation**, idee separată, neprogramată azi (vezi tabelul Sumar). Metodologia de fidelitate confirmată ca fiind relativă (nu pretinde acces la ClubElo real), plus o cerință nouă, explicită: **Spearman Rank Correlation** între clasamentul replay-ului și clasamentul referinței — răspunde dacă noul ELO păstrează mai bine ierarhia echipelor, nu doar dacă se apropie în valoare absolută.
- **Criteriu de succes (P3, extins de Chief Architect)**: promovare dacă **fidelitatea ELO crește SAU predictorul crește clar** (Accuracy ≥+0,3pp, fără regres simultan pe Log Loss ȘI Brier), fără regresii majore pe celălalt braț. Nu se cere câștig simultan pe ambele — dacă predictorul câștigă vizibil și fidelitatea rămâne practic identică, e suficient.
- **Status**: **Accepted** — document + decizii finalizate, P3 poate începe.

### P3 — Goal Difference ELO (MOV — Margin of Victory)

- **Motiv**: `ELOTracker` (`sync/backfill_features.py`) folosește azi exclusiv rezultatul categorial (H/D/A) la actualizarea ratingului — un 5-0 și un 1-0 produc identică actualizare. Standard în implementările Elo moderne (FiveThirtyEight, ClubElo).
- **Ipoteză**: un multiplicator de diferență de goluri produce un ELO mai fidel, care îmbunătățește la rândul lui predicțiile modelului.
- **Metrică urmărită**: Accuracy (principal — precedent direct în `ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md`, unde variante ELO diferite au mutat Accuracy cu +4,3pp); Log Loss/Brier raportate, regula de simultaneitate (CLAUDE.md) se aplică; fidelitatea ELO (§3, P3.0) raportată și ea, nu doar predictorul.
- **Benchmark oficial**: idem.
- **Criteriu de succes**: (fidelitatea ELO crește — eroare relativă vs. referință scade ȘI/SAU Spearman rank correlation crește) SAU (Accuracy crescută cu ≥0,3pp, fără regres simultan pe Log Loss ȘI Brier) — criteriu compus, formalizat în P3.0 §6, extins cu Spearman.
- **Criteriu de abandon**: fidelitatea ELO scade ȘI câștigul de predictor e doar marginal (sub pragul de mai sus) — nu se promovează un ELO mai puțin fidel pentru un câștig mic.
- **Formula aleasă**: FiveThirtyEight-style (§P3.0) — `ln(gd+1) × c/(d·elo_diff+c)` pentru rezultate decisive, multiplicator=1,0 la egal (caz special, gd=0 ar anula altfel actualizarea — descoperit la implementare, nu în document). 3 variante de constante testate la replay (V1 baseline 2,2/0,001, V2 damped 4,4/0,0005, V3 amplified 1,1/0,002) — verificare de direcție, nu căutare exhaustivă.
- **Precondiție tehnică**: necesită recalculul complet al replay-ului istoric ELO (nu e o schimbare incrementală) — de rulat izolat, comparat cap-la-cap cu ELO-ul actual, nu de suprascris direct.
- **Status**: **Inconclusive (fără promovare în producție)** — închis definitiv, două runde independente (5 variante de constante testate total), nu se reia decât dacă P3.5 rezolvă problema de normalizare a numelor de echipă semnalată mai jos.

**Rezultate reale, runda 1 (2026-07-15, 53.409 meciuri, walk-forward, doar `home_elo`/`away_elo` înlocuite):**

```
                Accuracy    Log Loss    Brier      vs. referință (16 echipe)      Spearman
Replay A (control)  0,4842   1,0304     0,6175     mean_abs_pct_diff=11,23%       0,755
V1 baseline          +0,22pp  mai bun   mai bun     10,99% (mai bun)               0,737 (mai slab)
V2 damped            +0,10pp  mai bun   mai bun     10,35% (cel mai bun)           0,723 (cel mai slab)
V3 amplified         +0,20pp  cel mai bun brier/LL  13,13% (mai slab)              0,782 (cel mai bun)
```

Toate 3 variante îmbunătățesc simultan Accuracy/Log Loss/Brier față de Replay A, fără nicio regresie — semnal real, nu zgomot. Dar cea mai bună Accuracy (V1, +0,22pp) rămâne sub pragul de succes (+0,3pp) stabilit înainte de rezultat — conform disciplinei „nu schimbăm regulile după rezultate", nu se declară Accepted. Fidelitatea arată un trade-off real: V1/V2 reduc eroarea medie vs. referință dar înrăutățesc Spearman; V3 face invers (eroare medie mai mare, dar cel mai bun rang ȘI cel mai bun Log Loss/Brier) — niciun candidat nu câștigă clar pe ambele axe de fidelitate simultan, deci nu se declară nici Rejected (metricile de predictor nu regresează nicăieri).

**Problemă de reproductibilitate semnalată, de rezolvat înaintea oricărei alte optimizări**: `mean_abs_pct_diff` pentru Replay A (control, neschimbat față de producție) a ieșit 11,23% în această rulare, față de 9,40% raportat cu 2 zile înainte în `ELO_FIDELITY_AUDIT_2026-07-13.md`, cu aceeași metodologie și același număr total de meciuri (53.409). Cauza nu e încă identificată.

**Decizie Chief Architect (runda 1)**: nu se trece la P4. Se deschide **P3.1** — rundă scurtă de rafinare (nu o căutare nouă): (1) investighează discrepanța de reproductibilitate 9,40%/11,23%, (2) testează maximum câteva variante de constante în jurul lui V3 (cel mai interesant candidat — cel mai bun Log Loss/Brier, cel mai bun Spearman, argumentul fiind că rangul e mai puțin corupt de bias-ul de cold-start deja documentat decât eroarea medie absolută).

**Rezultate P3.1 (2026-07-15, aceleași 53.409 meciuri):**

*Diagnostic reproductibilitate* — Replay A a dat exact 11,23% și în această rulare (identic cu runda 1, deci 100% reproductibil intern). Comparat rând-cu-rând cu tabelul publicat în `ELO_FIDELITY_AUDIT_2026-07-13.md`: unele echipe aproape identice (Atletico Madrid 1530,7 vs 1531; Manchester City 1776,6 vs 1782; Real Madrid 1791,0 vs 1781), altele diferă cu sute de puncte (Manchester United 1549,6 vs 1742, diferență ~192; Inter Milan 1550,1 vs 1791, ~241; Bayern Munich 1781,5 vs 1909, ~127; Tottenham 1494,3 vs 1575, ~81). Tipar neregulat, nu un offset uniform — semnătura unei probleme de **normalizare a numelui de echipă** în `match_history` (istoric fragmentat sub variante de nume diferite), nu a formulei MOV sau a codului de replay. Precedent direct: `ELO_FIDELITY_AUDIT` semnalase deja exact acest mecanism pentru Atletico Madrid („doar 10 meciuri în tot replay-ul"). Cauza rădăcină NU e rezolvată aici — vezi P3.5.

*Rundă de rafinare (V3 repetat + V4 mai amplificat + V5 mai puțin amplificat)*:

```
                Accuracy vs A    Log Loss vs A    Brier vs A    Fidelitate (eroare/Spearman)    yoy_std sezon
V3 (repetat)    +0,20pp          mai bun          mai bun       13,13% / 0,782 (identic rundei 1) 61,65
V4 mai amplif.  -0,10pp (regres) mai slab         mai slab      14,0% / 0,737 (ambele mai slabe)   105,87 (dublu)
V5 mai puțin    +0,29pp          mai bun          mai bun       11,9% / 0,752 (practic identic)    63,39 (practic identic)
```

V4 arată clar limita superioară — regresie pe toate metricile plus instabilitate sezon-cu-sezon dublă (corecție de surpriză prea agresivă). **V5 e cel mai bun rezultat din tot P3**: Accuracy +0,29pp, la 0,01pp sub pragul strict de 0,3pp — cel mai aproape de prag din toate cele 5 variante testate (2 runde) — cu fidelitate practic neschimbată față de Replay A.

**Verdict final (Chief Architect)**: nu se mai face o rundă P3.2. Motivul nu e diferența de 0,01pp — e că tiparul e deja convergent și coerent pe două runde independente (V1→V5, aceeași zonă de câștig mic dar real), consistent cu concluziile P1 (plafon atins după 2 runde Optuna) și P2 (model deja bine calibrat): informația marginală dintr-o căutare suplimentară ar fi foarte mică. **P3 se închide ca Inconclusive, NU Rejected** — distincție deliberată: efectul predictiv e real (toate cele 5 variante mișcă Accuracy/Log Loss/Brier consistent în direcția bună, fără nicio regresie la V1/V2/V3/V5), dar insuficient pentru costul unui replay complet al întregii istorii ELO, azi. Cea mai valoroasă descoperire a acestei investigații nu e formula MOV — e problema de normalizare a numelor de echipă, care probabil produce mai mult zgomot în comparațiile de fidelitate decât orice alegere de formulă. **Nu se reoptimizează MOV** — următoarea prioritate e calitatea datelor (P3.5). Dacă acel audit repară fragmentarea istoricului, V5 (sau formula A în general) poate fi re-testată peste luni, fără reinventarea metodologiei.

### P3.1 — Rafinare P3 (reproductibilitate + rundă scurtă în jurul V3)

- **Motiv**: P3 marcat Inconclusive — semnal real (toate metricile de predictor se mișcă în direcția bună, fără nicio regresie), dar sub pragul de succes stabilit, plus o discrepanță de reproductibilitate nerezolvată pe fidelitate.
- **Pasul 1**: diagnostic direct — tabel complet per-echipă (Replay A vs. referință) printat explicit, comparabil rând-cu-rând cu tabelul deja publicat în `ELO_FIDELITY_AUDIT_2026-07-13.md`, pentru a localiza sursa discrepanței 9,40%/11,23%.
- **Pasul 2**: 3 variante noi de constante, bracketând V3 (V3 repetat ca ancoră/verificare de reproductibilitate + V4 mai amplificat + V5 mai puțin amplificat) — nu o căutare exhaustivă.
- **Criteriu**: identic cu P3 (§ de mai sus).
- **Rezultat**: vezi rezultatele complete în secțiunea P3 de mai sus. Cel mai bun candidat (V5) a ajuns la 0,01pp sub prag — aproape, dar nu clar. Chief Architect a decis să nu mai continue cu o rundă suplimentară (convergență deja demonstrată pe 2 runde/5 variante), și a închis P3 ca Inconclusive, nu Rejected.
- **Status**: **Done** — a informat verdictul final al P3, nu se mai reia separat.

### P3.5 — Team Identity Audit & Historical Normalization

- **Motiv**: descoperire directă din P3.1 — comparând ratingul final `ELOTracker` (replay complet peste `match_history`) cu referința externă pentru aceleași 16 echipe, unele echipe se potrivesc aproape perfect (Atletico Madrid, Manchester City, Real Madrid — diferențe sub 10 puncte), altele diferă cu 80-240 de puncte (Manchester United, Inter Milan, Bayern Munich, Tottenham). Tiparul neregulat (nu un offset sistematic) e incompatibil cu o eroare de formulă sau un bias uniform de cold-start — e semnătura clasică a unui istoric de echipă fragmentat sub mai multe variante de nume, fiecare pornind propriul rating de la zero. Precedent deja documentat pentru Atletico Madrid în `ELO_FIDELITY_AUDIT_2026-07-13.md` (doar 10 meciuri în tot replay-ul, semnalat atunci ca „indiciu de problemă de acoperire/normalizare specifică acestui nume", nerezolvat).
- **Ipoteză**: `match_history` conține variante de nume neconsolidate pentru un subset de echipe (alias-uri, redenumiri istorice, promovări/retrogradări între ligi cu nume ușor diferite, posibile duplicate) — consolidarea lor ar produce un `ELOTracker` semnificativ mai fidel, fără nicio schimbare de formulă.
- **Scop**: audit sistematic — alias-uri de echipe, redenumiri, promovări/retrogradări, echipe duplicate, istorii fragmentate. Nu e un experiment ML (fără criteriu Accuracy/Log Loss/Brier propriu) — e un audit de calitate a datelor, cu livrabil probabil un raport + o listă de consolidări propuse (aplicate ulterior, separat, cu disciplina obișnuită de scriere pe producție — confirmare explicită, niciodată check-then-act).
- **Legătură cu P3**: dacă acest audit reduce semnificativ discrepanțele neregulate găsite în P3.1, formula MOV (în special V5) devine candidat pentru re-testare — fără reinventarea metodologiei, doar peste date mai curate.
- **Status**: **Done**.

**Rezultate reale (2026-07-15)**: `docs/03_ENGINE/TEAM_IDENTITY_AUDIT.md` + `docs/03_ENGINE/canonical_team_mapping.csv`.

Descoperire centrală: `TEAM_ALIASES`/`normalize_team_name()` (`mappings.py`, 272 intrări) **există deja** și acoperă majoritatea covârșitoare a cazurilor — problema nu e lipsa unei surse de adevăr, e o **gaură de wiring**: `sync/import_historical.py` (import istoric bulk) apelează `normalize_team_name()` la fiecare rând; niciunul din writer-ii sincronizării zilnice (`sync/sources/football_data.py`, `football_data_co_uk.py`, `kaggle.py`, `openfootball.py`, `sync/sync_results.py`) nu o apelează — scriu numele echipelor brut, direct din payload-ul API.

**137 echipe canonice afectate, 146 cazuri confirmate** (129 deja acoperite de `TEAM_ALIASES` dar neaplicate + 17 noi, negăsite până acum — tipar ALL-CAPS dintr-un al treilea provider de date de cupe europene). **10.835 apariții de meci „rătăcite" (10,1% din tot volumul `match_history`, 106.860 apariții).** Verificare exhaustivă: cele 729 de nume rămase, rulate prin `normalize_team_name()` pentru clustering automat — zero clustere noi găsite, deci acoperire completă a tot ce e detectabil mecanic.

**Descoperire importantă, contrazice ipoteza inițială**: distribuția impactului NU e concentrată — top 20 cazuri acoperă doar 25,1% din impact, top 30 doar 36,1% (nu „primele 20 rezolvă 95%"). Aproape toate echipele mari afectate (Atletico Madrid, Real Madrid, Inter Milan, Arsenal, PSG, Manchester City, Bayern Munich...) au impact similar (120-160 meciuri fiecare) — problema e lată, nu ascuțită.

**Cele 4 echipe cu discrepanțele cele mai mari din P3.1** (Manchester United, Inter Milan, Bayern Munich, Tottenham) apar toate în lista confirmată, cu exact același mecanism.

**Nicio scriere efectuată în timpul auditului** — nici în `match_history`, nici în `TEAM_ALIASES`, nici în cod de producție.

**Fix de wiring aplicat separat, imediat după (2026-07-15), aprobat explicit de Chief Architect — Faza 1 din planul în 3 faze (Fix preventiv → Observație → Consolidare istoric):**
- `database/queries._normalize_team_fields()` (funcție nouă) aplicată în `upsert_match()` și `upsert_matches_bulk()` — funnel-ul folosit de `sync/sync_matches.py` (football-data.org, openfootball), același principiu ca „Protecția Writer-ilor" (2026-07-13): garda la punctul unic de trecere, nu în fiecare sursă individual.
- `supabase_client.upsert_match_history()` — al doilea funnel (folosit de `oracle_engine.py`, introducere manuală de rezultat din UI) — normalizare identică.
- `sync/sync_results.py` (`fetch_yesterday_results()`) — normalizare la EXTRAGERE, nu doar la scriere: căutarea rândului existent (`home_team`+`away_team`+`kickoff_date`) ar fi eșuat silențios contra rândurilor deja scrise canonic de primele două funnel-uri, altfel.
- **10 teste noi** (`tests/test_team_normalization_writers.py`) — demonstrează că toate cele 3 puncte de intrare produc același nume canonic pentru aceeași echipă (`test_all_writers_agree_on_the_same_canonical_name`), inclusiv regresie directă pe cazul Atletico Madrid din audit. 380/380 teste verzi (370 + 10 noi).
- **Nicio consolidare a `match_history` existent** — doar rândurile scrise de acum înainte sunt normalizate. Faza 2 (observație, câteva zile) și Faza 3 (plan de migrare dry-run + raport înainte/după, execuție separată) rămân neînceput, condiționate explicit de confirmarea că Faza 1 funcționează corect în producție.

### P3 Revalidation — Re-test MOV pe baza consolidată de P3.5

- **Motiv**: P3.5 (audit + consolidare istoric echipe) fusese deschis direct din P3.1, cu legătura explicit semnalată atunci: „dacă acest audit reduce semnificativ discrepanțele neregulate găsite în P3.1, formula MOV ... devine candidat pentru re-testare — fără reinventarea metodologiei, doar peste date mai curate." Faza 3 (consolidare istoric, executată și verificată pe producție, 2026-07-15) a închis precondiția — directivă explicită Chief Architect de a răspunde la întrebare pe date măsurate.
- **Metodologie**: identică cu P3/P3.1 (`scripts/_p3_elo_mov_replay_temp.py`, recuperat din git history, formula/constantele/împărțirea walk-forward neschimbate), extinsă aditiv cu toate 5 variante testate vreodată (V1-V5, constantele V4/V5 recuperate din log-urile GitHub Actions ale rulării P3.1 originale — nu erau comise nicăieri), plus ECE și feature importance ca instrumentare suplimentară.
- **Document complet**: `docs/03_ENGINE/P3_REVALIDATION_POST_P3_5_2026-07-15.md`.
- **Rezultat central**: eroarea de fidelitate a Replay A (control, neschimbat) a scăzut de la 11,23% la **6,84%** (−39% relativ) — cea mai mare îmbunătățire de fidelitate ELO din tot proiectul. Mai important: **V1_baseline și V2_damped îmbunătățesc acum SIMULTAN ambele axe de fidelitate** (eroare absolută ȘI Spearman rank correlation) — pentru prima dată în tot istoricul P3, rezolvând exact compromisul intern (o axă câștigă, cealaltă pierde) care produsese verdictul Inconclusive original. Niciun candidat nu atinge pragul de Accuracy +0,3pp (cel mai apropiat, V2, +0,25pp) — dar criteriul compus stabilit în P3.0 (fidelitate crește SAU predictor crește clar) e o disjuncție, nu o conjuncție, iar ramura de fidelitate e acum clar îndeplinită.
- **Descoperire secundară**: V4_more_amplified (deja slab în P3.1) produce pe date consolidate o instabilitate numerică reală (Inter Milan → rating 4040, +112,85% față de referință) — constantele sale (c=0,8/d=0,0025) devin degenerate quando diferențele ELO reale (nu mai comprimate de fragmentare) cresc. Confirmă, nu schimbă, respingerea deja stabilită a V4.
- **Status**: **Accepted** (V1_baseline, V2_damped — pe axa fidelitate ELO, susținut exclusiv de măsurători). **Nicio implementare încă** — verdictul e o recomandare completă, cu V2_damped ca prim candidat; decizia de promovare + planul de implementare rămân la Chief Architect, așteptând review arhitectural explicit înainte de orice schimbare de cod. Execuția NU a continuat automat spre P4/P7.2 sau alt experiment.

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

### P7 — Structural Match Statistics (familie de experimente, disciplină un-singur-feature-per-rundă)

**Document umbrelă**: `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md` (2026-07-15) — audit + design review complet: stare reală DB (backfill ADR-011 deja rulat, 66,7% populat pe cele 5 ligi mari pentru `shots`/`shots_on_target`/`fouls`/`corners`/`cards`/HT; `possession`/`xg_actual` 0% peste tot), infrastructură reutilizabilă identificată (`STAT_GROUPS`, `MatchStatsBackfillService`, `ShotsTracker`), 17 feature-uri derivate propuse, matrice prioritate/impact/complexitate.

**Decizie Chief Architect (2026-07-15)**: nu se implementează simultan întreaga familie de feature-uri bazate pe șuturi propusă în documentul umbrelă. Se respectă disciplina deja stabilită la P1-P3: **un singur feature nou pe rundă, ablație completă walk-forward, decizie Accepted/Rejected/Inconclusive explicită înainte de a continua la următorul.** P7 devine, la rândul lui, o secvență de sub-experimente numerotate (P7.1, P7.2, ...), nu un singur experiment cu mai multe feature-uri bundle-uite.

- **P7.1 — `shot_dominance`** (singurul feature implementat în această rundă) — design complet: `P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md`. **P7.1A — Data Quality Audit** (`P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md`): coverage 92,7%, nicio corelație ≥0,9 cu feature existent, Mutual Information 1,44× mai mare ca `corner_dominance` și 3,19× mai mare ca `foul_diff` — verdict GO. **Implementation Plan aprobat** (`P7_1_IMPLEMENTATION_PLAN.md`), implementare completă: `ShotCountTracker` (`sync/backfill_features.py`), migrare + backfill pe producție (4.868/5.253 rânduri, 92,7%, zero valori negative/NaN/infinite — verificare de consistență trecută). **Ablație oficială** (`SHOT_DOMINANCE_ABLATION_2026-07-15.md`): toate 3 metrici îmbunătățite simultan (Δacc +0,0046, Δlog-loss −0,0062, Δbrier −0,0047). Status: **Accepted** — `ADR-021-shot-dominance-ml-feature.md`. `ml_predictor.FEATURE_COLUMNS` are acum 14 intrări; `oracle_engine`/`explainability.py` extinse pentru calea live. 387/387 teste verzi.
- **P7.2 — `sot_dominance`** — pornește DOAR dacă P7.1 e Accepted. Reutilizează `ShotsTracker` (deja calculează media glisantă de șuturi pe poartă, azi consumată doar de `compute_team_offdef_rating`, niciodată expusă ca feature XGBoost separat) — cost de implementare mic dacă se ajunge acolo, dar design-ul propriu-zis (leakage, prag de succes) se scrie abia după verdictul P7.1, nu în avans. Status: Planned, condiționat.
- **Backlog, neprogramat explicit** (nu respins, doar în afara scopului rundei curente): `shot_accuracy`, `finishing_efficiency`, `defensive_efficiency`, `opponent_shot_pressure`, restul celor 17 feature-uri din documentul umbrelă — reevaluate individual, câte unul, doar după ce P7.1/P7.2 se închid.
- **Possession**: rămâne blocat — nicio sursă gratuită conformă ToS nu acoperă backfill istoric (confirmat în documentul umbrelă, §3), doar API-Football live/incremental, cu lună(i) de acumulare înainte de a avea istoric suficient pentru un test walk-forward relevant. Nu se deschide niciun P7.x pentru posesie până nu există fie o sursă, fie suficient istoric acumulat.
- **Big Chances**: rămâne explicit în afara scopului — nicio coloană în schemă, nicio sursă conformă ToS pentru niciuna din cele 11 competiții urmărite (confirmat, `KNOWLEDGE_ENGINE_SOURCES_AUDIT_2026-07-13.md`).
- **League Identity (duplicare `E0` vs. `Premier League`)**: risc identificat separat în documentul umbrelă (§8.2), analog structural cu Team Identity Audit (P3.5) dar distinct de el — rămâne backlog separat, tratat ca un eventual P3.5-bis viitor. **Nu blochează P7.1** — `shot_dominance` se calculează per echipă din istoricul ei cronologic, indiferent sub ce nume de ligă apare rândul; fragmentarea de ligă ar afecta agregări pe ligă (ex. calibrare per ligă), nu media glisantă per echipă folosită aici.

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

### P10 — Pi Rating Evaluation

- **Motiv**: descoperit/discutat explicit în P3.0 (`P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md`, §1.3) ca a treia formulă candidată pentru MOV — dar Pi Ratings (Constantinou & Fenton, 2013) nu e o extensie a Elo, e un sistem de rating diferit: două ratinguri per echipă (acasă/deplasare), actualizate printr-o regresie asupra diferenței de goluri, cu factor de „scurgere" între cele două ratinguri ale aceleiași echipe. Ar înlocui `ELOTracker` complet, nu l-ar extinde — scos explicit din scopul P3, confirmat de Chief Architect.
- **Ipoteză**: neformulată încă în detaliu — necesită propriul document de design (similar P3.0) înainte de orice implementare, dat fiind că schimbă structura de rating, nu doar formula de actualizare.
- **Metrică urmărită**: Accuracy / Log Loss / Brier — plus, probabil, aceleași verificări de fidelitate/Spearman stabilite la P3.0, adaptate la structura pe două ratinguri.
- **Status**: Idea — capturată explicit, neprogramată, candidat pentru un viitor P3.0-style design review dedicat, după ce P3 (MOV) se închide.

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
