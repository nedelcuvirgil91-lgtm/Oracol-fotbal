# R-Sync-FLASH-01 — Flashscore ca Provider Auxiliar UDAL

**Status**: DESIGN, neimplementat. Nu s-a rulat niciun scraping live, nu s-a aplicat nicio migrare Supabase, `tos_reviewed` rămâne `False`.
**Cerut**: "R-SYNC-FLASH-01 — Flashscore as Auxiliary UDAL Provider" (după POC-ul cu 10 meciuri, `UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md`, recomandare B — sursă auxiliară).
**[ACTUALIZAT 2026-07-29]** — "Direction Update (Architecture Decision)": bootstrap incremental (nu bulk), scope redus (ultimul sezon complet, nu tot istoricul), ordine explicită de bootstrap, cote ca fallback temporar, robustness (checkpoint/queue/resume). Vezi §10 — secțiunile 1-9 rămân valabile ca fundație, neînlocuite, doar extinse. Status rămâne DESIGN — „Nu implementa imediat" respectat identic.

## 0. Corecție arhitecturală față de propunerea inițială (surprinsă înainte de implementare, nu după)

Propunerea cerea scriere în tabele noi `match_statistics`, `match_lineups`, `match_events`, `player_match_stats`. Verificare directă a schemei live (`match_history`, migrațiile 008 și 026) arată că **`match_statistics` și `match_lineups` există deja — ca și coloane pe `match_history`, nu ca tabele separate**:

- Coloane deja existente (owner: Soccer Football Info, Sprint 1, ADR-041): `home/away_possession`, `home/away_shots`, `home/away_shots_on_target`, `home/away_shots_off_target`, `home/away_corners`, `home/away_fouls`, `home/away_yellow_cards`, `home/away_red_cards`, `home/away_offsides`, `home/away_penalties`, `home/away_substitutions`, `home/away_xg_actual`, `home_lineup`/`away_lineup` (jsonb — XI complet), `home_manager`/`away_manager`, `referee`, `stadium`, `provider_raw_json`, `stats_source`.
- Scriere exclusiv prin RPC-ul canonic `upsert_match_canonical` (`_upsert_match_canonical_locked`, migrația 026) — **semantică `COALESCE`, per coloană, nu overwrite** (ADR-036, Canonical Feature Ownership).

Asta schimbă designul într-un mod favorabil, nu îl blochează: **`COALESCE` e exact mecanismul de "completează doar golurile" cerut pentru Flashscore** — dacă Soccer Football Info a scris deja `home_possession`, o rescriere ulterioară prin același RPC, cu aceeași valoare de coloană, e no-op automat, fără cod condițional suplimentar de "verifică dacă lipsește". Nu trebuie inventată o tabelă paralelă pentru date care au deja casă canonică — ar fragmenta sursa unică de adevăr exact pe tipul de date pe care Sprint 1 tocmai l-a consolidat.

**Ownership rămas neschimbat**: ADR-036 / garda AST (`tests/test_canonical_feature_ownership.py`) protejează explicit doar cele 10 coloane de FEATURE_COLUMNS (ELO/formă/rating off-def, h2h) și `actual_*` — Match Statistics NU e în acel set protejat, ownership-ul lor e "Sync Layer, prin RPC canonic", nu "un singur fișier Python anume". Un al doilea adaptor Sync Layer (Flashscore) care scrie prin ACELAȘI RPC e conform contractului existent, nu o încălcare — cu o singură condiție nouă, explicită mai jos (§2, regula de precedență).

**Ce e genuin nou** (nu are casă canonică azi): statistici **per jucător** (rating individual, minute, goluri/assist-uri per jucător — `home_lineup`/`away_lineup` azi sunt doar liste XI, nu obiecte bogate per jucător), un **timeline structurat de evenimente** (goluri/cartonașe/schimbări cu minut exact — azi doar `home/away_substitutions` ca număr agregat), și **tot ce ține de meciuri viitoare** (Predictor enrichment — `match_history` e prin definiție doar meciuri finalizate).

**Consecință de design**: 2 tabele noi, nu 5.

## 1. Principiul arhitectural (confirmat, neschimbat față de propunere)

```
API Providers (API-Football, Soccer Football Info, ESPN, ...)
        ↓ (deja prioritate 1, ADR-042)
Open Data (Kaggle, football-data.org, ClubElo)
        ↓ (deja prioritate 2, ADR-042)
Flashscore (Tier 2 Playwright, auxiliar — completează DOAR goluri)
        ↓
UDAL Normalize (adaptor comun, generic_rich_match_scraper_adapter.py — Faza 1.5)
        ↓
Supabase (match_history extins + 2 tabele noi)
        ↓
   ┌─────────────┬─────────────┐
   │  ML Engine  │  Predictor  │   ← citesc EXCLUSIV din Supabase, niciodată Flashscore direct
   └─────────────┴─────────────┘
```

Ordinea de achiziție UDAL (ADR-042, neschimbată): **API → Open Data → Flashscore**. Regula de precedență, impusă la nivel de query, nu de convenție:

> Dacă un rând `match_history` are deja `home_possession`/`home_shots`/`home_corners` NOT NULL (indiferent de sursă), acel rând e exclus din target-ul Night Sync — Flashscore nu e interogat deloc pentru el, nu doar "rescrie aceeași valoare". Verificarea se face ÎNAINTE de fetch (economisește request-uri), nu după.

## 2. Capability Matrix

```python
# providers/flashscore/adapter.py (propus)
FLASH_PROVIDER_CAPABILITIES = {
    "possession":        True,
    "shots":              True,
    "shots_on_target":    True,
    "corners":            True,
    "fouls":               True,
    "yellow_cards":        True,
    "red_cards":           True,
    "offsides":            True,
    "goalkeeper_saves":    True,   # coloana NU exista azi in match_history - vezi 3.1
    "lineups_starting_xi": True,
    "player_ratings":      True,
    "substitution_events": True,
    "referee":             True,
    "attendance":          True,
    "stadium":             True,
    "odds_snapshot":       False,  # vezi 3.4 - blocat deliberat, nu implementat aici
    "xg":                  False,  # POC: fals-pozitiv, niciun widget real gasit
    "weather":             False,  # POC: confirmat absent pe Flashscore
    "h2h_history_rows":    False,  # POC: tab navigheaza, randuri reale neconfirmate
    "coach_name":          False,  # POC: doar eticheta de traducere, nume neconfirmat
    "bench_full_list":     False,  # POC: doar eticheta de traducere, lista neconfirmata
}
```

Sursă: `UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md`, secțiunile 5-6 — fiecare `True`/`False` de mai sus corespunde direct unui ✅/❌/⚠️ verificat, nu unei presupuneri. Câmpurile ⚠️ din POC (H2H rows, coach, bench complet) sunt marcate `False` aici — un capability declarat `True` fără dovadă directă ar fi exact genul de „aproximare a unei stări necunoscute" interzis de North Star #8.

Această declarație e format `DataType`-compatibil cu `provider_capabilities.py` (`STATISTICS`, `LINEUPS`, `PLAYER_RATINGS`), dar rămâne un dict separat, la fel cum `scraper_registry.py` descrie deja — capabilitatea "ce poate tehnic" nu forțează același `dataclass` ca la provideri API (motiv documentat deja în `scraper_registry.py`).

## 3. Mapping Supabase

### 3.1 `match_history` — extindere aditivă, scriere prin `upsert_match_canonical` existent

Singura schimbare de schemă propusă (NU aplicată încă — necesită aprobare separată, SQL exact înainte de execuție, per `supabase-safety`):

```sql
ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS home_goalkeeper_saves integer,
  ADD COLUMN IF NOT EXISTS away_goalkeeper_saves integer;
```

Toate celelalte câmpuri candidate din capability matrix (possession, shots, corners, fouls, cards, offsides, referee, stadium, home/away_lineup XI) au deja coloană — Flashscore devine pur și simplu un al doilea apelant posibil al `upsert_match_canonical`, gata gated de COALESCE.

`stats_source` (coloană existentă, azi populată de Soccer Football Info) devine relevantă pentru trasabilitate (North Star #9) — propunere: quando Flashscore completează un gol, `stats_source` ar trebui să reflecte compoziția reală (ex. `"soccerfootballinfo+flashscore_gapfill"`), nu doar suprascris — necesită o mică extensie a RPC-ului (concatenare condiționată, nu overwrite) — parte din implementare, nu design.

### 3.2 `player_match_stats` (NOU — genuin fără casă azi)

```sql
CREATE TABLE IF NOT EXISTS player_match_stats (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  match_id bigint NOT NULL REFERENCES match_history(id),
  team text NOT NULL CHECK (team IN ('home', 'away')),
  player_name text NOT NULL,
  shirt_number integer,
  position text,
  is_starting boolean NOT NULL DEFAULT true,
  minutes_played integer,
  rating numeric(3,1),
  goals integer DEFAULT 0,
  assists integer DEFAULT 0,
  yellow_cards integer DEFAULT 0,
  red_cards integer DEFAULT 0,
  source text NOT NULL DEFAULT 'flashscore',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (match_id, team, player_name)
);
ALTER TABLE player_match_stats ENABLE ROW LEVEL SECURITY;
```

Owner de scriere: exclusiv Flashscore Night Sync (singura sursă din capability matrix cu `player_ratings: True` azi) — `INSERT ... ON CONFLICT (match_id, team, player_name) DO UPDATE`, atomic, nu check-then-act (regula North Star deja stabilită).

### 3.3 `match_events` (NOU — genuin fără casă azi)

```sql
CREATE TABLE IF NOT EXISTS match_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  match_id bigint NOT NULL REFERENCES match_history(id),
  team text NOT NULL CHECK (team IN ('home', 'away')),
  minute integer NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('goal', 'yellow_card', 'red_card', 'substitution')),
  player_name text,
  related_player_name text,  -- pentru substitutie: cine intra
  source text NOT NULL DEFAULT 'flashscore',
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE match_events ENABLE ROW LEVEL SECURITY;
```

### 3.4 Odds snapshot — deliberat AFARĂ din scope-ul acestui design

`ODDS_PERSISTENCE_DESIGN.md` e **Frozen** (ADR-005, extins ADR-006/ADR-010) — orice atingere a modelului de date de cote trece printr-un ADR nou, nu printr-o coloană/tabelă ad-hoc introdusă de un provider auxiliar nou. Capability matrix de mai sus declară `odds_snapshot: False` intenționat — dacă Flashscore devine vreodată sursă de cote, e un task separat, cu propriul ADR, nu un side-effect al R-Sync-FLASH-01.

### 3.5 Tabele Pre-Match (NOI — domeniu genuin nou, Predictor enrichment)

```sql
CREATE TABLE IF NOT EXISTS upcoming_matches (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  home_team text NOT NULL,
  away_team text NOT NULL,
  competition text NOT NULL,
  kickoff_at timestamptz NOT NULL,
  standings_snapshot jsonb,
  recent_form_home jsonb,
  recent_form_away jsonb,
  source text NOT NULL DEFAULT 'flashscore',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (home_team, away_team, kickoff_at)
);

CREATE TABLE IF NOT EXISTS upcoming_lineups (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  upcoming_match_id bigint NOT NULL REFERENCES upcoming_matches(id),
  team text NOT NULL CHECK (team IN ('home', 'away')),
  predicted_lineup jsonb,   -- Flashscore "Predicted lineups", cf. POC (TRANS_DETAIL_LABEL_PREDICTED_LINEUPS)
  confidence text,          -- Flashscore nu garanteaza acuratete - marcat explicit "predicted"
  fetched_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (upcoming_match_id, team)
);

CREATE TABLE IF NOT EXISTS upcoming_match_features (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  upcoming_match_id bigint NOT NULL REFERENCES upcoming_matches(id) UNIQUE,
  h2h_summary jsonb,
  odds_backup_snapshot jsonb,  -- doar ca fallback informativ, NU inlocuieste odds_persistence_service (3.4)
  extra_stats jsonb,
  fetched_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE upcoming_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_lineups ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_match_features ENABLE ROW LEVEL SECURITY;
```

**Notă**: Predictor-ul ACTUAL (`oracle_engine.py`) nu citește azi din aceste tabele — a le popula fără ca Oracle Engine să le consume ar fi scriere moartă. Racordarea Predictor-ului la `upcoming_*` e un task separat, ulterior, explicit **în afara scope-ului acestui document de design** (design-only, cf. cerință).

## 4. Structură provider propusă (schelet de interfețe, ZERO logică de scraping)

```
providers/
    flashscore/
        __init__.py
        adapter.py       # FlashscoreAdapter(ScraperAdapterBase) - fetch() ridica NotImplementedError
        extractor.py      # selector map declarativ (wcl-* testids confirmate in POC) - date, nu cod
        normalizer.py     # normalize() -> forma canonica match_history / player_match_stats / match_events
```

Extinde `ScraperAdapterBase` (Faza 0) + reutilizează `udal_extraction.extract()`/`CSS_RESOLVER` (Faza 1.5) — **zero cod nou de parsare generică**, doar selector map specific Flashscore (`wcl-statistics-value`, `wcl-lineupsParticipantName`, `wcl-badgeRating`, `wcl-summaryMatchInformation`, confirmate structural în POC). Fișierele create acum sunt schelet — `fetch()` rămâne neimplementat (`NotImplementedError`), consistent cu Faza 0/1.5.

Înregistrare `scraper_registry.py` — declarativă, `tos_reviewed=False` (neschimbat, blocant, `is_runnable()` respinge orice pornire):

```python
"flashscore_match_enrichment": ScraperCapability(
    scraper_id="flashscore_match_enrichment", version=1,
    tier=AcquisitionTier.PLAYWRIGHT,
    data_types=frozenset({DataType.STATISTICS, DataType.LINEUPS, DataType.PLAYER_RATINGS}),
    target_url_template="https://www.flashscore.com/football/{country}/{competition}/results/",
    selector_map_ref="flashscore_match_enrichment-v1",
    politeness_policy_ref="flashscore_match_enrichment-politeness-v1",
    tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
)
```

## 5. Flux Night Sync (ML enrichment)

**Fereastră**: 02:00–05:00 (după fereastra de sincronizare zilnică existentă, `daily.yml` — nu concurent cu ea).
**[CORECTAT §13.2, R-Sync-FLASH-02]** — afirmația "nu concurent cu `daily.yml`" era greșită, neverificată la momentul redactării: `daily.yml` pornește la `03:00 UTC`, în plină fereastră `02:00-05:00`. Fereastra corectă, cu justificare completă, e în §13.2 (`01:00 UTC`, plafon 90 min).

```
1. SELECT din match_history:
     WHERE league IN (ligile active, mappings.LEAGUE_PROVIDERS — azi 11)
       AND actual_result IS NOT NULL           -- doar meciuri finalizate
       AND kickoff_date >= now() - interval '7 days'   -- fereastra rezonabila, nu backfill istoric total
       AND (home_possession IS NULL OR home_shots IS NULL OR home_corners IS NULL
            OR referee IS NULL OR home_lineup IS NULL OR home_goalkeeper_saves IS NULL)
   → target real = DOAR randurile cu cel putin un gol (regula de precedenta, sectiunea 1)

2. Pentru fiecare rand target:
   a. preflight() - blocheaza daca tos_reviewed=False (azi: blocheaza TOT, deliberat)
   b. discovery link real de meci (acelasi mecanism validat in POC: hub /results/ -> href real,
      nu URL construit din nume de echipe)
   c. fetch() Playwright (Tier 2) - navigare Match + taburile relevante DOAR pentru campurile lipsa
      (daca doar goalkeeper_saves lipseste, nu se navigheaza Lineups/H2H inutil - cost minimizat)
   d. normalize() -> forma canonica
   e. validate() -> udal_validation.validate_records() (Faza 1, neschimbat)
   f. persist():
        - campuri match_history -> upsert_match_canonical (COALESCE, deja idempotent)
        - randuri player_match_stats / match_events -> INSERT...ON CONFLICT DO UPDATE
   g. acquisition_run_log + acquisition_dead_letter (Faza 0, neschimbat) - trasabilitate completa

3. Politeness: pauza intre meciuri (POC a folosit 2s, fara nicio protectie declansata pe 10
   navigari secventiale - insuficient pentru a extrapola la scara mai mare, vezi sectiunea 7)
```

## 6. Flux Pre-Match Sync (Predictor enrichment)

**Fereastră**: următoarele 7 zile (rulare zilnică, sincronizată cu descoperirea de meciuri existentă, nu separat).

```
1. SELECT meciuri viitoare din sursa de descoperire existenta (oracle_api.get_matches_for_week()
   / echivalent Database-First, R-Sync-7 cand va fi migrat) pentru ligile active.

2. Pentru fiecare meci viitor:
   a. preflight() - identic Night Sync
   b. discovery link real Flashscore pentru meciul respectiv (hub /fixtures/, nu /results/)
   c. fetch() - Summary + Standings + H2H (daca disponibil) + lineup-uri PREZISE (nu confirmate -
      Flashscore le eticheteaza explicit "Predicted lineups", cf. POC)
   d. normalize() -> forma upcoming_matches / upcoming_lineups / upcoming_match_features
   e. persist() -> INSERT...ON CONFLICT DO UPDATE in cele 3 tabele noi (3.5) - NICIODATA in
      match_history (meciul inca nu s-a jucat, ar corupe cheia naturala si semantica actual_*)

3. Predictor-ul NU citeste inca din aceste tabele (vezi nota 3.5) - popularea lor e utila doar
   dupa ce un task separat conecteaza oracle_engine.py la ele. Pana atunci, tabelele exista si
   se populeaza (daca fluxul e activat), dar raman neconsumate - decizie constienta, nu accident.
```

## 7. Estimare (cerută explicit înainte de orice implementare)

Bază reală: latența măsurată în POC (medie 829ms/navigare inițială, 10 meciuri, 2 competiții), plus 4-6 navigări/meci necesare pentru acoperire completă (Summary + Lineups + H2H + Odds + eventual Standings) + 2s pauză de politețe între meciuri.

- **Cost per meci** (complet, toate câmpurile lipsă): ~4 navigări utile × ~0.8s + 2s politețe ≈ **~5-6 secunde/meci**.
- **Meciuri/noapte** (Night Sync, 11 ligi active, fereastră 7 zile, doar rânduri cu goluri reale): estimare **10-40 meciuri/noapte** — depinde direct de cât de complet e deja Soccer Football Info (Sprint 1) per ligă; niciun număr măsurat real încă (necesită interogarea efectivă a `match_history` cu filtrul de la §5.1, neexecutată aici — design-only).
- **Timp total estimat/noapte**: 10-40 meciuri × ~6s ≈ **1-4 minute** de navigare Playwright efectivă — mult sub fereastra de 3 ore alocată (02:00-05:00), marjă mare.
- **Request-uri/noapte**: ~4-6 navigări HTTP(S) reale per meci → **40-240 request-uri/noapte** la volumul estimat — ordin de mărime mic față de praguri tipice de rate-limiting observate pe siteuri similare.
- **Risc de blocare**: **necunoscut la scară**, explicit — POC-ul a validat 10 navigări secvențiale fără nicio protecție, dar 10 ≠ zeci pe noapte, în mod repetat, în fiecare noapte. Recomandare: prima activare reală (dacă se aprobă) rulează cu volum redus deliberat (ex. 5 meciuri/noapte, o săptămână), monitorizat explicit prin `acquisition_run_log`/`acquisition_dead_letter`, înainte de a crește la volumul complet estimat — consistent cu principiul „shadow rămâne shadow până e dovedit" (North Star #1).

## 8. Ce NU s-a făcut în acest document (deliberat, cf. cerință explicită)

- Nicio migrare Supabase aplicată (SQL de mai sus e PROPUS, nu executat).
- Niciun scraping live, nicio verificare suplimentară de ToS (`tos_reviewed` rămâne `False`).
- Niciun cod de extracție/normalizare real scris — doar scheletul de fișiere (interfețe, fără logică).
- Predictor-ul NU a fost modificat să citească din tabelele noi.
- Nicio estimare de mai sus nu e validată empiric la scară — sunt calcule pe baza datelor reale din POC-ul cu 10 meciuri, extrapolate, marcate explicit ca atare.

## 9. Pași următori (necesită aprobare separată, per etapă — neschimbat față de disciplina UDAL stabilită)

1. Aprobare design (acest document).
2. Migrare Supabase (§3.1, 3.2, 3.3, 3.5) — SQL exact arătat, aprobat separat, per `supabase-safety`.
3. Implementare reală `providers/flashscore/{adapter,extractor,normalizer}.py` (înlocuiește scheletul).
4. `POC_SCRAPER_SOURCE_02` — validare live, volum mic, monitorizat (§7) — separat de `tos_reviewed=True`, care rămâne decizia finală, explicită, a proprietarului produsului.
5. Abia după (2)-(4): activare Night Sync + Pre-Match Sync, cu flag-uri noi (`udal_source_enabled["flashscore"]`, pattern existent în `udal_config.py`), implicit `False`.

---

## 10. [ACTUALIZAT 2026-07-29] Direction Update — Bootstrap incremental, ordine, cote fallback, robustness

Răspuns la "R-SYNC-FLASH-01 — Direction Update (Architecture Decision)". Secțiunile 1-9 de mai sus rămân fundația (principiu arhitectural, capability matrix, mapping Supabase, schelet provider) — ce urmează extinde, nu înlocuiește. **Tot ce urmează rămâne DESIGN — nicio linie de cod de scraping/migrare nouă nu s-a scris ca urmare a acestei actualizări**, cu o singură excepție minoră notată explicit în §10.7.

### 10.1 Principiul auxiliar — neschimbat, reconfirmat

Flashscore rămâne provider auxiliar, ultimul din ordinea UDAL (API → Open Data → Flashscore). ML și Predictor citesc exclusiv din Supabase — niciun cod nu citește Flashscore direct. Neschimbat față de §1.

### 10.2 Bootstrap incremental (înlocuiește ideea de bootstrap masiv, respinsă)

Nicio rulare nu procesează mai mult de un lot mic. Design:

- **50 meciuri/noapte, în 3 batch-uri** (~17 meciuri/batch) — nu 50 dintr-o singură trecere continuă; fiecare batch e o invocare separată (workflow separat sau pas separat în același workflow, cu pauză impusă între ele), nu doar o buclă internă fără respirație.
- **Rate limiting între batch-uri**: pauză minimă (propunere: 5-10 minute între batch-uri, în plus față de politețea de 2s deja folosită între meciuri individuale în POC) — separă explicit „politețea per-request" (§7, deja proiectată) de „politețea per-lot" (nouă, cerută aici).
- **Checkpoint după fiecare batch, nu doar la final** — vezi §10.6 pentru mecanismul exact (coadă persistentă, nu variabilă în memorie).
- **Reluare exactă, nu de la capăt**: dacă procesul moare la mijlocul batch-ului 2, următoarea rulare continuă de la exact următorul meci neprocesat — niciun meci deja `done` nu se reprocesează, niciun meci `in_progress` abandonat nu rămâne blocat permanent (regulă de „stale reclaim", §10.6).

### 10.3 Scope istoric — un singur sezon complet per competiție

**Nu** tot istoricul. Pentru fiecare competiție: **doar ultimul sezon complet** (cel mai recent sezon încheiat, nu sezonul curent în desfășurare — un sezon "complet" înseamnă toate meciurile lui au `actual_result` deja în `match_history`). Restul istoricului rămâne construit organic de sincronizarea zilnică existentă, în timp — compromis explicit acceptat, nu o lacună ascunsă.

Consecință directă asupra volumului: un sezon complet de SuperLiga (32 echipe... de fapt 16 echipe, ~30 runde) înseamnă ~240 meciuri — la 50/noapte, bootstrap-ul SuperLiga complet durează **~5 nopți**, nu una singură. Estimarea din §7 (10-40 meciuri/noapte pentru Night Sync, regim de croazieră) rămâne separată de această fază de bootstrap (regim inițial, mai intens, dar plafonat explicit la 50/noapte).

### 10.4 Ordinea bootstrapului — impusă, nu opțională

```
1. SuperLiga România   (singura ligă activă acum -> valoare imediata pentru ML)
2. Premier League
3. La Liga
4. Serie A
5. Bundesliga
6. Ligue 1
7. restul competitiilor (ordine neschimbata fata de mappings.LEAGUE_PROVIDERS)
```

Implementare: coloana `bootstrap_order` din coada persistentă (§10.6) — worker-ul consumă strict în ordinea `bootstrap_order ASC`, o competiție nu începe înainte ca precedenta să atingă `completed` (excepție posibilă, de discutat separat: rulare paralelă pe competiții diferite ar accelera, dar contrazice „SuperLiga produce valoare imediată" ca prioritate explicită — recomandare: **strict secvențial**, cel puțin pentru primele 2-3 competiții, până se validează robustness-ul la scară).

### 10.5 Night Sync — rafinat, nu doar gap-fill generic

După ce bootstrap-ul unei ligi atinge `completed`:

- Night Sync pentru acea ligă comută automat de la „scan tot sezonul" la **doar meciurile noi + ultimele zile** (fereastră mică, propunere: ultimele 3-4 zile, suficient să acopere orice întârziere de sincronizare, nu o redeschidere a întregului istoric).
- **Nu reprocesează meciuri deja complete** — regula de precedență din §1/§5 (query înainte de fetch, doar rânduri cu câmpuri `NULL`) rămâne mecanismul exact care garantează asta, neschimbată. „Complet" = toate câmpurile țintă din capability matrix (§2) sunt deja populate, indiferent de sursă.
- Tranziția bootstrap→regim-de-croazieră per ligă e citită direct din `flashscore_acquisition_queue` (§10.6): dacă nu mai există rânduri `pending`/`in_progress` pentru acea competiție la `bootstrap_order`-ul curent, Night Sync-ul standard preia liga respectivă.

### 10.6 Robustness — checkpoint, coadă persistentă, retry, resume automat

Propunere concretă (schemă, nu migrare aplicată — la fel ca §3, arătată explicit, aprobare separată înainte de execuție):

```sql
CREATE TABLE IF NOT EXISTS flashscore_acquisition_queue (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition      TEXT NOT NULL,               -- 'superliga_romania', 'premier_league', ...
    bootstrap_order  INTEGER NOT NULL,             -- 1..7, ordinea din §10.4
    season           TEXT NOT NULL,                -- ultimul sezon complet (§10.3)
    match_url        TEXT NOT NULL,                -- link real, descoperit (acelasi mecanism ca in POC)
    status           TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'in_progress', 'done', 'failed')),
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    claimed_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (competition, match_url)
);
CREATE INDEX IF NOT EXISTS flashscore_queue_pending_idx
    ON flashscore_acquisition_queue (bootstrap_order, id) WHERE status = 'pending';
ALTER TABLE flashscore_acquisition_queue ENABLE ROW LEVEL SECURITY;
```

- **Populare** (o singură dată per competiție, la începutul bootstrap-ului ei): discovery real (mecanismul deja validat în POC — hub `/results/`, linkuri reale, nu construite) pentru ultimul sezon complet, INSERT în lot, `status='pending'`.
- **Claim atomic** (elimină check-then-act, regulă deja stabilită în proiect — vezi `upsert_match_canonical`): `UPDATE ... SET status='in_progress', claimed_at=now() WHERE id = (SELECT id FROM flashscore_acquisition_queue WHERE status='pending' ORDER BY bootstrap_order, id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *` — `FOR UPDATE SKIP LOCKED`, pattern standard Postgres pentru cozi, nicio fereastră de cursă.
- **Checkpoint = starea coloanei `status`, nu o variabilă de proces** — dacă workflow-ul GitHub Actions moare (timeout, crash, întrerupere), rândurile deja `done` rămân `done`, rândurile `in_progress` abandonate sunt recuperate de o regulă de „stale reclaim": `UPDATE ... SET status='pending' WHERE status='in_progress' AND claimed_at < now() - interval '2 hours'` — rulată la începutul fiecărei sesiuni de batch, înainte de claim. Fără asta, un crash mid-batch ar bloca permanent acele rânduri.
- **Retry logic**: `attempt_count` incrementat la fiecare eșec, `last_error` populat; propunere: după 3 eșecuri consecutive, `status='failed'` definitiv (nu mai reintră în coadă automat) — vizibil pentru investigare manuală, consistent cu `acquisition_dead_letter` (Faza 0) ca precedent de „nimic nu se pierde silențios" (North Star #9).
- **Trasabilitate**: fiecare batch încă scrie în `acquisition_run_log` (Faza 0, neschimbat) — coada de mai sus e mecanismul de reluare exactă, `acquisition_run_log` rămâne jurnalul agregat per lot.

Acest design reutilizează exclusiv pattern-uri deja stabilite în proiect (advisory-lock-style claim, `ON CONFLICT`, RLS fără policy, `acquisition_run_log`/`acquisition_dead_letter` ca precedent) — nicio dependință nouă (Redis, coadă externă) introdusă, consistent cu „Supabase Single Source of Truth".

### 10.7 Cotele — excepție deliberată, fallback temporar, NU schimbare de filosofie

**Conflict real identificat cu designul existent** (§3.4 al acestui document excludea explicit cotele, citând `ODDS_PERSISTENCE_DESIGN.md`, Frozen via ADR-005, extins ADR-006/ADR-010) — verificare directă a documentului Frozen (nu presupunere):

- `odds_history` are cheie `UNIQUE(fixture_id, bookmaker)` — **fără coloană de sursă/provider**. Verificat live în `database/migrations/001_odds_history.sql`.
- Confirmat direct în POC (`UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md`, secțiunea 5): Flashscore afișează cote reale de la bookmaker-i reali (**bet365, Unibet** — aceiași nume folosite probabil și de The Odds API).
- **Consecință**: dacă Flashscore ar scrie direct în `odds_history` folosind același nume de bookmaker ca The Odds API, cele două surse s-ar **amesteca silențios pe același rând** (COALESCE-ul din `upsert_match_canonical` nu se aplică aici — `odds_history` are propriul trigger de imutabilitate, per-coloană, care nu distinge sursa) — **încălcare directă North Star #9** ("orice rezultat trasabil complet până la sursă") dacă nu e tratată explicit.

**Decizie de design, ca răspuns**: **NU** se scrie direct în `odds_history` (tabelă Frozen, trigger deja testat exhaustiv — reopen-ul ei ar cere un ADR care modifică un document deja verdict "FROZEN", risc mai mare decât beneficiul). În loc, o tabelă **nouă, separată**, strict pentru fallback:

```sql
CREATE TABLE IF NOT EXISTS odds_fallback_flashscore (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id    TEXT NOT NULL,          -- acelasi fixture_id canonic (ADR-024)
    bookmaker     TEXT NOT NULL,
    home          NUMERIC,
    draw          NUMERIC,
    away          NUMERIC,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fixture_id, bookmaker)
);
ALTER TABLE odds_fallback_flashscore ENABLE ROW LEVEL SECURITY;
```

- **Regula de citire pentru Predictor** (propusă, de implementat într-un singur punct — `database/queries.py`, nu dispersat): citește întâi `odds_history` (sursa primară, neschimbată); **doar dacă** acel `fixture_id` nu are NICIUN rând acolo, citește `odds_fallback_flashscore` ca alternativă. Niciodată amestecate pe același fixture, niciodată `odds_fallback_flashscore` preferat față de `odds_history` când ambele există.
- **Etichetare explicită, la nivel de schemă, nu doar de convenție**: numele tabelei însuși (`odds_fallback_flashscore`) documentează statutul temporar/secundar — orice consumator viitor vede imediat, din numele coloanei sursă în query, că nu citește sursa oficială.
- **Nu schimbă filosofia**: Flashscore rămâne auxiliar; the-odds-api (sau orice provider oficial viitor) rămâne sursa principală de cote, neatinsă, cu prioritate necondiționată în citire.
- **ADR necesar**: **da** — introducerea unei surse noi de cote care alimentează Predictorul e o schimbare de contract (North Star #5), chiar dacă tabela Frozen `odds_history` nu e atinsă deloc. Propunere: **ADR-043** (următorul număr secvențial liber — verificat, ultimul ADR existent e ADR-042), redactat mai jos (§10.8), status **PROPUS**, neaprobat încă.

### 10.8 ADR-043 (PROPUS) — Flashscore ca sursă de fallback pentru cote

Redactat ca răspuns direct la cerința "verifică dacă noua direcție nu intră în conflict cu ADR-urile existente" — nu e o decizie finală, e propunerea supusă aprobării, salvată separat în `docs/00_GOVERNANCE/ADR-043-flashscore-odds-fallback.md` (§10.9 mai jos descrie exact conținutul, fișierul e creat ca parte a acestei actualizări, status PROPUS — nicio migrare aplicată ca urmare a lui).

### 10.9 Ce NU s-a schimbat / NU s-a implementat ca urmare a acestei actualizări

- Nicio migrare Supabase aplicată (nici cea din §3, nici `flashscore_acquisition_queue`, nici `odds_fallback_flashscore`).
- Niciun scraping live, `tos_reviewed` neschimbat (`False`).
- Niciun cod de bootstrap/queue/retry scris — doar schema propusă mai sus.
- Singura schimbare de cod ca urmare a acestei actualizări: `providers/flashscore/adapter.py`, `FLASH_PROVIDER_CAPABILITIES["odds_snapshot"]` actualizat de la `False` la `True` (cu comentariu „fallback temporar" — POC-ul a confirmat structural date reale de cotă, doar scope-ul de utilizare s-a schimbat acum, nu dovada tehnică) — o declarație, nu o implementare de scriere.
- ADR-043 rămâne **PROPUS**, nu **ACCEPTAT** — nu intră în vigoare până la aprobare explicită separată, consistent cu disciplina ADR a proiectului.

### 10.10 Pași următori (înlocuiește §9, cumulativ)

1. Aprobare ADR-043 (§10.8/§10.9) — decizie separată de aprobarea restului designului, dat fiind că atinge o zonă adiacentă unui document Frozen.
2. Aprobare restul actualizării din §10 (bootstrap incremental, ordine, robustness).
3. Migrații Supabase: `flashscore_acquisition_queue`, `odds_fallback_flashscore`, plus cele din §3 (`player_match_stats`, `match_events`, `upcoming_*`, `home/away_goalkeeper_saves`) — toate arătate explicit, aprobate separat, per `supabase-safety`.
4. Implementare reală `providers/flashscore/{adapter,extractor,normalizer}.py` + logica de coadă/checkpoint.
5. `POC_SCRAPER_SOURCE_02` — validare live la volum mic (propunere: 1 batch, 17 meciuri, SuperLiga) — separat de `tos_reviewed=True`.
6. Abia după (3)-(5): activare Night Sync + Bootstrap, flag nou `udal_source_enabled["flashscore"]`, implicit `False`.

---

## 11. [2026-07-29] Verificare finală de conflicte + Stage 1 (implementare aprobată, etapizată)

Răspuns la aprobarea explicită ("Sunt de acord cu soluția ta... dacă designul este compatibil, începe implementarea etapizat, în commit-uri mici, cu teste după fiecare etapă").

### 11.1 Verificare de conflicte (înainte de orice cod) — rezultat: niciun conflict nou

- **North Star #1-10**: verificate individual. Niciuna încălcată — `tos_reviewed=False` continuă să blocheze orice rulare reală (#1); niciun flag nou implicit activ, `udal_source_enabled["flashscore"]` rămâne `False` (#3); niciun document Frozen editat direct — `odds_history`/`ODDS_PERSISTENCE_DESIGN.md` complet neatinse (#4, verificat live, vezi §10.7); ADR-043 acoperă schimbarea de contract pentru cote (#5); SQL arătat explicit înainte de execuție (#6, acest document + mesajul de commit); niciun câmp neconfirmat marcat `True` în capability matrix (#8); trasabilitate păstrată prin `flashscore_acquisition_queue`/`acquisition_run_log`/numele auto-documentat `odds_fallback_flashscore` (#9); nicio dependință nouă „în sus" — Predictor citește Supabase, nu Flashscore direct (#10).
- **ADR-036 (Canonical Feature Ownership)**: verificat direct în `tests/test_canonical_feature_ownership.py` — garda AST acoperă exclusiv `_save_prediction`/`update_weights_from_result`, nu vizează un modul nou de Sync Layer care scrie prin `upsert_match_canonical`. Niciun conflict.
- **ADR-024 (Canonical Match Identity)**: `fixture_id` în `odds_fallback_flashscore` e `TEXT`, identic tipului din `odds_history` (migrația 001) — consistent, opac per-provider, cum specifică ADR-024.
- **FROZEN_REGISTRY.md**: verificat complet — niciun document Frozen listat (`ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md`, `ODDS_PERSISTENCE_DESIGN.md`, contractele Learning Core, `BASELINE_FAZA1_2026-07.md`) nu are conținut care intră în conflict cu tabelele noi propuse — cele 5 declarate Frozen dar absente fizic din repo (gol cunoscut, documentat deja în `CLAUDE.md`) rămân neverificabile prin construcție, nu prin omisiune aici.
- **CLAUDE.md, „Regulile bazelor de date"**: toate cele 7 tabele noi — idempotente (`CREATE TABLE IF NOT EXISTS`), RLS activ, scriere atomică (`FOR UPDATE SKIP LOCKED` pentru coadă, `ON CONFLICT` pentru restul — niciun check-then-act).

**Concluzie**: designul (§1-§10) e compatibil cu ADR-urile existente, CLAUDE.md și North Star — niciun conflict nou identificat, nicio schimbare de arhitectură necesară înainte de implementare.

### 11.2 Stage 1 — Migrație Supabase (schema-only), APLICATĂ live

SQL exact: `database/migrations/032_flashscore_auxiliary_provider_infrastructure.sql` (commit separat, mic — un singur obiectiv: schema, nimic altceva). Aplicată live pe proiectul `Prediction` (`gtlpyxzocacaqyompkwe`), verificată prin `list_tables` — toate 7 tabele noi există, RLS activ pe fiecare:

`player_match_stats`, `match_events`, `upcoming_matches`, `upcoming_lineups`, `upcoming_match_features`, `flashscore_acquisition_queue`, `odds_fallback_flashscore` — plus `match_history.home/away_goalkeeper_saves` (coloane aditive).

**Test pentru această etapă**: verificare schema-only, nu pytest (fără precedent în repo de a testa migrații SQL direct — `pytest tests/` rămâne fără dependință de rețea/Supabase live, per `test-coverage-guard`) — confirmarea e `list_tables` live, arătată mai sus, plus re-rularea completă a `pytest tests/` (neschimbată de această migrație, 1670 passed, aceleași 3 eșecuri preexistente).

**Notă de securitate, nelegată de acest task** (semnalată de Supabase advisor, obligatoriu de raportat, NU auto-remediată): 12 tabele PRE-EXISTENTE (`sync_status`, `elo_ratings`, `api_cache`, `league_provider_coverage`, `api_provider_status`, `provider_metrics`, `shadow_predictions`, `experiment_registry`, cele 4 `match_history_*_backup_*`) au RLS dezactivat — expuse complet la `anon`/`authenticated`. Niciuna atinsă de acest task; SQL de remediere disponibil, dar necesită decizie separată a proprietarului produsului (dezactivarea RLS fără politici ar bloca accesul existent la ele).

### 11.3 Etapele următoare (nu începute încă — commit-uri mici, separate)

- Stage 2: logica de populare a cozii (`flashscore_acquisition_queue`) — discovery real per competiție, INSERT în lot, ordonat după `bootstrap_order`.
- Stage 3: worker-ul de claim/procesare (`FOR UPDATE SKIP LOCKED`, stale-reclaim, retry) — fără `fetch()` real încă (rămâne blocat de `tos_reviewed=False` + `PlaywrightNotImplementedError`, neschimbat).
- Stage 4: implementarea reală `fetch()`/`normalize()`/`persist()` — necesită, separat, `POC_SCRAPER_SOURCE_02` + decizie explicită de `tos_reviewed=True`, per disciplina deja stabilită (nu parte a acestei aprobări).
- Stage 5: regula de citire Predictor (`odds_history` → fallback `odds_fallback_flashscore`) în `database/queries.py`.

Fiecare etapă: commit separat, teste rulate înainte de commit, raportate explicit.

---

## 12. [2026-07-29] Plan Stage 2 — propus, NEAPROBAT, NEIMPLEMENTAT

Răspuns la cererea explicită: "Înainte să scrii cod pentru Stage 2 vreau să îmi prezinți: planul exact al implementării; ordinea commit-urilor; estimarea fiecărui commit; riscurile fiecărui commit... Nu implementa încă Stage 2." Nicio linie de cod din acest §12 nu a fost scrisă încă.

### 12.0 Corecție de plan față de §11.3 — găsită înainte de a scrie cod, nu după

`§11.3` grupase greșit „Stage 2: populare coadă" ca pas separat de „Stage 4: fetch() real". Revizuire: **popularea cozii (`flashscore_acquisition_queue`) cere ea însăși un `fetch()` live** (navigare pe hub-ul `/results/` al competiției, exact mecanismul din POC) — deci e supusă **aceluiași gate** ca Stage 4: `ScraperAdapterBase.preflight()` blochează orice `fetch()` cât timp `tos_reviewed=False` (neschimbat, nicio decizie de ToS luată în acest document). Consecință: **popularea reală a cozii nu poate fi implementată/rulată acum** — ar fi cod scris care nu poate rula niciodată legitim până la o decizie separată de `tos_reviewed`.

Ce **poate** fi construit și testat acum, fără nicio dependență de rețea live: **mecanica cozii** — claim atomic, marcare done/failed, stale-reclaim, retry — operații pur SQL/Python peste rânduri deja existente în `flashscore_acquisition_queue` (populate manual, cu date sintetice, în teste — exact tiparul deja folosit la Faza 1, fixture local în loc de rețea live).

### 12.1 Plan de commit-uri (revizuit)

| # | Commit | Conținut | Dependință de rețea live? |
|---|---|---|---|
| 2.1 | `database/queries.py` — funcții cozii | `claim_next_flashscore_queue_item()` (`FOR UPDATE SKIP LOCKED`), `mark_queue_item_done(id)`, `mark_queue_item_failed(id, error)` (incrementează `attempt_count`, `status='failed'` după 3), `reclaim_stale_queue_items()` (`claimed_at < now() - 2h`) | **Nu** — SQL pur, testabil cu rânduri sintetice |
| 2.2 | `tests/test_flashscore_queue_mechanics.py` | Teste pentru fiecare funcție de mai sus — inserare rânduri sintetice direct (nu prin discovery), verificare tranziții de stare, verificare că `FOR UPDATE SKIP LOCKED` nu livrează același rând de două ori la claim-uri concurente (test cu 2 conexiuni/thread-uri, dacă infra de test o permite; altfel, verificare secvențială a stării, cu notă explicită despre limitarea testului) | **Nu** |
| 2.3 | `scripts/flashscore_queue_admin.py` (opțional, utilitar) | CLI simplu pentru inspecție manuală a cozii (`--status pending`, `--competition superliga_romania`) — utilitate operațională, nu parte a fluxului automat | **Nu** |
| — | ~~Populare coadă (discovery real)~~ | **Scos din Stage 2** — mutat implicit sub Stage 4 (același gate `tos_reviewed`) | **Da — blocat** |

### 12.2 Estimare per commit

- **2.1**: mediu — ~120-180 linii Python, 4 funcții, fiecare cu semantică SQL atomică deja proiectată (§10.6) — risc de implementare scăzut, logica e deja specificată exact.
- **2.2**: mediu — teste multiple per funcție (happy path + concurență + stale-reclaim + prag retry) — cel mai mare consumator de timp al Stage 2, dar fără risc arhitectural (testare pură).
- **2.3**: mic — opțional, poate fi omis din Stage 2 dacă nu e considerat necesar acum.

### 12.3 Riscuri per commit

- **2.1**: risc principal — corectitudinea semanticii `FOR UPDATE SKIP LOCKED` sub concurență reală (două rulări GitHub Actions suprapuse) nu poate fi testată complet fără infra de concurență reală în CI; mitigare — test unitar cât de aproape posibil de concurență reală (thread-uri/conexiuni paralele către Supabase de test), plus review explicit al SQL-ului înainte de commit (per `supabase-safety`, chiar dacă funcțiile astea nu creează schemă nouă).
- **2.2**: risc scăzut — cel mai mare pericol e un test fals-pozitiv (verifică prea puțin) sau fals-negativ (flaky din cauza timing-ului real de rețea Supabase) — mitigare: teste rulate de mai multe ori local înainte de commit, nu doar o rulare.
- **2.3**: risc minim, utilitate opțională.

### 12.4 Ce rămâne explicit AFARĂ din Stage 2 (mutat, nu uitat)

- Discovery real / populare coadă cu meciuri reale — necesită `tos_reviewed=True`, decizie separată, neluată aici.
- `fetch()`/`normalize()`/`persist()` real (Stage 4, neschimbat).
- Orice atingere a Predictorului — rămâne blocată explicit, cf. §"Predictor" din cererea curentă și `R-SYNC-FLASH-01_PREDICTOR_IMPACT_ANALYSIS.md`.

**Acest plan așteaptă aprobare explicită înainte de commit-ul 2.1.**

---

## 13. [R-SYNC-FLASH-02, 2026-07-29] Night Sync ca flux permanent, separat de Bootstrap — verificare de conflicte

Răspuns la "R-SYNC-FLASH-02 — Night Sync pentru sezonul curent (după bootstrap)". **Analiză, fără cod implementat** — cf. cerință explicită.

### 13.1 Confirmare — fără conflict

Separarea Bootstrap (one-time, per competiție, niciodată reluat după `completed`)/Night Sync (permanent, doar ultimele 3-4 zile, doar câmpuri lipsă) e deja consistentă cu §10.2-§10.5 din acest document — nicio contradicție, doar formalizare mai explicită. Regula COALESCE (niciodată rescriere de date existente) rămâne neschimbată, deja garantată de `upsert_match_canonical`. Decizia de a NU introduce un Weight Manager Predictor/ML: confirmată, fără impact de design — nimic din R-Sync-FLASH-01/02 presupunea sau necesita așa ceva.

### 13.2 Conflict real găsit #1 — coliziune de programare cu `daily.yml`, propunere de soluție

Fereastra Night Sync propusă inițial (§5: "02:00–05:00") **se suprapune cu `daily.yml`, care pornește la 03:00 UTC** (`cron: "0 3 * * *"`) și rulează, în aceeași execuție, `history_sync` → `feature_update` (`sync.backfill_features.run_backfill()`, recalculează exact mediile mobile care alimentează `corner_dominance`/`card_diff`/`foul_diff`/`shot_dominance` — vezi `R-SYNC-FLASH-01_PREDICTOR_IMPACT_ANALYSIS.md`) → `ml_retrain` (**deja există**, `PipelineStep("ml_retrain", depends_on=("feature_update",))`, `sync/run_daily.py`).

**Consecință dacă neschimbat**: dacă Flashscore Night Sync nu apucă să termine înainte ca `feature_update` să citească `match_history` în aceeași noapte, completarea de azi nu ajunge în recalcularea de azi — beneficiul se amână cu o zi, silențios, contrazicând exact așteptarea din cerere ("dacă azi s-au jucat meciuri... mâine dimineață... deja").

**Soluție propusă** (aleasă dintre 2 opțiuni evaluate):
- **Opțiunea A — integrare formală ca `PIPELINE_STEP`** (`flashscore_night_sync`, `depends_on=("history_sync",)`, extinde `feature_update` la `depends_on=("history_sync", "flashscore_night_sync")`) — corectitudine garantată de dependență, nu de presupunere temporală. **Respinsă pentru acum**: `run_daily.py` nu are azi un motor real de orchestrare cross-workflow (propriul docstring, PIPELINE_STEPS: "O adevărată orchestrare... rămâne o extindere viitoare, neaprobată acum") — un pas care necesită Playwright ar cere fie adăugarea browserului în job-ul existent `daily.yml` (risc asupra bugetului de 30 min deja alocat altor 12 pași), fie o coordonare cross-workflow pe care manifestul declarativ nu o impune azi (doar validează dependențe declarate, nu așteaptă alt workflow GitHub Actions).
- **Opțiunea B — workflow separat, fereastră de timp cu marjă generoasă, ALEASĂ**: Flashscore Night Sync rămâne un workflow GitHub Actions propriu (Playwright izolat, buget de timp propriu, fără să concureze cu cei 12+ pași deja din `daily.yml`), programat **înainte** de 03:00 UTC, cu plafon intern ferm (propunere: pornire `01:00 UTC`, timeout intern 90 min, deci finalizat cel târziu `02:30 UTC` — marjă de 30 min față de pornirea `daily.yml`). Mai puțin "corect" arhitectural decât Opțiunea A (garanție de timp, nu de dependență), dar realist azi, izolează eșecul (dacă Flashscore Night Sync pică, nu afectează deloc `daily.yml`), și nu cere nicio modificare a `run_daily.py` existent.
- **Plasă de siguranță, opțională, neimplementată acum**: `feature_update` ar putea verifica, informativ (nu blocant), dacă `acquisition_run_log` are o intrare Flashscore reușită din noaptea curentă, înainte de `01:00 UTC` — logare de avertisment dacă lipsește, fără să oprească pipeline-ul. Idee reținută pentru o etapă viitoare, nu parte a aprobării curente.

### 13.3 Clarificare (nu conflict de blocat, dar necesară în documentație) #2 — "ML se reantrenează automat" există deja

Verificat direct în cod: **`ml_retrain` e deja un `PIPELINE_STEP` activ** (`depends_on=("feature_update",)`) și `continuous_learning.yml` rulează deja zilnic (06:00 UTC) cu `learning_core_enabled=true` **deja activ** (`docs/00_GOVERNANCE/ARCHITECTURE_STATE.md`, confirmat live). **R-Sync-FLASH-02 nu introduce nicio automatizare nouă aici** — doar îmbunătățește datele de intrare pe care aceste procese, deja existente și deja aprobate, le consumă.

**Distincție care trebuie păstrată explicit, altfel riscă să fie înțeleasă greșit ulterior**: "Predictorul folosește deja datele noi" e adevărat **imediat** pentru componenta statistică/Poisson/ELO/formă (`oracle_engine._build_profile()`, verificat — citește live din `match_history`, fără cache/TTL intermediar) — dar pentru componenta **ML**, rămâne adevărat **doar după promovare manuală** a Challenger-ului antrenat cu datele noi (Champion Manager, ADR-002/ADR-016, neschimbat — "Not Implemented: Auto-promovare... fără om în buclă" din CLAUDE.md rămâne valabil, R-Sync-FLASH-02 nu-l atinge și nu-l ocolește). Diagrama din cerere ("retrain ML → Predictor") descrie corect fluxul de ANTRENARE automată (deja existent), nu o promovare automată (care nu există și nu se introduce aici).

### 13.4 Actualizare a interogării de gap-fill Night Sync (§5) — completare, nu schimbare de principiu

Interogarea originală din §5 nu enumera explicit `match_events`/`player_match_stats` ca declanșatori de gap-fill (doar coloanele `match_history`). Corectat aici — condiția de target pentru Night Sync devine:

```
WHERE actual_result IS NOT NULL
  AND kickoff_date >= now() - interval '4 days'   -- fereastra 3-4 zile, cf. cerinta
  AND (
    home_possession IS NULL OR home_shots IS NULL OR home_corners IS NULL
    OR home_goalkeeper_saves IS NULL OR referee IS NULL OR home_lineup IS NULL
    OR NOT EXISTS (SELECT 1 FROM match_events WHERE match_events.match_id = match_history.id)
    OR NOT EXISTS (SELECT 1 FROM player_match_stats WHERE player_match_stats.match_id = match_history.id)
  )
```

Regula de precedență (§1: dacă API/Open Data au deja completat un câmp, Flashscore nu se mai interoghează pentru el) rămâne identică — extinsă acum explicit și la `match_events`/`player_match_stats`, nu doar la coloanele `match_history`.

### 13.5 Ce rămâne neschimbat / neimplementat

- Niciun cod scris ca urmare a acestei secțiuni — analiză + actualizare documentație, cf. cerință explicită.
- Niciun Weight Manager Predictor/ML — confirmat, neintrodus.
- `tos_reviewed` neschimbat — Night Sync-ul real rămâne, la fel ca Bootstrap-ul, blocat de același gate (§12.0) până la o decizie separată.
- Planul de Stage 2 (§12) rămâne valabil neschimbat — integrarea de programare (§13.2) e o decizie de arhitectură pentru un Stage viitor (worker-ul de execuție), nu pentru mecanica cozii deja planificată acolo.

---

## 14. [R-ML-GATE-01, 2026-07-29] Activation Gate — pointer

Predictorul/ML/blending-ul rămân complet înghețate cât timp acest document e activ — nicio schimbare de acest fel nu face parte din roadmap-ul Flashscore. Condiții și stare curentă: `docs/00_GOVERNANCE/ML_ACTIVATION_GATE.md`. Prioritatea de dezvoltare, confirmată explicit: (1) provider Flashscore, (2) validare extractibilitate, (3) integrare pipeline, (4) colectare automată/populare bază, (5) monitorizare sincronizări — Stage 2 (§12) rămâne următorul pas concret, neschimbat, în așteptare de aprobare.
