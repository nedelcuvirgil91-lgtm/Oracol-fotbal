# ADR-046 — Matricea de protecție rate-limit per provider (eliminarea fail-open din RateLimitManager)

**Status**: **ACCEPTAT ȘI IMPLEMENTAT** — aprobat explicit de proprietarul produsului, 2026-08-03 (EPIC „Functional Completion", Punctul 1).

**Autor**: Claude, la cererea proprietarului produsului.

**Data**: 2026-08-03.

**Companion**: `docs/00_GOVERNANCE/FUNCTIONAL_COMPLETION_MASTER_PLAN.md` (finding #1, 🔴 Critic — sursa auditului care a identificat problema). Extinde `RateLimitManager`/`RequestManager` introduse de ADR-038 (`api-football-synchronization-architecture-v2.md`) — nu le rescrie, nu le contrazice.

---

## Context

`RateLimitManager` (ADR-038, R4.1) urmărea bugetul real per provider DOAR din header-ele oficiale API-Football (`x-ratelimit-*`). `can_request()` e fail-open prin design cât timp niciun header cunoscut nu a fost citit — comportament corect ca plasă de siguranță, dar devenit un bug real pentru cei 5 provideri care nu foloseau niciodată convenția de nume API-Football: TheSportsDB, WeatherAPI, The Odds API, eloratings.net, football-data.org. Pentru aceștia, `self._state[provider]` rămânea `None` la nesfârșit — fail-open PERMANENT, nu temporar.

Auditul „Functional Completion" (finding #1, 🔴 Critic) a cerut verificare **cu dovadă live**, nu presupunere din documentația publică a fiecărui provider. S-a construit un POC temporar (`sync/poc_rate_limit_headers_check.py` + workflow `workflow_dispatch` dedicat, ambele șterse după închiderea investigației — dovada rămâne în istoricul rulărilor GitHub Actions, run `30831280759`, 2026-08-03, și în mesajele de commit `9f18133`/`48bb3e5`) — un singur apel HTTP real per provider, prin exact punctul de intrare de producție (`FootballOracleAPI._get()`), logând toate header-ele brute de răspuns.

## Decizie — Matricea de protecție per provider

| Provider | Header real confirmat live | Mecanism de protecție | Motiv dacă nu există rate-limit real din header |
|---|---|---|---|
| **The Odds API** (`oddsapi`) | `x-requests-remaining: 484`, `x-requests-used: 16`, `x-requests-last: 2` | **Header real** — mapat în `RateLimitManager._PROVIDER_SCHEMES["oddsapi"]` la `daily_remaining` | — (are header real, protejat) |
| **WeatherAPI** (`weatherapi`) | `x-weatherapi-qpm-left: 999999` | **Header real** — mapat la `minute_remaining` (semantică per-minut, "queries per minute left", nu zilnică) | — (are header real, protejat) |
| **TheSportsDB** (`thesportsdb`) | niciun header cu `rate`/`limit`/`remaining`/`quota` în nume (confirmat, listă completă de header-e verificată) | **Throttling static documentat** — `oracle_api._STATIC_THROTTLE_INTERVAL_SECONDS["thesportsdb"] = 1.0`, enforce direct în `_get()` | Cheie publică de test partajată (`"3"`, fără cont propriu) — niciun API key propriu, deci niciun header de cotă per-cont posibil. Interval ales conservator; nu există documentație oficială confirmată pentru un număr exact (verificat, nu găsit) |
| **eloratings.net** | niciun header cu `rate`/`limit`/`remaining`/`quota` în nume (confirmat) | **Protecție structurală, cache-only** — scrape HTML unic (toate ratingurile naționale într-un singur răspuns, fără paginare per echipă) + `CacheManager` TTL 24h (`_cget`/`_cset("elo_ratings", ...)`) — cel mult un apel real la 24h per proces, indiferent de câte procese partajează cache-ul disc/Supabase | Pagină HTML statică, fără API/cheie — nu trimite niciodată header-e de cotă. Cache-ul de 24h e o protecție mai puternică decât orice interval static per-cerere, pentru că natura apelului (un singur scrape acoperă toate echipele) elimină orice risc de burst |
| **football-data.org** (`footballdata`) | nu a necesitat verificare live — throttling static deja documentat înainte de acest audit | **Throttling static preexistent** — `REQUEST_INTERVAL = 6.1` (10 req/min, plan gratuit), `sync/sources/football_data.py::_rate_limited_get()`, neatins de acest ADR | Confirmat prin citire de cod (`REQUEST_INTERVAL`, comentat explicit „Rate limit: 10 requests/minut pe planul gratuit") — suficient, nu a necesitat verificare live suplimentară |

## Implementare

- `rate_limit_manager.py`: `_PROVIDER_SCHEMES` — mapare explicită, per provider, header real → slot intern (`daily_limit`/`daily_remaining`/`minute_limit`/`minute_remaining`). `_DEFAULT_SCHEME` (convenția API-Football) rămâne neschimbată pentru `apifootball`/`soccerfootballinfo` — niciun provider existent nu-și schimbă comportamentul.
- `oracle_api.py::_get()`: gating (`should_request`) + înregistrare (`record_response_headers`) devin **universale**, aplicate automat pe baza providerului detectat din URL (`_detect_provider_endpoint()`, mecanism deja existent pentru `provider_metrics`) — orice provider nou care trece prin `_get()` capătă automat același gating, fără cod nou la fiecare apelant. Fail-open păstrat identic acolo unde nu există `_request_manager` atașat (dublurile de test existente) sau header-e recunoscute (comportament neschimbat, documentat deja în ADR-038).
- `oracle_api.py::_fetch_elo_ratings()`: bypass istoric al `_get()` (răspuns HTML, nu JSON) — protecția rămâne documentată direct la punctul de apel, fără cod de enforcement suplimentar (motivat mai sus).

## Consecințe

**Pozitive**:
- Cei 4 provideri auditați (TheSportsDB, WeatherAPI, The Odds API, eloratings.net) nu mai sunt fail-open PERMANENT — fiecare are acum fie protecție reală din header, fie o protecție documentată explicit, cu motiv.
- Generalizarea din `_get()` elimină riscul ca un provider viitor să repete aceeași gaură — gating-ul e automat, nu opțional per apelant.
- Zero regresie: 1915 teste trecute (12 noi, dedicate acestui ADR), aceleași 3 eșecuri preexistente și necorelate, neschimbate.

**Negative/costuri**:
- `x-weatherapi-qpm-left`/`x-requests-remaining` nu au un header explicit de "limit" — `RateLimitManager` urmărește doar "remaining", suficient pentru blocare la epuizare, dar fără vizibilitate asupra plafonului total configurat pe cheie.
- Intervalul static pentru TheSportsDB (1.0s) e o alegere conservatoare internă, nu dintr-o documentație oficială confirmată — poate fi ajustat dacă apare o sursă oficială.

## Aprobare

```
[x] Aprobat de proprietarul produsului — data: 2026-08-03.
```
