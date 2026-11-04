# Analiza modulului ML — ce trebuia să fie, ce este, ce se poate cabla

**Tip**: analiză măsurată, read-only. **NU e ADR, nu autorizează cod, nu schimbă nimic.**
**Data**: 2026-11-04 · **Rol**: arhitect/inginer, la cererea proprietarului produsului.
**Metodă**: ADR-urile citite integral; codul citit, nu presupus; cifrele măsurate pe producție.

---

## 0. Rezumatul într-o propoziție

> **Plafonul modulului ML nu e algoritmul, nu sunt hiperparametrii și nu e calibrarea — e că 88,8% din rândurile lui de antrenare nu conțin NICIO informație pe care Oracle nu o are deja.** Viziunea ADR-051 cere ca ML să „observe relații pe care Oracle nu le vede"; structura datelor de antrenare o face **imposibilă** pe aproape tot setul.

---

## 1. Viziunea declarată — ce trebuia să fie (ADR-051 §2.2, ACCEPTED 2026-08-04)

Citat exact, fiindcă fiecare propoziție e un criteriu verificabil:

> *„Nu mai e «XGBoost» — XGBoost e primul algoritm folosit, nu definiția motorului. Machine Learning Engine e o entitate care învață continuu, **cu obiectiv distinct de a reproduce Oracle**: descoperă tipare noi, **observă relații pe care Oracle nu le vede**, identifică contexte speciale, estimează risc."*

Plus, din același ADR:
- **§2.4** — UI trebuie să afișeze **separat, simultan**, Oracle / ML / Blend. Niciun motor ascuns.
- **§2.5** — învățare continuă din istoric + meciuri noi + **propriile predicții anterioare**.
- **§3** — „niciun motor nu e primar prin construcție"; poziția de lider e **fapt empiric curent**.

**Precizare care contează pentru tot restul raportului**: ADR-051 e explicit un ADR *de viziune*, §5 — „nicio modificare de cod". Deci golurile de mai jos **nu sunt încălcări**; sunt distanța, niciodată măsurată până azi, între o direcție declarată și implementarea ei.

---

## 2. Trei goluri din ADR-051 §6 pe care le credeam deschise și sunt ÎNCHISE

Consemnate întâi, fiindcă un raport care le-ar fi presupus deschise ar fi fost „documentație care minte".

| gol §6 | starea reală, verificată azi |
|---|---|
| UI cu trei ieșiri separate | ✅ **IMPLEMENTAT.** `app.py:355-405` — Oracle, `🔀 Blend`, `🤖 ML`, afișate simultan, fără selector. Flaguri `blend_engine_display_enabled` și `ml_engine_display_enabled` amândouă **`true`** în producție. ML are **trei** stări, nu două: succes / indisponibil **cu motiv explicit** / absent — nu aproximează (North Star #8). |
| „Dualitatea Blend" (`ml_blending_enabled` legacy) | ✅ **ÎNCHISĂ.** `grep` pe tot codul de producție: **zero** apariții. Blendul legacy inline a fost eliminat; rămâne doar `blend_v1` ca familie în Model Registry. |
| ML tratat ca „experiment abandonat" | ✅ **Infirmat.** 7 experimente în registru, reevaluate în aceeași zi (4 nov 09:11-09:42), antrenare automată nocturnă, 5 artefacte guvernate. |

**Și calitatea codului de bază e bună, verificată punct cu punct, nu presupusă:**
- sortare cronologică **strictă** înainte de orice split (`df.sort_values("kickoff_date")`);
- **zero imputare** cu mediana — comentariul explică de ce: o mediană globală calculată pe setul sortat „vede" segmentele viitoare, deci e scurgere **la preprocesare**, distinctă de cea de etichete. XGBoost primește NaN nativ;
- `random_state=42` fixat;
- walk-forward expanding window, 5 folduri, model de producție antrenat pe tot istoricul **după** validarea onestă;
- `get_training_data()` exclude `superseded_by` (fără filtru, ~3.500 de meciuri intrau **de două ori**) și pagineză keyset (26 ms vs 2558 ms la OFFSET 50000, măsurat cu `EXPLAIN ANALYZE`).

**Deci nu e un modul neglijat.** Problemele de mai jos sunt structurale, nu de igienă.

---

## 3. 🔴 CONSTATAREA CENTRALĂ — prăpastia de eră

`FEATURE_COLUMNS` are **14** feature-uri. Împărțirea lor pe origine, și acoperirea măsurată pe setul real de antrenare (**50.549** de rânduri eligibile):

| grup | feature-uri | acoperire |
|---|---|---:|
| **Intrările lui Oracle** | `home/away_offensive_rating`, `home/away_defensive_rating`, `home/away_form_score`, `home/away_elo`, `h2h_modifier`, `h2h_meetings` — **10** | **100,00%** |
| **Independente de Oracle** | `corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance` — **4** | **11,18%** |

> **Pe 88,8% din rândurile de antrenare, modelul vede exact și numai ce vede Oracle.** Cele 4 feature-uri „independente" sunt NaN acolo. XGBoost le tratează nativ (învață o direcție implicită de split), deci nu e un defect de cod — dar informația pur și simplu **nu există** pe 9 rânduri din 10.

**Cauza, măsurată pe ere** (meciuri terminate, nesupersedate):

| eră | meciuri | șuturi | posesie | xG real | arbitru | lot |
|---|---:|---:|---:|---:|---:|---:|
| istoric (< iul 2025) | **47.676** | 7,3% | **0,0%** | **0,0%** | **0,0%** | **0,0%** |
| sezon 2025/26 | 2.873 | 5,2% | 5,2% | 5,2% | 5,2% | 5,2% |
| **sezon curent** | **2.080** | **99,6%** | **99,6%** | **93,1%** | **99,9%** | **99,9%** |

**90,5% din setul de antrenare e un import istoric subțire** (Kaggle / football-data.co.uk) care conține practic doar echipe, dată, rezultat și goluri. Tot ce e bogat există **doar pentru ultimele ~4 luni**.

**De ce asta explică D-17 mai bine decât o face D-17 însuși.** D-17 a atribuit convergența celor trei motoare la 0,003 Brier la trei cauze, a treia fiind „ML vede aproape numai intrările Oracle — 10 din 14". Cifra corectă, **ponderată pe rânduri**, e mai dură: **informație Oracle-only pe 88,8% din antrenare**. Corelația ML↔Oracle de 0,777 și argmax diferit în 20,9% nu vin din informație în plus — vin în mare parte din **forma funcțională** (arbori vs Poisson) plus cele 11% de rânduri bogate.

**Setul „bogat complet"** (șuturi + posesie + xG + scor la pauză, toate prezente), pe lună:

| lună | terminate | set bogat complet |
|---|---:|---:|
| 2026-07 | 146 | 93 |
| 2026-08 | 679 | 594 |
| 2026-09 | 534 | **528** |
| 2026-10 | 643 | **642** |
| 2026-11 (parțial) | 78 | 73 |

**Total azi: 1.930 de meciuri, +~600/lună**, cu acoperire ~100% din septembrie. Proiecție: ~4.300 în aprilie 2027, ~7.900 în noiembrie 2027.

---

## 4. Defect măsurat — calibrarea remizei e inversată exact unde contează

Pe toate rândurile `xgboost_v1` cu rezultat (`processing_stage='final'`), găleți de probabilitate declarată pentru remiză:

| ML, remiză declarată | n | rată reală | eroare |
|---:|---:|---:|---:|
| 0,1265 | 44 | 0,1364 | +0,0099 |
| 0,1792 | 139 | 0,1223 | −0,0569 |
| 0,2281 | 379 | 0,1979 | −0,0302 |
| 0,2757 | 683 | 0,2679 | −0,0077 |
| **0,3202** | **451** | **0,2439** | **−0,0763** |
| **0,3692** | **86** | **0,2558** | **−0,1134** |
| **0,4392** | **30** | **0,1000** | **−0,3392** |

**Monotonia e ruptă**: cu cât ML e mai încrezător pe remiză, cu atât e mai greșit. Oracle, pe aceleași găleți, e bine calibrat (−0,0007 / +0,0199 / −0,0175).

**Consecința pe argmax**, aceeași cohortă (n=1828 per bandă):

| realitate | n | % | Oracle prinde | ML prinde | Δ |
|---|---:|---:|---:|---:|---:|
| gazdă | 826 | 45,2% | 558 (67,6%) | **621 (75,2%)** | **+63** |
| oaspete | 586 | 32,1% | **339 (57,8%)** | 292 (49,8%) | **−47** |
| **remiză** | **416** | **22,8%** | **10 (2,4%)** | **12 (2,9%)** | +2 |

> **416 meciuri — 22,8% din eșantion — și ambele motoare prind sub 3%.** Cel mai mare bloc de semnal neatins din tot sistemul.

**🔴 Corecție la propria mea citire, consemnată**: la prima interogare am citit „ML 49,2% corect pe oaspete vs Oracle 43,9%" ca **avantaj la oaspete**. Era **precizie**, nu recall — ML prezice oaspete mai rar (594 vs 772), deci nimerește procentual mai bine și ratează în valoare absolută. Recall-ul arată opusul: ML e mai bun la **gazdă** (+63) și mai slab la oaspete (−47). *Precizia și recall-ul pe aceeași clasă pot avea semne opuse; raportarea unuia singur e o afirmație incompletă.*

**ADR-049 e corect pentru defectul lui și structural incapabil pentru acesta.** Calibrarea existentă e **Temperature Scaling cu un SINGUR scalar global** (`temperature: float | None`, `softmax(margini / T)` aplicat identic pe toate trei clasele). ADR-049 §1 a fost scris pentru supra-încrederea *globală* (gap 4,9pp → 17,1pp cu încrederea) — și pentru aceea un T global e remediul corect. Dar un singur parametru **nu poate** micșora capul remizei lăsând gazda/oaspetele intacte, și cu atât mai puțin **inversa o non-monotonie**. Clasa de remediu e cunoscută: *vector/matrix scaling* (temperatură per clasă) sau calibrare Dirichlet.

**Rezerva de la prima redactare — ✅ REZOLVATĂ ÎN ACEEAȘI ZI prin P1, vezi §4bis.** Scrisesem că `calibration_temperature` nu e persistată în `training_runs.walk_forward_metrics` (adevărat — are exact trei chei: `accuracy`, `log_loss`, `brier_score`) și că artefactul din Supabase Storage nu se poate citi prin SQL (tot adevărat), deci nu pot afirma dacă artefactul servit are calibrare aplicată. **Ruta aceea era închisă, dar exista o a doua pe care n-o căutasem**: `continuous_learning.py:699` scrie temperatura în `automation_runs.summary`. Deci întrebarea era răspunzabilă read-only tot timpul.

---

## 4bis. P1 EXECUTAT (2026-11-04) — ADR-049 e **ACTIV**, iar prejudecata remizei e a MODELULUI, nu a calibrării

**Lanțul, verificat verigă cu verigă, în cod ȘI în date:**

1. **Fit** — `ml_predictor.train()` linia 606: `self.temperature = self._fit_temperature(wf["oof_margins"], wf["oof_labels"])`, pe setul **out-of-fold** al walk-forward-ului (nu pe datele modelului de producție — ADR-049 §5 opțiunea 3, respinsă explicit ca scurgere).
2. **Persistență** — scriitor **UNIC**: `continuous_learning.py:684`, bucket `model-artifacts`, cheie `<training_run_id>.calibration.json`.
3. **Gardă D3, care face dovada structurală**: dacă temperatura e `None`, `ar.fail_run(..., "CALIBRATION_NOT_AVAILABLE")` și **Challenger-ul NU se creează deloc**. Deci *existența* unui Challenger implică o calibrare reușită — nu e nevoie de Storage ca să se știe.
4. **Servire** — `local_model_cache.py:209` încarcă artefactul; `ml_predictor.predict()` liniile 682-686 aplică `_softmax_with_temperature(margins, T)` dacă T există, altfel `predict_proba()`.

**Urma în date — 6 rulări `calibration_persistence`, TOATE `completed`/`SUCCESS`:**

| data | țintă | T |
|---|---|---:|
| 4 aug | `blend_v1\|all` | 1,2200 |
| 5 aug | `xgboost_v1\|all` | 1,1934 |
| 24 aug | `blend_v1\|all` | 1,1962 |
| 6 sep | `xgboost_v1\|all` | 1,1943 |
| 20 sep | `blend_v1\|all` | 1,2016 |
| **14 oct 05:31:03** | **`xgboost_v1\|all`** | **1,2037503022912854** |

Ultima corespunde exact artefactului servit `dda4f7f3` (antrenat 05:31:01, cu două secunde înainte). **Verdict: ADR-049 e ACTIV — nu inactiv, nu parțial.** `T > 1` pe toate șase, bandă strânsă (1,193–1,220) pe 2,5 luni — supra-încredere globală ușoară și remarcabil de stabilă.

**Comparația brut vs calibrat, exactă și fără model.** Dacă `p = softmax(z/T)`, atunci `p^T ∝ exp(z)`, deci `softmax(p^T) = predict_proba()` — inversare **matematic exactă**, calculabilă doar din probabilitățile jurnalizate (singura imprecizie: `prob_*` e rotunjit la 4 zecimale, ordin 1e-4, neglijabil față de efectele de 5e-3).

| artefact | n | Δbrier (calib − brut) | \|t\| | Δlog-loss | \|t\| |
|---|---:|---:|---:|---:|---:|
| `e638c1dc` | 679 | **−0,00082** *(calib mai bun)* | 0,50 | −0,00126 | 0,50 |
| `6e7265c5` | 620 | +0,00115 | 0,64 | +0,00185 | 0,66 |
| **`dda4f7f3`** (servit) | 529 | **+0,00466** | **2,30** | +0,00621 | 1,91 |

**🔴 CORECȚIE LA MINE, în aceeași oră.** Prima citire — doar pe artefactul servit — m-a dus la „calibrarea înrăutățește ambele metrici". **Afirmația e exagerată.** Pe celelalte două artefacte diferența e **indistinctă de zero** (|t| = 0,50 și 0,64) și **semnul se inversează**. Doar pe cel servit există un semnal slab contra calibrării, și doar pe Brier (2,30); log-loss-ul nu trece pragul (1,91 < 1,96). **Formularea corectă: calibrarea globală e net NEUTRĂ, cu un semnal slab advers pe artefactul curent.** Luasem cifra unui singur artefact ca pe concluzie — exact „două măsurători care nu se potrivesc = cauză de găsit, nu cifră de ales", aplicat de data asta la trei.

**Și constatarea care RE-ORDONEAZĂ propunerile:**

| | remiză declarată | realitate |
|---|---:|---:|
| **brut** (T=1) | **0,2518** | **0,2098** |
| calibrat (T=1,2038) | 0,2660 | 0,2098 |

> **Prejudecata de remiză există ÎNAINTE de calibrare** (+0,042 absolut pe brut) și e doar **agravată** de ea (+0,056). Deci e o proprietate a **MODELULUI**, nu un artefact al calibrării.

Mecanismul e coerent: `T > 1` netezește spre uniform, iar remiza e clasa din mijloc — netezirea îi **împinge** masă. Calibrarea a fost fitată pe marginile out-of-fold ale celor ~50k rânduri istorice și aplicată pe cohorta sezonului curent, unde eroarea dominantă e alta. **A patra instanță a clasei „o mărime fitată pe o populație, aplicată pe alta"** — după baseline-ul înghețat (ADR-072), rata peste o fereastră care traversează reparația (ADR-081/085), și premisa de volum măsurată în timpul unei pene (ADR-077).

**Consecința pentru P3**: calibrarea per clasă ar trata un simptom a cărui cauză e în model, iar efectul TOTAL al calibrării globale e de ordinul **0,005** pe Brier — de două ori mai mic decât câștigul blendului (−0,0089) sau avantajul curent al lui `174e7e17` (−0,0094). **P3 coboară în prioritate**; P2 rămâne levierul real. P3 nu e exclus — 3 parametri au mai multă libertate decât unul, iar capul remizei e umflat cu 0,042 — dar plafonul lui trebuie **măsurat înainte** de orice ADR, nu presupus.

---

## 5. Ce se poate cabla — propuneri ordonate după raport dovadă/cost

Fiecare are: ce schimbă, ce costă, cum se testează, și ce ar infirma-o.

### P1. ✅ **EXECUTAT 2026-11-04** — verifică dacă ADR-049 e activ pe artefactul servit

**Rezultat: ACTIV, T = 1,2037503022912854.** Lanțul verificat end-to-end, în cod și în date; calibrarea globală e **net neutră**; prejudecata de remiză e a **modelului**, nu a calibrării. Toate cifrele și corecția la propria mea citire: **§4bis**.

Nu a fost nevoie de Storage: urma e în `automation_runs.summary`, iar garda D3 face existența Challenger-ului o dovadă structurală a calibrării reușite.

### P2. 🥇 Modelul „erei bogate" — testat contra celui actual, NU în locul lui

**Ipoteza**: **1.930 de rânduri × ~25 de feature-uri bogate** bat **50.549 × 14 feature-uri preponderent Oracle**. Nu e evident — e exact genul de întrebare pe care proiectul o rezolvă prin ablație, nu prin intuiție.

Feature-uri candidate care EXISTĂ deja în bază și nu sunt folosite, toate ca **medii glisante** (niciodată valoarea meciului în curs — North Star #7):
- **xG real recent per echipă** (`home/away_xg_actual`) — cel mai promițător: e cea mai bună măsură publică a calității șanselor, iar Oracle folosește xG **propriu, calculat**, nu xG observat;
- posesie recentă, șuturi pe poartă vs totale (raport de conversie), parade portar, ofsaiduri;
- scor la pauză recent (`ht_goals`) — **atenție**: `ht_goal_diff` a fost testat și **RESPINS** (`HT_SCORE_ABLATION_2026-07-14`), deci forma glisantă e o întrebare **nouă**, nu o reluare;
- grad de umplere a stadionului (`attendance`/`capacity`) ca proxy de presiune.

**Cost**: un script read-only, zero migrări, zero atingere a servirii. **Rulează în afara căii de predicție.**
**Protocol, declarat ÎNAINTE** (ca să nu alegem sensul după rezultat):
- walk-forward pe era bogată, aceeași procedură (`_walk_forward_validate`), `random_state` fix;
- **referința e modelul actual evaluat pe ACEEAȘI fereastră**, nu pe istoricul lui — altfel comparăm două populații;
- **interpretare declarată**: mai bun simultan pe Brier **și** log-loss → candidat pentru un ADR de feature-uri noi; mai bun doar pe acuratețe → **nu se promovează** (poarta cere scoring rules); mai slab → **subiectul se închide**, iar asta e un răspuns, nu un eșec;
- **capcana de evitat**: 1.930 de rânduri pe 3 clase cu 25 de feature-uri e subțire. Dacă rezultatul e pozitiv dar cu |t| mic, verdictul e „insuficiente date", nu „promovabil" (North Star #8).

### P3. Calibrare per clasă — **COBORÂTĂ în prioritate de rezultatul P1**

> **P1 a arătat că globala E activă și că prejudecata de remiză o PRECEDE** (0,2518 brut vs 0,2098 real). Deci P3 ar trata un simptom a cărui cauză e în model. Rămâne pe listă, dar **plafonul lui se măsoară înainte de orice ADR** — efectul total al calibrării globale e ~0,005 pe Brier, sub câștigul blendului (−0,0089).

Vector scaling (un T per clasă, 3 parametri) fitat pe **exact aceleași margini out-of-fold** pe care ADR-049 le folosește deja — deci **zero infrastructură nouă**, `oof_margins`/`oof_labels` sunt deja capturate.
- **Atinge contractul model↔calibrator** (ADR-049 §7, „unitate logică unică de inferență") → **cere ADR**, nu editare tăcută.
- **Câștig așteptat**: pe log-loss și Brier, nu pe acuratețe — exact metricile pe care poarta le cere.
- **Riscul real, declarat**: 3 parametri pe ~1.800 de margini e încă rezonabil, dar e **supraînvățare potențială** acolo unde un parametru nu era. Se validează out-of-fold, nu in-sample.

### P4. Cotele pieței ca feature — **măsurat ca cel mai puternic semnal independent, ȘI cu o obiecție de principiu**

Reperul extern (`CLAUDE.md`) măsoară piața la **0,5233** vs Oracle **0,4939**. ML **nu vede cotele deloc**. Acoperire: **1.463 din 2.080** de meciuri din sezonul curent (**70,3%**), 24 de case.

> **🔴 Obiecția care trebuie pusă pe masă, nu ascunsă**: un model antrenat pe cote **învață să prezică piața**. Pentru *acuratețe* e cel mai mare levier disponibil. Pentru **value betting** — scopul declarat al produsului — e **circular**: radarul caută divergențe față de piață, iar un motor care reproduce piața nu poate produce niciuna. Ar îmbunătăți metricile și ar **reduce** utilitatea.
>
> Varianta care ocolește circularitatea: cotele intră nu ca feature de predicție, ci ca **ancoră de calibrare** sau ca detector de regim („cât de mult diferim de piață, și în ce context greșim mai des decât ea"). Asta rămâne o întrebare **nedeschisă**, nu o propunere coaptă.

### P5. Căutare de hiperparametri — ieftină, probabil marginală

Hardcodate și **niciodată căutate**: `n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85`.
- Pe 50k rânduri cu 14 feature-uri, `max_depth=4` e **conservator**; un model puțin mai adânc ar putea extrage mai mult din cele 11% rânduri bogate.
- **Obligatoriu walk-forward-safe**: hiperparametrii se aleg **exclusiv pe folduri trecute**, altfel e scurgere prin selecție de model — exact clasa pe care comentariul despre imputare o evită deja.
- **Așteptare onestă: câștig mic.** Se face fiindcă e ieftin, nu fiindcă promite mult.

### P6. Învățarea din propriile predicții anterioare — cerută de §2.5, NEIMPLEMENTATĂ

ADR-051 §2.5 cere explicit învățare din *„propriile predicții anterioare"*. Azi nu există: ML se antrenează pe `match_history`, iar `shadow_predictions` (istoricul predicțiilor lui) nu e niciodată citit ca intrare.
- **Nu propun să se cableze.** E cea mai riscantă dintre toate: un model care se antrenează pe propriile ieșiri își poate amplifica erorile, iar aici ar atinge și dependența circulară din §20.H.
- **Consemnat ca gol declarat al viziunii**, ca să nu fie redescoperit — nu ca lucru de făcut.

---

## 6. Ce NU se face, și de ce

| propunere | de ce nu |
|---|---|
| Alt algoritm (CatBoost, LightGBM, rețele) | Contractul `LearningAlgorithm` îl permite fără ADR nou, dar **nu atacă limitarea**: un algoritm mai bun pe aceleași 14 coloane rămâne un model antrenat pe intrările lui Oracle. Întâi datele, apoi algoritmul. |
| Mai multe date istorice (alt import Kaggle) | Ar îngroșa exact stratul care nu conține informație nouă — 47.676 de rânduri cu 0,0% xG/posesie/arbitru. **Ar scădea proporția erei bogate**, deci ar înrăutăți problema. |
| Feature nou fără ablație | Interzis de §Regulile ML. Precedent: 6 feature-uri eliminate prin permutation importance pe 53.409 meciuri; `rest_days_modifier` respins deși avea fundament teoretic solid. |
| Orice schimbare de servire | Blocată de dependența circulară (`DE_URMARIT` §20.H): rândul `control` e **simultan** predicția servită și baseline-ul porții. Ordinea forțată rămâne ADR-084 → D-15 → Pasul 3. |

---

## 7. Ordinea recomandată

1. ~~**P1**~~ — ✅ **FĂCUT**, §4bis. A schimbat ordinea, exact cum spera să poată: a coborât P3.
2. **P2** (modelul erei bogate) — **URMĂTORUL**. Read-only, cel mai mare câștig potențial, protocol declarat înainte. Aprobat de proprietarul produsului pe 4 nov, după P1.
3. **P5** (hiperparametri) — ieftin, se poate rula în paralel cu P2.
4. **P3** (calibrare per clasă) — **coborât de P1**; întâi se măsoară plafonul, abia apoi se discută un ADR.
5. **P4** (cotele) — **discuție de principiu înainte de orice cod**, din cauza circularității.
6. **P6** — rămâne consemnat, nu se face.

**Condițiile proprietarului produsului pentru P2, consemnate ca atare** (4 nov): separare strictă temporală antrenare/evaluare · **aceleași meciuri de evaluare** pentru ambele modele · zero modificare a modelului din producție · Brier și log-loss **principale**, acuratețea **secundară** · rezultatul **nu declanșează nicio promovare automată** · nicio interferență cu ordinea ADR-084 → D-15 → Pasul 3.

**Niciuna nu atinge calea de predicție, niciuna nu cere migrare, niciuna nu promovează nimic automat (ADR-002).**

---

## 8. Ce ar infirma analiza asta

Scris explicit, ca reevaluarea să fie ieftină prin construcție:

- dacă P2 arată că era bogată **pierde** clar, atunci „prăpastia de eră" e reală ca fapt dar **irelevantă ca levier** — cele 10 intrări Oracle ar fi pur și simplu informația care contează, iar concluzia §0 ar trebui rescrisă;
- ~~dacă P1 arată T ≈ 1,0 acceptat…~~ **REZOLVAT: T = 1,2038, iar §4bis arată că reziduul e exact „strict pe clasa remiză" — deci cazul ESTE mai îngust decât îl prezentam în §4**, și prezentarea aceea a fost corectată;
- dacă acoperirea bogată **se rupe** din nou (precedentul ADR-076, 39 de zile), cifra de 1.930 încetează să crească cu ~600/lună, iar P2 își pierde baza. **Clasa 11 din `check_data_health` e detectorul declarat** pentru asta.
