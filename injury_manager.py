"""
================================================================================
FOOTBALL ORACLE — Injury & Suspension Manager v1.0
================================================================================
Module  : injury_manager.py
Role    : Fetch, cache și calculează impactul accidentărilor și suspendărilor
          asupra xG-ului echipei.

Surse de date:
  1. SportAPI — Event lineups (substitute: false = titular)
  2. SportAPI — Player seasonstatistics (minute jucate = importanță)
  3. SportAPI — Player nearevents (disponibilitate meci următor)

Impact model:
  Fiecare jucător lipsă are un impact negativ pe xG bazat pe:
  - Minutele jucate în sezon (proxy pentru importanță în echipă)
  - Poziția (portar > fundaș > mijlocaș > atacant — în funcție de context)
  - Tipul absenței (accidentat vs suspendat — suspendatul e mai sigur absent)

  Formule:
    minutes_share = player_minutes / team_total_minutes
    position_weight = {GK: 1.5, DEF: 1.0, MID: 0.8, FWD: 1.2}
    raw_impact = minutes_share * position_weight
    xg_penalty = min(raw_impact * 0.25, 0.20)  # max 20% per jucător

  Exemplu real:
    Mbappé (FWD, 2800 min din 3060 echipă) → 91% min share → impact -18% xG
    Un fundaș rezervă (200 min) → 6.5% min share → impact -0.8% xG

================================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("FootballOracle.Injuries")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Ponderi per poziție pentru impact xG
POSITION_WEIGHTS: dict[str, float] = {
    "G":   1.5,   # Goalkeeper — critic pentru apărare
    "GK":  1.5,
    "D":   1.0,   # Defender
    "DEF": 1.0,
    "M":   0.8,   # Midfielder
    "MID": 0.8,
    "F":   1.2,   # Forward — impact pe atac
    "FWD": 1.2,
    "A":   1.2,   # Attacker (alias)
}

# Tipuri de absență și coeficienți de certitudine
ABSENCE_CERTAINTY: dict[str, float] = {
    "injured":    1.0,    # Confirmat absent
    "suspended":  1.0,    # Confirmat absent (cartonaș)
    "doubtful":   0.5,    # 50% șanse să lipsească
    "questionable": 0.4,
    "unknown":    0.3,
}

# Praguri pentru minute — determină "titularitate"
MIN_STARTER_MINUTES   = 900   # >900 min = jucător important
MIN_KEY_PLAYER_MINUTES= 1500  # >1500 min = jucător cheie

# Impact maxim pe xG per jucător (cap)
MAX_SINGLE_PLAYER_IMPACT = 0.18  # 18%
MAX_TOTAL_TEAM_IMPACT    = 0.30  # 30% total per echipă


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlayerAbsence:
    """Un jucător absent (accidentat sau suspendat)."""
    player_id:        int | str
    name:             str
    position:         str          # G, D, M, F
    minutes_played:   int          # minute jucate în sezon
    absence_type:     str          # injured / suspended / doubtful
    certainty:        float        # 0.0 - 1.0
    xg_impact:        float        # penalizare xG calculată (negativ)
    impact_label:     str          # "KEY PLAYER", "STARTER", "ROTATION"
    note:             str          # text pentru UI


@dataclass
class TeamInjuryReport:
    """Raportul complet de accidentări pentru o echipă."""
    team_name:          str
    team_id:            int | str | None
    absences:           list[PlayerAbsence] = field(default_factory=list)
    total_xg_penalty:   float = 0.0         # penalizare totală xG (0-0.30)
    data_quality:       str   = "unknown"   # "confirmed" / "estimated" / "unavailable"
    summary:            str   = ""
    has_key_absences:   bool  = False        # dacă lipsesc jucători cheie


# ─────────────────────────────────────────────────────────────────────────────
# INJURY MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class InjuryManager:
    """
    Calculează impactul accidentărilor și suspendărilor pe xG.
    """

    def __init__(self, api=None, cache=None) -> None:
        """
        Parameters
        ----------
        api   : FootballOracleAPI instance (pentru fetch date)
        cache : CacheManager instance (pentru cache disc)
        """
        self._api   = api
        self._cache = cache

    # ══════════════════════════════════════════════════════════════════════
    # IMPACT CALCULATOR
    # ══════════════════════════════════════════════════════════════════════

    def _calc_impact(
        self,
        minutes_played:    int,
        position:          str,
        absence_type:      str,
        team_total_minutes: int,
    ) -> float:
        """
        Calculează penalizarea xG pentru un jucător absent.

        Formula:
          minutes_share    = player_minutes / team_total_minutes
          position_weight  = POSITION_WEIGHTS[position]
          certainty        = ABSENCE_CERTAINTY[absence_type]
          raw_impact       = minutes_share * position_weight * certainty
          xg_penalty       = min(raw_impact * 0.35, MAX_SINGLE_PLAYER_IMPACT)

        Returns penalizarea ca float negativ (ex: -0.12)
        """
        if team_total_minutes <= 0:
            team_total_minutes = 3060  # 34 meciuri × 90 min

        pos_key = position.upper()[:3].rstrip("_")
        pos_w   = POSITION_WEIGHTS.get(pos_key, 0.8)
        cert    = ABSENCE_CERTAINTY.get(absence_type.lower(), 0.5)

        minutes_share = min(minutes_played / team_total_minutes, 1.0)
        raw_impact    = minutes_share * pos_w * cert
        penalty       = min(raw_impact * 0.35, MAX_SINGLE_PLAYER_IMPACT)

        return -round(penalty, 4)

    def _impact_label(self, minutes: int) -> str:
        """Etichetă pentru importanța jucătorului."""
        if minutes >= MIN_KEY_PLAYER_MINUTES:
            return "⚡ KEY PLAYER"
        if minutes >= MIN_STARTER_MINUTES:
            return "🔵 STARTER"
        return "⬜ ROTATION"

    # ══════════════════════════════════════════════════════════════════════
    # FETCH LINEUP + PARSE ABSENCES
    # ══════════════════════════════════════════════════════════════════════

    def get_lineup_absences(
        self,
        event_id:    int | str,
        team_id:     int | str,
        team_name:   str,
        league:      str,
    ) -> TeamInjuryReport:
        """
        Fetch lineupul unui meci și identifică jucătorii cheie ABSENȚI
        față de formația standard a echipei.

        Logică:
        1. Fetch lineup eveniment curent (titulari confirmați)
        2. Fetch ultimele 5 meciuri ale echipei (formație standard)
        3. Compară — jucătorii care apar de obicei dar lipsesc = absenți
        4. Fetch minute pentru fiecare absent (din seasonstatistics)
        5. Calculează impact xG
        """
        report = TeamInjuryReport(
            team_name = team_name,
            team_id   = team_id,
        )

        if not self._api or not event_id:
            report.data_quality = "unavailable"
            report.summary      = "⚠️ Date lineup indisponibile"
            return report

        # ── Fetch lineup curent ───────────────────────────────────────────
        lineup_data = None
        if self._cache:
            lineup_data = self._cache.get_lineup(event_id)

        if lineup_data is None and self._api:
            raw = self._api._sportapi_get(f"event/{event_id}/lineups")
            if raw:
                lineup_data = raw
                if self._cache:
                    self._cache.set_lineup(event_id, raw)

        if not lineup_data:
            report.data_quality = "unavailable"
            report.summary      = "⚠️ Lineup neconfirmat încă"
            return report

        # ── Extrage titularii din lineup ──────────────────────────────────
        home_away = "home" if str(team_id) in str(
            lineup_data.get("home", {}).get("players", [{}])[0]
            if lineup_data.get("home", {}).get("players") else ""
        ) else "away"

        team_lineup = lineup_data.get(home_away, {})
        if not team_lineup:
            # Încearcă să găsim echipa după ID
            for side in ("home", "away"):
                side_data = lineup_data.get(side, {})
                players   = side_data.get("players", [])
                if players:
                    first_player = players[0] if players else {}
                    if str(first_player.get("teamId", "")) == str(team_id):
                        team_lineup = side_data
                        break

        starters_in_lineup: set[str] = set()
        starter_details: dict[str, dict] = {}

        for player_entry in team_lineup.get("players", []):
            p = player_entry.get("player", {})
            if not player_entry.get("substitute", True):  # substitute=False = titular
                pid  = str(p.get("id", ""))
                name = p.get("name", p.get("shortName", ""))
                pos  = player_entry.get("position", "M")
                mins = player_entry.get("statistics", {}).get(
                    "minutesPlayed", 90
                )
                starters_in_lineup.add(name)
                starter_details[name] = {
                    "id":       pid,
                    "position": pos,
                    "minutes":  mins,
                }

        # ── Fetch formația standard (ultimele 5 meciuri) ──────────────────
        usual_starters: dict[str, dict] = {}

        if self._api and team_id:
            recent_events = self._api._fetch_sportapi_team_events(
                int(team_id), last_n=5
            )
            for ev in recent_events:
                ev_id = ev.get("event_id")
                if not ev_id:
                    continue
                ev_lineup = self._api._sportapi_get(f"event/{ev_id}/lineups")
                if not ev_lineup:
                    continue
                for side in ("home", "away"):
                    side_data = ev_lineup.get(side, {})
                    for pe in side_data.get("players", []):
                        p   = pe.get("player", {})
                        if pe.get("substitute", True):
                            continue
                        pid  = str(p.get("id", ""))
                        name = p.get("name", p.get("shortName", ""))
                        pos  = pe.get("position", "M")
                        if name not in usual_starters:
                            usual_starters[name] = {
                                "id":        pid,
                                "position":  pos,
                                "app_count": 0,
                            }
                        usual_starters[name]["app_count"] = (
                            usual_starters[name].get("app_count", 0) + 1
                        )

        # ── Identifică absenții ───────────────────────────────────────────
        # Jucătorii care apar în ≥3 din ultimele 5 dar nu sunt în lineup curent
        potential_absences = {
            name: data
            for name, data in usual_starters.items()
            if data.get("app_count", 0) >= 3
            and name not in starters_in_lineup
        }

        if not potential_absences:
            report.data_quality = "confirmed"
            report.summary      = "✅ Fără absențe notabile față de formația standard"
            return report

        # ── Fetch minute jucate în sezon pentru fiecare absent ────────────
        team_total_minutes = 3060  # estimat: 34 meciuri × 90 min
        absences: list[PlayerAbsence] = []

        for name, pdata in potential_absences.items():
            pid       = pdata.get("id", "")
            position  = pdata.get("position", "M")
            minutes   = 0

            # Fetch player season statistics
            if self._api and pid:
                player_stats = self._api._sportapi_get(
                    f"player/{pid}/season/statistics",
                    # params vor fi adăugate de API
                )
                if player_stats and "statistics" in player_stats:
                    minutes = int(
                        player_stats["statistics"].get("minutesPlayed", 0) or 0
                    )

            # Dacă nu avem minute, estimăm din numărul de apariții
            if not minutes:
                minutes = pdata.get("app_count", 3) * 85

            impact = self._calc_impact(
                minutes_played     = minutes,
                position           = position,
                absence_type       = "injured",   # presupunem accidentat
                team_total_minutes = team_total_minutes,
            )

            label = self._impact_label(minutes)

            absence = PlayerAbsence(
                player_id    = pid,
                name         = name,
                position     = position,
                minutes_played = minutes,
                absence_type = "injured",
                certainty    = 0.8,   # 80% certitudine (comparare lineup)
                xg_impact    = impact,
                impact_label = label,
                note         = (
                    f"{label} | {minutes} min în sezon | "
                    f"Impact xG: {impact*100:.1f}%"
                ),
            )
            absences.append(absence)

        # ── Calculează impactul total ──────────────────────────────────────
        total_penalty = max(
            sum(a.xg_impact for a in absences),
            -MAX_TOTAL_TEAM_IMPACT,
        )

        has_key = any(
            a.minutes_played >= MIN_KEY_PLAYER_MINUTES for a in absences
        )

        # Sortează după impact (cel mai mare impact primul)
        absences.sort(key=lambda a: a.xg_impact)

        absence_names = ", ".join(
            f"{a.name} ({a.position})" for a in absences[:3]
        )
        report.absences         = absences
        report.total_xg_penalty = round(total_penalty, 4)
        report.data_quality     = "confirmed"
        report.has_key_absences = has_key
        report.summary          = (
            f"{'⚠️' if has_key else 'ℹ️'} "
            f"{len(absences)} absență/e detectate: {absence_names} | "
            f"Penalizare xG totală: {total_penalty*100:.1f}%"
        )

        logger.info(
            "[Injuries] %s: %d absences, total xG penalty=%.3f",
            team_name, len(absences), total_penalty,
        )

        return report

    # ══════════════════════════════════════════════════════════════════════
    # SIMPLE INJURY REPORT (fără lineup comparat — fallback)
    # ══════════════════════════════════════════════════════════════════════

    def get_injury_report_from_cache(
        self,
        team_id:   int | str,
        team_name: str,
    ) -> TeamInjuryReport:
        """
        Returnează raportul de accidentări din cache.
        Fallback când nu avem lineup confirmat.
        """
        report = TeamInjuryReport(
            team_name = team_name,
            team_id   = team_id,
        )

        if not self._cache:
            report.data_quality = "unavailable"
            return report

        cached = self._cache.get_injuries(team_id)
        if not cached:
            report.data_quality = "unavailable"
            report.summary      = "ℹ️ Date accidentări indisponibile"
            return report

        absences: list[PlayerAbsence] = []
        for item in cached:
            impact = self._calc_impact(
                minutes_played     = item.get("minutes", 500),
                position           = item.get("position", "M"),
                absence_type       = item.get("status", "injured"),
                team_total_minutes = item.get("team_total_minutes", 3060),
            )
            label = self._impact_label(item.get("minutes", 500))
            absences.append(PlayerAbsence(
                player_id    = item.get("id", ""),
                name         = item.get("name", "Unknown"),
                position     = item.get("position", "M"),
                minutes_played = item.get("minutes", 500),
                absence_type = item.get("status", "injured"),
                certainty    = ABSENCE_CERTAINTY.get(
                    item.get("status", "injured"), 0.5
                ),
                xg_impact    = impact,
                impact_label = label,
                note         = (
                    f"{label} | {item.get('minutes',500)} min | "
                    f"Impact: {impact*100:.1f}%"
                ),
            ))

        total_penalty = max(
            sum(a.xg_impact for a in absences),
            -MAX_TOTAL_TEAM_IMPACT,
        )
        has_key = any(
            a.minutes_played >= MIN_KEY_PLAYER_MINUTES for a in absences
        )
        absences.sort(key=lambda a: a.xg_impact)

        report.absences         = absences
        report.total_xg_penalty = round(total_penalty, 4)
        report.data_quality     = "estimated"
        report.has_key_absences = has_key
        report.summary          = (
            f"{'⚠️' if has_key else 'ℹ️'} "
            f"{len(absences)} absențe din cache | "
            f"Penalizare: {total_penalty*100:.1f}%"
        )

        return report

    # ══════════════════════════════════════════════════════════════════════
    # APPLY IMPACT TO XG
    # ══════════════════════════════════════════════════════════════════════

    def apply_injury_penalty(
        self,
        home_xg:      float,
        away_xg:      float,
        home_report:  TeamInjuryReport,
        away_report:  TeamInjuryReport,
    ) -> tuple[float, float, str]:
        """
        Aplică penalizările de accidentări pe xG-urile calculate.

        Returns:
            (home_xg_adjusted, away_xg_adjusted, injury_note)
        """
        notes: list[str] = []

        # Penalizare home
        home_penalty = home_report.total_xg_penalty
        if home_penalty < 0:
            home_xg_new = max(home_xg * (1 + home_penalty), 0.20)
            notes.append(
                f"🏠 {home_report.team_name}: "
                f"{home_penalty*100:.1f}% xG penalty"
            )
        else:
            home_xg_new = home_xg

        # Penalizare away
        away_penalty = away_report.total_xg_penalty
        if away_penalty < 0:
            away_xg_new = max(away_xg * (1 + away_penalty), 0.20)
            notes.append(
                f"✈️ {away_report.team_name}: "
                f"{away_penalty*100:.1f}% xG penalty"
            )
        else:
            away_xg_new = away_xg

        note = "  |  ".join(notes) if notes else "✅ Fără penalizări accidentări"

        return round(home_xg_new, 4), round(away_xg_new, 4), note

    # ══════════════════════════════════════════════════════════════════════
    # UI HELPER
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def format_report_for_ui(report: TeamInjuryReport) -> str:
        """
        Formatează raportul pentru afișare în Streamlit.
        Returns HTML string.
        """
        if not report.absences:
            return (
                f'<div style="color:#00d17a;font-family:var(--mono);'
                f'font-size:.8rem;">✅ Fără absențe notabile</div>'
            )

        rows = ""
        for a in report.absences[:5]:  # max 5 în UI
            color = (
                "#ff4757" if a.minutes_played >= MIN_KEY_PLAYER_MINUTES
                else "#f5a623" if a.minutes_played >= MIN_STARTER_MINUTES
                else "#8892a4"
            )
            rows += (
                f'<div style="display:flex;justify-content:space-between;'
                f'margin:3px 0;font-family:var(--mono);font-size:.75rem;">'
                f'<span style="color:{color};">{a.impact_label} {a.name} ({a.position})</span>'
                f'<span style="color:#ff4757;">{a.xg_impact*100:.1f}%</span>'
                f'</div>'
            )

        total_color = (
            "#ff4757" if report.total_xg_penalty < -0.10
            else "#f5a623" if report.total_xg_penalty < -0.05
            else "#8892a4"
        )

        return f"""
        <div style="background:#141820;border:1px solid #1e2535;
                    border-radius:8px;padding:.7rem;margin:.3rem 0;">
            <div style="font-family:var(--mono);font-size:.65rem;
                        color:#4a5568;letter-spacing:.1em;
                        text-transform:uppercase;margin-bottom:.4rem;">
                Absențe detectate
            </div>
            {rows}
            <div style="border-top:1px solid #1e2535;margin-top:.4rem;
                        padding-top:.4rem;font-family:var(--mono);
                        font-size:.78rem;">
                <span style="color:#4a5568;">Total penalizare xG: </span>
                <span style="color:{total_color};font-weight:600;">
                    {report.total_xg_penalty*100:.1f}%
                </span>
            </div>
        </div>
        """


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  injury_manager.py — self-test")
    print("=" * 55)

    im = InjuryManager()

    # Test 1: calc_impact — jucător cheie
    impact_key = im._calc_impact(
        minutes_played=2800, position="F",
        absence_type="injured", team_total_minutes=3060,
    )
    assert impact_key < -0.10, f"Key player impact prea mic: {impact_key}"
    print(f"  ✅  Key player (FWD, 2800 min): {impact_key*100:.1f}% xG")

    # Test 2: calc_impact — rezervă
    impact_sub = im._calc_impact(
        minutes_played=200, position="D",
        absence_type="doubtful", team_total_minutes=3060,
    )
    assert -0.03 < impact_sub < 0, f"Sub impact wrong: {impact_sub}"
    print(f"  ✅  Rotation player (DEF, 200 min, doubtful): {impact_sub*100:.1f}% xG")

    # Test 3: impact_label
    assert im._impact_label(2000) == "⚡ KEY PLAYER"
    assert im._impact_label(1000) == "🔵 STARTER"
    assert im._impact_label(300)  == "⬜ ROTATION"
    print("  ✅  impact_label()")

    # Test 4: apply_injury_penalty
    home_report = TeamInjuryReport(
        team_name="Bayern", team_id=2672,
        total_xg_penalty=-0.12,
    )
    away_report = TeamInjuryReport(
        team_name="Lazio", team_id=2699,
        total_xg_penalty=0.0,
    )
    h_new, a_new, note = im.apply_injury_penalty(
        2.0, 1.2, home_report, away_report
    )
    assert h_new < 2.0, "Home xG should decrease"
    assert a_new == 1.2, "Away xG unchanged"
    print(f"  ✅  apply_injury_penalty: {2.0:.2f}→{h_new:.2f} home, {1.2:.2f}→{a_new:.2f} away")
    print(f"       Note: {note}")

    # Test 5: format_report_for_ui
    test_report = TeamInjuryReport(
        team_name="Test FC", team_id=1,
        absences=[
            PlayerAbsence(
                player_id=1, name="Mbappé", position="F",
                minutes_played=2800, absence_type="injured",
                certainty=1.0, xg_impact=-0.15,
                impact_label="⚡ KEY PLAYER",
                note="Test",
            )
        ],
        total_xg_penalty=-0.15,
        data_quality="confirmed",
        has_key_absences=True,
    )
    html = InjuryManager.format_report_for_ui(test_report)
    assert "Mbappé" in html
    print("  ✅  format_report_for_ui()")

    # Test 6: MAX caps
    impact_max = im._calc_impact(
        minutes_played=3060, position="G",
        absence_type="injured", team_total_minutes=3060,
    )
    assert impact_max >= -MAX_SINGLE_PLAYER_IMPACT
    print(f"  ✅  MAX cap respectat: {impact_max*100:.1f}% (max {MAX_SINGLE_PLAYER_IMPACT*100:.0f}%)")

    print("\n  Toate testele au trecut ✅\n")
