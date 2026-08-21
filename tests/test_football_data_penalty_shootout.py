"""
Teste pentru fix-ul F4.5 — departajarea de la 11 metri nu mai e numarata ca
goluri la importul din football-data.org (`sync/sources/football_data.py`).

Fara retea, fara Supabase: `_parse_match()` e o functie pura de transformare a
unui payload de provider, testata direct cu dict-uri in forma documentata de
API-ul football-data.org v4.

Context (audit F4, pe date live): `fd_524100` — Liverpool vs Paris
Saint-Germain, Champions League, 2025-03-11 — a fost scris in `match_history`
cu `actual_home_goals=1, actual_away_goals=5`. Meciul s-a incheiat 0-1, iar PSG
a castigat departajarea cu 4-1. Suma se potriveste exact: 0+1=1 si 1+4=5.
Cauza: `_parse_match()` citea `score.fullTime` neconditionat si nu consulta
niciodata `score.duration`.

De ce conteaza dincolo de scorul afisat: `actual_result` ramane corect
(castigatorul e acelasi), dar diferenta de goluri intra distorsionat in
multiplicatorul MOV al ELO (`sync/backfill_features._mov_multiplier`) —
goal_diff 4 in loc de 1 — deci eroarea se propaga in starea derivata.
"""
from sync.sources.football_data import _parse_match


def _payload(duration, full_time, regular_time=None, penalties=None,
             status="FINISHED"):
    score = {"duration": duration, "fullTime": full_time}
    if regular_time is not None:
        score["regularTime"] = regular_time
    if penalties is not None:
        score["penalties"] = penalties
    return {
        "id": 524100,
        "status": status,
        "homeTeam": {"name": "Liverpool FC"},
        "awayTeam": {"name": "Paris Saint-Germain FC"},
        "utcDate": "2025-03-11T20:00:00Z",
        "score": score,
        "season": {"startDate": "2024-08-01", "endDate": "2025-05-31"},
    }


# ── Regresia propriu-zisa ───────────────────────────────────────────────────

def test_penalty_shootout_uses_regular_time_not_fulltime():
    """Cazul real `fd_524100`: fullTime include departajarea (1-5), regularTime
    are scorul meciului (0-1). Trebuie scris 0-1."""
    parsed = _parse_match(
        _payload("PENALTY_SHOOTOUT",
                 full_time={"home": 1, "away": 5},
                 regular_time={"home": 0, "away": 1},
                 penalties={"home": 1, "away": 4}),
        league="Champions League",
    )
    assert parsed is not None
    assert parsed["actual_home_goals"] == 0
    assert parsed["actual_away_goals"] == 1
    assert parsed["actual_result"] == "A"


def test_penalty_shootout_without_regular_time_is_skipped_not_approximated():
    """North Star #8 — o stare necunoscuta nu se aproximeaza. Fara `regularTime`
    explicit nu scadem `penalties` din `fullTime` (ar presupune ca fullTime e
    mereu suma, ipoteza neverificata pe payload-uri reale): meciul e sarit.
    Un meci sarit e recuperabil din alta sursa; unul scris gresit contamineaza
    tacit ELO."""
    parsed = _parse_match(
        _payload("PENALTY_SHOOTOUT",
                 full_time={"home": 1, "away": 5},
                 penalties={"home": 1, "away": 4}),
        league="Champions League",
    )
    assert parsed is None


def test_penalty_shootout_that_was_a_draw_in_regular_time_is_a_draw():
    """Cazul tipic: 1-1 dupa 90'/120', decis la penalty-uri. Rezultatul scris
    trebuie sa fie egal (D) — departajarea nu schimba rezultatul meciului."""
    parsed = _parse_match(
        _payload("PENALTY_SHOOTOUT",
                 full_time={"home": 4, "away": 3},
                 regular_time={"home": 1, "away": 1},
                 penalties={"home": 3, "away": 2}),
        league="Champions League",
    )
    assert parsed is not None
    assert parsed["actual_home_goals"] == 1
    assert parsed["actual_away_goals"] == 1
    assert parsed["actual_result"] == "D"


# ── Non-regresie: cazurile normale raman neschimbate ────────────────────────

def test_regular_match_still_uses_fulltime():
    parsed = _parse_match(
        _payload("REGULAR", full_time={"home": 3, "away": 1}),
        league="Premier League",
    )
    assert parsed is not None
    assert parsed["actual_home_goals"] == 3
    assert parsed["actual_away_goals"] == 1
    assert parsed["actual_result"] == "H"


def test_extra_time_match_uses_fulltime():
    """Prelungiri fara departajare: `fullTime` E scorul real al meciului."""
    parsed = _parse_match(
        _payload("EXTRA_TIME",
                 full_time={"home": 2, "away": 1},
                 regular_time={"home": 1, "away": 1}),
        league="Champions League",
    )
    assert parsed is not None
    assert parsed["actual_home_goals"] == 2
    assert parsed["actual_away_goals"] == 1
    assert parsed["actual_result"] == "H"


def test_missing_duration_field_falls_back_to_fulltime():
    """Compatibilitate cu payload-uri fara `duration` (ligi/versiuni care nu-l
    trimit): comportamentul de dinainte de fix ramane neschimbat."""
    payload = _payload("REGULAR", full_time={"home": 0, "away": 0})
    del payload["score"]["duration"]
    parsed = _parse_match(payload, league="La Liga")
    assert parsed is not None
    assert parsed["actual_result"] == "D"


def test_duration_is_case_insensitive():
    parsed = _parse_match(
        _payload("penalty_shootout",
                 full_time={"home": 1, "away": 5},
                 regular_time={"home": 0, "away": 1}),
        league="Champions League",
    )
    assert parsed is not None
    assert parsed["actual_home_goals"] == 0


def test_unfinished_match_still_returns_none():
    parsed = _parse_match(
        _payload("REGULAR", full_time={"home": None, "away": None},
                 status="TIMED"),
        league="Premier League",
    )
    assert parsed is None


def test_missing_fulltime_object_does_not_raise():
    """`score.fullTime` absent complet — nu trebuie sa arunce, doar sa sara."""
    payload = _payload("REGULAR", full_time={"home": 1, "away": 0})
    del payload["score"]["fullTime"]
    assert _parse_match(payload, league="Serie A") is None
