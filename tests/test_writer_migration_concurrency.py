"""
Teste de concurenta pentru Writer Migration (ID-025-03), criteriile V-06..V-08
+ testul compus V-11 din ID-025-05. Verifica empiric ca pg_advisory_xact_lock
serializeaza scrierile concurente pe aceeasi cheie naturala si ca nu se creeaza
niciodata un al doilea rand fizic (race-safe INDEPENDENT de constrangerea UNIQUE).

NU depind de Supabase live: ruleaza contra unui Postgres LOCAL, efemer, indicat
prin variabila de mediu `ADR025_TEST_PG_DSN` (ex. "host=127.0.0.1 port=54329
user=postgres dbname=postgres"). Daca variabila nu e setata SAU psycopg2 nu e
instalat, intreg modulul e SKIP — deci `pytest tests/` implicit ramane verde si
fara retea. Testele incarca EXACT artefactul de productie
`database/migrations/008_match_canonical_upsert.sql`.
"""
import json
import os
import threading
import time
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

DSN = os.environ.get("ADR025_TEST_PG_DSN")
if not DSN:
    pytest.skip(
        "ADR025_TEST_PG_DSN nesetat — teste de concurenta pe Postgres local, optionale",
        allow_module_level=True,
    )

MIGRATION = Path(__file__).resolve().parent.parent / "database" / "migrations" / "008_match_canonical_upsert.sql"

SCHEMA_DDL = """
DROP TABLE IF EXISTS match_history CASCADE;
CREATE TABLE match_history (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fixture_id text NOT NULL,
  home_team text NOT NULL, away_team text NOT NULL, league text NOT NULL,
  kickoff_date text,
  home_xg_pred numeric, away_xg_pred numeric,
  home_offensive_rating numeric, home_defensive_rating numeric,
  away_offensive_rating numeric, away_defensive_rating numeric,
  home_form_score numeric, away_form_score numeric,
  home_elo integer, away_elo integer,
  h2h_modifier numeric, h2h_meetings integer, weather_penalty numeric,
  home_data_quality text, away_data_quality text,
  prob_home_pred numeric, prob_draw_pred numeric, prob_away_pred numeric,
  mc_prob_home numeric, mc_prob_draw numeric, mc_prob_away numeric,
  actual_home_goals integer, actual_away_goals integer, actual_result text,
  used_for_training boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  backfill_done boolean NOT NULL DEFAULT false,
  home_xg_actual numeric, away_xg_actual numeric,
  home_possession numeric, away_possession numeric,
  home_shots integer, away_shots integer,
  home_shots_on_target integer, away_shots_on_target integer, stats_source text,
  home_fouls integer, away_fouls integer, home_corners integer, away_corners integer,
  home_yellow_cards integer, away_yellow_cards integer, home_red_cards integer, away_red_cards integer,
  home_ht_goals integer, away_ht_goals integer,
  home_corner_avg_recent numeric, away_corner_avg_recent numeric,
  home_card_avg_recent numeric, away_card_avg_recent numeric,
  home_foul_avg_recent numeric, away_foul_avg_recent numeric,
  home_shot_avg_recent numeric, away_shot_avg_recent numeric,
  home_elo_after integer, away_elo_after integer,
  superseded_by bigint REFERENCES match_history(id),
  superseded_at timestamptz, superseded_reason text,
  CONSTRAINT match_history_fixture_id_key UNIQUE (fixture_id)
);
-- Indexul natural-key UNIQUE PARTIAL (ID-025-04 / Gate-08) — backstop pasiv:
-- RPC-ul migrat nu produce oricum duplicate (lock advisory), dar indexul
-- garanteaza structural aceeasi proprietate pentru orice cale care ar ocoli RPC-ul.
CREATE UNIQUE INDEX idx_match_history_natural_key_canonical
  ON match_history (home_team, away_team, kickoff_date)
  WHERE superseded_by IS NULL;
"""


def _conn(autocommit=True):
    c = psycopg2.connect(DSN)
    c.autocommit = autocommit
    return c


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
    c = _conn()
    cur = c.cursor()
    cur.execute(SCHEMA_DDL)
    cur.execute(MIGRATION.read_text())
    c.close()
    yield


@pytest.fixture(autouse=True)
def _reset():
    c = _conn()
    c.cursor().execute("TRUNCATE match_history RESTART IDENTITY CASCADE")
    c.close()
    yield


def _rpc(cur, payload):
    cur.execute("SELECT upsert_match_canonical(%s::jsonb)", (json.dumps(payload),))
    return cur.fetchone()[0]


def _count(h, a, d, live_only=False):
    c = _conn(); cur = c.cursor()
    q = ("SELECT count(*) FROM match_history WHERE lower(trim(home_team))=lower(trim(%s)) "
         "AND lower(trim(away_team))=lower(trim(%s)) AND left(kickoff_date,10)=%s")
    if live_only:
        q += " AND superseded_by IS NULL"
    cur.execute(q, (h, a, d)); n = cur.fetchone()[0]; c.close(); return n


def _row(h, a, d):
    c = _conn(); cur = c.cursor()
    cur.execute("SELECT home_shots, away_shots, actual_result FROM match_history "
                "WHERE lower(trim(home_team))=lower(trim(%s)) AND lower(trim(away_team))=lower(trim(%s)) "
                "AND left(kickoff_date,10)=%s AND superseded_by IS NULL", (h, a, d))
    r = cur.fetchone(); c.close(); return r


def _controlled_race(p1, p2, use_bulk_for_2=False):
    """t1 deschide tranzactie, apeleaza RPC (achizitioneaza lock-ul advisory,
    face scrierea), si TINE tranzactia deschisa. t2 apeleaza RPC pentru aceeasi
    cheie intr-un thread -> trebuie sa BLOCHEZE pe lock. Verificam ca t2 e blocat,
    apoi t1 face commit -> t2 continua. Intoarce (r1, r2, t2_a_fost_blocat)."""
    c1 = _conn(autocommit=False); cur1 = c1.cursor()
    r1 = _rpc(cur1, p1)  # lock tinut, tranzactie deschisa
    box = {}

    def worker():
        c2 = _conn(autocommit=False); cur2 = c2.cursor()
        if use_bulk_for_2:
            cur2.execute("SELECT upsert_matches_canonical(%s::jsonb)", (json.dumps([p2]),))
        else:
            cur2.execute("SELECT upsert_match_canonical(%s::jsonb)", (json.dumps(p2),))
        box["r2"] = cur2.fetchone()[0]; c2.commit(); c2.close()

    th = threading.Thread(target=worker); th.start()
    time.sleep(1.0)
    blocked = th.is_alive()  # inca blocat pe lock-ul tinut de c1
    c1.commit()              # elibereaza lock-ul
    th.join(timeout=10)
    c1.close()
    return r1, box.get("r2"), blocked


# ── Functional ───────────────────────────────────────────────────────────────

def test_insert_then_update_fills_only_nulls():
    base = dict(fixture_id="fd_1", home_team="Arsenal", away_team="Chelsea",
                league="PL", kickoff_date="2025-03-01")
    c = _conn(); cur = c.cursor()
    assert _rpc(cur, {**base, "home_shots": 10})["action"] == "insert"
    assert _rpc(cur, {**base, "fixture_id": "kaggle_x", "away_shots": 7})["action"] == "update"
    assert _count("Arsenal", "Chelsea", "2025-03-01") == 1
    r = _row("Arsenal", "Chelsea", "2025-03-01")
    assert r[0] == 10 and r[1] == 7  # both filled
    # Writer Protection: existing non-null never overwritten
    _rpc(cur, {**base, "home_shots": 999})
    assert _row("Arsenal", "Chelsea", "2025-03-01")[0] == 10
    c.close()


def test_hard_conflict_not_written():
    base = dict(fixture_id="fd_1", home_team="A", away_team="B", league="L", kickoff_date="2025-01-01")
    c = _conn(); cur = c.cursor()
    _rpc(cur, {**base, "actual_result": "H", "actual_home_goals": 2, "actual_away_goals": 1})
    r = _rpc(cur, {**base, "fixture_id": "kaggle_y", "actual_result": "A",
                   "actual_home_goals": 0, "actual_away_goals": 3})
    assert r["action"] == "hard_conflict"
    assert _row("A", "B", "2025-01-01")[2] == "H"  # unchanged
    assert _count("A", "B", "2025-01-01") == 1
    c.close()


def test_superseded_row_never_revived():
    c = _conn(); cur = c.cursor()
    cur.execute("INSERT INTO match_history (fixture_id,home_team,away_team,league,kickoff_date) "
                "VALUES ('fd_can','Bayern','Porto','CL','2025-04-01') RETURNING id")
    canid = cur.fetchone()[0]
    cur.execute("INSERT INTO match_history (fixture_id,home_team,away_team,league,kickoff_date,"
                "superseded_by,superseded_at,superseded_reason) "
                "VALUES ('kaggle_sup','Bayern','Porto','CL','2025-04-01',%s,now(),'t') RETURNING id", (canid,))
    supid = cur.fetchone()[0]
    r = _rpc(cur, {"fixture_id": "espn_new", "home_team": "Bayern", "away_team": "Porto",
                   "league": "CL", "kickoff_date": "2025-04-01", "home_shots": 5})
    assert r["action"] == "update" and r["id"] == canid
    cur.execute("SELECT home_shots FROM match_history WHERE id=%s", (supid,))
    assert cur.fetchone()[0] is None  # superseded row untouched
    c.close()


def test_batch_merges_intra_batch_duplicate():
    c = _conn(); cur = c.cursor()
    cur.execute("SELECT upsert_matches_canonical(%s::jsonb)", (json.dumps([
        {"fixture_id": "fd_a", "home_team": "A", "away_team": "B", "league": "L",
         "kickoff_date": "2025-01-01", "home_shots": 1},
        {"fixture_id": "fd_b", "home_team": "C", "away_team": "D", "league": "L", "kickoff_date": "2025-01-02"},
        {"fixture_id": "kaggle_a", "home_team": "A", "away_team": "B", "league": "L",
         "kickoff_date": "2025-01-01", "away_shots": 2},
    ]),))
    res = cur.fetchone()[0]
    assert res["inserted"] == 2 and res["updated"] == 1
    assert _count("A", "B", "2025-01-01") == 1
    r = _row("A", "B", "2025-01-01")
    assert r[0] == 1 and r[1] == 2
    c.close()


# ── Concurenta (ID-025-05) ───────────────────────────────────────────────────

def test_V06_two_writers_complementary_fields():
    p1 = {"fixture_id": "fd_1", "home_team": "X", "away_team": "Y", "league": "L",
          "kickoff_date": "2025-05-01", "home_shots": 11}
    p2 = {"fixture_id": "kaggle_1", "home_team": "X", "away_team": "Y", "league": "L",
          "kickoff_date": "2025-05-01", "away_shots": 4}
    r1, r2, blocked = _controlled_race(p1, p2)
    assert blocked, "t2 trebuie sa blocheze pe lock-ul advisory tinut de t1"
    assert _count("X", "Y", "2025-05-01") == 1
    r = _row("X", "Y", "2025-05-01")
    assert r[0] == 11 and r[1] == 4
    assert r1["action"] == "insert" and r2["action"] == "update"


def test_V07_identical_payloads_second_is_noop():
    p = {"fixture_id": "fd_2", "home_team": "P", "away_team": "Q", "league": "L",
         "kickoff_date": "2025-06-01", "home_shots": 8, "away_shots": 9}
    r1, r2, blocked = _controlled_race(p, dict(p))
    assert blocked
    assert _count("P", "Q", "2025-06-01") == 1
    assert r2["action"] == "update"  # no-op, fara eroare, fara al doilea rand


def test_V08_both_new_no_existing_row_single_insert():
    # Exact scenariul pentru care s-a ales pg_advisory_xact_lock: SELECT FOR
    # UPDATE nu ar fi putut bloca aici (nu exista inca niciun rand de blocat).
    p1 = {"fixture_id": "fd_3", "home_team": "M", "away_team": "N", "league": "L",
          "kickoff_date": "2025-07-01", "home_shots": 3}
    p2 = {"fixture_id": "kaggle_3", "home_team": "M", "away_team": "N", "league": "L",
          "kickoff_date": "2025-07-01", "home_corner_avg_recent": 6}
    r1, r2, blocked = _controlled_race(p1, p2)
    assert blocked
    assert r1["action"] == "insert" and r2["action"] == "update"
    assert _count("M", "N", "2025-07-01") == 1


def test_V11_compound_bulk_and_single_concurrent():
    p1 = {"fixture_id": "fd_4", "home_team": "S", "away_team": "T", "league": "L",
          "kickoff_date": "2025-08-01", "home_shots": 2}
    p2 = {"fixture_id": "kaggle_4", "home_team": "S", "away_team": "T", "league": "L",
          "kickoff_date": "2025-08-01", "away_shots": 5}
    r1, r2, blocked = _controlled_race(p1, p2, use_bulk_for_2=True)
    assert blocked
    assert _count("S", "T", "2025-08-01") == 1
    r = _row("S", "T", "2025-08-01")
    assert r[0] == 2 and r[1] == 5


def test_V10_direct_insert_bypassing_rpc_violates_unique_index():
    # ID-025-05 V-10 / ID-025-04 "Comportament la violare": o scriere directa
    # care ocoleste RPC-ul, pentru o cheie naturala deja canonica, esueaza dur cu
    # violare a indexului unic partial — backstop-ul pasiv.
    c = _conn(); cur = c.cursor()
    _rpc(cur, {"fixture_id": "fd_10", "home_team": "Aa", "away_team": "Bb", "league": "L",
               "kickoff_date": "2025-10-01"})
    c2 = _conn(autocommit=True); cur2 = c2.cursor()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur2.execute(
            "INSERT INTO match_history (fixture_id,home_team,away_team,league,kickoff_date) "
            "VALUES ('kaggle_10','Aa','Bb','L','2025-10-01')")
    c2.close(); c.close()


def test_V10_superseded_row_coexists_with_canonical_key():
    # Indexul e PARTIAL (WHERE superseded_by IS NULL): un rand superseded poate
    # coexista cu cheia naturala a canonicului sau, fara sa violeze indexul.
    c = _conn(autocommit=True); cur = c.cursor()
    cur.execute("INSERT INTO match_history (fixture_id,home_team,away_team,league,kickoff_date) "
                "VALUES ('fd_c','Cc','Dd','L','2025-11-01') RETURNING id")
    canid = cur.fetchone()[0]
    # inserarea unui rand superseded cu ACEEASI cheie naturala nu esueaza
    cur.execute("INSERT INTO match_history (fixture_id,home_team,away_team,league,kickoff_date,"
                "superseded_by,superseded_at,superseded_reason) "
                "VALUES ('kaggle_c','Cc','Dd','L','2025-11-01',%s,now(),'t')", (canid,))
    assert _count("Cc", "Dd", "2025-11-01", live_only=True) == 1
    assert _count("Cc", "Dd", "2025-11-01", live_only=False) == 2
    c.close()


def test_stress_many_threads_single_row():
    def hammer(i):
        c = _conn(); cur = c.cursor()
        _rpc(cur, {"fixture_id": f"fd_s{i}", "home_team": "Zed", "away_team": "Won",
                   "league": "L", "kickoff_date": "2025-09-01", "home_shots": i + 1})
        c.close()
    ths = [threading.Thread(target=hammer, args=(i,)) for i in range(12)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert _count("Zed", "Won", "2025-09-01") == 1
