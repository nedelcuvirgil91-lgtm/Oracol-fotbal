# ADR-068 — Starea „amânat" devine explicită, nu dedusă din absența rezultatului

**Status**: Faza A implementată (2026-08-26) · Faza B așteaptă datele Fazei A
**Atinge contractul**: `match_history` (coloană nouă), `scripts/check_data_health.py`
**Nu atinge**: `_upsert_match_canonical_locked` (migrarea 048 rămâne mecanismul de reprogramare), criteriile de promovare, `season`

---

## Context

Azi, un meci amânat și un meci al cărui rezultat n-a fost colectat arată
**identic**: `kickoff_date` în trecut, `actual_result` NULL. Sistemul nu poate
spune care e care.

Nu e teoretic. Din cele 4 meciuri Flashscore raportate pe 2026-08-25 de
`check_data_health` ca „fixture-uri trecute fără rezultat", **trei erau
amânate**, confirmat pe surse independente:

| Meci | Dovadă externă |
|---|---|
| Braga – Gil Vicente, 16 aug | `Postp.` (footlive) |
| Rijeka – Dinamo Zagreb, 8 aug | `Postponed` (sofascore **și** sportytrader) |
| CFR Cluj – U Cluj, 10 aug | amânat oficial de LPF, reprogramat 8 octombrie (flashscore.ro, digisport.ro, as.ro) |

Al patrulea (Wisla Plock – Lech Poznan) rămâne neverificat individual.

### Ce funcționează deja

Migrarea 048 tratează **reprogramarea**: același `fixture_id`, dată nouă → se
mută data, fluxul continuă normal. Verificat live pe Celta Vigo – Osasuna.

### Ce nu funcționează

Între momentul amânării și momentul în care providerul publică data nouă,
meciul rămâne un **fixture-fantomă** cu data veche. În acel interval:

1. `check_data_health` îl raportează ca problemă de colectare. Am acoperit asta
   cu o linie de bază (2026-08-25), dar aceea e o listă manuală care trebuie
   întreținută de om — nu o soluție.
2. Intră în numărătoarea de rânduri „live în sezon" ca meci nejucat, deși nu e.
3. Orice consumator care presupune „dată în trecut + fără rezultat = date
   lipsă" trage concluzia greșită.

Cazul CFR Cluj arată și limita: **știm** data nouă (8 octombrie) din surse
publice, dar sistemul nu are unde s-o pună până când Flashscore n-o expune în
fereastra hub-ului.

---

## Decizie propusă

**1. Coloană nouă `match_status` pe `match_history`**, text, nullable:

| Valoare | Înțeles |
|---|---|
| `NULL` | starea normală — nimic special de spus |
| `postponed` | providerul a marcat meciul ca amânat |
| `cancelled` | meci anulat definitiv |

`NULL` rămâne implicit, deci **niciun rând existent nu se schimbă** și niciun
consumator existent nu se rupe.

**2. Scriitor unic: calea canonică de upsert**, cu `COALESCE`, exact ca
celelalte ~80 de coloane (ADR-036). Nicio cale nouă de scriere.

**3. Sursa: providerul, niciodată inferența.** Dacă Flashscore marchează
`Postp.`, se scrie `postponed`. Dacă nu marchează nimic, coloana rămâne `NULL`
— nu se deduce din „data e în trecut și n-avem rezultat" (North Star #8).
Asta cere o verificare separată a extractorului: **nu am confirmat încă** că
marcajul e prezent în HTML-ul pe care îl descărcăm deja.

**4. `check_data_health` separă cele două clase.** Un meci `postponed` iese din
categoria „cer atenție" și intră în context, ca meciurile din competiții
încheiate. Linia de bază manuală devine inutilă pentru acele rânduri.

**5. Reprogramarea rămâne migrarea 048.** Când providerul publică data nouă,
mecanismul existent mută data. `match_status` se șterge atunci (revine la
`NULL`) — meciul redevine normal.

---

## Argumente PRO

- **Distincția e reală și recurentă**: 3 cazuri confirmate în 3 săptămâni de
  date Flashscore, plus Celta–Osasuna care a blocat descoperirea 10 zile.
- **Elimină o listă întreținută manual.** Linia de bază din
  `data_health_baseline.json` e un plasture: cineva trebuie s-o actualizeze la
  fiecare amânare. O coloană umplută de provider nu cere întreținere.
- **Aditivă și reversibilă.** O coloană nullable, un scriitor, `COALESCE`.
  Dacă se dovedește inutilă, rămâne `NULL` peste tot și nu deranjează nimic.
- **Deblochează măsurarea onestă a acoperirii.** Azi nu putem spune ce procent
  din meciurile jucate au rezultat, fiindcă numitorul include meciuri nejucate.

## Argumente CONTRA, asumate

- **Depinde de un marcaj de provider pe care NU l-am verificat încă.** Dacă
  Flashscore nu-l expune în HTML-ul pe care îl descărcăm, ADR-ul nu se poate
  implementa așa cum e scris. **Asta trebuie verificat înainte de orice cod** —
  altfel construim o coloană care rămâne veșnic `NULL`.
- **Rezolvă o problemă care se autovindecă.** Un meci amânat își capătă data
  nouă în cele din urmă, iar migrarea 048 îl repară singur. Câștigul e
  vizibilitatea în intervalul intermediar, nu corectitudinea finală.
- **Încă o coloană de întreținut**, plus o valoare pe care consumatorii viitori
  trebuie să știe s-o citească.
- **Beneficiu concentrat pe un singur consumator** (`check_data_health`), care
  are deja o soluție de lucru.

## Verdict

**Merită făcut, dar NU înainte de verificarea de la primul contra-argument.**
Ordinea corectă e: (a) confirmăm live că marcajul de amânare există în paginile
Flashscore pe care le descărcăm deja; (b) abia apoi migrarea și cablarea. Dacă
marcajul nu există, ADR-ul se închide ca „blocat upstream", nu se implementează
pe jumătate.

---

## Verificarea cerută — făcută 2026-08-26, rezultat PARȚIAL

**Confirmat**, pe HTML real din repo (55 de fișiere salvate ca evidență POC):

```html
<span class="detailStatus">Finished</span>              88 apariții
<div class="fixedHeaderDuel__detailStatus">Finished</div>
„After Extra Time"                                      12 apariții
```

Câmpul **există**, e în pagina `summary` pe care pipeline-ul o descarcă deja
(cost de rețea **zero**), iar clasele sunt **semantice — fără hash**, deci
structural mai robuste decât bara de sezon din ADR-067. Normalizatorul nu îl
extrăgea deloc: singura potrivire pe „status" în tot fișierul era
`wcl-stageTime`, altceva.

**NEconfirmat: litera pentru un meci AMÂNAT.** Niciunul din cele 55 de fișiere
nu conține un meci amânat. Sandbox-ul de dezvoltare nu ajunge la
flashscore.com (403 la proxy, verificat), iar pagina e randată prin JS, deci nu
poate fi citită printr-un fetch extern. Două proiecte independente de scraping
listează `postponed`/`cancelled`/`abandoned`, dar acelea sunt valorile **lor
normalizate**, nu literalul din DOM — dovadă de a doua mână, insuficientă
pentru a defini un vocabular canonic.

### Consecință: ADR-ul se împarte în două faze

**Faza A — COLECTARE, fără interpretare** *(implementată 2026-08-26)*.
`extract_detail_status()` extrage litera **verbatim** — fără traducere, fără
`lower()`, fără mapare. Valoarea ajunge în `flashscore_raw_extraction` prin
`flashscore_status_raw`, o cheie care NU e coloană canonică (RPC-ul citește
doar chei cunoscute, deci o ignoră inofensiv). Numele conține deliberat `_raw`:
semnalează că valoarea nu trebuie citită ca stare a meciului.

Faza A **este** verificarea cerută, făcută prin conductă în loc de ad-hoc: după
o rulare de noapte, valorile distincte reale devin observabile în RAW.

**Faza B — INTERPRETARE** *(neîncepută, așteaptă datele Fazei A)*. Coloana
`match_status`, migrarea, maparea literalelor **observate**. Nu se pornește
până când vocabularul nu e citit din date proprii.

Aceeași disciplină ca la ADR-067: se colectează faptul întâi, se interpretează
după. Și evită exact ce interzice acest ADR în propriul text — o coloană
construită pe un vocabular ghicit.

---

## Consecințe

**Pozitive**
- Un meci amânat încetează să arate ca o eroare de colectare.
- Linia de bază manuală se micșorează la cazurile genuin necunoscute.
- Acoperirea rezultatelor devine măsurabilă onest.

**Negative, acceptate**
- Încă o coloană și încă o stare de cunoscut.
- Dependență de un marcaj de provider — dacă Flashscore îl schimbă, coloana
  încetează tăcut să se populeze. Aceeași clasă de fragilitate ca la calendarul
  din ADR-067, cu aceeași mitigare posibilă (log la absență).

**Ce NU face acest ADR**
- Nu schimbă mecanismul de reprogramare (migrarea 048).
- Nu introduce descoperirea datei noi din surse externe — CFR Cluj rămâne
  fixture-fantomă până când Flashscore publică 8 octombrie.
- Nu atinge `season` și nu modifică ADR-066/067.
