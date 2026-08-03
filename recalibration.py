"""
================================================================================
FOOTBALL ORACLE — recalibration.py (v1.1)
================================================================================
Modul: recalibration.py

Contine LOGICA PURA de auto-invatare (recalibrare ponderi) folosita de
Football Oracle. Nu are nicio dependinta de Supabase, API extern, fisiere
pe disc, sau stare globala — primeste starea curenta de ponderi si
rezultatul unui meci, si returneaza starea NOUA de ponderi + un rezultat
structurat. Nu muta niciodata `weights` in loc (lucreaza pe o copie),
tocmai ca sa poata fi apelata in bucla, meci cu meci, fara efecte
secundare ascunse intre iteratii.

CHANGES v1.1:
  - [FIX] league_weights[league] este acum creat si sample_count este acum
    incrementat la FIECARE rezultat confirmat, indiferent de marimea erorii
    de predictie. Anterior, un meci cu eroare mica (combined < 0.30) se
    intorcea devreme fara sa creeze intrarea ligii si fara sa incrementeze
    sample_count — o liga cu predictii bune parea "fara date de calibrare"
    in loc de "sample_count mare, ajustari mici". Ajustarea efectiva a
    ponderilor ramane in continuare proportionala cu eroarea (un meci cu
    eroare mica inca nu forteaza o schimbare de ponderi) — s-a schimbat
    doar CONTORIZAREA, nu logica de ajustare.
  - [ADAUGAT] parametrul `recency_weight` (default 1.0, neutru — pastreaza
    comportamentul anterior pentru orice apelant existent care nu-l seteaza
    explicit). Scaleaza learning_rate-ul efectiv al pasului curent, pentru
    a permite ca meciurile recente sa influenteze mai mult ponderile decat
    cele vechi. Vezi compute_recency_weight() mai jos pentru formula.
  - [ADAUGAT] compute_recency_weight(): decadere exponentiala cu half-life
    configurabil — inlocuieste ideea de praguri fixe (0-3 luni / 3-12 luni
    / ...) cu o curba continua, fara discontinuitati la granitele intre
    praguri. A se vedea docstring-ul functiei pentru justificare.

Aceasta este SINGURA implementare a algoritmului de invatare din tot
proiectul:
  - oracle_engine.FootballOracleEngine.update_weights_from_result() o
    foloseste ca wrapper subtire pentru fluxul live — apelat AUTOMAT de
    sync/sync_results.py dupa ce rezultatul real e detectat, NU de un
    utilizator care confirma manual un pariu din Portfolio (Portfolio a
    fost decuplat complet de League Learning in v1.1 — ramane doar jurnal
    de pariuri).
  - sync/bootstrap_league_learning.py o foloseste identic, intr-un replay
    cronologic peste intreg istoricul deja completat de backfill, ca sa
    produca acelasi model_weights la care s-ar fi ajuns daca sistemul ar
    fi rulat live inca din primul meci din dataset (cu recency_weight < 1.0
    pentru meciurile vechi, ca sa nu domine ponderile finale).

PROVENIENTA: extras din oracle_engine.py v3.0, metoda
update_weights_from_result() — blocul de calcul al erorii si ajustarea
ponderilor. Extragere 1:1: aceleasi praguri (0.30, 0.50), aceiasi
coeficienti de scalare (0.6, 0.5, 0.3, 0.2, 0.15, 0.4, 0.25), aceleasi
limite (lo/hi) pe fiecare pondere. NU s-a schimbat nicio valoare (v1.0);
v1.1 schimba doar contorizarea si adauga recency — vezi CHANGES v1.1.

NU face parte din acest modul (ramane responsabilitatea apelantului):
  - incarcarea predictiei salvate (din match_history in Supabase, pentru
    fluxul automat, sau din predictions/*.json pentru compatibilitate)
  - scrierea rezultatului real in Supabase match_history
  - persistarea ponderilor (save_weights) sau a jurnalului de recalibrare
    (recalibration_log / CSV) — acestea sunt efecte de I/O, responsabilitatea
    apelantului (fluxul live SAU bootstrap-ul), nu a algoritmului in sine.
================================================================================
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

DEFAULT_LEAGUE_WEIGHTS_TEMPLATE: dict[str, float | int] = {
    "form_weight": 0.60, "base_weight": 0.40, "goals_weight": 0.45,
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
    # [FIX v1.1] Nu mai e None pentru status == "stable" — vezi CHANGES v1.1.
    # Ramane None DOAR daca meciul nu a fost procesat deloc (nu se intampla
    # in fluxul normal — recalibrate_weights() produce mereu un log_row).
    log_row: dict | None = None


def compute_recency_weight(
    match_date: str | date,
    half_life_days: float,
    reference_date: str | date | None = None,
) -> float:
    """
    Decadere exponentiala: weight = 0.5 ** (zile_trecute / half_life_days).

    De ce exponentiala si nu praguri fixe (0-3 luni=1.0, 3-12 luni=0.8, ...):
      - Continuitate: pragurile fixe creeaza un salt artificial la fiecare
        granita (un meci la 11 luni si 29 de zile ar pondera 0.8, unul la
        12 luni si 1 zi ar pondera 0.6 — o diferenta de 25% pentru o
        singura zi calendaristica). Exponentiala nu are asemenea discontinuitati.
      - Un singur parametru de calibrat (half_life_days), configurabil din
        config.json, in loc de N praguri arbitrare.
      - Aceeasi idee matematica sta la baza sistemelor ELO (inclusiv cel de
        pe eloratings.net, deja folosit in proiect) si a modelelor Dixon-Coles
        de forta a echipelor, standard in analiza sportiva profesionista.

    Cu half_life_days=365 (implicit): azi→1.0, ~3 luni→~0.85, 1 an→0.50,
    2 ani→~0.25, 5 ani→~0.03 — istoricul vechi influenteaza tot mai putin,
    dar niciodata printr-un salt brusc.

    match_date / reference_date accepta atat obiecte `date` cat si string-uri
    ISO "YYYY-MM-DD" (sau cu timp, se ia doar partea de data). Daca
    match_date lipseste sau e in viitor fata de reference_date, se returneaza
    1.0 (niciun penalizare — cazul normal pentru un meci recent-terminat).
    """
    def _to_date(v: str | date | None) -> date | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v).strip()[:10]
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    md = _to_date(match_date)
    if md is None or half_life_days <= 0:
        return 1.0

    ref = _to_date(reference_date) or date.today()
    days = (ref - md).days
    if days <= 0:
        return 1.0

    return 0.5 ** (days / half_life_days)


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
    recency_weight: float = 1.0,
) -> tuple[dict[str, Any], RecalibrationResult]:
    """
    Aplica un singur pas de recalibrare peste `weights` si returneaza
    (weights_nou, rezultat) — NU modifica `weights` primit ca parametru.

    Parametrii `learning_rate` / `max_delta` corespund exact la
    config["recalibration_learning_rate"] / config["recalibration_max_delta"]
    din oracle_engine.py — apelantul le extrage din config si le paseaza
    aici explicit, ca acest modul sa ramana independent de structura
    completa a config-ului.

    `recency_weight` (implicit 1.0 — neutru, comportament identic cu v1.0
    pentru apelantii care nu-l seteaza) scaleaza learning_rate-ul efectiv
    al acestui pas. Apelantul calculeaza aceasta valoare o singura data,
    de obicei via compute_recency_weight(kickoff_date, half_life_days) —
    modulul acesta nu decide singur cat de "vechi" e un meci, doar aplica
    ponderea primita.

    Poate fi apelata:
      - o singura data, pentru un update automat live (wrapper in
        oracle_engine.py, declansat de sync/sync_results.py dupa ce
        rezultatul real e detectat — fara nicio interventie manuala)
      - de mii de ori la rand, intr-o bucla cronologica de bootstrap,
        transmitand de fiecare data `weights` = rezultatul pasului anterior
        si `recency_weight` < 1.0 pentru meciurile vechi.
    """
    w = copy.deepcopy(weights)

    home_err = actual_home_goals - pred_home_xg
    away_err = actual_away_goals - pred_away_xg
    combined = (abs(home_err) + abs(away_err)) / 2.0
    avg_err  = (home_err + away_err) / 2.0

    # [FIX v1.1] effective_lr include recency_weight din primul moment —
    # afecteaza atat pragul de ajustare (mai jos) cat si magnitudinea ei.
    effective_lr = learning_rate * max(0.0, recency_weight)

    # [FIX v1.1] Intrarea ligii se creeaza si sample_count se incrementeaza
    # NECONDITIONAT — indiferent daca eroarea justifica sau nu o ajustare
    # de ponderi. Vezi CHANGES v1.1 din header-ul modulului.
    lw_all = w.setdefault("league_weights", {})
    if league not in lw_all:
        lw_all[league] = {
            "form_weight":       float(w.get("form_weight",       0.60)),
            "base_weight":        float(w.get("base_weight",        0.40)),
            "goals_weight":      float(w.get("goals_weight",      0.45)),
            "shots_ot_weight":   float(w.get("shots_ot_weight",   0.30)),
            "possession_weight": float(w.get("possession_weight", 0.25)),
            "home_advantage":    float(w.get("home_advantage",    1.07)),
            "away_penalty":      float(w.get("away_penalty",      0.95)),
            "sample_count":      0,
        }
    lw = lw_all[league]
    sc = int(lw.get("sample_count", 0))

    if combined < 0.30:
        lw_all[league]["sample_count"] = sc + 1
        w["league_weights"] = lw_all
        log_row = {
            "fixture_id":     fixture_id,
            "league":         league,
            "sample_count":   sc + 1,
            "home":           f"{home_team} ({pred_home_xg:.2f} xG)",
            "away":           f"{away_team} ({pred_away_xg:.2f} xG)",
            "actual":         f"{actual_home_goals}-{actual_away_goals}",
            "combined_error": round(combined, 3),
            "new_form_w":     float(lw.get("form_weight", 0.60)),
            "new_dna_w":      float(lw.get("base_weight", 0.40)),
            "home_advantage": float(lw.get("home_advantage", 1.07)),
            "reason":         "Model accurate — sample inregistrat, fara ajustare de ponderi.",
        }
        return w, RecalibrationResult(
            status="stable", league=league, combined_error=round(combined, 4),
            home_error=round(home_err, 4), away_error=round(away_err, 4),
            pred_home_xg=round(pred_home_xg, 3), pred_away_xg=round(pred_away_xg, 3),
            actual_home_goals=actual_home_goals, actual_away_goals=actual_away_goals,
            reason="Model accurate.", adjustments={}, log_row=log_row,
        )

    adjustments: dict = {}
    reasons: list = []

    def _shift(name, cur, delta, lo=0.05, hi=0.95):
        delta   = max(-max_delta, min(max_delta, delta))
        new_val = max(lo, min(hi, cur + delta))
        adjustments[name] = {"old": round(cur, 4), "delta": round(delta, 4), "new": round(new_val, 4)}
        return new_val

    lr_league = min(effective_lr * max(1.0, 3.0 / (sc + 1)), effective_lr * 3)
    scale_l   = min(combined / 3.0, 1.0) * lr_league

    fw  = float(lw.get("form_weight",       0.60))
    dw  = float(lw.get("base_weight",        0.40))
    gw  = float(lw.get("goals_weight",      0.45))
    sow = float(lw.get("shots_ot_weight",   0.30))
    pw  = float(lw.get("possession_weight", 0.25))
    ha  = float(lw.get("home_advantage",    1.07))
    ap  = float(lw.get("away_penalty",      0.95))

    if combined >= 0.50:
        fw = _shift("form_weight", fw, -scale_l * 0.6, lo=0.10, hi=0.90)
        dw = _shift("base_weight",  dw, +scale_l * 0.6, lo=0.10, hi=0.90)
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
        "form_weight": fw, "base_weight": dw, "goals_weight": gw,
        "shots_ot_weight": sow, "possession_weight": pw,
        "home_advantage": ha, "away_penalty": ap, "sample_count": sc + 1,
    })

    gfw  = float(w.get("form_weight",       0.60))
    gdw  = float(w.get("base_weight",        0.40))
    ggw  = float(w.get("goals_weight",      0.45))
    gsow = float(w.get("shots_ot_weight",   0.30))
    gpw  = float(w.get("possession_weight", 0.25))

    w.update({
        "form_weight":       round(max(0.10, min(0.90, gfw  + (fw  - gfw)  * 0.25)), 4),
        "base_weight":        round(max(0.10, min(0.90, gdw  + (dw  - gdw)  * 0.25)), 4),
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
