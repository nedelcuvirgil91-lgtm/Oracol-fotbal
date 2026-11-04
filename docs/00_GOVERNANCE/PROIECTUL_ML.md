# PROIECTUL ML — dosar de cercetare și specificația testului prospectiv

**Tip**: dosar de cercetare + specificație de experiment. **NU e ADR. Nu decide nimic. Nu autorizează cod.**
**Stare**: cercetare ÎNCHEIATĂ pentru runda 1 · testul prospectiv **NEÎNCEPUT, NEAPROBAT**
**Deschis**: 2026-11-04 · **Reluare programată**: săptămâna viitoare
**De ce există**: ca săptămâna viitoare să nu redescoperim de la zero despre ce e vorba.

> **Cum se reia**: citește §0 (întrebarea), §4 (rezultatele), §5 (cele trei corecții), apoi §7 (specificația ta, verbatim). §8 e ce am de prezentat la reluare. Anexele A-C fac cercetarea reproductibilă.

---

## 0. Întrebarea

> **Putem obține un Football Oracle mai precis și mai bine calibrat fără să sacrificăm informația acumulată în istoricul de 50.000+ de meciuri?**

Formularea proprietarului produsului, care a pornit tot: *„Dacă date aproape complete le avem doar de la începutul acestui sezon, iar din istoricul vechi avem complet doar ELO — hai să vedem cum ar fi predicțiile dacă ML ar ține cont din istoric doar de ELO, și de toate statisticile doar din sezonul ăsta."*

**Distincția care ordonează totul**, pusă explicit de proprietarul produsului: există diferență între un model care *explică* bine rezultatele istorice, unul care *estimează* bine probabilitățile, și unul care *prezice* mai bine meciuri pe care nu le-a văzut. **Ne interesează ultima.**

---

## 1. Ce era starea la pornire (din `ANALIZA_MODUL_ML_2026-11-04.md`, pe `main` @ `fb2af69`)

- Viziunea ADR-051 §2.2 cere ca ML să „observe relații pe care Oracle nu le vede".
- `FEATURE_COLUMNS` = 14, din care **10 SUNT** intrările Oracle (100% acoperire) și 4 independente.
- **Acoperirea celor 4, pe setul REAL de antrenare (52.629 de rânduri): 14,39%.**
  - 🔴 **Corecție la documentul acela**: acolo scrie **11,18%**, cifră calculată pe istoricul singur (50.549), fiindcă filtrasem `used_for_training IS NOT FALSE`. Dar `get_training_data()` **nu citește coloana aceea** — e scrisă de cele trei surse de import și niciodată citită ca filtru. Deci sezonul curent **intră** în antrenare, numitorul corect e 52.629, iar titlul corect e **85,6% Oracle-only**, nu 88,8%. Direcția și ordinul de mărime rămân.
- P1 închis: **ADR-049 e ACTIV**, T = 1,2037503022912854 pe artefactul servit; calibrarea globală e net neutră; prejudecata de remiză **precedă** calibrarea, deci e a modelului.

---

## 2. Era bogată vs istoric — faptul fizic de la care pleacă totul

| eră | meciuri | șuturi | posesie | xG real | arbitru | lot |
|---|---:|---:|---:|---:|---:|---:|
| istoric (< iul 2025) | **47.676** | 7,3% | **0,0%** | **0,0%** | **0,0%** | **0,0%** |
| sezon 2025/26 | 2.873 | 5,2% | 5,2% | 5,2% | 5,2% | 5,2% |
| **sezon curent** | **2.080** | **99,6%** | **99,6%** | **93,1%** | **99,9%** | **99,9%** |

Era bogată completă (șuturi + posesie + xG + pauză, toate prezente): **1.930 de meciuri, +~600/lună**, acoperire ~100% din septembrie.

---

## 3. Auditul — contaminare GĂSITĂ și eliminată

Cerut explicit de proprietarul produsului. Rezultatele rundei 1 **s-au refăcut** după audit.

| verificare | rezultat |
|---|---|
| predicții shadow scrise **după** fluier | 🔴 **202 din 1.496 (13,5%)**, cea mai târzie la **−1,61 zile** — **EXCLUSE** |
| cauza | batch-ul ADR-056 face `upsert` nocturn pe o fereastră de 7 zile, deci `prediction_time` e **ultima** scriere; pentru 202 de meciuri ultima scriere s-a produs după ce meciul se jucase |
| `home_elo`/`away_elo` sunt pre-meci? | ✅ **martor pozitiv**: pe Arsenal, `elo` = `elo_after` al meciului **precedent**, diferență **0 pe toate cele 7** rânduri comparabile; iar `elo_after` al meciului curent diferă (1948→1951 după victorie, **1970→1937** după înfrângere) |
| priorul estimat doar pe antrenare? | ✅ `kickoff < 2026-07-01` (50.549) vs evaluare `>= 2026-07-01` — **disjuncte temporal** |
| meciul evaluat era în antrenarea producției? | ✅ nu — regula „artefactul antrenat **înaintea** meciului" (3 artefacte: `e638c1dc` 5 aug, `6e7265c5` 6 sep, `dda4f7f3` 14 oct) |
| dedup pe artefact | 🔴 **295 de meciuri aveau 2 artefacte, 1 avea 3** — rândurile se dublau. Reparat prin regula de mai sus |
| `flashscore_standings_snapshot` | 🔴 **INUTILIZABILĂ pentru backtesting**: 398 rânduri, 398 perechi `(competiție, echipă)` — **un singur instantaneu curent**, `captured_at` 26 oct – 4 nov. Reflectă starea de azi, deci include rezultatele tuturor meciurilor evaluate. Clasamentul a fost **RECONSTRUIT** din rezultate strict anterioare |

**Eliminarea contaminării a MĂRIT avantajul priorului ELO** (−0,0094 → −0,0136), exact cum prezicea direcția erorii — contaminarea favoriza producția.

---

## 4. REZULTATELE — n = 794 out-of-sample (12 sep – 3 nov), aceleași meciuri pentru toate

Protocol: 1.294 de meciuri curate, ordonate cronologic · **burn-in 500** (doar antrenare) · 5 blocuri succesive, fiecare prezis de un model antrenat DOAR pe meciurile anterioare · hiperparametri FIXAȚI identici cu producția · **zero tuning pe test** · IC 95% bootstrap (10.000 reeșantionări) pe diferențe pereche.

| model | Brier | Δ vs A | IC 95% | \|t\| | log-loss | acuratețe |
|---|---:|---:|---|---:|---:|---:|
| **C′ = B + corecție rate** | **0,56532** | **−0,01391** | [−0,0234, −0,0044] | 2,90 | 0,95466 | **0,5655** |
| **E′ = (0,5A+0,5B) + corecție** | 0,56632 | −0,01290 | **[−0,0184, −0,0071]** | **4,44** | 0,95632 | 0,5617 |
| **B = prior ELO istoric** | 0,56672 | −0,01251 | [−0,0216, −0,0034] | 2,72 | 0,95674 | 0,5655 |
| 0,5A + 0,5B | 0,56977 | −0,00945 | [−0,0140, −0,0050] | 4,07 | 0,96134 | 0,5605 |
| D = A + corecție rate | 0,57372 | −0,00551 | [−0,0092, −0,0018] | 2,88 | 0,96758 | 0,5479 |
| **A = producție** | 0,57922 | — | — | — | 0,97553 | 0,5315 |
| E2 ELO+formă *(sezon)* | 0,61766 | **+0,0384** | [+0,018, +0,060] | 3,53 | 1,05325 | 0,4950 |
| E3 ELO+xG | 0,61932 | +0,0401 | [+0,018, +0,062] | 3,56 | 1,05362 | 0,4912 |
| E6 ELO+tot | 0,62255 | +0,0433 | [+0,021, +0,066] | 3,74 | 1,06135 | 0,5139 |
| E1 ELO *(sezon)* | 0,62389 | +0,0447 | [+0,026, +0,064] | 4,47 | 1,05450 | 0,4799 |
| E5 ELO+H2H | 0,62757 | +0,0484 | [+0,028, +0,070] | 4,54 | 1,06362 | 0,4761 |
| **F = prior ELO + sezon** | 0,62806 | **+0,0488** | [+0,026, +0,073] | 4,11 | 1,06527 | 0,4975 |
| E4 ELO+clasament | 0,62821 | +0,0490 | [+0,025, +0,072] | 4,04 | 1,08755 | 0,5113 |

### 4.1 🔴 Arhitectura pe două surse e INFIRMATĂ — iar cauza e măsurată

**F e printre cele mai slabe**, +0,049 Brier peste producție, |t| = 4,11. **Nu ideea e greșită, e mărimea eșantionului.** Curba de învățare, cu **același feature (ELO), aceeași clasă de model**, doar antrenarea diferită:

| antrenat pe | Brier |
|---|---:|
| ~125 meciuri de sezon | 0,68334 |
| ~250 | 0,65502 |
| ~375 | 0,61846 |
| ~500 | 0,62389 |
| **50.549 meciuri istorice** | **0,56672** |

**Același ELO, de la 0,68 la 0,57, exclusiv prin ~100× mai multe date.** Mărimea eșantionului domină cu un ordin de mărime. Arhitectura pe două surse aruncă exact eșantionul istoric pentru partea de statistici, iar ~1.000 de meciuri nu îl pot înlocui.

### 4.2 Valoare incrementală — referința CORECTĂ e E1, nu A

| | Δ Brier vs ELO singur | IC 95% |
|---|---:|---|
| +formă | −0,0062 | [−0,027, **+0,014**] |
| +xG | −0,0046 | [−0,028, **+0,019**] |
| +tot | −0,0013 | [−0,028, +0,025] |
| +H2H | +0,0037 | [−0,013, +0,020] |
| +clasament | +0,0043 | [−0,019, +0,028] |

**Toate intervalele includ zero.** Verdictul corect e **„nedetectabil la acest eșantion", NU „inutil"** — exact distincția cerută. Efectele sunt ~0,005, efectul minim detectabil e ~0,024 → ar trebui **~16× mai multe date**. Cu era bogată crescând ~600/lună, se retestează în câteva luni.

### 4.3 Corecția ratelor de bază e STABILĂ

Factorii, estimați pe antrenarea fiecărui bloc (niciodată pe blocul prezis):

| bloc | f(gazdă) | **f(remiză)** | f(oaspete) | remiză reală în bloc |
|---|---:|---:|---:|---:|
| 500-658 | 1,0746 | **0,8860** | 1,0065 | 0,2089 |
| 658-817 | 1,0691 | **0,8698** | 1,0241 | 0,2013 |
| 817-976 | 1,0878 | **0,8458** | 1,0196 | 0,2327 |
| 976-1135 | 1,0803 | **0,8533** | 1,0213 | 0,2075 |
| 1135-1294 | 1,0725 | **0,8414** | 1,0418 | 0,1887 |

Remiza e **sub 1 în fiecare bloc**, bandă 0,841–0,886. Pe ferestre succesive de 200: 0,285 / 0,210 / 0,230 / 0,205 / 0,225 / 0,225 — stabilă după startul de sezon. **Istoric 0,2616 vs sezon 0,2241.**

Deplasarea remizelor e **largă, nu compoziție**: scade în **11 din 14 ligi** (p ≈ 0,029). Creșterea gazdei (+2,82pp agregat) e în schimb **8 din 14** — indistinctă de hazard, deci în mare parte compoziție.

### 4.4 Stabilitate pe ligi

**B bate A în 13 din 15 ligi** (pierde doar Eredivisie și Champions League). Test de semn **p ≈ 0,004**. Nu vine din câteva competiții dominante.

### 4.5 Priorul ELO — ce este, exact

Model **neparametric**: `P(H/D/A | diferență ELO)`, 28 de găleți, estimat pe cele 50.549 de meciuri istorice. Monoton pe P(gazdă) 0,10 → 0,88; P(remiză) are vârf la mijloc (0,29) și scade la extreme. **3 inversiuni de monotonie din 27**, toate în cozile subțiri (n = 182-581) — zgomot de eșantion, **neatins deliberat** (netezirea e o alegere de modelare care cere justificare separată). Tabelul complet: **Anexa A**.

---

## 5. Cele trei corecții la propriile mele citiri — păstrate ca metodă

1. **Precizie citită ca recall.** Raportasem „ML 49,2% pe oaspete vs Oracle 43,9%" ca avantaj la oaspete. Era **precizie**: ML prezice oaspete mai rar (594 vs 772), deci nimerește procentual mai bine și ratează în valoare absolută. Pe **recall**, ML e mai bun la gazdă (+63) și mai slab la oaspete (−47). *Precizia și recall-ul pe aceeași clasă pot avea semne opuse.*
2. **„Calibrarea înrăutățește" — tras dintr-un singur artefact.** Pe `dda4f7f3` Δbrier = +0,00466 (|t|=2,30), dar pe celelalte două e indistinct de zero (|t| 0,50 și 0,64) **și semnul se inversează**. Formularea corectă: **net neutră**, cu semnal slab advers pe artefactul curent.
3. **Semnalul xG spectaculos era un proxy pentru ELO.** Testul necontrolat arăta reziduu monoton de ±0,14 pe dominanța xG. Dar `corr(xG, ELO) = 0,589`, iar cu benzi de ELO **cu semn** efectul se evaporă: în cele două benzi cu ELO potrivit și n mare, reziduul e **non-monoton** (formă de U) și în zgomot. **Prima bandare, pe |diferență|, era și ea greșită** — amesteca −215 cu +229.

**Capcană de proces, plătită în aceeași zi**: `concat_ws` **sare peste NULL-uri**, deci prima extragere a dat **489 de rânduri malformate** din 1.294. Avertismentul exista scris în propriul meu reminder și am intrat direct în el. Prins de validarea pe numărul de coloane. **Regula: `coalesce(x::text,'')` pe FIECARE câmp.**

---

## 6. 🔴 Constatarea care atinge DIRECT specificația testului prospectiv

Specificația de mai jos (§7, punctul 2) cere: *„Nu permite suprascrierea predicțiilor deja înregistrate."*

**Infrastructura actuală NU respectă asta.** `shadow_predictions` se scrie prin `upsert` pe cheie compusă, iar batch-ul ADR-056 reprocesează o fereastră de 7 zile în fiecare noapte — deci predicția se **rescrie** până la (și uneori după) meci. Exact mecanismul care a produs cele 202 predicții post-fluier.

**Consecință pentru proiectare**: testul prospectiv **nu poate** refolosi `shadow_predictions` ca atare fără a încălca cerința de imuabilitate. Asta e prima problemă de arhitectură de rezolvat la reluare, și e o constatare, nu o presupunere.

---

## 7. SPECIFICAȚIA TESTULUI PROSPECTIV — promptul proprietarului produsului, VERBATIM

> *Păstrat neschimbat, ca sursă autoritativă. Orice abatere la implementare se discută explicit, nu se rezolvă prin reinterpretare.*

---

Vreau să pregătim următoarea etapă: TESTUL PROSPECTIV CONTROLAT.

Nu implementăm încă nicio modificare în producție.

Scopul este să verificăm dacă avantajul observat pe cele 794 de meciuri se repetă pe meciuri care nu au avut loc la momentul generării predicțiilor.

**1. Cele cinci variante experimentale**

Înregistrează separat predicțiile pentru:

A. Modelul actual de producție.

B. Priorul ELO istoric, fără corecție.

C. Priorul ELO istoric + corecția ratelor de bază.

D. Modelul de producție + corecția ratelor de bază.

E. Blend 50/50 între producție și priorul ELO + corecția ratelor de bază.

Nu modifica ponderile după începerea experimentului.

**2. Înghețarea experimentului**

Pentru fiecare variantă:

- fixează versiunea modelului;
- înregistrează parametrii și configurația;
- păstrează factorii de corecție utilizați;
- salvează momentul generării predicției;
- salvează probabilitățile 1X2;
- identifică fiecare meci printr-un identificator unic;
- păstrează suficiente informații pentru reproducerea rezultatului.

Predicțiile trebuie înregistrate înainte de începerea meciurilor.

Nu permite suprascrierea predicțiilor deja înregistrate.

Orice recalculare ulterioară trebuie păstrată separat și nu trebuie să înlocuiască predicția originală.

**3. Corecția ratelor de bază**

Pentru variantele care folosesc această corecție:

- factorii se estimează exclusiv din informațiile disponibile înainte de predicție;
- nu se utilizează rezultatul meciului evaluat;
- se stabilește dinainte metoda de actualizare;
- se păstrează istoricul factorilor utilizați.

Nu recalibra retrospectiv variantele după observarea rezultatelor.

**4. Evaluarea finală**

După 4–6 săptămâni, compară toate cele cinci variante pe exact aceleași meciuri.

Raportează:

- Brier Score;
- Log Loss;
- Accuracy;
- calibrarea probabilităților;
- intervale de încredere 95%;
- diferențe statistice pereche;
- rezultate separate pe ligi;
- rezultate separate pe ferestre temporale.

Verifică inclusiv dacă avantajul variantei câștigătoare este distribuit între ligi sau provine din câteva competiții dominante.

Nu declara un câștigător doar pe baza Accuracy.

**5. Reguli de validitate**

- Nicio modificare a modelului de producție.
- Nicio modificare a ponderilor după pornirea testului.
- Nicio eliminare selectivă a meciurilor după aflarea rezultatelor.
- Aceeași populație de meciuri pentru toate variantele.
- Fără contaminare temporală.
- Fără optimizare pe setul prospectiv.
- Documentarea tuturor excluderilor și a predicțiilor lipsă.

Stabilește înainte de pornire criteriile de validitate și condițiile în care experimentul poate fi declarat neconcludent.

Nu opri testul anticipat doar pentru că una dintre variante conduce temporar.

**6. Implementare și guvernanță**

Mai întâi inspectează arhitectura actuală și identifică modalitatea minimă de înregistrare a predicțiilor experimentale.

Verifică dacă infrastructura existentă permite shadow logging fără să influențeze predicțiile servite utilizatorilor.

Nu crea fișiere noi și nu modifica fișiere existente fără aprobarea mea.

Nu activa flaguri și nu modifica model_config.

Prezintă-mi:

1. Arhitectura propusă pentru experiment.
2. Tabelele sau mecanismele existente care pot fi reutilizate.
3. Modificările strict necesare, dacă există.
4. Riscurile de contaminare și de interferență cu producția.
5. Protocolul experimental complet.
6. Criteriile exacte de acceptare a rezultatelor.

Așteaptă aprobarea mea înainte de orice implementare.

**Obiectiv final**

Vreau să aflăm dacă putem obține un Football Oracle mai precis și mai bine calibrat fără să sacrificăm informația acumulată în istoricul de 50.000+ de meciuri.

Decizia arhitecturală se ia numai după validarea prospectivă.

**Un detaliu important**

Aș mai introduce o condiție: dacă după 6 săptămâni eșantionul prospectiv este prea mic pentru a diferenția variantele, testul nu trebuie declarat câștigat sau pierdut. Se prelungește până la un prag statistic stabilit înainte de pornire.

Nu ne grăbim să schimbăm modelul. Vrem să demonstrăm că următoarea versiune este realmente mai bună.

---

## 8. Ce am de prezentat la reluare (cele 6 puncte cerute) — NEFĂCUT

Săptămâna aceasta se continuă **doar** cercetările deja în curs și clar stabilite, prin decizie explicită a proprietarului produsului. Următoarele rămân **neînceput**:

1. **Arhitectura propusă pentru experiment** — inclusiv cum se respectă imuabilitatea, dat §6.
2. **Tabele/mecanisme reutilizabile** — candidați de inspectat: `shadow_predictions` (dar vezi §6), `engine_comparison_snapshots` (cadrul ADR-052, deja captează Oracle/ML/Blend pe același meci), `automation_runs` ca jurnal.
3. **Modificările strict necesare** — de minimizat; orice tabelă nouă cere ADR + `GRANT` către `service_role` (regula de la 30 oct).
4. **Riscuri de contaminare și interferență** — inclusiv dependența circulară din `DE_URMARIT` §20.H (rândul `control` e simultan predicția servită ȘI baseline-ul porții de promovare).
5. **Protocolul experimental complet.**
6. **Criteriile exacte de acceptare** + condițiile de „neconcludent" + pragul statistic de prelungire.

**Estimare de putere, de rafinat la reluare**: la n = 794 am obținut IC de ±0,008 pe Brier. Ritmul sezonului e ~600 de meciuri bogate/lună, deci 4-6 săptămâni ≈ **600-900 de meciuri** — același ordin, deci **puterea va fi comparabilă, nu mai mare**. Dacă efectul real e ~0,013 (cât am măsurat), e detectabil; dacă e ~0,005, **nu**. Asta e exact motivul pentru care condiția de prelungire din §7 e necesară, nu opțională.

---

## 9. Rezervele mele asupra rezultatelor — puse de mine, nu așteptate să fie găsite

1. **Victoria lui B e parțial o poveste de VARIANȚĂ, nu de informație.** B are un feature efectiv și 50k rânduri → varianță mică. A are 14 feature-uri → varianță mare. La n = 794, varianța mică câștigă. Asta **nu** dovedește că ELO conține mai multă informație decât cele 14 feature-uri — dovedește că varianța lor în plus costă mai mult decât informația lor în plus, **la acest volum de evaluare**. Contra-argument parțial: B câștigă și pe **acuratețe** (56,5% vs 53,1%), ceea ce e mai greu de explicat prin varianță.
2. **Citirea corectă NU e „înlocuiește ML cu un tabel de căutare"** — e că modelul de producție pare **supra-parametrizat față de semnalul pe care îl extrage**, și că deriva ratelor de bază nu e tratată de nimic.
3. **794 de meciuri pe 7,5 săptămâni nu sunt o replicare.** Testul cerut — meciuri viitoare — încă nu a avut loc. De aici tot §7.
4. **Eșecul familiei E nu dovedește că statisticile sunt inutile** — dovedește că nu se pot învăța din ~1.000 de meciuri. Afirmație diferită, și singura susținută de date.
5. **Varianta cea mai FIABILĂ nu e cea cu cel mai bun punct estimat.** `B + corecție` are Brier 0,56532 dar IC [−0,0234, −0,0044]; `(0,5A+0,5B) + corecție` are 0,56632 cu IC **[−0,0184, −0,0071]** și |t| = 4,44. Blendul reduce varianța. La decizie, asta poate conta mai mult decât 0,001 pe punctul estimat.

---

## 10. Ce NU s-a atins în toată cercetarea

Zero modificări de cod · zero flaguri atinse · zero scrieri pe Supabase (tot read-only) · `model_config` neatins · calea de predicție neatinsă · modelul de producție neatins. Singurele fișiere scrise sunt documentul de analiză (`fb2af69`) și acesta.

---

## Anexa A — priorul ELO istoric (28 de găleți, 50.549 de meciuri, `kickoff < 2026-07-01`)

`(d_min, d_max, n, pH, pD, pA)` pe diferența ELO `home_elo − away_elo`:

```python
PRIOR_ELO = [
    (-528, -326, 420, 0.1000, 0.1524, 0.7476),
    (-325, -301, 182, 0.1374, 0.1593, 0.7033),
    (-300, -276, 325, 0.1569, 0.2185, 0.6246),
    (-275, -251, 401, 0.1546, 0.2494, 0.5960),
    (-250, -226, 540, 0.1593, 0.2278, 0.6130),
    (-225, -201, 750, 0.2360, 0.2467, 0.5173),
    (-200, -176, 982, 0.2475, 0.2332, 0.5193),
    (-175, -151, 1353, 0.2535, 0.2831, 0.4634),
    (-150, -126, 1919, 0.2871, 0.2595, 0.4534),
    (-125, -101, 2437, 0.3135, 0.2753, 0.4112),
    (-100,  -76, 3090, 0.3311, 0.2825, 0.3864),
    ( -75,  -51, 3669, 0.3759, 0.2805, 0.3437),
    ( -50,  -26, 4274, 0.3996, 0.2878, 0.3126),
    ( -25,   -1, 4722, 0.4102, 0.2918, 0.2980),
    (   0,   24, 5076, 0.4413, 0.2794, 0.2794),
    (  25,   50, 4459, 0.4683, 0.2839, 0.2478),
    (  51,   74, 3608, 0.5028, 0.2611, 0.2361),
    (  75,   99, 3049, 0.5346, 0.2624, 0.2030),
    ( 100,  124, 2355, 0.5609, 0.2442, 0.1949),
    ( 125,  149, 1850, 0.5832, 0.2341, 0.1827),
    ( 150,  174, 1435, 0.6028, 0.2321, 0.1652),
    ( 175,  199, 1004, 0.6624, 0.2052, 0.1325),
    ( 200,  224,  714, 0.6933, 0.1835, 0.1232),
    ( 225,  249,  581, 0.7435, 0.1704, 0.0861),
    ( 250,  274,  394, 0.8071, 0.1218, 0.0711),
    ( 275,  299,  273, 0.7326, 0.1685, 0.0989),
    ( 300,  324,  220, 0.8818, 0.0818, 0.0364),
    ( 325,  549,  467, 0.8394, 0.1028, 0.0578),
]
BAZA_ISTORICA = (0.4377, 0.2616, 0.3007)   # H / D / A pe cele 50.549
```

**Căutare**: prima găleată care conține valoarea. În afara intervalului observat istoric se folosește capătul cel mai apropiat, **niciodată o extrapolare** (North Star #8).
**Validare**: toate 28 însumează 1,0 (toleranță 0,002); `n` total = 50.549, exact.
**Reproducere**: `width_bucket(home_elo - away_elo, -325, 325, 26)` pe `match_history` cu `actual_result IS NOT NULL AND superseded_by IS NULL AND kickoff_date < '2026-07-01'`.

## Anexa B — extragerea setului de evaluare

Un singur `SELECT` pe `match_history` + `shadow_predictions`, cu:

- **filtrul erei bogate**: `home_shots`, `home_possession`, `home_xg_actual`, `home_ht_goals`, `home_elo`, `away_elo` toate `NOT NULL`, `kickoff_date >= '2026-07-01'`, `superseded_by IS NULL`, `actual_result NOT NULL`;
- **alegerea artefactului** (evită dublarea pe 295+1 meciuri):
  `kickoff >= '2026-10-14 05:31:02+00'` → `dda4f7f3…` · `>= '2026-09-06 18:34:41+00'` → `6e7265c5…` · altfel `e638c1dc…`;
- **garda anti-contaminare**: `sp.prediction_time < b.kickoff_date::timestamptz`;
- **feature-uri glisante STRICT anterioare**, pe format lung (un rând per echipă-meci):
  `WINDOW w5 AS (PARTITION BY echipa ORDER BY kickoff_date, fixture_id ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)` — `1 PRECEDING`, **niciodată** `CURRENT ROW`;
- **clasament reconstruit**: `WINDOW wl AS (PARTITION BY league, echipa ORDER BY kickoff_date, fixture_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)`, cumulat puncte și golaveraj → puncte/meci și golaveraj/meci, apoi diferența gazdă−oaspete;
- **`coalesce(x::text,'')` pe FIECARE câmp** la serializare (vezi §5).

Coloane: `dt,lg,r,ph,pd,pa,ed,hf,af,h2m,h2n,hxp,hxc,axp,axc,dpos,dcon,dht,dcor,dcar,dfou,dsh,dppg,dgdpg,jmin,nmin` → **1.294 de rânduri, 26 de coloane, 0 malformate**.

## Anexa C — protocolul de evaluare, în cod

```python
BURN_IN, N_BLOCURI = 500, 5
HP = dict(n_estimators=150, max_depth=4, learning_rate=0.08, subsample=0.85,
          colsample_bytree=0.85, objective="multi:softprob", num_class=3,
          eval_metric="mlogloss", random_state=42)   # IDENTICI cu productia

granite = np.linspace(BURN_IN, n, N_BLOCURI + 1).astype(int)
BLOCURI = [(granite[i], granite[i+1]) for i in range(N_BLOCURI)]
# blocuri efective: (500,658) (658,817) (817,976) (976,1135) (1135,1294)

def walk_forward(cols):            # antreneaza pe tot ce e INAINTE de bloc
    for a, b in BLOCURI:
        m = XGBClassifier(**HP); m.fit(X[:a], y[:a])
        P[a:b] = m.predict_proba(X[a:b])

def corectie_rate_baza(P):         # factorii DOAR din trecutul fiecarui bloc
    for a, b in BLOCURI:
        obs = [(y[:a] == k).mean() for k in range(3)]
        f = obs / P[:a].mean(0)
        Q[a:b] = (P[a:b] * f) / (P[a:b] * f).sum(1, keepdims=True)
```

**IC 95%**: bootstrap, 10.000 reeșantionări, pe **diferențele pereche** (`brier_model − brier_A` per meci), `np.percentile(med, [2.5, 97.5])`, `default_rng(42)`.
**Toate modelele** se evaluează pe masca comună `valid = mask_test & ~isnan(P)` pentru **toate** variantele simultan, ca populația să fie identică.
**Decizie de metodă**: s-au păstrat **toate** cele 1.294 de meciuri, cu NaN nativ pe feature-urile indisponibile — exact cum funcționează producția, și singurul mod de a respecta „aceleași meciuri pentru toate comparațiile". Filtrarea pe istoric complet rămâne verificare de robustețe, nu set principal.
