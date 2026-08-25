# xG Oracle — preanaliză de calibrare: ipoteza inițială e RESPINSĂ

**Data**: 2026-08-25
**Status**: Analiză completă. **Nu se propune niciun experiment de recalibrare.**
**Nu modifică nimic**: niciun parametru Oracle, niciun flag, niciun cod de predicție.

---

## De ce a existat acest punct

Nota din `CLAUDE.md` (2026-08-10, n=35) semnala o asimetrie între corelația pe
partea gazdei (0,019) și cea pe oaspete (0,550), plus un MAE agregat de 0,747, cu
recomandarea de a re-rula peste 2-3 săptămâni. Ulterior s-a adăugat observația
unei **subdispersii de ~40%**: Oracle prezice prea „la mijloc".

Ipoteza implicită era: *predicțiile sunt prea comprimate, deci trebuie
dilatate*. Eșantionul a ajuns la n=250, deci punctul a devenit testabil.

**Ipoteza e respinsă de date.** Detaliile mai jos.

---

## Pasul 0 — separarea liniei de bază neutre (ADR-065)

Prima măsurătoare pe tot corpusul e contaminată. Champions League și Europa
League au **dispersie zero** a predicției: `stddev(home_xg_pred) = 0.000`.
Fiecare meci primește exact aceeași valoare (0,867 la CL, 0,784 la EL) — sunt
meciuri de calificare între echipe fără date, unde Oracle cade pe linia de bază
neutră (`data_quality='neutral'`).

| Subset | n | pred. medie | real medie | disp. pred | disp. real | raport | corelație (gazdă/oaspete) |
|---|---|---|---|---|---|---|---|
| **Informat** | 225 | 1,594 | 1,557 | 0,557 | 0,924 | 0,603 | 0,142 / 0,318 |
| Neutru | 25 | 0,827 | 1,948 | 0,043 | 0,948 | 0,045 | −0,085 / −0,021 |

Tot ce urmează folosește **exclusiv subsetul informat** — aceeași disciplină pe
care ADR-065 a impus-o deja evaluării Challenger-ului.

---

## Constatarea 1 — media e bine calibrată, nu există bias

1,594 prezis vs. 1,557 real. Diferență de 2,4%. **Nu există o problemă de
nivel.** Orice recalibrare care ar muta media ar strica ceva ce funcționează.

## Constatarea 2 — subdispersia e reală, dar nu e un defect

Raportul de dispersie e 0,603: predicțiile variază cu 60% din cât variază
realitatea. Asta e observația care a pornit tot punctul. Dar dispersia se
judecă **împreună cu corelația**, nu singură.

Corelația pe partea gazdei e **0,142**. La n=225, eroarea standard e ≈0,067,
deci intervalul e aproximativ 0,01–0,27 — abia distinct de zero.

Pentru o predicție `p` și o realitate `a`, multiplicatorul care minimizează
eroarea pătratică aplicat abaterilor lui `p` este `k* = corr · sd(a)/sd(p)`.
Cu cifrele de mai sus: `k* = 0,142 × 0,924 / 0,557 = 0,236`.

**Adică optimul e să COMPRIMĂM predicțiile, nu să le dilatăm.** Exact opusul
ipotezei inițiale.

## Constatarea 3 — verificat empiric, nu doar algebric

Scalând abaterile față de medie cu diverși `k`, pe subsetul informat:

| k | MAE (vs xG real) | MSE (vs xG real) |
|---|---|---|
| 0,00 — constanta mediei | 0,7244 | 0,8518 |
| **0,25** | 0,7093 | **0,8348** |
| **0,50** | **0,7079** | 0,8563 |
| 0,75 | 0,7267 | 0,9164 |
| **1,00 — ce facem azi** | **0,7601** | **1,0152** |
| 1,25 | 0,8110 | 1,1525 |
| 1,66 — „repararea" subdispersiei | 0,9313 | 1,4612 |
| 2,00 | 1,0489 | 1,7960 |

Optimul empiric (0,25–0,50) confirmă predicția algebrică. Iar „repararea"
subdispersiei ar înrăutăți MAE cu 23% și MSE cu 44%.

## Constatarea 4 — pe endpoint-ul care contează, Oracle chiar aduce semnal

`xg_pred` nu există ca să prezică xG-ul real; alimentează Poisson pentru
**goluri**. Măsurat pe același subset (n=227), corelația cu golurile reale e
**0,204** — mai bună decât cea cu xG-ul real.

| k | MAE (vs goluri) | MSE (vs goluri) |
|---|---|---|
| 0,0 | 1,0686 | 1,6269 |
| **0,5** | **1,0231** | **1,5596** |
| 1,0 — azi | 1,0295 | 1,6459 |
| 1,5 | 1,0876 | 1,8858 |

Aici, spre deosebire de comparația cu xG-ul real, **`xg_pred` bate constanta**
(MAE 1,0295 vs 1,0686). Deci feature-ul e util, doar ușor prea dispersat.

---

## Concluzie și recomandare

**1. Ipoteza „subdispersia trebuie reparată prin dilatare" e respinsă**, pe
ambele endpoint-uri, algebric și empiric. Dacă s-ar fi implementat fără această
verificare, ar fi înrăutățit predicția cu 23–44%.

**2. NU recomand un experiment de recalibrare acum.** Câștigul maxim disponibil,
pe endpoint-ul real, e de la MAE 1,0295 la 1,0231 — **0,6%**, măsurat
*in-sample*, pe n=227. Un `k` ales pe aceleași date pe care e evaluat e
supraadaptat prin construcție; out-of-sample câștigul ar fi și mai mic. Regula
proiectului cere dovadă statistică pe metrici multiple pentru orice schimbare de
formulă Oracle — 0,6% in-sample nu se apropie de acel prag.

**3. Asimetria gazdă/oaspete din nota inițială (0,019 vs 0,550, n=35) nu s-a
confirmat.** La n=225 diferența s-a redus la 0,142 vs 0,318 — ambele mici, în
aceeași zonă. Era zgomot de eșantion mic, nu un tipar.

**4. Ce merită urmărit în schimb**: corelația de 0,142/0,204 e joasă. Întrebarea
utilă nu e „cum recalibrăm dispersia", ci „de ce `calibrate_xg()` extrage atât
de puțină informație per meci". Aia e o investigație de feature engineering, nu
de calibrare — și cere un eșantion mai mare pentru orice concluzie.

---

## Dacă totuși se decide un experiment, protocolul e acesta

Nu îl recomand azi, dar îl las scris ca să nu fie improvizat mai târziu.

1. **Walk-forward, fereastră expandabilă.** `k` se estimează EXCLUSIV pe
   meciurile dinaintea celui evaluat. Zero scurgere temporală (regula #7).
   Fără asta, orice cifră e supraadaptată — inclusiv cele de mai sus, care
   sunt marcate explicit ca in-sample.
2. **Subsetul informat**, cu excluderea liniei de bază neutre (ADR-065).
3. **Trei metrici simultan**, pe GOLURI, nu pe xG: MAE, MSE, log-loss al
   probabilităților 1X2 rezultate. Îmbunătățire simultană sau nimic (#2).
4. **Prag minim de eșantion**: n ≥ 500 pe subsetul informat. La n=227,
   intervalul de încredere al corelației e prea larg pentru o decizie de formulă.
5. **`random_state` fixat**, rezultat reproductibil.
6. **Aprobare separată, explicită** înainte de orice atingere a
   `feature_engine.calibrate_xg()`. Un backtest favorabil nu e, singur,
   suficient — regula e deja scrisă în `CLAUDE.md`.

---

## Ce anulează acest document

Nota din `CLAUDE.md` care descrie asimetria gazdă/oaspete ca tipar de urmărit și
subdispersia ca justificare pentru un experiment de recalibrare. Ambele au fost
măsurate la eșantion de 7 ori mai mare și nu se susțin. Nota rămâne în istoric;
concluzia ei e înlocuită de acest document.
