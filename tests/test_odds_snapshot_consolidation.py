"""
Teste de regresie pentru INCIDENT 2026-07-17 (PGRST203) — consolidarea
supraincarcarii `upsert_odds_snapshot` prin migration 010.

Verifica empiric, pe un Postgres LOCAL efemer, ca dupa aplicarea migrarii 010:
  1. exista EXACT o singura functie `upsert_odds_snapshot` (ambiguitatea de
     supraincarcare care producea PGRST203 e eliminata la nivel de schema);
  2. apelul cu 6 parametri (calea zilnica OddsPersistenceService) reuseste si
     populeaza coloanele NOT NULL de provenance din DEFAULT-uri (fara violare);
  3. apelul cu 11 parametri (BackfillOddsService) scrie provenance explicit.

NU depinde de Supabase live: ruleaza contra unui Postgres LOCAL, efemer, indicat
prin `ADR025_TEST_PG_DSN`. Daca variabila nu e setata SAU psycopg2 nu e instalat,
intreg modulul e SKIP — deci `pytest tests/` implicit ramane verde si fara retea.
Testul incarca EXACT artefactele de productie 001 (schema odds_history +
coloane provenance) si 010 (consolidarea).
"""
import os
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

DSN = os.environ.get("ADR025_TEST_PG_DSN")
if not DSN:
    pytest.skip(
        "ADR025_TEST_PG_DSN nesetat — test pe Postgres local, optional",
        allow_module_level=True,
    )

MIG_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"
MIG_010 = MIG_DIR / "010_odds_snapshot_overload_consolidation.sql"

# Schema odds_history EXACT ca in productie (001 + coloanele provenance adaugate
# ad-hoc prin ADR-010): provider/import_type/import_version sunt NOT NULL fara
# default — exact conditia care face functia 6-arg incompatibila.
SCHEMA_DDL = """
DROP TABLE IF EXISTS odds_history CASCADE;
CREATE TABLE odds_history (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fixture_id text NOT NULL,
  bookmaker  text NOT NULL,
  opening_home numeric, opening_draw numeric, opening_away numeric,
  closing_home numeric, closing_draw numeric, closing_away numeric,
  opening_fetched_at timestamptz, closing_fetched_at timestamptz,
  provider text NOT NULL,
  import_type text NOT NULL,
  import_version text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now(),
  source_hash text, source_url text,
  CONSTRAINT odds_history_fixture_id_bookmaker_key UNIQUE (fixture_id, bookmaker)
);
-- Reproduce ambiguitatea de productie INAINTE de fix: cele doua supraincarcari.
CREATE OR REPLACE FUNCTION upsert_odds_snapshot(
    p_fixture_id text, p_bookmaker text, p_home numeric, p_draw numeric,
    p_away numeric, p_now timestamptz
) RETURNS boolean AS $$
BEGIN
    INSERT INTO odds_history (fixture_id, bookmaker, opening_home, opening_draw,
        opening_away, opening_fetched_at, closing_home, closing_draw, closing_away,
        closing_fetched_at)
    VALUES (p_fixture_id, p_bookmaker, p_home, p_draw, p_away, p_now,
        p_home, p_draw, p_away, p_now)
    ON CONFLICT (fixture_id, bookmaker) DO NOTHING;
    RETURN true;
END; $$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION upsert_odds_snapshot(
    p_fixture_id text, p_bookmaker text, p_home numeric, p_draw numeric,
    p_away numeric, p_now timestamptz,
    p_provider text DEFAULT 'the-odds-api', p_import_type text DEFAULT 'live_capture',
    p_import_version text DEFAULT 'OddsPersistenceService_v1',
    p_source_hash text DEFAULT NULL, p_source_url text DEFAULT NULL
) RETURNS boolean AS $$
BEGIN
    INSERT INTO odds_history (fixture_id, bookmaker, opening_home, opening_draw,
        opening_away, opening_fetched_at, closing_home, closing_draw, closing_away,
        closing_fetched_at, provider, import_type, import_version, imported_at,
        source_hash, source_url)
    VALUES (p_fixture_id, p_bookmaker, p_home, p_draw, p_away, p_now,
        p_home, p_draw, p_away, p_now, p_provider, p_import_type, p_import_version,
        p_now, p_source_hash, p_source_url)
    ON CONFLICT (fixture_id, bookmaker) DO NOTHING;
    RETURN true;
END; $$ LANGUAGE plpgsql;
"""


def _count_overloads(cur):
    cur.execute(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname='upsert_odds_snapshot'"
    )
    return cur.fetchone()[0]


@pytest.fixture()
def conn():
    c = psycopg2.connect(DSN)
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute(SCHEMA_DDL)
        yield c
    finally:
        c.close()


def test_precondition_two_overloads_exist(conn):
    """Sanity: reproducem starea de productie — doua supraincarcari coexista."""
    with conn.cursor() as cur:
        assert _count_overloads(cur) == 2


def test_migration_010_leaves_exactly_one_function(conn):
    """Dupa 010: o singura functie -> zero ambiguitate de rezolvare (PGRST203)."""
    with conn.cursor() as cur:
        cur.execute(MIG_010.read_text())
        assert _count_overloads(cur) == 1
        # ...si e varianta cu 11 parametri (provenance-aware).
        cur.execute(
            "SELECT pronargs FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname='upsert_odds_snapshot'"
        )
        assert cur.fetchone()[0] == 11


def test_six_arg_call_populates_notnull_provenance_defaults(conn):
    """Calea zilnica (6 params) reuseste dupa 010 si umple coloanele NOT NULL
    din DEFAULT-uri — exact ce functia 6-arg nu putea face."""
    with conn.cursor() as cur:
        cur.execute(MIG_010.read_text())
        cur.execute(
            "SELECT upsert_odds_snapshot(%s,%s,%s,%s,%s,now())",
            ("fx_live_1", "bk_live", 2.0, 3.2, 3.5),
        )
        assert cur.fetchone()[0] is True
        cur.execute(
            "SELECT provider, import_type, import_version, imported_at IS NOT NULL "
            "FROM odds_history WHERE fixture_id='fx_live_1'"
        )
        row = cur.fetchone()
        assert row == ("the-odds-api", "live_capture", "OddsPersistenceService_v1", True)


def test_eleven_arg_call_writes_explicit_provenance(conn):
    """Calea de backfill (11 params) scrie provenance explicit, neschimbata."""
    with conn.cursor() as cur:
        cur.execute(MIG_010.read_text())
        cur.execute(
            "SELECT upsert_odds_snapshot(%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s)",
            ("fx_bf_1", "bk_bf", 1.8, 3.4, 4.1,
             "football-data.co.uk", "historical_backfill", "BackfillOddsService_v1",
             "deadbeef", "http://example/odds.csv"),
        )
        assert cur.fetchone()[0] is True
        cur.execute(
            "SELECT provider, import_type, source_hash, source_url "
            "FROM odds_history WHERE fixture_id='fx_bf_1'"
        )
        assert cur.fetchone() == (
            "football-data.co.uk", "historical_backfill", "deadbeef",
            "http://example/odds.csv",
        )
