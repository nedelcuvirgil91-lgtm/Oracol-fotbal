# ADR-082 — Banda de predicții a campionului promovat, și atribuirea corectă în Champion Guardian

**Status**: **ACCEPTED** (aprobat explicit de proprietarul produsului, 2026-10-27)
**Data**: 2026-10-27
**Notă de revizie**: aprobat după **două corecții făcute în timpul scrierii**,
ambele marcate în text și ambele găsite verificând, nu deducând — §2.3 (un
apelant inexistent) și §2.4 (un `CHECK` pe `baseline_source` care ar fi cerut o
migrare). A doua a dus la o **simplificare reală**: un singur flag în loc de
două, iar schimbarea de sursă a gardianului devine necondiționată.
**Autor**: sesiune Claude Code, la cererea proprietarului produsului
**Înlocuiește / amendează**: **amendează ADR-037 §9** (atribuirea temporală a
ferestrei de sănătate), a cărei precondiție a fost invalidată tacit de
ADR-051/052. Nu atinge ADR-002 (promovarea rămâne exclusiv umană), nici
ADR-018 (verdicte imuabile).
**Depinde de**: ADR-073 (intrările de la servire persistate) — fără el,
validarea din §6 ar fi imposibilă.
**Precondiție deja livrată**: P6.0-c, paginarea ferestrei gardianului,
`main` @ `b153acd`.

---

## 0. De ce acest ADR e mai mic decât cel pe care l-am anunțat

Îl descrisesem ca „un scriitor nou plus o schimbare de sursă în gardian" —
adică o construcție. **Verificarea înainte de scriere l-a redus la o cablare**,
și două fapte măsurate sunt motivul:

1. **Predicția campionului se calculează DEJA la fiecare meci servit** și se
   aruncă. `oracle_engine.py:2202` o scrie în
   `pred.blend_v1_champion_prediction`, iar comentariul de deasupra spune
   explicit *„nu atinge raw_predictions/prob_home_win/**shadow_predictions**"*.
   Flagul `blend_v1_champion_display_enabled` e **`true`** în producție, deci
   codul rulează în fiecare noapte. Nu trebuie construită o predicție — trebuie
   persistată una existentă. **Aceeași formă ca D-2/ADR-073**: *„datele nu
   trebuie construite — se aruncă la ultima linie"*.

2. **Banda nouă nu cere nicio schimbare de schemă.** Verificat în producție:
   `shadow_predictions` are **zero `CHECK` pe `experiment_group`** (singurele
   constrângeri sunt cheia primară și `shadow_predictions_invalidation_coerenta`),
   iar cheia de conflict e
   `fixture_id, experiment_name, experiment_version, experiment_group,
   processing_stage` — deci o valoare nouă de grup e un rând distinct, fără
   migrare și fără să atingă niciun rând existent.

Deci ce urmează descrie o cablare cu flag, nu un proiect.

---

## 1. Context — ce s-a măsurat, element cu element

### 1.1 Champion Guardian măsoară PERIOADA, nu MODELUL

`champion_guardian._live_metrics()` și `_mean_brier()` citesc
`prob_home_pred`/`prob_draw_pred`/`prob_away_pred` din `match_history`. Prin
`oracle_engine.py:2279` (`_cache_prediction`), acele coloane sunt **ieșirea
Poisson a lui Oracle** — singurul scriitor al probabilității servite e linia
2095, iar ea vine din `_poisson_model`.

Deci gardianul care ar trebui să detecteze un campion care se degradează
**raportează sănătatea lui Oracle, sub numele campionului.** Și Rollback
Engine se declanșează din verdictul lui, deci tot mecanismul de siguranță e
cablat la metricile motorului greșit.

### 1.2 Nu e un bug — e o precondiție care a expirat

`supabase_client.get_champion_served_outcomes()`, liniile 1010-1012, o spune
singură:

> *„Atribuire temporală (ADR-037 §9, acceptată Stage 1): `since_date` =
> promoted_at-ul campionului ca dată-only, **fiindcă `prob_*_pred` nu poartă
> identitatea modelului servitor**."*

ADR-037 §9 a **acceptat explicit** aproximarea: *nu putem spune ce model a
produs predicția, deci atribuim campionului tot ce s-a servit după promovarea
lui.* Aproximarea era corectă **sub premisa că campionul servește**.

ADR-051/052 a desființat orice blend in-place și a făcut campionul un câmp de
afișare. Premisa a dispărut, iar aproximarea a devenit, tăcut, o **atribuire
greșită**.

> Aceeași clasă deja documentată în `CLAUDE.md` la ADR-077: *„un ADR (044/045)
> a invalidat tacit precondiția altui ADR (041)"*. De aceea reparația e un
> **amendament**, nu o editare: retragem o premisă, nu corectăm o linie.

### 1.3 Amploarea atribuirii greșite, măsurată

Fereastra reală a campionului activ (`blend_v1/8ac89c70`, promovat
2026-08-23 09:36:27, `superseded_at` NULL, activ de 65 de zile):

| | meciuri | % |
|---|---:|---:|
| în fereastra gardianului (`kickoff_date >= 2026-08-23`) | **1135** | 100% |
| cu o predicție **proprie** a campionului | **172** | 15,2% |
| **fără** | **963** | **84,8%** |

Cele 172 se opresc imediat: **161 în august** (ultimul 31 aug), 9 în septembrie
(ultimul 15 sept), 2 în octombrie. **De la 1 septembrie, fereastra e ~99%
meciuri despre care campionul n-a spus nimic.**

Pe cele 383 de meciuri unde comparația e posibilă, substituția nu e o eroare de
rotunjire: Brier 0,6383 (Oracle, ce citește gardianul) vs **0,6130** (campionul,
ce ar trebui), acuratețe 0,4491 vs **0,5013**, iar **pronosticul diferă pe
69 din 383 (18,0%)**.

**Aritmetica pragului**, care face cifra decisivă:

```
baseline de promovare (challenger_evaluations, n=207)          = 0,6225
BASELINE_DEGRADATION_MARGIN                                    = 0,10 relativ
prag de alarmă                                                 = 0,6848
buget absolut de degradare                                     = 0,0623
eroarea de substituție (Oracle în loc de campion)              = 0,0253
```

> **40,6% din bugetul de degradare e consumat de măsurarea modelului greșit,
> înainte ca vreo degradare reală să se întâmple.**

Direcția e contraintuitivă și se consemnează: Oracle e *mai slab* decât
campionul, deci substituția împinge spre **alarmă falsă** — ar acuza un campion
sănătos — nu spre orbire. Dar nu se garantează că rămâne așa: campionul e
înghețat, Oracle primește intrări proaspete zilnic.

### 1.4 Cauza de bază: campionul încetează să producă predicții la promovare

`learning_core/challenger_shadow.log_shadow_for_active_challenger`, linia 94:
*„Nu face nimic (False) dacă nu există **Challenger activ**"*. Un model promovat
iese din FSM, deci nimic nu-l mai loghează.

Măsurat: **394 control + 394 treatment, ultima scriere 2026-08-23 09:23:17** —
cu **13 minute** înainte de promovarea de la 09:36:27. **Zero rânduri în 65 de
zile.**

**De ce asta e blocantul, nu un detaliu**: reparând doar §1.1 (gardianul să
citească predicțiile campionului) fără §1.4, gardianul găsește 0 rânduri de la
1 septembrie, cade pe `MIN_MATCHES_FOR_HEALTH = 30` și întoarce
`insufficient_data` la nesfârșit. Onest, dar inutil — am schimbat un gardian
care măsoară greșit cu unul care tace.

### 1.5 Riscul de azi e ZERO, și asta schimbă încadrarea

| Verificare | Rezultat |
|---|---|
| `champion_health_evaluations` | **0 rânduri** — gardianul n-a rulat niciodată |
| `champion_guardian_enabled` în `model_config` | **ABSENT** |
| `champion_guardian_proposals_enabled` | **ABSENT** |

ADR-037 R4 n-a fost activat niciodată, exact cum prevede planul de deployment.
**Deci nimic fals nu se raportează azi** — nu reparăm un indicator care induce
în eroare, ci o **precondiție a activării**. Toată munca din acest ADR poate fi
livrată cu efect zero în producție.

Inversul e însă adevărat și tare: **activarea ADR-037 R4 azi ar porni un
gardian care măsoară alt model.**

### 1.6 Ce a dovedit relurea (rularea 40518633429, 2026-10-27)

`scripts/replay_champion_on_persisted_inputs.py`, pe intrările persistate de
ADR-073:

**Faza 1 — martorul de control.** Relurea Challengerului ACTIV
`blend_v1/174e7e17` contra rândurilor lui logate **live**:

```
reluate: 512 · fără rând live: 0 · relure eșuată: 0
divergență maximă: 0.000e+00 · medie: 0.000e+00 · peste 1e-6: 0 / 512
```

**Zero, nu „sub toleranță".** Metoda de reconstrucție e exactă, nu plauzibilă.
Asta e piesa pe care acest ADR se sprijină: banda nouă are un martor contra
căruia se poate dovedi, nu doar testa.

**Faza 2 — campionul, pe 332 de meciuri terminate (15-26 oct), fără scurgere
temporală** (ambele modele antrenate înainte de 15 oct):

| Metrică | Oracle servit | Campion `8ac89c70` | \|t\| | verdict |
|---|---:|---:|---:|:--|
| Brier *(mai mic = mai bun)* | 0,6100 | **0,5960** | **3,07** | ✅ dovedit mai bun |
| Log-loss *(mai mic = mai bun)* | 1,0198 | **0,9977** | **3,00** | ✅ dovedit mai bun |
| Acuratețe *(mai mare = mai bun)* | 0,4970 | 0,5151 | 1,61 | ❔ incert |

Verificat independent din rândurile logate live (altă cale decât relurea):
`acc_oracle` 0,4970, `acc_martor` 0,5151, `brier_martor` 0,5965 — identice.
Acuratețea e incertă fiindcă blend-ul schimbă pronosticul pe **17 din 332**
meciuri, iar diferența netă e de **6 meciuri**; Brier folosește probabilitatea
pe toate 332, de aceea are rezoluție unde acuratețea n-are.

**Două ipoteze ale mele, infirmate**: campionul **nu** s-a erodat în 65 de zile;
iar Challengerul reantrenat **nu** e mai bun decât el (Brier 0,5965 vs 0,5960).
Reantrenarea n-a cumpărat nimic măsurabil.

---

## 2. Decizie

### 2.1 O bandă nouă în `shadow_predictions`: `experiment_group = 'champion'`

Un campion PROMOVAT continuă să producă, la fiecare meci servit, un rând
propriu de predicție.

- `experiment_name` = familia campionului (`blend_v1`)
- `experiment_version` = `training_run_id` al campionului activ
- `experiment_group` = **`'champion'`** (valoare nouă)
- `processing_stage` = `'final'`

**Zero schemă nouă**, verificat: nu există `CHECK` pe `experiment_group`, iar
cheia de conflict include grupul — deci rândurile `treatment` istorice ale
aceluiași `training_run_id` (cele 394 din august) **nu sunt atinse și nu se
rescriu**. Dovada că problema a existat se păstrează (North Star #9, aceeași
regulă ca la ADR-072 §Consecințe).

**Se scrie și rândul `control` pereche** pentru acel `(experiment_name,
experiment_version)`. Împerecherea e verificată în cod, nu presupusă:
`shadow_testing.py:457-462` cere `experiment_name` + `experiment_version` +
`experiment_group='control'` + `processing_stage='final'`, iar seria de
`control` a campionului se oprește și ea pe 23 august — deci fără rândul
pereche, banda `'champion'` ar fi nepereche și neevaluabilă.

**Rândul `control` al benzii NU primește `feature_metadata`** (înregistrarea
ADR-073). Motivul e măsurat, nu economic: pe toate cele **512** meciuri comune,
rândul `control` e **identic bit cu bit** între familii — 0 probabilități
diferite, 0 `ml_features` diferite, divergență maximă `0,0e-10`. O a treia
copie ar fi duplicare pură, la ~1065 de octeți pe rând (volum măsurat în
ADR-073).

### 2.2 Scriitorul: un adaptor nou, nu o cale nouă

`learning_core/champion_shadow.py`, simetric cu
`learning_core/blend_challenger_shadow.py`. Oracle Engine primește
`_log_champion_shadow()`, care **nu** atinge `shadow_testing` direct —
frontiera impusă de ADR-033/ADR-056 (Oracle Engine → Adaptor → persistență)
rămâne neschimbată.

Predicția **nu se recalculează**: se refolosește `pred.blend_v1_champion_prediction`,
deja calculat la linia 2202. Deci calea de predicție nu se atinge, iar
reconstrucția nu poate divergea de ce s-a afișat.

### 2.3 Gardianul citește predicțiile campionului

Champion Guardian primește o sursă nouă — `get_champion_lane_outcomes()` —
care citește banda `'champion'` a campionului activ, împerecheată cu
`match_history.actual_result`.

> **[CORECTAT în timpul scrierii]** Prima versiune a acestui paragraf spunea
> că funcția veche se păstrează fiindcă *„ștergerea ei ar rupe
> `prediction_evaluation.py`, consumator distinct"*. **Fals, verificat**:
> `get_champion_served_outcomes` are **exact un apelant** —
> `champion_guardian.py:104` — iar `prediction_evaluation.py` citește
> `match_history.prob_*_pred` **direct**, fără să treacă prin ea. Scrisesem
> justificarea din tiparul D-3, nu din măsurătoare.

**Iar odată ce §2.4 a eliminat al doilea flag, funcția veche rămâne cu ZERO
apelanți — adică devine cod mort în clipa livrării.** Nu i se inventează un
consumator. Se consemnează ca **restanță explicită de ștergere**, nu se lasă în
repo „pentru orice eventualitate", cum au rămas POC-ul API-Football 34 de zile
și `_fetch_elo_ratings` până la Phase 8. Nu se șterge în acest ADR fiindcă
ștergerea de cod mort e o decizie proprie, cu propriul audit (regula din
`CLAUDE.md`: nicio „curățenie preventivă").

**Un fapt incomod, consemnat în loc de ascuns**: P6.0-c, merge-uit acum câteva
ore, a paginat exact funcția pe care acest ADR o orfanizează. Nu a fost muncă
irosită, și motivul e verificabil: la momentul reparației, funcția era
**singura** sursă a gardianului, iar activarea ADR-037 R4 era o posibilitate
vie — o activare înainte de ADR-082 ar fi pornit un gardian care, pe lângă
atribuirea greșită, ar fi citit și o fereastră trunchiată la 1000 din 1135.
Mai mult: **reparația a fost instrumentul de măsurare care a produs acest
ADR** — cifrele 1135 / 172 / 963 au ieșit din analiza ferestrei pe care o
reparam. Lecția de ordine rămâne însă reală: o reparație pe un consumator
unic merită întrebarea „mai există consumatorul mâine?" înainte, nu după.

> **[CORECTAT în timpul scrierii, a doua oară]** Prima versiune spunea că
> *„`baseline_source` câștigă o valoare nouă, `'champion_lane'`"*. **Greșit pe
> două planuri, verificat**: (a) coloana are un `CHECK` —
> `baseline_source IN ('promotion_evaluation','trend_only','manual_override')`,
> migrarea 015 linia 76 — deci o valoare nouă ar cere o **migrare**, pe care
> §0 pretindea că acest ADR n-o are; (b) `baseline_source` descrie **de unde
> vine baseline-ul** pentru dimensiunea 2, nu de unde vine **fereastra**. Două
> fapte diferite într-o coloană ar fi exact confuzia pe care ADR-072 a
> rezolvat-o separând sursele.

**`baseline_source` nu se atinge. Zero migrare, confirmat.** Semantica lui
rămâne neschimbată.

### 2.4 UN flag, nu două — iar schimbarea de sursă a gardianului NU e flagată

Varianta cu două flaguri, pe care o propusesem, exista ca să permită o comutare
graduală a sursei. **E inutilă, și motivul e măsurat**: gardianul are **0
rânduri** în `champion_health_evaluations` și e dormant (ambele flaguri de
ADR-037 R4 absente). Nu există „comportament curent" de păstrat în spatele unui
flag — există o citire dovedit greșită, într-o componentă care n-a rulat
niciodată.

| Flag | Ce pornește | Implicit |
|---|---|---|
| `champion_shadow_logging_enabled` | scrierea benzii `'champion'` | **False** (North Star #3) |

Schimbarea sursei gardianului e **necondiționată**: citește banda, punct. Cât
banda e goală sau sub `MIN_MATCHES_FOR_HEALTH = 30`, gardianul întoarce
`insufficient_data` — care e **starea onestă**, nu un defect, și e deja
comportamentul lui pentru `n` mic (`_classify_champion_health`).

**Trei consecințe bune ale simplificării**, toate verificabile:
1. Dispare riscul pe care îl semnalasem la varianta cu două flaguri —
   „activate împreună, gardianul ar părea defect". Nu mai există ordine de
   activare de respectat.
2. Dispare ambiguitatea de evidență: fiecare rând care va exista vreodată în
   `champion_health_evaluations` e scris din bandă. Nu e nevoie de un marcator
   de sursă fiindcă nu există rânduri vechi de care să-l distingi.
3. Un gardian activat din greșeală **nu poate** mai raporta sănătatea lui
   Oracle sub numele campionului. Cu flag, acea cale ar fi rămas vie.

---

## 3. Ce NU se decide aici, deliberat

- **Cablarea căii de servire** (P6, variantele V0/V3/V1). Acest ADR face
  campionul **măsurabil și monitorizabil**, nu servit. `prob_home_win` are în
  continuare exact un scriitor, linia 2095.
- **Activarea ADR-037 R4.** Rămâne o decizie separată, cu propriul plan.
- **D-3** — ceilalți consumatori ai coloanelor înghețate
  (`prediction_evaluation.py`). Semantici proprii, neanalizate.
- **Filtrul de rânduri supersedate** în selecția gardianului (Discovery Rule,
  semnalat la P6.0-c: 0 din 1135 azi). Criteriu de selecție, nu atribuire.
- **Retragerea campionului.** Relurea arată că nu e justificată (2 din 3
  metrici dovedit mai bune), dar dacă vreodată ar fi, operația e
  **supersedarea**, niciodată ștergerea — `model_champions_guard` o impune.

---

## 4. Consecințe

**Pozitive**
- Gardianul măsoară modelul pe care îl numește. Rollback Engine primește un
  semnal despre campion, nu despre Oracle.
- Un campion promovat nu mai devine invizibil în clipa promovării.
- **Decizia P6 devine măsurabilă continuu**: banda produce, zi de zi,
  comparația campion-contra-Oracle pe meciurile servite. V3 și V1 se pot decide
  pe o serie, nu pe o relure punctuală.
- Relurea devine **martor permanent**: banda live trebuie să se potrivească cu
  ce reconstruiește `replay_champion_on_persisted_inputs.py`. Un scriitor nou
  cu martor exact (divergență 0) e o situație rară în proiect.

**Negative, acceptate**
- **Volum**: 2 rânduri în plus per meci servit, fără `feature_metadata`. De
  măsurat exact înainte de activare, prin aceeași metodă ca ADR-073 (lungimea
  serializată reală, nu estimată — acolo estimarea din plan a fost greșită de
  3×).
- **Un al cincilea grup** în `shadow_predictions`. Orice interogare care
  presupune că grupurile sunt doar `control`/`treatment` trebuie verificată;
  §5 cere inventarul lor explicit.
- `evaluate_experiment()` nu se atinge, deci nu evaluează banda `'champion'` —
  corect: un campion nu e un candidat de promovat (ADR-080). Dar e o asimetrie
  de reținut.

**Neutre**
- Zero efect pe calea de predicție. Zero rânduri istorice rescrise.
- Cu ambele flaguri oprite, comportamentul în producție e identic cu cel de azi.

---

## 5. Gărzi cerute înainte de livrare

1. **Banda nu atinge `prob_home_win`** — gardă AST pe `oracle_engine.py`, în
   plus față de verificarea `git diff` pe calea de predicție.
2. **Scrierea trece prin adaptor**, niciodată direct la `shadow_testing` din
   Oracle Engine — gardă AST, tiparul deja folosit la ADR-073 pentru poarta
   flagului.
3. **Predicția nu se recalculează**: banda citește
   `pred.blend_v1_champion_prediction`, nu reapelează predictorul. Un al doilea
   apel ar putea divergea tăcut de ce s-a afișat.
4. **`feature_metadata` NU ajunge pe banda `'champion'`** — ar fi o afirmație
   falsă despre cine a produs intrările (regula ADR-073, care pasează
   înregistrarea exclusiv apelului `control`).
5. **Inventarul consumatorilor de `experiment_group`** — orice `.eq("experiment_group", …)`
   și orice filtrare în Python, enumerate și verificate față de valoarea nouă.
6. **Gardianul nu mai poate citi `prob_*_pred`** — gardă care cade dacă
   vechea sursă reapare pe calea lui. Fără flag, singura protecție e structura.
7. **Gardianul cade pe `insufficient_data`, nu pe o fereastră parțială**, când
   banda are < `MIN_MATCHES_FOR_HEALTH` rânduri. O fereastră incompletă care
   arată ca una completă e defectul reparat la P6.0-c.
8. **`baseline_source` rămâne în mulțimea permisă de `CHECK`** — gardă care
   cade dacă vreun cod scrie o valoare pe care baza o va respinge la rulare.
   Altfel defectul s-ar manifesta abia la prima activare, în producție.

---

## 6. Verificare cerută înainte de ACTIVARE

Un singur flag de activat, `champion_shadow_logging_enabled`. Schimbarea de
sursă a gardianului nu se activează — se livrează, cu efect zero cât gardianul
e dormant (§1.5).

1. O rulare de noapte cu flagul **oprit**, care confirmă comportament identic:
   zero rânduri cu `experiment_group = 'champion'`.
2. După activare: rândurile apar, `experiment_version` = `training_run_id` al
   campionului activ, `feature_metadata` **gol** pe banda `'champion'`.
3. **Martorul de control, obligatoriu**: pe meciurile acoperite de ambele,
   banda live trebuie să coincidă cu relurea din
   `replay_champion_on_persisted_inputs.py`. Divergența acceptată e aceeași
   care s-a măsurat la Faza 1 — **zero**. Orice altceva înseamnă că scriitorul
   nou nu scrie ce credem.
4. Volumul real măsurat, nu estimat.

**Separat, la o eventuală activare a ADR-037 R4** (decizie proprie, nu a
acestui ADR), și numai după ce banda are ≥ 30 de rânduri scorabile:

5. `n_matches_evaluated` al primei evaluări corespunde numărului de rânduri din
   **bandă**, nu celor 1135 ale ferestrei vechi. Aceea e verificarea care
   dovedește, dintr-o singură cifră, că atribuirea s-a corectat.
6. Verdictul se compară explicit cu cel pe care sursa veche l-ar fi dat, pe
   aceeași zi, read-only. **Se așteaptă o diferență** — e corectarea unei
   atribuiri, nu o regresie. Aceeași notă ca la ADR-072 D2.
7. Până atunci, orice rulare a gardianului trebuie să dea `insufficient_data`
   **fără să persiste** — `evaluate_champion_health` scrie doar la `n >= 1`.
   O evaluare persistată pe `n` mic ar fi primul semn că poarta nu ține.

`UPDATE model_config` se arată și se confirmă explicit înainte de rulare
(North Star #6), cu amprenta `md5(data − cheia_nouă)` înainte și după, plus
`updated_at = now()` — recomandarea D-14, pe care activările anterioare au
omis-o, lăsând lanțul de amprente rupt.

---

## 7. Alternative respinse

**(a) Gardianul deduce predicția campionului la citire, reluând-o din
`feature_metadata`.** Respinsă: ar face evaluarea de sănătate să depindă de
artefactul din Storage și de ADR-073 fiind activ — o dependență „în sus"
(North Star #10), într-o componentă care trebuie să rămână simplă. Relurea e
un instrument de analiză, nu o sursă de producție.

**(b) `prob_*_pred` câștigă o coloană cu identitatea modelului servitor.**
Ar repara atribuirea la rădăcină, dar presupune că acele coloane vor purta
vreodată altceva decât Oracle — adică presupune decizia P6, pe care acest ADR
o lasă deschisă deliberat. Se poate relua dacă V1 e vreodată aprobat.

**(c) Banda refolosește `experiment_group = 'treatment'`.** Respinsă: ar
amesteca, sub același `training_run_id`, predicții făcute ca Challenger cu
predicții făcute ca Campion — două roluri cu semantici diferite, iar seria ar
avea o gaură de 65 de zile la mijloc, fără nimic care s-o explice în date.

**(d) Se oprește producerea de campioni până se decide P6.** Respinsă: ar
opri singurul mecanism care funcționează, pentru a evita o problemă de
observabilitate.

---

## 8. Ce ar schimba decizia

- Dacă relurea ar fi arătat campionul **mai slab** decât Oracle, operația
  corectă ar fi fost supersedarea lui, nu o bandă de monitorizare. Nu e cazul:
  2 din 3 dovedit mai bune, `t ≈ 3`.
- Dacă `experiment_group` ar fi avut un `CHECK`, acest ADR ar fi inclus o
  migrare și ar fi intrat sub regula `GRANT` de la 2026-10-30. Verificat: nu
  are.
- Dacă P6 se decide pentru **V0** („rămâne așa"), acest ADR **rămâne
  justificat**: un V0 onest tot are nevoie de un gardian care măsoară campionul
  real, altfel ținem o protecție care minte.
