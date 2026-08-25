# ADR-066 — `season` devine coloană canonică, scrisă de calea de upsert

**Status**: Accepted (2026-08-25)
**Atinge contractul**: `_upsert_match_canonical_locked` (migrarea 052),
`providers/flashscore/*`, `oracle_engine._current_season_start_date()`
**Nu atinge**: formatul rândurilor istorice, criteriile de promovare, RLS

---

## Context

`match_history.season` e `NULL` pentru **toate** cele 1.058 de rânduri
Flashscore, dintre care 757 scrise doar în august. Golul e documentat din
2026-08-03 cu următoarea concluzie:

> „Flashscore: nicio extracție de sezon nu există încă în pipeline (nu doar
> netransmisă — genuin necolectată de pe pagină), ar cere investigație live
> nouă, neinclusă acum."

**Concluzia aceea era greșită**, iar dovada exista deja în repo. Verificat
2026-08-25, pe fișierele POC salvate
(`docs/06_UDAL/poc_evidence/flashscore_10matches/*_hub_raw.html`) — adică pe
HTML pe care pipeline-ul **îl descarcă deja** la fiecare rulare de Discovery:

| Element | Selector | Exemplu |
|---|---|---|
| Eticheta sezonului | `div.heading__info` | `2026/2027` |
| Începutul sezonului | `.wcl-progressBarContainer_ … .wcl-start_` | `17.07.` |
| Sfârșitul sezonului | `.wcl-progressBarContainer_ … .wcl-end_` | `30.05.` |

Confirmat pe două competiții cu calendare diferite (Romania SuperLiga
`17.07.→30.05.`, Champions League `07.07.→05.06.`) și, independent, pe
capturi de ecran ale proprietarului produsului: Ligue 1 `21.08.→06.06.`,
MLS `21.02.→18.12.`.

Nu era nevoie de nicio investigație live. Costul suplimentar de rețea al
extragerii este **zero** — pagina e deja adusă.

### Al doilea blocaj, descoperit la verificare

Chiar dacă extragerea ar exista, **nu ar avea unde să scrie**: niciunul dintre
cele trei RPC-uri canonice nu cunoaște coloana.

```
_upsert_match_canonical_locked   cunoaste_season = false
upsert_match_canonical           cunoaste_season = false
upsert_matches_canonical         cunoaste_season = false   (buclă peste prima)
```

Consecință netestată, dar mecanic implauzibilă: `CLAUDE.md` afirmă că „de acum,
orice meci nou de la football-data.org are `season` corect de la prima
scriere". Nu există **niciun** rând football_data scris după 2026-08-04 (ziua
backfill-ului), deci afirmația nu a putut fi verificată pe date — iar calea de
scriere spune că nu s-ar întâmpla. Rămâne marcată ca neverificată, nu ca
greșită.

---

## Decizie

**1. `season` devine coloană canonică**, adăugată în
`_upsert_match_canonical_locked` cu `COALESCE` (migrarea 052), exact ca
celelalte ~70. Asta deblochează orice provider, nu doar Flashscore, și face ca
afirmația despre football_data să devină adevărată.

**2. Flashscore extrage sezonul din hub-ul de ligă**, din HTML-ul deja adus.

**3. Anul se derivă DETERMINIST, niciodată prin ghicire calendaristică.**
Eticheta dă anii; luna decide care dintre ei:

- `2026/2027` + start luna 07 → `2026-07-17`; + sfârșit luna 05 → `2027-05-30`
- `2026` (sezon într-un singur an, ex. MLS) → ambele în 2026

Dacă eticheta lipsește sau nu se potrivește niciunui tipar cunoscut, sezonul
rămâne `NULL`. `season_cleanup.py` interzice deja explicit aproximarea
calendaristică — regula nu se slăbește aici (North Star #8).

**4. Format canonic pentru scrierile NOI: `YYYY-YYYY`.** Coloana e azi
fragmentată. Măsurat exact la aplicarea migrării 052 (2026-08-25):

| Sursă | Format | Rânduri | Ultima zi acoperită |
|---|---|---|---|
| football_data | `YYYY-YYYY` | 7.534 | 2026-05-30 |
| kaggle | `YYYY-YY` | 3.352 | 2025-05-31 |
| openfootball | `YYYY-YY` | 2.119 | 2025-05-31 |
| kaggle | `YYYY-YYYY` | 58 | 2025-05-18 |

Se scrie formatul majoritar și neambiguu. **Normalizarea celor 5.471 de rânduri
`YYYY-YY` NU face parte din acest ADR** — e o decizie separată, documentată ca
gol. Există exact două formate, niciun al treilea.

**5. `_current_season_start_date()` folosește startul real al sezonului**,
per ligă, în locul pragului fix pe 1 iulie. Pragul fix e corect pentru ligile
europene, dar greșit pentru MLS (februarie–decembrie), Scandinavia și Brazilia.
Azi nu produce pagubă — re-verificat 2026-08-25: **zero** meciuri Flashscore
înainte de 1 iulie 2026, în oricare dintre cele 17 ligi cu date — dar e o
eroare latentă care mușcă din februarie 2027, când pentru MLS „1 iulie 2026"
ar amesteca sezonul 2026 cu 2027 în același profil de echipă.

**Sursa startului real: `match_history` însuși, nu o tabelă nouă.**
`get_current_season_start(league)` face doi pași — (a) sezonul celui mai
**recent meci** al ligii, (b) prima zi a acelui sezon. Pasul (a) e deliberat
„cel mai recent meci", nu `max(season)` lexicografic: coloana are două formate
incompatibile (§4), iar o comparație între ele nu are sens garantat.

Alternativa evaluată și respinsă: o tabelă nouă cu metadate de sezon per
competiție, alimentată din `start_date`/`end_date` deja parsate din hub. Ar fi
fost un contract nou (Discovery Rule) pentru un câștig pe care datele existente
îl oferă oricum. Intervalul din hub rămâne folosit acolo unde chiar e nevoie de
el — garda `season_for_kickoff()` — fără să fie persistat.

Pragul de iulie rămâne ca **plasă de siguranță explicită**
(`_season_start_fallback()`), pentru ligile fără sezon cunoscut în date. Azi
asta înseamnă TOATE ligile (zero rânduri cu `season`), deci comportamentul e
neschimbat pentru toată lumea; fixul se activează singur pe măsură ce cablarea
din decizia 2 scrie sezoane.

### Fragilitate asumată, cu gardă

Clasele barei de progres sunt **hash-uite** (`wcl-start_TGQDT`) și se pot
schimba la orice redeploy Flashscore. Ancorarea se face pe **prefix**
(`wcl-start_`), nu pe numele complet, iar absența lor se **loghează explicit**
— nu se ghicește. Aceeași lecție ca la inversarea de teren din 2026-08-23:
o structură care se schimbă tăcut trebuie să producă un semnal, nu o valoare
inventată. `div.heading__info` e o clasă semantică stabilă, fără hash.

---

## Ce s-a dovedit diferit la implementare (2026-08-25)

Trei lucruri au ieșit la iveală abia la aplicare. Rămân notate aici, nu
corectate tăcut în textul de mai sus.

**1. Golul e de patru ori mai mare decât spunea Contextul.** ADR-ul vorbea
despre 1.058 de rânduri `match_history`. `persistence.py` transmite același
parametru `season` la încă trei tabele (liniile 142, 158, 167), toate la fel de
goale:

```
match_history (flashscore_*)        1.058 rânduri →  0 cu sezon
flashscore_match_context           12.569 rânduri →  0 cu sezon
match_statistics_extended          11.454 rânduri →  0 cu sezon
flashscore_standings_snapshot         267 rânduri →  0 cu sezon
                                   ──────────────────────────────
                                   25.348 rânduri →  0 cu sezon
```

Nu e o extindere de scop: aceeași cauză unică (`season=None` propagat pe tot
lanțul), aceeași reparație de o linie. Cele trei tabele suplimentare nu trec
prin RPC-ul canonic — beneficiază direct de cablare, fără migrare.

**2. `openfootball` e scriitor ACTIV de format `YYYY-YY`.** Comentariul din
`sync/sources/openfootball.py` („0 rânduri openfootball_* în producție azi",
verificat 2026-08-03) e depășit: azi sunt 2.119. Deci fragmentarea de format nu
e un rest istoric înghețat, ci e produsă în continuare de o cale vie din
`run_daily.py` (`use_openfootball=True`). Nu se schimbă aici — migrarea 038 cere
explicit sezonul „exact cum îl oferă sursa", iar schimbarea formatului unui
provider e o decizie separată. Notat ca gol real, nu ca detaliu.

**3. Hub-ul `/fixtures/` poartă eticheta, dar nu și bara de interval.**
Verificat live (2026-08-25): pagina `/fixtures/` a SuperLigii afișează
„Superliga 2026/2027", fără bara de progres. Contează pentru că exact acel hub
e folosit de `flashscore_weekly_fixtures.yml` (`future_fixtures_only=True`).
De aceea garda de interval (`season_for_kickoff()`) se aplică **doar când
intervalul e cunoscut** — fără el, eticheta rămâne singurul semnal și se
folosește ca atare. Nu se inventează un interval doar ca să existe ce verifica.

---

## Consecințe

**Pozitive**

- 1.058 de rânduri Flashscore capătă sezon; creșterea de ~750/lună se oprește.
- Pragul fix de 1 iulie dispare — o eroare latentă închisă înainte să muște.
- Coloana `season` devine scriibilă pe calea canonică pentru **orice** provider.
- Cost de rețea zero: pagina e deja descărcată.

**Negative, acceptate**

- Dependență de structura HTML a unui provider. Mitigată prin ancorare pe
  prefix + log la absență, nu eliminată.
- O coloană în plus în corpul RPC-ului canonic.
- Sezoanele rămân în două formate până la o decizie separată de normalizare.

**Ce NU face acest ADR**

- Nu normalizează cele 5.245 de rânduri `YYYY-YY`.
- Nu face backfill pe cele 1.058 de rânduri Flashscore existente — scriere pe
  producție, cere aprobare separată, cu SQL arătat integral.
- Nu schimbă `season_cleanup.py` și nu slăbește interdicția de aproximare.
