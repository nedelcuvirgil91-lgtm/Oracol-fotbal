"""
================================================================================
FOOTBALL ORACLE — Injury & Suspension Manager v2.1
================================================================================
Module  : injury_manager.py
CHANGES v2.0:
  - get_lineup_absences() primește acum is_home: bool (nu league: str)
  - Citește direct lineup.unavailable[] din Free Live Football endpoint
  - Impact calculat din marketValue (proxy importanță) + certainty din expectedReturn

CHANGES v2.1:
  - get_lineup_absences() delegă fetch-ul către self._api.get_lineup()
    (oracle_api.py) în loc să-și ducă propriul HTTP call cu URL/cheie
    RapidAPI hardcodate în acest fișier. Asta elimină:
      1) duplicarea cheii API în două fișiere (risc la rotația cheii)
      2) un bug de robustețe: fetch-ul propriu citea doar
         lineup_data["lineup"], fără fallback pe ["response"] — pe care
         get_lineup() din oracle_api.py îl gestionează deja corect.
  - Parsarea câmpurilor folosește acum schema normalizată din get_lineup()
    ("market_value" în loc de "marketValue"; "position" e preluat la fel
    ca înainte — oracle_api.py a fost actualizat să-l includă).
================================================================================
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("FootballOracle.Injuries")

POSITION_WEIGHTS: dict[str, float] = {
    "G": 1.5, "GK": 1.5, "D": 1.0, "DEF": 1.0, "M": 0.8, "MID": 0.8,
    "F": 1.2, "FWD": 1.2, "A": 1.2,
}

ABSENCE_CERTAINTY: dict[str, float] = {
    "injured": 1.0, "suspended": 1.0, "doubtful": 0.5,
    "questionable": 0.4, "unknown": 0.3,
}

_EXPECTED_RETURN_CERTAINTY: dict[str, float] = {
    "doubtful": 0.50, "doubt": 0.50,
    "about a week": 0.95, "a week": 0.95,
    "two weeks": 0.95, "2 weeks": 0.95,
    "a month": 0.95, "month": 0.95,
    "out": 0.95, "injured": 0.85,
    "suspended": 1.0, "ban": 1.0,
    "questionable": 0.40,
}

MIN_STARTER_MINUTES    = 900
MIN_KEY_PLAYER_MINUTES = 1500
MAX_SINGLE_PLAYER_IMPACT = 0.18
MAX_TOTAL_TEAM_IMPACT    = 0.30

# Prag marketValue (€) sub care jucătorul e considerat rotație
MARKET_VALUE_KEY_PLAYER = 20_000_000   # >20M = KEY PLAYER
MARKET_VALUE_STARTER    = 5_000_000    # >5M  = STARTER


@dataclass
class PlayerAbsence:
    player_id:     int | str
    name:          str
    position:      str
    minutes_played: int
    market_value:  int            # €
    absence_type:  str
    certainty:     float
    xg_impact:     float
    impact_label:  str
    note:          str


@dataclass
class TeamInjuryReport:
    team_name:        str
    team_id:          int | str | None
    absences:         list[PlayerAbsence] = field(default_factory=list)
    total_xg_penalty: float = 0.0
    data_quality:     str   = "unknown"
    summary:          str   = ""
    has_key_absences: bool  = False


class InjuryManager:
    """Calculează impactul accidentărilor și suspendărilor pe xG."""

    def __init__(self, api=None, cache=None) -> None:
        self._api   = api
        self._cache = cache

    # ── Impact calculator ─────────────────────────────────────────────────
    def _calc_impact_from_market_value(
        self,
        market_value: int,
        position: str,
        certainty: float,
    ) -> float:
        """
        Calculează penalizarea xG pe baza market value (proxy importanță).
        Market value e mereu disponibil în Free Live Football lineup.

        Formule:
          mv_share  = log10(market_value + 1) / log10(max_expected + 1)
          pos_w     = POSITION_WEIGHTS[position]
          penalty   = min(mv_share * pos_w * certainty * 0.20, MAX_SINGLE)
        """
        import math
        max_expected = 150_000_000  # €150M = Mbappé-level
        mv_norm = math.log10(max(market_value, 100_000) + 1) / math.log10(max_expected + 1)
        pos_key = position.upper()[:3]
        pos_w   = POSITION_WEIGHTS.get(pos_key, 0.8)
        penalty = min(mv_norm * pos_w * certainty * 0.25, MAX_SINGLE_PLAYER_IMPACT)
        return -round(penalty, 4)

    def _parse_certainty_from_text(self, expected_return_text: str) -> float:
        """Extrage certainty din textul liber expectedReturn."""
        if not expected_return_text:
            return 0.80  # default: probabil absent
        txt = expected_return_text.lower().strip()
        for keyword, cert in _EXPECTED_RETURN_CERTAINTY.items():
            if keyword in txt:
                return cert
        return 0.80

    def _impact_label_from_market_value(self, market_value: int) -> str:
        if market_value >= MARKET_VALUE_KEY_PLAYER:
            return "⚡ KEY PLAYER"
        if market_value >= MARKET_VALUE_STARTER:
            return "🔵 STARTER"
        return "⬜ ROTATION"

    def _impact_label(self, minutes: int) -> str:
        if minutes >= MIN_KEY_PLAYER_MINUTES: return "⚡ KEY PLAYER"
        if minutes >= MIN_STARTER_MINUTES:   return "🔵 STARTER"
        return "⬜ ROTATION"

    # ── FETCH LINEUP — Free Live Football (semnătură NOUĂ v2.0) ──────────
    def get_lineup_absences(
        self,
        event_id:  int | str,
        team_id:   int | str,
        team_name: str,
        is_home:   bool,        # ← SEMNĂTURĂ NOUĂ: bool, nu string league
    ) -> TeamInjuryReport:
        """
        [NEAPELATĂ din oracle_engine.py — R-Sync-10, ADR-039] Fetch lineup
        prin oracle_api.get_lineup() (Free Live Football) și returnează
        absenții. Rămâne definită (Sync Layer/scripturi standalone o pot
        folosi în continuare) — dar calea live de servire citește azi
        STRICT din Supabase (`database.queries.get_freelf_lineup_snapshot()`
        + `build_injury_report_from_raw_lineup()` de mai jos), niciodată
        prin această metodă. Delegăm fetch-ul propriu-zis către
        oracle_api.py — acolo se gestionează deja URL-ul, cheia RapidAPI,
        caching-ul în memorie, și fallback-ul pe forma de răspuns
        ("lineup" sau "response").

        get_lineup() întoarce deja normalizat:
          {confirmed, formation, unavailable: [{id, name, position,
                                                 market_value, unavailability}]}
        """
        if not self._api or not event_id:
            report = TeamInjuryReport(team_name=team_name, team_id=team_id)
            report.data_quality = "unavailable"
            report.summary      = "⚠️ Date lineup indisponibile (no API/event_id)"
            return report

        # ── Check cache (disc, categorie "lineups") ───────────────────────
        cache_key = f"lineup_{event_id}_{'home' if is_home else 'away'}"
        lineup_data = None
        if self._cache:
            lineup_data = self._cache.get_raw("lineups", cache_key)

        # ── Fetch prin oracle_api.get_lineup() — sursă unică de adevăr ────
        if lineup_data is None:
            try:
                raw = self._api.get_lineup(event_id, is_home)
                if raw:
                    lineup_data = raw
                    if self._cache:
                        self._cache.set("lineups", cache_key, raw)
            except Exception as exc:
                logger.warning("[InjuryManager] Lineup fetch failed: %s", exc)

        return self.build_injury_report_from_raw_lineup(lineup_data, team_id, team_name)

    # ── PARSE LINEUP (pură, fără I/O) — R-Sync-10 ─────────────────────────
    def build_injury_report_from_raw_lineup(
        self,
        lineup_data: dict | None,
        team_id:     int | str,
        team_name:   str,
    ) -> TeamInjuryReport:
        """
        Logica de calcul a penalizării (impact per jucător, agregare,
        etichete) EXTRASĂ identic din fostul `get_lineup_absences()` —
        „no defect, no rewrite" (ADR-038). Singurul apelant de producție
        rămâne `oracle_engine.py` (Database-First, R-Sync-10) — primește
        `lineup_data` deja normalizat, exact forma întoarsă de
        `oracle_api.get_lineup()` / persistată de
        `freelf_lineup_adapter.py`
        ({confirmed, formation, unavailable: [{id, name, position,
        market_value, unavailability}]}), niciodată printr-un apel live.

        Funcție pură — zero I/O, testabilă izolat.
        """
        report = TeamInjuryReport(team_name=team_name, team_id=team_id)

        if not lineup_data:
            report.data_quality = "unavailable"
            report.summary      = "⚠️ Lineup neconfirmat"
            return report

        # ── Parsează unavailable[] (deja normalizat de get_lineup()) ─────
        unavailable = lineup_data.get("unavailable", [])

        if not unavailable:
            report.data_quality = "confirmed"
            report.summary      = "✅ Fără absențe confirmate"
            return report

        absences: list[PlayerAbsence] = []
        for player in unavailable:
            try:
                pid    = player.get("id", "")
                name   = player.get("name", "Unknown")
                mv     = int(player.get("market_value", 0) or 0)
                unavail = player.get("unavailability", {})
                abs_type = (unavail.get("type", "injured") or "injured").lower()
                exp_ret  = unavail.get("expectedReturn", "") or ""
                certainty = self._parse_certainty_from_text(exp_ret)
                if abs_type == "suspended": certainty = 1.0
                position = player.get("position", "M") or "M"
                impact   = self._calc_impact_from_market_value(mv, position, certainty)
                label    = self._impact_label_from_market_value(mv)
                mv_str   = f"€{mv/1_000_000:.1f}M" if mv >= 1_000_000 else f"€{mv:,}"
                note     = f"{label} | {mv_str} | {abs_type} | ret: {exp_ret or 'unknown'} | xG: {impact*100:.1f}%"
                absences.append(PlayerAbsence(
                    player_id=pid, name=name, position=position,
                    minutes_played=0, market_value=mv,
                    absence_type=abs_type, certainty=certainty,
                    xg_impact=impact, impact_label=label, note=note,
                ))
            except (TypeError, ValueError) as exc:
                logger.debug("[InjuryManager] Parse error for player: %s", exc)
                continue

        total_penalty = max(sum(a.xg_impact for a in absences), -MAX_TOTAL_TEAM_IMPACT)
        has_key = any(a.market_value >= MARKET_VALUE_KEY_PLAYER for a in absences)
        absences.sort(key=lambda a: a.xg_impact)

        absence_names = ", ".join(f"{a.name} ({a.position})" for a in absences[:3])
        report.absences         = absences
        report.total_xg_penalty = round(total_penalty, 4)
        report.data_quality     = "confirmed"
        report.has_key_absences = has_key
        report.summary          = (
            f"{'⚠️' if has_key else 'ℹ️'} "
            f"{len(absences)} absență/e: {absence_names} | "
            f"Penalizare xG: {total_penalty*100:.1f}%"
        )
        logger.info("[Injuries] %s: %d absences, xG penalty=%.3f", team_name, len(absences), total_penalty)
        return report

    # ── Fallback din cache ─────────────────────────────────────────────────
    def get_injury_report_from_cache(self, team_id: int | str, team_name: str) -> TeamInjuryReport:
        report = TeamInjuryReport(team_name=team_name, team_id=team_id)
        if not self._cache:
            report.data_quality = "unavailable"; return report
        cached = self._cache.get_injuries(team_id)
        if not cached:
            report.data_quality = "unavailable"
            report.summary = "ℹ️ Date accidentări indisponibile"; return report
        absences: list[PlayerAbsence] = []
        for item in cached:
            mv     = int(item.get("marketValue", 0) or 0)
            abs_type = item.get("status", "injured")
            cert   = ABSENCE_CERTAINTY.get(abs_type, 0.5)
            pos    = item.get("position", "M")
            impact = self._calc_impact_from_market_value(mv, pos, cert)
            label  = self._impact_label_from_market_value(mv)
            absences.append(PlayerAbsence(
                player_id=item.get("id",""), name=item.get("name","Unknown"),
                position=pos, minutes_played=0, market_value=mv,
                absence_type=abs_type, certainty=cert,
                xg_impact=impact, impact_label=label,
                note=f"{label} | {abs_type} | xG: {impact*100:.1f}%",
            ))
        total_penalty = max(sum(a.xg_impact for a in absences), -MAX_TOTAL_TEAM_IMPACT)
        has_key = any(a.market_value >= MARKET_VALUE_KEY_PLAYER for a in absences)
        absences.sort(key=lambda a: a.xg_impact)
        report.absences = absences; report.total_xg_penalty = round(total_penalty,4)
        report.data_quality = "estimated"; report.has_key_absences = has_key
        report.summary = f"{'⚠️' if has_key else 'ℹ️'} {len(absences)} absențe din cache | Penalizare: {total_penalty*100:.1f}%"
        return report

    # ── Apply penalty ─────────────────────────────────────────────────────
    def apply_injury_penalty(self, home_xg: float, away_xg: float, home_report: TeamInjuryReport, away_report: TeamInjuryReport) -> tuple[float, float, str]:
        notes: list[str] = []
        home_penalty = home_report.total_xg_penalty
        home_xg_new  = max(home_xg * (1 + home_penalty), 0.20) if home_penalty < 0 else home_xg
        if home_penalty < 0: notes.append(f"🏠 {home_report.team_name}: {home_penalty*100:.1f}% xG penalty")
        away_penalty = away_report.total_xg_penalty
        away_xg_new  = max(away_xg * (1 + away_penalty), 0.20) if away_penalty < 0 else away_xg
        if away_penalty < 0: notes.append(f"✈️ {away_report.team_name}: {away_penalty*100:.1f}% xG penalty")
        note = "  |  ".join(notes) if notes else "✅ Fără penalizări accidentări"
        return round(home_xg_new,4), round(away_xg_new,4), note

    # ── UI formatter ──────────────────────────────────────────────────────
    @staticmethod
    def format_report_for_ui(report: TeamInjuryReport) -> str:
        if not report.absences:
            return '<div style="color:#00d17a;font-family:var(--mono);font-size:.8rem;">✅ Fără absențe notabile</div>'
        rows = ""
        for a in report.absences[:5]:
            color = "#ff4757" if a.market_value >= MARKET_VALUE_KEY_PLAYER else ("#f5a623" if a.market_value >= MARKET_VALUE_STARTER else "#8892a4")
            rows += f'<div style="display:flex;justify-content:space-between;margin:3px 0;font-family:var(--mono);font-size:.75rem;"><span style="color:{color};">{a.impact_label} {a.name} ({a.position})</span><span style="color:#ff4757;">{a.xg_impact*100:.1f}%</span></div>'
        total_color = "#ff4757" if report.total_xg_penalty < -0.10 else ("#f5a623" if report.total_xg_penalty < -0.05 else "#8892a4")
        return f'<div style="background:#141820;border:1px solid #1e2535;border-radius:8px;padding:.7rem;margin:.3rem 0;"><div style="font-family:var(--mono);font-size:.65rem;color:#4a5568;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem;">Absențe detectate</div>{rows}<div style="border-top:1px solid #1e2535;margin-top:.4rem;padding-top:.4rem;font-family:var(--mono);font-size:.78rem;"><span style="color:#4a5568;">Total penalizare xG: </span><span style="color:{total_color};font-weight:600;">{report.total_xg_penalty*100:.1f}%</span></div></div>'


if __name__ == "__main__":
    print("\n" + "="*55)
    print("  injury_manager.py v2.1 — self-test")
    print("="*55)
    im = InjuryManager()
    # Test 1: calc_impact_from_market_value
    impact_key = im._calc_impact_from_market_value(80_000_000, "F", 1.0)
    assert impact_key < -0.10, f"Key player impact prea mic: {impact_key}"
    print(f"  ✅  Key player (€80M FWD): {impact_key*100:.1f}% xG")
    # Test 2: rotation player
    impact_rot = im._calc_impact_from_market_value(1_000_000, "D", 0.5)
    assert -0.15 < impact_rot < 0, f"Rotation impact wrong: {impact_rot}"
    print(f"  ✅  Rotation (€1M DEF, doubtful): {impact_rot*100:.1f}% xG")
    # Test 3: certainty parse
    assert im._parse_certainty_from_text("Doubtful") == 0.50
    assert im._parse_certainty_from_text("About a week") == 0.95
    assert im._parse_certainty_from_text("Suspended") == 1.0
    print("  ✅  _parse_certainty_from_text()")
    # Test 4: apply_injury_penalty
    hr = TeamInjuryReport(team_name="Test Home", team_id=1, total_xg_penalty=-0.12)
    ar = TeamInjuryReport(team_name="Test Away", team_id=2, total_xg_penalty=0.0)
    h_new, a_new, note = im.apply_injury_penalty(2.0, 1.2, hr, ar)
    assert h_new < 2.0 and a_new == 1.2
    print(f"  ✅  apply_injury_penalty: {2.0:.2f}→{h_new:.2f} home")
    print(f"       Note: {note}")
    print("\n  Toate testele au trecut ✅\n")
