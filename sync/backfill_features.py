"""
================================================================================
FOOTBALL ORACLE v4.0 — Backfill Historical Features
================================================================================
Module: sync/backfill_features.py

Calculează retrospectiv feature-urile ML pentru toate meciurile din
match_history care nu au fost încă procesate (backfill_done = false).

Feature-uri calculate per meci (la momentul t al meciului):
  - ELO acasă/deplasare (calculat din toate meciurile ANTERIOARE acelui meci)
  - Forma acasă/deplasare (ultimele 5 meciuri înainte de acel meci)
  - Rating ofensiv/defensiv (din forma recentă)
  - H2H modifier (din meciurile anterioare dintre cele două echipe)

Strategia de resume:
  - Meciurile procesate sunt marcate cu backfill_done = true
  - La reluare, scriptul sare automat peste meciurile deja procesate
  - Sigur să fie oprit și reluat oricând

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
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from feature_engine import compute_form_score, compute_h2h_modifier

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
                    "backfill_done")
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

    def calculate_ratings(self, team: str) -> tuple[float, float]:
        """
        Calculează rating ofensiv și defensiv din forma recentă.
        Returnează (offensive_rating, defensive_rating).
        """
        form = self.get_form(team)
        if not form:
            return 1.0, 1.0

        avg_gf = sum(gf for _, gf, _ in form) / len(form)
        avg_ga = sum(ga for _, _, ga in form) / len(form)

        # Rating ofensiv: normalizat față de media ligii (1.25 goluri/meci)
        off_rating = round(min(avg_gf / 1.25, 3.5), 4)
        def_rating = round(min(avg_ga, 2.5), 4)

        return off_rating, def_rating

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
# ORCHESTRATORUL PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def run_backfill(
    league: str | None = None,
    batch_size: int = 50,
    dry_run: bool = False,
) -> dict:
    """
    Procesează toate meciurile din match_history și completează feature-urile ML.

    Strategia:
    1. Încarcă TOATE meciurile în ordine cronologică
    2. Procesează-le unul câte unul, menținând starea ELO/formă/H2H
    3. Pentru fiecare meci:
       a. Citește ELO/formă/H2H ÎNAINTE de meci (feature-uri ML)
       b. Dacă meciul nu e deja procesat (backfill_done=False), salvează feature-urile
       c. Actualizează ELO/formă/H2H cu rezultatul meciului
    4. Meciurile deja procesate (backfill_done=True) sară la pasul c direct
    """
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
    already_done = sum(1 for m in all_matches if m.get("backfill_done"))
    to_process = total - already_done

    logger.info("[Backfill] Total meciuri: %d | Deja procesate: %d | De procesat: %d",
                total, already_done, to_process)

    if to_process == 0:
        logger.info("[Backfill] Toate meciurile sunt deja procesate!")
        return {"status": "done", "processed": 0, "already_done": already_done}

    # 2. Inițializăm tracker-ele
    elo_tracker  = ELOTracker()
    form_tracker = FormTracker()
    h2h_tracker  = H2HTracker()

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
        home_elo, away_elo = elo_tracker.get_elos_before_match(home, away)
        home_form  = form_tracker.calculate_form_score(home)
        away_form  = form_tracker.calculate_form_score(away)
        home_off, home_def = form_tracker.calculate_ratings(home)
        away_off, away_def = form_tracker.calculate_ratings(away)
        h2h_mod, h2h_meet  = h2h_tracker.get_h2h_before(home, away)

        # Dacă meciul nu e deja procesat, adăugăm la lista de update-uri
        if not match.get("backfill_done"):
            features = {
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
            }
            pending_updates.append((match["id"], features))

        # Actualizăm starea tracker-elor (indiferent dacă meciul era deja procesat)
        elo_tracker.process_match(home, away, result)
        form_tracker.process_match(home, away, hg, ag, result)
        h2h_tracker.process_match(home, away, result, hg, ag)

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
