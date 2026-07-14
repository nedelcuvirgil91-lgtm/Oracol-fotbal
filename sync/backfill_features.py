"""
================================================================================
FOOTBALL ORACLE v4.0 — Backfill Historical Features
================================================================================
Module: sync/backfill_features.py

Calculează retrospectiv feature-urile ML pentru toate meciurile din
match_history care au cel puțin o coloană de feature NULL.

Feature-uri calculate per meci (la momentul t al meciului):
  - ELO acasă/deplasare (calculat din toate meciurile ANTERIOARE acelui meci)
  - Forma acasă/deplasare (ultimele 5 meciuri înainte de acel meci)
  - Rating ofensiv/defensiv (din forma recentă)
  - H2H modifier (din meciurile anterioare dintre cele două echipe)

Strategia de resume — NON-DESTRUCTIVĂ, gating PER-COLOANĂ (v4.1):
  [FIX] Înainte, gating-ul era per-rând (`backfill_done`): dacă fals, se
  scriau toate cele 10 coloane necondiționat, inclusiv peste un `home_elo`
  real deja existent (Kaggle) — asta a produs disjuncția completă demonstrată
  în DATA_PIPELINE_INVESTIGATION_2026-07-12.md (0% din rânduri cu ELO ȘI
  toate feature-urile simultan). Acum gating-ul e per-coloană: se calculează
  întotdeauna toate cele 10 valori (calcul Python, ieftin), dar se scrie DOAR
  subsetul ale cărui valori curente sunt NULL. O coloană deja populată nu
  e niciodată suprascrisă, indiferent de `backfill_done`. Strategie proiectată
  și documentată în BACKFILL_NON_DESTRUCTIVE_STRATEGY_2026-07-12.md — vezi
  acel document pentru riscurile NEREZOLVATE de acest fix (§3.2 — ordinea
  cronologică între rulări succesive cu istoric nou mai vechi; §3.4 —
  offensive/defensive_rating folosesc mereu ELO-ul din replay-ul intern,
  niciodată ELO-ul real stocat, chiar și după acest fix).
  - Un rând cu toate cele 10 coloane deja populate e complet sărit (fără
    niciun apel de UPDATE).
  - `backfill_done` rămâne un indicator agregat pentru raportare rapidă
    (setat True doar când, după scriere, toate cele 10 coloane sunt
    populate — garantat prin construcție, fiindcă se scrie exact setul de
    coloane care lipseau).
  - Idempotent: o a doua rulare, fără date noi, nu mai scrie nimic.
  - Sigur să fie oprit și reluat oricând.

Rulare:
  python sync/backfill_features.py
  python sync/backfill_features.py --league "Premier League"
  python sync/backfill_features.py --batch-size 100
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from feature_engine import (
    compute_form_score, compute_h2h_modifier, compute_team_offdef_rating,
    elo_to_offensive_multiplier, elo_to_defensive_multiplier, resolve_league_weights,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.Backfill")

# ── Parametri ELO ─────────────────────────────────────────────────────────────
INITIAL_ELO    = 1500
HOME_ADVANTAGE = 50
K_FACTOR_BASE  = 32
K_FACTOR_NEW   = 40

# ── Parametri formă ───────────────────────────────────────────────────────────
FORM_WINDOW    = 10     # ultimele N meciuri pentru formă (mărit de la 5 la 10 —
                        # decizie bazată pe replay-ul complet Premier League,
                        # 760 meciuri: Brier 0.6312→0.6047, testat 5-15,
                        # câștigul devine neglijabil după ~10-11)

# Cele 10 coloane de feature completate de acest script — sursă unică pentru
# SELECT-ul din fetch_all_matches() și pentru gating-ul per-coloană din
# run_backfill(). Nu conține niciodată actual_result/actual_home_goals/
# actual_away_goals — scriptul nu rescrie și nu a rescris niciodată rezultate.
FEATURE_COLUMNS: tuple[str, ...] = (
    "home_elo", "away_elo",
    "home_form_score", "away_form_score",
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "h2h_modifier", "h2h_meetings",
    # [ADAUGAT — ADR-012] Medii reale de cornere/cartonașe, promovate la
    # FEATURE_COLUMNS in ml_predictor.py dupa dovada de ablatie
    # (docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md).
    "home_corner_avg_recent", "away_corner_avg_recent",
    "home_card_avg_recent", "away_card_avg_recent",
)


def _missing_feature_columns(match: dict) -> list[str]:
    """Subsetul din FEATURE_COLUMNS ale căror valori curente sunt NULL
    pentru acest rând. Listă goală == rând complet, de sărit fără UPDATE."""
    return [col for col in FEATURE_COLUMNS if match.get(col) is None]


def get_client():
    from supabase_client import get_client as _gc
    return _gc()


# ════════════════════════════════════════════════════════════════════════════
# CITIRE DATE DIN SUPABASE
# ════════════════════════════════════════════════════════════════════════════

def fetch_all_matches(league: str | None = None) -> list[dict]:
    """
    Returnează TOATE meciurile cu rezultat real, sortate cronologic.
    Folosit pentru a construi starea ELO/formă pas cu pas.
    """
    client = get_client()
    if client is None:
        return []
    try:
        q = (
            client.table("match_history")
            .select("id,fixture_id,home_team,away_team,league,kickoff_date,"
                    "actual_home_goals,actual_away_goals,actual_result,"
                    "backfill_done,home_shots_on_target,away_shots_on_target,"
                    "home_corners,away_corners,home_yellow_cards,away_yellow_cards,"
                    + ",".join(FEATURE_COLUMNS))
            .not_.is_("actual_result", "null")
            .order("kickoff_date", desc=False)
            .order("id", desc=False)
        )
        if league:
            q = q.eq("league", league)

        # Paginare — Supabase returnează max 1000 rânduri per cerere
        all_rows = []
        offset = 0
        page_size = 1000
        while True:
            res = q.range(offset, offset + page_size - 1).execute()
            rows = res.data or []
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size

        logger.info("[Backfill] %d meciuri încărcate din Supabase", len(all_rows))
        return all_rows
    except Exception as exc:
        logger.error("[Backfill] fetch_all_matches failed: %s", exc)
        return []


def update_match_features(match_id: int, features: dict) -> bool:
    """Actualizează feature-urile unui meci în Supabase."""
    client = get_client()
    if client is None:
        return False
    try:
        client.table("match_history").update({
            **features,
            "backfill_done": True,
        }).eq("id", match_id).execute()
        return True
    except Exception as exc:
        logger.error("[Backfill] update_match_features(%d) failed: %s", match_id, exc)
        return False


def bulk_update_features(updates: list[tuple[int, dict]]) -> tuple[int, int]:
    """
    Actualizează feature-urile pentru o listă de meciuri.
    updates: [(match_id, features_dict), ...]
    Returnează (ok_count, error_count).
    """
    ok = 0
    errors = 0
    for match_id, features in updates:
        if update_match_features(match_id, features):
            ok += 1
        else:
            errors += 1
        # Pauză mică între update-uri ca să nu suprasolicităm Supabase
        time.sleep(0.05)
    return ok, errors


# ════════════════════════════════════════════════════════════════════════════
# CALCULUL ELO RETROSPECTIV
# ════════════════════════════════════════════════════════════════════════════

def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _k_factor(matches_played: int) -> float:
    return K_FACTOR_NEW if matches_played < 10 else K_FACTOR_BASE


class ELOTracker:
    """
    Urmărește ratingurile ELO pentru toate echipele în timp real,
    procesând meciurile în ordine cronologică.

    La fiecare meci, returnează ELO-ul ÎNAINTE de acel meci
    (adică ELO-ul cu care echipele intrau în meci).
    """

    def __init__(self):
        self.ratings: dict[str, float] = {}
        self.match_counts: dict[str, int] = {}

    def get_elo(self, team: str) -> float:
        return self.ratings.get(team, float(INITIAL_ELO))

    def get_count(self, team: str) -> int:
        return self.match_counts.get(team, 0)

    def get_elos_before_match(self, home: str, away: str) -> tuple[int, int]:
        """Returnează ELO-urile ÎNAINTE de a procesa meciul."""
        return round(self.get_elo(home)), round(self.get_elo(away))

    def process_match(self, home: str, away: str, result: str) -> None:
        """Actualizează ELO după un meci. Apelat DUPĂ ce am salvat ELO-ul pre-meci."""
        r_home = self.get_elo(home) + HOME_ADVANTAGE
        r_away = self.get_elo(away)

        exp_home = _expected_score(r_home, r_away)
        exp_away = 1.0 - exp_home

        if result == "H":
            score_home, score_away = 1.0, 0.0
        elif result == "A":
            score_home, score_away = 0.0, 1.0
        else:
            score_home, score_away = 0.5, 0.5

        k_home = _k_factor(self.get_count(home))
        k_away = _k_factor(self.get_count(away))

        self.ratings[home] = self.get_elo(home) + k_home * (score_home - exp_home)
        self.ratings[away] = self.get_elo(away) + k_away * (score_away - exp_away)
        self.match_counts[home] = self.get_count(home) + 1
        self.match_counts[away] = self.get_count(away) + 1


# ════════════════════════════════════════════════════════════════════════════
# CALCULUL FORMEI RETROSPECTIVE
# ════════════════════════════════════════════════════════════════════════════

class FormTracker:
    """
    Urmărește forma recentă (ultimele N meciuri) pentru fiecare echipă,
    procesând meciurile în ordine cronologică.

    La fiecare meci, returnează forma ÎNAINTE de acel meci.
    """

    def __init__(self, window: int = FORM_WINDOW):
        self.window = window
        # {team: [(result_for_team, gf, ga), ...]} — ultimele N meciuri
        self.history: dict[str, list[tuple[str, int, int]]] = {}

    def get_form(self, team: str) -> list[tuple[str, int, int]]:
        return self.history.get(team, [])[-self.window:]

    def calculate_form_score(self, team: str) -> float:
        """
        Calculează scorul de formă (0-1) bazat pe ultimele N meciuri.
        Meciurile mai recente au pondere mai mare (exponențial).
        """
        form = self.get_form(team)
        if not form:
            return 0.5  # formă neutră dacă nu avem date

        results = [r for r, _, _ in form]
        return compute_form_score(results)

    # [ELIMINAT — v3] calculate_ratings() folosea o formulă simplificată proprie
    # (min(avg_gf/1.25, 3.5) / min(avg_ga, 2.5)), DUPLICATĂ față de
    # compute_team_offdef_rating() din feature_engine.py — aceeași folosită de
    # motorul live (oracle_engine._build_profile) și de bootstrap
    # (acum team_pre_match_rating(), mai jos). Cele două formule divergeau:
    # aceasta din urmă ignora complet goals_weight/shots_ot_weight/
    # possession_weight și blend-ul ELO. Eliminată ca sursă duplicată de
    # adevăr — vezi team_pre_match_rating() pentru înlocuitor, folosit acum
    # uniform de live, backfill ȘI bootstrap.

    def process_match(
        self, home: str, away: str,
        home_goals: int, away_goals: int, result: str
    ) -> None:
        """Actualizează forma după un meci."""
        # Rezultat din perspectiva fiecărei echipe
        home_result = result if result in ("H", "D") else "L"
        away_result = result if result in ("A", "D") else "L"
        home_result = "W" if home_result == "H" else ("D" if home_result == "D" else "L")
        away_result = "W" if away_result == "A" else ("D" if away_result == "D" else "L")

        if home not in self.history:
            self.history[home] = []
        if away not in self.history:
            self.history[away] = []

        self.history[home].append((home_result, home_goals, away_goals))
        self.history[away].append((away_result, away_goals, home_goals))

        # Păstrăm doar ultimele 20 de meciuri (suficient pentru calcule)
        self.history[home] = self.history[home][-20:]
        self.history[away] = self.history[away][-20:]


# ════════════════════════════════════════════════════════════════════════════
# ȘUTURI PE POARTĂ REALE (înlocuiește proxy-ul avg_gf*0.45, când există)
# ════════════════════════════════════════════════════════════════════════════

class ShotsTracker:
    """
    Urmărește șuturile pe poartă REALE (populate de MatchStatsBackfillService,
    Task 1) pentru fiecare echipă, procesând meciurile în ordine cronologică —
    identic ca disciplină cu FormTracker. La fiecare meci, returnează media
    ÎNAINTE de acel meci, doar din meciuri cu valoare reală cunoscută.

    O echipă fără niciun meci cu șuturi reale în istoric întoarce None —
    apelantul păstrează fallback-ul sintetic (avg_gf*0.45), nu se aproximează
    aici (Regula #8).
    """

    def __init__(self, window: int = FORM_WINDOW):
        self.window = window
        self.history: dict[str, list[float]] = {}

    def get_avg_shots_on_target(self, team: str) -> float | None:
        values = self.history.get(team, [])[-self.window:]
        if not values:
            return None
        return sum(values) / len(values)

    def process_match(self, home: str, away: str,
                       home_sot: float | None, away_sot: float | None) -> None:
        if home_sot is not None:
            self.history.setdefault(home, []).append(float(home_sot))
            self.history[home] = self.history[home][-20:]
        if away_sot is not None:
            self.history.setdefault(away, []).append(float(away_sot))
            self.history[away] = self.history[away][-20:]


class CornerCardTracker:
    """
    Medie glisantă reală de cornere/cartonașe galbene per echipă — identică
    ca disciplină cu ShotsTracker. Sursă pentru home_corner_avg_recent/
    away_corner_avg_recent/home_card_avg_recent/away_card_avg_recent
    (ADR-012), promovate la ml_predictor.FEATURE_COLUMNS după ablație
    (docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md).
    """

    def __init__(self, window: int = FORM_WINDOW):
        self.window = window
        self.corners: dict[str, list[float]] = {}
        self.cards: dict[str, list[float]] = {}

    def get_avg_corners(self, team: str) -> float | None:
        values = self.corners.get(team, [])[-self.window:]
        return sum(values) / len(values) if values else None

    def get_avg_cards(self, team: str) -> float | None:
        values = self.cards.get(team, [])[-self.window:]
        return sum(values) / len(values) if values else None

    def process_match(self, home: str, away: str,
                       home_corners: float | None, away_corners: float | None,
                       home_cards: float | None, away_cards: float | None) -> None:
        if home_corners is not None:
            self.corners.setdefault(home, []).append(float(home_corners))
            self.corners[home] = self.corners[home][-20:]
        if away_corners is not None:
            self.corners.setdefault(away, []).append(float(away_corners))
            self.corners[away] = self.corners[away][-20:]
        if home_cards is not None:
            self.cards.setdefault(home, []).append(float(home_cards))
            self.cards[home] = self.cards[home][-20:]
        if away_cards is not None:
            self.cards.setdefault(away, []).append(float(away_cards))
            self.cards[away] = self.cards[away][-20:]


# ════════════════════════════════════════════════════════════════════════════
# CALCULUL H2H RETROSPECTIV
# ════════════════════════════════════════════════════════════════════════════

class H2HTracker:
    """
    Urmărește istoricul head-to-head între perechi de echipe.
    La fiecare meci, returnează H2H-ul ÎNAINTE de acel meci.
    """

    def __init__(self):
        # {(team_a, team_b): [(result_for_a, gf_a, ga_a), ...]}
        self.history: dict[tuple, list] = {}

    def _key(self, home: str, away: str) -> tuple:
        """Cheie canonică — echipele în ordine alfabetică."""
        return (min(home, away), max(home, away))

    def get_h2h_before(self, home: str, away: str) -> tuple[float, int]:
        """
        Returnează (h2h_modifier, meetings) ÎNAINTE de acel meci.
        h2h_modifier: pozitiv = avantaj home, negativ = avantaj away
        """
        key = self._key(home, away)
        history = self.history.get(key, [])

        if not history:
            return 0.0, 0

        # Calculăm din perspectiva echipei home
        home_wins = sum(1 for h, _, _ in history if h == home)
        away_wins = sum(1 for h, _, _ in history if h == away)
        n = len(history)

        modifier = compute_h2h_modifier(home_wins, away_wins, n, weight=0.15)
        return modifier, n

    def process_match(
        self, home: str, away: str, result: str,
        home_goals: int, away_goals: int
    ) -> None:
        """Actualizează H2H după un meci."""
        key = self._key(home, away)
        if key not in self.history:
            self.history[key] = []

        # Salvăm echipa câștigătoare (sau None pentru egal)
        if result == "H":
            winner = home
        elif result == "A":
            winner = away
        else:
            winner = "D"

        self.history[key].append((winner, home_goals, away_goals))
        # Păstrăm ultimele 10 meciuri H2H
        self.history[key] = self.history[key][-10:]


# ════════════════════════════════════════════════════════════════════════════
# CALCULUL CLASAMENTULUI RETROSPECTIV
# ════════════════════════════════════════════════════════════════════════════

# Convenția de sezon (start 1 iulie) reutilizează EXACT aceeași regulă folosită
# de _compute_season_cutoff_date() din sync/import_historical.py — nu se
# inventează o a doua definiție de "sezon" în proiect. Diferența e de scop:
# acolo se calculează O SINGURĂ dată cutoff-ul global (câte sezoane înapoi se
# importă), aici se calculează, per meci, ANUL de start al sezonului căruia îi
# aparține acel meci — o funcție diferită, dar aceeași regulă (1 iulie).
# [NOTĂ ARHITECTURALĂ] Ar fi mai curat ca formula anului de start să fie
# extrasă într-un helper comun, importat de ambele module — nu s-a făcut aici
# ca să nu se modifice sync/import_historical.py în afara scopului cerut.

def _season_start_year(kickoff_date: str) -> int:
    """Anul de start al sezonului (ex. 2024 pentru sezonul 2024-2025),
    pe baza convenției de sezon fotbalistic = 1 iulie - 30 iunie."""
    d = date.fromisoformat(str(kickoff_date)[:10])
    return d.year if d >= date(d.year, 7, 1) else d.year - 1


class StandingsTracker:
    """
    Reconstruiește clasamentul cronologic (puncte, meciuri jucate, golaveraj)
    per (ligă, sezon, echipă), procesând meciurile în ordine cronologică.

    La fiecare meci, returnează clasamentul ÎNAINTE de acel meci — exact
    același model ca ELOTracker.get_elos_before_match() → process_match().

    [IMPORTANT — compatibilitate cu izolarea pe ligă] La fel ca ELOTracker/
    FormTracker/H2HTracker, acest tracker NU distinge singur între ligi — dacă
    e alimentat cu un flux cronologic care amestecă mai multe ligi (cazul
    run_backfill() FĂRĂ --league), rezultatul ar fi corect DOAR dacă `league`
    e trecut corect la fiecare apel (cheia internă include liga). Rămâne însă
    responsabilitatea apelantului să nu amestece sezoane/ligi diferite ca și
    cum ar fi aceeași competiție — acest tracker respectă izolarea DACĂ i se
    dă liga corectă per meci, dar nu o poate detecta singur dacă apelantul
    greșește. Pattern identic cu izolarea deja folosită în
    sync/bootstrap_league_learning.py (tracker-e proaspete per ligă).

    [FALLBACK — decizie explicită, nu ascunsă] Pentru o echipă fără niciun
    meci jucat în sezonul curent (primul ei meci din sezon — inclusiv echipe
    promovate), get_standings_before() returnează rank=None și ppg=None,
    NU o valoare neutră implicită. Alegerea fallback-ului (ex. "mijlocul
    clasamentului" sau altă valoare) e o decizie de arhitectură separată,
    pentru stratul care consumă acest tracker (feature_engine.py), nu ceva
    de ascuns aici — la fel cum ELOTracker ISI ALEGE explicit 1500 ca
    default, dar acolo a fost o decizie asumată, nu o valoare arbitrară.
    """

    def __init__(self):
        # {(league, season_start_year, team): {"points", "played", "gf", "ga"}}
        self.table: dict[tuple, dict] = {}

    def _key(self, league: str, season_year: int, team: str) -> tuple:
        return (league, season_year, team)

    def _ensure(self, league: str, season_year: int, team: str) -> dict:
        key = self._key(league, season_year, team)
        if key not in self.table:
            self.table[key] = {"points": 0, "played": 0, "gf": 0, "ga": 0}
        return self.table[key]

    def _rank(self, league: str, season_year: int, team: str) -> int | None:
        """Rank 1-indexat, tie-break standard (puncte, apoi golaveraj, apoi
        goluri marcate) — identic cu regula folosită în clasamentele reale."""
        entries = [
            (k[2], v) for k, v in self.table.items()
            if k[0] == league and k[1] == season_year
        ]
        if not entries:
            return None
        ranked = sorted(
            entries,
            key=lambda kv: (-kv[1]["points"], -(kv[1]["gf"] - kv[1]["ga"]), -kv[1]["gf"]),
        )
        for i, (t, _) in enumerate(ranked):
            if t == team:
                return i + 1
        return None

    def get_standings_before(self, league: str, kickoff_date: str, home: str, away: str) -> dict:
        """Returnează clasamentul ÎNAINTE de acest meci pentru ambele echipe.
        Trebuie apelat înainte de process_match() pentru ACELAȘI meci."""
        season_year = _season_start_year(kickoff_date)
        home_key = self._key(league, season_year, home)
        away_key = self._key(league, season_year, away)
        home_stats = self.table.get(home_key, {"points": 0, "played": 0, "gf": 0, "ga": 0})
        away_stats = self.table.get(away_key, {"points": 0, "played": 0, "gf": 0, "ga": 0})

        home_ppg = round(home_stats["points"] / home_stats["played"], 4) if home_stats["played"] > 0 else None
        away_ppg = round(away_stats["points"] / away_stats["played"], 4) if away_stats["played"] > 0 else None

        return {
            "season_year": season_year,
            "home_rank": self._rank(league, season_year, home),
            "away_rank": self._rank(league, season_year, away),
            "home_points": home_stats["points"], "home_played": home_stats["played"],
            "away_points": away_stats["points"], "away_played": away_stats["played"],
            "home_ppg": home_ppg, "away_ppg": away_ppg,
            "n_teams_so_far": len({k[2] for k in self.table if k[0] == league and k[1] == season_year}),
        }

    def process_match(
        self, league: str, kickoff_date: str, home: str, away: str,
        home_goals: int, away_goals: int, result: str,
    ) -> None:
        """Actualizează clasamentul DUPĂ ce am citit starea 'înainte' (vezi
        get_standings_before) — aceeași ordine ca la ELOTracker/FormTracker."""
        season_year = _season_start_year(kickoff_date)
        home_stats = self._ensure(league, season_year, home)
        away_stats = self._ensure(league, season_year, away)

        home_stats["played"] += 1
        away_stats["played"] += 1
        home_stats["gf"] += home_goals
        home_stats["ga"] += away_goals
        away_stats["gf"] += away_goals
        away_stats["ga"] += home_goals

        pts_home, pts_away = {"H": (3, 0), "A": (0, 3)}.get(result, (1, 1))
        home_stats["points"] += pts_home
        away_stats["points"] += pts_away


# ════════════════════════════════════════════════════════════════════════════
# REST DAYS / FIXTURE CONGESTION
# ════════════════════════════════════════════════════════════════════════════

class RestDaysTracker:
    """
    Urmărește data ULTIMULUI meci jucat de fiecare echipă, INDIFERENT de
    competiție — calculează zile de odihnă înainte de meciul curent.

    [DECIZIE ARHITECTURALĂ — diferită de ELOTracker/FormTracker/StandingsTracker]
    Acelea sunt izolate per ligă (corect — formă/ELO/clasament sunt semnale
    specifice unei competiții). Oboseala fizică NU e specifică unei competiții:
    o echipă care joacă marți în Champions League e obosită sâmbătă în
    campionatul intern, indiferent cum sunt izolate celelalte tracker-e.
    De aceea acest tracker trebuie alimentat cu fluxul GLOBAL de meciuri ale
    unei echipe (toate competițiile), nu cu fluxul izolat per-ligă al
    bootstrap-ului. Dacă e folosit într-un backfill filtrat pe o singură
    ligă (--league), valoarea calculată va fi incompletă (nu vede meciurile
    din alte competiții) — limitare cunoscută, nu ascunsă.

    La fiecare meci, returnează zilele de odihnă ÎNAINTE de acel meci
    (None dacă echipa nu are niciun meci anterior cunoscut).
    """

    def __init__(self):
        self.last_match_date: dict[str, str] = {}  # team -> "YYYY-MM-DD"

    def get_rest_days_before(self, team: str, kickoff_date: str) -> int | None:
        last = self.last_match_date.get(team)
        if last is None:
            return None
        d_last = date.fromisoformat(last)
        d_now = date.fromisoformat(str(kickoff_date)[:10])
        return (d_now - d_last).days

    def process_match(self, home: str, away: str, kickoff_date: str) -> None:
        kd = str(kickoff_date)[:10]
        self.last_match_date[home] = kd
        self.last_match_date[away] = kd


# ════════════════════════════════════════════════════════════════════════════
# RATING OFENSIV/DEFENSIV PRE-MECI — SURSĂ UNICĂ (live/backfill/bootstrap)
# ════════════════════════════════════════════════════════════════════════════

def team_pre_match_rating(
    team: str, league: str,
    elo_tracker: "ELOTracker", form_tracker: "FormTracker",
    weights: dict, config: dict,
    shots_tracker: "ShotsTracker | None" = None,
) -> tuple[float, float, float, int]:
    """
    Calculează (offensive_rating, defensive_rating, form_score, elo_before)
    pentru o echipă, ÎNAINTE de meciul curent.

    [UNIFICARE — v3] Această funcție e acum SINGURA cale prin care se
    calculează offensive/defensive rating în afara fluxului live — folosită
    IDENTIC de run_backfill() (mai jos) ȘI de
    sync/bootstrap_league_learning.py (care o importă de aici, nu mai are
    propria copie). Înainte, backfill folosea o formulă proprie simplificată
    (FormTracker.calculate_ratings(), eliminată) care ignora complet
    goals_weight/shots_ot_weight/possession_weight și blend-ul ELO —
    o divergență de model deja documentată în feature_engine.py, acum
    rezolvată. Matematica de transformare (compute_team_offdef_rating) e
    identică cu cea din oracle_engine._build_profile() — fluxul live diferă
    doar prin SURSA datelor brute (API extern vs istoric replay-uit local),
    nu prin formulă.

    Fallback identic cu cascada live: dacă echipa nu are încă niciun meci
    în istoricul acestei ligi → Level "ELO only" (fără formă, fără blend
    din statistici — ELO există mereu, chiar la valoarea inițială 1500).

    `elo_tracker`/`form_tracker` trebuie scopate la o singură ligă (replay
    independent) — la fel ca în sync/bootstrap_league_learning.py — altfel
    "istoricul" folosit ar amesteca competiții diferite.
    """
    elo_before = round(elo_tracker.get_elo(team))
    elo_off = elo_to_offensive_multiplier(
        elo_before, config.get("elo_reference", 1500.0), config.get("elo_sigmoid_scale", 400.0)
    )
    elo_def = elo_to_defensive_multiplier(
        elo_before, config.get("elo_reference", 1500.0), config.get("elo_sigmoid_scale", 400.0)
    )

    form = form_tracker.get_form(team)
    lw = resolve_league_weights(weights, league)
    baselines = weights.get("league_baselines", {})
    baseline = float(baselines.get(league, baselines.get("default", 1.25)))

    if form:
        avg_gf = sum(gf for _, gf, _ in form) / len(form)
        avg_ga = sum(ga for _, _, ga in form) / len(form)
        real_sot = shots_tracker.get_avg_shots_on_target(team) if shots_tracker else None
        avg_sot = real_sot if real_sot is not None else avg_gf * 0.45  # proxy — fallback cand nu exista date reale
        avg_pos = 50.0            # neutru — posesie absentă 100% din Kaggle

        off_rating, def_rating = compute_team_offdef_rating(
            avg_goals_for=avg_gf, avg_goals_against=avg_ga,
            avg_shots_on_target=avg_sot, avg_possession=avg_pos,
            goals_weight=lw["goals_weight"], shots_ot_weight=lw["shots_ot_weight"],
            possession_weight=lw["possession_weight"],
            offensive_cap=float(weights.get("offensive_cap", 3.5)),
            defensive_cap=float(weights.get("defensive_cap", 2.5)),
            elo_offensive_multiplier=elo_off, elo_defensive_multiplier=elo_def,
            elo_blend_weight=float(config.get("elo_blend_weight", 0.35)),
        )
        form_score = form_tracker.calculate_form_score(team)
    else:
        off_rating = round(elo_off * baseline, 4)
        def_rating = round(elo_def, 4)
        form_score = 0.0

    return off_rating, def_rating, form_score, elo_before


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRATORUL PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def run_backfill(
    league: str | None = None,
    batch_size: int = 50,
    dry_run: bool = False,
    weights: dict | None = None,
    config: dict | None = None,
) -> dict:
    """
    Procesează toate meciurile din match_history și completează feature-urile ML.

    Strategia (gating per-coloană, non-destructiv — v4.1):
    1. Încarcă TOATE meciurile în ordine cronologică, cu toate cele 10
       coloane de feature (pentru a putea verifica NULL per-coloană)
    2. Procesează-le unul câte unul, menținând starea ELO/formă/H2H
    3. Pentru fiecare meci:
       a. Citește ELO/formă/H2H ÎNAINTE de meci (feature-uri ML) — se
          calculează întotdeauna, indiferent de completitudinea rândului
       b. Scrie DOAR coloanele ale căror valori curente sunt NULL — o
          coloană deja populată nu e niciodată suprascrisă
       c. Actualizează ELO/formă/H2H cu rezultatul meciului (întotdeauna,
          indiferent dacă rândul a fost scris sau sărit — starea replay-ului
          trebuie să avanseze pe toate meciurile, nu doar pe cele incomplete)
    4. Un rând deja complet (toate cele 10 coloane populate) e sărit la
       pasul b, fără niciun apel de UPDATE

    [UNIFICARE — v3] `weights`/`config`: dacă nu sunt date explicit, se
    încarcă din Supabase (model_weights/model_config — sursa reală de adevăr
    în producție), cu DEFAULT_WEIGHTS/DEFAULT_CONFIG din oracle_engine.py ca
    fallback — EXACT aceeași strategie de încărcare ca la pornirea motorului
    live (oracle_engine.FootballOracleEngine.__init__). Necesare acum pentru
    team_pre_match_rating() (goals_weight/shots_ot_weight/possession_weight/
    elo_blend_weight/league_baselines) — înainte, backfill nu avea nevoie de
    ponderi deloc, fiindcă folosea formula proprie simplificată (eliminată).
    """
    if weights is None or config is None:
        from oracle_engine import DEFAULT_WEIGHTS, DEFAULT_CONFIG
        try:
            import supabase_client as sb
            if weights is None:
                weights = sb.load_weights(DEFAULT_WEIGHTS) if sb.is_available() else dict(DEFAULT_WEIGHTS)
            if config is None:
                config = sb.load_config(DEFAULT_CONFIG) if sb.is_available() else dict(DEFAULT_CONFIG)
        except ModuleNotFoundError:
            weights = weights if weights is not None else dict(DEFAULT_WEIGHTS)
            config = config if config is not None else dict(DEFAULT_CONFIG)

    start_time = time.time()
    logger.info("═" * 60)
    logger.info("  FOOTBALL ORACLE — Backfill Features")
    logger.info("  Liga: %s | Batch: %d | Dry run: %s",
                league or "toate", batch_size, dry_run)
    logger.info("═" * 60)

    # 1. Încarcă toate meciurile
    all_matches = fetch_all_matches(league)
    if not all_matches:
        logger.warning("[Backfill] Niciun meci găsit!")
        return {"status": "error", "message": "Niciun meci găsit"}

    total = len(all_matches)
    # [FIX v4.1] Completitudinea reală se verifică per-coloană (NULL check),
    # nu prin flag-ul `backfill_done` — acesta poate fi inexact tocmai din
    # cauza disjuncției pe care acest fix o repară (vezi header-ul modulului).
    already_done = sum(1 for m in all_matches if not _missing_feature_columns(m))
    to_process = total - already_done

    logger.info("[Backfill] Total meciuri: %d | Deja complete (toate cele %d coloane): %d | De completat: %d",
                total, len(FEATURE_COLUMNS), already_done, to_process)

    if to_process == 0:
        logger.info("[Backfill] Toate meciurile sunt deja procesate!")
        return {"status": "done", "processed": 0, "already_done": already_done}

    # 2. Inițializăm tracker-ele
    elo_tracker        = ELOTracker()
    form_tracker       = FormTracker()
    h2h_tracker        = H2HTracker()
    shots_tracker      = ShotsTracker()
    corner_card_tracker = CornerCardTracker()

    # 3. Procesăm meciurile în ordine cronologică
    pending_updates: list[tuple[int, dict]] = []
    processed = 0
    skipped   = 0
    errors    = 0

    for i, match in enumerate(all_matches):
        home   = match.get("home_team", "")
        away   = match.get("away_team", "")
        result = match.get("actual_result", "")
        hg     = match.get("actual_home_goals", 0) or 0
        ag     = match.get("actual_away_goals", 0) or 0

        if not home or not away or not result:
            continue

        # Citim feature-urile ÎNAINTE de meci
        match_league = match.get("league", "") or (league or "")
        home_elo, away_elo = elo_tracker.get_elos_before_match(home, away)
        home_off, home_def, home_form, _ = team_pre_match_rating(
            home, match_league, elo_tracker, form_tracker, weights, config, shots_tracker
        )
        away_off, away_def, away_form, _ = team_pre_match_rating(
            away, match_league, elo_tracker, form_tracker, weights, config, shots_tracker
        )
        h2h_mod, h2h_meet  = h2h_tracker.get_h2h_before(home, away)
        home_corner_avg = corner_card_tracker.get_avg_corners(home)
        away_corner_avg = corner_card_tracker.get_avg_corners(away)
        home_card_avg   = corner_card_tracker.get_avg_cards(home)
        away_card_avg   = corner_card_tracker.get_avg_cards(away)

        # [FIX v4.1] Gating per-coloană: se scrie DOAR subsetul de coloane
        # ale căror valori curente sunt NULL — o coloană deja populată
        # (ex. home_elo real din Kaggle) nu e niciodată inclusă în payload,
        # deci nu e niciodată suprascrisă. Rândurile complete (toate cele
        # 10 coloane deja populate) primesc missing == [] și sunt sărite
        # complet, fără niciun apel de UPDATE.
        missing = _missing_feature_columns(match)
        if missing:
            computed = {
                "home_elo":               home_elo,
                "away_elo":               away_elo,
                "home_form_score":        home_form,
                "away_form_score":        away_form,
                "home_offensive_rating":  home_off,
                "home_defensive_rating":  home_def,
                "away_offensive_rating":  away_off,
                "away_defensive_rating":  away_def,
                "h2h_modifier":           h2h_mod,
                "h2h_meetings":           h2h_meet,
                "home_corner_avg_recent": home_corner_avg,
                "away_corner_avg_recent": away_corner_avg,
                "home_card_avg_recent":   home_card_avg,
                "away_card_avg_recent":   away_card_avg,
            }
            # [Regula #13] Nu scriem None peste None — dacă tracker-ul de
            # cornere/cartonașe nu are încă istoric real (ex. primul meci al
            # unei echipe din dataset), valoarea calculată e None și rămâne
            # None la infinit; scrierea ei ar genera UPDATE-uri redundante
            # la fiecare rulare, fără să schimbe vreodată starea din DB.
            features = {col: computed[col] for col in missing if computed[col] is not None}
            if features:
                pending_updates.append((match["id"], features))

        # Actualizăm starea tracker-elor (indiferent dacă meciul era deja procesat)
        elo_tracker.process_match(home, away, result)
        form_tracker.process_match(home, away, hg, ag, result)
        h2h_tracker.process_match(home, away, result, hg, ag)
        shots_tracker.process_match(home, away, match.get("home_shots_on_target"), match.get("away_shots_on_target"))
        corner_card_tracker.process_match(
            home, away,
            match.get("home_corners"), match.get("away_corners"),
            match.get("home_yellow_cards"), match.get("away_yellow_cards"),
        )

        # Scriem în batch
        if len(pending_updates) >= batch_size:
            if not dry_run:
                ok, err = bulk_update_features(pending_updates)
                processed += ok
                errors    += err
            else:
                processed += len(pending_updates)

            pending_updates = []

            # Progress log
            pct = (i + 1) / total * 100
            logger.info(
                "[Backfill] Progress: %d/%d (%.1f%%) | Procesate: %d | Erori: %d",
                i + 1, total, pct, processed, errors
            )

    # Scriem ultimul batch
    if pending_updates:
        if not dry_run:
            ok, err = bulk_update_features(pending_updates)
            processed += ok
            errors    += err
        else:
            processed += len(pending_updates)

    duration = round(time.time() - start_time, 1)

    logger.info("═" * 60)
    logger.info("  BACKFILL COMPLET")
    logger.info("  Procesate : %d", processed)
    logger.info("  Erori     : %d", errors)
    logger.info("  Durată    : %ss", duration)
    logger.info("═" * 60)

    return {
        "status":       "done",
        "total":        total,
        "processed":    processed,
        "already_done": already_done,
        "errors":       errors,
        "duration_sec": duration,
    }


def main():
    parser = argparse.ArgumentParser(description="Football Oracle — Backfill Features")
    parser.add_argument("--league",     type=str, default=None,
                        help="Procesează doar o ligă specifică")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Numărul de meciuri per batch (default: 50)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Simulare fără scriere în Supabase")
    args = parser.parse_args()

    result = run_backfill(
        league     = args.league,
        batch_size = args.batch_size,
        dry_run    = args.dry_run,
    )

    if result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
