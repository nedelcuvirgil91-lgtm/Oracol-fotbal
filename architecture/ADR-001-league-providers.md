# ADR-001 — LEAGUE_PROVIDERS ca sursă canonică unică

## Status
Acceptat, implementat.

## Context

Proiectul avea, înainte de această decizie, **cel puțin 6 locuri separate** care mapau
nume de ligă → identificator specific unui provider extern:

- `ODDS_SPORT_KEYS` (mappings.py) — sport_key pt The Odds API
- `FD_COMPETITIONS` (mappings.py) — cod competiție pt football-data.org
- `ESPN_LEAGUE_SLUGS` (mappings.py) — slug pt ESPN
- `TSDB_LEAGUE_IDS` (mappings.py) — id numeric pt TheSportsDB
- `FREE_LF_LEAGUE_IDS` (mappings.py) — id numeric pt Free Live Football
- `COMPETITION_TO_LEAGUE` (sync/sync_results.py) — **copie manuală, independentă**,
  inversă a `FD_COMPETITIONS`

Un audit (iulie 2026) a descoperit că `COMPETITION_TO_LEAGUE` nu fusese actualizat
când `FD_COMPETITIONS` a fost extins ulterior cu `"EL"` (Europa League) și
`"WC"` (World Cup 2026) — rezultat concret: **meciurile din aceste două
competiții nu primeau niciodată rezultate automate** prin job-ul zilnic de
sincronizare (`sync/sync_results.py`), silențios, fără nicio eroare vizibilă.
Mecanismul de recalibrare automată per-meci nu apucase niciodată să ruleze cu
date reale din acest motiv (`sample_count=0` pt toate ligile, confirmat direct
în `model_weights`).

## Decizie

Toate mapările de competiții provin dintr-o singură structură canonică,
`LEAGUE_PROVIDERS` (mappings.py):

```python
@dataclass
class LeagueDefinition:
    name: str
    provider_ids: dict[str, str | int | None]   # {"football_data": "PL", "freelf": 47, ...}
    supported: dict[str, bool | str]             # True / False / "necunoscut"
```

Toate celelalte dicționare (`FD_COMPETITIONS`, `ESPN_LEAGUE_SLUGS`,
`TSDB_LEAGUE_IDS`, `ODDS_SPORT_KEYS`, `FREE_LF_LEAGUE_IDS`,
`COMPETITION_TO_LEAGUE`) sunt **generate automat** din `LEAGUE_PROVIDERS`,
niciodată scrise manual.

`supported` distinge explicit trei stări — **niciodată dedusă dintr-o
valoare lipsă**:
- `True` — confirmat suportat (verificat la sursă)
- `False` — confirmat NEsuportat oficial (verificat la sursă, ex.
  football-data.org plan gratuit are exact 12 competiții documentate public,
  Romania SuperLiga/Conference League nu sunt printre ele)
- `"necunoscut"` — neconfirmat încă; **nu se inventează niciodată un ID sau
  o valoare** doar ca să umple golul.

## Verificare automată

`verify_league_coverage()` compară `LEAGUE_PROVIDERS` cu lista de ligi active
(`BOOTSTRAP_LEAGUES`) și separă problemele pe severitate:
- **errors** — niciun provider obligatoriu (`football_data`/`espn`/`tsdb`)
  confirmat suportat pentru o ligă activă → CI eșuează.
- **warnings** — provideri opționali (`odds`/`freelf`/`api_football`) încă
  neconfirmați → tolerat temporar, nu blochează CI.

Rulată ca test (viitor: integrată în GitHub Actions), astfel încât adăugarea
unei ligi noi fără mapările necesare **nu mai poate trece neobservată**.

## Consecințe

- O ligă nouă (ex. Conference League, adăugată integral odată cu acest ADR)
  se adaugă într-un singur loc.
- `sync/sync_results.py` nu mai definește propriul `COMPETITION_TO_LEAGUE` —
  îl derivă din `FD_COMPETITIONS` (mappings.py). Bug-ul descoperit (Europa
  League + World Cup 2026 fără sincronizare de rezultate) e reparat ca
  efect direct al acestei refactorizări, nu ca patch separat.
- Cost: orice cod care importa direct un dicționar vechi continuă să
  funcționeze neschimbat (compatibilitate păstrată) — migrarea completă a
  codului consumator către `LEAGUE_PROVIDERS` e graduală, nu impusă dintr-o
  dată.
