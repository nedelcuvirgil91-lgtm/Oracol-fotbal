# Universal Synchronization Architecture — Audit + Design (Pre-Implementation)

**Status**: FROZEN — aprobat oficial de proprietarul produsului, 2026-07-22, ca bază oficială pentru implementarea Universal Synchronization Architecture. Niciun cod scris sub acest document. Companion la `docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md` (de asemenea Frozen).

**Data**: 2026-07-22. **Autor**: Claude, la cererea explicită a proprietarului produsului, ca extindere a ADR-038 (API-Football) la toți providerii externi ai proiectului.

**Metodologie, spusă explicit**: acest document reutilizează integral evidența deja adunată pentru API-Football (`API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md`, verificată live prin Exa/Postman/cod) — nu se repetă cercetarea externă acolo unde a fost deja făcută. Pentru ceilalți provideri (Odds API, Weather API, football-data.org, FreeLF, ESPN, TheSportsDB), auditul de mai jos e sursat din **codul existent** (`fișier:linie`, citit direct în această sesiune), nu din documentație oficială externă re-cercetată — nu exista o presiune operațională echivalentă cotei de 100/zi a API-Football care să justifice acel nivel de efort pentru fiecare provider acum. Unde o afirmație ar necesita verificare live neefectuată, e marcată explicit `Assumed`/`de verificat`, nu prezentată ca `Verified`.

---

## 1. Audit al tuturor providerilor existenți

| Provider | Rol azi în Oracle Engine | Tip date | Stare chei | Persistare existentă | Politică de fallback |
|---|---|---|---|---|---|
| **Kaggle** | Import istoric, o dată (`sync/import_historical.py`) | Meciuri istorice (`HomeElo`/`AwayElo` incluse) | N/A (fișier local, nu API live) | **DA — deja 100% sync-only**, scrie direct în `match_history` | N/A — niciodată apelat live |
| **API-Football** | Injuries/coaches/team ID (`oracle_engine.py:1333-1357`), fixtures fallback inert | Team health, fixtures (inert) | Env var (`API_FOOTBALL_KEY`), migrat R4.1 | Parțial — Coverage Cache (migrare 016, aplicată); team health **încă live**, fără persistare | Apel live, inline, per meci evaluat — candidatul deja proiectat pentru migrare (ADR-038) |
| **Odds API** | (a) cote pre-meci — sursă PRIMARĂ de descoperire meciuri + cote (`get_matches_for_week`, pasul 1, `oracle_api.py:1189-1192`); (b) fallback H2H (`get_h2h`, `oracle_api.py:489`); (c) fallback formă/scoruri (`get_team_recent_form`, `oracle_api.py:648`) | Fixtures+odds (a), H2H (b), formă (c) | Env var (`ODDS_API_KEY`), migrat R4.1 | **(a) DA — deja Frozen** (`services/odds_persistence_service.py`, ADR-005/006); (b)/(c) NU | (a) deja sync-first prin design; (b)/(c) apel live, fallback ADR-035 |
| **Weather API** | Prognoză oraș+dată pentru penalizare xG (`get_weather`, `oracle_api.py:1104`, apelat necondiționat, `oracle_engine.py:1286`) | Vreme (prognoză, nu istoric) | Env var (`WEATHER_API_KEY`), migrat R4.1 | NU | Apel live, necondiționat — nu e „fallback", e singura cale azi |
| **football-data.org** | Fallback formă/standings (`get_standings_form`, `oracle_api.py:725`), fallback descoperire meciuri (`_fetch_matches_fd`, pasul 3 din `get_matches_for_week`) | Standings, fixtures | Env var (`FOOTBALL_DATA_KEY`), migrat R4.1 — **singurul provider deja bine practicat** înainte de R4.1 (folosea `key_manager` corect, fără duplicare) | NU | Apel live, fallback ADR-035 |
| **FreeLF (Free Live Football)** | **Sursă PRIMARĂ** pentru descoperirea meciurilor săptămânii (pasul 2, `oracle_api.py:1194-1201`), plus fallback H2H (`self.api.get_h2h`, indirect via event_id FreeLF), formă (`get_team_form_freelf`), standings (`get_freelf_standings`) | Fixtures (primar), formă, standings | Env var (`RAPIDAPI_KEY_FREELIVEFOOTBALL`), migrat R4.1 | NU | Cel mai greu folosit provider structural — nu doar fallback, sursă primară de descoperire |
| **ESPN** | Fallback descoperire meciuri (pasul 4, `_fetch_matches_espn`, `oracle_api.py:732`) | Fixtures | N/A — provider public, fără cheie (nu apare în `key_manager.PROVIDERS`) | NU | Apel live, fallback ADR-035 |
| **TheSportsDB** | Fallback descoperire meciuri (pasul 5, `_fetch_matches_tsdb`, `oracle_api.py:806`), team stats (`get_team_stats`, `oracle_api.py:902`), ELO fallback pentru naționale (`ELO_RATINGS_FALLBACK`, `get_elo_rating`, `oracle_api.py:975`) | Fixtures, stats, ELO | N/A — provider public, fără cheie | NU | Apel live, fallback ADR-035; singura sursă reală pentru naționale (fără meciuri de club sincronizate) |
| **sportapi** (RapidAPI) | **Declarat în registry (ADR-034), niciodată apelat din nicio cale de producție** — confirmat prin grep, zero rezultate | — | Env var (`RAPIDAPI_KEY_SPORTAPI`), migrat R4.1 | N/A | N/A — dormant |
| **Understat** | Neintegrat azi | — | — | — | — |

**Observație structurală, nouă față de auditul API-Football**: nu toți providerii sunt „fallback-uri" — **FreeLF și Odds API sunt surse PRIMARE** pentru descoperirea meciurilor (nu doar completare de date lipsă). Migrarea lor la sync-only e calitativ diferită de migrarea unui fallback rar-folosit (football-data/ESPN/TSDB) — afectează calea prin care Oracle Engine află *ce meciuri există*, nu doar *ce features are un meci deja cunoscut*.

**Observație #2**: Odds API pentru cote pre-meci **e deja conform regulii** — persistare Frozen dedicată, existentă înainte ca regula să fie formulată explicit. Nu e un candidat de migrare, e dovada că principiul funcționează deja acolo unde a fost aplicat.

---

## 2. Universal Sync Layer — componente

| Componentă | Există azi? | Unde | Ce lipsește |
|---|---|---|---|
| **Provider Adapters** | Parțial — `FootballDataProvider` (ABC, `football_providers.py:71-89`) e deja exact acest tipar, dar doar pentru API-Football (injuries/coaches) | `football_providers.py` | Extinderea aceleiași interfețe la fixtures/odds/formă/vreme/standings — un adaptor per (provider, tip de date), nu per provider monolitic |
| **Scheduler** | **DA — deja generic** | `sync_orchestrator.py` (`SyncOrchestrator`, `SyncTask`, R4.1) | Nimic structural — funcționează neschimbat pentru orice provider nou, confirmat: niciun cod nu hardcodează „apifootball" |
| **Request Manager** | **DA — deja generic** | `request_manager.py` (R4.1) | Nimic — indexat deja după `provider: str` |
| **Rate Limit Manager** | **DA — deja generic** | `rate_limit_manager.py` (R4.1) | Nimic structural — dar azi citește doar header-ele oficiale API-Football; alți provideri pot avea alt format de header (de verificat per provider, la migrare) |
| **Coverage Manager** | Parțial — Coverage Cache (`coverage_cache.py`, migrare 016) e specific schemei oficiale API-Football (`coverage` din `/leagues`) | `coverage_cache.py` | **Generalizare reală necesară** — „coverage" înseamnă lucruri diferite per provider (API-Football: per ligă+sezon; football-data: per nivel de abonament; Weather: practic universal, fără restricție reală) — nu toți providerii au un concept de coverage relevant. Recomandare: capacitate OPȚIONALĂ a adaptorului, nu obligatorie |
| **Data Normalizer** | Parțial — `Injury`/`CoachInfo` (dataclass-uri normalizate, `football_providers.py:46-64`) există doar pentru API-Football | `football_providers.py` | Dataclass-uri echivalente pentru `Fixture`/`OddsSnapshot`/`FormEntry`/`WeatherSnapshot`/`Standing` — tipar deja dovedit, doar neextins |
| **Data Validator** | **NU — nu există ca pas distinct** — parsarea defensivă (`.get()`, log warning la formă neașteptată) e împrăștiată în fiecare `_normalize_*` | Peste tot, informal | Formalizare: un pas explicit, separat de normalizare, care validează plaja de valori (ex. cotă > 1.0, dată validă, coordonate oraș valide) ÎNAINTE de persistare — nu doar formă de payload |
| **Persistence Layer** | Parțial — funcții dedicate în `supabase_client.py` per tip de date (`set_cached_response`, `set_league_coverage`, viitorul `set_team_health`) | `supabase_client.py` | Consistență de tipar — fiecare tip nou de date capătă owner unic de scriere, exact disciplina ADR-036, nu inventată acum, doar aplicată sistematic |
| **Sync Jobs** | **DA — `SyncTask`, deja generic** | `sync_orchestrator.py` | Nimic — dar azi registrul e gol (niciun task real înregistrat) |
| **Monitoring** | Parțial — `provider_health.py` + `provider_metrics_source_supabase.py` agregă apeluri/erori/latență per provider | existent | Lipsesc: ultima oră de sync reușit per (provider, tip de date), alertă de „date învechite" dincolo de erori HTTP |

**Concluzie**: 4 din 9 componente cerute (Scheduler, Request Manager, Rate Limit Manager, Sync Jobs) sunt deja construite generic în R4.1 și NU necesită nicio schimbare pentru a servi orice provider nou. Coverage Manager și Data Normalizer au un precedent dovedit (API-Football), de extins. Data Validator e componenta cu adevărat nouă.

---

## 3. Adaptoare de provider — schiță (fără cod)

Interfață comună propusă, extinzând tiparul deja existent (`FootballDataProvider`):

```
SyncAdapter (protocol/ABC):
    provider_id: str
    fetch(params) -> raw_payload | None          # unicul punct de apel HTTP
    normalize(raw_payload) -> list[CanonicalRecord]
    validate(records) -> list[CanonicalRecord]    # filtrează/respinge, nu aruncă excepție
    persist(records) -> bool                       # scrie in Supabase, owner unic per tip
    coverage_check(context) -> bool                # opțional — default True
```

Per provider, ce adaptor ar rezulta (design, nu implementare):

| Provider | Adaptor(i) | Note |
|---|---|---|
| API-Football | `ApiFootballHealthAdapter` (injuries+coaches) | Deja proiectat conceptual (turul anterior); `fetch`/`normalize` există deja în `football_providers.py`, doar `persist` lipsește (scrie azi în cache, nu în Supabase canonic) |
| Odds API | `OddsApiFallbackAdapter` (H2H+formă, NU cotele — acelea rămân pe calea Frozen existentă, neatinsă) | Scope limitat explicit — nu se atinge `odds_persistence_service.py` |
| Weather API | `WeatherForecastAdapter` | Cel mai simplu — fără coverage, fără normalizare complexă |
| football-data.org | `FootballDataFormAdapter` | Cel mai curat azi (deja folosea `key_manager` corect) — cel mai ieftin de migrat |
| FreeLF | `FreeLfFixtureAdapter` + `FreeLfFormAdapter` (separate — roluri diferite, discovery vs. formă) | Necesită atenție — sursă primară, nu doar fallback |
| ESPN | `EspnFixtureAdapter` | Fallback pur, risc mic |
| TheSportsDB | `TsdbStatsAdapter` + `TsdbEloAdapter` | ELO pentru naționale e o cale critică (singura sursă reală) — migrare cu grijă suplimentară |

Niciunul dintre acestea nu se scrie acum — tabelul de mai sus e input pentru roadmap (§6), nu cod.

---

## 4. Politică de sincronizare per provider (cadență)

Extinde direct modelul deja aprobat în ADR-038 (Reference/Historical/Dynamic/Live), aplicat acum per provider:

| Provider / date | Domeniu | Cadență propusă | Motivare |
|---|---|---|---|
| Kaggle | Historical | O dată (deja făcut) | Date istorice, nu se schimbă |
| API-Football injuries/coaches | Dynamic | 4h/72h (deja decis, ADR-038) | Cadență oficială confirmată |
| football-data/ESPN/TSDB (formă/stats fallback) | Dynamic, prioritate joasă | Zilnic | Date lent-schimbătoare, folosite doar ca fallback |
| FreeLF (descoperire meciuri) | **Reference/Bootstrap, dar frecvent** | La câteva ore | Meciuri noi apar continuu — cadență zilnică ar întârzia descoperirea |
| Weather | Dynamic, fereastră scurtă | De câteva ori/zi, doar pentru meciuri în următoarele 48h | Prognoza se schimbă, dar nu are sens sincronizată cu săptămâni înainte |
| Odds API (fallback H2H/formă) | Dynamic, prioritate foarte joasă | Zilnic | Rar sursa reală (Odds API răspunde deja la pasul 1 al descoperirii, nu la fallback separat) |
| Odds API (cote pre-meci) | **Deja gestionat separat** | Neschimbat (`odds_persistence_service.py`) | Nu face parte din acest roadmap |

**Tensiune numită explicit, neschimbată față de discuția anterioară**: descoperirea de meciuri (FreeLF/Odds/football-data/ESPN, pasul 1-4 din `get_matches_for_week`) cere o cadență mult mai deasă decât injuries/coaches — altfel Oracle Engine ar „vedea" meciuri noi cu întârziere reală. Asta rămâne cea mai mare piesă de proiectat cu grijă, nu de subestimat.

---

## 5. Model de persistare Supabase

**Recomandare de design**: tabele specifice per tip de date, NU un depozit generic key-value. Motivare, nu presupunere — proiectul are deja acest precedent, consecvent: `match_history` (66 coloane tipizate), `champion_health_evaluations`, `api_football_league_coverage` — niciodată un „blob JSON generic". Un depozit generic ar contrazice disciplina de ownership deja aplicată (ADR-036) și ar face imposibilă validarea la nivel de schemă DB (CHECK constraints, tipuri corecte).

Tabele noi necesare (design, nicio migrare pregătită încă — se face per pas de migrare, §6):

| Tabelă propusă | Scop | Owner de scriere |
|---|---|---|
| `team_health_snapshot` | Injuries+coaches curente per echipă (API-Football) | Sync Layer, exclusiv |
| `scheduled_fixtures` | Meciuri viitoare descoperite (FreeLF/Odds/football-data/ESPN) | Sync Layer, exclusiv |
| `weather_forecast_cache` | Prognoză per (oraș, dată) — mai aproape de cache decât de „date canonice ML", TTL scurt | Sync Layer, exclusiv |

**Ce NU se construiește din nou** — deja acoperit:
- Formă/ELO/H2H → deja `match_history` (ADR-035 D1-D3), nu se duplică.
- Cote pre-meci → deja `odds_history` (Frozen, ADR-005/006), nu se atinge.
- Coverage API-Football → deja `api_football_league_coverage` (migrare 016).

---

## 6. Strategie de migrare provider cu provider

Secvențiere pe risc crescător, exact disciplina deja aplicată la D1-D4 din ADR-035 (un pas mic, testat, verificat live, ÎNAINTE de următorul):

1. **API-Football** (injuries/coaches) — deja proiectat (turul anterior), cel mai avansat, cel mai bine înțeles. Prim pas real.
2. **football-data.org** (formă/standings fallback) — cel mai curat azi, risc minim, fallback rar folosit.
3. **ESPN** (descoperire fallback) — fallback pur, risc mic.
4. **TheSportsDB** (stats + ELO naționale) — atenție suplimentară la ELO (singura sursă reală pentru naționale — o eroare aici ar lăsa naționale fără ELO deloc, nu doar „date vechi").
5. **Weather** — nou tip de tabelă (cache prognoză), independent de restul.
6. **FreeLF** (formă/standings fallback, NU descoperirea) — separat de rolul de descoperire, migrat întâi ca fallback simplu.
7. **Odds API** (fallback H2H/formă, NU cotele) — ultimul dintre fallback-uri, cel mai rar folosit real.
8. **Descoperirea meciurilor** (FreeLF+Odds+football-data+ESPN împreună, `get_matches_for_week`) — **etapă separată, cea mai mare**, după ce toate fallback-urile individuale sunt deja migrate — schimbă o cale folosită de UI, nu doar de predicție.

Fiecare pas: criteriu de succes verificabil (date complete în Supabase pentru un eșantion cunoscut), fail-before/pass-after, aprobare explicită înainte de commit — identic tiparului deja stabilit.

---

## 7. Vezi ADR-039

`docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md`

---

## 8. Roadmap de implementare (propus, neaprobat, fără cod)

1. Formalizare `SyncAdapter` (interfață) — generalizare a `FootballDataProvider`, cu `validate()` ca pas nou explicit.
2. Migrare API-Football (§6, pasul 1) — primul adaptor real, folosind infrastructura deja construită în R4.1.
3. Migrare football-data.org + ESPN (§6, pașii 2-3) — risc minim, validează tiparul pe cazuri simple.
4. Migrare TheSportsDB (§6, pasul 4) — cu verificare specială pentru ELO naționale.
5. `weather_forecast_cache` + adaptor Weather (§6, pasul 5).
6. Migrare FreeLF formă/standings + Odds API fallback (§6, pașii 6-7).
7. **Descoperirea meciurilor** (§6, pasul 8) — etapă proprie, plan separat, aprobare separată.
8. Doar după toate cele de mai sus: eliminarea completă a `self.api`/`self.apifootball` din `oracle_engine.py` — Oracle Engine citește exclusiv Supabase.

Fiecare pas urmează disciplina deja stabilită: design → implementare → teste → audit → aprobare explicită → commit → confirmare punct de restaurare.

---

## Addendum — două concepte verificate explicit (consolidare, nu redesign)

### Football Data Warehouse

Deja acoperit implicit: fluxul `Provider → Sync Adapter → Normalize → Validate → Persist → Supabase` (§3 de mai sus) + regula „citire exclusivă din Supabase" (ADR-039, Context + Principiul 1). Nu lipsea capacitatea, lipsea numele — adăugat acum ca Principiul 6 din ADR-039, fără nicio schimbare structurală.

### Canonical Entity Resolution

**Nu lipsește — există deja, mai extins decât ar sugera o primă privire, sub o formă diferită de cea intuitivă (nume normalizat, nu ID numeric + tabelă de crosswalk):**

| Entitate | Mecanism canonic existent | Status |
|---|---|---|
| Match | `ADR-024` (Accepted) + `ADR-025` (Approved/Architecture Frozen) — cheie `(home normalizat, away normalizat, kickoff_date)`, fără ligă în cheie | Frozen, cu strategie de migrare fazată deja definită acolo |
| Team | `mappings.TEAM_ALIASES`/`normalize_team_name()` (272 intrări) | Funcțional, cu un gol de wiring documentat separat (`TEAM_IDENTITY_AUDIT.md` — unii writeri de sincronizare zilnică nu apelează normalizarea la scriere, 137 echipe afectate) |
| Competition | `mappings.LEAGUE_PROVIDERS` — cheie = nume canonic, `provider_ids: dict[str, ...]` per provider (confirmat prin cod, `mappings.py:367-371`) | Funcțional, deja folosit ca precedent pentru Coverage Cache (ADR-038) |

**Notă importantă, de citit înainte de a proiecta orice adaptor nou**: `ADR-025` a comparat explicit varianta „tabelă de crosswalk (N ID-uri de provider → 1 ID canonic)" — exact tiparul din exemplul cerut de misiune — și a **respins-o**, cu motivare documentată (cost de mentenanță mai mare, risc de desincronizare deja materializat o dată în proiect, `mappings.py`). Orice Sync Adapter nou (§3) trebuie să reutilizeze cheile naturale normalizate deja existente, nu să reintroducă o tabelă de crosswalk de ID-uri — asta ar contrazice o decizie deja înghețată, nu ar completa un gol real.

**Concluzie**: ambele concepte verificate. Primul a necesitat doar o denumire (adăugată). Al doilea exista deja, mai matur decât presupunerea inițială — integrat acum prin referințe explicite în ADR-039 (Principiul 7 + Referințe), fără nicio schimbare de arhitectură, roadmap sau scope.
