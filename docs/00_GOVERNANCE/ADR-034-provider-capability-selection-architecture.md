# ADR-034 — Provider Capability, Registry & Selection Architecture

**Status**: FROZEN

**Autor**: Claude, redactat ca lucrare proprie, în colaborare directă cu
proprietarul produsului — design iterativ (propunere inițială → restructurare
pe straturi, cerută explicit → scor ponderat, cerut explicit → 3 reguli
suplimentare, cerute explicit → aprobare finală + 3 ajustări de text înainte
de Freeze), fiecare etapă aprobată explicit înainte de a trece la următoarea.

**Data redactării**: 2026-07-18. Nu există încă nicio implementare — acest
fișier e contractul normativ care urmează să fie implementat (PR1-PR7), nu
unul retroactiv.

---

## Context

`oracle_api.py::get_matches_for_week()` conține o secvență hardcodată de 6
pași (Odds API → FreeLF → football-data.org → ESPN → TheSportsDB →
API-Football → demo), fiecare cu gating ad-hoc propriu, scris separat:
`_dead_keys` (doar Odds API), `_freelf_exhausted` (doar FreeLF), un gate
global `len(matches)<5` pentru TheSportsDB (cauza reală, verificată live, a
BUG-014B — TheSportsDB nu a fost niciodată interogat pentru Romania
SuperLiga fiindcă alte ligi umpluseră deja pragul global), și starea
`"plan_restricted"`, inventată ad-hoc pentru API-Football (vezi investigația
live din aceeași sesiune: `/fixtures?league=283&season=2026` → HTTP 200,
`errors.plan: "Free plans do not have access to this season"`).

`provider_metrics` (Supabase, ADR-003) e scris consecvent la fiecare apel
real, dar niciodată citit — infrastructură de observabilitate moartă pe
jumătate.

Proiectul urmează să adauge multipli provideri noi pe termen scurt
(SportAPI/sportapi7, confirmat live funcțional pentru Romania SuperLiga
sezonul curent — spre deosebire de API-Football, blocat de plan — plus
potențial alții). În arhitectura actuală, fiecare provider nou cere cod nou,
scris manual, în `oracle_api.py`.

## Decizie

Se adoptă o arhitectură pe 6 straturi, fiecare independent testabil,
implementată în ordinea PR1→PR7 de mai jos (nu Selection Engine primul):

1. **Provider Registry** — enumerare canonică a providerilor. Derivă din
   `key_manager.PROVIDERS.keys()`, nu-l duplică — sursă unică de adevăr
   pentru „ce provideri există", separată de mecanica de credențiale/cotă.
2. **Capability Registry** — declarativ, static, per provider: `data_types`
   (din `DataType`, vezi Regula 1), `cost_class`, TTL implicit per tip de
   date, `version` (Regula 2).
3. **League Mapping v2** — extensie a `mappings.LEAGUE_PROVIDERS` existent
   (NU înlocuire): vocabular de stare generalizat (`True` / `False` /
   `"necunoscut"` / `"plan_restricted"` / `"dead_key"` / `"quota_exhausted"`)
   + `confidence` explicit per intrare (Regula 3).
4. **Health Monitor** — citește, pentru prima oară, `provider_metrics`
   (reliability, `consecutive_failures`, latență) + cota rămasă din
   `key_manager`. Zero scriere nouă.
5. **Selection Engine** — strat subțire deasupra straturilor 1-4: filtrare
   tare (Capability Registry + League Mapping exclud binar), apoi scor
   ponderat DOAR între supraviețuitori.
6. **Prediction Engine** (`oracle_engine.py`) — neschimbat, agnostic de
   sursă; cere date pe tip/ligă, nu știe niciodată din ce provider vin.

### Scor ponderat (Selection Engine, strat 5)

```
score = 0.40 · availability   (provider funcțional global, nu doar pt. liga cerută)
      + 0.25 · coverage       (liga cerută: confirmată / necunoscută, în League Mapping)
      + 0.15 · reliability    (din provider_metrics: 1 - errors/calls)
      + 0.10 · quota          (% cotă rămasă, din key_manager)
      + 0.05 · latency        (invers normalizat, din avg_latency_ms)
      + 0.05 · priority       (tie-breaker static, configurabil)
```

Aplicat DOAR providerilor care trec filtrarea tare (suportă tipul de date
cerut ȘI nu sunt `False`/`plan_restricted`/`dead_key`/`quota_exhausted`
pentru liga cerută).

### Regula 1 — Data Type Registry obligatoriu

```python
class DataType(Enum):
    FIXTURES = "fixtures"
    ODDS = "odds"
    STANDINGS = "standings"
    STATISTICS = "statistics"
    LINEUPS = "lineups"
    PLAYER_RATINGS = "player_ratings"
    XG = "xg"
    H2H = "h2h"
    MANAGERS = "managers"
    INJURIES = "injuries"
    TRANSFERS = "transfers"
```

Niciun string liber în Capability Registry sau League Mapping — doar valori
din acest enum. Previne desincronizare de tipul `"statistic"` vs
`"statistics"` vs `"stats"`.

### Regula 2 — Provider Capability Version

Fiecare intrare din Capability Registry poartă `version: int`, explicit. O
schimbare de structură la un provider (ex. SportAPI v2) devine o intrare
NOUĂ versionată, nu o suprascriere silențioasă — coerent cu disciplina
generală a proiectului („nicio editare tăcută a unui contract").

### Regula 3 — Confidence Level (nu doar True/False)

Fiecare `(provider, league, data_type)` din League Mapping poartă, separat
de starea binară/enumerată, un nivel de încredere explicit:

```
CONFIRMED  — verificat live, cu dovadă (ex. fixtures Romania SuperLiga
             prin SportAPI, verificat live în această sesiune)
DOCUMENTED — din documentație oficială, neverificat live
ASSUMED    — presupus prin analogie structurală cu alt endpoint
UNKNOWN    — necunoscut complet
```

`confidence` nu decide dacă se încearcă (asta rămâne rolul stării din §3) —
explică CÂT DE SIGURĂ e informația, trasabil peste luni, coerent cu
filosofia „Verificat, nu presupus" (CLAUDE.md).

## PR-uri (ordinea obligatorie)

| PR | Conținut | Efect asupra comportamentului live |
|---|---|---|
| PR1 | Provider Registry | Niciunul — doar enumerare |
| PR2 | Capability Registry | Niciunul — doar date declarative |
| PR3 | League Mapping v2 | Niciunul — extensie aditivă peste `mappings.py` existent |
| PR4 | Health Monitor | Niciunul — doar citire, zero scriere nouă |
| PR5 | Selection Engine — **shadow mode** | Niciunul — loghează `Current provider / Engine recommendation / Reason (scor A vs B)`, NU schimbă rezultatele reale |
| PR6 | Feature flag ON | Abia acum motorul decide efectiv — flag implicit OFF până aici |
| PR7 | Eliminarea logicii hardcodate din `oracle_api.py` | Doar după validare shadow reușită |

### Criterii de succes PR5 → PR6 (obligatorii, verificate înainte de activare)

Activarea flag-ului (PR6) se face DOAR dacă, pe perioada shadow mode (PR5):

1. recomandările motorului coincid cu providerul folosit efectiv azi în
   **>95%** din cazurile observate;
2. nu apar regresii funcționale (niciun caz în care motorul ar fi ales un
   provider care întoarce mai puține date decât cel curent, pentru aceeași
   cerere);
3. rata de erori de fetch NU crește față de baseline-ul actual;
4. consumul real de cereri API rămâne în limitele estimate per provider
   (nicio cotă epuizată neașteptat din cauza motorului).

Niciun criteriu nu poate fi omis sau relaxat fără un ADR nou, dedicat.

## Consequences

- Provider nou = doar date noi în Provider Registry + Capability Registry +
  League Mapping — zero cod nou în `oracle_api.py`, obiectivul central al
  acestui ADR.
- Rezolvă generic cauza reală a BUG-014B (gate global → filtrare per
  `(league, data_type)`, pentru toți providerii, nu doar cel adăugat ultim).
- `provider_metrics` capătă, pentru prima oară, un consumator real.
- Costuri: 4 module noi (`provider_registry.py`, `provider_capabilities.py`,
  `provider_health.py`, `provider_selector.py`); migrarea `_dead_keys`/
  `_freelf_exhausted` în vocabularul unificat e efort de implementare
  separat, nu doar design; calibrarea inițială a ponderilor/priority
  necesită date reale din shadow mode, nu poate fi „ghicită" corect din
  prima — motiv suplimentar pentru care PR5 rulează în shadow înainte de
  PR6.

## Dependencies

`mappings.py`, `key_manager.py`, `cache_manager.py`, `supabase_client.py`
(`provider_metrics`), `oracle_api.py`, `football_providers.py`.

## References

Sesiune live: verificare API-Football (`plan_restricted`, runs
29616468120/29616932623), verificare SportAPI (runs 29631260855/
29631591251/29631849589, 16 apeluri reale confirmate funcționale pentru
Romania SuperLiga sezonul curent) · BUG-014B (cauza gate global TSDB) ·
CLAUDE.md — Architectural North Star, regulile 3/5/9/10.

## Regulă normativă

Niciun provider nou nu se adaugă prin cod nou în `oracle_api.py` — doar prin
completarea Provider Registry + Capability Registry + League Mapping.
Selection Engine rulează exclusiv în shadow mode (PR5) minimum câteva zile
înainte de activare (PR6, flag implicit OFF, per regula 3 CLAUDE.md).
Eliminarea logicii hardcodate (PR7) se face DOAR după validare shadow
reușită conform criteriilor de succes de mai sus, nu odată cu activarea
flag-ului.

**Backward compatibility**: Until PR7 is completed, the legacy
provider-selection path must remain fully functional and switchable through
the feature flag. No existing production behaviour may change before the
shadow-mode validation is complete.

---

## Freeze Declaration

**ADR-034 — FROZEN.**

Tratat de acum ca contract normativ, nu document de lucru — nicio
modificare arhitecturală ulterioară decât printr-un ADR nou, dedicat, per
aceeași regulă aplicată ADR-026/028/030/031/033.

### Ce rămâne blocat, permanent, prin acest freeze:

- Ordinea de implementare PR1→PR7, neschimbată — Selection Engine NU se
  construiește înaintea Provider Registry/Capability Registry/League
  Mapping/Health Monitor.
- Vocabularul `DataType` (Regula 1) — extindere posibilă (valori noi), nu
  redenumire a celor existente.
- `version` obligatoriu pe orice intrare de Capability Registry (Regula 2).
- `confidence` obligatoriu, separat de starea binară/enumerată, pe orice
  intrare de League Mapping (Regula 3).
- Formula de scor ponderat (§Decision) — ponderile pot fi recalibrate DOAR
  cu date din shadow mode (PR5), niciodată ghicite.
- Criteriile de succes PR5→PR6, toate 4, obligatorii, fără relaxare fără
  ADR nou.
- Backward compatibility explicită: comportamentul de producție NU se
  schimbă înainte de finalul validării shadow (PR7 exclus).

### Următorul pas

Aștept confirmarea ta explicită pentru a începe implementarea PR1 (Provider
Registry), urmând aceeași disciplină folosită la ADR-026/028/030/031/033:
plan + identificare dependențe ascunse → implementare → teste → PR →
verificare → merge (doar după aprobare explicită).
