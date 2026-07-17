"""
Teste de regresie pentru fix-ul de wiring al normalizarii numelor de echipa
(P3.5 Team Identity Audit, 2026-07-15) — vezi docs/03_ENGINE/
TEAM_IDENTITY_AUDIT.md pentru descoperirea completa.

Cauza radacina demonstrata acolo: mappings.TEAM_ALIASES / normalize_team_
name() exista de mult si sunt deja folosite de sync/import_historical.py,
dar niciunul din writer-ii sincronizarii zilnice nu le apela — 137 echipe
canonice fragmentate in match_history (10,1% din volumul total), pornind
fiecare variant de la un rating ELO separat, de la zero.

Fix, la punctul unic de scriere (nu in fiecare sursa individual) — acelasi
principiu ca "Protectia Writer-ilor" (2026-07-13, vezi test_sync_writer_
protection.py): un writer viitor nu poate reintroduce defectul daca garda
e la punctul de trecere, nu la fiecare sursa:
  1. database.queries.upsert_match() / upsert_matches_bulk() — funnel-ul
     folosit de sync/sync_matches.py (football-data.org, openfootball).
  2. supabase_client.upsert_match_history() — al doilea funnel, folosit de
     oracle_engine.py (introducere manuala de rezultat din UI).
  3. sync.sync_results.fetch_yesterday_results() — NU scrie in match_
     history direct, dar cauta randul existent dupa home_team+away_team+
     kickoff_date; daca nu normalizeaza, cautarea ar esua silentios contra
     randurilor deja scrise canonic de (1).

Niciun test nu atinge reteaua sau Supabase live.
"""
import database.queries as q
import supabase_client as sb
import sync.sync_results as sr
from mappings import normalize_team_name


# ════════════════════════════════════════════════════════════════════════
# Helper de test — capteaza payload-ul trimis la Supabase, fara retea
# ════════════════════════════════════════════════════════════════════════

class _CapturingRpc:
    """[MIGRAT — ID-025-03] Writer-ii ruteaza acum prin RPC-ul canonic
    (`upsert_match_canonical` / `upsert_matches_canonical`), nu prin `.upsert()`
    direct pe fixture_id. Fake-ul capteaza apelul RPC + payload-ul si intoarce
    un rezultat plauzibil (insert)."""

    def __init__(self, fn, params, sink):
        self.fn = fn
        self.params = params
        self.sink = sink

    def execute(self):
        self.sink.append((self.fn, self.params))

        class Res:
            pass
        r = Res()
        if self.fn == "upsert_matches_canonical":
            n = len(self.params["p_payloads"])
            r.data = {"inserted": n, "updated": 0, "hard_conflict": 0}
        else:
            r.data = {"action": "insert", "id": 1}
        return r


class _CapturingClient:
    def __init__(self):
        self.rpcs = []

    def rpc(self, fn, params):
        return _CapturingRpc(fn, params, self.rpcs)


# ════════════════════════════════════════════════════════════════════════
# (1) database.queries — funnel-ul folosit de sync/sync_matches.py
# ════════════════════════════════════════════════════════════════════════

def test_normalize_team_fields_maps_known_alias():
    row = {"fixture_id": "x", "home_team": "Man Utd", "away_team": "Inter"}
    out = q._normalize_team_fields(row)
    assert out["home_team"] == "Manchester United"
    assert out["away_team"] == "Inter Milan"


def test_normalize_team_fields_leaves_unknown_team_unchanged():
    row = {"home_team": "FC O Echipa Complet Necunoscuta", "away_team": "Alta"}
    out = q._normalize_team_fields(row)
    assert out["home_team"] == "FC O Echipa Complet Necunoscuta"


def test_normalize_team_fields_handles_missing_keys():
    """Randuri partiale (ex. doar update de scor, fara home_team/away_team)
    nu trebuie sa pice — normalizarea e opt-in pe cheile prezente."""
    row = {"fixture_id": "x", "actual_result": "H"}
    out = q._normalize_team_fields(row)
    assert out == row


def test_normalize_team_fields_does_not_mutate_original():
    row = {"home_team": "Man Utd"}
    q._normalize_team_fields(row)
    assert row["home_team"] == "Man Utd", "dict-ul apelantului nu are voie sa fie mutat"


def test_upsert_match_normalizes_before_upsert(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    ok = q.upsert_match({
        "fixture_id": "fd_1", "home_team": "Man Utd", "away_team": "FC Internazionale Milano",
        "kickoff_date": "2025-01-01", "actual_result": "H",
    })

    assert ok is True
    fn, params = client.rpcs[0]
    assert fn == "upsert_match_canonical"
    sent = params["p_payload"]
    assert sent["home_team"] == "Manchester United"
    assert sent["away_team"] == "Inter Milan"


def test_bulk_upsert_normalizes_every_row(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    rows = [
        {"fixture_id": "fd_1", "home_team": "Man Utd", "away_team": "Ath Madrid", "actual_result": "H"},
        {"fixture_id": "fd_2", "home_team": "Club Atlético de Madrid", "away_team": "Tottenham Hotspur FC", "actual_result": "A"},
    ]
    ok, errors = q.upsert_matches_bulk(rows)

    assert (ok, errors) == (2, 0)
    fn, params = client.rpcs[0]
    assert fn == "upsert_matches_canonical"
    sent_batch = params["p_payloads"]
    assert sent_batch[0]["home_team"] == "Manchester United"
    assert sent_batch[0]["away_team"] == "Atletico Madrid"
    assert sent_batch[1]["home_team"] == "Atletico Madrid"
    assert sent_batch[1]["away_team"] == "Tottenham Hotspur"
    # Regresie directa pe cazul central din TEAM_IDENTITY_AUDIT.md: cele doua
    # randuri au variante diferite ale Atletico Madrid ca input -- ambele
    # trebuie sa iasa cu ACELASI nume canonic, altfel ELOTracker le-ar trata
    # in continuare ca echipe separate.
    assert sent_batch[0]["away_team"] == sent_batch[1]["home_team"]


# ════════════════════════════════════════════════════════════════════════
# (2) supabase_client.upsert_match_history — al doilea funnel (oracle_engine.py)
# ════════════════════════════════════════════════════════════════════════

def test_upsert_match_history_normalizes_before_upsert(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(sb, "get_client", lambda: client)

    ok = sb.upsert_match_history({
        "fixture_id": "fd_2", "home_team": "Bayern", "away_team": "FC Bayern München",
        "kickoff_date": "2025-01-01",
    })

    assert ok is True
    fn, params = client.rpcs[0]
    assert fn == "upsert_match_canonical"
    sent = params["p_payload"]
    assert sent["home_team"] == "Bayern Munich"
    assert sent["away_team"] == "Bayern Munich", (
        "aceeasi echipa, doua variante brute diferite -- trebuie sa convearga "
        "la acelasi nume canonic prin ambele funnel-uri de scriere"
    )


def test_upsert_match_history_strips_none_before_rpc(monkeypatch):
    """[MIGRAT — ID-025-03] Writer Protection la nivel Python: o cheie None nu
    ajunge in payload-ul RPC (ar fi oricum inofensiva, fiindca RPC-ul face
    COALESCE(existing, NULL)=existing, dar o eliminam la sursa pentru claritate
    si payload minim)."""
    client = _CapturingClient()
    monkeypatch.setattr(sb, "get_client", lambda: client)

    ok = sb.upsert_match_history({
        "fixture_id": "fd_3", "home_team": "X", "away_team": "Y",
        "kickoff_date": "2025-01-01", "actual_home_goals": 2, "home_elo": None,
    })
    assert ok is True
    _, params = client.rpcs[0]
    sent = params["p_payload"]
    assert "home_elo" not in sent
    assert sent["actual_home_goals"] == 2


# ════════════════════════════════════════════════════════════════════════
# (3) sync.sync_results — normalizare la EXTRAGERE, nu doar la scriere,
#     altfel cautarea randului existent (home_team+away_team+kickoff_date)
#     ar esua silentios contra randurilor deja scrise canonic de (1)/(2)
# ════════════════════════════════════════════════════════════════════════

def _fd_finished_match(home_name, away_name):
    return {
        "id": 999,
        "competition": {"tla": "PL"},
        "homeTeam": {"name": home_name},
        "awayTeam": {"name": away_name},
        "score": {"fullTime": {"home": 2, "away": 1}},
        "utcDate": "2026-07-14T15:00:00Z",
    }


def test_fetch_yesterday_results_normalizes_team_names(monkeypatch):
    monkeypatch.setattr(sr, "COMPETITION_TO_LEAGUE", {"PL": "Premier League"})
    monkeypatch.setattr(
        sr, "_rate_limited_get",
        lambda url, params=None: {"matches": [_fd_finished_match("Man Utd", "Tottenham Hotspur FC")]},
    )

    results = sr.fetch_yesterday_results(target_date="2026-07-14")

    assert len(results) == 1
    assert results[0]["home_team"] == "Manchester United"
    assert results[0]["away_team"] == "Tottenham Hotspur"


def test_all_writers_agree_on_the_same_canonical_name():
    """Cerinta explicita: toate sursele trebuie sa produca acelasi rezultat
    pentru aceeasi echipa, indiferent de varianta bruta de input -- nu doar
    ca fiecare normalizeaza *ceva*, ci ca normalizeaza la ACELASI nume."""
    raw_variants = ["Inter", "FC Internazionale Milano", "Inter Milan", "Internazionale"]
    canonical_forms = {normalize_team_name(v) for v in raw_variants}
    assert canonical_forms == {"Inter Milan"}, (
        f"variante diferite ale aceleiasi echipe converg la nume diferite: {canonical_forms}"
    )
