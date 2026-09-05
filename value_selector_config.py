"""
================================================================================
FOOTBALL ORACLE — Value Selector Config (ADR-071)
================================================================================
Module: value_selector_config.py

Citeste flagurile selectorului din `model_config` si construieste
`SelectorPolicy`. Tipar identic `flashscore_kickoff_correction_config.py`.

TOATE flagurile sunt implicit inerte (North Star #3): cu configuratia
implicita, `build_policy()` intoarce exact `LEGACY_POLICY`, adica reproduce
comportamentul de azi al listei Top Value Bets. Niciuna dintre cheile de mai
jos nu exista inca in `model_config` — absenta lor e comportamentul asteptat in
F1, nu o omisiune.

Profilele din `F2_PROFILES` sunt candidaturi EXPERIMENTALE pentru rularea
shadow din F2, nu politici aprobate. Pragurile lor provin din analiza
retrospectiva si sunt explicit NEvalidate — se compara prospectiv, si niciuna
nu e declarata castigatoare aici (ADR-071 §15).
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

from value_selector import LEGACY_POLICY, SelectorPolicy

_DEFAULT_CONFIG: dict[str, object] = {
    "value_selector_v1_enabled": False,
    "value_selector_shadow_logging_enabled": False,
    "value_selector_policy_profile": "legacy",
    "value_selector_ranker_id": "legacy_relative_edge",
    "value_selector_shrinkage_w": 1.0,
    "value_selector_require_rank_one": False,
    "value_selector_market_plausibility_floor": None,
    "value_selector_probability_floor": None,
    "value_selector_min_abs_edge_pp": None,
    "value_selector_odds_ceiling": None,
    "value_selector_require_sufficient_data_quality": False,
    "value_selector_min_matches_analysed": None,
    "value_selector_max_odds_age_s": None,
    "value_selector_max_prediction_age_s": None,
    "value_selector_require_positive_value": False,
    "value_selector_legacy_relative_edge_floor_pct": 5.0,
    "value_selector_top_n_matches": None,
    "value_selector_one_selection_per_match": False,
}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("value_selector_v1_enabled", False))


def is_shadow_logging_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("value_selector_shadow_logging_enabled", False))


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_policy(config: dict | None = None) -> SelectorPolicy:
    """Construieste politica din `model_config`. Cu valorile implicite intoarce
    `LEGACY_POLICY` — invariant verificat de teste."""
    cfg = config if config is not None else sb.load_config(_DEFAULT_CONFIG)
    # `w = 0.0` e o valoare legitima (control market-only), deci nu se poate
    # folosi `or` pentru default — ar transforma 0.0 in 1.0.
    w = _opt_float(cfg.get("value_selector_shrinkage_w"))
    return SelectorPolicy(
        profile=str(cfg.get("value_selector_policy_profile", "legacy") or "legacy"),
        ranker_id=str(cfg.get("value_selector_ranker_id", "legacy_relative_edge")
                      or "legacy_relative_edge"),
        shrinkage_w=1.0 if w is None else w,
        require_rank_one=bool(cfg.get("value_selector_require_rank_one", False)),
        market_plausibility_floor=_opt_float(cfg.get("value_selector_market_plausibility_floor")),
        probability_floor=_opt_float(cfg.get("value_selector_probability_floor")),
        min_abs_edge_pp=_opt_float(cfg.get("value_selector_min_abs_edge_pp")),
        odds_ceiling=_opt_float(cfg.get("value_selector_odds_ceiling")),
        require_sufficient_data_quality=bool(
            cfg.get("value_selector_require_sufficient_data_quality", False)),
        min_matches_analysed=_opt_int(cfg.get("value_selector_min_matches_analysed")),
        max_odds_age_s=_opt_float(cfg.get("value_selector_max_odds_age_s")),
        max_prediction_age_s=_opt_float(cfg.get("value_selector_max_prediction_age_s")),
        require_positive_value=bool(cfg.get("value_selector_require_positive_value", False)),
        legacy_relative_edge_floor_pct=_opt_float(
            cfg.get("value_selector_legacy_relative_edge_floor_pct", 5.0)),
        top_n_matches=_opt_int(cfg.get("value_selector_top_n_matches")),
        one_selection_per_match=bool(cfg.get("value_selector_one_selection_per_match", False)),
    )


# ── Profile experimentale pentru F2 ──────────────────────────────────────────
# NU sunt politici aprobate. Pragurile sunt de pornire, alese ca sa acopere
# intervalul cerut la testare, si raman inghetate pe durata F3 prin `policy_id`.

def _radar_profile(name: str, *, w: float, market_floor: float | None,
                   ranker_id: str = "probability_first") -> SelectorPolicy:
    return SelectorPolicy(
        profile=name,
        ranker_id=ranker_id,
        shrinkage_w=w,
        require_rank_one=True,
        market_plausibility_floor=market_floor,
        min_abs_edge_pp=3.0,
        require_sufficient_data_quality=True,
        require_positive_value=True,
        legacy_relative_edge_floor_pct=None,
        top_n_matches=5,
        one_selection_per_match=True,
    )


F2_PROFILES: dict[str, SelectorPolicy] = {
    # Baseline obligatoriu — exact selectorul de azi.
    "legacy": LEGACY_POLICY,

    # Control market-only. Ordonare dupa probabilitatea pietei, FARA poarta de
    # valoare pozitiva: la w=0, `ev_shr` e negativ pentru orice selectie, deci
    # o poarta pe EV ar produce mereu multimea vida (vezi
    # `value_selector.shrink_probability`). Nu e un defect, e algebra.
    "market_only": SelectorPolicy(
        profile="market_only", ranker_id="market_controlled", shrinkage_w=0.0,
        require_rank_one=True, market_plausibility_floor=0.25,
        require_sufficient_data_quality=True, require_positive_value=False,
        legacy_relative_edge_floor_pct=None, top_n_matches=5,
        one_selection_per_match=True,
    ),

    # Familia de shrinkage ceruta explicit (w = 1.00 / 0.75 / 0.50 / 0.25).
    "shrunk_100": _radar_profile("shrunk_100", w=1.00, market_floor=0.25),
    "shrunk_075": _radar_profile("shrunk_075", w=0.75, market_floor=0.25),
    "shrunk_050": _radar_profile("shrunk_050", w=0.50, market_floor=0.25),
    "shrunk_025": _radar_profile("shrunk_025", w=0.25, market_floor=0.25),

    # Familia de praguri de plauzibilitate a pietei, la w fix.
    "market_floor_020": _radar_profile("market_floor_020", w=0.50, market_floor=0.20),
    "market_floor_025": _radar_profile("market_floor_025", w=0.50, market_floor=0.25),
    "market_floor_030": _radar_profile("market_floor_030", w=0.50, market_floor=0.30),
    "market_floor_035": _radar_profile("market_floor_035", w=0.50, market_floor=0.35),
    "market_floor_040": _radar_profile("market_floor_040", w=0.50, market_floor=0.40),

    # Familia de rankere, la politica de porti identica.
    "ranker_prob_value": _radar_profile("ranker_prob_value", w=0.50, market_floor=0.25,
                                        ranker_id="probability_plus_value"),
    "ranker_shrunk_ev": _radar_profile("ranker_shrunk_ev", w=0.50, market_floor=0.25,
                                       ranker_id="shrunk_ev"),
}
