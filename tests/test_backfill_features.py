"""
Teste pentru gating-ul per-coloană (non-destructiv) din sync/backfill_features.py
— vezi docs/03_ENGINE/BACKFILL_NON_DESTRUCTIVE_STRATEGY_2026-07-12.md pentru
cerințele exacte testate aici: (1) scrie doar coloane NULL, (2) ELO real
existent nu e niciodată suprascris, (3) rezultatele nu sunt niciodată
atinse, (4) idempotență pe 2 rulări succesive, (5) reluare sigură după o
întrerupere simulată.

Nu ating rețeaua — fetch_all_matches/bulk_update_features sunt înlocuite cu
un "store" in-memory care simulează exact comportamentul relevant al
Supabase (citire completă + UPDATE parțial per coloană).
"""
import copy

import sync.backfill_features as bf
from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS


def _fresh_store():
    """Trei meciuri cronologice, aceleași echipe, stări de completitudine
    diferite — exact scenariile cerute:
      id=1: complet gol (are nevoie de backfill integral)
      id=2: home_elo deja populat real (simulează Kaggle) — restul NULL
      id=3: deja complet populat (nu trebuie atins deloc)
    """
    return {
        1: {
            "id": 1, "fixture_id": "f1", "home_team": "Team X", "away_team": "Team Y",
            "league": "Test League", "kickoff_date": "2021-01-01",
            "actual_home_goals": 2, "actual_away_goals": 0, "actual_result": "H",
            "backfill_done": False,
            **{col: None for col in bf.BACKFILL_COLUMNS},
        },
        2: {
            "id": 2, "fixture_id": "f2", "home_team": "Team X", "away_team": "Team Z",
            "league": "Test League", "kickoff_date": "2021-02-01",
            "actual_home_goals": 1, "actual_away_goals": 1, "actual_result": "D",
            "backfill_done": False,
            **{col: None for col in bf.BACKFILL_COLUMNS},
            "home_elo": 1600,  # valoare reala preexistenta (ex. Kaggle) — NU trebuie suprascrisa
        },
        3: {
            "id": 3, "fixture_id": "f3", "home_team": "Team Y", "away_team": "Team Z",
            "league": "Test League", "kickoff_date": "2021-03-01",
            "actual_home_goals": 0, "actual_away_goals": 1, "actual_result": "A",
            "backfill_done": True,
            "home_elo": 1510, "away_elo": 1490,
            "home_form_score": 0.5, "away_form_score": 0.5,
            "home_offensive_rating": 1.1, "home_defensive_rating": 0.9,
            "away_offensive_rating": 1.0, "away_defensive_rating": 1.0,
            "h2h_modifier": 0.0, "h2h_meetings": 0,
            "home_corner_avg_recent": 5.5, "away_corner_avg_recent": 4.5,
            "home_card_avg_recent": 1.5, "away_card_avg_recent": 2.0,
            "home_foul_avg_recent": 11.0, "away_foul_avg_recent": 10.0,
            "home_shot_avg_recent": 12.0, "away_shot_avg_recent": 9.5,
            "home_elo_after": 1495, "away_elo_after": 1505,
        },
    }


class FakeSupabase:
    """Simulează exact interfața folosită de backfill_features: citire
    completă (fetch_all_matches) + UPDATE parțial per rând (bulk_update_features)."""

    def __init__(self, store):
        self.store = store
        self.update_calls: list[tuple[int, dict]] = []
        self.crash_after_n_updates: int | None = None

    def fetch_all_matches(self, league=None):
        rows = [copy.deepcopy(r) for r in self.store.values()]
        rows.sort(key=lambda r: (r["kickoff_date"], r["id"]))
        return rows

    def bulk_update_features(self, updates):
        ok, errors = 0, 0
        for match_id, features in updates:
            self.update_calls.append((match_id, dict(features)))
            if self.crash_after_n_updates is not None and len(self.update_calls) > self.crash_after_n_updates:
                errors += 1
                continue
            self.store[match_id].update(features)
            self.store[match_id]["backfill_done"] = True
            ok += 1
        return ok, errors


def _run(fake, batch_size=50):
    return bf.run_backfill(
        batch_size=batch_size, dry_run=False,
        weights=dict(DEFAULT_WEIGHTS), config=dict(DEFAULT_CONFIG),
    )


def _patch(monkeypatch, fake):
    monkeypatch.setattr(bf, "fetch_all_matches", fake.fetch_all_matches)
    monkeypatch.setattr(bf, "bulk_update_features", fake.bulk_update_features)


def test_writes_only_null_columns(monkeypatch):
    """Cerința #1: payload-ul de UPDATE pentru fiecare rând conține DOAR
    coloanele care erau NULL — niciodată coloane deja populate."""
    store = _fresh_store()
    fake = FakeSupabase(store)
    _patch(monkeypatch, fake)

    _run(fake)

    calls_by_id = {mid: feats for mid, feats in fake.update_calls}

    # id=1 era complet gol -> update-ul trebuie sa acopere toate coloanele
    # calculabile. Exceptie: cornere/cartonase/faulturi/suturi raman None
    # (Regula #8 — nicio stare necunoscuta nu se aproximeaza) pentru ca e
    # primul meci din dataset pentru ambele echipe, deci CornerCardTracker/
    # FoulsTracker/ShotCountTracker nu au niciun istoric antecedent; o
    # valoare None nu se scrie niciodata peste NULL.
    cold_start_cols = {
        "home_corner_avg_recent", "away_corner_avg_recent",
        "home_card_avg_recent", "away_card_avg_recent",
        "home_foul_avg_recent", "away_foul_avg_recent",
        "home_shot_avg_recent", "away_shot_avg_recent",
    }
    assert set(calls_by_id[1].keys()) == set(bf.BACKFILL_COLUMNS) - cold_start_cols

    # id=2 avea deja home_elo populat -> NU trebuie sa apara in payload-ul de update
    assert "home_elo" not in calls_by_id[2], (
        "home_elo era deja populat (valoare reala) si NU trebuia inclus in UPDATE"
    )
    # Fixture-ul nu include deloc coloane brute de cornere/cartonase/suturi
    # (home_corners/away_corners/home_shots/etc.) pe niciun rand ->
    # CornerCardTracker/FoulsTracker/ShotCountTracker nu acumuleaza
    # niciodata istoric real, deci cold_start_cols raman None si pentru
    # id=2 (Regula #8, nu se scrie None peste NULL).
    assert set(calls_by_id[2].keys()) == set(bf.BACKFILL_COLUMNS) - {"home_elo"} - cold_start_cols

    # id=3 era deja complet -> nu trebuie sa aiba niciun apel de update
    assert 3 not in calls_by_id, "randul deja complet nu trebuie atins deloc"


def test_existing_elo_value_never_overwritten(monkeypatch):
    """Cerința #2: valoarea reală de ELO deja stocată rămâne neschimbată
    în store după backfill, chiar dacă replay-ul intern ar calcula alta."""
    store = _fresh_store()
    fake = FakeSupabase(store)
    _patch(monkeypatch, fake)

    _run(fake)

    assert store[2]["home_elo"] == 1600, "ELO real preexistent a fost suprascris — regresie destructiva"


def test_results_never_touched(monkeypatch):
    """Cerința #3: niciun payload de UPDATE nu conține vreodată
    actual_result/actual_home_goals/actual_away_goals."""
    store = _fresh_store()
    fake = FakeSupabase(store)
    _patch(monkeypatch, fake)

    _run(fake)

    forbidden = {"actual_result", "actual_home_goals", "actual_away_goals"}
    for _, features in fake.update_calls:
        assert forbidden.isdisjoint(features.keys()), (
            f"payload-ul de update a atins un camp de rezultat interzis: {features.keys()}"
        )


def test_idempotent_second_run_writes_nothing(monkeypatch):
    """Cerința #4: a doua rulare, fără date noi introduse, nu mai scrie nimic."""
    store = _fresh_store()
    fake = FakeSupabase(store)
    _patch(monkeypatch, fake)

    result_1 = _run(fake)
    assert result_1["processed"] > 0

    fake.update_calls.clear()
    result_2 = _run(fake)

    assert fake.update_calls == [], "a doua rulare nu ar trebui sa emita niciun UPDATE"
    assert result_2["processed"] == 0
    # id=1 si id=2 nu au date brute de cornere/cartonase in fixture (nicio
    # cheie home_corners/away_corners etc.) -> cele 4 coloane *_avg_recent
    # raman permanent None (Regula #8, nu se aproximeaza), deci randurile
    # raman "incomplete" strict dupa _missing_feature_columns chiar daca nu
    # se mai emite niciun UPDATE pentru ele. Doar id=3 (populat explicit in
    # fixture) e complet sub schema de 14 coloane.
    assert result_2["already_done"] == 1


def test_safe_resume_after_interruption(monkeypatch):
    """Cerința #5: o rulare întreruptă la jumătate (simulăm eroare la
    scriere pentru restul batch-urilor) poate fi reluată printr-o a doua
    rulare completă, ajungând la aceeași stare finală ca o rulare fără
    întrerupere."""
    # Rulare de referință, fara intrerupere, pe un store separat identic
    reference_store = _fresh_store()
    reference_fake = FakeSupabase(reference_store)
    monkeypatch.setattr(bf, "fetch_all_matches", reference_fake.fetch_all_matches)
    monkeypatch.setattr(bf, "bulk_update_features", reference_fake.bulk_update_features)
    _run(reference_fake, batch_size=1)

    # Rulare cu "intrerupere": primul update reuseste, restul esueaza (simuleaza crash)
    store = _fresh_store()
    fake = FakeSupabase(store)
    fake.crash_after_n_updates = 1
    _patch(monkeypatch, fake)
    _run(fake, batch_size=1)

    assert store != reference_store, "testul nu simuleaza nimic daca intreruperea nu a lasat starea incompleta"

    # Reluare completa, fara intrerupere de data asta
    fake.crash_after_n_updates = None
    fake.update_calls.clear()
    result_resume = _run(fake, batch_size=1)

    assert result_resume["errors"] == 0
    assert store == reference_store, (
        "starea finala dupa reluare trebuie sa fie identica cu o rulare fara intrerupere "
        "(replay determinist, gating per-coloana)"
    )
