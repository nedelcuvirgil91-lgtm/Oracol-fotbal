# ML Activation Implementation Plan (EPIC "ML Activation & Oracle Evolution", Etapa 4)

**Status**: Plan aprobat (APPROVED WITH CHANGES, Architecture Review 2026-08-03) — actualizat cu observațiile obligatorii ale review-ului. Niciun cod de producție nu a fost modificat, niciun flag activat.
**Data**: 2026-08-03 (revizuit 2026-08-03, post Architecture Review)
**Precondiții**: `docs/00_GOVERNANCE/ORACLE_ENGINE_AUDIT.md` (Etapa 1), `docs/00_GOVERNANCE/ML_ENGINE_AUDIT.md` (Etapa 2), `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md` (Etapa 3) — toate completate și aprobate ca precondiție pentru acest document. Acest plan nu introduce nicio informație nouă, brută — sintetizează exclusiv concluziile deja stabilite în cele trei rapoarte, plus corecțiile cerute explicit de Architecture Review (marcate „adăugat/actualizat din Architecture Review" la fiecare punct atins).

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

### 2.6 Verificare `h2h_lookback_days` — cod mort suspect, neconfirmat (adăugat din Architecture Review)

Oracle Engine Audit (§7) marchează `h2h_lookback_days` (din `DEFAULT_CONFIG`) drept „suspect" de cod mort — nefolosit direct în cascada DB curentă a H2H, dar **NU confirmat 100%** (posibil citit undeva în Sync Layer, neverificat exhaustiv). Acest punct fusese semnalat de audit, dar lipsea din versiunea inițială a planului — completare cerută de Architecture Review.

**Recomandare**: pas investigativ, separat de orice eliminare — grep exhaustiv pe `h2h_lookback_days` în tot repo-ul (inclusiv `sync/`), înainte de orice decizie. Dacă neapelat confirmat: se adaugă la lista de cod mort (§2.5, extensie). Dacă apelat: se documentează rolul real. Zero risc — pas de citire, nu de scriere.

**Rezultat (executat 2026-08-03, Pasul 4)**: **confirmat cod mort, 100%, și eliminat în același pas**. Grep exhaustiv pe tot repo (`.py`, inclusiv `sync/`) — singurele apariții: definiția din `DEFAULT_CONFIG` (`oracle_engine.py:140`) și `tests/test_oracle_engine_compat.py:18` (test de regresie pe forma dict-ului `DEFAULT_CONFIG`, nu citire funcțională). Verificat integral, linie cu linie, `_build_h2h()`/`_h2h_record_from_history_rows()` (toate cele 3 cascade — DB/`match_history`, FreeLF, Odds API): niciuna nu citea `h2h_lookback_days`, doar `h2h_weight`. Actualizat `ORACLE_ENGINE_AUDIT.md` §7 cu concluzia finală.

**Decizie de proces (cerută explicit de proprietarul produsului, 2026-08-03)**: un pas nu se consideră închis doar pentru că demonstrează o problemă — se închide când problema e rezolvată complet, dacă rezolvarea e sigură și în scopul pasului. Aplicat aici: Pasul 4 nu s-a oprit la "confirmat, dar neeliminat" — cheia a fost scoasă din `DEFAULT_CONFIG` și din testul de regresie asociat, în același pas, imediat după confirmare. Această regulă se aplică de acum tuturor pașilor rămași din EPIC.

### 2.7 Suprapunerea ferestrei de date formă/goluri — documentare, fără acțiune de cod (adăugat din Architecture Review)

Oracle Engine Audit (§6.3) semnalează explicit că `form_score` și `avg_goals_for`/`avg_goals_against` provin din ACEEAȘI fereastră de `last_n_fixtures` (5 meciuri) — nu o duplicare de informație, dar o limitare reală a diversității semnalului de intrare, marcată explicit de audit drept „relevant pentru Etapa 4". Acest punct fusese omis din versiunea inițială a planului — completare cerută de Architecture Review.

**Recomandare**: nu se propune nicio schimbare de cod în acest EPIC — o eventuală extindere a `last_n_fixtures` sau diversificarea surselor de semnal ar fi o schimbare de comportament separată, care ar necesita propriul test de ablație (consecvent cu regula ML a proiectului), nu o decizie luată tacit aici. Se documentează explicit ca observație cunoscută, ca să nu fie redescoperită ca „gol" într-o sesiune viitoare.

### 2.8 Ce NU se modifică din Etapa 1

- `rest_days_modifier` rămâne neapelat, deliberat — deja validat printr-un test de ablație real (`REST_DAYS_VALIDATION.md`), nicio acțiune necesară.
- Regula de penalizare a vremii (weather penalty, egală pe ambele echipe) — nu a fost identificată ca bug, doar documentată ca regulă hardcodată; nu există dovadă că ar trebui schimbată.
- Cascada de aplicare a penalizării de accidentări ca pas separat, după `calibrate_xg` — arhitectural corect (injury e per-echipă, post-xG), nu un defect.

---

## 3. Ce trebuie modificat în ML Engine

Sursă: `ML_ENGINE_AUDIT.md` (persistență §7, concept drift §8, versionare §9, rollback §10, promovare §11) și `ORACLE_VS_ML_REPORT.md` — Etapa 3 (supraîncredere/calibrare §3.2, confirmată empiric, nu doar teoretizată în audit). **Corectare din Architecture Review**: versiunea inițială a acestei secțiuni atribuia greșit constatarea de calibrare (§3.2 de mai jos) exclusiv lui `ML_ENGINE_AUDIT.md`, care nu conține o secțiune de calibrare — sursa corectă e benchmark-ul din Etapa 3.

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

### 3.6 Promovare — corect, fără acțiune de cod necesară

Promovarea Champion/Challenger e strict om-în-buclă (`auto_promotion_enabled` nu există în cod ca opțiune reală) — consecvent cu ADR-002 și cu North Star #2/#3. Nicio schimbare de comportament recomandată — pentru discrepanța de documentație asociată, vezi §3.7 (adăugat mai jos, cerut explicit de audit dar omis din versiunea inițială a planului).

### 3.7 Curățare documentație — `ARCHITECTURE_STATE.md` și `auto_promotion_enabled` (adăugat din Architecture Review)

Două discrepanțe de documentație semnalate explicit de `ML_ENGINE_AUDIT.md` dar omise din versiunea inițială a acestui plan:

- `ARCHITECTURE_STATE.md` menține o secțiune depășită despre cron-ul propriu al `continuous_learning.yml` (`0 6 * * *`), consolidat de fapt în `night_sync.yml` (ML Audit §3).
- `auto_promotion_enabled` e menționat în mai multe documente de guvernanță (CLAUDE.md, `LEARNING_CORE_ARCHITECTURE.md`) ca un flag existent, dar nu există ca opțiune citită de niciun cod (ML Audit §11, §13 pct. 4) — auditul cere explicit rezolvare într-un sens sau altul, nu tăcere.

**Recomandare**: pentru `ARCHITECTURE_STATE.md`, corectare directă a secțiunii de cron, ca să reflecte starea reală de cod. Pentru `auto_promotion_enabled`: **eliminare din documentație, NU implementare** — implementarea ar contrazice direct ADR-002 (promovare cu om în buclă, obligatorie) și regulile Champion/Challenger din CLAUDE.md; varianta „elimină din documentație" e singura consecventă cu restul planului (§3.6, §4). Ambele: doc-only, risc zero, fără atingere de cod funcțional.

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

**Notă de reconciliere (adăugată din Architecture Review)**: cifra de accuracy=0.4720 folosită mai sus (Etapa 3, walk-forward, 1250 rânduri held-out din ultimele 8 luni, 2025-11-28→2026-07-31) NU trebuie confundată cu accuracy=0.4843 raportată de `ML_ENGINE_AUDIT.md` §0 pentru ultima rulare de producție (`ml_model_status`, antrenată pe întreg `match_history` disponibil, ~49.981 eșantioane). Sunt două măsurători diferite, pe eșantioane și metodologii diferite (retrain complet pe tot istoricul, fără held-out dedicat, vs. walk-forward held-out strict pe un subset recent) — nu o inconsistență între documente. Pentru orice decizie de activare, cifra relevantă e cea din Etapa 3 (0.4720), pentru că e singura măsurată corect held-out, fără scurgere temporală față de eșantionul evaluat.

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

1. **Dependență tehnică reală** — dacă pasul B nu poate fi validat corect fără rezultatul pasului A, A vine obligatoriu înainte, indiferent de impact sau risc. Asta guvernează integral secvența ML (pașii 9-14, vezi §6.3).
2. **Risc de regresie asupra predicției live** — pentru pași fără dependență tehnică între ei (grupul Oracle, §6.2), cei care NU schimbă output-ul de predicție (doc, cod mort, redenumiri) trec înaintea celui care chiar schimbă output-ul (§2.1). Motivul: pipeline-ul de validare (Predictor Regression Suite + rulare funcțională) trebuie exercitat pe schimbări sigure înainte de a fi singurul filtru pentru o schimbare cu risc real — și orice diferență găsită la validarea schimbării riscante rămâne izolată, nu amestecată cu zgomotul altor modificări simultane.
3. **Impact** (magnitudinea problemei corectate, din audituri) — folosit ca justificare a lui DE CE un pas merită făcut, nu ca literă de ordonare între pași independenți; pentru pașii dependenți (ML), impactul explică de ce pasul 9 e cel cu cea mai mare pârghie din tot planul (vezi §6.3), nu doar primul din listă.

Fiecare pas se validează prin Predictor Regression Suite (EPIC anterior, Punctul 2) imediat după implementare, înainte de a trece la următorul. **Actualizare (Architecture Review)**: pentru pașii marcați explicit mai jos, validarea minimă (regresie + fixture-uri cunoscute) nu e suficientă — se cere fie un backtest agregat (pasul 8), fie un test de semnificație statistică (pasul 13), fie o verificare de capacitate a infrastructurii existente înainte de activare (pasul 12). Numerotarea de mai jos înlocuiește integral versiunea inițială (10 pași) — s-au adăugat 3 pași noi în grupul Oracle (4, 5, 6) și 1 pas nou în grupul ML (12), plus 2 reclasificări (pasul 7 necesită acum ADR; pașii 8 și 13 au cerințe de validare extinse).

### 6.2 Oracle (independenți între ei) — ordonați risc-ascendent

| # | Pas | Impact | Risc de regresie | Justificare poziție | Necesită ADR? |
|---|---|---|---|---|---|
| 1 | Documentare inerție ponderi per-ligă (§2.4) | Scăzut (nu schimbă nimic, previne redescoperire ca "bug") | Zero — doc, zero cod atins | Primul: zero risc, zero cod, elimină un gol de trasabilitate deja confirmat | Nu |
| 2 | Corectare docstring impact accidentări 0.20→0.25 (§2.3) | Foarte scăzut (elimină o discrepanță documentată, nu schimbă valoarea reală folosită) | Zero — doc, zero cod funcțional atins | Al doilea: aceeași categorie ca #1 (doc-only) | Nu |
| 3 | Eliminare cod mort `injury_manager.py` (§2.5) | Scăzut (reduce suprafața de citit/întreținut, zero efect funcțional) | Foarte scăzut — verificat exhaustiv fără apelanți; se re-verifică o dată în plus chiar înainte de ștergere | Al treilea: singurul risc rezidual e "ceva s-a schimbat între audit și execuție", mitigat prin re-verificare, nu prin schimbare de comportament | Nu |
| 4 | **(nou)** Verificare `h2h_lookback_days` (§2.6) | Scăzut — clarifică un cod mort suspect, neconfirmat | Zero — doar grep/citire, nicio scriere | Al patrulea: extensie firească a pasului 3 (tot verificare de cod mort), pregătește o decizie ulterioară fără s-o forța acum | Nu |
| 5 | **(nou)** Curățare documentație `ARCHITECTURE_STATE.md` + `auto_promotion_enabled` (§3.7) | Scăzut — elimină două surse de confuzie deja documentate | Zero — doc-only | Al cincilea: aceeași categorie doc-only ca 1-2, grupat aici pentru a epuiza toate fix-urile de documentație înainte de a atinge cod funcțional | Nu |
| 6 | **(nou)** Documentare suprapunere fereastră formă/goluri (§2.7) | Scăzut — previne redescoperire ca "gol" | Zero — doc-only | Al șaselea: ultimul pas pur documentar, închide seria fără risc înainte de pașii care ating efectiv formula | Nu |
| 7 | Redenumire `dna_weight` → `base_weight` (§2.2) | Scăzut (claritate) — dar atinge o cheie de configurare **persistată** (`weights.json`/`model_weights` Supabase, inclusiv valorile per-ligă din §4.3 Oracle Audit), nu doar un nume de parametru local | Scăzut-Mediu — fără schimbare de valoare/comportament, dar schimbă o cheie dintr-un contract de date stocat | Al șaptelea: primul pas care atinge efectiv un **contract de date**, deci trece prin ADR înainte de execuție, chiar dacă riscul funcțional e redus | **Da — reclasificat (Architecture Review)**: versiunea inițială marca acest pas "Nu"; `dna_weight` e o cheie din `DEFAULT_WEIGHTS`/`model_weights`, nu un detaliu intern de implementare — redenumirea ei e o schimbare de contract de date (North Star #5), consecvent cu opțiunea pe care chiar Oracle Engine Audit §9 pct. 3 o ridicase |
| 8 | Fix dublă numărare `avg_goals_for` (§2.1) | **Ridicat** — bug confirmat, afectează sistematic `off_stat` la fiecare predicție, cu o pondere invizibilă din config | **Mediu** — singurul pas din grup care schimbă efectiv rezultatul predicției | Ultimul, deliberat — vezi §6.1. **Validare extinsă (Architecture Review)**: Predictor Regression Suite + fixture-uri cunoscute NU sunt suficiente aici — termenul eliminat a influențat probabil sistematic predicțiile pe o perioadă lungă, nu doar cazuri izolate; se cere și un **backtest agregat de tip Etapa 3** (Oracle-only, aceleași metrici — accuracy/Brier/log-loss/calibrare —, înainte vs. după fix, pe același eșantion walk-forward), consecvent cu disciplina de ablație pe care proiectul o cere deja pentru ML | Nu (fix de bug într-o formulă existentă, nu schimbare de contract) |

Pașii 1-8 sunt independenți de secvența ML (§6.3) și pot rula în paralel cu ea — nu există nicio dependență tehnică între cele două grupuri. În interiorul grupului, ordinea 1→8 e recomandată (risc ascendent), dar nu strict obligatorie — dacă proprietarul produsului preferă să înceapă direct cu #8 (impactul cel mai mare), nu există un blocaj tehnic, doar un compromis asumat: pipeline-ul de validare nu va fi fost "încălzit" în avans pe schimbări sigure, iar pasul 7 rămâne oricum blocat de aprobarea propriului ADR indiferent de poziția din listă.

### 6.3 ML (strict secvențiali — dependență tehnică, nu preferință)

| # | Pas | Impact | Risc | Depinde de | Necesită ADR? |
|---|---|---|---|---|---|
| 9 | Wire `save_model_artifact()` la finalul antrenării + verificare `champion_loader` (§3.1) | **Cel mai mare din tot planul** — fără el, "campion persistat" nu există deloc; blochează logic pașii 10, 12, 13, 14 și rezolvă automat §3.5 (versionare) | Ridicat — schimbă contractul Training Runner ↔ Champion Manager, scrie schemă/contract Supabase | — | **Da** — ADR-ul trebuie să clarifice explicit **scopul** (Architecture Review): dacă persistența acoperă doar calea Champion (încărcare la boot), sau și artefactele intermediare de Challenger pe durata evaluării FSM (`WAITING→EVALUATING`, care per ML Audit §11 se poate întinde pe mai multe cicluri nocturne) — niciunul din cele 3 audituri nu explică azi cum funcționează evaluarea unui Challenger de-a lungul mai multor zile fără artefact persistat; întrebarea rămâne deschisă și trebuie răspunsă de ADR, nu presupusă în implementare |
| 10 | Calibrare post-hoc probabilități ML (isotonic/Platt) (§3.2) | Ridicat — corectează supraîncrederea confirmată empiric în Etapa 3 (gap de 24.3pp pe bin-ul de încredere mare) | Mediu — schimbare de algoritm, nu doar hiperparametru | Pasul 9 — calibrarea trebuie aplicată pe modelul care va fi cu adevărat servit (persistat), nu pe unul efemer, altfel calibrarea măsurată nu corespunde modelului din producție | Da |
| 11 | Re-rulare benchmark Etapa 3, cu ML persistat + calibrat | Mediu — e poarta de decizie pentru pasul 13, nu o schimbare de sistem | Zero — analiză, fără atingere de cod de producție | Pașii 9, 10 | Nu |
| 12 | **(nou)** Verificare capacitate `shadow_testing.py` pentru o ipoteză de Blend cu pondere variabilă (nu doar swap complet de model) | Mic, dar **blocant** pentru pasul 14 dacă infrastructura nu suportă azi testarea unei ponderi de Blend — niciunul din cele 3 audituri n-a confirmat asta | Zero — verificare de cod existent, nicio scriere | Pasul 11 — rulează după poarta de decizie, nu înainte, ca să nu se investească timp de verificare pe o cale posibil respinsă deja la pasul 11 | Nu |
| 13 | **(actualizat)** Dacă pasul 11 confirmă/îmbunătățește rezultatul Blend **ȘI** pasul 12 confirmă capacitatea infrastructurii: activare Blend în **shadow testing** (nu producție) | Mediu — testează ipoteza din Etapa 3 (§5) în condiții reale, nu simulate | Redus — shadow, nu servire live (North Star #1) | Pașii 11, 12 — **validare extinsă (Architecture Review)**: decizia de la pasul 11 trebuie să includă un test de semnificație statistică pe diferența de metrici Oracle vs. Blend, nu doar comparația descriptivă din Etapa 3 (care își documentează singură această limitare, §6 din `ORACLE_VS_ML_REPORT.md`) — altfel poarta de decizie repetă exact golul deja semnalat | Da — flag nou, implicit `False` (North Star #3) |
| 14 | Evaluare shadow pe fereastră suficientă → decizie de promovare (om în buclă) | — (proces, nu schimbare de sistem) | Zero — promovarea rămâne manuală, exact ca azi | Pasul 13 | Nu |

Motivul pentru care pasul 9 e primul din acest grup nu e poziția lui în listă, ci pârghia lui: e singurul pas din întregul EPIC care e simultan cel mai riscant (schimbare de contract, ADR obligatoriu) ȘI cel mai cu impact (fără el, pașii 10/12/13/14 nu au pe ce să se sprijine — orice calibrare sau testare de Blend înainte de pasul 9 ar produce rezultate despre un model efemer, nereprezentativ pentru ce ar fi cu adevărat servit). Aici dependența tehnică precede orice preferință de ordonare pe risc — spre deosebire de grupul Oracle, unde pașii sunt cu adevărat independenți.

---

## 7. Reguli de guvernanță aplicabile pe parcursul implementării

- Niciun pas din secțiunea 6 nu se implementează fără aprobarea explicită, per-pas, a proprietarului produsului — acest document e o propunere de ordine, nu o autorizație de execuție.
- Pașii marcați "Necesită ADR" (7, 9, 10, 13) nu încep implementarea înainte ca ADR-ul respectiv să fie scris și aprobat (disciplina ADR, CLAUDE.md).
- Pasul 13 (activare Blend în shadow) rămâne shadow până dovedit — nicio activare directă în calea de servire live (North Star #1), și flag-ul implicit rămâne `False` la introducere (North Star #3).
- Fiecare pas cu efect funcțional real asupra codului (3, 7, 8, 9, 10, 13) se validează atât prin `pytest tests/` (rămâne verde), cât și prin rulare funcțională reală pe fixture-uri cunoscute (regula CLAUDE.md pentru schimbări în calea de predicție); pașii 1, 2, 5, 6 sunt doc-only, iar pașii 4, 12 sunt verificări de cod existent (grep/citire), fără scriere.
- Pasul 8 (fix `avg_goals_for`) și pasul 13 (activare Blend shadow) au, suplimentar, cerințe de validare extinse (backtest agregat, respectiv test de semnificație statistică) — vezi §6.2/§6.3, adăugate din Architecture Review.
- Pasul 9 implică o scriere de schemă/contract cu Supabase producție (`Prediction`) — orice migrare trece prin verificarea `supabase-safety` (SQL exact arătat înainte de execuție), fără excepție.
- **Definiția „task terminat"** (formalizată explicit, 2026-08-03, cerută de proprietarul produsului — se aplică tuturor pașilor rămași din acest EPIC): un pas NU e considerat terminat până când, în ordine: (1) implementarea e completă; (2) regresiile sunt verzi (`pytest tests/`, plus verificare funcțională unde se aplică); (3) review-ul e prezentat și aprobat explicit; (4) commit-ul e făcut; (5) merge în `main` e realizat; (6) `ARCHITECTURE_STATE.md` e actualizat cu noul SHA. Abia după toate cele șase se trece la pasul următor — niciun pas nu se consideră „practic gata" doar pentru că a demonstrat sau a implementat o problemă, dacă oricare din cele șase verigi lipsește.
- **Scop restrâns cerut proactiv** (regulă de proces, cerută explicit de proprietarul produsului, 2026-08-03): dacă în timpul unui task se descoperă că scopul planificat inițial e prea larg sau ar putea produce efecte secundare nedorite, sesiunea se oprește și propune restrângerea scopului înainte de a modifica fișiere — nu execută mecanic planul așa cum a fost scris inițial (precedent: Pasul 5, restrângerea scopului `auto_promotion_enabled` doar la CLAUDE.md, fără atingerea ADR-urilor/documentelor Frozen/roadmap-urilor).

---

## 8. Explicit în afara scopului acestui plan

- **ROI** — rămâne un gol de date real (join `match_history`↔`odds_history`), netratat aici; e o precondiție separată pentru orice decizie bazată pe profitabilitate, nu pe acuratețe statistică.
- **Activarea `auto_recalibration_enabled`** (ponderi per-ligă) — menționată doar ca observație de documentat (§2.4), nu ca acțiune de acest EPIC.
- **Activarea Champion Guardian / concept drift monitoring** — condiționată logic de rezolvarea §3.1, nu un pas independent al acestui plan.
- **Activarea rollback-ului în producție (ADR-037 R4)** — are deja propriul plan de deployment separat, nu duplicat aici.
- **Baleiere (sweep) pe `ml_weight`** — menționată ca limitare a benchmark-ului (Etapa 3), nu inclusă ca pas obligatoriu în secvența de mai sus; poate fi propusă separat dacă pasul 13 arată rezultate promițătoare.

---

## 9. Rezumat pentru aprobare

Acest plan propune **14 pași** (actualizat post Architecture Review — inițial 10), ordonați și cu dependențe explicite. Primii 8 (Oracle, §6.2) sunt independenți de decizia ML: 6 sunt fix-uri/verificări/documentări cu risc zero-spre-scăzut (inclusiv 3 pași noi adăugați din review — verificarea `h2h_lookback_days`, curățarea documentației `ARCHITECTURE_STATE.md`/`auto_promotion_enabled`, documentarea suprapunerii ferestrei formă/goluri), 1 (redenumirea `dna_weight`) a fost reclasificat ca necesitând ADR, iar ultimul (fix-ul `avg_goals_for`) primește acum o cerință explicită de backtest agregat, nu doar validare pe fixture-uri. Pașii 9-14 (ML/Blend, §6.3) rămân strict secvențiali, încep cu rezolvarea golului critic de persistență (cu scopul Champion-vs-Challenger clarificat explicit prin ADR), includ un pas nou de verificare a capacității infrastructurii de shadow testing pentru Blend, și cer un test de semnificație statistică înainte de poarta de decizie spre activarea shadow. Nimic din acest plan nu implică activarea ML sau Blend în producție fără trecerea prin shadow testing și aprobare explicită, per pas.

**Status Architecture Review**: toate observațiile obligatorii din review (2026-08-03) au fost aplicate direct în acest document — vezi marcajele „adăugat/actualizat din Architecture Review" la §2.6, §2.7, §3.7, §4 (notă de reconciliere), §6.2 (pașii 4-6 noi, pasul 7 reclasificat, pasul 8 extins), §6.3 (pasul 9 cu scop clarificat, pasul 12 nou, pasul 13 extins), §7. Faza de analiză a EPIC-ului „ML Activation & Oracle Evolution" se consideră închisă — implementarea urmează etapizat, pas cu pas, conform ordinii din §6.2/§6.3.
