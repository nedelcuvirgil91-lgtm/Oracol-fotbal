# European Competition Form-History Filtering Defect

**Status**: DIAGNOSTIC — NEREPARAT, deliberat. **Titlul („Defect") e prea absolut** — vezi §2c: filtrul pe competiție codifică semnal real și trebuie PĂSTRAT; ce lipsește e legarea de sezon și o cale de rezervă onestă.
**Data**: 2026-09-04 · **extins 2026-09-08** cu a doua manifestare (§2b) și cu contra-argumentul testat (§2c)
**Descoperit în**: auditul Top Value Bets (ADR-071), la investigarea celor 25 de meciuri în care egalul apărea ca rezultat cel mai probabil
**Decizie proprietar produs**: se documentează acum, se repară într-un task separat de arhitectură de date. Nu se aplică niciun fix local.

> **Citește §2b și §2c înainte de §3.** Documentul descria inițial O SINGURĂ
> manifestare — echipa fără niciun meci în competiție, care ajunge la valori
> neutre. Pe 2026-09-08 s-au adăugat două lucruri care schimbă concluzia:
>
> - **§2b** — o a DOUA manifestare, din aceeași linie de cod, cu simptom opus
>   (istoric prezent dar din alt sezon) și **fără nicio protecție în aval**.
> - **§2c** — un contra-argument al proprietarului produsului, **testat pe date
>   și confirmat**: filtrul pe competiție codifică semnal real (dispersie de 2,0
>   ppm între echipe, campionat vs. UCL) și e singura ajustare la forța
>   adversarului pe care motorul o are azi. **Nu se șterge.**
>
> Concluziile din §3-§5 acoperă doar prima manifestare; secțiunile sunt marcate
> acolo unde nu se mai aplică integral. §6.1 a fost ÎNCHISĂ cu date.

---

## 1. Simptomul observat

În setul curat de predicții (predicție dovedit anterioară loviturii de start), **25 de meciuri aveau egalul drept rezultat cel mai probabil al modelului**. Prima ipoteză — „modelul are o preferință pentru egaluri" — s-a dovedit falsă la prima verificare.

**Toate cele 25 au probabilități identice, la zecimală:**

```
1 = 34,1%      X = 37,0%      2 = 28,9%
```

Nu 25 de predicții asemănătoare. Aceeași predicție, de 25 de ori.

| Meci | ELO gazdă / oaspete | Istoric gazdă / oaspete | Predicție |
|---|---|---|---|
| Benfica – Aarhus | 1802 / 1597 | 352 / 111 | 34,1 / 37,0 / 28,9 |
| Omonia (CYP) – Lincoln Red Imps | 1501 / 1501 | 3 / 3 | 34,1 / 37,0 / 28,9 |
| Hearts – Benfica | 1576 / 1802 | 151 / 350 | 34,1 / 37,0 / 28,9 |
| Besiktas – Kauno Zalgiris (LTU) | 1661 / 1484 | 175 / 4 | 34,1 / 37,0 / 28,9 |
| Universitatea Craiova – Ararat-Armenia | 1696 / 1475 | 263 / 4 | 34,1 / 37,0 / 28,9 |

Benfica, cu ELO 1802 și 352 de meciuri în istoric, primește exact aceeași predicție ca Lincoln Red Imps, cu ELO 1501 și 3 meciuri. **Nu e o predicție — e o constantă.**

---

## 2. Cauza rădăcină

`supabase_client.get_team_recent_results()`, linia 372:

```python
res = (
    client.table("match_history")
    .select("home_team,away_team,actual_home_goals,actual_away_goals,"
            "actual_result,kickoff_date")
    .eq("league", league)                      # ← AICI
    .or_(f"home_team.eq.{team},away_team.eq.{team}")
    .not_.is_("actual_result", "null")
    .gte("kickoff_date", cutoff)
    .order("kickoff_date", desc=True)
    .limit(last_n)
    .execute()
)
```

Aceasta e sursa canonică Database-First a formei, folosită de `oracle_engine._build_profile()` (linia 1174) ca **primul** nivel al cascadei de 8 niveluri.

Filtrul `.eq("league", league)` cere ultimele 5 meciuri ale echipei **în aceeași competiție**. Pentru un meci de Europa League înseamnă „ultimele 5 meciuri ale lui Benfica în Europa League, în ultimele 365 de zile".

La începutul unei campanii europene, acel număr e zero. Cascada cade nivel cu nivel până la **Level 6 — Neutral defaults** (`oracle_engine.py:1467-1478`):

```python
off_rating = round(baseline * 0.65, 4)
def_rating = round(baseline, 4)
gf = ga = baseline
data_source = "neutral-defaults"
```

Ambele echipe primesc profile identice, construite din `league_baselines`, iar Poisson-ul produce mereu aceeași distribuție. Egalul iese pe primul loc pentru că e ordinea implicită a acelei constante — nu pentru că modelul „crede" ceva despre meci.

**Nu e o problemă de lipsă de istoric.** Istoricul există (Benfica: 352 de meciuri, Craiova: 263). E invizibil din cauza filtrului.

---

## 2b. A doua manifestare — istoric PREZENT, dar din alt sezon (adăugat 2026-09-08)

**Descoperit de proprietarul produsului**, dintr-o observație pe ecran: „de ce
Real are în aplicație 2 înfrângeri consecutive?" — Flashscore arăta o singură
înfrângere în ultimele 5 meciuri.

### 2b.1 Cazul concret, reprodus rând cu rând

Real Madrid – Inter, Champions League, 2026-09-08 (`flashscore_foBRjez1`).
Aplicația afișa forma **`LLWWW`** pentru Real. Interogarea exactă pe care o face
`get_team_recent_results("Real Madrid", "Champions League", 5)` întoarce:

| Dată | Meci | Pentru Real |
|---|---|---|
| 2026-04-15 | Bayern Munich 4-3 Real Madrid | **L** |
| 2026-04-07 | Real Madrid 1-2 Bayern Munich | **L** |
| 2026-03-17 | Manchester City 1-2 Real Madrid | W |
| 2026-03-11 | Real Madrid 3-0 Manchester City | W |
| 2026-02-25 | Real Madrid 2-1 Benfica | W |

Cele două „înfrângeri consecutive" sunt **sferturile de finală din aprilie**, de
acum 146 de zile. Forma reală, pe toate competițiile, e `LWWWW` — o singură
înfrângere (Betis, 4 septembrie). Același tipar la Inter: `LLWLL`, ultimul meci
folosit din **24 februarie**.

Profilul întreg vine de-acolo, nu doar șirul de formă: Real primește OFF 1,276
(11 goluri în acele 5 meciuri, contra Bayern/City/Benfica), Inter 0,877 (5
goluri în 5, cu 4 înfrângeri). Cifre reale — dintr-o altă perioadă și contra
altui nivel de adversar.

### 2b.2 De ce e mai periculoasă decât prima

Diferența nu e de amploare, e de **vizibilitate**:

| | §1-§2 (manifestarea documentată) | §2b (aceasta) |
|---|---|---|
| Meciuri în competiție, ultimele 365 zile | 0 | 3-5, dar din sezonul trecut |
| Ce produce | constantă identică (34,1 / 37,0 / 28,9) | profil real, vechi de 4-7 luni |
| Nivelul cascadei atins | Level 6 — `neutral-defaults` | **Level DB — `supabase-history`** |
| `data_quality` scris în `match_history` | `neutral` | **`live`** (verificat pe `flashscore_foBRjez1`) |
| Ce vede utilizatorul în UI | — | **„✅ Date reale — meciuri terminate"** |
| Poarta de calitate ADR-071 | **respinge candidatul** | **NU se declanșează** |

Prima manifestare se auto-semnalează: marchează starea ca `neutral`, iar Value
Selector o aruncă (`tests/test_value_selector.py::test_T14_...`). A doua trece
prin toate porțile ca dată bună, cu bifă verde în interfață. **Plasa de
siguranță din §5 nu acoperă acest caz** — nu pentru că e prost construită, ci
pentru că se uită la un semnal (`data_quality`) care aici e, tehnic, corect:
datele CHIAR sunt reale. Doar că nu sunt recente.

### 2b.3 Amploarea, măsurată (2026-09-08)

Cele 72 de echipe cu meciuri în cupele europene în fereastra 8-22 septembrie:

| | echipe |
|---|---:|
| Trec de Level DB (≥3 meciuri în competiție) | 27 |
| — dintre care **exclusiv din sezonul TRECUT** (§2b) | **16** |
| Cad pe cascadă (§1-§2) | 45 |

### 2b.4 Constatarea care schimbă interpretarea defectului

**Toate cele 16 sunt din Champions League, și sunt exact cluburile mari:**

| Echipă | Meciuri CL în fereastră | Cel mai recent folosit | Vechime |
|---|---:|---|---:|
| Villarreal · Napoli · PSV | 8 | 2026-01-28 | **223 zile** |
| Inter Milan · Club Brugge | 10 | 2026-02-24 | 196 zile |
| Borussia Dortmund | 10 | 2026-02-25 | 195 zile |
| Manchester City | 10 | 2026-03-17 | 175 zile |
| Galatasaray | 12 | 2026-03-18 | 174 zile |
| Liverpool · FC Barcelona | 12 | 2026-04-14 | 147 zile |
| Real Madrid · Sporting CP | 12-14 | 2026-04-15 | 146 zile |
| Atletico Madrid | 16 | 2026-05-05 | 126 zile |
| Bayern Munich | 14 | 2026-05-06 | 125 zile |
| Arsenal · Paris Saint-Germain | 15-17 | 2026-05-30 | **101 zile** |

Zero echipe din Europa League sau Conference League.

**Cele două manifestări împart terenul după forța clubului, nu aleatoriu.** Un
club care a mers departe în competiția de anul trecut are ≥3 meciuri în
fereastra de 365 de zile → nimerește §2b. Un club care nu s-a calificat, sau a
ieșit devreme, are 0 → nimerește §1. Rezultatul: **defectul lovește sistematic
cele mai cunoscute și cele mai pariate echipe din Europa**, iar pe acelea le
lovește tocmai pe calea care NU e semnalată nicăieri.

Corolar temporal, de reținut: cele 16 migrează singure către §1 pe măsură ce
meciurile din sezonul trecut ies din fereastra de 365 de zile. Cazul Villarreal/
Napoli/PSV (223 de zile) e deja la ~4 luni de acea graniță. Defectul nu dispare
— își schimbă forma, din „date vechi nesemnalate" în „constantă semnalată".

### 2b.5 Ce NU s-a verificat

- Dacă predicția servită (60,6 / 21,6 / 17,8 pentru Real–Inter) ar fi
  semnificativ diferită cu forma corectă. Ar cere re-rularea motorului cu un
  profil alternativ — nu s-a făcut, nu se presupune.
- Dacă cele 16 apar și în `shadow_predictions`, contaminând evaluarea
  Challenger. §4 nota deja golul echivalent pentru prima manifestare, tot
  neinvestigat.
- Nivelul FS2 (`get_team_recent_form_context`, NEfiltrat pe ligă) nu e atins
  aici, pentru că Level DB reușește înaintea lui — deci întrebarea din §6.3
  („de ce tace FS2?") nu se aplică acestui caz: nu tace, nu ajunge la el.

---

## 2c. Contra-argument testat: filtrul pe competiție NU e un simplu bug (2026-09-08)

**Ridicat de proprietarul produsului**, imediat după §2b: *„ținând cont că UCL e
o competiție nouă, poate ceea ce pare un defect acum, după 3 meciuri în UCL o să
fie adevărata formă. Câteodată unele echipe joacă diferit în competițiile
europene față de campionatele lor — fie mai bine, fie mai rău."*

Ipoteza a fost testată, nu acceptată. **Datele o confirmă**, iar asta schimbă
diagnosticul: titlul acestui document („Defect") era prea absolut.

### 2c.1 Măsurătoarea

Puncte pe meci, sezonul 2025-07-01 → 2026-06-30, aceleași echipe, campionat
intern vs. Champions League (doar echipe cu ≥10 meciuri domestice și ≥6 UCL):

| Echipă | Campionat | UCL | Δ ppm | GD/meci dom. | GD/meci UCL |
|---|---:|---:|---:|---:|---:|
| Villarreal | 1,89 | **0,13** | **−1,77** | +0,68 | −1,63 |
| PSV | 2,47 | 1,00 | −1,47 | +1,65 | 0,00 |
| Napoli | 2,00 | 1,00 | −1,00 | +0,58 | −0,75 |
| Inter Milan | 2,29 | 1,50 | −0,79 | +1,42 | +0,50 |
| Borussia Dortmund | 2,15 | 1,40 | −0,75 | +1,06 | +0,10 |
| Sporting CP | 2,41 | 1,67 | −0,75 | +1,91 | +0,58 |
| FC Barcelona | 2,47 | 1,92 | −0,56 | +1,55 | +1,00 |
| Manchester City | 2,05 | 1,60 | −0,45 | +1,11 | +0,20 |
| Real Madrid | 2,26 | 1,93 | −0,33 | +1,11 | +0,93 |
| Atletico Madrid | 1,82 | 1,50 | −0,32 | +0,47 | +0,44 |
| Bayern Munich | 2,62 | 2,43 | −0,19 | +2,53 | +1,64 |
| Paris Saint-Germain | 2,24 | 2,06 | −0,18 | +1,32 | +1,29 |
| **Liverpool** | 1,58 | **1,75** | **+0,17** | +0,26 | +0,92 |
| **Arsenal** | 2,24 | **2,47** | **+0,23** | +1,16 | +1,53 |

### 2c.2 Ce arată

**Media Δ = −0,58 ppm.** Ăsta e efectul banal, așteptat: adversarii din UCL sunt
mai buni decât media unui campionat, deci toată lumea coboară.

**Dispersia e argumentul: de la −1,77 la +0,23, adică 2,0 puncte pe meci.** Dacă
diferența ar fi doar „adversari mai tari", Δ ar fi aproximativ constant. Nu e —
variază de zece ori între extreme.

Contrastul decisiv: **PSV arată mai bine decât Liverpool în campionat (2,47 vs
1,58) și e substanțial mai slab în Europa (1,00 vs 1,75).** O formă calculată
exclusiv pe campionat ar fi inversat complet ordinea acestor două echipe pentru
un meci de Champions League.

### 2c.3 Confuzia care trebuie numită, nu ascunsă

O parte din dispersie **nu** e „echipa joacă diferit" — e „campionatul intern are
altă tărie". 2,47 ppm în Eredivisie (PSV) nu valorează cât 2,24 în Premier League
(Arsenal). Cele două cauze nu se pot separa cu datele de aici.

**Dar asta întărește concluzia, nu o slăbește**: ambele efecte sunt informație
reală despre nivelul echipei într-un meci european, iar filtrul pe competiție le
captează pe amândouă gratuit. Motorul nu are nicio altă ajustare la forța
adversarului (gol deja documentat, audit Top Value Bets §3/C3) — deci filtrul
face azi o muncă pe care nimic altceva n-o face.

### 2c.4 Consecința pentru diagnostic

**`.eq("league", league)` nu e o eroare de concept. E o implementare care nu-și
duce conceptul până la capăt.**

Recomandarea din §6 („ultimele 5 meciuri indiferent de competiție" ca variantă
posibilă) e, în lumina acestor cifre, **greșită** — ar face PSV să pară un rulou
compresor în Champions League. Vezi §6.1 rescris.

### 2c.5 Ce NU rezolvă contra-argumentul

Trei lucruri rămân probleme reale, independent de faptul că filtrul e conceptual
corect:

1. **Fereastra de 365 de zile n-are noțiunea de sezon.** Formularea proprietarului
   produsului o arată singură: „după 3 meciuri o să avem adevărata formă" — adică
   forma europeană **din campania curentă**. Codul ia ultimele 5 meciuri de UCL
   din ultimul an, indiferent de sezon. Forma lui Real de azi e din
   februarie-aprilie, cu alt lot, după o fereastră de transferuri.
2. **Nu există semnal de vechime** (§2b.2). Un profil de 146 de zile e etichetat
   `live` și afișat ca „✅ Date reale".
3. **Cele 45 de echipe fără istoric european rămân pe constantă** (§1-§2). Acolo
   filtrul nu ajustează nimic — nu întoarce nimic. Forma domestică penalizată,
   marcată explicit ca substitut, ar fi strict mai bună decât o constantă
   identică pentru orice meci.

### 2c.6 Un punct în care contra-argumentul agravează, nu ameliorează

„După 3 meciuri" înseamnă două lucruri, ambele problematice:

- **Ca durată**: din propriile noastre date, etapa 2 e pe 2026-10-13, la 33 de
  zile după prima (8-10 septembrie). Dacă etapa 3 păstrează ritmul, ajunge pe la
  începutul lui noiembrie — **~2 luni** în care cele 16 echipe merg pe date din
  sezonul trecut, iar cele 45 pe constantă. (Descoperirea noastră are doar
  parțial calendarul viitor; data exactă a etapei 3 nu e confirmabilă din bază.)
- **Ca statistică**: la etapa 3 avem **n=3**, iar motorul cere `last_n = 5` și
  pornește de la `MIN_DB_MATCHES = 3`. Trei meciuri e un eșantion subțire pentru
  rating-uri ofensive/defensive — profilul va fi dominat de un singur rezultat
  extrem. Nu e „adevărata formă", e primul semnal al ei.

---

## 3. Impactul măsurat

> **Domeniu de aplicare (precizat 2026-09-08)**: cifrele de mai jos măsoară
> manifestarea din §1-§2 — predicțiile căzute pe `neutral`. Ele NU includ cazul
> §2b, care produce predicții variate, cu `data_quality = live`, deci invizibile
> pentru orice numărătoare bazată pe `neutral`. Coloana „valori distincte de
> `prob_draw`" de mai jos e chiar dovada: cele 7 valori distincte din Champions
> League vin de la echipele care trec de Level DB — adică de la cele 16 din §2b.
> Le vedeam în tabel de la început; le citeam ca „semn de sănătate".

### 3.1 Per competiție (`match_history`, toate predicțiile cu rezultat cunoscut, n=431)

| Competiție | predicții | `neutral` | valori distincte de `prob_draw` |
|---|---:|---:|---:|
| **Europa League** | 37 | **29 (78%)** | **13** |
| **Champions League** | 24 | **19 (79%)** | **7** |
| **Conference League** | 1 | **1 (100%)** | 1 |
| Premier League | 20 | 1 | 20 |
| Serie A | 20 | 0 | 20 |
| MLS | 61 | 0 | 58 |
| Romania SuperLiga | 41 | 0 | 40 |
| Ligue 1 | 19 | 0 | 19 |

Citirea coloanei a treia: în ligile domestice numărul de valori distincte ≈ numărul de meciuri (fiecare meci are predicția lui). În Champions League, **24 de meciuri împart 7 predicții**.

### 3.2 Pe setul curat, fără scurgere temporală (n=365)

- competiții europene: **61 de meciuri**, dintre care **48 pe date `neutral` (79%)**
- ligi domestice: 304 meciuri, dintre care 22 `neutral` (7%)

### 3.3 Calitatea predicțiilor afectate

Cele 25 de meciuri cu egal „lider" s-au terminat: **6 egaluri din 25 = 24%**, față de 37,0% pretins de constantă.

---

## 4. Impact asupra celorlalte componente

| Componentă | Impact | Verificat |
|---|---|---|
| **Forma / off-def rating** | Complet inert în cupele europene — profilele sunt valori implicite, identice pentru orice pereche de echipe | da, prin cele 25 de cazuri |
| **ELO** | Neatins ca date (`home_elo`/`away_elo` sunt corecte în `match_history`), dar **nefolosit** pe această cale: Level 6 se atinge doar când și multiplicatorii ELO lipsesc | da, prin cod (`oracle_engine.py:1454-1478`) |
| **Value Selector** | Ar fi promovat aceste constante drept „valoare" — un edge relativ mare față de o piață care prețuiește corect | da; de aceea ADR-071 impune poarta de calitate a datelor |
| **ML / Blend** | NEinvestigat aici — `FEATURE_COLUMNS` se alimentează din altă cale (`sync/backfill_features.py`). Nu se presupune nimic. | nu |
| **Shadow evaluation** | Cele 48 de predicții intră în evaluarea Challenger ca predicții obișnuite, deși sunt constante. Efectul asupra Brier/log-loss al campionului nu a fost cuantificat. | nu |

---

## 5. Ce s-a făcut ca protecție imediată (fără a atinge motorul)

ADR-071 impune ca stratul de selecție să **respingă** orice candidat construit pe `data_quality = neutral` — și explicit să **nu-l trateze ca „Longshot Value"**: un fallback nu e „valoare cu risc mai mare", e absența informației. Regula e testată (`tests/test_value_selector.py::test_T14_...`), inclusiv cu constanta reală 34,1 / 37,0 / 28,9 ca fixture.

Aceasta e o **plasă de siguranță în aval**, nu o reparație. Predicțiile constante continuă să fie produse, stocate și servite în restul aplicației.

> **Limita plasei, confirmată 2026-09-08**: acoperă EXCLUSIV manifestarea §1-§2.
> Cazul §2b scrie `data_quality = live` — corect, în litera regulii: datele chiar
> provin din meciuri terminate reale. Poarta nu se declanșează, iar UI-ul afișează
> „✅ Date reale — meciuri terminate". Cele 16 echipe din §2b.4 (Real Madrid,
> Barcelona, Bayern, PSG, Arsenal, Liverpool, Inter, Manchester City, …) pot intra
> azi în Top Value Bets pe profile vechi de 101-223 de zile, fără niciun semnal.
>
> Nu e o breșă în implementarea porții — e o limită a semnalului pe care se
> bazează. `data_quality` răspunde la „avem date reale?", nu la „sunt recente?".
> Orice remediere trebuie să introducă al doilea semnal, nu să-l reinterpreteze
> pe primul (a marca `live` ca `neutral` ar fi o minciună în cealaltă direcție —
> Regula #8).

---

## 6. Recomandare de remediere (task separat, NEÎNCEPUT)

**Nu se repară printr-un hack local.** Ștergerea filtrului `.eq("league", league)` din `get_team_recent_results()` ar schimba forma pentru **toți** consumatorii, inclusiv ligile domestice unde funcționează corect azi — o schimbare de contract, deci ADR propriu (regula #5).

> **[REVIZUIT 2026-09-08, după §2c]** Fraza de mai sus rămâne valabilă, dar
> motivul ei s-a schimbat radical. Documentul original respingea ștergerea
> filtrului pentru că *ar afecta și ligile domestice*. Măsurătoarea din §2c arată
> ceva mai important: **ștergerea filtrului ar fi greșită și pentru cupe** — e
> singurul mecanism prin care motorul ajustează azi la forța adversarului și la
> tăria campionatului intern. Nu e un rău necesar de tolerat, e o funcție de
> păstrat.

Întrebarea reală de arhitectură, de decis explicit, nu implicit:

1. ~~**Ce înseamnă „forma" unei echipe într-o competiție de cupă?**~~ — **ÎNCHISĂ 2026-09-08, cu date (§2c).**

   Variantele listate inițial erau: (a) ultimele 5 din acea cupă — „azi, și e greșit"; (b) ultimele 5 indiferent de competiție; (c) ultimele 5 din liga domestică plus cupele.

   **Varianta (b) e infirmată empiric.** Pe sezonul trecut, dispersia Δppm campionat→UCL e de 2,0 puncte pe meci (−1,77 Villarreal … +0,23 Arsenal), iar PSV — mai bun decât Liverpool în campionat — e substanțial mai slab în Europa. O formă indiferentă la competiție ar fi inversat ordinea acestor echipe pentru un meci de UCL. Varianta (c) moștenește aceeași problemă, diluată.

   **Varianta (a) e conceptul corect** — dar nu în implementarea de azi. Răspunsul complet, în trei părți care trebuie decise împreună:

   | Parte | Ce trebuie | De ce |
   |---|---|---|
   | **Competiție** | se PĂSTREAZĂ filtrul | singurul mecanism de ajustare la forța adversarului (§2c.2-2c.3) |
   | **Sezon** | fereastra trebuie legată de **campania curentă**, nu de 365 de zile | altfel forma lui Real e din aprilie, cu alt lot (§2c.5 pct. 1) |
   | **Rezervă** | echipa fără istoric în competiție primește **formă domestică penalizată, marcată explicit ca substitut** — niciodată constantă | §1-§2: 45 din 72 de echipe azi (§2c.5 pct. 3) |

   **Capcana de evitat, explicit**: un fix care atinge doar partea de sezon (ex. „păstrăm filtrul, reducem fereastra la 120 de zile") **fără** partea de rezervă ar muta toate cele 16 echipe din §2b din „date vechi" în „fără date" — adică din forma nesemnalată în constanta semnalată. Ar înrăutăți predicțiile, chiar dacă ar îmbunătăți onestitatea etichetei. Cele trei părți nu sunt independente.

   - **Fereastra de 365 de zile e un parametru nedecis niciodată explicit** (`lookback_days=365`, valoare implicită în semnătura funcției). Ea e cea care face diferența între §1 și §2b — nu filtrul de competiție singur.
   - **Costul tranziției, cuantificat (§2c.6)**: chiar cu conceptul corect, o competiție nouă începe cu zero meciuri. Etapa 3 din UCL ajunge pe la începutul lui noiembrie, deci ~2 luni de profile pe rezervă; iar la n=3 eșantionul e prea subțire pentru rating-uri stabile (`last_n = 5`). Orice soluție trebuie să spună explicit ce se servește în acele două luni — nu e un caz marginal, e starea normală la începutul fiecărui sezon european.
2. **Cum se tratează diferența de nivel între competiții?** Forma din liga domestică nu e direct comparabilă cu cea din Champions League — aceeași problemă ca lipsa ajustării la forța adversarului, deja documentată în auditul Top Value Bets §3/C3.
3. **Există un `Level` intermediar deja construit care ar trebui să prindă cazul?** `get_team_recent_form_context()` (`oracle_engine.py:1288`) NU e filtrat pe ligă și a fost adăugat pe 2026-08-10 exact pentru „cupele europene fără clasament". În cele 25 de cazuri nu a produs nimic — de investigat separat de ce.

4. **[NOU 2026-09-08] Cum se semnalează „date reale, dar vechi"?** Azi nu există
   niciun câmp pentru asta. `data_quality` distinge `live` / `partial` / `elo` /
   `neutral` — toate despre PROVENIENȚA datelor, niciuna despre vârsta lor. Fără
   un al doilea semnal, nici poarta ADR-071, nici UI-ul, nici evaluarea shadow nu
   pot face diferența între un profil din meciul de acum 3 zile și unul din
   sferturile de acum 7 luni. Decizia (câmp nou? prag? doar afișare?) e separată
   de decizia despre filtrul de competiție și **poate fi luată independent** —
   e singura parte care aduce valoare chiar dacă restul rămâne neschimbat.

Punctul 3 e cel mai promițător ca punct de plecare: există deja un nivel proiectat pentru acest scenariu, care nu se declanșează. Cauza acelei tăceri e necunoscută azi și **nu se presupune**. — **Precizare 2026-09-08**: valabil pentru §1-§2. Pentru §2b, FS2 nici nu e consultat (Level DB reușește înaintea lui), deci acolo întrebarea e alta: nu „de ce tace?", ci „ar trebui Level DB să câștige, când tot ce are e vechi de 5 luni?"

---

## 7. Ce NU s-a atins

`supabase_client.py` · `oracle_engine.py` · `feature_engine.py` · ELO · ML · `match_history` (nicio predicție rescrisă) · niciun flag de producție. Documentul acesta e strict diagnostic.

**Valabil și pentru extinderile din 2026-09-08**: §2b și §2c sunt rezultatul a
opt interogări `SELECT` pe `Prediction` și al citirii codului. Zero scriere, zero
cod de producție atins, niciun flag schimbat.

---

## 8. Cum a ieșit la iveală §2b — merită reținut ca metodă (2026-09-08)

Nu printr-o alertă, nici printr-un test. Proprietarul produsului s-a uitat la
ecran, a comparat cu Flashscore și a întrebat: *„de ce Real are în aplicație 2
înfrângeri consecutive?"*

Defectul era **vizibil de la prima măsurătoare din 4 septembrie** — §3.1 arăta
„Champions League: 24 de meciuri, 7 valori distincte". Cele 7 valori distincte
erau exact echipele din §2b. Le-am citit atunci ca *semn de sănătate* (predicții
variate = model care funcționează), în contrast cu ligile domestice unde numărul
de valori distincte ≈ numărul de meciuri. Era jumătate de adevăr: predicțiile
CHIAR erau variate — variate pe date vechi de cinci luni.

**Lecția**: un indicator construit ca să detecteze o formă a unui defect (aici:
„câte predicții identice avem?") poate ascunde o altă formă a **aceluiași**
defect, tocmai pentru că a doua formă produce exact semnalul opus. Contrastul pe
care-l foloseam ca dovadă de sănătate era el însuși simptomul.
