# ADR-075 — Dubluri de identitate între provideri, cu date divergente

**Status**: Proposed (2026-10-16) — **NEaprobat, nimic implementat**
**Autor**: Claude (arhitect principal, sesiune delegată explicit)
**Declanșator**: proprietarul produsului a trimis o captură cu workflow-ul `check_data_health` roșu și a întrebat „cum scăpăm de eroarea asta?". Investigația a arătat că monitorul nu era roșu degeaba — găsise o clasă de defect necunoscută.
**Atinge contractul**: depinde de opțiunea aleasă — vezi §5. Opțiunea recomandată (A) **nu atinge niciun contract**: nu adaugă niciun scriitor, nu schimbă nicio responsabilitate, e un detector read-only.
**Nu atinge**: `_upsert_match_canonical_locked` (migrările 048/049 rămân neschimbate — §3 arată că ele deja se comportă corect), calea de predicție, ADR-070 ca decizie (rămâne valid; se descrie o margine pe care nu a prevăzut-o).

---

## 1. Context

ADR-070 a rezolvat cazul „Flashscore publică o etapă cu ~3 săptămâni înainte,
cu o oră placeholder, iar orele reale apar cu câteva zile înainte de fluier".
Mecanismul: `correct_flashscore_kickoff_if_mismatched()` compară data scrapată
de pe `/fixtures/` cu data stocată **pentru același `fixture_id`**, iar la
diferență rescrie prin RPC-ul canonic.

Cazul pe care ADR-070 **nu l-a prevăzut**: între momentul descoperirii timpurii
de către Flashscore și momentul confirmării orei reale, **alt provider** poate
crea un rând propriu pentru același meci, cu data corectă. Atunci există două
rânduri live pentru un singur meci real, cu `fixture_id` diferit și dată
diferită, iar rândul placeholder al Flashscore **nu mai e vizitat de nimeni
niciodată**:

- `resolve_fixture_id()` (`providers/flashscore/pre_match_odds.py`) potrivește
  întâi prin `match_key(gazdă, oaspete, dată)` cu meciurile deja descoperite în
  aceeași rulare. Odată ce data reală e cunoscută, potrivirea cade pe rândul
  **celuilalt** provider, deci întoarce `fixture_id`-ul ACELUIA.
- `correct_flashscore_kickoff_if_mismatched()` compară apoi data stocată a
  acelui rând cu data scrapată — sunt egale — și se întoarce fără să facă
  nimic.
- Rândul placeholder rămâne cu data lui veche. Descoperirea privește doar
  înainte (7 zile), deci un rând a cărui dată a trecut nu e redescoperit.

Nici detectorul de duplicate din `check_data_health` nu îl prinde: cheia lui e
`(gazdă, oaspete, ZI)`, iar **ziua diferă**. Duplicatul e invizibil prin
construcție pentru singurul instrument care ar fi trebuit să-l vadă.

## 2. Cazul concret, măsurat (2026-10-16)

Trei meciuri, fiecare cu două rânduri live:

| Meci | Rând Flashscore (7 sep) | Rând `odds` (2 oct) |
|---|---|---|
| Borussia Dortmund – SV Werder Bremen | `flashscore_plkwWY3D`, **10 oct**, fără rezultat | `odds_3fb6…`, **9 oct**, D 2-2 |
| PSV – SC Heerenveen | `flashscore_ABvXMeTa`, **10 oct**, fără rezultat | `odds_217a…`, **9 oct**, fără rezultat |
| Galatasaray – Kasimpasa | `flashscore_YiWPvQZg`, **11 oct**, fără rezultat | `odds_eff2…`, **9 oct**, fără rezultat |

### Care dată e corectă — trei dovezi independente, nu o deducție

1. **Flashscore însuși**, în tab-ul H2H (`flashscore_match_context`), dă toate
   trei meciurile pe **9 octombrie**: 2-2, 2-0, 3-1.
2. **`home_xg_actual` e scris exclusiv de Flashscore.** Rândul `odds` al lui
   Dortmund îl are populat (2.42) — deci colectarea Flashscore a scris pe
   rândul de 9 octombrie, nu pe al ei de 10 octombrie.
3. **Aritmetica etapelor închide independent pe toate trei ligile** (9
   meciuri/etapă): Bundesliga 1+6+2, Eredivisie 1+4+4, Super Lig 1+4+3+1. În
   fiecare caz, ziua de 9 octombrie conține exact un meci, iar sursa lui e
   exclusiv `odds`. 9 octombrie 2026 e **vineri** — slotul normal de meci de
   vineri seara.

**Deci rândul placeholder e cel al Flashscore, iar cel creat de alt provider
are data corectă.** Asta răstoarnă presupunerea obișnuită a proiectului
(„Flashscore are dreptate"), și de-aceea verdictul e sprijinit pe trei dovezi,
nu pe una.

### Amploarea, mărginită prin măsurare

Căutarea tuturor perechilor de rânduri live cu aceleași echipe și date diferite
la cel mult 10 zile, pe tot sezonul curent: **exact 3 perechi**, toate create
de aceeași rulare `odds` din 2 octombrie, 09:05.

**Limită onestă a acestei măsurători**: interogarea cere egalitate EXACTĂ a
numelor de echipă, deci ar rata o pereche pe care cei doi provideri o scriu cu
grafii diferite (clasa `Mjällby`/`Mjallby`, documentată în CLAUDE.md). Pentru
constatările zilei de azi acoperirea e completă — cele 5 rânduri raportate au
fost verificate individual. Pentru sezon, **3 e o limită inferioară**, nu un
total.

## 3. Ce NU e stricat — RPC-ul se comportă deja corect

Formularea inițială a diagnosticului („trebuie un mecanism nou de
supersedare") era greșită. `_upsert_match_canonical_locked` (migrarea 049) are
deja garda exactă pentru această situație:

```sql
-- Garda: data noua nu are voie sa fie deja ocupata de ALT rand live —
-- altfel UPDATE-ul ar viola idx_match_history_natural_key_canonical.
-- Raportat ca hard_conflict (rand nescris, vizibil), nu ca exceptie.
RETURN jsonb_build_object('action','hard_conflict','id',v_resched_id,
                          'reason','reschedule_target_occupied');
```

Dacă s-ar încerca mutarea rândului placeholder pe data reală, RPC-ul ar
întoarce `reschedule_target_occupied`, **fără să scrie nimic** — adică exact
afirmația „aceste două rânduri sunt același meci, decide un om".

**Golul nu e în RPC. Golul e că declanșatorul nu pornește niciodată.** Asta
face problema mult mai mică decât părea: nu lipsește un mecanism de rezolvare,
lipsește unul de *observare*.

## 4. Consecințele reale, măsurate — și una care NU există

**Ce costă:**

- Monitorul `check_data_health` rămâne roșu la nesfârșit pe rânduri care nu
  se vor rezolva niciodată singure — exact tiparul pe care baseline-ul a fost
  construit să-l evite („un monitor permanent roșu nu mai e citit de nimeni").
- Două dintre cele trei meciuri **n-au primit rezultat pe niciun rând**, timp
  de 7 zile, deși rezultatul exista deja în propria noastră bază
  (`flashscore_match_context`). Pentru comparație, cele 12 meciuri „recente"
  din același raport au primit rezultate singure în câteva ore — deci acestea
  două erau blocate, nu în întârziere.
- Fiecare meci real ocupă două identități, deci două seturi de rânduri
  derivate: `shadow_predictions` (5+5), `value_selector_shadow` (39+39),
  `engine_comparison_snapshots` (1+1).

**Ce NU costă — corectură la o afirmație proprie, scrisă în aceeași zi:**

Raportasem că „experimentul F2 a numărat aceste 3 meciuri dublu". **Greșit.**
`value_selector_evaluation.rezultat_selectiei()` întoarce `None` când
`actual_result` e `NULL`, iar rândurile placeholder n-au avut niciodată
rezultat. Verificat în date: cele 13 selecții de pe fiecare `fixture_id`
fantomă au `actual_result = NULL`, deci **n-au intrat niciodată în statisticile
de selecții decise** — cele pe care se sprijină pragul F3 și ROI-ul. Au umflat
doar numărul de meciuri *văzute*.

Lecția de metodă: numărul de *rânduri* duplicate nu implică numărare dublă în
*statistică*. Dedup-ul pe `(policy_id, fixture_id)` plus poarta „fără rezultat
= nedecis" filtrau deja fantomele. Afirmația de severitate a fost făcută din
numărarea rândurilor, înainte de a citi cum se consumă.

## 5. Opțiuni

### Opțiunea A — detector read-only (RECOMANDATĂ)

Se adaugă în `check_data_health` o clasă nouă: rânduri live care împart
`(gazdă, oaspete)` cu date diferite la cel mult N zile. Raportează, nu scrie.

- **Contract atins**: niciunul. Nicio scriere nouă, niciun scriitor nou, deci
  ADR-036 neatins. Un monitor read-only e detaliu de implementare per Change
  Policy — acest ADR există pentru *clasa de defect*, nu pentru detector.
- **Ce rezolvă**: face duplicatul vizibil în ziua în care apare, nu după o
  investigație manuală declanșată de o captură de ecran.
- **Ce NU rezolvă**: nu repară nimic. Fiecare caz cere tot decizie umană.
- **Risc**: fals pozitiv pe un meci genuin reprogramat cu 1-2 zile, care
  arată identic. De tratat prin baseline, ca amânările — mecanismul există
  deja și e dovedit.

### Opțiunea B — declanșatorul ADR-070 ajunge la rândul placeholder

`correct_flashscore_kickoff_if_mismatched()` caută și după `(gazdă, oaspete,
ligă)`, nu doar după `fixture_id`, și încearcă corecția pe rândul placeholder.
RPC-ul întoarce atunci `reschedule_target_occupied`, fără să scrie.

- **Contract atins**: `database/queries.py` capătă o cale de căutare nouă, dar
  **niciun scriitor nou** — rezultatul e un `hard_conflict`, nu o scriere.
- **Ce rezolvă**: semnalul apare în log-ul rulării de noapte, mai devreme
  decât la A, și pe calea care deja se ocupă de date de start.
- **Ce NU rezolvă**: tot nu repară. Produce un semnal, nu o soluție — deci e
  un supliment la A, nu o alternativă.
- **De ce nu e recomandată singură**: un `hard_conflict` în log-ul unei rulări
  de 90 de minute e mai greu de observat decât o clasă într-un monitor dedicat.

### Opțiunea C — supersedare automată. RESPINSĂ

Supersedarea automată a rândului „greșit" ar necesita alegerea mecanică a unui
câștigător între două afirmații de dată care se contrazic.

**Migrarea 049 a decis deja exact această întrebare, pentru clasa vecină**
(aceleași echipe, orientare contradictorie):

> Decizie deliberată: NU se alege automat un câștigător între două afirmații
> de identitate contradictorii. Care echipă e gazdă determină ELO, forma, H2H,
> atribuirea xG pe părți și avantajul terenului propriu — e o decizie de
> identitate, verificată de om, nu una mecanică.

Data meciului e în aceeași clasă: determină ce formă se citește, în ce
fereastră cade meciul, ce etapă e. Și decizia de azi a cerut **trei** dovezi
independente (tab-ul H2H Flashscore, coloana `home_xg_actual` cu scriitor
unic, aritmetica etapelor pe trei ligi) — niciuna disponibilă ca regulă
simplă. O euristică „câștigă cine are rezultat" ar fi dat răspunsul corect
pentru Dortmund și **niciun** răspuns pentru celelalte două, unde niciun rând
nu avea rezultat.

## 6. Decizie cerută

**Recomand A**, singură, acum. B doar dacă A arată că rata e suficient de mare
ca să justifice un al doilea semnal. C respinsă, cu precedentul citat.

Dacă răspunsul e „niciuna", golul rămâne documentat aici și reapare la fiecare
etapă descoperită devreme peste care alt provider scrie întâi — adică
previzibil, nu accidental.

## 7. Reparația de date deja făcută — excepție, nu precedent

Pe 16 octombrie, cu SQL arătat integral și confirmat explicit de proprietarul
produsului, s-a făcut o reparație unică: cele 3 rânduri placeholder supersedate
de rândul canonic, plus cele 2 rezultate lipsă scrise pe rândurile canonice din
`flashscore_match_context`. Garda triplă pe fiecare instrucțiune (`id` +
`fixture_id` + `actual_result IS NULL`), toate cinci într-o singură
instrucțiune cu CTE-uri (atomic), `RETURNING` pe fiecare — exact 5 rânduri
atinse, dovedit.

**Două lucruri de consemnat explicit:**

1. Partea de rezultate scrie `actual_*`, coloane al căror owner unic e
   `sync_results` (ADR-036). Garda AST impune proprietatea la nivel de **cod**,
   deci nu a fost încălcată; dar o scriere manuală pe aceste coloane e o
   **excepție la regula de proprietate** și rămâne consemnată ca atare.
   Justificare: meciurile stăteau de 7 zile, fereastra pasului `results` e
   exact 7 zile, deci expira.
2. Supersedarea de azi **nu e un precedent pentru automatizare**. A fost
   posibilă fiindcă un om a văzut cele trei dovezi. Opțiunea C rămâne respinsă
   tocmai pentru că acea judecată nu e mecanizabilă azi.

## 8. Nedeterminat — nu se completează prin deducere

**De ce colectarea Flashscore a ajuns la meciul Dortmund (`home_xg_actual`
prezent) și nu la celelalte două (absent).** Asta explică de ce unul avea
rezultat și două nu, dar mecanismul exact nu a fost stabilit. Ipoteze
plauzibile (fereastra de descoperire, Delta Sync) n-au fost verificate, deci
nu sunt scrise aici ca explicație.

Contează pentru alegerea opțiunii: dacă motivul e o regulă de sărire pe care o
controlăm noi, ar putea exista o reparație mai bună decât oricare dintre A, B,
C — una care duce rezultatul la rândul corect fără să ceară decizie umană. **De
investigat înainte de a implementa, nu după.**

---

### [ÎNCHIS 2026-10-20 — întrebarea avea un răspuns banal, iar investigația a găsit altceva]

**Răspunsul: LATENȚĂ, nu o regulă de sărire.** Niciuna dintre cele două ipoteze
(fereastra de descoperire, Delta Sync) nu era necesară. Remăsurat read-only pe
20 octombrie, toate trei rândurile `odds_` au acum rezultat **și** xG:

| meci | rezultat | xG (gazdă/oaspete) | potrivește dovada #1 (H2H Flashscore)? |
|---|---|---|---|
| Borussia Dortmund – SV Werder Bremen | D 2-2 | 2,42 / 1,10 | ✅ 2-2 |
| PSV – SC Heerenveen | H 2-0 | 2,34 / 1,55 | ✅ 2-0 |
| Galatasaray – Kasimpasa | H 3-1 | 2,52 / 0,49 | ✅ 3-1 |

Exact cele trei scoruri pe care §2 le anticipase. Colectarea Flashscore a ajuns
la toate trei; **Dortmund a fost doar primul.** Deci nu exista nicio „regulă de
sărire pe care o controlăm noi", iar reparația pe care §8 o spera — una care
duce rezultatul la rândul corect fără decizie umană — **nu are obiect**:
rezultatul era deja pe rândul corect, pentru toate trei.

**Consecință pentru alegerea opțiunii**: cazul live s-a stins singur. A, B și C
se decid de-acum pe meritele detectorului, nu pe urgența unui duplicat activ.
Reamintire din `DE_URMARIT` §679, reconfirmată: `check_data_health` prinde deja
clasa, la ~6 zile după meci — deci A rămâne o îmbunătățire de **viteză și
claritate**, nu închiderea unui gol.

### Ce a ieșit la iveală în locul întrebării — un gol de trasabilitate real

Cele trei rânduri placeholder Flashscore sunt acum `superseded_by`
(132416 / 132415 / 132414) — **cu `superseded_reason` ȘI `superseded_at` NULL pe
toate trei.** Combinația e unică în tabelă:

```
superseded_by IS NOT NULL                        →  6742 rânduri
  … din care superseded_reason IS NULL           →     4
  … din care superseded_at IS NULL               →     3
  … din care AMBELE NULL                         →     3   ← exact cele trei
```

**Nimic din sistem nu poate produce asta** — verificat, nu presupus:

- `services/match_identity_reconciliation_service._mark_superseded()` scrie
  **mereu** toate trei coloanele, filtrat idempotent pe `superseded_by is null`.
- RPC-ul canonic `_upsert_match_canonical_locked` **doar citește**
  `superseded_by` (`WHERE superseded_by IS NULL`): nicio atribuire, fără SQL
  dinamic, fără `jsonb_populate_record`, listă de coloane explicită.
  *(Prima citire a fost greșită — `position('superseded_by' in src) > 0`
  prinsese liniile de **citire**. Corectat prin regex pe atribuire.)*
- Singurele funcții din bază care scriu un `superseded_by` sunt
  `promote_challenger` și `rollback_champion` — pe `model_champions`, **altă
  tabelă**.
- Acest ADR e `Proposed`, nimic implementat; niciun commit din 15–20 oct îl
  implementează.

**Deci a fost o scriere din AFARA sistemului, iar singurul câmp care ar fi
putut-o data e exact cel care e NULL.** Cine și când: **necunoscut**, și nu se
deduce (Regula #8).

#### [PRECIZARE 2026-10-20, după prima rulare reală a clasei 9 — monitorul numără 4, nu 3]

Tabelul de mai sus e corect, dar prozele din jur spun „cele trei", iar monitorul
raportează **4 rânduri**. Cele două cifre nu se contrazic — numără criterii
diferite — dar lăsate așa, cineva care citește monitorul și apoi ADR-ul caută o
regresie inexistentă. **Aceeași clasă de eroare ca „→ 7" vs. „→ 3" din 14
octombrie: o cifră de verificare care nu se reproduce e mai rea decât niciuna.**

- Clasa 9 filtrează pe **`superseded_reason IS NULL`** — criteriul corect, fiindcă
  un rând scos din setul live fără să spună **de ce** e deja o pierdere de
  trasabilitate, indiferent dacă poartă sau nu un marcaj de timp. Deci **4**.
- „Cele trei" din acest ADR sunt rândurile cu **AMBELE** câmpuri NULL — subsetul
  despre care nu se poate spune nici măcar *când*.

**Al patrulea e IDENTIFICAT și benign**: `id=130978`, `tsdb_2482525`,
Rijeka – Dinamo Zagreb (8 aug), cu `superseded_at = 2026-08-23 19:41:11`. Data îl
leagă fără dubiu de lucrarea documentată în `CLAUDE.md` la unificarea formelor
abreviate — *„Coliziunea unică apărută (Rijeka–Dinamo Zagreb, 8 aug) rezolvată
prin supersedarea rândului TSDB de către cel Flashscore"*.

**Și asta e o pistă reală pentru cele trei, nu o concluzie**: dovedește că
supersedarea manuală prin SQL e o **practică existentă și documentată** în
proiect. Cele trei sunt foarte probabil același mecanism; diferența e că acolo
s-a sărit **și** `superseded_at`, deci nu a mai rămas nimic care să le dateze.
Asimetria merită reținută: pe 23 august s-a scris marcajul dar nu motivul; la
cele trei, niciunul. Cine și când **rămâne necunoscut pentru cele trei** — pista
nu se transformă în atribuire.

**Consecință pentru monitor: niciuna.** Un `exit 1` pentru 4 rânduri netrasabile
e verdictul corect, iar al patrulea nu se „scuză" fiindcă îi știm proveniența —
îi lipsește tot motivul scris. Se închide când primește unul, sau prin `CHECK`-ul
din secțiunea următoare.

### Reparație făcută (nu propusă): clasa 9 din `check_data_health`

`database.queries.get_supersede_without_reason()` + clasa 9 în monitor, **prag
zero absolut**: un rând scos din setul live fără să spună de ce e deja o
pierdere de trasabilitate, nu un indiciu statistic. Detector **read-only**, deci
nu atinge niciun contract — exact argumentul cu care §5 justifica opțiunea A.
Nu repară nimic retroactiv; face **următoarea** astfel de scriere vizibilă în
loc de tăcută (North Star #9). 9 teste, 6 mutații verificate.

**Rămâne de decis, nefăcut deliberat**: un `CHECK` în Postgres care ar face
starea **imposibilă**, nu doar detectabilă
(`CHECK (superseded_by IS NULL OR (superseded_reason IS NOT NULL AND superseded_at IS NOT NULL))`).
Ar fi garanția reală, dar schimbă un contract de date pe o tabelă centrală și ar
trebui să trateze cele 4 rânduri existente care îl încalcă — deci **ADR propriu**,
nu un amendament aici.
