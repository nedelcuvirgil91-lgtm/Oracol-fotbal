"""
================================================================================
FOOTBALL ORACLE — recalibration.py
================================================================================
Modul: recalibration.py

Contine LOGICA PURA de auto-invatare (recalibrare ponderi) folosita de
Football Oracle. Nu are nicio dependinta de Supabase, API extern, fisiere
pe disc, sau stare globala — primeste starea curenta de ponderi si
rezultatul unui meci, si returneaza starea NOUA de ponderi + un rezultat
structurat. Nu muta niciodata `weights` in loc (lucreaza pe o copie),
tocmai ca sa poata fi apelata in bucla, meci cu meci, fara efecte
secundare ascunse intre iteratii.

Aceasta este SINGURA implementare a algoritmului de invatare din tot
proiectul:
  - oracle_engine.FootballOracleEngine.update_weights_from_result() o
    foloseste ca wrapper subtire pentru fluxul live (dupa ce utilizatorul
    confirma manual scorul real al unui meci analizat anterior).
  - sync/bootstrap_league_learning.py (etapa urmatoare, neimplementata
    inca) o va folosi identic, intr-un replay cronologic peste intreg
    istoricul Kaggle deja completat de backfill, ca sa produca acelasi
    model_weights la care s-ar fi ajuns daca sistemul ar fi rulat live
    inca din primul meci din dataset.

PROVENIENTA: extras din oracle_engine.py v3.0, metoda
update_weights_from_result() — blocul de calcul al erorii si ajustarea
ponderilor. Extragere 1:1: aceleasi praguri (0.30, 0.50), aceiasi
coeficienti de scalare (0.6, 0.5, 0.3, 0.2, 0.15, 0.4, 0.25), aceleasi
limite (lo/hi) pe fiecare pondere. NU s-a schimbat nicio valoare.

NU face parte din acest modul (ramane in oracle_engine.py, ca inainte):
  - incarcarea predictiei cache-uite (_load_prediction / predictions/*.json)
  - scrierea rezultatului real in Supabase match_history
  - persistarea ponderilor (save_weights) sau a jurnalului de recalibrare
    (recalibration_log / CSV) — acestea sunt efecte de I/O, responsabilitatea
    apelantului (fluxul live SAU bootstrap-ul), nu a algoritmului in sine.
================================================================================
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

DEFAULT_LEAGUE_WEIGHTS_TEMPLATE: dict[str, float | int] = {
    "form_weight": 0.60, "dna_weight": 0.40, "goals_weight": 0.45,
    "shots_ot_weight": 0.30, "possession_weight": 0.25,
    "home_advantage": 1.07, "away_penalty": 0.95, "sample_count": 0,
}


@dataclass
class RecalibrationResult:
    """Rezultatul structurat al unui singur pas de recalibrare (un meci)."""
    status: str                       # "stable" | "recalibrated"
    league: str
    combined_error: float
    home_error: float = 0.0
    away_error: float = 0.0
    pred_home_xg: float = 0.0
    pred_away_xg: float = 0.0
    actual_home_goals: int = 0
    actual_away_goals: int = 0
    adjustments: dict = field(default_factory=dict)
    reason: str = ""
    # None cand status == "stable" (nu s-a scris nimic in jurnal atunci).
    log_row: dict | None = None


def recalibrate_weights(
    weights: dict[str, Any],
    *,
    league: str,
    pred_home_xg: float,
    pred_away_xg: float,
    actual_home_goals: int,
    actual_away_goals: int,
    fixture_id: str = "",
    home_team: str = "",
    away_team: str = "",
    learning_rate: float = 0.05,
    max_delta: float = 0.15,
) -> tuple[dict[str, Any], RecalibrationResult]:
    """
    Aplica un singur pas de recalibrare peste `weights` si returneaza
    (weights_nou, rezultat) — NU modifica `weights` primit ca parametru.

    Parametrii `learning_rate` / `max_delta` corespund exact la
    config["recalibration_learning_rate"] / config["recalibration_max_delta"]
    din oracle_engine.py — apelantul le extrage din config si le paseaza
    aici explicit, ca acest modul sa ramana independent de structura
    completa a config-ului.

    Poate fi apelata:
      - o singura data, pentru un update live (wrapper in oracle_engine.py)
      - de mii de ori la rand, intr-o bucla cronologica de bootstrap,
        transmitand de fiecare data `weights` = rezultatul pasului anterior.
    """
    w = copy.deepcopy(weights)

    home_err = actual_home_goals - pred_home_xg
    away_err = actual_away_goals - pred_away_xg
    combined = (abs(home_err) + abs(away_err)) / 2.0
    avg_err  = (home_err + away_err) / 2.0

    if combined < 0.30:
        return w, RecalibrationResult(
            status="stable", league=league, combined_error=round(combined, 4),
            home_error=round(home_err, 4), away_error=round(away_err, 4),
            pred_home_xg=round(pred_home_xg, 3), pred_away_xg=round(pred_away_xg, 3),
            actual_home_goals=actual_home_goals, actual_away_goals=actual_away_goals,
            reason="Model accurate.", adjustments={},
        )

    adjustments: dict = {}
    reasons: list = []

    def _shift(name, cur, delta, lo=0.05, hi=0.95):
        delta   = max(-max_delta, min(max_delta, delta))
        new_val = max(lo, min(hi, cur + delta))
        adjustments[name] = {"old": round(cur, 4), "delta": round(delta, 4), "new": round(new_val, 4)}
        return new_val

    lw_all = w.setdefault("league_weights", {})
    if league not in lw_all:
        lw_all[league] = {
            "form_weight":       float(w.get("form_weight",       0.60)),
            "dna_weight":        float(w.get("dna_weight",        0.40)),
            "goals_weight":      float(w.get("goals_weight",      0.45)),
            "shots_ot_weight":   float(w.get("shots_ot_weight",   0.30)),
            "possession_weight": float(w.get("possession_weight", 0.25)),
            "home_advantage":    float(w.get("home_advantage",    1.07)),
            "away_penalty":      float(w.get("away_penalty",      0.95)),
            "sample_count":      0,
        }

    lw        = lw_all[league]
    sc        = int(lw.get("sample_count", 0))
    lr_league = min(learning_rate * max(1.0, 3.0 / (sc + 1)), learning_rate * 3)
    scale_l   = min(combined / 3.0, 1.0) * lr_league

    fw  = float(lw.get("form_weight",       0.60))
    dw  = float(lw.get("dna_weight",        0.40))
    gw  = float(lw.get("goals_weight",      0.45))
    sow = float(lw.get("shots_ot_weight",   0.30))
    pw  = float(lw.get("possession_weight", 0.25))
    ha  = float(lw.get("home_advantage",    1.07))
    ap  = float(lw.get("away_penalty",      0.95))

    if combined >= 0.50:
        fw = _shift("form_weight", fw, -scale_l * 0.6, lo=0.10, hi=0.90)
        dw = _shift("dna_weight",  dw, +scale_l * 0.6, lo=0.10, hi=0.90)
        reasons.append(f"[{league}] Large error ({combined:.2f}) → DNA shift.")

    if avg_err > 0.50:
        gw  = _shift("goals_weight",    gw,  +scale_l * 0.5, lo=0.10, hi=0.80)
        sow = _shift("shots_ot_weight", sow, +scale_l * 0.3, lo=0.05, hi=0.60)
        if home_err > 0.5:
            ha = _shift("home_advantage", ha, +scale_l * 0.2, lo=1.00, hi=1.20)
        reasons.append(f"[{league}] Under-estimated.")
    elif avg_err < -0.50:
        gw = _shift("goals_weight",      gw, -scale_l * 0.4, lo=0.10, hi=0.80)
        pw = _shift("possession_weight", pw, +scale_l * 0.3, lo=0.05, hi=0.50)
        if home_err < -0.5:
            ha = _shift("home_advantage", ha, -scale_l * 0.15, lo=1.00, hi=1.20)
        reasons.append(f"[{league}] Over-estimated.")

    t_comp = gw + sow + pw
    if t_comp > 0:
        gw  = round(gw  / t_comp, 4)
        sow = round(sow / t_comp, 4)
        pw  = round(pw  / t_comp, 4)
    t_fd = fw + dw
    if t_fd > 0:
        fw = round(fw / t_fd, 4)
        dw = round(dw / t_fd, 4)

    lw_all[league].update({
        "form_weight": fw, "dna_weight": dw, "goals_weight": gw,
        "shots_ot_weight": sow, "possession_weight": pw,
        "home_advantage": ha, "away_penalty": ap, "sample_count": sc + 1,
    })

    gfw  = float(w.get("form_weight",       0.60))
    gdw  = float(w.get("dna_weight",        0.40))
    ggw  = float(w.get("goals_weight",      0.45))
    gsow = float(w.get("shots_ot_weight",   0.30))
    gpw  = float(w.get("possession_weight", 0.25))

    w.update({
        "form_weight":       round(max(0.10, min(0.90, gfw  + (fw  - gfw)  * 0.25)), 4),
        "dna_weight":        round(max(0.10, min(0.90, gdw  + (dw  - gdw)  * 0.25)), 4),
        "goals_weight":      round(max(0.10, min(0.80, ggw  + (gw  - ggw)  * 0.25)), 4),
        "shots_ot_weight":   round(max(0.05, min(0.60, gsow + (sow - gsow) * 0.25)), 4),
        "possession_weight": round(max(0.05, min(0.50, gpw  + (pw  - gpw)  * 0.25)), 4),
        "league_weights":    lw_all,
    })

    reason = "  |  ".join(reasons) or "Minor adjustment."
    log_row = {
        "fixture_id":     fixture_id,
        "league":         league,
        "sample_count":   sc + 1,
        "home":           f"{home_team} ({pred_home_xg:.2f} xG)",
        "away":           f"{away_team} ({pred_away_xg:.2f} xG)",
        "actual":         f"{actual_home_goals}-{actual_away_goals}",
        "combined_error": round(combined, 3),
        "new_form_w":     fw,
        "new_dna_w":      dw,
        "home_advantage": ha,
        "reason":         reason,
    }

    return w, RecalibrationResult(
        status="recalibrated", league=league, combined_error=round(combined, 3),
        home_error=round(home_err, 3), away_error=round(away_err, 3),
        pred_home_xg=round(pred_home_xg, 3), pred_away_xg=round(pred_away_xg, 3),
        actual_home_goals=actual_home_goals, actual_away_goals=actual_away_goals,
        adjustments=adjustments, reason=reason, log_row=log_row,
    )
