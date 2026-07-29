# R-Sync-FLASH-01 — Flashscore ca Provider Auxiliar UDAL

**Status**: DESIGN, neimplementat. Nu s-a rulat niciun scraping live, nu s-a aplicat nicio migrare Supabase, `tos_reviewed` rămâne `False`.
**Cerut**: "R-SYNC-FLASH-01 — Flashscore as Auxiliary UDAL Provider" (după POC-ul cu 10 meciuri, `UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md`, recomandare B — sursă auxiliară).

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
