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
    sync/backfill_features.py), fiindcă motorul live obține ELO-ul deja
    calculat de la un API extern (get_elo_rating). Sunt două responsabilități
    diferite, nu aceeași matematică — nu se unifică aici.
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
