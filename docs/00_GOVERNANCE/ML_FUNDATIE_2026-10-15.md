# ML — fundație pentru lucrul de mâine (15 octombrie)

Punct de plecare pentru îmbunătățirea Machine Learning Engine. Conține tot ce s-a măsurat pe 14 octombrie, ipotezele de testat (inclusiv cea a proprietarului produsului), designul experimentului și capcanele identificate.

**Nimic din ce urmează nu e implementat.** Toate măsurătorile sunt read-only. Niciun cod schimbat, nicio scriere în baza de date.

Context complet, cu toate tabelele: `DIAGNOSTIC_ML_2026-10-14.md` și `COMPARATIE_MOTOARE_2026-10-14.md`.

---

## 1. Unde suntem — cele patru fapte care contează

Pe **998 de meciuri comune**, comparație împerecheată: **Blend 0,5070 > Oracle 0,4940 > ML 0,4699**. Piața: 0,5233.

### F1. ML nu învață — platou măsurat pe propria validare

| Antrenare | Data | `samples_used` | Acuratețe | Log-loss | Brier |
|---|---|---:|---:|---:|---:|
| `6e7265c5` | 6 sep | 51.418 | 0,4834 | 1,0308 | 0,6177 |
| `174e7e17` | 20 sep | 51.720 | 0,4854 | 1,0310 | 0,6178 |
| `dda4f7f3` | 14 oct | 51.926 | 0,4853 | 1,0307 | 0,6176 |

Cinci săptămâni, mișcare în a patra zecimală. **+508 meciuri pe o bază de 51.400 = +1,0% per reantrenare**, deci datele noi sunt diluate ~100:1.

### F2. Deriva de distribuție e monotonă

2021 → 2026: rating ofensiv mediu **0,924 → 1,113**; ELO mediu **1502,6 → 1589,4**; feature-uri avansate **0% → 74,8%**; ligi **40 → 18**. Pe tot setul, ratingul ofensiv e la **0,92 abateri standard** între istoric și sezonul curent.

### F3. Semnalul e în diferențe; modelul primește niveluri

Nivelurile derivă (+87 ELO, +0,20 rating). **Diferențele sunt stabile pe șase ani**: `elo_diff` între −0,52 și +1,31; `off_diff` între −0,009 și −0,003.

`FEATURE_COLUMNS` conține `home_elo`/`away_elo` ca **niveluri absolute**. Un arbore poate reconstrui diferența doar prin perechi de tăieturi, iar acele praguri **se demodează** pe măsură ce nivelurile se inflatează.

Verificat că **raportul nu e soluția**: `home_off / away_def` derivă și el (0,794 → 0,908). Doar diferența e staționară.

### F4. Patru feature-uri din 14 lipsesc la antrenare, există la servire

16,0% acoperire în istoric vs. **89,1%** în sezonul curent, pentru `corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance`. Modelul învață că „lipsă" e norma.

**Confirmare**: live 0,4699 vs. validare 0,4853 — **−1,5pp**, semnătura derivei de distribuție. Nu e scurgere temporală; walk-forward e corect implementat.

---

## 2. Ipoteza proprietarului produsului — „un istoric mai scurt îl face mai precis"

> *„Poate și istoricul de 5 ani îl afectează. Poate un istoric mai scurt, de maxim 1 an și cel în curs, îl face mai precis."*
> — proprietar produs, 2026-10-14

**Ipoteza e susținută de date pe axa principală, și e acum măsurată**, nu doar plauzibilă:

| Fereastră | Meciuri | % feat. avansate | Distanță rating ofensiv | Distanță ELO | Ligi |
|---|---:|---:|---:|---:|---:|
| **A.** tot istoricul (regimul de azi) | 58.653 | 17,7% | **−0,197** | −38,1 | 43 |
| **B.** ultimii 3 ani | 27.005 | 35,6% | −0,153 | −18,8 | 43 |
| **C.** ultimii 2 ani | 12.525 | 48,3% | −0,126 | **−2,0** | 43 |
| **D.** ultimul 1 an | 3.618 | **71,9%** | **−0,052** | +30,2 | **18** |
| **E.** doar sezonul curent | 1.347 | 89,1% | 0,000 | 0,0 | 18 |

*„Distanță" = media feriestrei minus media sezonului curent (ce prezicem efectiv).*

**Ce confirmă ipoteza**: la 1 an, distanța de rating scade de **~4×** (−0,197 → −0,052) iar acoperirea feature-urilor crește de **~4×** (17,7% → 71,9%). Ambele atacă direct F2 și F4.

### Dar trei lucruri pe care măsurătoarea le scoate la iveală și care NU erau evidente

**(a) ELO-ul nu e monoton — fereastra de 2 ani nimerește mai bine decât cea de 1 an.** Distanța de ELO: −2,0 la 2 ani, dar **+30,2** la 1 an (depășește în cealaltă direcție). Cauza: Jan–Iun 2026 a avut ELO mediu mai mare (1589) decât sezonul curent Iul–Oct 2026 (1564,5) — efect de graniță de sezon.

**Consecința e importantă**: nivelul ELO nu e stabil nici măcar în interiorul aceluiași an. **O fereastră urmărește o țintă mobilă; feature-urile de diferență fac ținta irelevantă.** Asta întărește ipoteza H1 de mai jos față de H2 — nu o înlocuiește, dar schimbă ordinea.

**(b) Costul de eșantion e abrupt**: 52k → 3.618 la 1 an, o reducere de **14×**. Cu 14 feature-uri e lucrabil, dar varianța crește. Fereastra de 2 ani (12.525) e compromisul evident de testat alături.

**(c) Numărul de ligi scade 43 → 18 exact la 1 an.** E **ambivalent**, nu un câștig curat: se potrivește mai bine cu ce servim (18 ligi), dar modelul pierde generalizarea între ligi. De urmărit separat în rezultate, nu de presupus într-un sens sau altul.

---

## 3. Ipotezele de testat, cu designul experimentului

Toate sunt schimbări în **Learning Core**. Niciuna nu atinge Oracle, `weights.json` sau predicția servită. Fiecare cere **ablație**, per regula ML din `CLAUDE.md`.

| | Ipoteza | Ce atacă | Cost |
|---|---|---|---|
| **H1** | Feature-uri de **diferență** (`elo_diff`, `off_diff`, `def_diff`) | F3 — cauza măsurată | Mic: datele există |
| **H2** | **Fereastră de istoric** scurtată (1 an / 2 ani) | F1 + F2 + F4 | Mic: un filtru |
| **H3** | **Ponderare după recență** (`sample_weight` descrescător) | F1 + F2, fără pierdere de eșantion | Mic: un parametru |
| **H4** | **Eliminarea** celor 4 feature-uri rare | F4 | Mic |

### Designul care evită cea mai probabilă greșeală

**NU se testează una câte una, în serie.** H1 și H2 pot fi substitute parțiale: dacă fereastra rezolvă nestaționaritatea, diferențele par inutile — și invers. Testate secvențial, a doua ar apărea mereu „fără efect", indiferent de ordine.

**Design propus: grilă 3 × 2**

| | niveluri (azi) | niveluri + diferențe |
|---|---|---|
| tot istoricul | **referință** | H1 |
| 2 ani | H2 | H1+H2 |
| 1 an | H2′ | H1+H2′ |

Șase antrenări, aceeași validare walk-forward, `random_state` fixat. H3 și H4 se testează **după**, pe configurația câștigătoare — altfel grila explodează la 24 de celule fără să câștige claritate.

### Criteriul de succes, stabilit ÎNAINTE de a rula

- **Primar**: log-loss și Brier pe walk-forward — sunt metrici de calibrare, mai sensibile și mai puțin zgomotoase decât acuratețea la n mic.
- **Secundar**: acuratețea.
- **Poarta reală rămâne neschimbată**: promovarea cere Brier + log-loss + acuratețe *simultan* semnificative contra Oracle, pe rândul `control` (North Star #2). O îmbunătățire de validare **nu e** o promovare.

---

## 4. Capcane identificate, de evitat explicit

1. **Adăugarea diferențelor fără eliminarea nivelurilor** lasă modelul liber să folosească tot nivelurile. Grila trebuie să conțină și varianta „înlocuire", nu doar „adăugare".

2. **Comparația pe ferestre diferite de validare e invalidă.** Un model antrenat pe 1 an și validat pe 1 an nu e comparabil cu unul antrenat pe 5 ani și validat pe 5 ani. **Setul de validare trebuie să fie același pentru toate cele șase celule** — de preferat sezonul curent, fiindcă el e ce prezicem.

3. **n = 3.618 la fereastra de 1 an** înseamnă varianță mai mare. O diferență de 0,5pp între celule poate fi zgomot. Intervalele de încredere sunt obligatorii, nu opționale.

4. **Nu se schimbă nimic la Oracle.** Chiar dacă un experiment ar sugera o recalibrare, aceea e un experiment separat, cu aprobare proprie (regula din §Filosofia proiectului).

5. **ADR-073 rămâne precondiția pentru orice merge mai adânc** — intrările servite încă nu se persistă, deci nu se poate verifica nimic *până la ce a primit efectiv modelul la servire*. Codul e pe `main`, flagul oprit.

6. **Verdictele din `experiment_registry` dinainte de 14 octombrie sunt calculate pe baseline-ul înghețat** și nu se citează ca fapte.

---

## 5. Ce NU se face, și de ce

- **Algoritm nou** (CatBoost, LightGBM, rețele, Transformer). Problema măsurată nu e forma funcțională — e distribuția datelor și nestaționaritatea feature-urilor. Orice algoritm pe aceleași date le-ar moșteni identic. De reconsiderat **după** ce H1-H4 sunt epuizate, nu înainte.
- **Mai multe date istorice.** Ar agrava F2.
- **Colectare de date noi** (accidentări, Transfermarkt). Deprioritizat separat: reperul extern arată Oracle la −1,98pp de piață pe 97,5% din meciuri, **nesemnificativ** (z = 1,35) — deci nu se vede headroom acolo. H1-H4 nu cer nicio colectare: toate datele există.

---

## 6. Rezerve, scrise explicit

- Diagnosticul explică **de ce** ML e slab. Nu garantează că H1-H4 îl fac mai bun. Rămân ipoteze.
- Plafon structural: favoritul caselor nu e **niciodată** remiza (0 din 986), iar **23,9%** din meciuri se termină egal. Acuratețea e deci plafonată la ~76% pentru orice sistem de tip argmax — motiv tehnic să nu se judece progresul doar după acuratețe.
- Nici Oracle nu bate piața semnificativ (z = 1,96, exact la prag). „ML să devină cel mai precis" e un obiectiv rezonabil **față de Oracle**, nu neapărat față de case.
- `flashscore_team_dna` **nu e un motor** — sunt probabilitățile Oracle (diferență maximă 0,000050 pe 1162 de fixture-uri). Nu intră în nicio comparație între motoare.
