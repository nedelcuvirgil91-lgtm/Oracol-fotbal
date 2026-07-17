# P7.1A — Data Quality Audit: `shot_dominance`

**Status**: Audit de calitate a datelor — zero cod de producție scris, zero migrare, zero modificare a `FEATURE_COLUMNS`/`ml_predictor.py`. Precondiție explicită, cerută de Chief Architect, înainte de aprobarea implementării P7.1 (`P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md`).

**Metodologie**: un singur `SELECT` (read-only) a extras din `match_history` toate cele 5.253 meciuri (5 ligi mari, `actual_result` cunoscut) cu coloanele brute necesare (`home_shots`/`away_shots`, `home_elo`/`away_elo`, `home_offensive_rating`/`away_offensive_rating`, `home_corner_avg_recent`/`away_corner_avg_recent`, `home_foul_avg_recent`/`away_foul_avg_recent`, `actual_home_goals`/`actual_away_goals`). Analiza propriu-zisă (rulare `ShotCountTracker` simulat, statistici, corelații, MI) a rulat **100% local**, în Python, pe datele deja extrase — zero scriere, zero al doilea apel la producție. Simularea replică **exact** logica descrisă în §2.1 din documentul de design: `history[echipă]` conține doar valorile CUNOSCUTE, în ordine cronologică; la fiecare meci se CITEȘTE media ultimelor ≤10 valori din istoric, ABIA APOI se adaugă valoarea meciului curent (dacă e cunoscută) — nicio scurgere temporală introdusă de simulare.

---

## 1. Coverage real

| Nivel | Meciuri | % din 5.253 |
|---|---:|---:|
| `home_shots` + `away_shots` populate pe rândul curent (brut) | 3.501 | 66,6% |
| `shot_dominance` calculabil (ambele echipe au ≥1 valoare cunoscută în istoric — **fereastră parțială admisă, exact semantica de producție** a `corner_dominance`/`foul_diff` azi) | **4.868** | **92,7%** |
| Fereastră COMPLETĂ (10/10 pentru ambele echipe — interpretare strictă, NU cerința de producție azi) | 4.314 | 82,1% |

Per ligă (fereastră parțială admisă, semantica de producție):

| Ligă | Total | Cu `shot_dominance` | % |
|---|---:|---:|---:|
| Bundesliga | 917 | 872 | 95,1% |
| Ligue 1 | 916 | 870 | 95,0% |
| Premier League | 1.140 | 1.053 | 92,4% |
| Serie A | 1.140 | 1.053 | 92,4% |
| La Liga | 1.140 | 1.020 | 89,5% |

**Comparație directă cu precedentul deja acceptat**: acoperirea brută (66,6%) e identică cu ce raporta documentul de design (§4), dar acoperirea REALĂ utilizabilă pentru ML (92,7%) e, coincidență verificată nu presupusă, **exact aceeași cifră** ca `foul_diff` la momentul acceptării lui (`FOULS_DOMINANCE_ABLATION_2026-07-14.md`: „4.868 rânduri (92,7%) au istoric real"). Diferența dintre 66,6% (rândul curent populat) și 92,7% (feature-ul calculabil) se explică prin fereastra glisantă: un meci nu are nevoie ca EL ÎNSUȘI să aibă șuturi populate, doar ca echipele să fi jucat cel puțin un meci ANTERIOR cu șuturi cunoscute — mecanism deja verificat corect la corner/card/foul, reconfirmat aici pentru șuturi.

**Concluzie coverage**: suficient, nu marginal — 92,7% e peste pragul la care s-a acceptat deja `foul_diff`, și cu marjă confortabilă peste orice prag calitativ minim rezonabil (documentul de design propunea ~50% ca prag de alarmă).

---

## 2. Distribuția valorilor (n=4.868)

| Statistică | Valoare |
|---|---:|
| Medie | −0,098 |
| Deviație standard | 3,592 |
| Min | −19,0 |
| P5 | −6,07 |
| P25 | −2,40 |
| P50 (mediană) | −0,10 |
| P75 | 2,20 |
| P95 | 5,70 |
| Max | 13,5 |

```
[-19.00,-17.38)     1
[-17.38,-15.75)     1
[-15.75,-14.12)     1
[-14.12,-12.50)     4
[-12.50,-10.88)     9
[-10.88, -9.25)    26  #
[ -9.25, -7.62)    61  ###
[ -7.62, -6.00)   142  #######
[ -6.00, -4.38)   294  ################
[ -4.38, -2.75)   515  ############################
[ -2.75, -1.12)   776  ###########################################
[ -1.12,  0.50)   893  #################################################
[  0.50,  2.12)   897  ##################################################
[  2.12,  3.75)   590  ################################
[  3.75,  5.38)   370  ####################
[  5.38,  7.00)   163  #########
[  7.00,  8.62)    77  ####
[  8.62, 10.25)    31  #
[ 10.25, 11.88)    12
[ 11.88, 13.50)     5
```

Distribuție aproximativ simetrică, unimodală, centrată foarte aproape de 0 (mediană −0,10 — de așteptat, echipe „gazdă"/„oaspete" mediate peste mii de meciuri nu ar trebui să aibă bias sistematic mare). **Doar 24,0%** din valori cad în intervalul îngust [−1, +1], **12,5%** în [−0,5, +0,5] — majoritatea masei NU e concentrată în jurul lui zero, coada se întinde util până la ±19. Nu e un feature degenerat (o singură valoare dominantă) — are răspândire reală, cu care un model poate discrimina.

**Concluzie distribuție**: are putere de separare — nu e concentrat artificial în jurul lui zero.

---

## 3. Corelații (Pearson, n=4.868, pairwise-complete)

| Comparat cu | r |
|---|---:|
| `outcome_numeric` (H=+1, D=0, A=−1) | **+0,314** |
| `goal_difference` | **+0,333** |
| `home_offensive_rating` | +0,279 |
| `away_offensive_rating` | −0,308 |
| `corner_dominance` | **+0,687** |
| `foul_diff` | +0,284 |
| `elo_difference` | +0,592 |

Medie `shot_dominance` per rezultat (vedere directă, nu doar coeficient):

| Rezultat | Medie | Std | n |
|---|---:|---:|---:|
| A (oaspeți câștigă) | −1,523 | 3,395 | 1.543 |
| D (egal) | −0,342 | 3,437 | 1.228 |
| H (gazde câștigă) | +1,094 | 3,407 | 2.097 |

`eta²` (cât din varianța `shot_dominance` e explicată de grupul de rezultat H/D/A): **0,099** — o echipă care domină net la șuturi recente câștigă vizibil mai des, ordonare monotonă clară A→D→H, dar departe de a determina singură rezultatul (cum era de așteptat — un singur feature nu poate).

**Niciun coeficient nu se apropie de identitate (|r| ≥ 0,9)** — pragul la care ar fi inutil de implementat, conform cerinței explicite. Cel mai mare, `corner_dominance` la 0,687, e o corelație MODERATĂ-RIDICATĂ, nu o duplicare: cornerele și șuturile sunt ambele proxy pentru „presiune ofensivă recentă", deci o corelație reală era de așteptat — dar 0,687² ≈ 0,47 înseamnă că doar ~47% din varianța unuia e „explicată" de celălalt, rămân ~53% informație distinctă. `elo_difference` la 0,592 e similar: ELO e un rating pe termen lung, `shot_dominance` captează forma imediată — related, nu redundant, exact ipoteza din documentul de design (§ motiv P7.1 din roadmap).

**Concluzie corelații**: nu e un duplicat al niciunui feature existent.

---

## 4. Mutual Information / feature importance preliminară

**Fără nicio modificare a `ml_predictor.py`/`FEATURE_COLUMNS`** — calcul diagnostic separat, local.

### 4.1 Mutual Information față de outcome (3 clase), n=4.868

| Feature | MI |
|---|---:|
| `elo_difference` | 0,0906 |
| **`shot_dominance`** | **0,0450** |
| `corner_dominance` | 0,0313 |
| `home_offensive_rating` | 0,0287 |
| `foul_diff` | 0,0141 |
| `away_offensive_rating` | 0,0064 |

**Rezultat central al acestui audit**: `shot_dominance` are Mutual Information de **1,44× mai mare decât `corner_dominance`** și **3,19× mai mare decât `foul_diff`** — ambele deja PROMOVATE în producție prin ablație reală (`ADR-012`, `ADR-013`). Dacă un semnal mai slab decât acesta a trecut deja pragul de acceptare de două ori, informația brută sugerează că `shot_dominance` are șanse reale să treacă și el.

### 4.2 RandomForest diagnostic (5-fold CV, non-walk-forward — NU înlocuiește ablația oficială)

Model separat, 7 feature-uri (`home_elo`, `away_elo`, `home_offensive_rating`, `away_offensive_rating`, `corner_dominance`, `foul_diff`, `shot_dominance`), doar pentru rang relativ de importanță — nu atinge modelul de producție, nu folosește walk-forward (deci nu comparabil direct cu benchmark-ul oficial ADR-020).

| Feature | Gain importance |
|---|---:|
| `home_elo` | 0,272 |
| **`shot_dominance`** | **0,254** |
| `away_elo` | 0,176 |
| `corner_dominance` | 0,090 |
| `home_offensive_rating` | 0,076 |
| `away_offensive_rating` | 0,070 |
| `foul_diff` | 0,063 |

`shot_dominance` iese pe locul 2 din 7, imediat după `home_elo` — peste `away_elo` și peste toate celelalte feature-uri deja în producție din acest subset. **Notă onestă de interpretare**: acesta e un model mic (7 feature-uri, nu cele 13 de producție), CV simplu (nu walk-forward), deci rangul relativ NU e o predicție exactă a ce s-ar întâmpla în ablația oficială — e un semnal diagnostic preliminar, exact ce a cerut acest audit, nu un substitut al ablației reale.

CV accuracy cu vs. fără `shot_dominance` (același subset, aceleași 6 feature-uri de bază): 0,5232 vs. 0,5222 (**Δ +0,0010**) — magnitudine mică, comparabilă cu câștigurile mici dar simultane raportate onest la `foul_diff`/`corner_dominance` în ablațiile lor oficiale; nesemnificativ ca test de sine stătător (CV simplu, nu walk-forward), dar consistent cu direcția indicată de MI și de gain importance.

---

## 5. Concluzie — GO / NO GO / INCONCLUSIVE

```
COVERAGE   : 92,7% (4.868/5.253) — peste pragul la care s-a acceptat foul_diff (92,7%, identic)
DISTRIBUȚIE: reală, nu concentrată în jurul lui 0 (doar 24% în [-1,+1]), std 3,59
CORELAȚII  : nicio pereche ≥0,9 — cel mai mare (corner_dominance, r=0,687) lasă ~53%
             varianță neexplicată; relație cu outcome/goal_difference reală (r≈0,31-0,33)
             dar departe de determinism (eta²=0,099)
MI         : 0,0450 — de 1,44x mai mare ca corner_dominance (MI=0,0313) și 3,19x mai
             mare ca foul_diff (MI=0,0141), AMBELE deja acceptate în producție
IMPORTANȚĂ : locul 2/7 în diagnostic preliminar RandomForest, peste away_elo
```

**Verdict: GO.**

Argumente numerice, nu impresii:
1. Acoperirea (92,7%) egalează exact precedentul deja acceptat (`foul_diff`), fără compromis de eșantion.
2. Distribuția are răspândire reală — nu risc de feature „mort" (varianță aproape nulă).
3. Nu e un duplicat — cea mai apropiată corelație (0,687 cu `corner_dominance`) lasă majoritatea varianței neexplicată de un feature deja existent.
4. Semnalul de informație (MI) e strict mai mare decât AL DOUĂ feature-uri deja promovate prin ablație reală — dacă acelea au trecut pragul, acesta pornește de pe o poziție mai puternică.
5. Diagnosticul preliminar de importanță (RandomForest, non-oficial) confirmă aceeași direcție, fără să pretindă că înlocuiește ablația.

**Ce NU demonstrează acest audit** (limită onestă, explicită): MI mai mare și gain importance mai mare într-un model diagnostic mic NU garantează câștig simultan pe Accuracy/Log Loss/Brier în ablația walk-forward oficială, pe cele 13+1 feature-uri de producție — corelația cu `elo_difference` (0,592) și `corner_dominance` (0,687) înseamnă că o parte din informația lui `shot_dominance` ar putea fi deja parțial „acoperită" de acestea în prezența TUTUROR celorlalte 12 feature-uri simultan, nu doar a celor 6-7 din acest diagnostic. Acesta e motivul exact pentru care planul de ablație din `P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md` (§5, walk-forward, 5 folduri, cele 13 feature-uri de producție + `shot_dominance`) rămâne pasul următor necesar — acest audit arată că merită încercat, nu că rezultatul e deja cunoscut.

**Recomandare**: aprobare pentru a trece direct la ablația oficială P7.1 (workflow temporar, read-only, exact metodologia deja proiectată) — fără altă rundă de audit intermediar.
