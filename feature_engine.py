"""
================================================================================
FOOTBALL ORACLE — Feature Engine (matematică pură, sursă unică de adevăr)
================================================================================
Module: feature_engine.py

Acest modul conține DOAR matematica ce este cu adevărat comună între:
  - oracle_engine.py       (motorul live, predicții în timp real)
  - sync/backfill_features.py (reconstrucție retrospectivă din match_history)

Ce NU conține acest modul (intenționat):
  - Calculul ratingului ELO de la zero (K-factor, istoric cronologic) —
    responsabilitate exclusivă a bootstrap-ului (ELOTracker din
    sync/backfill_features.py). Sunt două responsabilități diferite, nu
    aceeași matematică — nu se unifică aici.
    [NOTĂ — ADR-023 Phase 6 / ADR-035 D2, finalizată 2026-07-20] Motorul
    live citește acum ELO-ul PRIMAR din match_history.home_elo_after/
    away_elo_after (Canonical Live ELO Snapshot) prin
    database.queries.get_latest_team_elo() — vezi
    docs/00_GOVERNANCE/ADR-023-canonical-live-elo-source.md.
    [ACTUALIZAT — ADR-039 R-Sync-4] Fallback-ul pentru echipele naționale
    (fără meciuri de club sincronizate) citește acum STRICT din Supabase
    (database.queries.get_national_team_elo(), national_team_elo_snapshot)
    — API-ul extern (oracle_api.get_elo_rating(), eloratings.net) nu mai e
    apelat live de motor, doar de Sync Layer (sync/sync_national_team_elo.py).
  - Formula de calcul a offensive_rating/defensive_rating din backfill
    (FormTracker.calculate_ratings), care în prezent NU include blend-ul ELO
    folosit de motorul live. Aceasta este o divergență de MODEL cunoscută și
    asumată temporar — se tratează separat, ca decizie ulterioară, nu ca
    refactor.

Toate funcțiile de aici sunt pure (fără stare, fără I/O) și trebuie
reutilizate identic de ambele componente, nu reimplementate.
================================================================================
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import poisson

# ── Form score ──────────────────────────────────────────────────────────────

_FORM_RESULT_VALUES = {"W": 1.0, "D": 0.4, "L": 0.0}


def compute_form_score(results: list[str]) -> float:
    """
    Scor de formă (0-1) pe baza rezultatelor recente (W/D/L), cu ponderare
    exponențială care favorizează meciurile recente.

    `results` trebuie ordonat cronologic, cu cel mai recent rezultat ca
    ULTIM element din listă (index mai mare = pondere mai mare = 2**i).

    Pentru listă goală întoarce 0.0 (nu e un caz special — apelanții care
    vor o valoare neutră (ex. 0.5) pentru "fără istoric" trebuie să trateze
    asta explicit înainte de a apela această funcție, la fel cum se
    întâmplă deja în FormTracker).
    """
    if not results:
        return 0.0
    weights = [2 ** i for i in range(len(results))]
    total_weight = sum(weights) or 1
    score = sum(
        _FORM_RESULT_VALUES.get(r, 0.4) * weights[i]
        for i, r in enumerate(results)
    ) / total_weight
    return round(score, 4)


# ── H2H modifier ──────────────────────────────────────────────────────────────

def compute_h2h_modifier(home_wins: int, away_wins: int, n: int, weight: float = 0.15) -> float:
    """
    Modificator H2H pe baza dominanței (home_wins - away_wins) / n.
    Pozitiv = avantaj gazdă, negativ = avantaj oaspete.

    `n` (numărul de întâlniri) trebuie să fie >= 1 la apel; apelanții
    verifică deja asta înainte (return 0.0 dacă nu există istoric H2H).
    """
    if n <= 0:
        return 0.0
    dominance = (home_wins - away_wins) / n
    return round(dominance * weight, 4)


# ── Transformări ELO → multiplicator sigmoid ─────────────────────────────────
# NOTĂ: acestea transformă un rating ELO deja existent într-un multiplicator
# ofensiv/defensiv. NU calculează ratingul ELO în sine (asta rămâne treaba
# ELOTracker-ului din backfill, respectiv a API-ului live).

def elo_to_offensive_multiplier(elo: float, reference: float = 1500.0, scale: float = 400.0) -> float:
    sigmoid = 1.0 / (1.0 + math.exp(-((elo - reference) / scale)))
    return round(0.55 + sigmoid * 1.10, 4)


def elo_to_defensive_multiplier(elo: float, reference: float = 1500.0, scale: float = 400.0) -> float:
    sigmoid = 1.0 / (1.0 + math.exp(-((elo - reference) / scale)))
    return round(1.80 - sigmoid * 1.20, 4)


# ── Rest days / fixture congestion → multiplicator ───────────────────────────
# NOTĂ: transformare PURĂ (rest_days brut -> multiplicator xG). Sursa
# rest_days (calculul zilelor de odihnă) rămâne treaba RestDaysTracker din
# sync/backfill_features.py — aceeași separare stare/matematică ca la ELO.

def rest_days_modifier(
    rest_days: int | None,
    threshold_days: int = 4,
    penalty: float = 0.05,
) -> float:
    """
    Multiplicator xG pentru o echipă, pe baza zilelor de odihnă înainte de
    meci. Dacă `rest_days` e None (nicio informație — primul meci cunoscut
    al echipei) sau >= `threshold_days`, returnează 1.0 (neutru, fără
    penalizare). Sub prag (relansare rapidă — ex. jocuri la 2-3 zile
    distanță, tipic pentru echipe cu calendar european încărcat), aplică o
    penalizare fixă `penalty` (ex. 0.05 = -5% xG).

    Nu face nicio presupunere asupra unui bonus pentru odihnă foarte lungă
    (>threshold) — literatura pe acest efect ("lipsă de ritm") e mult mai
    puțin robustă decât cea pe oboseala de congestie, deci nu e modelată.
    """
    if rest_days is None or rest_days >= threshold_days:
        return 1.0
    return round(1.0 - penalty, 4)


# ── Calibrare xG ──────────────────────────────────────────────────────────────

def calibrate_xg(
    home_offensive_rating: float,
    home_defensive_rating: float,
    away_offensive_rating: float,
    away_defensive_rating: float,
    home_form_score: float,
    away_form_score: float,
    baseline: float,
    form_weight: float,
    dna_weight: float,
    home_advantage: float,
    away_penalty: float,
    defensive_cap: float,
    h2h_modifier: float = 0.0,
    h2h_meetings: int = 0,
    weather_penalty: float = 0.0,
) -> tuple[float, float]:
    """
    Calculează xG-ul calibrat pentru ambele echipe. Matematică pură,
    identică cu cea folosită anterior inline în oracle_engine._calibrate_xg().
    """
    away_def_mod  = 0.60 + (away_defensive_rating / defensive_cap) * 0.80
    home_def_mod  = 0.60 + (home_defensive_rating / defensive_cap) * 0.80
    home_form_mod = 0.80 + home_form_score * 0.40
    away_form_mod = 0.80 + away_form_score * 0.40

    home_xg = home_offensive_rating * away_def_mod * baseline * (form_weight * home_form_mod + dna_weight) * home_advantage
    away_xg = away_offensive_rating * home_def_mod * baseline * (form_weight * away_form_mod + dna_weight) * away_penalty

    if h2h_meetings >= 2:
        home_xg = home_xg * (1 + h2h_modifier)
        away_xg = away_xg * (1 - h2h_modifier)

    if weather_penalty > 0:
        home_xg *= (1 - weather_penalty)
        away_xg *= (1 - weather_penalty)

    home_xg = round(max(home_xg, 0.20), 4)
    away_xg = round(max(away_xg, 0.20), 4)
    return home_xg, away_xg


# ── Rezolvare ponderi per-ligă (blend global ↔ per-ligă auto-învățat) ────────

def resolve_league_weights(weights: dict, league: str) -> dict:
    """
    Face blend între ponderile globale și cele specifice unei ligi, ponderat
    de `sample_count` (cu cât liga a acumulat mai multe rezultate reale, cu
    atât ponderile ei proprii cântăresc mai mult, saturând la sample_count=5).

    Matematică pură, identică cu cea folosită anterior inline în
    oracle_engine._get_league_weights(). `weights` este dict-ul complet de
    ponderi (global + league_weights), la fel ca self.weights din motorul live.
    """
    lw_all = weights.get("league_weights", {})
    lw     = lw_all.get(league, lw_all.get("default", {}))
    sc     = int(lw.get("sample_count", 0))
    alpha  = min(sc / 5.0, 1.0)

    def _blend(key, default):
        lv = float(lw.get(key, weights.get(key, default)))
        gv = float(weights.get(key, default))
        return alpha * lv + (1 - alpha) * gv

    return {
        "form_weight":       _blend("form_weight",       0.60),
        "dna_weight":        _blend("dna_weight",        0.40),
        "goals_weight":      _blend("goals_weight",      0.45),
        "shots_ot_weight":   _blend("shots_ot_weight",   0.30),
        "possession_weight": _blend("possession_weight", 0.25),
        "home_advantage":    _blend("home_advantage",    1.07),
        "away_penalty":      _blend("away_penalty",      0.95),
        "sample_count":      sc,
    }


# ── Rating ofensiv/defensiv dintr-un set de statistici medii ─────────────────

def compute_team_offdef_rating(
    avg_goals_for: float,
    avg_goals_against: float,
    avg_shots_on_target: float,
    avg_possession: float,
    goals_weight: float,
    shots_ot_weight: float,
    possession_weight: float,
    offensive_cap: float,
    defensive_cap: float,
    elo_offensive_multiplier: float | None = None,
    elo_defensive_multiplier: float | None = None,
    elo_blend_weight: float = 0.35,
) -> tuple[float, float]:
    """
    Calculează ratingul ofensiv/defensiv al unei echipe din media statisticilor
    (goluri, șuturi pe poartă, posesie), blendat opțional cu multiplicatorul
    ELO. Matematică pură, identică cu blocul "Compute ratings din stats" din
    oracle_engine._build_profile().

    Dacă `elo_offensive_multiplier`/`elo_defensive_multiplier` sunt None,
    ratingul e folosit neblendat (echivalent cu elo_off is None în live).
    """
    g_norm   = min(avg_goals_for  / 2.0, 1.0) * 1.5
    sot_norm = min(avg_shots_on_target / 6.0, 1.0) * 1.5
    pos_norm = max(0.0, min(((avg_possession - 30.0) / 40.0) * 0.5, 0.5))

    off_stat = min(
        g_norm * goals_weight + sot_norm * shots_ot_weight + pos_norm * possession_weight
        + avg_goals_for * 0.2,
        offensive_cap,
    )
    def_stat = min(avg_goals_against, defensive_cap)

    if elo_offensive_multiplier is not None:
        off_rating = round((1 - elo_blend_weight) * off_stat + elo_blend_weight * elo_offensive_multiplier, 4)
        def_rating = round((1 - elo_blend_weight) * def_stat + elo_blend_weight * elo_defensive_multiplier, 4)
    else:
        off_rating = round(off_stat, 4)
        def_rating = round(def_stat, 4)

    off_rating = min(off_rating, offensive_cap)
    def_rating = min(def_rating, defensive_cap)
    return off_rating, def_rating


# ── Model Poisson ──────────────────────────────────────────────────────────────

def poisson_model(home_xg: float, away_xg: float, max_goals: int = 8) -> tuple[float, float, float, list]:
    """
    Matrice Poisson home/away și probabilitățile 1X2, plus top 6 scoruri
    exacte cele mai probabile. Matematică pură, identică cu
    oracle_engine._poisson_model().
    """
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            matrix[hg, ag] = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)

    ph = float(np.sum(np.tril(matrix, -1)))
    pd = float(np.sum(np.diag(matrix)))
    pa = float(np.sum(np.triu(matrix, 1)))

    scores = sorted(
        [(hg, ag, round(matrix[hg, ag] * 100, 2))
         for hg in range(max_goals + 1) for ag in range(max_goals + 1)],
        key=lambda x: x[2], reverse=True,
    )
    return ph, pd, pa, scores[:6]
