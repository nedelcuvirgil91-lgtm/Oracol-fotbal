"""
================================================================================
FOOTBALL ORACLE — Flashscore Team DNA (Faza 2, ADR-044 §5)
================================================================================
Module: flashscore_team_dna.py

Funcții PURE (fără I/O — la fel ca feature_engine.py), care agregă rândurile
deja citite din Foundation Data Layer (database.queries.get_team_recent_*)
în statistici rolling per echipă: xG real, posesie reală, cornere/faulturi/
cartonașe (extinse cu roșii/offside/apărări), pase/dueluri/tackle-uri
(EAV), rating mediu jucători, tendință acasă/deplasare.

Aditiv, izolat de TeamProfile — NU produce `avg_possession`/`avg_shots_ot`
(deja parametri ai compute_team_offdef_rating(), deci ai blending-ului,
în feature_engine.py). Ieșirea de aici e context suplimentar, afișat și
disponibil pentru feature engineering ML viitor (FEATURE_COLUMNS rămâne
neatins azi — orice promovare cere test de ablație, per regulile ML din
CLAUDE.md).

Zero scurgere temporală: intrarea vine deja filtrată pe meciuri TERMINATE
(database.queries.get_team_recent_*) — acest modul doar agregă, nu
filtrează pe dată.
================================================================================
"""
from __future__ import annotations


def rolling_advanced_stats(rows: list[dict], canonical: str) -> dict:
    """xG real/posesie reală/offside/apărări portar/cartonașe roșii,
    medie pe rândurile primite (database.queries.get_team_recent_advanced_
    stats). Valorile lipsă rămân None — nu se aproximează (Regula #8)."""
    xg, poss, offsides, saves, reds, goals_for, goals_against = [], [], [], [], [], [], []
    for r in rows:
        is_home = r.get("home_team") == canonical
        is_away = r.get("away_team") == canonical
        if not (is_home or is_away):
            continue
        side = "home" if is_home else "away"
        opp_side = "away" if is_home else "home"
        for values, key in (
            (xg, f"{side}_xg_actual"), (poss, f"{side}_possession"),
            (offsides, f"{side}_offsides"), (saves, f"{side}_goalkeeper_saves"),
            (reds, f"{side}_red_cards"),
        ):
            v = r.get(key)
            if v is not None:
                values.append(float(v))
        gf = r.get(f"actual_{side}_goals")
        ga = r.get(f"actual_{opp_side}_goals")
        if gf is not None:
            goals_for.append(float(gf))
        if ga is not None:
            goals_against.append(float(ga))

    def _avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "avg_xg": _avg(xg), "avg_possession": _avg(poss),
        "avg_offsides": _avg(offsides), "avg_goalkeeper_saves": _avg(saves),
        "avg_red_cards": _avg(reds),
        "avg_goals_for": _avg(goals_for), "avg_goals_against": _avg(goals_against),
        "matches_sampled": len(rows),
    }


def rolling_finishing_and_setpieces(rows: list[dict], canonical: str) -> dict:
    """Eficiență finalizare (goluri/xG real, goluri/șuturi pe poartă) +
    volum faze fixe (cornere/meci) — pe SUMELE agregate pe perechi
    aliniate per meci (nu media rapoartelor per meci, care ar exploda la
    meciuri cu 0 șuturi pe poartă, și nu ar aduna goluri dintr-un meci cu
    xG dintr-un meci diferit dacă unul din cele două lipsește). Cere
    aceleași rânduri ca rolling_advanced_stats, extinse cu home/away_
    shots_on_target și home/away_corners — vezi database.queries.
    get_team_recent_advanced_stats(). Eficiența la faze fixe (cornere/
    lovituri libere -> gol) NU e calculabilă azi — match_events.detail
    (tipul de asistență la gol) nu e populat încă (verificat live,
    2026-08-15) — doar volumul, niciodată aproximată conversia."""
    goals_xg_pairs: list[tuple[float, float]] = []
    goals_sot_pairs: list[tuple[float, float]] = []
    corners: list[float] = []
    n_matches = 0
    for r in rows:
        is_home = r.get("home_team") == canonical
        is_away = r.get("away_team") == canonical
        if not (is_home or is_away):
            continue
        n_matches += 1
        side = "home" if is_home else "away"
        g = r.get(f"actual_{side}_goals")
        xg = r.get(f"{side}_xg_actual")
        sot = r.get(f"{side}_shots_on_target")
        cor = r.get(f"{side}_corners")
        if g is not None and xg is not None:
            goals_xg_pairs.append((float(g), float(xg)))
        if g is not None and sot is not None:
            goals_sot_pairs.append((float(g), float(sot)))
        if cor is not None:
            corners.append(float(cor))

    def _sum_ratio(pairs: list[tuple[float, float]]) -> float | None:
        if not pairs:
            return None
        denom = sum(p[1] for p in pairs)
        return sum(p[0] for p in pairs) / denom if denom > 0 else None

    return {
        "goals_per_xg": _sum_ratio(goals_xg_pairs),
        "goals_per_shot_on_target": _sum_ratio(goals_sot_pairs),
        "avg_corners": sum(corners) / len(corners) if corners else None,
        "matches_sampled": n_matches,
        "finishing_sample_matches": len(goals_xg_pairs),
    }


def rolling_extended_stats(rows: list[dict]) -> dict[str, float]:
    """Medie per `stat_key`, din rândurile deja rezolvate la partea
    corectă (database.queries.get_team_recent_statistics_extended) —
    pase/dueluri/tackle-uri/big_chances/etc., orice etichetă EAV găsită
    real pe fixture-urile colectate. Cheile prezente depind strict de ce
    a extras Flashscore — niciun stat_key nu e presupus/ghicit."""
    buckets: dict[str, list[float]] = {}
    for r in rows:
        key = r.get("stat_key")
        value = r.get("value")
        if key is None or value is None:
            continue
        buckets.setdefault(key, []).append(float(value))
    return {key: sum(values) / len(values) for key, values in buckets.items()}


def rolling_player_ratings(rows: list[dict]) -> dict:
    """Rating mediu (`player_match_stats.rating`), ponderat simplu pe
    numărul de jucători eșantionați — din database.queries.get_team_
    recent_player_ratings(). None dacă niciun rating real nu există."""
    ratings = [float(r["rating"]) for r in rows if r.get("rating") is not None]
    if not ratings:
        return {"avg_player_rating": None, "players_sampled": 0}
    return {
        "avg_player_rating": sum(ratings) / len(ratings),
        "players_sampled": len(ratings),
    }


def build_team_dna(
    advanced_rows: list[dict],
    extended_rows: list[dict],
    player_rows: list[dict],
    standings_row: dict | None,
    canonical: str,
) -> dict:
    """Combină cele 4 agregări de mai sus + un snapshot de clasament
    (deja per-echipă, database.queries.get_team_standings_row) într-un
    singur dict "Team DNA" Flashscore — folosit atât pentru afișare
    (Streamlit) cât și ca fundație de feature engineering ML viitor.
    Fiecare secțiune degradează independent la valori goale/None dacă
    Flashscore n-a colectat încă date suficiente pentru acea echipă —
    niciodată aproximat dintr-o altă secțiune.

    `finishing` reutilizează `advanced_rows` (nu un al 5-lea parametru) —
    rolling_finishing_and_setpieces() cere exact aceleași coloane deja
    citite de rolling_advanced_stats() (plus șuturi pe poartă/cornere,
    deja incluse în get_team_recent_advanced_stats())."""
    return {
        "advanced": rolling_advanced_stats(advanced_rows, canonical),
        "finishing": rolling_finishing_and_setpieces(advanced_rows, canonical),
        "extended_stats": rolling_extended_stats(extended_rows),
        "player_ratings": rolling_player_ratings(player_rows),
        "standings": standings_row,
    }
