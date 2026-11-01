# ADR-084 — Poarta de promovare se sprijină pe regulile de scor propriu, nu pe metrica cea mai slabă dintre trei

**Status**: **PROPUNERE — cere aprobare explicită a proprietarului produsului**
**Data**: 2026-10-29
**Revizia 2** (2026-10-29, după auditul cerut de proprietarul produsului): trei
afirmații proprii **infirmate** și corectate (§4.4, §6.1, §9), **§4.3 trecută de
la poartă la divulgare** (vezi §7.2 — pragul era nederivabil), o **etapă
preliminară obligatorie adăugată** (§9 Etapa 0 — un defect FSM care făcea
întregul ADR inert), o **regulă de eligibilitate** nouă (§4.6), și proiecția
statistică din §5.5 marcată ca **neconfirmată de datele ulterioare**. Nimic din
§9 nu e implementat; toate etapele rămân **plan**, nu aprobări.
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Legat de**: North Star #2 (dovadă statistică simultană pe metrici multiple),
ADR-002 (promovarea e act uman), ADR-016 (Challenger FSM), ADR-019 (Champion
Manager), ADR-057 (politica de expirare), ADR-072 (baseline proaspăt),
ADR-079 (ciclul de viață al deciziilor), ADR-082 (banda campionului — abia ea
face posibilă clauza §5.3)

---

## 0. Cum a pornit, fiindcă proveniența contează

Întrebarea e a **proprietarului produsului**, pusă pe 29 octombrie 2026, după ce
îi prezentasem de două ori deciziile #12 și #13 ca pe un troc echilibrat:

> „Tot spui că trebuie să fie 3/3 ca noul campion să fie promovat. Asta este mai
> greu. Noi în principiu avem 2/3 și a 3-a un pic sub prag. Mie mi se pare o
> îmbunătățire dacă 2/3 arată o diferență semnificativă și cea de-a 3-a o
> diferență mică. În teorie acest nou campion ar fi mai bun. Nu consideri că
> avem o pistă aici în avantajul proiectului?"

Documentul ăsta există fiindcă răspunsul măsurat a fost **da**, iar verificarea a
infirmat pe drum trei afirmații proprii ale mele. Sunt consemnate la §8, nu
ascunse: o propunere care ascunde erorile autorului nu e o propunere, e o
pledoarie.

---

## 1. Context — ce face poarta de azi, măsurat în cod

`shadow_testing.py:650`, codat dur:

```python
if brier_result.significant and logloss_result.significant and accuracy_result.significant:
    status = "candidate_for_promotion"
```

Iar semnificația (`_paired_bootstrap`, linia 304) e **unilaterală și
direcțională**:

```python
significant = (ci_high < 0) if favorable_direction == -1 else (ci_low > 0)
```

Deci „semnificativ" chiar înseamnă „semnificativ **mai bun**", nu „diferit".
Premisa întrebării de la §0 e corect formulată.

### 1.1 De ce conjuncția e mai strictă decât arată

Cele trei metrici se calculează **pe aceleași meciuri**, cu bootstrap **pereche**
(`statistical_method = paired_bootstrap`, confirmat în `evidence`-ul tuturor
verdictelor). Sunt deci puternic corelate, nu independente. O conjuncție de trei
teste corelate pe același eșantion nu înseamnă „trei dovezi independente" —
înseamnă, în practică, **„metrica cu cea mai puțină putere statistică trebuie să
treacă"**.

Iar acuratețea e structural cea mai slabă dintre cele trei:

- e o funcție **argmax 0/1** — aruncă toată informația de probabilitate pe care
  Brier și log-loss o folosesc;
- are plafon structural, **măsurat pe 28 octombrie 2026**: favoritul caselor de
  pariuri nu a fost remiza **niciodată**, 0 din 2071 de meciuri, iar 23,9% din
  meciuri se termină egal — deci acuratețea e plafonată la ~76% pentru orice
  sistem de tip argmax;
- iar `CLAUDE.md` scrie **din 14 octombrie**, înaintea acestei discuții:
  *„motiv tehnic serios să nu se judece promovările după acuratețe singură"*.

**Precizie obligatorie asupra acelui citat**, ca să nu pară un sprijin mai mare
decât e: fraza continuă cu *„(poarta cere oricum Brier + log-loss + acuratețe
simultan, North Star #2)"*. Deci `CLAUDE.md` spune „nu **doar** după acuratețe",
nu „fără acuratețe", și trata conjuncția ca pe **răspunsul** la problemă.

Observația nouă a acestui ADR e că **conjuncția nu rezolvă problema, ci o
inversează**: pe teste corelate, pe același eșantion, a cere simultan toate trei
face din metrica cea mai slabă singurul judecător efectiv. Ce era gândit ca
protecție contra judecării după acuratețe a devenit judecare **exclusiv** după
acuratețe, pentru orice model care trece confortabil pe celelalte două. Partea
anterioară discuției e premisa (acuratețea e metrica slabă); concluzia e nouă și
nu se poate atribui documentului.

### 1.2 Starea celor doi Challengeri activi, măsurată 29 octombrie

Recalculat cu **funcția de producție** `shadow_testing._paired_bootstrap`, nu
cu o reimplementare. Încărcarea datelor
a fost **validată prin martor**: mediile per meci reproduc deltele stocate în
`challenger_evaluations` la **15 zecimale**, pe ambii Challengeri și pe toate
trei metricile. Fără acel martor, un interval de încredere frumos nu dovedește
nimic.

`blend_v1/174e7e17`, n = 504, baseline `shadow_control`:

| metrică | delta | CI 95% | t aprox. | semnificativ | stabil |
|---|---:|---|---:|---|---:|
| Brier | **−0,010244** | [−0,016613, −0,003930] | **−3,17** | **da** | **100%** |
| log-loss | **−0,015923** | [−0,025961, −0,006134] | **−3,15** | **da** | **100%** |
| acuratețe | +0,015873 | [−0,003968, +0,035714] | +1,57 | nu | **0%** |

`xgboost_v1/dda4f7f3`, n = 351, baseline `shadow_control`:

| metrică | delta | CI 95% | t aprox. | semnificativ | stabil |
|---|---:|---|---:|---|---:|
| Brier | **−0,020618** | [−0,042183, +0,000916] | −1,88 | nu | **16,5%** |
| log-loss | **−0,030851** | [−0,063786, +0,001872] | −1,84 | nu | **7,5%** |
| acuratețe | +0,051282 | [+0,011396, +0,091168] | +2,52 | da | 100% |

> **[REVIZIA 2] Datele s-au mișcat, semnele nu.** Tabelele de mai sus sunt
> măsurate la `n = 504` / `n = 351`. Rularea din **29 octombrie** dă
> `174e7e17` la **n = 523** (Brier −0,010154 ✅, log-loss −0,015867 ✅,
> acuratețe +0,015296 ❌) și `dda4f7f3` la **n = 370** (Brier −0,019551 ❌,
> log-loss −0,029233 ❌, acuratețe +0,051351 ✅). Aceleași semne, aceleași
> flaguri. CI-urile și ratele de basculare rămân valide **la `n` indicat** — nu
> au fost recalculate la noul `n`.

Două citiri care contrazic ce credeam înainte de a măsura:

1. **`blend_v1` cade pe metrica slabă, ferm pe cele puternice.** t ≈ 3,16 pe
   ambele reguli de scor propriu, 100% stabil. Acuratețea e la t = 1,57 și cade
   în **toate** cele 200 de replicări — acolo nu e „un pic sub prag", e scurt.
   Ar avea nevoie de n ≈ 785 ca să se certifice, dacă efectul e real.
2. **`xgboost_v1` are delte de scor propriu de DOUĂ ORI mai mari** decât blend
   (Brier −0,0206 vs −0,0102; log-loss −0,0309 vs −0,0159) și nu trece pragul
   **din cauza lui `n`**, nu fiindcă e mai slab. „Necertificat" nu e „mai slab".

### 1.3 Un defect propriu-zis, găsit pe drum: verdictul nu e determinist

`_paired_bootstrap` folosește `random.randrange` pe RNG-ul **global**, cu 2000
de iterații, iar `random.seed` **nu apare nicăieri** în `shadow_testing.py` sau
în `learning_core/`. Coloana „stabil" din tabelele de mai sus e rata cu care
flagul `significant` iese `True` în 200 de rulări independente, **pe date
identice**:

- Brier `dda4f7f3`: **16,5%**
- log-loss `dda4f7f3`: **7,5%**

Deci două nopți cu exact aceleași date pot produce verdicte diferite. Produsul
celor două rate ≈ **1,2%** din nopți ar declara `candidate_for_promotion`
**din zgomot de bootstrap**, nu din date.

Regula proiectului cere `random_state` fixat explicit pentru orice antrenare;
evaluarea care **decide promovările** nu are niciunul. Un verdict nereproductibil
e și un gol de trasabilitate (North Star #9).

### 1.4 Comparația care nu există: Challenger contra CAMPION

`evaluate_experiment()` compară Challenger-ul cu **Oracle** (rândul `control`,
de la ADR-072). **Niciodată cu campionul în funcție.**

Dar `blend_v1` **are** campion: `8ac89c70`, activ din 23 august. „Promovez
`174e7e17`" înseamnă „îl **înlocuiesc** pe `8ac89c70`" — iar acea comparație nu
a fost făcută niciodată în istoria proiectului.

Banda ADR-082 abia a făcut-o posibilă. Măsurat: suprapunere **189 din 189** de
fixture-uri între bandă și rândurile Challenger-ului, **zero fan-out** (verificat
pe toate trei părțile: niciun `fixture_id` cu mai mult de un rând în bandă, în
`treatment`, sau în `match_history`).

Prima citire, pe **23 de meciuri pereche** (27-28 octombrie):

| metrică | delta (challenger − campion) | CI 95% | t | semnificativ | stabil | meciuri favorabile |
|---|---:|---|---:|---|---:|---:|
| Brier | **−0,013662** | [−0,023191, −0,004110] | −2,81 | **da** | **100%** | 16/23 |
| log-loss | **−0,021899** | [−0,036869, −0,006804] | −2,86 | **da** | **100%** | 18/23 |

**Rezervă, scrisă înainte de concluzie**: n = 23, iar cele 23 sunt dintr-o
fereastră de două zile — posibile efecte de perioadă. Nu e o certificare, e
prima citire. Dar e consistentă în mod revelator: pe **22 din 23** de meciuri
cele două modele au făcut **exact aceeași alegere argmax**. Diferența e o
deplasare **sistematică de calibrare**, nu zgomot — exact ce arată și §1.2 pe o
comparație complet diferită (contra Oracle). Două măsurători independente care
spun același lucru.

---

## 2. Problema, în trei propoziții

1. Poarta cere simultan trei metrici corelate, deci e legată de cea cu cea mai
   puțină putere — acuratețea, despre care proiectul a scris el însuși că nu
   trebuie să judece promovări.
2. Flagurile ei nu sunt deterministe lângă prag, deci un verdict nu e
   reproductibil.
3. Întrebarea pe care o pune — „e mai bun decât Oracle?" — nu e întrebarea care
   contează când familia are deja campion; aceea e „e mai bun decât campionul?",
   și nu se pune niciunde.

---

## 3. Ce NU e în discuție

- **North Star #2 rămâne în picioare ca principiu**: dovadă statistică
  simultană pe metrici multiple, niciodată o singură metrică, niciodată
  intuiție. Propunerea schimbă **operaționalizarea**, nu principiul — și
  păstrează „simultan pe metrici multiple" (două reguli de scor propriu).
- **ADR-002 rămâne neatins**: promovarea rămâne exclusiv act uman, cu aprobare
  explicită. Nimic din acest ADR nu promovează nimic automat.
- **Nu se relaxează la „2 din 3".** O regulă „oricare 2 din 3" ar avea trei
  moduri de a trece și ar trata identic două situații statistic **opuse** (vezi
  §1.2: blend cade pe argmax, XGBoost cade pe scorurile proprii). Se numesc
  metricile, nu se numără.
- **Calea de servire nu se atinge.** Separat și deja consemnat (D-15): nicio
  promovare nu schimbă azi o probabilitate servită.
- **[REVIZIA 2] Poarta NU se extinde tacit la toate experimentele.** Regula de
  eligibilitate e la **§4.6**: doar `baseline_source == 'shadow_control'` **și**
  doar experimentele care participă la cadrul Challenger. Restul rămân pe 3/3.

---

## 4. Decizia propusă

### 4.1 Criteriul primar

Un Challenger devine `candidate_for_promotion` când **ambele reguli de scor
propriu** sunt simultan semnificativ mai bune:

```
brier_significant AND logloss_significant
```

**De ce acestea două și nu altele**: Brier și log-loss sunt *proper scoring
rules* — folosesc întreaga distribuție de probabilitate, iar produsul consumă
probabilități, nu argmax (edge-ul de value betting se calculează din `p_model`
contra probabilității implicite din cotă). Acuratețea măsoară altceva decât ce
vindem.

### 4.2 Garda pe acuratețe — direcție, nu semnificație

```
delta_accuracy >= 0
```

Nu „acuratețea nu e semnificativ mai rea", deși aceea ar fi formularea
teoretic corectă: flagul stocat e unilateral (`true` doar când e mai bună), deci
„semnificativ mai rea" **nu e calculabil din datele existente** fără o a doua
rulare de test. Se alege varianta **mai strictă și calculabilă**, nu una care
pretinde o precizie pe care datele nu o susțin (Regula #8).

Garda oprește cazul degenerat: mai bine calibrat, decizii mai proaste.

### 4.3 Comparația cu campionul — DIVULGARE obligatorie, NU poartă

> **[REVIZIA 2 — schimbare de substanță.]** Revizia 1 cerea asta ca **poartă**,
> cu un prag `n` „care se fixează înainte de prima aplicare". Auditul a arătat
> că acel prag e **nederivabil azi** (§7.2: calculul de putere are nevoie de o
> dispersie care există doar în eșantionul pe care l-am folosi — circular). Un
> număr inventat ar fi fost mai rău decât absența lui.

Pentru o familie care **are** campion activ, `evidence`-ul propunerii de
promovare **trebuie** să conțină comparația Challenger-vs-Campion, pe meciurile
**pereche** din banda ADR-082 (`experiment_group = 'champion'`):

```
n_pereche · delta_brier + CI · delta_logloss + CI · meciuri favorabile / total
cele două ferestre temporale disjuncte, cu semnul fiecăreia
fan-out verificat (COUNT(*) = COUNT(DISTINCT fixture_id) pe fiecare parte)
```

Dacă banda e goală sau mică, câmpul se scrie **explicit** ca
`insufficient_data` împreună cu `n` real — **niciodată omis, niciodată
aproximat** (Regula #8). Pentru o familie fără campion se scrie
`fara_campion_activ`, nu un zero fabricat.

**Un eșantion mic NU e dovadă de superioritate, și documentul nu-l va prezenta
niciodată ca atare.** Prima citire (23 de meciuri, §1.4) e consemnată ca
*primă citire*, cu rezerva scrisă înaintea rezultatului. Un `n` mic în evidence
e o **informație despre cât de puțin știm**, nu un argument pentru promovare.

**De ce divulgare și nu poartă**: ADR-002 face aprobarea umană singura cale de
promovare. Comparația cu campionul nu trebuie deci să blocheze codul — trebuie
să fie **în fața omului în momentul în care decide**. Asta o face implementabilă
azi, fără un prag inventat.

**Trocul, spus direct**: ca **poartă de cod**, pachetul devine astfel **mai
puțin strict** decât promitea revizia 1. Compensațiile — aprobarea umană
obligatorie oricum, zero modele noi admise la testul de inundare (§5), și calea
de întărire din §9 Faza 7 — sunt reale, dar nu anulează trocul. Decizia e a
proprietarului produsului, nu a autorului.

### 4.4 Reparația de determinism

> **[REVIZIA 2 — CORECTAT.]** Revizia 1 scria „seed derivat din
> `(training_run_id, n_matches_evaluated)`". **Neimplementabil ca scris**:
> `evaluate_experiment` nu primește `training_run_id`, primește
> `experiment_name` + `experiment_version`. Pentru Challengeri
> `experiment_version` **este** `training_run_id` (verificat în date), dar
> pentru `flashscore_team_dna` e `'v1'`.

Cheia corectă: **`(experiment_name, experiment_version, n_matches_evaluated)`**
— reproductibilă pentru același verdict, diferită între experimente și între
zile, fără să înghețe rezultatul la o valoare norocoasă.

Trei constrângeri de implementare, fiecare dintr-un mod concret de a greși:

1. **`hashlib.blake2b`, niciodată `hash()`.** `hash()` e sărat per proces
   (`PYTHONHASHSEED`), deci un seed derivat din el ar fi **nereproductibil între
   rulări** — exact defectul pe care îl reparăm, mutat.
2. **Instanță `random.Random(seed)` locală, niciodată `random.seed()`.** Un seed
   global ar afecta `_paired_permutation`, `polite_delay()` și orice alt
   consumator al RNG-ului global din același proces. Parametru opțional `rng`;
   când lipsește, comportamentul rămâne **identic** cu cel de azi.
3. **Varianta A — același set de reeșantionări pentru toate trei metricile**
   (instanță `Random(seed)` **nouă** înaintea fiecărei metrici, nu una avansată
   peste cele trei). Motivul: poarta e o **afirmație comună** („toate simultan
   mai bune"), iar §1.1 argumentează chiar că metricile **nu** sunt
   independente. Varianta B (fluxuri distincte) le-ar trata ca independente și
   păstrează componenta de fals-pozitiv care vine din alinierea a trei zgomote
   separate — ≈1,2% din nopți, calculat din ratele măsurate 16,5% × 7,5%.
   **Rezerva declarată**: A nu e doar reproductibilitate, schimbă ușor
   caracterul statistic al porții față de azi. De aceea e aici ca decizie, nu
   ca fix tăcut. Cine preferă caracterul neschimbat alege B.

Nu e un ADR separat prin conținut (nu schimbă niciun contract de date), dar
intră aici fiindcă **restul deciziei se sprijină pe reproductibilitate**: n-am
voie să propun o poartă nouă și să las verdictul ei nereproductibil.

### 4.5 Flag, implicit oprit

`promotion_gate_proper_scoring_enabled`, implicit **`False`** (North Star #3).
Cu flagul oprit, comportamentul e **identic** cu cel de azi: poarta rămâne 3/3.

### 4.6 Eligibilitate — poarta rafinată NU se aplică tuturor experimentelor

> **[REVIZIA 2 — secțiune nouă.]** Revizia 1 nu discuta domeniul, iar
> `evaluate_experiment` are **două** căi de apel în producție: una pentru
> Challengeri (`challenger_evaluation.evaluate_active_challenger`, baseline
> `shadow_control`), și `evaluate_all_active_experiments`
> (`shadow_testing.py:863`, din `run_daily`) care rulează pe **tot registrul**,
> inclusiv `flashscore_team_dna/v1` — singurul cu **zero** rânduri `control`
> din 1543, deci pe `baseline_source = 'match_history_frozen'`. Fără regula de
> mai jos, poarta s-ar fi extins **tacit** și la el.

Poarta rafinată se aplică **exclusiv** când sunt îndeplinite simultan:

1. **`baseline_source == 'shadow_control'`**;
2. experimentul **participă la cadrul Challenger**
   (`participates_in_challenger_framework`, flag deja declarat și citit la
   `continuous_learning.py:260`).

Orice altă combinație păstrează comportamentul de azi — **3/3, neschimbat**. Nu
există cădere implicită pe criteriul rafinat.

**De ce condiția (1) e esențială**: ADR-072 a măsurat că baseline-ul înghețat
**flatează** Challenger-ul în **4 din 5** cazuri, cu inversare de semn în 2 din
5 (`+1,18pp` înghețat → `−1,04pp` proaspăt). A relaxa poarta pe un baseline
despre care se **știe** că e optimist înseamnă a compune două erori. Rezerva pe
`4e17c737` din §5.4 e exact ilustrarea: 15 zile din 15 sub criteriul rafinat,
toate pe baseline înghețat, pentru un model care **pierde** contra Oracle-ului
real.

**Riscul rezidual, măsurat ca mic** (29 oct): `flashscore_team_dna/v1` nu are
rânduri în `challenger_evaluations`, deci `promotion_service` **nu poate**
acționa pe el (`promotion_service.py:88` citește
`get_latest_challenger_evaluation`). Iar singurul consumator de producție al lui
`experiment_registry.status` e filtrul de stări terminale
(`TERMINAL_REGISTRY_STATUSES = frozenset({"promoted", "deprecated"})`,
`shadow_testing.py:722`, folosit la linia 889) — nici `monitoring`, nici
`candidate_for_promotion` nu sunt terminale, deci o trecere între ele e inertă
acolo.

> **Corecție la o afirmație mai veche a proiectului**, găsită cu aceeași
> ocazie: `CLAUDE.md` scrie că „nimic nu citește `experiment_registry.status` în
> producție". Era adevărat la momentul scrierii; **nu mai e** — ADR-080 însuși a
> introdus consumatorul de la linia 889. De consemnat separat, în afara acestui
> ADR.

---

## 5. Testul de inundare — dovada că NU e o relaxare

Criteriul rafinat a fost aplicat **retroactiv** pe tot istoricul
`challenger_evaluations` (toate rândurile cu cele trei flaguri calculate),
**înainte** de a scrie o literă din decizia de mai sus.

### 5.1 O capcană prinsă pe drum

Din 11 „challengeri" distincți, **5 sunt `gate_validation_test`** — suita
sintetică rulată în 13 secunde pe 14 iulie, unde `league_scope` e numele cazului
de test. Agregatul brut („9 din 11 trec ambele porți") ar fi fost **grav
înșelător**. Modele reale: **6**.

### 5.2 Rezultatul, pe modele reale

| model | zile evaluate | **3/3 (azi)** | **rafinat §4.1+§4.2** | fără gardă | blocate de gardă | baseline |
|---|---:|---:|---:|---:|---:|---|
| `blend_v1/174e7e17` | 14 | **2** | **11** | 11 | 0 | `shadow_control` |
| `blend_v1/4e17c737` | 15 | 1 | 15 | 15 | 0 | înghețat |
| `blend_v1/8ac89c70` | 1 | 1 | 1 | 1 | 0 | înghețat |
| `xgboost_v1/6e7265c5` | 16 | **0** | **0** | **3** | **3** | înghețat |
| `xgboost_v1/dda4f7f3` | 7 | 2 | 2 | 2 | 0 | `shadow_control` |
| `xgboost_v1/e638c1dc` | 14 | 0 | 0 | 0 | 0 | înghețat |

**Mulțimea, nu cardinalitatea** (egalitatea a două numărători nu dovedește
egalitatea a două mulțimi): modelele care trec criteriul rafinat măcar o zi sunt
exact `{174e7e17, 4e17c737, 8ac89c70, dda4f7f3}` — **aceleași patru** care trec
3/3 măcar o zi.

> **ZERO modele noi admise.** Nu e o poartă deschisă; e aceeași poartă, citită
> stabil.

### 5.3 Garda pe acuratețe e validată contra unei decizii umane corecte

Singurul model care ar fi intrat **fără** garda §4.2 e `xgboost_v1/6e7265c5` —
3 zile, blocate toate 3.

Iar `6e7265c5` e exact Challenger-ul pe care proiectul **l-a expirat manual**, ca
decizia #7, pe motivul scris în `CLAUDE.md`: *„e sub Oracle la acuratețe pe
AMBELE baseline-uri (−1,97pp înghețat, −1,74pp proaspăt)"*.

**Criteriul rafinat reproduce independent o judecată umană deja luată și
verificată.** Nu există validare mai bună pentru o gardă.

### 5.4 Ce schimbă de fapt — și o rezervă

Nu *cine* trece, ci *cât de stabil*: `174e7e17` ar fi fost candidat **11 zile
din 14** în loc de 2. Pâlpâirea de candidatură dispare.

**Rezervă obligatorie**: `4e17c737` trece 15/15 sub criteriul rafinat, dar toate
rândurile lui sunt pe baseline **înghețat**, iar `CLAUDE.md` consemnează că
*„pare că bate Oracle cu +3,2pp, dar contra Oracle-ului real pierde cu 1,1pp"*.
Cele 15 zile sunt artefactul baseline-ului de dinainte de ADR-072, **nu** o
proprietate a porții propuse. Pe rânduri corecte (`shadow_control`) rămân doar
`174e7e17` și `dda4f7f3`.

### 5.5 Criteriul rafinat NU ajută XGBoost

`dda4f7f3` are 2 zile sub **ambele** criterii. Rafinarea **cere** exact cele două
metrici pe care el le ratează. Deci ADR-ul ăsta ajută `blend_v1`, nu
`xgboost_v1`.

> **🔴 [REVIZIA 2] Proiecția din revizia 1 e NECONFIRMATĂ și se retrage ca
> așteptare.** Scrisesem că, la ritmul măsurat al lui `n` (seria zilnică +11,
> +36, +13, **+61, +59**, +10, +4 — calendarul, nu o medie) și cu `t` scalând cu
> √n, ambele metrici lipsă ar trece 1,96 „în jurul 1-2 noiembrie, pe poarta
> actuală".
>
> Două zile noi au testat ipoteza și **nu** au confirmat-o. La `n = 370`
> (29 oct), `brier_significant` e în continuare `false`, iar efectul a scăzut:
> Brier −0,020618 → **−0,019551**, log-loss −0,030851 → **−0,029233**. Raportul
> estimat al statisticii, presupunând dispersia per meci aproximativ constantă:
> ×(0,9483 × √1,0541) ≈ **t ≈ 1,83**, adică **mai jos**, nu mai sus.
> **Degradarea efectului anulează câștigul din `n`.**
>
> Nicio dată nu se mai afirmă ca așteptare. Dacă `xgboost_v1` ajunge vreodată la
> două metrici semnificative, se vede în `challenger_evaluations` în dimineața
> respectivă — nu se prezice.

---

## 6. Consecințe

### 6.1 Imediate, dacă se aprobă ȘI se activează — CORECTAT, revizia 1 era FALSĂ

> **[REVIZIA 2 — cea mai importantă corecție a auditului.]** Revizia 1 afirma că
> se propune o promovare și că `propose_decision` retrage automat #12.
> **Fals.** Lanțul se rupe **înainte** de `propose_decision`:
> `_handle_candidate_for_promotion` începe cu `transition(tid, "SUCCEEDED")`,
> iar `ALLOWED_TRANSITIONS["SUCCEEDED"] = {"PROMOTED", "REJECTED"}` — **nu se
> conține pe sine**. Ambii Challengeri sunt deja `SUCCEEDED`, deci handlerul ar
> eșua, ar face `fail_run` și `return`: **nicio propunere, #12 neretrasă,
> rularea marcată `failed`**.
>
> **Dovada, nu ipoteza**: `automation_runs` **1288** (blend_v1) și **1291**
> (xgboost_v1), ambele 24 oct 07:58, plus **355** (23 aug 09:36) — toate
> `failed` cu *„tranzitie SUCCEEDED esuata: tranziție invalidă: SUCCEEDED ->
> SUCCEEDED"*. Tiparul: **prima** zi de candidatură propune (id 1274/1278/350);
> **a doua** moare tăcut. Consecință observabilă: #10 și #11 au rămas cu
> cifrele din 23 oct (n=357/204) deși pe 24 oct erau 370/217.
>
> Defectul **nu e consemnat** în `docs/` sau `CLAUDE.md` și **niciun test** nu
> îl acoperă. Lovește și **poarta actuală**, nu doar pe cea propusă: dacă un
> Challenger atinge 3/3 două zile la rând, a doua e înghițită. De aceea §9
> Etapa 0 e **preliminară obligatorie**.

**Condițiile REALE ca `propose_decision` să fie atins** (toate necesare):

1. verdict `candidate_for_promotion` din `evaluate_experiment`;
2. `training_run_id` rezolvabil (`get_active_challenger` non-`None`);
3. **Etapa 0 aplicată** — altfel un Challenger deja `SUCCEEDED` nu trece;
4. nicio decizie `approved` pe același `target_key` — ADR-079 §4.1 o îngheață și
   **REFUZĂ** propunerea nouă;
5. nicio răcire activă — `withdrawn` **nu** o declanșează
   (`_STARI_PENTRU_RACIRE = ("rejected", "expired")`), deci o expirare retrasă
   poate fi repropusă imediat;
6. `surface_decision` reușește (altfel contorul nu crește, ADR-079 §4.4a).

**Formulare condiționată, deliberat** (nicio stare nu se modifică prin acest
document): *dacă* Etapa 0 ar fi aplicată, *dacă* flagul ar fi activat, și *dacă*
verdictele ar rămâne cele măsurate pe 29 octombrie, atunci `174e7e17` ar
satisface §4.1+§4.2 (Brier ✅, log-loss ✅, acuratețe +0,015296 ≥ 0), iar
`dda4f7f3` **nu** le-ar satisface (cade exact pe cele două metrici cerute).
Niciuna dintre aceste condiții nu e îndeplinită azi.

**Candidatură ≠ promovare.** O propunere aprobată se execută **doar** dacă la
momentul comiterii: `challenger["state"] == "SUCCEEDED"`
(`promotion_service.py:80`) **și** **ULTIMA** evaluare are
`verdict == "candidate_for_promotion"` (liniile 88-90 — nu cea de la aprobare,
cea de atunci) **și** artefactul validează. Promovarea rămâne `pending` până la
aprobarea **explicită** a omului (ADR-002); nimic nu se promovează singur.

### 6.2 Interacțiunea cu expirările (ADR-057 / ADR-079), neschimbată

Un Challenger `candidate_for_promotion` nu ajunge niciodată în handlerul de
`monitoring`, deci expirarea nu i se mai propune. Regula de expirare
(`MIN_MATCHES_FOR_EXPIRY = 300`, `MAX_MATCHES_FOR_TREND_HOLD = 450`,
`MIN_SIGNIFICANT_FOR_TREND_HOLD = 2`) **nu se atinge** de acest ADR.

### 6.3 Costul acceptat

O poartă care cere două metrici în loc de trei are, formal, o rată de
fals-pozitiv mai mare decât conjuncția de trei. Argumentele pentru care se
acceptă: a treia metrică nu adăuga dovadă independentă (§1.1, teste corelate pe
același eșantion); varianta A a seed-ului (§4.4) elimină componenta de
fals-pozitiv care venea din alinierea a trei zgomote separate; iar testul de
inundare (§5) arată empiric **zero** modele noi admise.

> **[REVIZIA 2 — compensație retrasă.]** Revizia 1 invoca aici și clauza §4.3 ca
> „condiție genuin nouă și mai greu de trecut". **Nu mai e valabil**: §4.3 e
> acum divulgare, nu poartă, deci nu compensează nimic la nivel de cod. Rămâne
> ce compensează genuin: non-independența metricilor, seed-ul A, și testul de
> inundare. Trocul e scris explicit la finalul §4.3.

### 6.4 Ce NU se schimbă

`prob_home_win` are în continuare exact un scriitor. Calea de servire, Champion
Guardian, Rollback Engine, Oracle Engine, `model_champions` — neatinse. Niciun
rând istoric nu se rescrie (verdictele din `challenger_evaluations` rămân
imuabile, inclusiv cele produse de poarta veche).

---

## 7. Riscuri, spuse de autor, nu descoperite după

### 7.1 Riscul principal: croirea regulii după date

Propun rafinarea **pentru că** am observat că `174e7e17` cade pe acuratețe. Asta
e, în parte, croirea regulii după rezultat — clasa pe care proiectul o interzice
explicit („nu păstrăm buguri în cod doar pentru că produc rezultate bune").

Trei contramăsuri, toate deja aplicate sau obligatorii:

1. **Argumentul e anterior cazului.** Afirmația că acuratețea e metrica slabă e
   scrisă în `CLAUDE.md` din **14 octombrie**, înainte de discuția asta și fără
   niciun interes în răspuns.
2. **Testul de inundare a rulat ÎNAINTE de redactare** (§5), și ar fi oprit
   propunerea dacă admitea modele noi. Nu le-a admis.
3. **[REVIZIA 2 — contramăsura s-a SLĂBIT, consemnat.]** Revizia 1 se sprijinea
   aici pe faptul că §4.3 „poate chiar să blocheze cazul care a declanșat
   ADR-ul". Odată ce §4.3 a devenit divulgare, **nu mai blochează nimic** —
   deci a treia contramăsură nu mai e o barieră, e o **obligație de
   transparență**: comparația cu campionul ajunge în fața omului, cu `n`-ul ei
   real, inclusiv când acel `n` e prea mic pentru a dovedi ceva. Contramăsura
   reală rămâne că **omul decide** văzând cifra, nu că poarta o impune.

### 7.2 Pragul de `n` e NEDERIVABIL azi — de aceea §4.3 a devenit divulgare

> **[REVIZIA 2 — rescris.]** Revizia 1 spunea că pragul „se fixează separat".
> Auditul a arătat că **nu se poate fixa**, nici separat, nici deloc, cu datele
> de azi.

**Cercul, explicit.** Un calcul de putere cere o estimare de dispersie pentru
**exact perechea** comparată. Dispersiile disponibile sunt ale unor comparații
**diferite**: Challenger-vs-Oracle dă `sd = 0,0730` pentru `blend_v1` și
`0,2050` pentru `xgboost_v1` — dar aceea e dispersia dintre **două motoare
diferite**. Campion-vs-Challenger sunt **ambele `blend_v1`**, deci dispersia
reală e cu un ordin de mărime mai mică. Singura estimare a *acelei* dispersii
vine din cele 23 de meciuri pe care tocmai pragul ar trebui să le judece.
**Circular.**

Agravant, și e eroarea de la §7.1 în formă numerică: am văzut deja rezultatul la
`n = 23`. Un prag derivat din acel efect ar suferi de *winner's curse* — un efect
măsurat la `n` mic e sistematic supraestimat, deci pragul ar ieși artificial mic.

**Ce rămâne scris ca limită, nu ca prag:**

- **`N = 30` e inapărabil.** La ancora conservatoare, efectul minim detectabil
  la 80% putere e **16,6% relativ** — mai mare decât
  `BASELINE_DEGRADATION_MARGIN = 0,10`, pragul la care proiectul consideră un
  campion degradat suficient ca să justifice **retragerea**. Am certifica
  promovări pe o dovadă mai slabă decât cea cerută ca să dăm înapoi.
- **`MIN_MATCHES_FOR_HEALTH = 30` NU se refolosește**: e pragul de sănătate al
  Guardianului, nu al unei comparații între două modele.
- **Calea care sparge cercul legitim, pentru mai târziu** (§9 Faza 7):
  **split-sample** — se fixează criteriul și metoda acum, banda acumulează,
  dispersia se estimează pe **prima** fereastră, pragul se calculează din ea, iar
  testul se face pe **a doua**. Costă timp, nu validitate.
- **Regula celor două ferestre, când divulgarea devine poartă**: varianta
  recomandată e **semne concordante + plafon de omogenitate** între ferestre, cu
  cifrele variantei „fiecare fereastră semnificativă separat" **raportate, nu
  impuse**. Consecința celei din urmă e cuantificabilă și independentă de
  dispersie: pentru `t ≥ 1,96` pe o fereastră de `N/2`, statistica pe eșantionul
  complet trebuie `t ≥ 2,77`, adică **de două ori mai multe meciuri** și un
  efect minim detectabil cu **41%** mai mare. Nu e o rafinare, e o altă decizie.

### 7.3 Riscul de perioadă

Banda ADR-082 are **229 de rânduri** și doar **23 scorabile** (29 oct), toate din
27-28 octombrie. Orice concluzie pe ea e, azi, o concluzie despre două zile — și
de aceea §4.3 o prezintă ca primă citire, nu ca dovadă.

---

## 8. Erori proprii consemnate, fiindcă au schimbat concluzia

1. **„Avantajul lui XGBoost s-a subțiat la o metrică din trei"** — fals. Toate
   trei deltele îl favorizează în continuare; s-a pierdut *semnificația* pe două,
   nu direcția și nici mărimea.
2. **„XGBoost e tiparul slab, blend cel solid"** — fals ca ierarhie. Deltele de
   scor propriu ale lui XGBoost sunt de **două ori** mai mari; el cade pe `n`.
3. **„Reperul extern e optimist, deci există headroom, deci se redeschide
   discuția accidentărilor"** — **infirmat de măsurătoare**, și e eroarea cea mai
   instructivă: construisem lanțul din literatură, nu din date. Pe cele 209
   meciuri unde `opening ≠ closing`, captura numită „închidere" e luată în medie
   cu **54,8 ore** înainte de fluier și e cu 0,48pp **mai slabă**. Reprodus pe
   2071 de meciuri: favorit după deschidere 54,76%, după „închidere" 54,71% —
   **titlul proiectului nu se mișcă**. Defectul de etichetă e real, consecința pe
   care i-o atașasem nu e.
4. **[REVIZIA 2] „XGBoost e proiectat să treacă poarta actuală în jurul 1-2
   noiembrie"** — **neconfirmat de datele ulterioare**, vezi §5.5. Proiecția
   presupunea efect constant și scalare `t ∝ √n`. Două zile noi au testat-o: la
   `n = 370`, `brier_significant` e în continuare `false`, iar efectul a scăzut
   (−0,0206 → −0,0196), ceea ce **anulează** câștigul din `n`. Lecția:
   o extrapolare care presupune efect constant se etichetează ca ipoteză și se
   re-testează la fiecare punct nou — nu se raportează ca așteptare, și cu atât
   mai puțin cu o dată atașată.

---

## 9. Implementare — NEÎNCEPUTĂ. Tot ce urmează e PLAN, nu aprobare

**Nicio linie de cod nu a fost scrisă.** Niciuna dintre etapele de mai jos nu e
aprobată prin acceptarea acestui document: fiecare cere o aprobare proprie, iar
activarea (Faza 6) una explicit separată. Ordinea e obligatorie.

### Etapa 0 — PRELIMINARĂ OBLIGATORIE: idempotența candidaturii

> **[REVIZIA 2 — etapă nouă.]** Fără ea, **întregul ADR e inert** pentru exact
> modelele pentru care a fost scris (vezi §6.1). Are valoare **independentă**:
> defectul lovește și poarta actuală de 3/3.

- **Fișier**: `learning_core/continuous_learning.py`,
  `_handle_candidate_for_promotion` (azi liniile 331-335) și apelantul unic
  (linia 318).
- **Modificare minimă**: handlerul primește starea deja citită de apelant la
  linia 314 și **sare** tranziția dacă e `SUCCEEDED`; orice altă stare
  (`REJECTED`, `PROMOTED`) eșuează în continuare **zgomotos**, ca azi.
- **NU se atinge `ALLOWED_TRANSITIONS`** și **NU** se face `transition()`
  idempotentă global — o tranziție genuin invalidă trebuie să eșueze.
- **De ce citirea stării de la linia 314 e sigură**: a sări înseamnă a **nu
  scrie**, deci nu există cursă de pierdut; iar calea de promovare
  **revalidează** la execuție (`promotion_service.py:80` și 88-90), deci o
  stare învechită aici nu poate produce o promovare greșită, doar o propunere
  care va fi respinsă.
- **Limita de verificare, declarată**: nu se poate confirma live până la
  următoarea candidatură reală. Acceptare = teste + mutații verzi, plus absența
  erorii „tranzitie SUCCEEDED" în `automation_runs` la prima candidatură.

### Etapa 1 — determinismul (§4.4)
Seed-ul, varianta A, `blake2b`, `random.Random` local. Zero schimbare de
contract. Fără reproductibilitate nu se poate măsura dacă restul funcționează.

### Etapa 2 — flagul
`promotion_gate_proper_scoring_enabled`, implicit `False`; o rulare de noapte
care demonstrează comportament **identic** cu flagul oprit.

### Etapa 3 — criteriul
§4.1 + §4.2 în `evaluate_experiment`, sub flag, cu eligibilitatea §4.6.

### Etapa 4 — divulgarea comparației cu campionul (§4.3)

> **[REVIZIA 2 — CORECTAT.]** Revizia 1 scria că „cere o funcție nouă de citire
> a benzii campionului". **Fals**:
> `supabase_client.get_champion_lane_outcomes(algorithm_family, league_scope,
> training_run_id, …)` **există deja** (linia 1146), cu paginare keyset și listă
> goală la eroare. Se **refolosește**; nu se scrie cititor nou.

Intră în `evidence`, **nu** în poartă. Nu există prag de `n` de aprobat, fiindcă
nu există poartă — vezi §4.3 și §7.2.

### Etapa 5 — teste
Unitare + integrare + regresie + **negative** (caz degenerat, bandă goală, `n`
sub orice prag, fan-out prezent), plus o gardă care cade dacă poarta veche devine
inaccesibilă cu flagul oprit.

### Etapa 6 — activarea
**Decizie separată**, cu SQL arătat și confirmat (North Star #6).

### Etapa 7 — mai târziu: divulgarea poate deveni poartă
Doar prin **split-sample** (§7.2), când banda are volum. Nu face parte din acest
ADR; e consemnată ca direcție, nu ca angajament.

## 10. Verificare cerută înainte de activare

0. **[REVIZIA 2]** Etapa 0 ⇒ o a doua zi consecutivă de candidatură produce
   **propunere**, nu `failed`. Verificabil în `automation_runs`: zero rânduri
   noi cu „tranzitie SUCCEEDED esuata". Plus: un Challenger în `REJECTED` sau
   `PROMOTED` eșuează în continuare, zgomotos.
1. Flagul oprit ⇒ verdicte **identice** cu cele de azi, pe o rulare completă.
2. Seed-ul ⇒ două evaluări pe aceleași date dau **același** verdict (azi:
   16,5% / 7,5% rată de basculare).
3. Testul de inundare **re-rulat** după implementare, pe cod, nu pe SQL ad-hoc —
   aceleași cifre ca §5.2, altfel implementarea nu e criteriul descris aici.
4. `6e7265c5` rămâne **respins** de gardă (martorul pozitiv din §5.3).
5. Calea de predicție neatinsă: `git diff` gol pe `oracle_engine.py`,
   `feature_engine.py`, `ml_predictor.py`, `recalibration.py`, `app.py`,
   `oracle_api.py`.
6. **[REVIZIA 2]** Eligibilitatea §4.6 respectată: un experiment pe
   `match_history_frozen` (azi: `flashscore_team_dna/v1`) primește în continuare
   poarta **3/3**, verificat pe un caz real, nu doar pe un fals.
