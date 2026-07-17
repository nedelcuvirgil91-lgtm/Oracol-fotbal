# ELO_ROOT_CAUSE_ANALYSIS_2026-07-13.md — Football Oracle

**Status**: Cauza exactă, demonstrată prin măsurători reale — zero cod scris, zero fișier modificat, zero soluție propusă. Continuă `ELO_FIDELITY_AUDIT_2026-07-13.md`.
**Metodă**: am rulat local, azi, șase experimente separate pe date reale (53.409 meciuri) — nu am presupus nicio cauză, am testat fiecare ipoteză izolat.

---

## Rezumat — răspuns direct la întrebarea centrală

**Nu e o singură cauză. Sunt trei cauze independente, demonstrate separat, cu ponderi diferite pe echipă:**
1. **Inițializare la 1500 + fereastră de date insuficientă** — cauza dominantă, dar **nu suficientă singură** pentru toate echipele (demonstrat prin simulare, nu presupus).
2. **Reactivitatea formulei în sine** (K-factor/parametri) — demonstrat printr-un test care elimină explicit ipoteza „doar lipsă de istoric": chiar pornind de la valoarea live corectă, ratingul deviază semnificativ pentru mai multe echipe.
3. **Un bug de normalizare a numelui de echipă**, specific și critic pentru Atletico Madrid — nu pentru celelalte 4 echipe testate (verificat, nu presupus).

Un al patrulea factor investigat (**meciuri duplicate în `match_history`**, 2,4% din tot setul de date) e real, demonstrat, dar **impact neglijabil** asupra ratingului final — testat izolat, nu doar presupus minor.

---

## 1. Lipsa istoricului — suficientă matematic? Testată, nu presupusă

Am reconstruit distribuția reală pe ani a `match_history`: **500 meciuri în 2000, apoi gol complet 2001-2020 (zero meciuri), apoi densitate mare doar din 2021** (6.757 în 2021, urcând la 13.570 în 2023). Fereastra reală de date pentru echipele mari e efectiv de **~5 ani**, nu 25.

**Test direct**: am repetat de 3 ori consecutiv (proxy pentru „~15 ani echivalenți") aceeași fereastră densă (2021-2026, 52.909 meciuri), pornind de la 1500, formula neschimbată:

| Echipă | Live | După ~5 ani | După ~10 ani | După ~15 ani | Verdict |
|---|---:|---:|---:|---:|---|
| Bayern Munich | 1940 | 1906 (−34) | 1935 (−5) | 1952 (+12) | **Converge complet** — lipsa de istoric explică singură deviația |
| Arsenal | 1915 | 1846 (−69) | 1900 (−15) | 1935 (+20) | **Converge complet** — la fel |
| Manchester City | 1950 | 1781 (−169) | 1839 (−111) | 1875 (−75) | Converge parțial — lipsa de istoric explică O PARTE, nu tot |
| Real Madrid | 1945 | 1780 (−165) | 1808 (−137) | 1824 (−121) | **NU converge** — gap rămâne mare chiar și la ~15 ani echivalenți |
| Atletico Madrid | 1890 | 1529 (−361) | 1577 (−313) | 1623 (−267) | NU converge — dar confundat cu bug-ul de normalizare (§4) |

**Concluzie demonstrată**: lipsa istoricului e **suficientă** pentru unele echipe (Bayern, Arsenal), dar **nu e suficientă singură** pentru altele (Real Madrid, parțial Manchester City) — pentru acestea, chiar și un istoric mult mai lung, cu același tipar competitiv, nu ar închide complet decalajul. Nu pot generaliza „lipsa de istoric explică totul" — datele arată clar că nu, pentru cel puțin 2 din 5 echipe testate.

---

## 2. Formula implementată e identică cu eloratings.net?

**Nu pot demonstra asta din acest mediu** — fără acces la rețea live, nu pot citi metodologia publicată de eloratings.net. Ce pot spune, separat pe surse de certitudine:

- **Demonstrat din cod**: formula implementată (`ELOTracker`, `sync/backfill_features.py`) e `expected = 1/(1+10^((R_b−R_a)/400))`, K variabil (40 sub 10 meciuri, 32 după), home advantage fix +50, start 1.500 — parametri standard de Elo pentru fotbal, dar **specifici acestei implementări**, nu confirmați identici cu eloratings.net.
- **Cunoștințe generale, NEVERIFICATE live, semnalate explicit ca atare**: proiectul World Football Elo Ratings (eloratings.net) e documentat public ca folosind un K-factor variabil **după importanța competiției** (amical vs. calificare vs. turneu final), nu după numărul de meciuri jucate, plus un multiplicator de diferență de scor. Dacă asta e corect, e o diferență structurală de metodologie — dar **nu pot confirma acest lucru din acest mediu**, deci nu-l tratez ca demonstrat.

**Concluzie**: nedemonstrabil direct. Ce POT demonstra e efectul indirect — testul din §3 arată că formula noastră, indiferent dacă diferă sau nu de eloratings.net, **nu păstrează stabil un rating corect** pentru mai multe echipe, ceea ce e o dovadă indirectă de problemă de calibrare, chiar dacă nu pot localiza exact care parametru.

---

## 3. Test decisiv: pornind de la valoarea LIVE corectă, formula rămâne stabilă?

Am rulat replay-ul complet, dar **am inițializat echipele cunoscute cu rating-ul lor live/fallback real**, nu 1.500 — aceeași formulă, aceleași meciuri reale. Dacă „lipsa de istoric" ar fi singura cauză, ratingul ar trebui să rămână aproape de valoarea de start.

| Echipă | Live | Final (start = live) | Derivă | Derivă % |
|---|---:|---:|---:|---:|
| Bayern Munich | 1940 | 1928 | −12 | −0,6% |
| Arsenal | 1915 | 1886 | −29 | −1,5% |
| Atletico Madrid | 1890 | 1841 | −49 | −2,6% |
| FC Barcelona | 1928 | 1845 | −83 | −4,3% |
| Paris Saint-Germain | 1920 | 1845 | −75 | −3,9% |
| Manchester City | 1950 | 1825 | −125 | −6,4% |
| Real Madrid | 1945 | 1800 | −145 | −7,5% |
| Juventus | 1895 | 1719 | −176 | −9,3% |
| Liverpool | 1932 | 1714 | −218 | −11,3% |
| Chelsea | 1908 | 1661 | −247 | **−13,0%** |

**Rezultat decisiv**: chiar pornind de la valoarea corectă, formula **deviază semnificativ** pentru Chelsea (−13%), Liverpool (−11,3%), Juventus (−9,3%), Real Madrid (−7,5%), Manchester City (−6,4%). Pentru Bayern și Arsenal, deriva e mică — consistent cu observația de la §1 că exact aceste două converg bine din 1.500. **Asta demonstrează, nu presupune, că „lipsa de istoric" nu e explicația completă** — formula însăși, aplicată pe rezultate reale, nu păstrează un rating corect pentru cel puțin 5 din 10 echipe testate.

---

## 4. Normalizarea echipelor — cauză reală, dar izolată la o singură echipă din cele 5

Verificat direct în date: **`"Club Atlético de Madrid"` nu se normalizează la `"Atletico Madrid"`** (`mappings.normalize_team_name()`) — nu există alias pentru varianta lungă cu „Club" ca prefix. Consecință măsurată:

- Sub numele `"Atletico Madrid"`: **10 meciuri**, 2021-09-15 → 2022-04-13.
- Sub numele `"Club Atlético de Madrid"`: **150 meciuri**, 2023-08-14 → 2026-05-24.

Aceeași echipă reală, ruptă în două entități complet separate în `ELOTracker` — cea „canonică" vede doar 6% din meciurile reale ale clubului, exact din cea mai puțin relevantă perioadă (2021-2022, cea mai apropiată de start-ul rece). **Asta explică, separat de cauza generală, de ce Atletico Madrid are cea mai mare eroare din tot eșantionul (−19%).**

Verificat explicit pentru celelalte 4 echipe (Bayern Munich, Real Madrid, Arsenal, Manchester City): **toate variantele lor de nume brute normalizează corect** la un singur nume canonic (`"Real Madrid CF"`→`"Real Madrid"`, `"FC Bayern München"`→`"Bayern Munich"`, etc.) — verificat, nu presupus. **Bug-ul de normalizare NU e o cauză generală — e specific și demonstrat doar pentru Atletico Madrid** din acest eșantion.

---

## 5. Meciuri duplicate — cauză reală, dar impact neglijabil (testat, nu presupus)

Verificat: **646 meciuri (1.292 rânduri, 2,4% din tot `match_history`) apar de două ori** — o dată sub eticheta de ligă „normală" (ex. „Premier League"), o dată sub codul brut football-data.co.uk (ex. „E0") — aceleași echipe, aceeași dată, ambele normalizându-se la același nume canonic. Concentrate în cele 5 ligi mari: Premier League (392 rânduri), Bundesliga (98), Serie A (84), La Liga (60), Ligue 1 (12).

**Test izolat**: am rulat simularea de la §3 (start = live) și cu duplicate eliminate. Diferența față de rularea cu duplicate:

| Echipă | Cu duplicate | Fără duplicate | Diferență |
|---|---:|---:|---:|
| Chelsea | 1661 | 1655 | 6 puncte |
| Real Madrid | 1800 | 1804 | 4 puncte |
| Manchester City | 1825 | 1815 | 10 puncte |
| Liverpool | 1714 | 1716 | 2 puncte |

**Concluzie**: bug-ul e real și confirmat (nu presupus), dar impactul asupra ratingului final e **sub 1%** pentru toate echipele testate — nu explică deriva mare observată la §3. Rămâne un defect de calitate a datelor care merită corectat pentru integritate generală, dar nu e cauza principală a divergenței ELO.

---

## 6. Reconstrucția cronologică — unde apare exact deviația

Pentru toate cele 5 echipe cerute, deviația **nu apare progresiv — apare instant, la primul meci procesat**, din cauza inițializării la 1.500:

| Echipă | Elo la meciul #1 | Gap la meciul #1 | Gap final |
|---|---:|---:|---:|
| Bayern Munich | 1517 | −423 | −31 |
| Real Madrid | 1523 | −422 | −164 |
| Arsenal | 1483 | −432 | −68 |
| Atletico Madrid | 1497 | −393 | −359 |
| Manchester City | 1483 | −467 | −168 |

Gap-ul se îngustează apoi neuniform (verificat pe checkpoint-uri la fiecare 20 de meciuri, `ELO_FIDELITY_AUDIT` §4 + date suplimentare din acest document) — nu monoton, cu oscilații reale (ex. Manchester City: gap −53 la meciul #200, apoi brusc −318 la meciul #220, revenind treptat până la −168 final — variație de formă reală pe termen scurt, amplificată de reactivitatea formulei, vezi §3).

---

## 7. Clasificare finală, după impact demonstrat

| Cauză | Impact | Dovadă |
|---|---|---|
| **Inițializare la 1.500 (cold start)** | **Critică** | Gap de −400...−470 la meciul #1, pentru toate cele 5 echipe, instant, universal |
| **Fereastra de date istorice insuficientă** | **Critică** | Testul de repetare (§1): suficientă pentru 2/5 echipe, insuficientă pentru 2/5, confundată pentru 1/5 |
| **Reactivitatea formulei (K-factor/parametri, neizolabilă exact)** | **Majoră** | Test decisiv (§3): derivă de până la −13% chiar pornind de la valoarea corectă — demonstrat independent de lipsa de istoric |
| **Normalizarea numelui de echipă** | **Majoră, dar specifică** | Critică pentru Atletico Madrid (150 vs. 10 meciuri), verificat absentă la celelalte 4 echipe testate |
| **Meciuri duplicate în `match_history`** | **Minoră** | Confirmat 2,4% din date, dar impact testat sub 1% pe rating final |
| Formula exact identică cu eloratings.net | **Nedemonstrabil** | Fără acces la sursa live din acest mediu — nu presupun |
| Contribuția izolată a home advantage (+50) față de K-factor | **Nedemonstrat** | Nu am rulat un test dedicat care separă cei doi parametri — semnalez explicit, nu presupun o pondere |

---

## 8. Răspuns la întrebarea de fond: metodologie, implementare, sau date?

**Toate trei, cu roluri diferite, demonstrate separat:**
- **Datele** (fereastra istorică scurtă) sunt cauza dominantă pentru echipele „ușoare" de reconstruit (Bayern, Arsenal) — o problemă de volum, nu de metodă.
- **Metodologia/parametrii** (nu pot separa exact K-factor de home advantage cu testele rulate) contribuie independent și demonstrabil, pentru echipe unde chiar și un start corect deviază (Chelsea, Liverpool, Real Madrid, Manchester City, Juventus).
- **Implementarea** (normalizarea numelui) e o cauză reală, dar izolată — un singur bug demonstrat, la o singură echipă din cinci, nu un defect sistemic de implementare.

Nu există o singură „cauză exactă" unică, așa cum ar fi sugerat auditul anterior — există trei cauze independente, cu ponderi diferite pe echipă, toate demonstrate separat prin măsurători, nu presupuse.
