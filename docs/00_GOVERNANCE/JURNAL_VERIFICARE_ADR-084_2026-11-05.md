# Jurnal de verificare — ADR-084, cele trei verificări cerute înainte de aprobare

**Stare: JURNAL DE VERIFICARE. NU e un ADR. Nu decide nimic, nu autorizează nicio
linie de cod, nu modifică nicio poartă, nu activează nici un flag.**

Înregistrează ce s-a măsurat pe 2026-11-05, read-only, pe producție
(`Prediction`, `gtlpyxzocacaqyompkwe`), la cererea explicită a proprietarului
produsului, plus concluzia formală pe care acesta a luat-o în urma lor.

> **⚠️ CITEȘTE §3bis ÎNAINTE DE §3.** Documentul a fost prezentat abia pe
> **2026-11-09**, după patru zile de inactivitate. Cifrele din §3 sunt corecte
> **la data lor** și au fost depășite: C4b a crescut de la 20 la 55 de meciuri,
> iar o cohortă nouă (C5, n=137) **trece pe toate trei metricile**. Decizia
> formală din §7 rămâne neschimbată, cu data ei.

Documentul se citește împreună cu `ADR-084` (**care rămâne NEMODIFICAT**),
`DE_URMARIT.md` §18.1 și `CLAUDE.md` D-16 / D-17.

> **⚠️ Precizare care contează mai mult decât rezultatele:** propunerea de
> revizuire metodologică din §6 (confirmare pe cohorte disjuncte) e o
> **PROPUNERE**. Nu e o regulă aprobată, nu e un amendament la ADR-084, și nu se
> citează nicăieri ca și cum ar fi în vigoare. Poarta de promovare în efect azi
> rămâne, neatinsă, cea din `shadow_testing.evaluate_experiment()` — Brier ȘI
> log-loss ȘI acuratețe simultan semnificative (North Star #2).

---

## §0 — Ce a declanșat verificările

Pe 2026-11-05 toate trei condițiile declanșatorului din ADR-084 §11 s-au
raportat îndeplinite: (1) trei zile de evaluare cu codul ADR-085 pe `main`
(3, 4, 5 nov; `1b3c3ef` aterizat 2 nov 20:06 UTC); (2) partiția pe oră dispărută
pe cohorta post-reparație; (3) verdictele lui `blend_v1/174e7e17` neoscilante,
13-14 zile la rând.

Proprietarul produsului **nu a aprobat** revizia 3 și a cerut, înainte de orice
decizie, trei verificări independente: integritatea baseline-ului (nu doar
proveniența), auditul istoric prin replay pentru `4e17c737` și `6e7265c5`, și
stabilitatea pe **cohorte temporale genuin independente** — cu observația, care
s-a dovedit decisivă, că *două ferestre consecutive care conțin aproape aceleași
meciuri nu sunt două confirmări independente*.

Documentul consemnează și **patru retrageri de afirmații proprii ale
asistentului** (§5), fiindcă trei dintre ele au fost făcute în aceeași sesiune
în care au fost infirmate.

---

## §1 — Verificarea 1: baseline. Proveniență ✅ · fidelitate ✅ · corectitudine ❌ NEDEMONSTRATĂ

Distincția a fost ridicată de proprietarul produsului, contra unei recomandări a
asistentului care le confunda:

> `baseline_source = 'shadow_control'` dovedește **proveniența**. Nu dovedește
> **corectitudinea predicțiilor din baseline.** Sunt două proprietăți diferite.

### §1.1 Proveniență și acoperire

| verificare | rezultat |
|---|---|
| `baseline_source` pe evaluările lui `174e7e17` | `shadow_control` pe **22 din 40** (restul 18 = `insufficient_data`, dinainte de prag) |
| acoperire `control` pe cohorta lui `4e17c737` | **481 / 481**, 0 lipsă |
| acoperire `control` pe cohorta lui `6e7265c5` | **470 / 470**, 0 lipsă |

Acoperirea completă contează fiindcă `shadow_testing.rezolva_sursa_baseline()`
cade pe `match_history_frozen` pentru **toate** meciurile la orice lipsă — un
verdict pe baseline-uri mixte ar fi neinterpretabil (ADR-072 D2).

### §1.2 Fidelitatea înregistrării — martor independent

Martorul: `engine_comparison_snapshots.oracle_prob_*`, scris de
`validation_framework.py` (cadrul ADR-052) — **alt cod** decât
`shadow_testing.log_shadow_prediction()`, care scrie rândul `control`.

| măsurătoare | valoare |
|---|---|
| perechi comparate (`174e7e17`, bandă `control`) | **878** |
| divergență maximă pe oricare dintre cele trei probabilități | **0,00000000** |
| rânduri identice bit cu bit | **878 / 878** |
| divergențe ≥ 1pp | **0** |

### §1.3 🔴 Ce NU dovedește asta — golul se păstrează explicit

**Ambii scriitori primesc același obiect `pred`, în același proces.** Deci
divergența zero dovedește că rândul `control` înregistrează **fidel** ce a
produs motorul în acea rulare: nu e stătut, nu e transcris greșit, nu e al altui
meci. **Nu dovedește că predicția e corectă.**

**Iar verificarea completă nu e construibilă din datele de azi.** Singurul
candidat de martor care nu împarte obiectul `pred` e
`match_history.prob_*_pred`, dar acela e înghețat *first-writer-wins* prin RPC-ul
canonic (`COALESCE(m.existent, p->nou)`, migrarea 053) — divergența acolo e
**prevăzută prin design**, deci nu poate distinge o eroare de o vechime.

Cerința „integritate demonstrabilă" e astăzi satisfăcută **doar în forma slabă**.
Se consemnează ca gol, nu ca verificare bifată.

**Observație colaterală, măsurată, nu alarmă**: probabilitățile din banda
`control` însumează în medie **0,999359**, nu 1 — sub-normalizare reală, în
toleranța de 2e-3 pe care proiectul o folosește deja în propriile assert-uri.
Neinvestigată, consemnată.

---

## §2 — Verificarea 2: auditul istoric prin replay

### §2.1 Metoda, și validarea ei pe un martor pozitiv

Poarta reală folosește `_paired_bootstrap` (`shadow_testing.py:290`) —
bootstrap percentil, 2000 de iterații, pe diferențe perechi;
`significant = ci_high < 0` pentru Brier/log-loss, `ci_low > 0` pentru
acuratețe.

Replay-ul folosește **aproximarea normală** a aceluiași interval
(`medie ± 1,96 · SE`), calculată în SQL. **Nu se folosește înainte de a fi
validată contra verdictelor stocate**, pe cohorta exactă a fiecărui verdict
(`evaluation_window_start` … `evaluation_window_end`):

| artefact | n stocat | n replay | Δbrier stocat → replay | Δlog-loss stocat → replay | Δacc stocat → replay |
|---|---:|---:|---|---|---|
| `4e17c737` | 479 | 481 | −0,0247 → **−0,0245** | −0,0394 → **−0,0390** | +1,88 → **+1,87pp** |
| `6e7265c5` | 461 | 470 | −0,0166 → **−0,0174** | −0,0247 → **−0,0265** | −1,74 → **−1,70pp** |

Estimările punctuale reproduc la a 3-4-a zecimală. Flagurile de semnificație
coincid pe **5 din 6**.

> **🔴 Limita declarată a metodei.** Singura divergență — log-loss la
> `6e7265c5`, stocat `false`, replay `true` — e aproximarea normală contra
> bootstrap-ului percentil la limită. Deci replay-ul e **marginal mai permisiv**
> pe semnificație, ceea ce face din verdictele contrafactuale de mai jos o
> **margine superioară**, nu valori exacte. Pentru concluzia §2.2 nu contează
> (toate verdictele ies negative, deci o metodă mai permisivă care tot nu
> declanșează e o concluzie mai tare), dar orice reutilizare a metodei trebuie
> să poarte limita cu ea.

**Prima încercare de replay a fost invalidă și a fost prinsă de martorul
pozitiv**: fără restricția la fereastra verdictului, evalua 620 de meciuri în
loc de 461 (meciuri logate înainte de 13 oct primiseră rezultat după), iar
acuratețea lui `6e7265c5` ieșea **+0,81pp** în loc de **−1,74pp** — semn opus.
Fără martor, cifra aceea ar fi intrat în raport.

### §2.2 Contrafactualul: aceleași cohorte, baseline-ul CORECT

| artefact | n | baseline | Δbrier | sig | Δlog-loss | sig | Δacc | sig |
|---|---:|---|---:|:-:|---:|:-:|---:|:-:|
| `4e17c737` | 481 | înghețat | −0,0245 | ✅ | −0,0390 | ✅ | **+1,87pp** | ❌ |
| `4e17c737` | 481 | **`control`** | **−0,0040** | ❌ | **−0,0071** | ❌ | **−1,04pp** | ❌ |
| `6e7265c5` | 470 | înghețat | −0,0174 | ❌ | −0,0265 | (✅)* | −1,70pp | ❌ |
| `6e7265c5` | 470 | **`control`** | **−0,0051** | ❌ | **−0,0103** | ❌ | **−1,70pp** | ❌ |

\* flagul stocat e `false`; `true` e artefactul aproximării, vezi §2.1.

**Pe măsurătoarea corectă, `4e17c737` cade pe AMBELE porți**, iar pe cea propusă
cade **dublu**: Brier și log-loss nesemnificative *și* garda de direcție
(`Δacc ≥ 0`) l-ar bloca. Avantajul se contractă de **6×** (−0,0245 → −0,0040) și
acuratețea își schimbă semnul.

Confirmă cifra deja scrisă în proiect din 14 octombrie: *„pare că bate Oracle cu
+3,2pp, dar contra Oracle-ului real pierde cu 1,1pp"* — măsurat aici **−1,04pp**.

### §2.3 Back-testul porților, pentru evidență

De câte ori ar fi tras fiecare poartă, pe toate evaluările reale înregistrate:

| artefact | stare finală | baseline | zile | poarta AZI (3/3) | poarta ADR-084 |
|---|---|---|---:|---:|---:|
| `blend_v1/174e7e17` | SUCCEEDED | `shadow_control` | 22 | **2** | **19** |
| `xgboost_v1/dda4f7f3` | SUCCEEDED | `shadow_control` | 15 | **3** | **3** |
| `blend_v1/4e17c737` | REJECTED/`expired` | înghețat | 25 | 1 | **15** |
| `xgboost_v1/6e7265c5` | REJECTED/`expired` | înghețat | 28 | 0 | 0 |
| `blend_v1/8ac89c70` | PROMOTED | înghețat | 14 | 1 | 1 |
| `xgboost_v1/e638c1dc` | REJECTED/`expired` | înghețat | 27 | 0 | 0 |

Aritmetica se închide: `174e7e17` 22 + 18 zile `insufficient_data` = 40;
`dda4f7f3` 15 + 11 = 26. Zilele `insufficient_data` contribuie 0 la ambele
porți.

**Trei lecturi, toate măsurate:**

1. **ADR-084 nu e „o poartă mai largă pentru toți".** Pentru `dda4f7f3` cele două
   porți sunt **identice** (3 = 3) — astăzi, la n=540, nu trece nici poarta
   propusă (Brier și log-loss amândouă nesemnificative). Singura entitate pe care
   o deblochează e `174e7e17`.
2. **Cele 15 declanșări ale lui `4e17c737` erau integral artefact de baseline**
   (§2.2). Deci acest caz **nu susține** teza că poarta 3/3 ar oferi o protecție
   suplimentară demonstrată — dar nici nu o infirmă: un caz pe care ambele porți
   îl resping nu le separă.
3. **Garda de direcție face muncă măsurabilă**: `6e7265c5` are **3 zile** cu
   Brier ȘI log-loss amândouă semnificative, oprite exclusiv de `Δacc < 0`
   (acuratețe negativă pe toate cele 28 de zile). Caveat: pe baseline-ul
   înghețat, deci dovada e despre gardă, nu despre regimul de măsurare.

### §2.4 Izolarea mecanică a blendului 50/50 — verificată în patru puncte

Întrebarea de la care a pornit episodul a fost dacă aprobarea ADR-084 ar deschide
calea servirii blendului 50/50 din D-17. **Nu poate**, și motivul e mecanic, nu
de politică:

| verigă | ce cere | blendul 50/50 are? |
|---|---|:-:|
| intrarea porții (`evaluate_experiment`) | rânduri `shadow_predictions`, bandă `treatment` | ❌ universul are **7** perechi (name, version); niciuna nu e el |
| execuția (`continuous_learning.py:317`) | verdict + `training_run_id` din `get_active_challenger()` | ❌ |
| registrul | intrare în `experiment_registry` | ❌ (7 intrări) |
| campionii | rând în `model_champions` | ❌ (exact unul activ: `blend_v1/8ac89c70 (all)`) |

Blendul 50/50 e `blend_engine.py` → `WeightedAverageStrategy` cu `weights={}`.
Trăiește exclusiv în `engine_comparison_snapshots`. `blend_v1/174e7e17` e alt
obiect: amestecă la **0,35**, prin `ml_predictor.blend_predictions`, cu
`effective_w = 0,35 · min(samples/150, 1)`.

**Și promovarea lui `174e7e17` nu ar schimba nicio probabilitate servită**:
`oracle_engine._get_blend_v1_champion_prediction()` (linia 2529) e *read-only, NU
modifică `ph`/`pd_`/`pa`*, gatată de `blend_v1_champion_display_enabled`, și
alimentează un câmp de **afișare**. Radarul de value bets citește banda
`control` = Oracle.

Deci avertismentul din `CLAUDE.md` D-17 („sub poarta propusă AR trece, și tocmai
de aceea nu se folosește ca argument") e un pericol **retoric** — nu se citează
ADR-084 ca licență de servire — nu unul mecanic.

---

## §3 — Verificarea 3: cohorte independente. CONSTATAREA DECISIVĂ

### §3.1 Definițiile exacte ale cohortelor

Partiție **disjunctă** pe `match_history.kickoff_date`, pentru
`blend_v1/174e7e17`, bandă `treatment` contra bandă `control`, meciuri cu
`actual_result` și `superseded_by IS NULL`:

| cohortă | interval `kickoff_date` | n |
|---|---|---:|
| C1 | < 2026-09-15 | **0** (Challengerul e creat 21 sep) |
| C2 | 2026-09-15 … 2026-10-04 | 19 |
| C3 | 2026-10-05 … 2026-10-21 | 302 |
| C4a | 2026-10-22 … 2026-11-02 | 352 |
| C4b | 2026-11-03 … 2026-11-05 | 20 |
| **C4** | C4a ∪ C4b | **372** |

Aritmetica se închide exact: 19 + 302 + 372 = **693** = `n_matches_evaluated`
stocat pe verdictul din 5 noiembrie.

Tăietura C4a / C4b e **pre-declarată de proiect** (`1b3c3ef`, ADR-085 pe `main`,
2 nov 20:06 UTC), nu aleasă după ce s-au văzut cifrele.

### §3.2 Rezultatele, cu intervale de încredere — **măsurate 2026-11-05, depășite; vezi §3bis**

| cohortă | n | Δbrier | IC95 Brier | Δlog-loss | IC95 log-loss | Δacc | IC95 acc |
|---|---:|---:|---|---:|---|---:|---|
| C2 | 19 | **+0,0329** | [+0,0009, +0,0649] | +0,0456 | [+0,0017, +0,0895] | −5,26pp | [−15,58, +5,05] |
| C3 | 302 | **−0,0147** | [−0,0229, **−0,0065**] | −0,0232 | [−0,0365, **−0,0100**] | **+3,31pp** | [**+0,43**, +6,19] |
| C4a | 352 | −0,0050 | [−0,0122, **+0,0022**] | −0,0062 | [−0,0168, +0,0043] | **−0,57pp** | [−2,33, +1,19] |
| C4b | 20 | −0,0368 | [−0,0792, +0,0057] | −0,0555 | [−0,1160, +0,0050] | +5,00pp | [−4,80, +14,80] |
| **C4** | **372** | **−0,0067** | sus **+0,0005** | **−0,0089** | traversează 0 | **−0,27pp** | traversează 0 |
| TOTAL cumulat | 693 | −0,0091 | sus −0,0038 | −0,0137 | sub 0 | +1,15pp | peste 0 |

Citire pe cohorte: **C3 e singura care trece.** C4 — cea mai recentă **și cea mai
mare** — cade pe toate trei, inclusiv pe garda de direcție. C2 (n=19) e
neinterpretabilă, deși IC-ul ei pe Brier e integral pozitiv. C4b (n=20) e
neconcludentă pe toate trei, oricât de favorabil arată punctul.

Tăietura pre-declarată arată că slăbiciunea lui C4 **nu e artefact ADR-085**: e
prezentă în C4a, blocul de **352** de meciuri de dinaintea reparației.

### §3.3 🔴 Concluzia metodologică

> **Cele 19 „zile consecutive" nu sunt 19 confirmări independente. Sunt 19
> citiri ale aceleiași ferestre cumulative, al cărei semnal provine dintr-un
> singur bloc de 17 zile (C3, 5–21 octombrie).** Pe informație nouă,
> nesuprapusă, din 22 octombrie încoace — 372 de meciuri, nu un eșantion mic —
> avantajul nu e semnificativ, iar acuratețea e negativă.

Deci **premisa condiției (3) din ADR-084 §11 e falsă**: condiția măsoară
persistența unei estimări cumulative, nu stabilitatea performanței pe date noi.
`174e7e17` nu are, la data acestui jurnal, dovezile necesare pentru promovare.

---

## §3bis — 🔴 REMĂSURAT 2026-11-09: a apărut o cohortă nouă care TRECE

**De ce există această secțiune.** Verificările din §1-§3 s-au făcut pe
**2026-11-05**. Documentul a fost prezentat proprietarului produsului abia pe
**2026-11-09**, iar el a cerut explicit ca analiza să țină cont de cele patru
zile de inactivitate. Între timp s-au jucat patru zile de fotbal.

**Nu e o notă de calendar.** Cifrele din §3.2 erau o stare, nu un fapt
permanent, iar proiectul are lecția plătită: *„orice cifră poartă ora ei"* și
*„«fără pagubă azi» se scrie numai cu măsurătoarea și data alături"* (a stat 64
de zile). Secțiunea asta pune data lângă cifre.

### §3bis.1 Cohortele, remăsurate 2026-11-09

Aceleași definiții disjuncte ca §3.1, plus **C5**, genuin nouă — meciuri jucate
**după** decizia din §7:

| cohortă | n (5 nov) | **n (9 nov)** | Δbrier | IC95 Brier | Brier sig | Δlog-loss | ll sig | Δacc | gardă |
|---|---:|---:|---:|---|:-:|---:|:-:|---:|:-:|
| C2 · 15 sep–4 oct | 19 | 19 | +0,0329 | [+0,0009, +0,0649] | ❌ | +0,0456 | ❌ | −5,26pp | ❌ |
| C3 · 5–21 oct | 302 | 302 | −0,0147 | [−0,0229, −0,0065] | ✅ | −0,0232 | ✅ | +3,31pp | ✅ |
| C4a · 22 oct–2 nov | 352 | 352 | −0,0050 | [−0,0122, +0,0022] | ❌ | −0,0062 | ❌ | −0,57pp | ❌ |
| C4b · 3–5 nov | **20** | **55** | −0,0172 | [−0,0376, +0,0032] | ❌ | −0,0285 | ❌ | +1,82pp | ✅ |
| **C5 · 6–9 nov** | — | **137** | **−0,0131** | [−0,0248, **−0,0015**] | **✅** | **−0,0189** | **✅** | **+1,46pp** | **✅** |
| TOTAL cumulat | 693 | **865** | −0,0096 | [−0,0144, −0,0049] | ✅ | −0,0145 | ✅ | +1,16pp | ✅ |

Aritmetica se închide exact: 19 + 302 + 352 + 55 + 137 = **865**.

**Două lucruri s-au mișcat, nu unul:**

1. **C4b a crescut de la 20 la 55 de meciuri.** Citirea de pe 5 nov
   („neconcludent, n=20") era ea însăși un instantaneu incomplet, care s-a
   umplut pe măsură ce meciurile au primit rezultat. Deci verdictul „C4 cade"
   din §3.2 s-a sprijinit parțial pe o sub-cohortă neterminată.
2. **C5 trece pe toate trei**, inclusiv pe garda de direcție.

### §3bis.2 Ce schimbă, și ce NU schimbă

**NU e o inversare.** C4a (n=352, cea mai mare cohortă post-C3) cădea pe 5 nov
și cade și azi, neschimbată. Tabloul e **mixt**: din patru cohorte post-C2,
**două trec** (C3, C5), una cade (C4a), una e direcțional corectă dar
nesemnificativă (C4b).

**Secvența nu e nici erodare monotonă, nici redresare monotonă**: trece → cade →
direcție corectă → trece. Citită contra condiției (3) din ADR-084 însăși
(*„verdictele nu oscilează"*), **oscilația pe date independente e ea însăși
informație** — îngrijorarea despre instabilitatea criteriului rămâne validă,
chiar dacă ultimul punct e favorabil.

**🔴 Consecința incomodă pentru propunerea din §6**, scrisă aici ca să nu fie
descoperită mai târziu: criteriul pe care îl propun acolo — *confirmare pe ≥ 2
cohorte disjuncte* — ar fi **satisfăcut azi** de C3 + C5. Prima aplicare a
criteriului propus îl aprobă pe candidatul despre care §3.3 scrie că „nu are
dovezile necesare". E informație despre **amândouă**: despre candidat și despre
criteriu.

### §3bis.3 Rezervele, spuse de mine

- **A treia citire a aceleiași întrebări.** ADR-084 §7.1 avertizează exact
  contra remăsurării până trece ceva. Remăsurarea a fost cerută de proprietarul
  produsului, pentru a ține cont de întârziere — nu a fost o căutare de rezultat
  mai bun. Dar **asta nu schimbă statistica**: trei citiri rămân trei citiri.
- **C5 e la limită.** E cea mai mică dintre cohortele care trec, iar capătul
  superior al IC pe Brier e **−0,0015**. O rundă nefavorabilă o întoarce.
- **C5 acoperă patru zile cu volum mare** (137 de meciuri) — un weekend plin de
  etape domestice. Nu e un eșantion „liniștit", dar nici nu e independent de
  compoziția acelui weekend.

### §3bis.4 Ce NU se modifică în acest document

**Decizia formală din §7 rămâne exact cum a fost luată, cu data ei.** A fost
corectă pe dovezile disponibile la 5 noiembrie, iar §3bis nu o rescrie
retroactiv — ar șterge dovada că decizia a fost luată pe ce se știa atunci
(North Star #9). Ce adaugă §3bis e dovada nouă, datată, pentru discuția
următoare.

**ADR-084 rămâne NEAPROBAT și declanșatorul §11 rămâne CONSUMAT.** §3bis nu e o
cerere de redeschidere; e consemnarea unui fapt măsurat.

---

## §4 — Blend 50/50 vs `174e7e17`, pe cohorte disjuncte

Blendul 50/50 (`blend_prob_*` din `engine_comparison_snapshots`, un instantaneu
per meci, ultimul capturat în ziua meciului sau înainte) contra Oracle, pe
cohorte **lunare disjuncte**:

| lună | n | Δbrier | IC95 | semnificativ |
|---|---:|---:|---|:-:|
| 2026-08 | 404 | −0,00804 | [−0,0188, +0,0027] | ❌ |
| 2026-09 | 460 | −0,00447 | [−0,0136, +0,0047] | ❌ |
| **2026-10** | 586 | **−0,01363** | [−0,0218, **−0,0054**] | ✅ |
| 2026-11 | 89 | −0,01051 | [−0,0324, +0,0114] | ❌ |
| TOTAL | 1539 | −0,00924 | \|t\| = 3,50 | ✅ |

**4 din 4 cohorte cu semn negativ, dar doar 1 din 4 semnificativă.**

Comparația onestă cu `174e7e17`: acela are 3 cohorte, semne **+ / − / −**, **1 din
3 semnificativă**. Deci amândouă sunt „o cohortă semnificativă din mai multe".
Asimetria reală e doar în **consecvența semnului** (4/4 contra 2/3) — un semnal
mai slab decât o diferență de calitate demonstrată.

**Blendul 50/50 rămâne candidat de CERCETARE, nu candidat autorizat pentru
servire.** Nu se promovează și nu se respinge pe baza acestei comparații.
Precondiția lui absolută rămâne neatinsă: guvernarea artefactului (D-17 Pasul 2,
`ml_source = "local"`), plus dependența circulară din §20.H și ordinea forțată
ADR-084 → D-15 → Pasul 3.

---

## §5 — Retrageri de afirmații proprii, toate făcute în aceeași sesiune

Consemnate fiindcă trei dintre patru au fost formulate **înainte** de
măsurătoarea care le-a infirmat, iar măsurătoarea era disponibilă.

1. **Recomandarea `baseline_source = 'shadow_control'` ca remediu suficient** —
   retrasă. Confunda proveniența cu corectitudinea (§1). Corecția a venit de la
   proprietarul produsului.
2. **Teza „poarta 3/3 era o plasă de siguranță pe care ADR-084 o scoate"** —
   infirmată de propriul audit (§2.2): pe date corecte ambele porți resping
   `4e17c737`.
3. **Citirea de la 4 noiembrie, „`Δacc` stabilizat peste zero"** — retrasă.
   Seria +1,33/+1,06/+1,04/+1,17/+1,15pp sunt **medii cumulative**; pe cohorte
   independente incrementul recent e negativ (§3.2). Un artefact de mediere citit
   ca dovadă proaspătă — forma cumulativă a lecției deja scrise în proiect („un
   indicator înghețat nu poate partiționa un rezultat împrospătat").
4. **„Obiectul de care te temeai se comportă mai bine la testul pe care l-ai
   cerut"** — supralicitat. 4/4 semn negativ ≠ 4/4 confirmări semnificative
   (§4). Corecția a venit de la proprietarul produsului.

**Primul replay a fost invalid și a fost prins de martorul pozitiv** (§2.1) — a
doua instanță consemnată a regulii „un «0» (sau o cifră) nu se raportează fără
martor pozitiv".

---

## §6 — PROPUNERE de revizuire metodologică (NEAPROBATĂ)

**Nu e o regulă în vigoare. Nu e un amendament la ADR-084. Nu se citează ca
aprobată.** Se consemnează ca punct de plecare pentru o discuție viitoare.

Condiția (3) a declanșatorului — sau orice succesoare a ei — ar trebui formulată
pe **informație nouă**, nu pe persistența unei estimări cumulative:

- confirmare pe **≥ 2 cohorte temporale disjuncte**, fiecare cu `n` suficient
  declarat **înainte** de măsurare, în locul zilelor consecutive dintr-o
  fereastră cumulativă;
- proveniență `shadow_control` obligatorie;
- fidelitatea înregistrării verificată contra unui martor independent (§1.2), cu
  golul de corectitudine (§1.3) declarat explicit ca **nerezolvat**;
- garda de direcție păstrată, pe dovada din §2.3.

**Ce rămâne nerezolvat în propunerea însăși, spus aici ca să nu fie descoperit
mai târziu:** ce înseamnă „`n` suficient", cum se aleg granițele cohortelor fără
a le croi pe date, și cum se tratează o cohortă neconcludentă — nu „în
favoarea", nu „împotriva". Acestea sunt întrebări deschise, nu detalii de
implementare.

> **🔴 [2026-11-09] Întrebarea „cum se tratează o cohortă neconcludentă" s-a
> dovedit a nu fi teoretică.** C4b era n=20 pe 5 nov și e n=**55** pe 9 nov
> (§3bis) — deci o cohortă poate fi neconcludentă **doar fiindcă n-a terminat
> de umplut**, nu fiindcă semnalul lipsește. Orice criteriu pe cohorte are deci
> nevoie și de o regulă despre **când o cohortă e considerată închisă**, altfel
> citirea depinde de ziua în care te uiți. Nerezolvat.
>
> Și, tot pe 9 nov: criteriul ăsta ar fi **satisfăcut** de C3 + C5. Faptul că
> prima lui aplicare aprobă exact candidatul pentru care a fost gândit e un
> motiv de prudență, nu de încredere (§7.1).

**Deliberat NU se propune un declanșator calendaristic nou.** O dată
prestabilită produce presiune pentru o decizie insuficient fundamentată — exact
tiparul pe care acest episod îl documentează. Metodologia se definește întâi.

---

## §7 — Decizia formală (proprietarul produsului, 2026-11-05)

| element | decizie |
|---|---|
| **ADR-084 revizia 3** | **NEAPROBATĂ** |
| **Declanșatorul §11** | **CONSUMAT, fără aprobare** |
| `blend_v1/174e7e17` | rămâne `SUCCEEDED`, **fără promovare** |
| Blend 50/50 (D-17) | cercetare, **fără servire** |
| ADR-086 | neschimbată |
| D-15 | neschimbată |
| Producție | **nicio modificare** |
| Cercetările ML (`PROIECTUL_ML.md`) | continuă conform planului |

Motivul declarat nu e o rezervă statistică, ci o **problemă demonstrată de
metodologie**: s-a confundat stabilitatea unei estimări cumulative cu
stabilitatea performanței pe date noi, independente.

ADR-084 **nu a fost modificat** de acest jurnal. Rămâne PROPUNERE, revizia 3, cu
declanșatorul §11 consemnat ca consumat.

---

## §8 — Lecția de arhitectură, de păstrat în guvernanță

> **O poartă de promovare trebuie să măsoare performanța pe informație NOUĂ, nu
> persistența unui rezultat calculat pe informația veche.**

Valabilă indiferent de arhitectura aleasă ulterior, și indiferent de ce se
decide despre ADR-084.

**Corolarul operațional**: o serie de verdicte produsă de o fereastră
cumulativă (expanding window) e stabilă **prin construcție** odată ce un bloc
timpuriu suficient de mare o domină. „N zile consecutive" pe o astfel de serie
nu e o măsurătoare a stabilității — e o măsurătoare a inerției mediei. Clasa e
rudă cu defectele deja numite în `CLAUDE.md`: un indicator cu o singură valoare
posibilă (`coverage_percent` fix la 100%), unul care nu poate fi roșu
(`night_sync` verde prin construcție), unul care colapsează lucruri distincte
(eticheta de endpoint Odds API) — și, cel mai apropiat, un indicator înghețat
folosit ca să partiționeze un rezultat împrospătat (ADR-072).

---

## §9 — Reproductibilitate

Toate cifrele provin din interogări **read-only** rulate pe 2026-11-05 contra
proiectului `Prediction`. Nicio scriere, nicio migrare, nicio activare de flag,
nicio atingere a `model_config`.

Sursele: `challenger_evaluations` (verdicte imuabile + ferestrele lor),
`shadow_predictions` (benzile `treatment` / `control`), `match_history`
(rezultate reale, `superseded_by IS NULL`), `engine_comparison_snapshots`
(martorul independent și blendul 50/50), `challengers`, `experiment_registry`,
`model_champions`, `model_config`.

Metoda statistică: aproximare normală a intervalului bootstrap
(`medie ± 1,96 · SE` pe diferențe perechi), **validată contra verdictelor
stocate** și cu limita declarată în §2.1 — marginal mai permisivă decât
bootstrap-ul percentil la limită.
