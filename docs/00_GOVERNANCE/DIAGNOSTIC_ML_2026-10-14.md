# De ce ML e cel mai slab motor — diagnostic măsurat, 2026-10-14

Întrebare proprietar produs: *„Dacă ML e cel mai slab, înseamnă că nu învață bine? Ce nu face bine? El trebuia să devină ușor-ușor motorul cu cea mai mare acuratețe."*

Totul de mai jos e măsurat read-only. Niciun cod schimbat, nicio scriere.

**Răspunsul scurt**: nu e că învață prost. E că **nu are cum să învețe** — iar ce învață e despre o lume care nu mai există.

---

## 1. Nu învață. Deloc. Măsurat pe propria lui validare

| Antrenare | Data | `samples_used` | Acuratețe | Log-loss | Brier |
|---|---|---:|---:|---:|---:|
| `6e7265c5` | 6 sep | 51.418 | 0,4834 | 1,0308 | 0,6177 |
| `174e7e17` | 20 sep | 51.720 | 0,4854 | 1,0310 | 0,6178 |
| `dda4f7f3` | 14 oct | 51.926 | 0,4853 | 1,0307 | 0,6176 |

Cinci săptămâni, trei reantrenări, **mișcare în a patra zecimală**. Nu e stagnare temporară — e platou.

**Cauza e aritmetică**, în coloana `samples_used`: **+508 meciuri în 5 săptămâni, pe o bază de 51.400 = +1,0%.** Fiecare reantrenare adaugă ~0,5% date noi într-un set dominat de istoric. Chiar dacă meciurile noi ar fi perfect informative, sunt diluate ~100:1.

**Așteptarea „va deveni ușor-ușor cel mai bun" presupunea că datele noi contează.** La ritmul actual de acumulare (~90 de meciuri/zi în ligile urmărite) ar dura **ani** până ca sezonul curent să fie majoritar în setul de antrenare.

---

## 2. Învață pe o distribuție care nu mai există

Deriva e **monotonă**, pe toate axele, și toate trag în aceeași direcție:

| An | n | Off. mediu | ELO mediu | % feat. avansate | Ligi |
|---|---:|---:|---:|---:|---:|
| 2021 | 7.166 | 0,924 | 1502,6 | 0,0% | 40 |
| 2022 | 13.112 | 0,913 | 1507,7 | 0,0% | 40 |
| 2023 | 14.323 | 0,944 | 1521,4 | 12,0% | 38 |
| 2024 | 14.012 | 0,982 | 1533,9 | 26,1% | 39 |
| 2025 | 6.692 | 1,013 | 1559,0 | 42,6% | 23 |
| 2026 | 2.848 | **1,113** | **1589,4** | **74,8%** | 18 |

Pe întregul set: `home_offensive_rating` are media **0,956** în istoric și **1,157** în sezonul curent — **0,92 abateri standard**. Un model cu arbori extrapolează constant dincolo de ultima tăietură învățată, deci pe zona unde prezice azi are densitate mică de antrenare.

ELO-ul mediu crește cu **87 de puncte** în cinci ani, deși ELO ar trebui să fie sumă-zero. Cauza nu e investigată aici (compoziția bazinului se schimbă: echipe care ies, echipe noi intrate la 1500), dar efectul e clar: **feature-ul nu e staționar.**

---

## 3. Semnalul e în diferențe, iar modelul primește niveluri — ăsta e punctul central

| An | ELO **nivel** | ELO **diferență** | Off. **nivel** | Off. **diferență** |
|---|---:|---:|---:|---:|
| 2021 | 1502,6 | −0,43 | 0,924 | −0,009 |
| 2022 | 1507,7 | +0,32 | 0,913 | −0,003 |
| 2023 | 1521,4 | −0,33 | 0,944 | −0,003 |
| 2024 | 1533,9 | −0,17 | 0,982 | −0,004 |
| 2025 | 1559,0 | −0,52 | 1,013 | −0,005 |
| 2026 | **1589,4** | **+1,31** | **1,113** | **−0,008** |

**Nivelurile derivă cu +87 de puncte ELO și +0,20 rating ofensiv. Diferențele oscilează în jurul lui zero, stabile pe șase ani.**

`FEATURE_COLUMNS` conține `home_elo` și `away_elo` ca **niveluri absolute**, nu diferența. Un arbore *poate* reconstrui diferența, dar numai prin perechi de tăieturi („home_elo > X ȘI away_elo < Y") — mult mai puțin eficient ca eșantion, și, mai grav, **acele praguri se demodează**: o tăietură învățată la `home_elo = 1520` în 2023 înseamnă altceva în 2026, când media e 1589.

Observație suplimentară: **raportul NU e soluția.** `home_off / away_def` derivă și el (0,794 → 0,908). Doar **diferența** e staționară.

Notat și: abaterea diferenței de ELO se dublează (76 → 156) — meciurile devin mai dezechilibrate pe măsură ce mixul de ligi se îngustează.

---

## 4. Patru feature-uri din 14 practic nu există la antrenare

| Set | Meciuri | ELO/formă/rating/H2H | Corner/card/fault/șuturi |
|---|---:|---:|---:|
| Istoric (**antrenează**) | 57.306 | 100% | **16,0%** |
| Sezon curent (**prezice**) | 1.347 | 100% | **89,1%** |

`corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance` lipsesc din 84% din datele de antrenare. XGBoost tratează nativ lipsa, dar învață astfel că **„lipsă" e norma** — apoi la servire valoarea e prezentă în 89% din cazuri, pe o ramură unde are puțin semnal.

Despărțirea pe acest criteriu e **neconcludentă azi** (doar 53 de meciuri servite fără feature-urile avansate, prea puțin). Dar pe cele 945 **cu** feature-uri complete, ML pierde **−2,54pp** față de Oracle — deci nu e un efect de nișă, e pe volumul principal.

---

## 5. Confirmarea finală: validare vs. realitate

| | Acuratețe |
|---|---:|
| Validare walk-forward (`dda4f7f3`) | 0,4853 |
| Live, pe 998 de meciuri | **0,4699** |

**−1,5pp live față de propria validare** — semnătura clasică a derivei de distribuție. Nu e scurgere temporală (walk-forward e corect implementat), e faptul că setul de validare seamănă cu trecutul, nu cu prezentul.

---

## 6. Ce se poate face — ordonat după efect pe unitate de efort

Toate sunt schimbări în **Learning Core**, nu în Oracle. Niciuna nu atinge predicția servită. Fiecare cere ablație, per regula ML din `CLAUDE.md` („feature nou doar cu dovadă de ablație, nu presupunere").

### A. Feature-uri de diferență — cel mai mare efect, cel mai mic cost

Adăugarea `elo_diff`, `off_diff`, `def_diff` în `FEATURE_COLUMNS`. Datele există deja, nu se colectează nimic.

**De ce e primul**: §3 arată că diferențele sunt staționare pe șase ani, iar nivelurile nu. E singura intervenție care atacă *direct* cauza măsurată. Testabil într-o singură antrenare de Challenger.

**Capcană**: adăugarea diferenței fără eliminarea nivelurilor lasă modelul liber să folosească tot nivelurile. Ablația trebuie să testeze ambele variante (adăugare vs. înlocuire).

### B. Ponderare după recență

`sample_weight` descrescător cu vechimea, în `_walk_forward_validate()`. Atacă §1 (diluția 100:1) și §2 (regimul vechi) simultan, cu **un parametru**.

**De ce nu e primul**: reduce eșantionul efectiv, deci poate crește varianța. Iar dacă A rezolvă nestaționaritatea, B devine mai puțin necesar — deci ordinea contează.

### C. Tratarea feature-urilor avansate

Variante: (a) backfill retroactiv al celor 4 coloane pe istoric (dacă datele brute există); (b) model separat pe subsetul de 16%; (c) eliminarea lor din `FEATURE_COLUMNS`. **(c) e cel mai onest de testat primul** — un feature prezent în 16% din antrenare poate să dăuneze, nu să ajute.

### D. ADR-073, pentru orice merge mai adânc

Nimic din cele de mai sus nu poate fi verificat *până la intrările servite*, fiindcă acelea nu se persistă încă. Codul e pe `main`, flagul oprit. **Asta e exact nevoia pentru care a fost construit.**

### Ce NU recomand

- **Un algoritm nou** (CatBoost, LightGBM, rețele). Problema măsurată nu e forma funcțională — e distribuția datelor și nestaționaritatea feature-urilor. Un algoritm nou pe aceleași date ar moșteni exact aceleași probleme.
- **Mai multe date istorice.** Ar agrava §2, nu l-ar rezolva.

---

## 7. Rezerve

- Diagnosticul explică **de ce ML e slab**, nu garantează că A sau B îl fac mai bun. Fiecare rămâne o ipoteză de testat prin ablație.
- Plafonul structural rămâne: favoritul caselor nu e niciodată remiza, iar 23,9% din meciuri se termină egal — deci acuratețea e plafonată la ~76% pentru orice sistem de tip argmax.
- Nici Oracle nu bate piața semnificativ (z = 1,96, exact la prag). „ML să devină cel mai bun" e un obiectiv rezonabil față de Oracle, nu neapărat față de case.
