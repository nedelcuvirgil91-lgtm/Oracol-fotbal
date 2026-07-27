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
| **Odds API** | (a) cote pre-meci — sursă PRIMARĂ de descoperire meciuri + cote (`get_matches_for_week`, pasul 1, `oracle_api.py:1189-1192`); (b) H2H+formă — **migrate, R-Sync-6**, sursă unică `odds_api_recent_results` | Fixtures+odds (a), meciuri recente (b) | Env var (`ODDS_API_KEY`), migrat R4.1 | **(a) DA — deja Frozen** (`services/odds_persistence_service.py`, ADR-005/006); **(b) NU — FINALIZAT, R-Sync-6** | (a) deja sync-first prin design; (b) Sync Layer, `sync/sync_odds_recent_results.py`; descoperirea (pasul 1) rămâne live, R-Sync-7 |
| **Weather API** | Prognoză oraș+dată pentru penalizare xG (`get_weather`, `oracle_api.py:1104`, apelat necondiționat, `oracle_engine.py:1286`) | Vreme (prognoză, nu istoric) | Env var (`WEATHER_API_KEY`), migrat R4.1 | NU | Apel live, necondiționat — nu e „fallback", e singura cale azi |
| **football-data.org** | Fallback formă/standings (`get_standings_form`, `oracle_api.py:725`), fallback descoperire meciuri (`_fetch_matches_fd`, pasul 3 din `get_matches_for_week`) | Standings, fixtures | Env var (`FOOTBALL_DATA_KEY`), migrat R4.1 — **singurul provider deja bine practicat** înainte de R4.1 (folosea `key_manager` corect, fără duplicare) | NU | Apel live, fallback ADR-035 |
| **FreeLF (Free Live Football)** | **Sursă PRIMARĂ** pentru descoperirea meciurilor săptămânii (pasul 2, `oracle_api.py:1194-1201`) — rămâne live, R-Sync-7; H2H (`self.api.get_h2h`, event_id-based) — cuplată la discovery, R-Sync-8; formă/standings (`get_team_form_freelf`/`get_freelf_standings`) — **migrate, FINALIZAT, R-Sync-6**, `freelf_team_form_snapshot` | Fixtures (primar), H2H, formă/standings | Env var (`RAPIDAPI_KEY_FREELIVEFOOTBALL`), migrat R4.1, **integrată în Request Manager/Rate Limit Manager, R-Sync-6** (§6d) | Discovery: DA; H2H: DA (deferred, §6d); **formă/standings: NU — FINALIZAT** | Cel mai greu folosit provider structural — nu doar fallback, sursă primară de descoperire |
| **ESPN** | Fallback descoperire meciuri (pasul 4, `_fetch_matches_espn`, `oracle_api.py:732`) | Fixtures | N/A — provider public, fără cheie (nu apare în `key_manager.PROVIDERS`) | NU | Apel live, fallback ADR-035 |
| **TheSportsDB** | Fallback descoperire meciuri (pasul 5, `_fetch_matches_tsdb`, `oracle_api.py:830`), team stats (`get_team_stats`, `oracle_api.py:926`) — **team stats cuplat structural la `team_id` `tsdb_`-prefixat, produs DOAR de discovery** (dovadă §6c, R-Sync-4) | Fixtures, stats | N/A — provider public, fără cheie | NU | Apel live, fallback ADR-035 |
| **eloratings.net** [**ADĂUGAT, §6c** — corectare a unei clasificări greșite moștenite din auditul inițial, care îl confunda cu TheSportsDB] | ELO fallback pentru echipele naționale (`get_elo_rating`/`_fetch_elo_ratings`, `oracle_api.py:964-1004`) — scrape HTML, provider distinct, nu API-ul TheSportsDB | ELO | N/A — provider public, fără cheie, scrape HTML (nu JSON API) | NU | Apel live, fallback ADR-035; singura sursă reală pentru naționale fără meciuri de club sincronizate |
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
| Odds API | `OddsApiRecentResultsAdapter` — **FINALIZAT, R-Sync-6** (H2H+formă unificate, dintr-un singur tabel canonic `odds_api_recent_results`, opțiunea A, §6d; NU cotele — acelea rămân pe calea Frozen existentă, neatinsă) | Scope limitat explicit — nu se atinge `odds_persistence_service.py` |
| Weather API | `WeatherForecastAdapter` | Cel mai simplu — fără coverage, fără normalizare complexă |
| football-data.org | `FootballDataFormAdapter` | Cel mai curat azi (deja folosea `key_manager` corect) — cel mai ieftin de migrat |
| FreeLF | `FreeLfFormAdapter` — **FINALIZAT, R-Sync-6** (formă+standings, fuzionate); `FreeLfFixtureAdapter` (discovery, R-Sync-7) și H2H (event_id-based, R-Sync-8, §6d) rămân separate | Necesită atenție — sursă primară, nu doar fallback |
| ESPN | `EspnFixtureAdapter` | Fallback pur, risc mic |
| TheSportsDB | `TsdbStatsAdapter` (team stats) | **AMÂNAT explicit, §6c** — cuplat structural la `team_id` produs de Match Discovery; migrare abia după Universal Match Discovery Layer |
| eloratings.net [**corectat, §6c** — nu e TheSportsDB] | `EloRatingsAdapter` | Tipar identic R-Sync-3 (un fetch → toate echipele naționale dintr-un scrape) — zero dependență de `team_id`/discovery, migrabil independent, acum |

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

Secvențiere pe risc crescător, exact disciplina deja aplicată la D1-D4 din ADR-035 (un pas mic, testat, verificat live, ÎNAINTE de următorul). **Corectată post-R-Sync-2 — vezi §6b — și din nou post-R-Sync-3 — vezi §6c — pentru dovada exactă a fiecărei corecții, nu doar concluzia.**

1. **API-Football** (injuries/coaches) — ✅ **FINALIZAT, R-Sync-2** (`team_health_snapshot`, migrare 017, commit `0eb0469`).
2. **football-data.org** — ✅ **FINALIZAT, R-Sync-3** — **DOAR** `get_standings_form()`/`get_team_form_fd()` (formă/standings). **Exclus explicit**: `_fetch_matches_fd()` (fixtures) — mutat la pasul 6 (Universal Match Discovery Layer).
3. **eloratings.net** (ELO naționale) — **corectat, §6c**: NU e TheSportsDB (eroare de clasificare moștenită, corectată prin dovadă de cod) — provider distinct (scrape HTML). Migrare curată, tipar identic R-Sync-3 (un fetch → toate echipele naționale, multe înregistrări canonice per apel), zero dependență de `team_id`/discovery.
4. **Weather** — nou tip de tabelă (cache prognoză), independent de restul.
5. **FreeLF** (formă/standings) + **Odds API** (H2H/formă) — **corectat, §6d**: FreeLF H2H (event_id-based) exclus explicit — cuplat la discovery, mutat la pasul 7. Odds API H2H/formă unificate într-un singur tabel canonic (`odds_api_recent_results`). **Exclus explicit, pentru amândoi**: orice rol de descoperire — `_fetch_freelf_matches()` (FreeLF) și `_fetch_events_odds_api()` (Odds API, pasul 1 din `get_matches_for_week` — distinct de `_fetch_market()`/`_fetch_odds()`, calea Frozen de persistare a cotelor, ADR-005/006, neatinsă) — mutate la pasul 6.
6. **Universal Match Discovery Layer** (redefinit, §6b) — **TOȚI** providerii de fixtures, într-un singur pas: FreeLF, Odds API (events/discovery), football-data.org (fixtures), ESPN, TheSportsDB (fixtures), **și API-Football (fixtures)** — niciun provider tratat separat sau privilegiat. Etapă proprie — schimbă o cale folosită și de UI, nu doar de predicție.
7. **Post-Discovery Cleanup** — **redefinit, §6d**: TheSportsDB team stats (mutat, §6c) **+ FreeLF H2H** (mutat, §6d), DOAR după pasul 6: ambele cer un identificator (`team_id` `tsdb_`-prefixat / `_freelf_event_id`) produs azi DOAR de discovery; migrarea izolată, înainte de Universal Match Discovery Layer, ar fi cerut fie duplicarea logicii de rezoluție de ID, fie o abstracție nouă de identity resolution, nedorită (vezi §6c, Decizia 4). Abia după pasul 6, `scheduled_fixtures` conține identificatori stabili, deja scriși, pe care Sync Layer îi poate citi direct.
8. Doar după pasul 7: eliminarea finală a `self.api` din `oracle_engine.py` — Oracle Engine citește exclusiv Supabase, pentru orice tip de date, de la orice provider.

Fiecare pas: criteriu de succes verificabil (date complete în Supabase pentru un eșantion cunoscut), fail-before/pass-after, aprobare explicită înainte de commit — identic tiparului deja stabilit.

---

## 6b. Corecție de roadmap, post-R-Sync-2 (evidență, nu doar concluzie)

Două constatări, ambele verificate direct în cod, nu presupuse, în urma unui audit scurt cerut explicit înainte de a începe pasul 2 (football-data.org + ESPN):

**1. ESPN nu are nicio responsabilitate în afara descoperirii de meciuri.** Verificat exhaustiv (`grep` pe tot `oracle_api.py`): o singură funcție, `_fetch_matches_espn()` (`oracle_api.py:732`), niciun rol de formă/stats/standings. Migrarea lui izolat, înaintea Universal Match Discovery Layer, ar fi însemnat fie reconstruirea acelei bucăți la pasul 6 (muncă dublată), fie o migrare incompletă (Oracle Engine tot ar depinde de restul cascadei). **Concluzie**: ESPN elimin din pasul „football-data.org + ESPN" — mutat integral la pasul 6.

**2. API-Football fixtures NU e un caz separat — e pasul 6 din exact aceeași funcție** (`get_matches_for_week()`, `oracle_api.py:1239-1253`) pe care Universal Match Discovery Layer o țintește deja pentru FreeLF/Odds/football-data/ESPN/TheSportsDB (pașii 1-5 din aceeași funcție). R-Sync-2 a eliminat DOAR calea de injuries/coaches (`self.apifootball` din `oracle_engine.py`) — calea de fixtures a lui API-Football (`_fetch_matches_api_football()`, via `self.api`) a rămas complet neatinsă, exact ca toate celelalte fallback-uri de descoperire. Tratarea ei ca „deja rezolvată" ar fi lăsat o excepție reală față de principiul 1 din ADR-039 („niciun alt modul... nu apelează direct sau indirect vreun adaptor de provider") — API-Football ar fi rămas singurul provider cu o cale de bypass, doar pentru că o altă parte a lui (injuries/coaches) migrase deja. **Concluzie**: API-Football (fixtures) intră explicit în Universal Match Discovery Layer, ca oricare alt provider — „încă un provider din ecosistem, nu unul privilegiat".

**Notă legată de Coverage Cache** (`api_football_league_coverage`, migrare 016, 0 rânduri azi): coverage per ligă+sezon pentru fixtures e exact cazul de utilizare pentru care schema aceea a fost proiectată. Universal Match Discovery Layer (pasul 6) e locul natural unde ar putea începe, în sfârșit, să fie populată — semnalat aici ca observație pentru decizia de la momentul acelui pas, nu decis acum.

---

## 6c. Corecție de roadmap, post-R-Sync-3 (evidență, nu doar concluzie)

Cerută explicit de proprietarul produsului înainte de a începe R-Sync-4 (auditul obligatoriu pre-implementare — vezi §8, nota de proces). Două constatări, ambele verificate direct în cod, nu presupuse.

**1. ELO pentru naționale NU e TheSportsDB.** Auditul §1 original (rândul „TheSportsDB") grupa greșit trei responsabilități distincte sub un singur provider. Verificare directă:
```python
# oracle_api.py:61
ELO_URL = "https://www.eloratings.net"          # NU thesportsdb.com

# oracle_api.py:964-1004
def _fetch_elo_ratings(self) -> dict[str, int]:
    ...
    r = self._s.get(ELO_URL, ...)               # scrape HTML (BeautifulSoup), nu apel JSON API TheSportsDB
```
`ELO_RATINGS_FALLBACK` (`mappings.py:623`) e un dicționar static hardcodat, nu date derivate din TheSportsDB. **eloratings.net e un provider complet separat** — roadmap-ul (§6, pasul 3 vechi) și auditul §1 au moștenit o eroare de clasificare din primul draft. Corectat acum: rând propriu în §1, adaptor propriu în §3, pas propriu în §6.

**2. TheSportsDB team stats e cuplat structural, demonstrat, la Match Discovery.**
```python
# oracle_engine.py:948 (Level 4, _build_profile())
if not stats and team_id and team_id.startswith("tsdb_"):
    tsdb_stats = self.api.get_team_stats(team_id, league)

# oracle_api.py:926
def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
    if team_id and team_id.startswith("tsdb_"):
        return self.get_team_last_events_tsdb(team_id)   # cere ID numeric TSDB
    return []
```
`team_id` vine din `match.get("home_team_id","")`/`away_team_id` (`oracle_engine.py:1284-1285`), populat cu prefixul `tsdb_` DOAR dacă meciul a fost descoperit prin `_fetch_matches_tsdb()` (pasul 5 din `get_matches_for_week()`). Singura alternativă azi e `TSDB_TEAM_IDS` (`mappings.py:559`) — **deliberat incomplet, manual, doar 5 echipe românești**, verificate live una câte una prin `searchteams.php` — cu un comentariu explicit în cod împotriva generalizării automate („`lookup_all_teams.php` s-a dovedit nefiabil... NU se generalizează automat").

**Decizie explicită, proprietar produs**: nu se introduce o rezoluție automată de identitate prin `searchteams.php` acum — ar fi o abstracție nouă de identity resolution, nejustificată de o a doua implementare reală, și ar contrazice disciplina deja înghețată (`ADR-024`/`ADR-025`, identitate canonică doar prin nume normalizat, crosswalk de ID-uri explicit respins). Dacă va exista vreodată un resolver universal de identitate, capătă propriul ADR — nu se introduce implicit, în trecere, la migrarea unui singur provider.

**Concluzie**: TheSportsDB team stats **rămâne pe calea live existentă**, neschimbat, mutat ca pas propriu DOAR după Universal Match Discovery Layer (§6, pasul 6) — moment în care `scheduled_fixtures` va conține deja ID-uri TSDB stabile, eliminând dependența fără nicio abstracție nouă.

**Notă adăugată la închiderea R-Sync-4** (aprobare explicită proprietar produs): `EloRatingsAdapter`/`get_national_elo_ratings_raw()` fuzionează scrape-ul live cu `ELO_RATINGS_FALLBACK` la persistare, ca să evite o regresie de acoperire față de comportamentul pre-migrare (vezi `mappings.py`, comentariul de la definiția dicționarului, și ADR-039 §Consecințe). **Explicit TEMPORAR** — nu o decizie arhitecturală permanentă. Se elimină (sau se reduce strict) când sincronizarea live confirmă acoperire completă.

---

## 6d. Corecție de roadmap, R-Sync-6 (evidență, nu doar concluzie)

Cerută de disciplina deja stabilită (audit complet înainte de cod). Patru constatări.

**1. FreeLF H2H (`get_h2h`, event_id-based) e cuplată structural la Match Discovery — exact tiparul TSDB team stats (§6c).**
```python
# oracle_engine.py — _build_h2h()
event_id = match.get("_freelf_event_id")
if event_id:
    freelf_h2h = self.api.get_h2h(int(event_id), home_name, away_name)
```
`_freelf_event_id` există DOAR dacă meciul a fost descoperit prin `_fetch_freelf_matches()` (FreeLF, pasul 2 din `get_matches_for_week()`). Fără endpoint alternativ de căutare per pereche de echipe. **Decizie, proprietar produs**: mutată alături de TheSportsDB team stats — R-Sync-8 devine „Post-Discovery Cleanup" (TSDB team stats + FreeLF H2H), ambele deblocate abia după R-Sync-7. `self.api.get_h2h()` rămâne, deliberat, live — verificat prin gardă AST pozitivă (`test_oracle_engine_still_calls_freelf_h2h_deliberately`).

**2. FreeLF standings/formă (`get_freelf_standings`/`get_team_form_freelf`) NU au dependență de discovery** — `team_id`-ul folosit de fostul Level 1 venea din fostul Level 0 (`season_entry`, ACELAȘI răspuns standings), nu din meciul descoperit. Migrabile acum — R-Sync-6 le include, redus la un singur adaptor (`FreeLfFormAdapter`), fuzionând Level 0+1 într-un singur rând persistat per echipă.

**3. Odds API H2H/formă — o singură sursă canonică, decizie explicită proprietar produs (opțiunea A).** `_fetch_scores_odds_api(sport_key, days_back)` era deja folosită, identic, atât pentru `get_team_recent_form()` (formă) cât și pentru fallback-ul H2H din `_build_h2h()` — un singur payload, două derivări. Tabelă nouă unică: `odds_api_recent_results`, cheie `(home_team_canonical, away_team_canonical, kickoff_date)` — reutilizează EXACT forma cheii naturale de Match deja Frozen (ADR-024/025), nu introduce o identitate paralelă. `database/queries.py` capătă două funcții de citire (`get_team_recent_form_oddsapi`/`get_h2h_from_odds_recent`) care derivă din ACELAȘI tabel — zero duplicare a logicii de fetch/normalizare, exact principiul deja aplicat la `xg_penalty` (R-Sync-5).

**4. FreeLF ocolea complet infrastructura R4.1 (Request Manager/Rate Limit Manager) — reparat înainte de orice migrare de date.** Confirmat: `_free_lf_get()` (`oracle_api.py`) apela direct `self._get()`, fără RAM cache (L0), fără dedup in-flight, fără gating de buget real din header-e — singurul provider din `oracle_api.py` cu acest gol (API-Football fusese deja integrat, R4.1). Decizie explicită, proprietar produs: „Nu accept provideri care ocolesc infrastructura generică introdusă în R4.1". Reparat: `_free_lf_get()` trece acum prin `RequestManager` (RAM L0 + dedup in-flight + `should_request()`), iar `_get()` a fost extins aditiv (`return_headers: bool = False`, implicit neschimbat pentru toți ceilalți apelanți) ca să poată alimenta `RateLimitManager.record_response_headers()`. Format real de header necunoscut/neverificat live pentru FreeLF (RapidAPI) — sigur oricum, `RateLimitManager` e deja fail-open pentru header-e nerecunoscute (design existent, R4.1). Testat explicit, 8 teste dedicate (`tests/test_oracle_api_freelf_request_manager.py`).

**Constatare separată, nu o corecție de roadmap ci un bug preexistent găsit la audit**: `get_team_form_freelf()` returnează întotdeauna `[]` în producție — `get_freelf_standings()` nu copiază niciodată un câmp `"form"` din răspunsul brut FreeLF în dicționarele sale normalizate (verificat prin citire de cod, comentariul din `oracle_api.py:519` pretinde că răspunsul brut ar avea un asemenea câmp, dar transformarea îl pierde). Decizie explicită, proprietar produs: **portă comportamentul actual fidel** (coloana `form` rămâne goală în `freelf_team_form_snapshot`), NU se ghicește numele câmpului real fără verificare live (Regula „Verificat, nu presupus"). Task separat, neînceput: **R-Sync-6a — verificare live payload FreeLF standings + reparare `get_freelf_standings()`**.

---

## 6e. R-Sync-7a — Universal Match Discovery Layer, fundația (evidență, nu doar concluzie)

Etapă separată, aprobată explicit ca sub-pas al R-Sync-7 (§6b), împărțită în 7a/7b/7c. **R-Sync-7a construiește fundația — tabela + adaptorii + politica de merge + sincronizare paralelă — fără să modifice `oracle_engine.py`.** Oracle Engine continuă să citească exclusiv `get_matches_for_week()` (calea veche, live) până la R-Sync-7b.

**Motivația (§7, auditul R-Sync-7 original)**: `get_matches_for_week()` (`oracle_api.py`) agregă 6 provideri prin `_add()`, care deduplică pe `match_key()` cu semantică **first-provider-wins** — dovedit prin simulare live (`python3` cu `match_key()` real), nu presupus: al doilea provider care raportează același meci își pierde definitiv toți identificatorii proprii (`_freelf_event_id`, `tsdb_*_id`, etc.). Aceasta e cauza structurală exactă care blochează R-Sync-8 (FreeLF H2H, TSDB team stats) — ambele au nevoie de un `team_id`/`event_id` care poate fi „pierdut" azi dacă alt provider a raportat primul.

**Decizie, proprietar produs**: MERGE, nu first-wins — o singură identitate canonică (`(home_team_canonical, away_team_canonical, kickoff_date)`, cheia naturală de Match deja Frozen ADR-024/025), N identificatori de provider, niciun identificator existent nu poate fi șters de un provider ulterior.

**Schema — `scheduled_fixtures` (migrare 023)**: identitate (`home_team_canonical`/`away_team_canonical`/`kickoff_date`, UNIQUE); câmpuri guvernate (`league`, `kickoff_utc`, `venue_city`, `status`) + `field_provenance` (JSONB, urmărește ce provider deține azi valoarea fiecărui câmp guvernat); 14 coloane deținute de provideri (2-3 per provider: `freelf_event_id`/`freelf_home_team_id`/`freelf_away_team_id`/`freelf_coverage_level`, `odds_api_event_id`/`odds_api_sport_key`, `apifootball_fixture_id`/`apifootball_home_team_id`/`apifootball_away_team_id`, `tsdb_home_team_id`/`tsdb_away_team_id`, `fd_home_team_id`/`fd_away_team_id`, `espn_home_team_id`/`espn_away_team_id`); `source_mask` (JSONB, ce provideri au contribuit) + `merge_count` (INTEGER) — utile pentru debugging/audit pe termen lung, cerute explicit de proprietarul produsului, fără necesitate funcțională imediată.

**FixtureMergePolicy — implementată integral în RPC `upsert_scheduled_fixture_merge` (nu read-modify-write din Python, decizie explicită proprietar produs), field-level, nu row-level**:
- Coloanele deținute de provider: `COALESCE(existing, new)` — owner unic per coloană, niciodată suprascris, niciodată golit de alt provider.
- `status`: last-write-wins (singurul câmp care se schimbă legitim în timp).
- `league`/`venue_city`/`kickoff_utc`: guvernate de **SourcePriority** — ranguri fixe per provider, comparate cu `field_provenance` stocat, NU cu ordinea de execuție a sync-ului (decizie explicită proprietar produs: „ordinea în care rulează providerii este o decizie tehnică, nu o măsură a calității datelor" — SourcePriority întâi, apoi MergePolicy, niciodată invers). Doar o sursă strict mai bine clasată poate suprascrie; egalitate sau rang mai slab nu suprascrie niciodată.
  - `league`: freelf=espn=tsdb=apifootball=oddsapi=1 (toate canonice prin construcție) > footballdata=2 — găsit la audit: `_fetch_matches_fd()` nu apelează niciodată `normalize_league_name()` (`mappings.py:829`, confirmat prin grep — apelată doar din scripturi offline de import istoric, niciodată din calea live `oracle_api.py`), singurul provider cu acest gol.
  - `venue_city`: freelf=1 > espn=2 > apifootball=3 > footballdata=4 (`area.name` e țară, nu oraș — găsit la R-Sync-5) > tsdb/oddsapi=5 (nu furnizează niciodată venue_city; TSDB reparat la sursă în R-Sync-5, `strVenue` nu mai populează `venue_city`).
  - `kickoff_utc`: **fără ierarhie de calitate** — niciun provider nu are un defect demonstrat, spre deosebire de `league`/`venue_city`. Decizie explicită, conservatoare (proprietar produs): tie-break pur determinist, arbitrar, doar pentru reproductibilitate: apifootball(1) < espn(2) < footballdata(3) < freelf(4) < oddsapi(5) < tsdb(6). Documentat verbatim în comentariul RPC-ului: „SourcePriority reprezintă ownership-ul sau calitatea demonstrată a câmpului. Pentru câmpurile fără dovezi obiective privind calitatea (ex. kickoff_utc), sistemul nu stabilește o ierarhie semantică între provideri; se aplică doar un tie-break determinist pentru a garanta reproductibilitatea."
- Demo Mode (`_generate_demo_matches()`) exclus complet din persistare — aprobat explicit, 100%.

**Validare live pe producție (branch Supabase indisponibil — plan curent nu include Branching, `PaymentRequiredException`; alternativă aprobată explicit: testare directă pe producție cu date sintetice `ZZTEST_*`, cleanup explicit, același rigor de logging cerut inițial pentru branch)**:

| # | Scenariu | Rezultat |
|---|---|---|
| 1 | Insert meci nou | PASS |
| 2 | Merge — al doilea provider adaugă un ID propriu | PASS |
| 3 | Merge — ordine inversă de sosire a providerilor | PASS |
| 4 | Precedență `venue_city` (SourcePriority) | PASS |
| 5 | Precedență `league` (SourcePriority) | PASS |
| 6 | No-downgrade — sursă cu rang mai slab nu suprascrie | PASS |
| 7 | Idempotență — reapelare cu aceleași date | PASS |
| 8 | Concurență minimă | Netestat sub concurență REALĂ (limitare unealtă — execuție SQL strict secvențială) — dar investigația declanșată de acest scenariu a găsit un bug real (vezi mai jos) |

7 rânduri inserate în total (S1-S7) + 1 rând suplimentar de regresie (S9, după fix). Toate verificările PASS. Cleanup: `DELETE FROM scheduled_fixtures WHERE home_team_canonical LIKE 'ZZTEST_%' OR away_team_canonical LIKE 'ZZTEST_%'`, confirmat prin `SELECT count(*) FROM scheduled_fixtures` → `0` (tabelă complet goală, inclusiv de date reale, întrucât niciun sync real nu rulase încă pe producție).

**Bug real găsit prin validare live, nu prin trace manual** — cel mai valoros rezultat al etapei: ramura INSERT din RPC nu avea `ON CONFLICT`, expusă la o excepție necontrolată de constrângere unică dacă doi provideri descoperă concurent, pentru prima dată, același meci nou. **Validation note: During live validation a race condition was discovered in the initial INSERT path. The RPC now uses INSERT ... ON CONFLICT DO NOTHING RETURNING id followed by a merge fallback, making concurrent first inserts safe.** Fix redeployat pe producție (`CREATE OR REPLACE FUNCTION`) și regresie-verificat (scenariul 9 + reconfirmare S1-S7 neschimbate).

**Ce elimină R-Sync-7a**: nimic din calea live a `oracle_engine.py` — `oracle_engine.py` e neatins deliberat în această etapă. **Ce adaugă**: fundația de persistare (`scheduled_fixtures`, 6 adaptori de fixtures, `sync/sync_scheduled_fixtures.py`) care va alimenta R-Sync-7b. **Ce rămâne live**: toate cele 5 rânduri de discovery din tabelul cumulat (§8) — neschimbate față de închiderea R-Sync-6, întrucât Oracle Engine nu citește încă din `scheduled_fixtures`.

**Fișiere**: `database/migrations/023_scheduled_fixtures.sql`; 6 wrapper-e publice noi în `oracle_api.py` (`get_freelf_matches_raw`, `get_odds_api_events_raw`, `get_football_data_matches_raw`, `get_espn_matches_raw`, `get_tsdb_matches_raw`, `get_api_football_matches_raw`); `database/queries.py` (`upsert_scheduled_fixture`, `get_scheduled_fixture`); `fixture_discovery_common.py` (helper comun, justificat de 6 implementări reale simultane); 6 adaptori (`freelf_fixture_adapter.py`, `odds_api_fixture_adapter.py`, `footballdata_fixture_adapter.py`, `espn_fixture_adapter.py`, `tsdb_fixture_adapter.py`, `apifootball_fixture_adapter.py`); `sync/sync_scheduled_fixtures.py`; 9 fișiere de test noi.

---

## 7. Vezi ADR-039

`docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md`

---

## 8. Roadmap de implementare (actualizat post-R-Sync-7a, §6e)

1. ✅ Formalizare `SyncAdapter` (interfață) — **FINALIZAT, R-Sync-1**.
2. ✅ Migrare API-Football injuries/coaches (§6, pasul 1) — **FINALIZAT, R-Sync-2**.
3. ✅ Migrare football-data.org — **DOAR** formă/standings (§6, pasul 2) — **FINALIZAT, R-Sync-3**, scope corectat, ESPN exclus.
4. ✅ Migrare eloratings.net — **National Team ELO Synchronization** (§6, pasul 3 — **corectat, §6c: NU e TheSportsDB**) — **FINALIZAT, R-Sync-4** (`national_team_elo_snapshot`, migrare 019).
5. ✅ `weather_forecast_cache` + adaptor Weather (§6, pasul 4) — **FINALIZAT, R-Sync-5**.
6. ✅ Migrare FreeLF formă/standings + Odds API fallback H2H/formă (§6, pasul 5) — **FINALIZAT, R-Sync-6** — **corectat, §6d**: FreeLF H2H exclus (cuplat la discovery, mutat la R-Sync-8), Odds API H2H/formă unificate într-un singur tabel canonic (`odds_api_recent_results`, opțiunea A), FreeLF integrată în Request Manager/Rate Limit Manager (R4.1) înainte de migrare.
7. **Universal Match Discovery Layer** (§6, pasul 6; §6b) — etapă proprie, cea mai mare, împărțită în 7a/7b/7c:
   - 7a. ✅ **FINALIZAT** — fundația: `scheduled_fixtures` (migrare 023) + RPC `upsert_scheduled_fixture_merge` (FixtureMergePolicy, field-level merge, validat live pe producție) + 6 adaptori de fixtures + `sync/sync_scheduled_fixtures.py`. `oracle_engine.py` neatins deliberat — vezi §6e.
   - 7b. Oracle Engine citește `scheduled_fixtures`, comparație cu calea veche (`get_matches_for_week()`), calea veche păstrată în spatele unui flag implicit dezactivat — **următorul, neînceput**.
   - 7c. Eliminarea căii vechi după dovadă de echivalență — neînceput.
8. **Post-Discovery Cleanup** — **redefinit, §6d**: TheSportsDB team stats (mutat, §6c) **+ FreeLF H2H** (mutat, §6d) — ambele cuplate structural la `team_id`/`event_id` produs DOAR de Match Discovery, deblocate abia după R-Sync-7 — R-Sync-8.
9. Doar după toate cele de mai sus: eliminarea completă a `self.api` din `oracle_engine.py` — Oracle Engine citește exclusiv Supabase, pentru orice tip de date, de la orice provider, fără excepție — R-Sync-9.

**Task separat, neînceput** (§6d): R-Sync-6a — verificare live payload FreeLF standings, identificare nume real câmp „form", reparare `get_freelf_standings()`.

### Tabel cumulat — dependențe live rămase în Oracle Engine (actualizat, post-R-Sync-7a — neschimbat față de R-Sync-6: `oracle_engine.py` neatins în R-Sync-7a, vezi §6e)

| Provider / sursă | Oracle Engine mai face apel live? | Motiv / unde | Eliminare planificată |
|---|---|---|---|
| API-Football (injuries/coaches) | **NU** | — | ✅ R-Sync-2 |
| football-data.org (formă/standings) | **NU** | — | ✅ R-Sync-3 |
| eloratings.net (ELO naționale) | **NU** | — | ✅ R-Sync-4 |
| Weather API | **NU** | — | ✅ R-Sync-5 |
| FreeLF (formă/standings) | **NU** | — | ✅ R-Sync-6 |
| Odds API (fallback H2H/formă) | **NU** | — | ✅ R-Sync-6 |
| FreeLF (H2H, event_id) | DA | `self.api.get_h2h()`, cuplat la `_freelf_event_id` produs de discovery (§6d) | R-Sync-8 |
| TheSportsDB (team stats) | DA | `get_team_stats`, cuplat la `team_id` de discovery (§6c) | R-Sync-8 |
| API-Football (fixtures) | DA | `_fetch_matches_api_football`, `get_matches_for_week()` | R-Sync-7 |
| Odds API (descoperire meciuri, pasul 1) | DA | `_fetch_events_odds_api`, `get_matches_for_week()` | R-Sync-7 |
| FreeLF (descoperire meciuri, pasul 2) | DA | `_fetch_freelf_matches`, `get_matches_for_week()` | R-Sync-7 |
| ESPN (descoperire meciuri) | DA | `_fetch_matches_espn`, `get_matches_for_week()` | R-Sync-7 |
| TheSportsDB (descoperire meciuri) | DA | `_fetch_matches_tsdb`, `get_matches_for_week()` | R-Sync-7 |
| Odds API (cote pre-meci) | DA — dar deja conform (Frozen) | `odds_persistence_service.py`, ADR-005/006 — nu e candidat de migrare | N/A, deja sync-first |

**Progres obiectiv, post-R-Sync-7a**: **6 din 13** surse reale de apel live eliminate (exclus rândul „deja conform") — **neschimbat față de R-Sync-6**. R-Sync-7a a construit fundația de persistare (`scheduled_fixtures`) fără să comute vreo citire a Oracle Engine — niciun apel live nu a dispărut încă din cele 5 rânduri de discovery de mai sus. Rămân 7: 5 se rezolvă la R-Sync-7b (comutarea efectivă a Oracle Engine pe `scheduled_fixtures`), 2 la R-Sync-8 (Post-Discovery Cleanup). `self.api` complet eliminat din `oracle_engine.py` abia la R-Sync-9.

**Notă de proces, adăugată la cererea proprietarului produsului (post-R-Sync-3)**: pentru fiecare pas de mai sus, ÎNAINTE de implementare, se produce un audit scurt care demonstrează explicit — ce elimină, ce adaugă, ce rămâne încă live, ce va elimina etapa următoare, dovadă că nu apare o dependență nouă. R-Sync-4 e primul pas care aplică formal acest tipar (vezi §6c) — evită exact genul de corecție post-hoc pe care a necesitat-o R-Sync-4 însuși.

**Notă de proces #2, adăugată la închiderea R-Sync-4**: după ÎNCHIDEREA fiecărui pas (nu doar înainte de el), două confirmări obligatorii, separate de rezultatul testelor: (1) ce apel live a dispărut DEFINITIV din Oracle Engine (dovadă AST/grep, nu presupunere); (2) ce apel live încă există și de ce (provider, motiv, pasul care îl va elimina). Scop explicit: dovadă obiectivă de progres către obiectivul final — Oracle Engine 100% Database-First, zero provideri externi în calea de execuție — nu doar „testele sunt verzi". Tabelul cumulat de dependențe live rămase (de mai sus, în §8) se actualizează la fiecare închidere, întreținut din R-Sync-4 încolo — un singur tabel, nu un istoric de versiuni separate.

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
