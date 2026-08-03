# ML Activation Implementation Plan (EPIC "ML Activation & Oracle Evolution", Etapa 4)

**Status**: Propunere de plan, în așteptarea aprobării. Niciun cod de producție nu a fost modificat, niciun flag activat, niciun commit în afara documentației.
**Data**: 2026-08-03
**Precondiții**: `docs/00_GOVERNANCE/ORACLE_ENGINE_AUDIT.md` (Etapa 1), `docs/00_GOVERNANCE/ML_ENGINE_AUDIT.md` (Etapa 2), `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md` (Etapa 3) — toate completate și aprobate ca precondiție pentru acest document. Acest plan nu introduce nicio informație nouă, brută — sintetizează exclusiv concluziile deja stabilite în cele trei rapoarte.

---

## 1. Verdict executiv

| Întrebare | Răspuns | Sursă |
|---|---|---|
| ML merită activat ca sursă principală de predicție, în locul Oracle? | **Nu, nu azi.** Nicio dovadă din benchmark nu susține asta. | Etapa 3 §1, §3.1 |
| Blend (Oracle + ML slab ponderat) aduce valoare? | **Plauzibil, sub testare graduală** — nu direct în producție. | Etapa 3 §1, §7 |
| Oracle are defecte care merită corectate independent de decizia ML? | **Da — cel puțin 2 bug-uri concrete și 1 ambiguitate de configurare.** | Etapa 1 |
| ML e pregătit tehnic pentru o activare, chiar dacă decizia ar fi "da"? | **Nu — lipsește persistența reală de model** (gol critic, nu detaliu). | Etapa 2 |

Concluzia generală: acest EPIC nu se termină cu "activăm ML" sau "renunțăm la ML" — se termină cu o secvență de reparații mici, verificabile individual, care trebuie făcute **înainte** ca orice decizie de activare să fie măcar tehnic posibilă de testat corect. Ordinea contează: reparațiile Oracle nu depind de ML, reparațiile ML nu depind de Oracle, dar Blend-ul nu poate fi testat serios până când ambele părți nu sunt curate.

---

## 2. Ce trebuie modificat în Oracle Engine

Sursă: `ORACLE_ENGINE_AUDIT.md`, secțiunile despre `compute_team_offdef_rating`, `calibrate_xg`, ponderi fixe, cod mort.

### 2.1 Bug confirmat — dublă numărare a golurilor marcate (`compute_team_offdef_rating`)

`avg_goals_for` intră de două ori în `off_stat`: o dată normalizat și ponderat prin `g_norm * goals_weight` (parte din sistemul de ponderi configurabil), a doua oară brut, prin `+ avg_goals_for * 0.2` — o pondere hardcodată, în afara sistemului `weights.json`/`DEFAULT_WEIGHTS`, deci invizibilă oricui ajustează ponderile din configurare. Efectul: echipele cu multe goluri marcate sunt favorizate mai mult decât indică ponderile configurate explicit, iar acest efect suplimentar nu poate fi văzut sau ajustat din config.

**Recomandare**: eliminarea termenului hardcodat `+ avg_goals_for * 0.2`, cu golurile marcate reprezentate o singură dată, prin calea ponderată normal. Necesită re-rulare a testelor de regresie (Predictor Regression Suite, EPIC anterior, Punctul 2) înainte/după, pentru a documenta explicit magnitudinea schimbării pe fixture-urile cunoscute.

**Risc**: schimbare de formulă în calea de predicție live — se califică drept schimbare de comportament al Oracle Engine, nu doar detaliu de implementare. Trebuie validată funcțional (rulare reală pe fixture-uri cunoscute), conform regulii din CLAUDE.md ("Orice schimbare în calea de predicție se verifică funcțional, nu doar prin teste unitare").

### 2.2 Ambiguitate de denumire — `dna_weight` în `calibrate_xg`

Numele parametrului `dna_weight` sugerează o legătură cu Team DNA (Flashscore), dar în formula `calibrate_xg` el e de fapt greutatea componentei "de bază" (non-formă) din blend-ul `form_weight*home_form_mod + dna_weight`, fără nicio legătură reală cu datele Team DNA introduse ulterior (Punctul 5, EPIC anterior). Nu e un bug funcțional — formula produce rezultatul corect — dar numele induce în eroare pe oricine citește codul și poate crea impresia falsă că Team DNA e deja integrat în `calibrate_xg`, când de fapt Team DNA alimentează doar UI-ul.

**Recomandare**: redenumire `dna_weight` → `base_weight` (sau echivalent neutru), fără schimbare de valoare sau comportament. Schimbare pur cosmetică, risc minim, dar previne confuzie viitoare exact în punctul unde Etapa 4 discută integrarea ML/Blend cu Oracle.

### 2.3 Discrepanță confirmată — pondere impact accidentări (0.20 vs. 0.25)

`_calc_impact_from_market_value()` (`injury_manager.py`) folosește ponderea `0.25` în cod, dar docstring-ul funcției afirmă `0.20`. Nu s-a stabilit care valoare e cea "corectă" (nu există test de ablație care să fi validat 0.25 vs. 0.20) — doar discrepanța a fost confirmată.

**Recomandare**: nu se schimbă valoarea numerică fără un test de ablație dedicat (conform regulii ML/proiect: "Feature nou... doar cu dovadă de ablație, nu presupunere" — extins prin analogie la orice schimbare de pondere fixă cu impact măsurabil). Se corectează doar docstring-ul, ca să reflecte realitatea codului (`0.25`), eliminând discrepanța documentată. Un test de ablație pe 0.20 vs. 0.25 rămâne opțional, separat, nu blocant pentru acest EPIC.

### 2.4 Ponderi per-ligă inerte (`resolve_league_weights`)

Confirmat live: `sample_count=0` pentru toate cele 11 ligi, deci `alpha = min(sample_count/5, 1)` e mereu `0` — mecanismul de blend global/per-ligă returnează mereu ponderile globale, niciodată cele per-ligă, indiferent de ce e configurat în `weights.json` pe secțiunea per-ligă. Root cause: `auto_recalibration_enabled` implicit `False`/absent în `model_config`.

**Recomandare**: NU se activează `auto_recalibration_enabled` ca parte a acestui EPIC — activarea unui mecanism de recalibrare automată e o schimbare de comportament separată, cu propriile riscuri (regula North Star #3: "niciun flag nou nu pornește implicit activ"), care merită propria evaluare, nu una ascunsă într-un EPIC despre ML. Se documentează explicit, în cod (comentariu) și în `ARCHITECTURE_STATE.md`, că mecanismul e prezent dar inert azi, ca să nu fie redescoperit ca "bug" într-o sesiune viitoare.

### 2.5 Cod mort — `injury_manager.py`

5 elemente confirmate fără apelanți: `get_injury_report_from_cache()`, `ABSENCE_CERTAINTY`, `_impact_label()`, `MIN_STARTER_MINUTES`, `MIN_KEY_PLAYER_MINUTES`.

**Recomandare**: eliminare directă — cod mort fără nicio referință funcțională, risc zero de regresie (căci nimic nu-l apelează). Singura precauție: verificare finală cu grep exhaustiv imediat înainte de ștergere (nu doar reluarea concluziei din audit), pentru cazul în care ceva a schimbat starea între timp.

### 2.6 Ce NU se modifică din Etapa 1

- `rest_days_modifier` rămâne neapelat, deliberat — deja validat printr-un test de ablație real (`REST_DAYS_VALIDATION.md`), nicio acțiune necesară.
- Regula de penalizare a vremii (weather penalty, egală pe ambele echipe) — nu a fost identificată ca bug, doar documentată ca regulă hardcodată; nu există dovadă că ar trebui schimbată.
- Cascada de aplicare a penalizării de accidentări ca pas separat, după `calibrate_xg` — arhitectural corect (injury e per-echipă, post-xG), nu un defect.

---

## 3. Ce trebuie modificat în ML Engine

Sursă: `ML_ENGINE_AUDIT.md`, secțiunile despre persistență, calibrare implicită, concept drift, rollback.

### 3.1 Gol critic — lipsa persistenței reale de model artefact

`model_artifact_storage.py::save_model_artifact()` are zero apelanți în producție. Efectul: `champion_loader` întoarce mereu `None`, iar `oracle_engine._initialize_ml()` reantrenează efemer, în memorie, la fiecare pornire de proces — nu există niciodată un model "campion" persistat și reîncărcat. Acesta e cel mai important gol tehnic găsit în întregul EPIC, pentru că invalidează parțial premisa de "învățare continuă": fiecare proces pornește de la zero, indiferent câte cicluri `continuous_learning.py` au rulat anterior.

**Recomandare**: aceasta e precondiția tehnică pentru orice activare serioasă a ML — fără ea, ML nu poate fi "campion" în sensul arhitecturii Champion/Challenger deja construite (ADR-016, ADR-030, ADR-037), doar un model efemer recalculat la fiecare boot. Implementarea necesită conectarea `save_model_artifact()` la finalul unui ciclu de antrenare reușit (`training_runner`/`continuous_learning.py`) și verificarea că `champion_loader` chiar găsește și încarcă artefactul salvat — se califică drept schimbare de contract (Prediction Engine ↔ Learning Core), deci necesită ADR nou, nu editare tăcută (regula ADR din CLAUDE.md).

### 3.2 Supraîncredere confirmată (Etapa 3) — necesită calibrare, nu doar antrenare

Benchmark-ul (Etapa 3) a confirmat empiric supraîncrederea ML: pe bin-ul de încredere [0.70, 1.01), ML raportează încredere medie 0.821 dar acuratețe reală de doar 0.578 (gap 24.3pp). Asta nu e un artefact al benchmark-ului — e consecința directă a antrenării full-batch pe eșantioane relativ mici per fold, fără niciun mecanism de calibrare post-hoc (Platt scaling, isotonic regression) în `ml_predictor.py`.

**Recomandare**: înainte de orice activare de Blend, chiar și în shadow, ML ar trebui să treacă printr-un pas de calibrare a probabilităților (de exemplu, isotonic regression pe un fold de validare separat) — altfel `blend_predictions()` combină o sursă bine calibrată (Oracle) cu una sistematic supraîncrezută, iar rezultatul depinde excesiv de `ml_weight` fiind suficient de mic ca să mascheze problema, nu ca s-o rezolve. Aceasta e o schimbare de algoritm (nu doar hiperparametru), deci intră sub disciplina de ablație — necesită măsurare explicită "înainte/după calibrare" pe același benchmark walk-forward din Etapa 3, nu presupunere.

### 3.3 Concept drift — cod prezent, dezactivat

Champion Guardian are `_trend_degradation()` implementat și testat, dar `champion_guardian_enabled=False` live. Nu există dovadă că activarea lui e urgentă azi (nu există încă un campion real persistat de monitorizat — vezi 3.1), dar codul e gata.

**Recomandare**: nu se activează în acest EPIC — activarea Champion Guardian depinde logic de rezolvarea 3.1 (fără artefact persistat, nu există "campion" a cărui sănătate să fie monitorizată în timp). Se documentează ca pas ulterior, condiționat explicit de 3.1.

### 3.4 Rollback — cod complet, neexecutat în producție

ADR-037 (R1/R2/R3) e cod complet și testat, dar neactivat (R4, activarea în producție, separată deliberat de merge). Nu necesită nicio acțiune nouă în acest plan — planul de activare există deja separat (`docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md`) și nu trebuie duplicat aici.

### 3.5 Versionare — parțială

`training_runs` persistă metadate (55 rânduri confirmate live), dar fără artefacte reale de model (vezi 3.1), versionarea e incompletă — există istoricul "când s-a antrenat", nu "ce anume s-a antrenat, recuperabil". Rezolvată automat de 3.1, nu necesită lucru separat.

### 3.6 Promovare — corect, fără acțiune necesară

Promovarea Champion/Challenger e strict om-în-buclă (`auto_promotion_enabled` nu există în cod ca opțiune reală) — consecvent cu ADR-002 și cu North Star #2/#3. Nicio schimbare recomandată.

---

## 4. ML merită activat ca sursă principală?

**Verdict: Nu, pe baza dovezilor actuale.**

Argumentare, exclusiv din Etapa 3:
- Accuracy mai mic decât Oracle (0.4720 vs. 0.4888).
- Brier Score mai slab (0.6747 vs. 0.6150).
- Log Loss mai slab (1.1531 vs. 1.0257).
- Calibrare vizibil mai proastă — supraîncredere sistematică pe zona de încredere mare, exact zona unde deciziile de pariere ar conta cel mai mult.

Nu există niciun criteriu din cele patru (accuracy, Brier, log-loss, calibrare) pe care ML să depășească Oracle pe eșantionul testat. O activare a ML ca sursă principală ar contrazice regula North Star #2 ("promovarea unui model cere dovadă statistică simultană pe metrici multiple") — aici dovada arată exact opusul, simultan pe toate metricile.

Această concluzie e despre ML **așa cum există azi** (fără persistență de artefact reală, fără calibrare post-hoc) — nu e o concluzie permanentă despre familia de algoritm. Dacă 3.1 și 3.2 sunt rezolvate, benchmark-ul ar trebui refăcut înainte de a reconsidera această întrebare.

## 5. Blend aduce valoare?

**Verdict: Candidat plauzibil pentru testare graduală, nu pentru activare directă.**

Argumentare, exclusiv din Etapa 3:
- Accuracy ușor mai bun decât Oracle pur (0.4920 vs. 0.4888, +0.32pp).
- Brier Score și Log Loss practic identice cu Oracle pur (diferență ≤0.0001) — Blend nu pierde nimic măsurabil pe cele două metrici probabilistice.
- Calibrarea Blend-ului rămâne bună (gap de doar 2.6pp pe bin-ul de încredere mare, față de 24.3pp la ML pur) — pentru că `ml_weight=0.35` combinat cu `sample_factor` din `blend_predictions()` diluează suficient supraîncrederea ML.

Dar (explicit, din secțiunea de limitări a Etapei 3):
- Diferența de 0.32pp accuracy și ≤0.0001 pe Brier/log-loss e prea mică pentru a fi declarată semnificativă statistic fără un test dedicat — a fost raportată ca observație descriptivă, nu ca dovadă tare.
- Un singur `ml_weight` (0.35) a fost testat — nu s-a făcut o baleiere.
- Benchmark-ul a rulat o singură dată, pe un eșantion de 1500 rânduri dintr-o fereastră de 8 luni — nu multiple cicluri, nu multiple semințe.

**Recomandare**: Blend-ul e singura direcție din acest EPIC cu o dovadă (chiar dacă mică) în favoarea sa. Testarea lui trebuie să treacă prin infrastructura de shadow testing deja existentă (`shadow_testing.py`), NU printr-o activare directă a `ml_blending_enabled` în producție — consecvent cu North Star #1 ("shadow rămâne shadow până e dovedit, niciodată invers").

## 6. Ordinea exactă de implementare

### 6.1 Cadru de prioritizare

Ordinea de mai jos nu e implicită sau arbitrară — e derivată explicit din trei criterii, aplicate în această prioritate:

1. **Dependență tehnică reală** — dacă pasul B nu poate fi validat corect fără rezultatul pasului A, A vine obligatoriu înainte, indiferent de impact sau risc. Asta guvernează integral secvența ML (pașii 6-10, vezi §6.3).
2. **Risc de regresie asupra predicției live** — pentru pași fără dependență tehnică între ei (grupul Oracle, §6.2), cei care NU schimbă output-ul de predicție (doc, cod mort, redenumiri) trec înaintea celui care chiar schimbă output-ul (§2.1). Motivul: pipeline-ul de validare (Predictor Regression Suite + rulare funcțională) trebuie exercitat pe schimbări sigure înainte de a fi singurul filtru pentru o schimbare cu risc real — și orice diferență găsită la validarea schimbării riscante rămâne izolată, nu amestecată cu zgomotul altor modificări simultane.
3. **Impact** (magnitudinea problemei corectate, din audituri) — folosit ca justificare a lui DE CE un pas merită făcut, nu ca literă de ordonare între pași independenți; pentru pașii dependenți (ML), impactul explică de ce pasul 6 e cel cu cea mai mare pârghie din tot planul (vezi §6.3), nu doar primul din listă.

Fiecare pas se validează prin Predictor Regression Suite (EPIC anterior, Punctul 2) imediat după implementare, înainte de a trece la următorul.

### 6.2 Oracle (independenți între ei) — ordonați risc-ascendent

| # | Pas | Impact | Risc de regresie | Justificare poziție | Necesită ADR? |
|---|---|---|---|---|---|
| 1 | Documentare inerție ponderi per-ligă (§2.4) | Scăzut (nu schimbă nimic, previne redescoperire ca "bug") | Zero — doc, zero cod atins | Primul: zero risc, zero cod, elimină un gol de trasabilitate deja confirmat | Nu |
| 2 | Corectare docstring impact accidentări 0.20→0.25 (§2.3) | Foarte scăzut (elimină o discrepanță documentată, nu schimbă valoarea reală folosită) | Zero — doc, zero cod funcțional atins | Al doilea: aceeași categorie ca #1 (doc-only) | Nu |
| 3 | Eliminare cod mort `injury_manager.py` (§2.5) | Scăzut (reduce suprafața de citit/întreținut, zero efect funcțional) | Foarte scăzut — verificat exhaustiv fără apelanți; se re-verifică o dată în plus chiar înainte de ștergere | Al treilea: singurul risc rezidual e "ceva s-a schimbat între audit și execuție", mitigat prin re-verificare, nu prin schimbare de comportament | Nu |
| 4 | Redenumire `dna_weight` → `base_weight` (§2.2) | Scăzut (claritate, previne o confuzie concretă relevantă chiar pentru acest EPIC — vezi §2.2) | Scăzut — atinge semnătura unei funcții din calea de predicție live, dar fără schimbare de valoare/comportament | Al patrulea: primul pas care ATINGE fișierul `feature_engine.py` de pe calea live, deci trece prin validare funcțională completă, dar fără risc de schimbare de rezultat | Nu |
| 5 | Fix dublă numărare `avg_goals_for` (§2.1) | **Ridicat** — bug confirmat, afectează sistematic `off_stat` la fiecare predicție, cu o pondere invizibilă din config | **Mediu** — singurul pas din grup care schimbă efectiv rezultatul predicției | Ultimul, deliberat: e singura schimbare reală de comportament din grupul Oracle — plasată ultima ca să primească validare (regresie + rulare funcțională pe fixture-uri cunoscute) neamestecată cu alte modificări simultane, și ca să beneficieze de un pipeline deja "încălzit" pe pașii 1-4 | Nu (fix de bug într-o formulă existentă, nu schimbare de contract) |

Pașii 1-5 sunt independenți de secvența ML (§6.3) și pot rula în paralel cu ea — nu există nicio dependență tehnică între cele două grupuri. În interiorul grupului, ordinea 1→5 e recomandată (risc ascendent), dar nu strict obligatorie ca ML — dacă proprietarul produsului preferă să înceapă direct cu #5 (impactul cel mai mare), nu există un blocaj tehnic, doar un compromis asumat: pipeline-ul de validare nu va fi fost "încălzit" în avans pe schimbări sigure.

### 6.3 ML (strict secvențiali — dependență tehnică, nu preferință)

| # | Pas | Impact | Risc | Depinde de | Necesită ADR? |
|---|---|---|---|---|---|
| 6 | Wire `save_model_artifact()` la finalul antrenării + verificare `champion_loader` (§3.1) | **Cel mai mare din tot planul** — fără el, "campion persistat" nu există deloc; blochează logic pașii 7, 9, 10 și rezolvă automat §3.5 (versionare) | Ridicat — schimbă contractul Training Runner ↔ Champion Manager, scrie schemă/contract Supabase | — | **Da** |
| 7 | Calibrare post-hoc probabilități ML (isotonic/Platt) (§3.2) | Ridicat — corectează supraîncrederea confirmată empiric în Etapa 3 (gap de 24.3pp pe bin-ul de încredere mare) | Mediu — schimbare de algoritm, nu doar hiperparametru | Pasul 6 — calibrarea trebuie aplicată pe modelul care va fi cu adevărat servit (persistat), nu pe unul efemer, altfel calibrarea măsurată nu corespunde modelului din producție | Da |
| 8 | Re-rulare benchmark Etapa 3, cu ML persistat + calibrat | Mediu — e poarta de decizie pentru pasul 9, nu o schimbare de sistem | Zero — analiză, fără atingere de cod de producție | Pașii 6, 7 | Nu |
| 9 | Dacă pasul 8 confirmă/îmbunătățește rezultatul Blend: activare Blend în **shadow testing** (nu producție) | Mediu — testează ipoteza din Etapa 3 (§5) în condiții reale, nu simulate | Redus — shadow, nu servire live (North Star #1) | Pasul 8 — fără o re-confirmare a rezultatului pe modelul real (persistat + calibrat), activarea shadow ar testa o ipoteză deja învechită | Da — flag nou, implicit `False` (North Star #3) |
| 10 | Evaluare shadow pe fereastră suficientă → decizie de promovare (om în buclă) | — (proces, nu schimbare de sistem) | Zero — promovarea rămâne manuală, exact ca azi | Pasul 9 | Nu |

Motivul pentru care pasul 6 e primul din acest grup nu e poziția lui în listă, ci pârghia lui: e singurul pas din întregul EPIC care e simultan cel mai riscant (schimbare de contract, ADR obligatoriu) ȘI cel mai cu impact (fără el, pașii 7/9/10 nu au pe ce să se sprijine — orice calibrare sau testare de Blend înainte de pasul 6 ar produce rezultate despre un model efemer, nereprezentativ pentru ce ar fi cu adevărat servit). Aici dependența tehnică precede orice preferință de ordonare pe risc — spre deosebire de grupul Oracle, unde pașii sunt cu adevărat independenți.

---

## 7. Reguli de guvernanță aplicabile pe parcursul implementării

- Niciun pas din secțiunea 6 nu se implementează fără aprobarea explicită, per-pas, a proprietarului produsului — acest document e o propunere de ordine, nu o autorizație de execuție.
- Pașii marcați "Necesită ADR" nu încep implementarea înainte ca ADR-ul respectiv să fie scris și aprobat (disciplina ADR, CLAUDE.md).
- Pasul 9 (activare Blend în shadow) rămâne shadow până dovedit — nicio activare directă în calea de servire live (North Star #1), și flag-ul implicit rămâne `False` la introducere (North Star #3).
- Fiecare pas de cod (1, 2, 4, 6, 7, 9) se validează atât prin `pytest tests/` (rămâne verde), cât și prin rulare funcțională reală pe fixture-uri cunoscute (regula CLAUDE.md pentru schimbări în calea de predicție).
- Pasul 6 implică o scriere de schemă/contract cu Supabase producție (`Prediction`) — orice migrare trece prin verificarea `supabase-safety` (SQL exact arătat înainte de execuție), fără excepție.

---

## 8. Explicit în afara scopului acestui plan

- **ROI** — rămâne un gol de date real (join `match_history`↔`odds_history`), netratat aici; e o precondiție separată pentru orice decizie bazată pe profitabilitate, nu pe acuratețe statistică.
- **Activarea `auto_recalibration_enabled`** (ponderi per-ligă) — menționată doar ca observație de documentat (§2.4), nu ca acțiune de acest EPIC.
- **Activarea Champion Guardian / concept drift monitoring** — condiționată logic de rezolvarea §3.1, nu un pas independent al acestui plan.
- **Activarea rollback-ului în producție (ADR-037 R4)** — are deja propriul plan de deployment separat, nu duplicat aici.
- **Baleiere (sweep) pe `ml_weight`** — menționată ca limitare a benchmark-ului (Etapa 3), nu inclusă ca pas obligatoriu în secvența de mai sus; poate fi propusă separat dacă pasul 9 arată rezultate promițătoare.

---

## 9. Rezumat pentru aprobare

Acest plan propune 10 pași, ordonați și cu dependențe explicite, dintre care primii 5 (Oracle) sunt fix-uri mici, cu risc redus, independente de decizia ML. Pașii 6-10 (ML/Blend) sunt strict secvențiali și încep cu rezolvarea unui gol critic (persistența modelului), nu cu activarea directă a niciunui mecanism. Nimic din acest plan nu implică activarea ML sau Blend în producție fără trecerea prin shadow testing și aprobare explicită, per pas.
