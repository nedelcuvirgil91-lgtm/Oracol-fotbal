"""
================================================================================
FOOTBALL ORACLE — Value Betting Dashboard: agregare (v0.2)
================================================================================
Module: value_dashboard.py

Două căi, aceeași semnătură și același tip de ieșire:

**Calea moștenită (implicită).** Agregă value bets DEJA calculate
(`MatchPrediction.value_bets` + `special_value_bets`, produse de
`oracle_engine.evaluate_match()`, deja filtrate peste `value_bet_threshold_pct`)
și le sortează descrescător după edge relativ. Nu recalculează nimic.

**Calea de radar (ADR-071 §17, gatată de `value_selector_v1_enabled`).** Trece
aceleași predicții prin `value_selector`, care aplică porțile explicite și
întoarce cel mult 5 MECIURI pe zi, unul singur per meci. Nu recalculează
nicio probabilitate și nu atinge nimic din ce a produs Oracle — filtrează
strict după ce motorul și-a terminat treaba.

Invariant de produs (ADR-071 §17): Top Value Bets e un RADAR, nu un sistem de
pariere. Nu produce niciodată mărimea mizei, Kelly, sumă în euro, bancă sau
execuție. `kelly_stake` e `None` pe calea de radar — DELIBERAT, nu din lipsă
de date.

Singura impuritate e citirea flagului, la intrarea în `collect_value_bets()`.
Ambele căi de calcul (`_collect_legacy`, `collect_radar_bets`) rămân funcții
pure, cu politica injectată — deci testabile fără Supabase.

Sursa predicțiilor (cache de sesiune vs. calcul nou) rămâne responsabilitatea
apelantului (`app.py`), neatins de această schimbare.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    """Punctul de intrare al ecranului. Cu flagul stins — comportamentul de
    dinaintea ADR-071, bit cu bit (invariant verificat prin test)."""
    if _radar_activ():
        try:
            from value_selector_config import build_policy
            return collect_radar_bets(predictions, build_policy())
        except Exception as exc:
            # Un radar care crapă nu are voie să golească ecranul: căderea pe
            # calea moștenită păstrează utilizatorul cu lista de dinainte, nu
            # cu o pagină goală și un mesaj de eroare.
            logger.warning("[ValueDashboard] radarul a esuat, revin la lista "
                           "clasica: %s", exc)
    return _collect_legacy(predictions)


def _radar_activ() -> bool:
    """Singurul punct de I/O din modul. Orice eroare de citire înseamnă
    „stins" — un flag necitit nu activează niciodată nimic (North Star #3)."""
    try:
        from value_selector_config import is_enabled
        return is_enabled()
    except Exception as exc:
        logger.warning("[ValueDashboard] flagul radarului nu a putut fi citit "
                       "(raman pe lista clasica): %s", exc)
        return False


# ── Calea moștenită ──────────────────────────────────────────────────────────

def _collect_legacy(predictions: list) -> list[ValueBetRow]:
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


# ── Calea de radar (ADR-071 §17) ─────────────────────────────────────────────

def collect_radar_bets(predictions: list, policy) -> list[ValueBetRow]:
    """Cel mult `policy.top_n_matches` meciuri pe zi, unul per meci. Funcție
    pură: politica e injectată, nu citită din configurație.

    Ordinea e cea produsă de selector (`rank_in_day`), NU sortarea după edge
    relativ — exact mecanismul care scotea outsiderii deasupra (ADR-071 §2).
    Edge-ul relativ rămâne afișat, ca diagnostic.

    Piețele speciale (Over/Under, BTTS) NU apar aici: sunt în afara scopului
    V1 (ADR-071 §12), iar câteva rânduri de piețe speciale ar dilua o listă de
    cinci meciuri. Rămân o fază separată, nu o omisiune."""
    from value_selector import select_by_day
    from value_selector_adapter import candidates_from_prediction

    dupa_fixture = {}
    candidaturi = []
    for pred in predictions:
        if pred is None:
            continue
        ale_meciului = candidates_from_prediction(pred)
        if not ale_meciului:
            continue  # piață incompletă — nicio candidatură parțială
        dupa_fixture[str(getattr(pred, "fixture_id", ""))] = pred
        candidaturi.extend(ale_meciului)

    rows: list[ValueBetRow] = []
    for _zi, rezultat in select_by_day(candidaturi, policy).items():
        for ales in rezultat.top:
            candidat = ales.candidate
            pred = dupa_fixture.get(candidat.fixture_id)
            if pred is None:
                continue
            rows.append(ValueBetRow(
                fixture_id=candidat.fixture_id,
                home_team=getattr(pred, "home_team", ""),
                away_team=getattr(pred, "away_team", ""),
                league=candidat.league,
                kickoff_utc=candidat.kickoff_utc,
                market=candidat.market,
                selection=candidat.selection_label,
                edge_pct=round(ales.metrics.e_rel_pct, 2),
                model_prob_pct=round(candidat.model_p * 100.0, 2),
                bk_odds=candidat.bk_odds,
                # Diferența absolută față de piață, în puncte procentuale — mărimea
                # pe care ADR-071 §2 o pune în locul edge-ului relativ. Nu e o notă
                # de valoare, e cât de mult se abate modelul de la cotă.
                rating=f"{ales.metrics.e_abs_pp:+.1f} pp vs piață",
                # Invariantul de radar: niciodată mărime de miză (ADR-071 §17).
                kelly_stake=None,
            ))
    return rows
