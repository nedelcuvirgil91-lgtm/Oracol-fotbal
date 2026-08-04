# Pasul 11 — Implementation Plan (Validare experimentală: re-rulare benchmark după ADR-049)

**Tip**: plan de validare experimentală, NU de arhitectură. Nu decide un ADR, nu propune un contract nou — răspunde exclusiv la întrebarea „calibrarea introdusă de ADR-049 (Pasul 10a/10b) îmbunătățește măsurabil calitatea probabilităților ML, în aceleași condiții metodologice ca benchmark-ul original (Etapa 3, `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md`)?"

**Precondiție**: ADR-049 complet implementat și integrat pe `main` (Pasul 10a @ `cd5d45e`, Pasul 10b @ `82ac2ff`) — confirmat.

**Out of scope (explicit, per cerința proprietarului produsului)**: acest pas **NU**:
- modifică cod de producție (`ml_predictor.py`, `champion_loader.py`, `oracle_engine.py`, `learning_core/*` — toate neatinse);
- introduce niciun ADR nou;
- schimbă niciun hiperparametru (XGBoost, `ml_weight`, praguri de calibrare);
- recalibrează manual niciun model (temperatura folosită e cea produsă deja de `_fit_temperature()`, nu una aleasă ad-hoc pentru acest raport);
- scrie în Supabase (interogări read-only, exact ca Etapa 3 — „Status: Analiză READ-ONLY, completă");
- activează `ml_blending_enabled` sau orice alt flag de producție;
- promovează niciun Challenger.

Rezultatul acestui pas e strict: **măsurare + documentare**.

---

## 1. Ce se re-rulează

### 1.1 Doar componenta afectată de ADR-049, nu întregul benchmark de la zero

Etapa 3 a produs 4 rânduri: Oracle, ML, Blend simulat, Baseline majoritate. Dintre acestea, **doar ML e afectat de ADR-049** — formula Oracle (`feature_engine.calibrate_xg()`/`poisson_model()`) și mecanismul de blend (`blend_predictions()`) nu au fost atinse de Pasul 10a/10b. Re-rularea completă a Oracle/Baseline ar fi muncă irosită — numerele lor nu se pot schimba dacă codul lor nu s-a schimbat, pe același eșantion.

**Decizie propusă**: re-rulare cu 2 straturi, nu unul singur:

- **Comparație primară, controlată (obiectivul central al acestui pas)**: **ML necalibrat vs. ML calibrat**, pe **exact aceleași fold-uri walk-forward, aceleași margini brute** dintr-o singură rulare — nu două rulări separate cu date potențial diferite. Se re-antrenează o singură dată per fold (identic metodologiei Etapa 3 §2.3), se calculează `predict_proba()` (calea necalibrată) ȘI `softmax_with_temperature(margini, T)` (calea calibrată, cu `T` produs de `_fit_temperature()` pe setul OOF al aceleiași rulări) din **aceleași margini brute**. Asta izolează complet efectul calibrării — zero confound din date diferite, zero confound din reantrenare separată. E comparația care răspunde direct la întrebarea Pasului 11.
- **Comparație secundară, contextuală (continuitate cu formatul Etapa 3)**: Oracle, ML calibrat, Blend — **toate 3 recalculate pe același eșantion nou** (§1.2), nu doar ML/Blend. [**REVIZUIT — review**] Deși codul Oracle nu s-a schimbat și numerele lui nu se pot schimba din motive de logică, recalcularea lui pe exact același eșantion ca ML/Blend costă neglijabil (Oracle nu are antrenare, e determinist pe formulă) și produce un tabel unde TOATE valorile provin din același experiment, aceeași fereastră de date — mai ușor de citit, mai greu de contestat decât un tabel care amestecă numere din două eșantioane diferite (Oracle din Etapa 3, ML/Blend din Pasul 11). Recalcularea Oracle NU e o repetare a codului deja verificat — e o garanție de consistență experimentală a raportului.

### 1.2 Dataset și fereastră temporală

**Nu se refolosește dataset-ul fizic exact din Etapa 3** — acele 1500 de rânduri specifice nu au fost salvate ca fixture, doar descrise metodologic (interogare `ORDER BY kickoff_date DESC LIMIT 1500`, filtrare pe feature-uri core ne-nule). Reproducerea EXACTĂ a acelorași 1500 rânduri ar necesite ori un fixture înghețat (nu există), ori o interogare cu fereastră de date fixată explicit (`kickoff_date <= '2026-07-31'`), nu `LIMIT 1500` pe starea curentă a bazei (care s-a schimbat — mai multe meciuri sincronizate între timp).

**Decizie propusă**: se repetă **exact aceeași interogare și aceeași metodologie de filtrare** (§2.1 din Etapa 3 — aceleași coloane core ne-nule, aceleași 1500 rânduri cele mai recente cronologic), rulată pe starea curentă a bazei — nu o fereastră temporală înghețată artificial. Motivul: scopul e „calibrarea ajută în condiții reale, curente", nu „reproduce identic un fixture istoric" — iar diferența dintre fereastra 2025-11-28→2026-07-31 (Etapa 3) și fereastra curentă (~4 zile mai recentă, câteva meciuri în plus) e nesemnificativă pentru concluzie. Comparația primară (§1.1, ML necalibrat vs. calibrat) rămâne oricum controlată perfect — se face pe **aceeași rulare**, deci diferența de fereastră temporală față de Etapa 3 nu afectează validitatea ei internă, doar comparabilitatea directă cu numerele Oracle/Blend deja publicate.

**Notă transparentă, obligatorie în raport** (consecvent cu Etapa 3 §6, „Limitări metodologice"): orice diferență de fereastră temporală față de Etapa 3 se declară explicit în raportul nou, nu se ascunde.

**[ADĂUGAT — review]** Raportul nou trebuie să declare explicit, chiar din rezumatul de pe prima pagină, natura sa exactă: **„Acesta nu este un benchmark de reproducere, ci un benchmark de revalidare"** — formularea exactă cerută la review. Diferența e importantă: un benchmark de reproducere ar pretinde să obțină aceleași numere pe aceleași date; un benchmark de revalidare confirmă (sau infirmă) aceeași concluzie calitativă, pe date curente, cu propria fereastră declarată explicit — nu se pretinde identitate numerică cu Etapa 3.

## 2. Ce reprezintă baseline-ul

Toate 3, nu una singură — cu roluri distincte, explicite:

1. **ML necalibrat vs. ML calibrat** — baseline-ul PRIMAR, cel care răspunde direct la întrebarea Pasului 11 („calibrarea ajută?"). Comparație perechi (paired), aceleași fold-uri, aceleași predicții de bază, doar transformarea finală diferă.
2. **Oracle (recalculat pe același eșantion, §1.1) vs. ML calibrat** — context, nu decizie de înlocuire (consecvent cu viziunea permanentă din `CLAUDE.md`: „Oracle rămâne motorul principal... nu din inerție"). Răspunde la „a recuperat ML din decalajul față de Oracle observat în Etapa 3, sau rămâne departe?" — comparație validă experimental fiindcă ambele numere provin acum din același eșantion, nu din eșantioane diferite (Etapa 3 vs. Pasul 11).
3. **Blend (cu ML calibrat) vs. Blend original (Etapa 3, cu ML necalibrat)** — verifică dacă introducerea calibrării schimbă concluzia deja publicată despre blend („nu strică nimic, câștig marginal de accuracy").

Toate 3 apar **într-un singur raport** (nu 3 documente separate) — tabelul din Etapa 3 §3.1 extins cu o coloană/rând nou, nu înlocuit.

## 3. Metrici decisive (enumerate explicit)

| Metrică | Sursă | Stare în cod |
|---|---|---|
| Accuracy | `sklearn.metrics.accuracy_score` | deja folosită, Etapa 3 |
| Log-loss | `sklearn.metrics.log_loss` | deja folosită, Etapa 3 |
| Brier score (multi-clasă) | `ml_predictor.MLPredictorEngine._multiclass_brier()` | deja folosită, Etapa 3 — reutilizată identic, fără reimplementare |
| Reliability / calibration table (încredere raportată vs. acuratețe reală, pe bin-uri) | metodologia din Etapa 3 §3.2 (binning manual pe intervale de încredere) | deja folosită, Etapa 3 — reprodusă identic pentru ML necalibrat și ML calibrat |
| **ECE (Expected Calibration Error)** | **nou** — nu există azi ca funcție în cod (verificat: niciun `ece`/`expected_calibration_error` în `ml_predictor.py`/`shadow_testing.py`/proiect) | calculat ca sumarul scalar al tabelului de reliability deja produs (medie ponderată cu `n` per bin a `|încredere_medie − acuratețe_reală|``) — formulă standard, calculată STRICT în scriptul de benchmark (efemer, §6), NU adăugată ca funcție nouă în `ml_predictor.py` sau alt fișier de producție. Nu e „cod de producție" în sensul out-of-scope de mai sus — e un artefact de măsurare, la fel ca restul scriptului |
| Timp de inferență (`predict()` calibrat vs. necalibrat) | nou, măsurare | `time.perf_counter()` în jurul apelului `predict()`, mediat pe N apeluri repetate (ex. 200) pe un fixture fix — pur observațional, nu modifică `predict()` |

## 4. Ce constituie succesul (criterii explicite, nu „vedem rezultatele")

Pe comparația PRIMARĂ (§2.1, ML necalibrat vs. calibrat, aceleași fold-uri):

- **Accuracy** — [**REVIZUIT — review**] reformulat pe două niveluri distincte, ca să nu se confunde o proprietate matematică demonstrată cu un rezultat empiric al acestui benchmark specific:
  - **Invariant așteptat** (proprietate matematică, deja demonstrată/testată unitar la Pasul 10a, nu o ipoteză a acestui benchmark): `argmax` e identic pentru aceeași ieșire brută (aceleași margini) — adevărat pentru orice `T>0`, indiferent de benchmark.
  - **Observație de benchmark**: accuracy ar trebui să rămână neschimbată între ML necalibrat și ML calibrat, fiindcă amândouă derivă din **aceleași margini** ale **aceleiași rulări** de antrenare (§1.1 — comparație perechi, nu două rulări separate). Totuși, benchmark-ul nu compară direct două seturi de probabilități dintr-un artefact deja salvat — implică propriul cod de agregare/rotunjire al scriptului. Orice diferență observată **trebuie investigată explicit** în raport (nu ignorată, nu presupusă „zgomot") — dar nu se declară a priori drept „bug" fără verificare, fiindcă sursa unei eventuale diferențe (rotunjire, cale de cod a scriptului) nu e cunoscută dinainte.
- **Log-loss: nu se degradează** — `log_loss(calibrat) <= log_loss(necalibrat)`, cu o marjă de toleranță pentru zgomot de reeșantionare de `+0.005` (calibrarea optimizează direct log-loss pe setul OOF prin construcție, plus garda din `_fit_temperature()` care deja respinge orice `T` ce nu bate strict baseline-ul `T=1.0` pe fold-ul propriu — o regresie pe acest benchmark ar fi neașteptată, dar posibilă dacă fold-urile diferă ușor de cele din antrenarea reală de producție).
- **Brier score: se îmbunătățește sau rămâne stabil** — `brier(calibrat) <= brier(necalibrat) + 0.005` (Brier e un „proper scoring rule" ca și log-loss — Temperature Scaling nu îl optimizează direct, dar istoric îl îmbunătățește când corectează supraîncrederea sistematică).
- **Gap de calibrare pe bin-ul de încredere mare `[0.70, 1.01)`: scade material** — țintă explicită: gap-ul de 24.3pp observat în Etapa 3 pentru ML necalibrat scade la **≤12pp** pentru ML calibrat (jumătate din gap-ul original — prag conservator, nu „la fel de bun ca Oracle" (~6pp), care ar fi o cerință nerealistă pentru un singur scalar de calibrare).
- **Overhead runtime: neglijabil** — sub **10% timp suplimentar** per apel `predict()` față de calea necalibrată (calea calibrată adaugă un singur `predict(..., output_margin=True)` + o funcție softmax pe 3 numere — cost teoretic minim, verificat empiric aici doar ca dovadă, nu ca risc real).

Dacă ORICARE dintre criteriile de mai sus eșuează, raportul documentează explicit eșecul (nu se ascunde, nu se reformulează criteriul post-hoc) — consecvent cu filosofia proiectului „verificat, nu presupus".

Pe comparațiile SECUNDARE (§2, punctele 2-3): raportate descriptiv, fără prag de succes/eșec — sunt context, nu validează sau invalidează Pasul 11 în sine.

## 5. Unde se documentează rezultatele

**Decizie propusă**: document nou, `docs/00_GOVERNANCE/ETAPA3_RERUN_AFTER_ADR049.md` — **nu** se editează `ORACLE_VS_ML_REPORT.md` direct (document nu e Frozen, dar suprascrierea numerelor originale ar distruge trasabilitatea istorică a deciziei deja luate în Etapa 3/Etapa 4). Structură (mirror al Etapa 3, pentru comparabilitate directă):

1. Rezumat pe o pagină (tabel extins cu rândul „ML calibrat").
2. Metodologie — diferențe explicite față de Etapa 3 (§1.2 de mai sus: fereastră de date, dacă diferă).
3. Rezultate detaliate — cele 3 comparații din §2, cu tabelele de reliability pentru ML necalibrat și calibrat una lângă alta.
4. ECE + timp de inferență (metrici noi față de Etapa 3, §3 de mai sus).
5. Verdict pe criteriile de succes din §4 — explicit, punct cu punct, PASS/FAIL, nu prozaic.
6. Legătură cu Etapa 3/4 — dacă vreo concluzie deja publicată (`ORACLE_VS_ML_REPORT.md` §7, „Sumar pentru Etapa 4") se schimbă sau rămâne valabilă.

**[REVIZUIT — review] `ORACLE_VS_ML_REPORT.md` rămâne complet neatins, fără nicio excepție, nici măcar un pointer.** Documentul original descrie exact experimentul original — orice atingere, chiar aditivă, îi schimbă imuabilitatea istorică. Trimiterea către `ETAPA3_RERUN_AFTER_ADR049.md` se face din altă parte: `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` §3.1 (deja actualizată la fiecare pas ADR-049) și, dacă există, indexul documentației de guvernanță — niciodată din interiorul raportului original.

## 6. Tooling — script committed, reutilizabil (§9 review — decizie finală: opțiunea B)

Etapa 3 nu a lăsat în urmă niciun script committed (verificat: `git log`/`find` nu găsesc un fișier de benchmark separat de `prediction_evaluation.py`, care e un instrument DIFERIT — evaluează predicții LIVE deja servite și stocate, nu re-simulează walk-forward; inutilizabil aici fiindcă azi nu există trafic real de producție cu Champion activ, `ARCHITECTURE_STATE.md` §4: `total_predictions=37`, `closed_loop_rows=0`). Metodologia Etapei 3 a fost, aparent, un script rulat o singură dată, nepăstrat în repo.

**[REVIZUIT — review] Decizie: `scripts/rerun_etapa3_benchmark.py`, committed.** Motivarea explicită de la review: benchmark-ul devine parte din procesul de validare al proiectului — reproductibilitatea trebuie să fie `python scripts/rerun_etapa3_benchmark.py`, nu „am avut un script temporar". Nu e cod de producție (niciun modul din `app.py`/`oracle_engine.py`/`sync/*`/`learning_core/*` îl importă sau depinde de el) — e tooling de validare, analog cu `prediction_evaluation.py`, deja committed cu exact acest statut. Implicație pentru §7 (out of scope): scriptul e un fișier NOU, nu o modificare de cod de producție existent — rămâne în limitele „nu modifică cod de producție" din header, dar necesită un commit propriu la finalul Pasului 11 (§7, pasul 9 de mai jos), separat de eventualele actualizări de documentație.

## 7. Ordinea de execuție (după aprobarea acestui plan)

1. Interogare read-only `match_history` (§1.2) — aceleași filtre ca Etapa 3.
2. Walk-forward identic metodologiei Etapa 3 §2.3 — un singur set de fold-uri, margini brute capturate per fold (identic cu `_walk_forward_validate()` extins la Pasul 10a).
3. Calcul `_fit_temperature()` pe setul OOF al acestei rulări (aceeași funcție de producție, apelată din script, neatinsă).
4. Calcul metrici (§3) pentru ML necalibrat și ML calibrat, din aceleași margini.
5. Recalcul Oracle (identic Etapa 3 §2.2, cod neschimbat) și Blend (cu ML calibrat ca input) pe același eșantion.
6. Măsurare overhead runtime (§3, ultimul rând).
7. Verdict pe criteriile de succes (§4).
8. Redactare `ETAPA3_RERUN_AFTER_ADR049.md` (§5) — `ORACLE_VS_ML_REPORT.md` rămâne complet neatins.
9. Commit separat: `scripts/rerun_etapa3_benchmark.py` + raportul nou + actualizarea `ARCHITECTURE_STATE.md` §3.1 (pointer către raportul nou) — abia după aprobarea explicită a rezultatelor, urmând disciplina de review-diff folosită la Pașii 9/10a/10b (nu o narațiune, materialul efectiv).

## 8. Criterii de rollback / eșec

Nu există „rollback" în sens de cod (niciun cod de producție nu se schimbă). Dacă rezultatele nu satisfac criteriile din §4, rezultatul e **documentat ca atare** — nu se reinterpretează pragul, nu se repetă rularea cu alte praguri "până iese bine". Un eșec pe criteriile de succes e o concluzie validă a Pasului 11 (analog concluziei Etapei 3: „ML singur nu are dovadă suficientă"), nu un motiv de a relua planificarea.

---

**Status**: **APPROVED — pregătit pentru execuție**. Redactat 2026-08-04, revizuit în aceeași zi pe baza a 5 observații de review, toate integrate: (1) §1.2, formularea explicită „benchmark de revalidare, nu de reproducere"; (2) §1.1/§2, Oracle recalculat pe același eșantion pentru consistență experimentală, nu doar ML/Blend; (3) §4, criteriul de accuracy despărțit explicit în invariant matematic (argmax, deja demonstrat) vs. observație de benchmark (investigată dacă diferă, nu presupusă bug); (4) §5, `ORACLE_VS_ML_REPORT.md` rămâne complet neatins, trimiterea se face din `ARCHITECTURE_STATE.md`; (5) §6, script committed (`scripts/rerun_etapa3_benchmark.py`), nu efemer. Execuția (§7) poate începe.
