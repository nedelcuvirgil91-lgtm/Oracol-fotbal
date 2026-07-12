"""
================================================================================
FOOTBALL ORACLE — Value Betting Dashboard: agregare (v0.1)
================================================================================
Module: value_dashboard.py

Agregă value bets DEJA calculate (MatchPrediction.value_bets +
MatchPrediction.special_value_bets, produse de oracle_engine.evaluate_match(),
deja filtrate peste `value_bet_threshold_pct` din config) peste o listă de
predicții — nu recalculează nimic, nu reimplementează logica de value
betting. Funcție pură, fără I/O, fără apeluri de rețea.

Sursa predicțiilor (cache de sesiune vs. calcul nou) e responsabilitatea
apelantului (app.py) — vezi acolo `_read_cached_prediction`/`_cache_prediction`.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValueBetRow:
    fixture_id:     str
    home_team:      str
    away_team:      str
    league:         str
    kickoff_utc:    str
    market:         str
    selection:      str
    edge_pct:       float
    model_prob_pct: float
    bk_odds:        float
    rating:         str
    kelly_stake:    float | None  # None — nu e calculat azi pentru piețe speciale


def collect_value_bets(predictions: list) -> list[ValueBetRow]:
    """Extrage toate value bets deja calculate din `predictions` (listă de
    MatchPrediction, `None` ignorat — meciuri care au eșuat la analiză),
    sortate descrescător după edge_pct. Nu aplică niciun prag nou — pragul
    (`value_bet_threshold_pct`) a fost deja aplicat de evaluate_match()."""
    rows: list[ValueBetRow] = []
    for pred in predictions:
        if pred is None:
            continue
        for vb in (pred.value_bets or []):
            selection = vb.get("selection", "?")
            rows.append(ValueBetRow(
                fixture_id=pred.fixture_id, home_team=pred.home_team, away_team=pred.away_team,
                league=pred.league, kickoff_utc=pred.kickoff_utc,
                market=vb.get("market", "1X2"), selection=selection,
                edge_pct=float(vb.get("edge_pct", 0.0)), model_prob_pct=float(vb.get("model_prob_pct", 0.0)),
                bk_odds=float(vb.get("bk_odds", 0.0)), rating=vb.get("rating", ""),
                kelly_stake=(pred.kelly_stakes or {}).get(selection),
            ))
        for vb in (pred.special_value_bets or []):
            rows.append(ValueBetRow(
                fixture_id=pred.fixture_id, home_team=pred.home_team, away_team=pred.away_team,
                league=pred.league, kickoff_utc=pred.kickoff_utc,
                market=vb.get("market", "?"), selection=vb.get("market", "?"),
                edge_pct=float(vb.get("edge_pct", 0.0)), model_prob_pct=float(vb.get("model_prob_pct", 0.0)),
                bk_odds=float(vb.get("bk_odds", 0.0)), rating=vb.get("rating", ""),
                kelly_stake=None,
            ))
    rows.sort(key=lambda r: r.edge_pct, reverse=True)
    return rows
