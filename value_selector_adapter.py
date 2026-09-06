"""
================================================================================
FOOTBALL ORACLE — Value Selector Adapter (ADR-071)
================================================================================
Module: value_selector_adapter.py

Singurul loc din stratul de selectie care stie ca o piata 1X2 are trei
rezultate. Traduce un `MatchPrediction` (produs de Oracle Engine) in trei
`SelectionCandidate` — dupa care `value_selector.py` le trateaza ca inregistrari
opace, fara sa mai stie care e care. Asa e impusa structural simetria H/X/A:
logica de decizie nu are cum sa se ramifice pe tipul selectiei, pentru ca nu-l
mai vede.

Citeste `MatchPrediction` prin `getattr` (duck typing), NU prin import din
`oracle_engine` — dependinta "in sus" e interzisa (North Star #10). Adaptorul
nu apeleaza motorul, nu recalculeaza nimic si nu modifica `model_p`: doar
transporta valorile deja produse.

Varstele (`prediction_age_s`, `odds_age_s`) si `seconds_to_kickoff` sunt
INJECTATE de apelant. `None` inseamna "nu stim" si ramane "nu stim" pana in
UI — nu se aproximeaza (Regula #8).

Nota, gol cunoscut si documentat (ADR-071 §16): `odds_age_s` e `None` in V1
pentru toate candidaturile. Timestamp-ul capturii cotei exista in
`odds_history` si e chiar folosit de `database/queries.py` ca sa aleaga cea mai
recenta casa de pariuri, dar e aruncat inainte de a ajunge la apelant.
Propagarea lui ar cere modificarea unor fisiere aflate in afara scopului V1.
Pana atunci, poarta de prospetime a cotei raporteaza `UNKNOWN`, niciodata
`PASS`.
================================================================================
"""
from __future__ import annotations

from typing import Any, Sequence

from value_selector import SelectionCandidate

# Clasele de calitate considerate insuficiente pentru Top Value Bets.
# `neutral` = profil construit din valori implicite, fara date reale despre
# echipa. Masurat pe date de productie: predictiile din aceasta clasa nu sunt
# doar mai slabe, ci pot fi constante identice pentru meciuri complet diferite
# (vezi docs/03_ENGINE/EUROPEAN_COMPETITION_FORM_FILTER_DEFECT.md).
INSUFFICIENT_DATA_QUALITY: frozenset[str] = frozenset({"neutral"})

_MARKET_1X2 = "1X2"

# Traducerea codului de selectie in codul de rezultat folosit de
# `match_history.actual_result`. Traieste AICI, nu in evaluator, pentru ca
# invariantul proiectului e "un singur modul stie ca piata 1X2 are trei
# rezultate" — la fel cum `candidates_from_prediction()` e singurul loc care
# construieste cele trei candidaturi. Evaluatorul o consuma, nu o redefineste.
REZULTAT_PENTRU_SELECTIE: dict[str, str] = {"1": "H", "X": "D", "2": "A"}


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _profile_matches_analysed(profile: Any) -> int | None:
    if profile is None:
        return None
    value = getattr(profile, "matches_analysed", None)
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _data_quality_pair(prediction: Any) -> tuple[str | None, bool | None]:
    """Calitatea agregata a meciului: cea mai slaba dintre cele doua echipe.
    Necunoscuta pe oricare parte -> agregat necunoscut (`None`), nu optimist."""
    home = getattr(getattr(prediction, "home_profile", None), "data_quality", None)
    away = getattr(getattr(prediction, "away_profile", None), "data_quality", None)
    if home is None and away is None:
        return None, None
    label = "/".join(str(q) if q is not None else "necunoscut" for q in (home, away))
    if home is None or away is None:
        return label, None
    sufficient = home not in INSUFFICIENT_DATA_QUALITY and away not in INSUFFICIENT_DATA_QUALITY
    return label, sufficient


def candidates_from_prediction(
    prediction: Any,
    *,
    prediction_age_s: float | None = None,
    odds_age_s: float | None = None,
    seconds_to_kickoff: float | None = None,
) -> list[SelectionCandidate]:
    """Trei candidaturi (una per rezultat 1X2) sau lista goala daca predictia nu
    are cotele complete. Piata cu cote incomplete nu produce candidaturi
    partiale — probabilitatile "fair" ale celorlalte rezultate ar fi calculate
    pe un de-vig incomplet, deci gresite."""
    if prediction is None:
        return []

    fixture_id = str(getattr(prediction, "fixture_id", "") or "")
    home_team = str(getattr(prediction, "home_team", "") or "")
    away_team = str(getattr(prediction, "away_team", "") or "")
    match_label = f"{home_team} - {away_team}".strip(" -")
    league = str(getattr(prediction, "league", "") or "")
    kickoff_utc = str(getattr(prediction, "kickoff_utc", "") or "")
    bookmaker = getattr(prediction, "bookmaker_name", None)

    quality_label, quality_sufficient = _data_quality_pair(prediction)
    home_matches = _profile_matches_analysed(getattr(prediction, "home_profile", None))
    away_matches = _profile_matches_analysed(getattr(prediction, "away_profile", None))
    if home_matches is None or away_matches is None:
        matches_analysed = None
    else:
        matches_analysed = min(home_matches, away_matches)

    # (cod, eticheta, probabilitate model, cota, probabilitate "fair" in procente)
    outcomes = (
        ("1", "Home Win", getattr(prediction, "prob_home_win", None),
         getattr(prediction, "bk_home_odds", None), getattr(prediction, "fair_home_pct", None)),
        ("X", "Draw", getattr(prediction, "prob_draw", None),
         getattr(prediction, "bk_draw_odds", None), getattr(prediction, "fair_draw_pct", None)),
        ("2", "Away Win", getattr(prediction, "prob_away_win", None),
         getattr(prediction, "bk_away_odds", None), getattr(prediction, "fair_away_pct", None)),
    )

    rows: list[SelectionCandidate] = []
    for code, label, model_p, odds, fair_pct in outcomes:
        p = _as_float(model_p)
        o = _as_float(odds)
        f = _as_float(fair_pct)
        if p is None or o is None or f is None:
            return []
        rows.append(SelectionCandidate(
            fixture_id=fixture_id,
            match_label=match_label,
            league=league,
            kickoff_utc=kickoff_utc,
            market=_MARKET_1X2,
            selection_code=code,
            selection_label=label,
            model_p=p,
            fair_p=f / 100.0,
            bk_odds=o,
            bookmaker=str(bookmaker) if bookmaker else None,
            data_quality=quality_label,
            data_quality_is_sufficient=quality_sufficient,
            matches_analysed=matches_analysed,
            prediction_age_s=prediction_age_s,
            odds_age_s=odds_age_s,
            seconds_to_kickoff=seconds_to_kickoff,
        ))
    return rows


def candidates_from_predictions(
    predictions: Sequence[Any],
    *,
    prediction_age_s: float | None = None,
    odds_age_s: float | None = None,
) -> list[SelectionCandidate]:
    """Varianta pentru o lista de predictii; `None` in lista e ignorat (meci
    care a esuat la analiza)."""
    out: list[SelectionCandidate] = []
    for prediction in predictions:
        out.extend(candidates_from_prediction(
            prediction,
            prediction_age_s=prediction_age_s,
            odds_age_s=odds_age_s,
        ))
    return out
