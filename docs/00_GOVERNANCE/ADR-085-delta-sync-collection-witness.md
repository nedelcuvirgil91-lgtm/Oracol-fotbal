# ADR-085 — Delta Sync întreabă dacă s-au colectat statisticile, nu dacă există un rezultat

**Status**: **PROPUNERE — cere aprobare explicită a proprietarului produsului**
**Data**: 2026-11-02
**Autor**: sesiune Claude Code, la cererea explicită a proprietarului produsului
(„trebuie reparata si treaba cu recuperarea. Daca trebuie adr, scrie adr. Daca
flashscore este sursa primara dovedita de colectare. Nu cred ca ar trebui sa
mai fie un scriitor. Ca altfel apar goluri de genul asta. Vreau o analiza
profunda pe situatia asta.")
**Legat de**: ADR-044/045 (Flashscore Foundation Data Layer, Single Owner),
ADR-036 (Canonical Feature Ownership), ADR-076 (pana de 39 de zile a
extragerii), ADR-077 (criteriul care citea un câmp-martor cu doi scriitori),
ADR-048 (reprogramări), North Star #8 (nicio stare necunoscută aproximată),
North Star #9 (trasabilitate completă)

---

## 0. Rezumatul executiv

Un meci jucat **după ora 19:00 UTC** are o șansă mare să rămână **permanent fără
statistici și fără xG**, deși Flashscore le publică. Nu e latență, nu e o pană
de provider, nu e un selector rupt. Sunt **două porți de „sari peste" care se
închid în aceeași rulare de noapte**, amândouă pe un câmp folosit ca martor
pentru o întrebare la care acel câmp nu răspunde.

Măsurat pe săptămâna 26 oct – 1 nov 2026: **23 de meciuri din 166 (13,9%)**, în
5 ligi, printre ele AC Milan – Inter, Juventus – Napoli, PSG – Lyon, Athletic –
Real Sociedad, Aston Villa – Fulham.

**Diagnosticul proprietarului produsului despre mecanism e confirmat prin
măsurare**: golul apare exact fiindcă `actual_result` are mai mulți scriitori.
**Dar concluzia propusă — eliminarea celorlalți scriitori — nu e remediul
recomandat de acest ADR**, și §3.1 explică de ce, cu riscul cuantificat.
Remediul propus e să se repare **întrebarea**, nu să se îngusteze sistemul ca o
întrebare greșită să devină adevărată.

---

## 1. Contextul măsurat — lanțul cauzal, verigă cu verigă

Totul în secțiunea asta e măsurat read-only pe producție, 2 noiembrie 2026.

### 1.1 Golul

Acoperire xG pe **săptămâna loviturii de start**, ligi domestice, sezonul curent
(cele 4 competiții excluse de `TEAM_PROFILE_EXCLUDED_LEAGUES`):

| săptămâna | terminate | cu xG | % |
|---|---:|---:|---:|
| 27 iul – 31 aug (5 săptămâni) | 636 | 636 | **100,0** |
| 7 sep | 156 | 150 | 96,2 |
| 14 sep | 175 | 175 | **100,0** |
| 5 oct | 137 | 137 | **100,0** |
| 12 oct | 138 | 138 | **100,0** |
| 19 oct | 145 | 145 | **100,0** |
| **26 oct** | **166** | **143** | **86,1** |

13 din 17 ligi domestice sunt la **100,0%** pe tot sezonul. Recuperarea
ADR-076/D-B a funcționat complet. Golul e **strict în ultima săptămână**.

### 1.2 NU e latență — dovedit prin martor pozitiv

Latența reală pe **aceeași săptămână**, pentru cele 143 care AU statistici:

| săptămâna | lag mediu | lag maxim |
|---|---:|---:|
| 19 oct | 0,90 zile | 1,67 zile |
| **26 oct** | **0,82 zile** | **1,67 zile** |

Banda normală e sub 2 zile. Sevilla – Osasuna, jucat 26 oct, are **zero** rânduri
la 7 zile. Nu se compară cu „nimic": se compară cu 143 de meciuri din aceeași
săptămână, colectate în mai puțin de 2 zile.

### 1.3 Cine a scris rezultatul — separare binară

Flashscore scrie `referee`, `home_ht_goals` și statisticile **în același
payload** (`providers/flashscore/normalizer.py:605-648`, un singur `dict`).
Deci prezența arbitrului e martorul că tabul summary a fost parsat.

| grup | meciuri | arbitru | scor pauză | goluri finale | `stats_source` | `fixture_id` |
|---|---:|---:|---:|---:|---|---|
| cu statistici | 146 | **146** | **146** | 146 | flashscore | flashscore |
| **fără statistici** | 23 | **0** | **0** | **23** | flashscore | flashscore |

Zero arbitru, zero scor la pauză, dar **goluri finale pe toate 23**. Deci
`actual_result` pe cele 23 **nu a fost scris de Flashscore**. Rândul Flashscore e
scheletul de dinainte de meci (are `stadium`, cunoscut în avans).

`flashscore_raw_extraction` confirmă independent: cele 23 au 3-4 rânduri, taburi
`h2h, standings, stats` (+`odds`) — **niciun `summary`, niciun `lineups`** — iar
`captured_at` e **înaintea meciului**: 12 oct pentru un meci din 26 oct, **30
iulie** pentru Aston Villa – Fulham din 31 oct.

> **Corecție consemnată**: prima mea interogare pe `flashscore_raw_extraction`
> căuta `match_ref` după `mid`-ul Flashscore. `match_ref` e cheia canonică
> (echipe + dată), nu `mid`-ul. Acel „0 rânduri" nu dovedea nimic și era pe
> punctul de a-mi susține o cauză greșită. Reparată înainte de a trage
> concluzia. Un „0" nu se raportează fără martor pozitiv.

### 1.4 Ora loviturii de start — cauza proximă

| grup | meciuri | oră medie UTC | ≥19:00 UTC | <19:00 UTC |
|---|---:|---:|---:|---:|
| cu statistici | 146 | 14,74 | 24 (16,4%) | 122 (83,6%) |
| **fără statistici** | 23 | **19,83** | **22 (95,7%)** | **1 (4,3%)** |

**22 din 23 sunt meciuri de la 19:00 UTC în sus.**

> **Confuz verificat și ELIMINAT** (nu presupus curat): MLS joacă aproape mereu
> târziu în UTC, deci partiția ar fi putut fi o proprietate a ligii, nu a orei.
> Tăiat în trei:
>
> | set | seara | gol | ziua | gol |
> |---|---:|---:|---:|---:|
> | toate ligile | 46 | 22 (47,8%) | 120 | 1 (0,8%) |
> | **fără MLS** | 34 | **14 (41,2%)** | 105 | **1 (0,95%)** |
> | **doar MLS** | 12 | **8 (66,7%)** | 15 | **0 (0%)** |
>
> MLS are **15 meciuri de zi** în fereastră și **zero** goluri pe ele. Partiția
> ține și în interiorul MLS, și în afara lui. **E ora, nu liga.**

Asta nu e o coincidență de calendar — e consecința directă a programării:

- `live_sync.yml` (DOAR Flashscore, fără pasul de rezultate) rulează la
  **09:00, 13:00, 17:00 UTC** (`cron: "0 9,13,17 * * *"`).
- Un meci care începe la 19:00–23:00 UTC se termină după **ultima** rulare
  `live_sync` a zilei. Flashscore nu mai are nicio ocazie să-l vadă în ziua lui.
- Următorul lucru care îl atinge e `night_sync`, iar acolo ordinea e fixă
  (`sync/run_night.py:411-412`): **etapa 1-4** e `run_daily`, al cărui **prim
  pas e `results`** (`PIPELINE_STEPS[0]`, `sync/run_daily.py:89`); **etapa 5** e
  Flashscore.

Deci, pentru un meci de seară, **providerii API scriu rezultatul cu patru etape
înaintea momentului în care Flashscore ajunge la el**.

### 1.5 Poarta 1 — Delta Sync

`database/queries.py:3842-3843`:

```python
if row.get("actual_result") is not None:
    return True          # = „deja colectat", sari
```

Întrebarea pe care funcția **trebuie** să o răspundă e *„am colectat deja
statisticile Flashscore pentru acest meci?"*. Întrebarea pe care o **pune** e
*„are acest meci un rezultat?"*. Cele două coincid doar dacă Flashscore e
singurul scriitor al rezultatului. Nu este.

Propriul docstring prezisese forma problemei — *„Flashscore nu s-ar mai fi
întors niciodată să-l completeze"* — dar fixul din 5 august 2026 a tratat **doar**
cazul `actual_result IS NULL`. Cazul *„rezultat prezent, statistici absente"*
nu era pe radar.

### 1.6 Poarta 2 — Single Owner

`database/queries.py:2886`, `.eq("has_stats", True)`, consumată de
`sync/sync_match_statistics.py:128` ca să nu cheme degeaba providerii de
rezervă (SFI/FreeLF), per ADR-045.

Toate cele 23 **AU** rând în `flashscore_data_completeness`, cu
`has_stats = true` și `coverage_percent = 100,00` — scris **înainte ca meciul
să se joace**:

| meci | jucat | rândul `completeness` scris |
|---|---|---|
| Sevilla – Osasuna | 26 oct | 12 oct |
| Juventus – Napoli | 1 nov | 26 oct |
| **Aston Villa – Fulham** | 31 oct | **30 iulie** |

Fiindcă `has_stats` măsoară **pagina descărcată, nu extragerea reușită** — prin
decizie documentată în propriul docstring, și **exact defectul pe care ADR-076
l-a numit drept cauza pentru care pana de 39 de zile a trecut neobservată**.

**Ambele porți se închid în aceeași rulare, la câteva minute una de alta**:
pasul `match_statistics` are `depends_on=("results",)`, deci rulează imediat
după pasul care a închis prima poartă.

### 1.7 Asimetria care face defectul contraintuitiv

Delta Sync are o ramură care întoarce **`False`** când `fixture_id` e de la alt
provider (documentată la liniile 3821-3825). Consecința, măsurată:

- **Alt provider câștigă IDENTITATEA** → `fixture_id` nu e `flashscore_<mid>` →
  Delta Sync **False** → Flashscore re-colectează → statisticile ajung. ✅
  *Dovada: Romania SuperLiga are 13 rânduri cu identitate non-Flashscore și
  totuși **110/110 cu arbitru, 0 fără statistici**.*
- **Flashscore câștigă identitatea** (scheletul de dinainte de meci) **dar alt
  provider scrie rezultatul primul** → Delta Sync **True** → Flashscore nu se
  mai întoarce niciodată. ❌

**Cu cât Flashscore descoperă un meci mai devreme, cu atât e mai probabil să-și
piardă statisticile.** Aston Villa – Fulham, descoperit cu **trei luni** înainte,
e cazul extrem. Defectul pedepsește exact munca făcută din timp.

### 1.8 Nedeterminismul

Dacă ordinea ar fi strict cea din §1.4, ar fi afectate **toate** meciurile de
seară. Sunt 22 din 24 (91,7%). Diferența o face **coada de programare GitHub**,
documentată pe 29 august (întârzieri de 10-12 h, fereastră de golire seara,
rulări abandonate). Când `night_sync` e livrat suficient de târziu, `live_sync`
de la 09:00 ajunge primul și salvează meciul.

**Deci rezultatul colectării depinde azi de adâncimea cozii GitHub.** O cursă cu
câștigător nedeterminist, pe o coloană din care se antrenează modele.

### 1.9 DECLANȘATORUL, datat și atribuit — e o reparație a noastră

> **[ADĂUGAT după prima versiune a acestui ADR, la întrebarea explicită a
> proprietarului produsului: „noi avem vreun număr de colectare mai mic?... Sau
> alt motiv identificat de tine?"]** Prima versiune lăsa deschisă întrebarea *de
> ce exact săptămâna aceea*. Acum e închisă, cu dată.

**Două ipoteze eliminate întâi, prin măsurare:**

- **Plafonul per ligă.** `DEFAULT_LIMIT_PER_LEAGUE_AUTOMATED = 20` în cod, dar
  valoarea **efectivă în producție e 50** (`model_config`, cheia
  `flashscore_limit_per_league_automated`). Maximul real pe ligă în săptămâna
  26 oct: **MLS 27**, Serie A 18. Nicio ligă nu s-a apropiat de 50. **Nu e
  trunchiere.**
- **Ligile noi** (Austria, Elveția, Danemarca, adăugate 17 oct). Plafonul e *per
  ligă*, nu global — deci nu diluează. Toate trei au **zero goluri**.
- **Providerul de rezultate** (football-data.org acoperă 10 competiții).
  Infirmată: Primeira Liga, Eredivisie și Bundesliga sunt acoperite de FD, au
  meciuri de seară și **zero goluri**; Scottish Premiership are 6 meciuri de
  seară, NU e acoperită de FD, și tot **zero goluri**.

**Declanșatorul real, din rândurile de audit `night_sync` (ADR-026, producător
adăugat 21 oct — acest ADR e prima dată când acele rânduri răspund la o
întrebare cauzală):**

| zi | pas `results` | etapa 5 Flashscore | goluri de seară |
|---|---:|---:|---:|
| 21 oct | 3,6 s | 7,9 min | 0 |
| 22 oct | 19,0 s | 15,5 min | 0 |
| 23 oct | 35,0 s | 23,1 min | 0 |
| 24 oct | 14,6 s | 10,7 min | 0 |
| 25 oct | 24,0 s | 22,8 min | 0 |
| 26 oct | 11,9 s | 11,7 min | 2 |
| **27 oct** | **62,0 s** | **5,8 min** | 2 |
| 28 oct | 66,9 s | 6,1 min | 5 |
| 30 oct | 74,8 s | 6,7 min | 2 |
| 31 oct | 62,5 s | 6,7 min | 5 |
| 1 nov | **107,7 s** | 12,0 min | 5 |
| 2 nov | **115,3 s** | 10,3 min | — |

Pasul care **scrie** rezultatele a crescut de 3-10×, iar etapa care colectează
statisticile a scăzut la **jumătate** — simultan, exact la data la care încep
golurile. Semnătură cuantificată pe **ambele** capete ale mecanismului.

**Cauza acelei creșteri: commit-ul `9202d82`, 26 octombrie 10:43** — reparația
parametrului `d` al Soccer Football Info. Propriul lui mesaj datează defectul
reparat: *„ultimul succes 10 oct 08:20:04, primul 400 pe 11 oct 08:37:03, apoi
100% eșec, 15 zile"*. Iar `fetch_results_from_soccerfootballinfo()` e **a treia
sursă din pasul `results`** (`sync_results.py:583`).

**Lanțul, complet:**

1. 11 → 26 oct: SFI eșua 100% la rezultate. `results` scria puține rânduri
   (4-35 s). Flashscore ajungea primul. **Zero goluri.**
2. 26 oct 10:43: am reparat `d`. SFI redevine funcțional.
3. De pe 26-27 oct: `results` urcă la 62-115 s — scrie mult mai multe
   `actual_result`.
4. Acele scrieri închid Delta Sync cu ~17 minute înaintea etapei 5, în
   **aceeași** rulare.
5. Etapa 5 scade la 6-7 min și raportează **`ok: true`**.
6. 23 de meciuri de seară rămân permanent fără statistici.

**Golul e efectul secundar al unei reparații corecte.** Defectul din Delta Sync
era latent **exact fiindcă un scriitor concurent era stricat**.

**Simetria merită consemnată**: mesajul lui `9202d82` conține propoziția
*„Defectul s-a activat FĂRĂ niciun commit"* — un defect trezit de o schimbare a
**datelor**. Aici e oglinda: un defect trezit de un **commit**, și anume de o
reparație. Clasa comună: **un defect latent se trezește când se schimbă ceva ce
nu-l atinge.**

**Consecința care schimbă prioritatea etapei 4 (§7)**: orice reparație viitoare
la `results`, `odds_recent_results` sau SFI va retrezi același defect, în același
mod tăcut. Fără un indicator de restanță, o reparație corectă va rupe din nou
colectarea, iar etapa 5 va raporta verde în 6 minute.

---

## 2. Clasa de defect — a treia instanță, numită deja în proiect

`CLAUDE.md` conține, din 27 octombrie, exact această frază:

> **Gol mai larg, lăsat scris explicit**: nimic nu detectează azi când un ADR nou
> adaugă **al doilea scriitor** pe un câmp folosit de altul ca martor.

Instanțele, în ordine:

| # | câmp-martor | întrebarea reală | al doilea scriitor | consecința |
|---|---|---|---|---|
| 1 | `referee IS NULL` | „lipsesc datele bogate?" | Flashscore (ADR-044/045) | criteriul întorcea 0 pe orice fereastră; **ADR-077** |
| 2 | `has_stats` | „s-a extras cu succes?" | — (proxy greșit de la naștere) | pana de 39 de zile, tăcută; **ADR-076** |
| 3 | **`actual_result IS NOT NULL`** | **„a colectat Flashscore?"** | **football-data.org · Odds API scores · SFI** | **acest ADR** |

Remediul ADR-077 e **tiparul de copiat**: criteriul a fost mutat pe
**coloana-țintă** (`home_shots IS NULL`), *„care nu poate minți despre propria
absență"*. Nu s-a căutat un martor mai bun — s-a eliminat martorul.

**O a patra instanță, găsită cu aceeași ocazie și nereparată de niciuna din
opțiunile de mai jos:** `stats_source` e scris necondiționat ca `"flashscore"`
de normalizer (`normalizer.py:620`), în același payload cu rezultatul. Măsurat:
**1653 din 1654** de meciuri domestice terminate au `stats_source = 'flashscore'`
— **inclusiv toate cele 29 care n-au nicio statistică**. Un audit „de la cine
avem statisticile?" primește azi „flashscore" pentru 29 de rânduri care n-au
statistici. Vezi §4.3.

---

## 3. Opțiunile analizate

### 3.1 Opțiunea A — Flashscore devine singurul scriitor al rezultatului

**Propusă explicit de proprietarul produsului.** Analizată serios, nu respinsă
din reflex.

**Ce ar rezolva**: proxy-ul lui Delta Sync ar redeveni **adevărat**. Dacă doar
Flashscore scrie rezultatul, atunci `actual_result IS NOT NULL` chiar implică
„Flashscore a colectat acest meci". Golul dispare la rădăcină, fără nicio
condiție nouă.

**Acoperirea reală, măsurată** (toate meciurile terminate din sezon, inclusiv
cupele):

| | meciuri |
|---|---:|
| Total terminate de la 1 iulie | **2057** |
| cu identitate `flashscore_` | **2037 (99,03%)** |
| cu altă identitate | 20 (0,97%) — 13 Romania SuperLiga, 2 World Cup 2026, 5 izolate |

`FLASHSCORE_TRACKED_COMPETITIONS` are **20** de competiții; singura ligă cu
meciuri terminate în afara listei e **World Cup 2026** (2 meciuri, competiție
încheiată, 0% xG, deja exclusă din Team Profile).

**Deci costul de acoperire al opțiunii A e aproape zero azi.** Argumentul contra
nu e acoperirea.

**Argumentul contra, și e decisiv — asimetria razei de explozie:**

- Dacă se repară întrebarea (B) și Flashscore se rupe mai târziu: pierdem
  statistici și xG, păstrăm rezultatele. Degradare parțială, recuperabilă prin
  mecanismul care a rulat chiar azi.
- Dacă Flashscore devine scriitor unic (A) și se rupe: **pierdem rezultatele.**
  Iar pe `actual_result` se sprijină lanțul ELO, setul de antrenare, evaluarea
  shadow, poarta de promovare, Champion Guardian și reperul extern. Nu e o
  coloană, e **fundația**.

**Riscul nu e teoretic, și proiectul are dovada**: ADR-076 documentează o pană de
**39 de zile** a extragerii Flashscore, cauzată de o redenumire de clase CSS la
provider, în două etape. În acea pană tabul summary a continuat să funcționeze,
deci rezultatele n-ar fi fost afectate — dar o redenumire în summary ar fi avut
exact efectul contrar. Mai mult: blocajele anti-bot sunt reale în proiect
(SofaScore respins prin Akamai, Transfermarkt prin AWS WAF), iar Flashscore e
Playwright, nu API — cea mai fragilă clasă de colectare pe care o avem.

**Și regula proprie a proiectului taie în ambele sensuri.** §chei API spune:
*„Nu se presupune niciodată că o cheie/provider nou e «mai bun» doar pentru că e
nou. Sistemul funcțional existent rămâne activ până când cel nou dovedește, prin
teste și audit, că îl poate înlocui fără regresii."* Inversul e la fel de
valabil: **eliminarea unui fallback funcțional cere dovada că nu mai e necesar**,
nu doar constatarea că astăzi nu e folosit. Cele 13 rânduri Romania SuperLiga
arată că fallback-ul **chiar prinde** cazuri. Iar `sync_results.py` documentează
el însuși că fereastra lui de o zi a fost lărgită tocmai după ce **pierduse
definitiv 16 meciuri World Cup**.

#### 3.1bis Temerea de calitate, verificată pe toate ligile — și reîncadrată

> **[ADĂUGAT la întrebarea explicită a proprietarului produsului: „pe mine mă
> sperie acest provider, că nu are statistici complete ca Flashscore... verifică
> dacă pentru toate ligile noastre primul scriitor este Flashscore și nu alt
> provider care are date parțiale."]**

**Măsurat, sezonul curent, toate cele 21 de ligi cu meciuri terminate:**

| | meciuri |
|---|---:|
| identitate `flashscore_` | **2037 / 2057 (99,03%)** |
| identitate `fd_` (football-data.org) | **0 — pe FIECARE ligă** |
| `stats_source = 'flashscore'` | **2058** |
| `stats_source = 'freelivefootball'` | **0** |
| `stats_source = 'soccerfootballinfo'` | **1** |

**football-data.org nu poate scrie statistici proaste, fiindcă nu are ce.**
Payload-ul lui complet (`sync/sources/football_data.py:232-244`) e: `fixture_id`,
nume, ligă, dată, `actual_home_goals/away_goals/result`, `used_for_training`,
`season`. `home_xg_pred`/`away_xg_pred` sunt **hardcodate `None`** (liniile
211-212). Zero coloane de statistici.

**Subtilitatea care face rezultatul mai tare, nu mai slab**: `fixture_id` e
`COALESCE`-only (primul scriitor câștigă, ADR-036). Deci „0 identități `fd_`" nu
înseamnă că football-data n-a scris niciodată — înseamnă că **Flashscore a creat
rândul primul**, fiindcă descoperă fixture-urile cu 7 zile înainte. Identitatea
`fd_` e aruncată; football-data scrie doar rezultatul într-un rând care e deja al
Flashscore-ului.

**Cele 20 de excepții de identitate, toate numărate**: 13 Romania SuperLiga
(`tsdb`), 5 izolate (`odds`/`tsdb`: Super Lig, Eredivisie, Europa League, MLS,
Bundesliga), 2 World Cup 2026 (`odds`/`espn`). **18 din 20 au statistici COMPLETE
de la Flashscore** — prin chiar asimetria din §1.7: când alt provider câștigă
identitatea, Delta Sync întoarce `False` și Flashscore intră. Cele 2 World Cup
sunt în afara celor 20 de competiții urmărite.

**Unde temerea E justificată: FreeLF.** `match_statistics_adapter.py:85-93`
scrie **6 câmpuri** (posesie ×2, xG actual ×2, șuturi la poartă ×2) din cele 20+
ale Flashscore — genuin parțial. Dar: **zero rânduri în tot sezonul** (cota
epuizată din august, 122 apeluri / 0 reușite, documentat), iar `COALESCE`-only
înseamnă că Flashscore poate umple restul **după** el. Nu suprascrie nimic.

**SFI scrie un set bogat**, nu parțial, și cel singur rând al lui e **100%
complet** pe 13 câmpuri verificate (șuturi, șuturi la poartă, posesie, xG,
cornere, faulturi, cartonașe, ofsaiduri, intervenții portar, arbitru, stadion,
scor la pauză, aliniament) — față de o medie de **94,1%** pe rândurile
Flashscore, unde diferența vine din meciurile de cupă fără xG, nu din lipsuri.

**REÎNCADRAREA, care e punctul**: calitatea NU e amenințată de un scriitor
parțial care suprascrie date bune — `COALESCE` o face imposibil. E amenințată de
un scriitor care **blochează** sursa bogată. Cele 23 de meciuri din §1.1 nu
aveau date *parțiale*; nu aveau **nicio** dată. football-data.org nu a corupt
nimic — scriind rezultatul, a închis poarta prin care veneau cele 20 de coloane.

**Caveat onest**: `stats_source` reține doar **primul** scriitor al acelui câmp,
deci în principiu un rând ar putea avea proveniență mixtă invizibilă acolo.
Practic irelevant azi (totul e ~100% complet și Flashscore scrie toate cele 20),
dar e exact ce face §4.3 necesar.

**Argumentul decisiv, adăugat după §1.9: eliminarea scriitorilor ar însemna să
ANULĂM o reparație făcută pe 26 octombrie.** Scriitorul care a declanșat golul e
Soccer Football Info, pe care l-am reparat acum șapte zile după 15 zile de eșec
total. El e sursa de rezultate pentru ligile pe care football-data.org nu le
acoperă — inclusiv cele 13 rânduri Romania SuperLiga din §1.7. A-l scoate din
joc ar reintroduce exact golul pe care reparația l-a închis.

**Verdict**: A rezolvă golul **îngustând sistemul ca o întrebare greșită să
devină adevărată**, plătește cu un punct unic de eșec pe coloana cea mai
fundamentală, și ar reveni asupra unei reparații corecte. **NU se recomandă.**
Rămâne o opțiune deschisă, consemnată aici cu cifrele ei, dacă proprietarul
produsului decide altfel după ce citește §3.2.

### 3.2 Opțiunea B — se repară întrebarea (RECOMANDATĂ)

Delta Sync încetează să întrebe „are rezultat?" și întreabă ce are nevoie să
știe: **„s-au scris statisticile Flashscore pentru acest meci?"** — citind
**coloana-țintă**, exact tiparul ADR-077:

```
colectat  ⟺  home_shots IS NOT NULL
```

`home_shots` nu poate minți despre propria absență, și are **un singur scriitor
de facto** pentru meciurile Flashscore (verificat: separarea binară din §1.3 —
cele 146 colectate au toate arbitru + scor la pauză + șuturi; cele 23 n-au
niciunul).

**Pro**: chirurgical, o condiție; niciun provider eliminat; niciun punct unic de
eșec; repară și cazul simetric; e remediul deja dovedit o dată în proiect.

**Contra, de tratat explicit**: un meci pe care Flashscore genuin **nu-l poate
servi** (pagină fără tabul stats, meci amânat, competiție necolectată) ar fi
re-vizitat la fiecare rulare, la nesfârșit — risipă, și exact tiparul
`live_sync` din august (jumătate din rulare petrecută pe muncă inutilă).
Mărginirea e obligatorie, nu opțională. Vezi §4.1.

### 3.3 Opțiunea C — se repară și poarta a doua (OBLIGATORIE, independent de A/B)

Oricare dintre A sau B se alege, **poarta 2 rămâne închisă** dacă nu se atinge:
providerii de rezervă sunt în continuare săriți pe baza unui rând
`completeness` scris înainte de meci.

Două variante:
- **(i)** `get_match_ids_with_complete_flashscore_stats()` cere ca rândul să fie
  calculat **după** lovitura de start (`computed_at > kickoff_date`);
- **(ii)** aceeași mutare pe coloana-țintă ca la B: un meci e „deja acoperit"
  dacă `home_shots IS NOT NULL`, nu dacă un rând de completitudine o afirmă.

**Recomandat: (ii)**, pentru coerență — o singură definiție a lui „colectat", în
ambele porți. Varianta (i) păstrează două definiții care pot divergea din nou.

**NU se schimbă semantica lui `has_stats`** în acest ADR. Ea e un contract
public (citit de `app.py:1730` și de `check_data_health`), iar schimbarea ei e o
discuție proprie — golul e deja consemnat de ADR-076. Aici doar **încetăm să o
citim ca martor pentru extragere**.

### 3.4 Opțiunea D — se schimbă ordinea etapelor din `night_sync`

Mutarea etapei 5 (Flashscore) înaintea pasului `results`.

**Respinsă.** Trei motive, în ordinea greutății:
1. **Nu elimină cursa, doar îi schimbă favoritul.** `live_sync` și coada GitHub
   fac ordinea reală nedeterministă (§1.8). Un meci ar continua să piardă când
   coada livrează altfel.
2. `match_statistics` are `depends_on=("results",)` — un lanț declarat explicit
   în `PIPELINE_STEPS`, care ar trebui rupt.
3. **Ar trece testele din noroc.** E exact clasa „un test care trece pentru
   motivul greșit", documentată de trei ori chiar în sesiunea de 1-2 noiembrie.
   O reparație care funcționează pentru că cineva ajunge primul nu e o
   reparație.

---

## 4. Decizia propusă

**B + C(ii) + remedierea onestității lui `stats_source`.** Trei schimbări mici,
niciun provider eliminat, nicio coloană nouă, nicio migrare.

### 4.1 B — Delta Sync citește coloana-țintă, mărginit

`is_flashscore_match_already_collected(mid)` devine:

- `home_shots IS NOT NULL` → **True** (colectat, dovedit pe coloana-țintă)
- `home_shots IS NULL` **și** `kickoff_date` în trecut **și** în fereastra de
  reîncercare → **False** (se re-colectează)
- `home_shots IS NULL` **și** `kickoff_date` în viitor → **True** (nu are rost;
  comportament identic cu azi)
- în afara ferestrei de reîncercare → **True** (se renunță, explicit)

**Fereastra de reîncercare** refolosește parametrul deja existent și dovedit al
recuperării (`recover_days_back`, implicit 60) — **zero mecanism nou**. Un meci
mai vechi decât fereastra nu mai e re-cerut; dacă se dorește, rămâne accesibil
prin recuperarea explicită, care ocolește Delta Sync prin construcție.

**Costul de fetch, măsurat, nu estimat**: restanța reală la pornire era **29 de
meciuri pe 60 de zile**, din care 23 dintr-o săptămână. În regim stabil, B ar
adăuga **~23 de fetch-uri pe săptămână** (~3/zi) — față de cele ~150 pe care o
rulare le face deja. Sub 2% în plus.

### 4.2 C(ii) — aceeași definiție în poarta Single Owner

`get_match_ids_with_complete_flashscore_stats()` întoarce meciurile cu
`home_shots IS NOT NULL`, nu cele cu un rând `has_stats = true`. Numele funcției
rămâne (contract de apelant), semantica devine onestă. Chunk-uirea la 500
(ADR-077 §2.2) se păstrează neatinsă.

### 4.3 `stats_source` nu se mai declară când nu s-a extras nimic

`normalizer.py:620` scrie `"stats_source": "flashscore"` necondiționat.
Devine condiționat de extragerea efectivă a măcar unei valori din
`STAT_LABEL_TO_FIELDS`. Altfel rămâne absent, iar `COALESCE`-ul canonic (ADR-036)
îl lasă nescris — **North Star #8: o stare necunoscută nu se aproximează.**

**Cele 29 de rânduri existente care mint despre proveniență NU se rescriu
retroactiv** în acest ADR. Recuperarea de azi le umple oricum cu date reale de la
Flashscore, deci afirmația devine adevărată prin umplere, nu prin rescriere
(North Star #9 — un rând istoric nu se corectează retroactiv ca să arate bine).

### 4.4 Ce NU se face

- **Nu se elimină niciun scriitor de rezultate.** §3.1.
- **Nu se schimbă semantica lui `has_stats`.** §3.3.
- **Nu se schimbă ordinea etapelor din `night_sync`.** §3.4.
- **Nu se atinge nicio linie din calea de predicție.** Niciuna dintre cele trei
  schimbări nu e în `oracle_engine.py`, `feature_engine.py`, `ml_predictor.py`,
  `recalibration.py`, `app.py`, `oracle_api.py`. Se verifică prin
  `git diff --stat` GOL pe cele șase, ca la fiecare schimbare din proiect.
- **Nu se rescriu retroactiv rândurile existente.**
- **Nu se repară rândurile orfane din `flashscore_data_completeness`** (UNIQUE pe
  `match_ref`, care include data → fiecare reprogramare lasă un orfan).
  Documentat din 30 august; C(ii) îl face **inofensiv** fără să-l atingă,
  fiindcă poarta nu mai citește acel rând. Rămâne gol deschis, acum fără pagubă
  demonstrabilă — iar afirmația „fără pagubă azi" se va scrie de aici încolo
  **numai cu măsurătoarea alături**, fiindcă exact ea s-a dovedit falsă.

---

## 5. Consecințe

### 5.1 Pozitive

1. Golul dispare la cauză, nu la simptom: un meci rămâne în vizor până când
   **coloana care contează** e scrisă.
2. Rezultatul colectării nu mai depinde de adâncimea cozii GitHub (§1.8).
3. Providerii de rezervă redevin accesibili pentru meciurile pe care Flashscore
   genuin nu le servește — azi sunt blocați de un rând de dinainte de meci.
4. O singură definiție a lui „colectat", în ambele porți.
5. Nicio dependență nouă, niciun punct unic de eșec nou.

### 5.2 Negative, asumate

1. **~23 de fetch-uri în plus pe săptămână** (§4.1). Mărginite de fereastră.
2. Un meci pe care Flashscore nu-l poate servi va fi reîncercat până la capătul
   ferestrei. Acceptat: alternativa e să-l abandonăm din prima, adică defectul
   de azi.
3. Fereastra de 60 de zile e un **prag**, deci va fi greșită pentru un caz
   extrem (un meci amânat cu peste 60 de zile). Acela rămâne accesibil prin
   recuperarea manuală — nu se inventează o a doua regulă pentru el.

### 5.3 Ce rămâne nerezolvat, scris explicit

- Rândurile orfane din `flashscore_data_completeness` (§4.4).
- Semantica lui `has_stats` (ADR-076).
- **Nimic nu detectează încă apariția unui al doilea scriitor pe un câmp folosit
  ca martor.** Acest ADR e a treia instanță a clasei; garda generală lipsește în
  continuare. Garda ADR-036 acoperă doar `FEATURE_COLUMNS`.

---

## 6. Verificarea cerută

### 6.1 Înainte de implementare

1. `pytest tests/` verde pe `main` — baseline înregistrat.
2. Restanța măsurată pe 60 de zile (`home_shots IS NULL`), pe ligă.
3. Confirmat că `home_shots` are un singur scriitor pentru meciurile Flashscore
   (ADR-036 — `run_backfill` nu îl atinge).

### 6.2 După implementare, înainte de merge

1. `pytest tests/` verde, aritmetica numărului de teste închisă **exact**.
2. `git diff --stat` **GOL** pe cele șase fișiere protejate.
3. Mutații obligatorii, fiecare trebuie prinsă:
   - M1 — defectul original reintrodus (`actual_result IS NOT NULL → True`);
   - M2 — mărginirea ferestrei ștearsă (reîncercare infinită);
   - M3 — garda „meci în viitor" ștearsă;
   - M4 — poarta Single Owner lăsată pe `has_stats`;
   - M5 — `stats_source` scris necondiționat din nou;
   - M6 — condiția inversată (`home_shots IS NULL → True`);
   - M7 — chunk-uirea la 500 ștearsă din poarta Single Owner.
4. **Contrapondere obligatorie**: un test care cade dacă garda nu mai vede
   nimic (un „0" fără martor pozitiv — lecția din §1.3).

### 6.3 După merge, în producție

1. Prima rulare de noapte: restanța scade, iar **meciurile de seară** din ziua
   precedentă primesc statistici. Semnalul corect e `home_shots` scris, nu
   numărul total de rânduri (care poate rămâne egal — `upsert` pe aceeași
   fereastră; capcana de măsurare din ADR-073).
2. După o săptămână: acoperirea săptămânii curente revine la ~100%, iar
   partiția pe oră din §1.4 **dispare** — asta e testul decisiv, fiindcă e
   singura măsurătoare care a izolat cauza.
3. Durata rulării: creșterea măsurată trebuie să fie sub ~2%. Peste, se
   reexaminează fereastra.

---

## 7. Plan de implementare, în etape

| etapă | ce | cere aprobare separată |
|---|---|---|
| **0** | Recuperarea restanței de azi (29 de meciuri) prin `--recover-missing-stats` | ✅ **aprobată și EXECUTATĂ 2 nov — vezi §7.1** |
| 1 | B — Delta Sync pe coloana-țintă, mărginit (§4.1) + teste + mutații | da (merge pe `main`) |
| 2 | C(ii) — poarta Single Owner pe aceeași definiție (§4.2) | da |
| 3 | `stats_source` condiționat (§4.3) | da |
| **4** | **Clasă nouă în `check_data_health`: meciuri terminate, competiție urmărită, fără statistici. Prag ZERO absolut, nu procent.** §1.9 o mută din „util" în **obligatoriu** | da |
| 5 | Verificarea din §6.3, după prima rulare de noapte | — |

### 7.1 Etapa 0 — executată și verificată, 2 noiembrie 2026

Rularea `41505315571` (FDL, `--recover-missing-stats`, `max_recover=50`,
`recover_days_back=60`, `limit_per_league=40`), 18:56:47 → 19:21:42 UTC,
**24m55s, `success`**.

`limit_per_league` a fost pus la 40 deliberat: el mărginește **Discovery**, iar
`_plan_recuperare()` restrânge apoi lista strict la țintele din restanță, deci un
hub mai adânc costă doar paginile de hub, nu fetch-uri în plus.

| indicator | înainte | după |
|---|---:|---:|
| restanță 60 zile (`home_shots IS NULL`) | 29 | **6** |
| **din săptămâna 26 oct** | **23** | **0** ✅ |
| `match_statistics_extended` | 58.423 | **59.341** (+918) |
| `player_match_stats` | 86.369 | **87.518** (+1.149) |
| sezon domestic cu xG | 1625 / 1654 (98,25%) | **1652 / 1658 (99,64%)** |

**Verificarea de calitate, nu doar de număr**: pe cele **27** de meciuri
recuperate, 8 competiții — `referee`, `home_ht_goals`, `home_shots`,
`home_xg_actual` și `home_possession` sunt prezente pe **27 din 27**. Deci tabul
summary a fost parsat complet, nu parțial. Semnalul corect era ăsta, nu numărul
de rânduri (care poate crește și dintr-un `upsert` pe aceeași fereastră).

**Cele 6 rămase sunt o CLASĂ DIFERITĂ, iar martorul le separă curat**: toate 6
(MLS, 9-13 septembrie) au **`referee IS NOT NULL`** — summary-ul a fost parsat,
dar tabul de statistici n-a dat nimic. Reziduul **penei ADR-076** (8 sep – 18
oct), nu al defectului din acest ADR, care are semnătura inversă
(`referee IS NULL`). Nu au fost recuperate fiindcă la 50+ zile nu mai apar pe
hub-ul `/results/` — explicație, nu defect. Toate 6 sunt la 21:00-23:30 UTC, dar
pentru MLS ora nu discriminează (vezi contraponderea din §1.4) — ce le
clasifică e arbitrul, nu ora.

**Registrul NU s-a împrospătat, și e corect**: `experiment_registry` pentru
`flashscore_team_dna` rămâne la `n = 1506`, evaluat 15:16:50, adică **înaintea**
recuperării. Evaluarea rulează în `night_sync` (`evaluate_all_active_experiments`,
`run_daily.py:537`), nu în FDL. Cifrele Team Profile se vor schimba la prima
rulare de noapte — **de aceea orice citire a lor azi e dinainte de recuperare.**

Etapele 1-3 pot merge într-un singur commit: ating același contract („ce
înseamnă «colectat»"), iar separarea lor ar lăsa producția într-o stare
intermediară în care o poartă s-a deschis și cealaltă nu — adică exact golul de
azi, pe jumătate.

**Nimic din §7 nu e implementat la data acestui document.** Toate etapele sunt
**plan**, nu aprobări.

---

## 8. Nota de metodă

Defectul n-a fost găsit de niciun test, de nicio alertă și de nicio privire pe
ecran. A fost găsit fiindcă proprietarul produsului a **contestat o afirmație a
mea** — „vrei să spui că nu avem acoperire 100% pe xG?". Afirmația mea era
corectă (vorbeam despre măsurătoarea din 13 octombrie, nu despre acoperirea de
azi), dar formularea invita exact citirea pe care a primit-o, iar verificarea
cerută de obiecție a scos la iveală un gol activ pe care nu-l căutam.

A cincea oară în proiect când observația proprietarului produsului bate
diagnosticul meu, după filtrul de formă (8 sep), acoperirea SuperLigii (29 aug),
promovarea din Decision Feed (14 oct) și plafonul artefact al penalizării de
accidentări (14 oct).

Regula operațională rămâne cea scrisă deja în `CLAUDE.md`, confirmată din nou:
**când o afirmație se sprijină pe diagnosticul meu, obiecția venită din
cunoașterea sistemului e dovadă de testat, nu zgomot de combătut.**
