-- =============================================================================
-- Football Oracle — Migration 023: scheduled_fixtures (R-Sync-7a, ADR-039)
-- =============================================================================
-- Implementeaza tabela + RPC de merge din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md (§ R-Sync-7 audit)
--
-- Scop STRICT: identitatea CANONICA a unui meci descoperit ("ce meciuri
-- exista"), populata de Sync Layer, prin cate un adaptor per provider de
-- descoperire (FreeLF, Odds API, football-data.org, ESPN, TheSportsDB,
-- API-Football). Oracle Engine NU scrie niciodata aici — in R-Sync-7a NU
-- CITESTE inca de aici (ramane pe cascada veche live, neschimbata) — asta
-- e R-Sync-7b, separat.
--
-- GASIT LA AUDIT (nu presupus, demonstrat prin cod + simulare reala):
-- get_matches_for_week() dedupica azi prin match_key() cu semantica
-- "primul provider caștiga" (_add(), oracle_api.py) — ID-urile de
-- provider ale oricarui provider care NU a fost primul (freelf_event_id,
-- tsdb_*_id, etc.) sunt PIERDUTE definitiv. Exact aceasta pierdere tine
-- blocate R-Sync-8 (FreeLF H2H, TSDB team stats). Tabela de fata NU
-- reproduce acel bug — foloseste MERGE la nivel de camp (o identitate
-- canonica, N identificatori de provider), prin RPC dedicat
-- (upsert_scheduled_fixture_merge), nu prin INSERT/UPSERT simplu care ar
-- suprascrie randul intreg.
--
-- Identitate canonica: (home_team_canonical, away_team_canonical,
-- kickoff_date) — EXACT forma cheii naturale de Match deja Frozen
-- (ADR-024/ADR-025), fara liga in cheie, reutilizata deja de
-- odds_api_recent_results (migrare 022).
--
-- FixtureMergePolicy (aplicata STRICT in RPC, niciodata in Python/adaptor
-- — "adaptorul trimite doar campurile lui, RPC decide", decizie explicita
-- proprietar produs):
--   1. Coloanele proprii per provider (freelf_*, odds_api_*, apifootball_*,
--      tsdb_*, fd_*, espn_*) — owner unic, COALESCE(existent, nou), NU se
--      suprascrie niciodata, NU se sterge niciodata.
--   2. `status` — ultima scriere caștiga (singurul camp care se schimba
--      legitim in timp: scheduled -> live -> finished).
--   3. `league`, `venue_city`, `kickoff_utc` — camp GUVERNAT de
--      SourcePriority (rank fix per provider, INDEPENDENT de ordinea de
--      executie a sincronizarii — o schimbare viitoare a ordinii
--      providerilor NU trebuie sa schimbe rezultatul mergeului):
--        - `league`: freelf=espn=tsdb=apifootball=oddsapi (rank 1, toate
--          canonice PRIN CONSTRUCTIE — primesc liga ca parametru de
--          intrare sau prin mapare statica deja verificata) > footballdata
--          (rank 2 — GASIT LA AUDIT: _fetch_matches_fd() NU aplica
--          normalize_league_name() pe numele brut al competitiei,
--          confirmat prin grep, singurul provider cu acest gol).
--        - `venue_city`: freelf (rank 1) > espn (rank 2) > apifootball
--          (rank 3) > footballdata (rank 4 — GASIT la audit R-Sync-5:
--          `area.name` e tara, nu orasul) > tsdb/oddsapi (rank 5, nu
--          furnizeaza niciodata azi).
--        - `kickoff_utc`: NICIO ierarhie semantica de calitate — nicio
--          dovada obiectiva ca vreun provider ar avea ore gresite (spre
--          deosebire de league/venue_city, unde dovada exista). Rank
--          DETERMINIST, arbitrar, doar pentru reproductibilitate:
--          apifootball(1) < espn(2) < footballdata(3) < freelf(4) <
--          oddsapi(5) < tsdb(6). Daca apare vreodata dovada masurabila ca
--          un provider are ore sistematic gresite, regula se schimba
--          ATUNCI, pe baza dovezii — nu presupusa acum.
--      Provenienta valorii curente per camp guvernat e tinuta in
--      `field_provenance` (JSONB) — necesara ca sa poata compara rank-ul
--      noii surse cu rank-ul sursei care detine azi valoarea, nu doar
--      "primul care scrie caștiga" (ar reintroduce dependenta de ordinea
--      de executie, exact ce s-a cerut explicit sa se evite).
--
-- `source_mask` (JSONB, {"freelf": true, ...}) + `merge_count` (INTEGER)
-- — adaugate la cererea explicita a proprietarului produsului, nu
-- necesare pentru R-Sync-7a functional, dar utile termen lung (debugging,
-- audit, statistici de acoperire) — cost minim acum.
--
-- Demo mode (_generate_demo_matches()) — EXCLUS explicit, niciun adaptor
-- de discovery nu se construieste pentru el; ramane exclusiv pe calea
-- veche, locala, neatinsa (Regula #8: nu se inventeaza date).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar
-- ca 001..022. Nu atinge nicio tabela existenta. RPC-ul ruleaza cu
-- privilegiile apelantului (service_role, prin Sync Layer) — nu SECURITY
-- DEFINER, consistent cu restul proiectului (nicio scriere ocolind RLS
-- prin alte cai).
-- =============================================================================

CREATE TABLE IF NOT EXISTS scheduled_fixtures (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Identitate canonica (ADR-024/025) — fara liga in cheie.
    home_team_canonical         TEXT NOT NULL,
    away_team_canonical         TEXT NOT NULL,
    kickoff_date                DATE NOT NULL,

    -- Campuri partajate, guvernate de SourcePriority (vezi comentariul de mai sus).
    league                      TEXT,
    kickoff_utc                 TIMESTAMPTZ,
    venue_city                  TEXT,
    status                      TEXT NOT NULL DEFAULT 'scheduled',
    field_provenance            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- FreeLF — owner unic per coloana.
    freelf_event_id              TEXT,
    freelf_home_team_id          TEXT,
    freelf_away_team_id          TEXT,
    freelf_coverage_level        TEXT,

    -- Odds API.
    odds_api_event_id            TEXT,
    odds_api_sport_key           TEXT,

    -- API-Football.
    apifootball_fixture_id       TEXT,
    apifootball_home_team_id     TEXT,
    apifootball_away_team_id     TEXT,

    -- TheSportsDB.
    tsdb_home_team_id            TEXT,
    tsdb_away_team_id            TEXT,

    -- football-data.org.
    fd_home_team_id              TEXT,
    fd_away_team_id               TEXT,

    -- ESPN.
    espn_home_team_id             TEXT,
    espn_away_team_id             TEXT,

    -- Metadate de trasabilitate a merge-ului.
    source_mask                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    merge_count                  INTEGER NOT NULL DEFAULT 0,

    first_seen_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_merged_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT scheduled_fixtures_unique_match
        UNIQUE (home_team_canonical, away_team_canonical, kickoff_date)
);

CREATE INDEX IF NOT EXISTS idx_scheduled_fixtures_kickoff_date
    ON scheduled_fixtures (kickoff_date);

CREATE INDEX IF NOT EXISTS idx_scheduled_fixtures_last_merged_at
    ON scheduled_fixtures (last_merged_at);

ALTER TABLE scheduled_fixtures ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- RPC: upsert_scheduled_fixture_merge — TOATA logica FixtureMergePolicy
-- traieste aici, un singur loc, folosit identic de toate cele 6 adaptoare.
-- Adaptorul trimite doar campurile pe care le are (restul raman NULL,
-- ignorate); RPC-ul decide ce se scrie si ce nu.
-- =============================================================================

CREATE OR REPLACE FUNCTION upsert_scheduled_fixture_merge(
    p_home_team_canonical         TEXT,
    p_away_team_canonical         TEXT,
    p_kickoff_date                DATE,
    p_provider_id                 TEXT,   -- 'freelf' | 'oddsapi' | 'apifootball' | 'tsdb' | 'fd' | 'espn'
    p_league                      TEXT DEFAULT NULL,
    p_kickoff_utc                 TIMESTAMPTZ DEFAULT NULL,
    p_venue_city                  TEXT DEFAULT NULL,
    p_status                      TEXT DEFAULT NULL,
    p_freelf_event_id             TEXT DEFAULT NULL,
    p_freelf_home_team_id         TEXT DEFAULT NULL,
    p_freelf_away_team_id         TEXT DEFAULT NULL,
    p_freelf_coverage_level       TEXT DEFAULT NULL,
    p_odds_api_event_id           TEXT DEFAULT NULL,
    p_odds_api_sport_key          TEXT DEFAULT NULL,
    p_apifootball_fixture_id      TEXT DEFAULT NULL,
    p_apifootball_home_team_id    TEXT DEFAULT NULL,
    p_apifootball_away_team_id    TEXT DEFAULT NULL,
    p_tsdb_home_team_id           TEXT DEFAULT NULL,
    p_tsdb_away_team_id           TEXT DEFAULT NULL,
    p_fd_home_team_id             TEXT DEFAULT NULL,
    p_fd_away_team_id             TEXT DEFAULT NULL,
    p_espn_home_team_id           TEXT DEFAULT NULL,
    p_espn_away_team_id           TEXT DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_id                BIGINT;
    v_provenance         JSONB;
    v_new_league_rank    INT;
    v_new_venue_rank     INT;
    v_new_kickoff_rank   INT;
    v_cur_league_rank    INT;
    v_cur_venue_rank     INT;
    v_cur_kickoff_rank   INT;
    v_final_provenance   JSONB;
BEGIN
    -- Rank-uri SourcePriority pentru sursa NOUA (p_provider_id).
    -- Rank mai mic = prioritate mai mare. Vezi justificarea completa,
    -- pe dovezi, in comentariul de la inceputul fisierului.
    v_new_league_rank  := CASE WHEN p_provider_id = 'fd' THEN 2 ELSE 1 END;
    v_new_venue_rank   := CASE p_provider_id
                             WHEN 'freelf' THEN 1
                             WHEN 'espn' THEN 2
                             WHEN 'apifootball' THEN 3
                             WHEN 'fd' THEN 4
                             ELSE 5 END;
    v_new_kickoff_rank := CASE p_provider_id
                             WHEN 'apifootball' THEN 1
                             WHEN 'espn' THEN 2
                             WHEN 'fd' THEN 3
                             WHEN 'freelf' THEN 4
                             WHEN 'oddsapi' THEN 5
                             WHEN 'tsdb' THEN 6
                             ELSE 7 END;

    SELECT id, field_provenance INTO v_id, v_provenance
    FROM scheduled_fixtures
    WHERE home_team_canonical = p_home_team_canonical
      AND away_team_canonical = p_away_team_canonical
      AND kickoff_date = p_kickoff_date
    FOR UPDATE;

    IF v_id IS NULL THEN
        -- Rand nou — orice camp guvernat prezent devine automat cel mai
        -- bun disponibil (nimic de comparat inca).
        --
        -- [GASIT LA TESTAREA LIVE, scenariul 8 — concurenta] "SELECT ...
        -- FOR UPDATE" de mai sus protejeaza DOAR randurile deja existente
        -- — nu previne cursa pe PRIMUL insert: doi provideri care
        -- descopera simultan acelasi meci NOU ar vedea amandoi v_id IS
        -- NULL inainte ca vreunul sa fi scris, iar al doilea INSERT ar
        -- fi esuat cu violare UNIQUE, necaptata. "ON CONFLICT ... DO
        -- NOTHING RETURNING id" rezolva asta explicit: daca insertul
        -- pierde cursa, cade pe calea normala de merge de mai jos, in
        -- loc sa arunce o exceptie.
        INSERT INTO scheduled_fixtures (
            home_team_canonical, away_team_canonical, kickoff_date,
            league, kickoff_utc, venue_city, status, field_provenance,
            freelf_event_id, freelf_home_team_id, freelf_away_team_id, freelf_coverage_level,
            odds_api_event_id, odds_api_sport_key,
            apifootball_fixture_id, apifootball_home_team_id, apifootball_away_team_id,
            tsdb_home_team_id, tsdb_away_team_id,
            fd_home_team_id, fd_away_team_id,
            espn_home_team_id, espn_away_team_id,
            source_mask, merge_count, first_seen_at, last_merged_at
        ) VALUES (
            p_home_team_canonical, p_away_team_canonical, p_kickoff_date,
            p_league, p_kickoff_utc, p_venue_city, COALESCE(p_status, 'scheduled'),
            jsonb_strip_nulls(jsonb_build_object(
                'league',      CASE WHEN p_league IS NOT NULL THEN p_provider_id END,
                'venue_city',  CASE WHEN p_venue_city IS NOT NULL THEN p_provider_id END,
                'kickoff_utc', CASE WHEN p_kickoff_utc IS NOT NULL THEN p_provider_id END
            )),
            p_freelf_event_id, p_freelf_home_team_id, p_freelf_away_team_id, p_freelf_coverage_level,
            p_odds_api_event_id, p_odds_api_sport_key,
            p_apifootball_fixture_id, p_apifootball_home_team_id, p_apifootball_away_team_id,
            p_tsdb_home_team_id, p_tsdb_away_team_id,
            p_fd_home_team_id, p_fd_away_team_id,
            p_espn_home_team_id, p_espn_away_team_id,
            jsonb_build_object(p_provider_id, true), 1, now(), now()
        )
        ON CONFLICT (home_team_canonical, away_team_canonical, kickoff_date) DO NOTHING
        RETURNING id INTO v_id;

        IF v_id IS NOT NULL THEN
            RETURN;  -- am câștigat cursa, insert-ul a reușit
        END IF;

        -- Am pierdut cursa — altcineva a inserat între timp. Recitim
        -- rândul (acum există) și trecem pe calea normală de merge.
        SELECT id, field_provenance INTO v_id, v_provenance
        FROM scheduled_fixtures
        WHERE home_team_canonical = p_home_team_canonical
          AND away_team_canonical = p_away_team_canonical
          AND kickoff_date = p_kickoff_date
        FOR UPDATE;
    END IF;

    -- Rand existent — coloanele proprii per provider: COALESCE strict,
    -- NU se suprascriu niciodata (owner unic per coloana).
    UPDATE scheduled_fixtures SET
        freelf_event_id            = COALESCE(freelf_event_id, p_freelf_event_id),
        freelf_home_team_id        = COALESCE(freelf_home_team_id, p_freelf_home_team_id),
        freelf_away_team_id        = COALESCE(freelf_away_team_id, p_freelf_away_team_id),
        freelf_coverage_level      = COALESCE(freelf_coverage_level, p_freelf_coverage_level),
        odds_api_event_id          = COALESCE(odds_api_event_id, p_odds_api_event_id),
        odds_api_sport_key         = COALESCE(odds_api_sport_key, p_odds_api_sport_key),
        apifootball_fixture_id     = COALESCE(apifootball_fixture_id, p_apifootball_fixture_id),
        apifootball_home_team_id   = COALESCE(apifootball_home_team_id, p_apifootball_home_team_id),
        apifootball_away_team_id   = COALESCE(apifootball_away_team_id, p_apifootball_away_team_id),
        tsdb_home_team_id          = COALESCE(tsdb_home_team_id, p_tsdb_home_team_id),
        tsdb_away_team_id          = COALESCE(tsdb_away_team_id, p_tsdb_away_team_id),
        fd_home_team_id            = COALESCE(fd_home_team_id, p_fd_home_team_id),
        fd_away_team_id            = COALESCE(fd_away_team_id, p_fd_away_team_id),
        espn_home_team_id          = COALESCE(espn_home_team_id, p_espn_home_team_id),
        espn_away_team_id          = COALESCE(espn_away_team_id, p_espn_away_team_id),
        -- status: ultima scriere caștiga necondiționat (singurul camp
        -- care se schimba legitim in timp).
        status                     = COALESCE(p_status, status),
        source_mask                = source_mask || jsonb_build_object(p_provider_id, true),
        merge_count                = merge_count + 1,
        last_merged_at             = now()
    WHERE id = v_id;

    -- Campuri guvernate de SourcePriority — comparam rank-ul sursei NOI
    -- cu rank-ul sursei care detine AZI valoarea (din field_provenance),
    -- NU cu ordinea de executie. Daca nu exista inca nicio sursa
    -- (provenance lipsa) SAU sursa noua are rank mai bun (numar mai mic),
    -- suprascriem valoarea SI provenienta.
    -- [IMPORTANT] Forma CAUTATA (CASE WHEN ... IS NULL ...), nu simpla —
    -- "CASE x WHEN NULL THEN ..." e cod mort in SQL (NULL = NULL nu e
    -- niciodata TRUE), ar fi cazut tacit pe ELSE si ar fi dat un rank
    -- gresit in loc de "nicio sursa inca" — verificat si corectat inainte
    -- de a aplica migrarea.
    v_cur_league_rank  := CASE
                             WHEN v_provenance->>'league' IS NULL THEN NULL
                             WHEN v_provenance->>'league' = 'fd' THEN 2
                             ELSE 1 END;
    v_cur_venue_rank   := CASE
                             WHEN v_provenance->>'venue_city' IS NULL THEN NULL
                             WHEN v_provenance->>'venue_city' = 'freelf' THEN 1
                             WHEN v_provenance->>'venue_city' = 'espn' THEN 2
                             WHEN v_provenance->>'venue_city' = 'apifootball' THEN 3
                             WHEN v_provenance->>'venue_city' = 'fd' THEN 4
                             ELSE 5 END;
    v_cur_kickoff_rank := CASE
                             WHEN v_provenance->>'kickoff_utc' IS NULL THEN NULL
                             WHEN v_provenance->>'kickoff_utc' = 'apifootball' THEN 1
                             WHEN v_provenance->>'kickoff_utc' = 'espn' THEN 2
                             WHEN v_provenance->>'kickoff_utc' = 'fd' THEN 3
                             WHEN v_provenance->>'kickoff_utc' = 'freelf' THEN 4
                             WHEN v_provenance->>'kickoff_utc' = 'oddsapi' THEN 5
                             WHEN v_provenance->>'kickoff_utc' = 'tsdb' THEN 6
                             ELSE 7 END;

    v_final_provenance := v_provenance;

    IF p_league IS NOT NULL AND (v_cur_league_rank IS NULL OR v_new_league_rank < v_cur_league_rank) THEN
        UPDATE scheduled_fixtures SET league = p_league WHERE id = v_id;
        v_final_provenance := jsonb_set(v_final_provenance, '{league}', to_jsonb(p_provider_id));
    END IF;

    IF p_venue_city IS NOT NULL AND (v_cur_venue_rank IS NULL OR v_new_venue_rank < v_cur_venue_rank) THEN
        UPDATE scheduled_fixtures SET venue_city = p_venue_city WHERE id = v_id;
        v_final_provenance := jsonb_set(v_final_provenance, '{venue_city}', to_jsonb(p_provider_id));
    END IF;

    IF p_kickoff_utc IS NOT NULL AND (v_cur_kickoff_rank IS NULL OR v_new_kickoff_rank < v_cur_kickoff_rank) THEN
        UPDATE scheduled_fixtures SET kickoff_utc = p_kickoff_utc WHERE id = v_id;
        v_final_provenance := jsonb_set(v_final_provenance, '{kickoff_utc}', to_jsonb(p_provider_id));
    END IF;

    IF v_final_provenance IS DISTINCT FROM v_provenance THEN
        UPDATE scheduled_fixtures SET field_provenance = v_final_provenance WHERE id = v_id;
    END IF;
END;
$$;
