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
fragmentată — 7.591 de rânduri `YYYY-YYYY` (football_data), 5.245 `YYYY-YY`
(kaggle și altele). Se scrie formatul majoritar și neambiguu. **Normalizarea
celor 5.245 de rânduri istorice NU face parte din acest ADR** — e o decizie
separată, documentată ca gol.

**5. `_current_season_start_date()` folosește startul real al sezonului**,
per ligă, în locul pragului fix pe 1 iulie. Pragul fix e corect pentru ligile
europene, dar greșit pentru MLS (februarie–decembrie), Scandinavia și Brazilia.
Azi nu produce pagubă — verificat: MLS și Ekstraklasa au **0 meciuri** înainte
de 1 iulie în corpus, deci pragul nu taie nimic — dar e o eroare latentă care
mușcă din februarie 2027. Cu sezonul real, dispare fără să mai fie nevoie de
un prag.

### Fragilitate asumată, cu gardă

Clasele barei de progres sunt **hash-uite** (`wcl-start_TGQDT`) și se pot
schimba la orice redeploy Flashscore. Ancorarea se face pe **prefix**
(`wcl-start_`), nu pe numele complet, iar absența lor se **loghează explicit**
— nu se ghicește. Aceeași lecție ca la inversarea de teren din 2026-08-23:
o structură care se schimbă tăcut trebuie să producă un semnal, nu o valoare
inventată. `div.heading__info` e o clasă semantică stabilă, fără hash.

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
