"""
Teste de regresie pentru fix-ul "writer destructiv" (2026-07-13) — regula
permanenta de arhitectura "Protectia Writer-ilor": niciun proces de
sincronizare nu are voie sa degradeze date deja validate.

Defectele reparate (ambele demonstrate pe productie, vezi memoria de
arhitect / raportul din 2026-07-13):
  (a) sync/sources/football_data.py si sync/sources/openfootball.py
      trimiteau explicit home_elo=None / away_elo=None in payload-ul de
      upsert -> la conflict pe fixture_id existent, ELO deja calculat era
      RESCRIS cu NULL (1.059 randuri re-anulate in timpul backfill-ului).
  (b) database/queries.py get_existing_fixture_ids() intorcea set() gol la
      ORICE exceptie (fail-open) -> deduplicarea murea silentios si tot
      setul preluat (5.756 meciuri) era re-upsert-at zilnic peste randurile
      existente (sync_status: fetched=5756, skipped=0).

Niciun test nu atinge reteaua sau Supabase live.
"""
import pytest

import database.queries as q
from sync.sources.football_data import _parse_match as fd_parse
from sync.sources.openfootball import _parse_match_json as of_parse


# ════════════════════════════════════════════════════════════════════════
# (a) Sursele nu mai emit chei ELO explicit None
# ════════════════════════════════════════════════════════════════════════

def _fd_sample_match():
    return {
        "status": "FINISHED",
        "id": 436146,
        "utcDate": "2024-01-22T20:00:00Z",
        "season": {"startDate": "2023-08-01"},
        "homeTeam": {"name": "Brighton & Hove Albion FC"},
        "awayTeam": {"name": "Wolverhampton Wanderers FC"},
        "score": {"fullTime": {"home": 0, "away": 0}},
    }


def test_football_data_payload_has_no_elo_keys():
    row = fd_parse(_fd_sample_match(), "Premier League")
    assert row is not None
    assert "home_elo" not in row and "away_elo" not in row, (
        "payload-ul football-data.org NU trebuie sa contina chei ELO — "
        "explicit None rescria cu NULL ELO deja calculat, la upsert"
    )
    # Restul contractului ramane neschimbat
    assert row["fixture_id"] == "fd_436146"
    assert row["actual_result"] == "D"


def test_football_data_payload_includes_season_when_provider_offers_it():
    """[FIX Pasul 3, Master Repair Plan] season era parsat din raspunsul real
    al providerului dar niciodata inclus in dict-ul scris in match_history —
    variabila locala calculata si aruncata. Testul foloseste doar startDate
    (fara endDate), ca in fixture-ul real de mai sus — format "YYYY"."""
    row = fd_parse(_fd_sample_match(), "Premier League")
    assert row is not None
    assert row["season"] == "2023"


def test_football_data_payload_season_uses_start_and_end_year_when_both_present():
    match = _fd_sample_match()
    match["season"] = {"startDate": "2023-08-11", "endDate": "2024-05-19"}
    row = fd_parse(match, "Premier League")
    assert row is not None
    assert row["season"] == "2023-2024"


def test_football_data_payload_season_is_none_when_provider_omits_it():
    match = _fd_sample_match()
    del match["season"]
    row = fd_parse(match, "Premier League")
    assert row is not None
    assert row["season"] is None, (
        "Fara sezon oferit de provider, coloana ramane NULL — nicio "
        "aproximare calendaristica (interzis explicit, season_cleanup.py)"
    )


def test_openfootball_payload_has_no_elo_keys():
    match = {
        "team1": {"name": "FCSB"},
        "team2": {"name": "CFR Cluj"},
        "score": {"ft": [2, 1]},
        "date": "2024-03-10",
    }
    row = of_parse(match, "Romania SuperLiga", "2023-24")
    assert row is not None
    assert "home_elo" not in row and "away_elo" not in row
    assert row["actual_result"] == "H"


def test_openfootball_payload_includes_season():
    """[FIX Pasul 3, Master Repair Plan] season era deja cunoscut (parametru
    din LEAGUE_PATHS[...]["seasons"], folosit la construirea fixture_id-ului)
    dar niciodata inclus in dict-ul scris in match_history — aceeasi clasa
    de bug ca la football_data.py. Text liber, exact cum e primit."""
    match = {
        "team1": {"name": "FCSB"},
        "team2": {"name": "CFR Cluj"},
        "score": {"ft": [2, 1]},
        "date": "2024-03-10",
    }
    row = of_parse(match, "Romania SuperLiga", "2023-24")
    assert row is not None
    assert row["season"] == "2023-24"


def test_football_data_payload_has_no_dead_odds_keys():
    """[ELIMINAT Pasul 3, Master Repair Plan] odds_home/odds_draw/odds_away
    erau parsate din match["odds"] dar niciodata incluse in payload — cod
    mort, eliminat complet (nu doar lasat neutilizat). Singura tabela reala
    de cote e odds_history, alimentata exclusiv din The Odds API
    (ADR-005/006 sectiunea 5 — evita dubla sursa de adevar)."""
    match = _fd_sample_match()
    match["odds"] = {"homeWin": 1.9, "draw": 3.4, "awayWin": 4.1}
    row = fd_parse(match, "Premier League")
    assert row is not None
    assert "odds_home" not in row and "odds_draw" not in row and "odds_away" not in row


# ════════════════════════════════════════════════════════════════════════
# (a') Garda de clasa la punctul unic de trecere: upsert-ul elimina orice
#      cheie None, indiferent de sursa — clasa de defect nu mai poate
#      reaparea printr-o sursa viitoare care emite None
# ════════════════════════════════════════════════════════════════════════

class _CapturingRpc:
    """[MIGRAT — ID-025-03] Writer-ii ruteaza prin RPC-ul canonic, nu prin
    `.upsert()` direct pe fixture_id. Garda de eliminare a cheilor None se
    aplica identic, inainte de apelul RPC."""

    def __init__(self, fn, params, sink):
        self.fn = fn
        self.params = params
        self.sink = sink

    def execute(self):
        self.sink.append((self.fn, self.params))

        class Res:
            pass
        r = Res()
        n = len(self.params.get("p_payloads", [])) if self.fn == "upsert_matches_canonical" else 1
        r.data = {"inserted": n, "updated": 0, "hard_conflict": 0}
        return r


class _CapturingClient:
    def __init__(self):
        self.rpcs = []

    def rpc(self, fn, params):
        return _CapturingRpc(fn, params, self.rpcs)


def test_bulk_upsert_strips_none_keys(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    rows = [{
        "fixture_id": "fd_x", "home_team": "A", "away_team": "B",
        "kickoff_date": "2025-01-01", "actual_result": "H",
        "home_elo": None, "away_elo": None,      # sursa ostila/veche
        "home_xg_pred": None,
    }]
    ok, errors = q.upsert_matches_bulk(rows)

    assert (ok, errors) == (1, 0)
    fn, params = client.rpcs[0]
    assert fn == "upsert_matches_canonical"
    sent = params["p_payloads"][0]
    assert "home_elo" not in sent and "away_elo" not in sent
    assert "home_xg_pred" not in sent
    assert all(v is not None for v in sent.values()), (
        "nicio cheie cu valoare None nu are voie sa ajunga in payload-ul "
        "RPC — ar rescrie cu NULL o valoare existenta"
    )
    # Valorile reale trec neatinse
    assert sent["fixture_id"] == "fd_x" and sent["actual_result"] == "H"


def test_bulk_upsert_original_rows_not_mutated(monkeypatch):
    """Garda construieste dict-uri noi — nu goleste dict-urile apelantului."""
    client = _CapturingClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    row = {"fixture_id": "fd_y", "home_elo": None}
    q.upsert_matches_bulk([row])
    assert "home_elo" in row, "dict-ul original al apelantului a fost mutat"


# ════════════════════════════════════════════════════════════════════════
# (b) Deduplicarea: chunking + fail-closed (nu mai exista set gol la eroare)
# ════════════════════════════════════════════════════════════════════════

class _InQueryTable:
    def __init__(self, known_ids, calls, fail=False):
        self.known_ids = known_ids
        self.calls = calls
        self.fail = fail
        self._chunk = None

    def select(self, cols):
        return self

    def in_(self, col, values):
        self.calls.append(list(values))
        self._chunk = values
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("simulare: URL prea lung / eroare PostgREST")
        class Res:
            pass
        r = Res()
        r.data = [{"fixture_id": v} for v in self._chunk if v in self.known_ids]
        return r


class _InQueryClient:
    def __init__(self, known_ids, fail=False):
        self.known_ids = known_ids
        self.calls = []
        self.fail = fail

    def table(self, name):
        return _InQueryTable(self.known_ids, self.calls, self.fail)


def test_get_existing_fixture_ids_chunks_large_input(monkeypatch):
    """Regresie directa pe cauza demonstrata: 5.756 id-uri intr-un singur
    .in_() depasea limita de URL -> exceptie -> fail-open. Acum interogarea
    se imparte in chunk-uri de maximum 200."""
    known = {f"fd_{i}" for i in range(0, 5756, 7)}
    client = _InQueryClient(known)
    monkeypatch.setattr(q, "get_client", lambda: client)

    ids = [f"fd_{i}" for i in range(5756)]
    result = q.get_existing_fixture_ids(ids)

    assert len(client.calls) == -(-5756 // 200), "asteptam interogari in chunk-uri de 200"
    assert all(len(c) <= 200 for c in client.calls)
    # Niciun id pierdut intre chunk-uri
    assert result == known


def test_get_existing_fixture_ids_fails_closed_on_error(monkeypatch):
    """Regresie pe fail-open: la eroare NU se mai intoarce set() gol
    (care insemna 'nimic nu exista' -> re-upsert total peste randuri
    existente). Exceptia trebuie sa se propage — apelantul din
    sync_matches.sync_all() o prinde per-sursa si abandoneaza FARA scrieri."""
    client = _InQueryClient(known_ids=set(), fail=True)
    monkeypatch.setattr(q, "get_client", lambda: client)

    with pytest.raises(RuntimeError):
        q.get_existing_fixture_ids(["fd_1", "fd_2"])


def test_sync_all_aborts_source_without_writes_on_dedup_failure(monkeypatch):
    """Lantul complet fail-closed: daca deduplicarea pica, sursa e
    abandonata cu raport de eroare si upsert-ul NU e apelat deloc."""
    import sync.sync_matches as sm

    upsert_calls = []
    monkeypatch.setattr(sm, "get_existing_fixture_ids",
                        lambda ids: (_ for _ in ()).throw(RuntimeError("dedup a picat")))
    monkeypatch.setattr(sm, "upsert_matches_bulk",
                        lambda rows: upsert_calls.append(rows) or (len(rows), 0))
    monkeypatch.setattr(sm, "upsert_sync_status", lambda **kw: None)

    import sync.sources.football_data as fd
    monkeypatch.setattr(
        fd, "fetch_all_leagues",
        lambda leagues=None, seasons=None: iter(
            [("Premier League", 2025, [{"fixture_id": "fd_1", "home_team": "A",
                                        "away_team": "B", "actual_result": "H"}])]
        ),
    )

    reports = sm.sync_all(use_football_data=True, use_openfootball=False)

    assert upsert_calls == [], (
        "cu deduplicarea picata, NICIO scriere nu are voie sa se produca "
        "(inainte: fail-open -> re-upsert total)"
    )
    assert len(reports) == 1 and reports[0].errors == 1
