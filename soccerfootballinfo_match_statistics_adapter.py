"""
================================================================================
FOOTBALL ORACLE — Soccer Football Info Match Statistics Adapter (Sprint 1 v6, ADR-041 Faza 1)
================================================================================
Implementare `SyncAdapter` (sync_adapter.py) — Owner NOU pentru Match
Statistics, scop mult mai larg decât `MatchStatisticsAdapter` (FreeLF, scope
restrâns la possession+xG): posesie, xG, șuturi (total/pe poartă/pe lângă),
cornere, faulturi, ofsaiduri, cartonașe, penalty-uri, schimbări, lineup
complet, manageri, arbitru, stadion, `provider_raw_json` (payload brut,
pentru orice extracție viitoare fără un nou apel HTTP) — confirmat live, pe
un meci real (Dinamo București 5-1 CS U Craiova, 2026-07-25, Sprint 1 v6 §11).

Rezoluția `match_id` NU trăiește aici — deleagă la
`soccerfootballinfo_event_resolver.SoccerFootballInfoEventResolver`
(componentă reutilizabilă Sync Layer, tipar identic cu FreeLF).

`stats_source = "soccerfootballinfo"` — dacă acest adaptor scrie primul
pentru un meci, devine owner-ul înregistrat al rândului (COALESCE-only,
ADR-036); dacă alt provider a scris deja, RPC-ul canonic păstrează valorile
existente neatinse (niciun adaptor nu suprascrie alt owner).
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.SoccerFootballInfoMatchStatistics")


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _team_stats(team: dict) -> dict:
    shoots = team.get("shoots") or {}
    corners = team.get("corners") or {}
    fouls = team.get("fouls") or {}
    attacks = team.get("attacks") or {}
    xg = team.get("xG") or {}

    # xG live e mai precis (recalculat pe parcursul meciului) — kickoff e
    # doar estimarea pre-meci, folosit strict ca fallback dacă live lipsește.
    xg_value = xg.get("live")
    if xg_value is None:
        xg_value = xg.get("kickoff")

    return {
        "possession": _int_or_none(team.get("possession")),
        "xg_actual": _float_or_none(xg_value),
        "shots": _int_or_none(shoots.get("t")),
        "shots_on_target": _int_or_none(shoots.get("on")),
        "shots_off_target": _int_or_none(shoots.get("off")),
        "corners": _int_or_none(corners.get("t")),
        "fouls": _int_or_none(fouls.get("t")),
        "offsides": _int_or_none(attacks.get("o_s")),
        "yellow_cards": _int_or_none(fouls.get("y_c")),
        "red_cards": _int_or_none(fouls.get("r_c")),
        "penalties": _int_or_none(team.get("penalties")),
        "substitutions": _int_or_none(team.get("substitutions")),
    }


def _team_lineup(team: dict) -> dict | None:
    """Trece structura brută `lineup` mai departe, neprelucrată — coloană
    jsonb, consumatorii viitori decid ce extrag (Regula #8: nu aproximăm o
    formă normalizată fără un caz de utilizare real dovedit)."""
    return team.get("lineup") or None


def _team_manager(team: dict) -> str | None:
    manager = team.get("manager") or {}
    return manager.get("name") or None


class SoccerFootballInfoMatchStatisticsAdapter(SyncAdapter):
    provider_id = "soccerfootballinfo"

    def __init__(self, resolver=None, client=None):
        if resolver is None:
            from soccerfootballinfo_event_resolver import get_soccerfootballinfo_event_resolver
            resolver = get_soccerfootballinfo_event_resolver()
        self._resolver = resolver
        if client is None:
            from soccerfootballinfo_client import get_soccerfootballinfo_client
            client = get_soccerfootballinfo_client()
        self._client = client

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"home_team", "away_team", "kickoff_date", "league"}`.
        Rezolvă match_id prin resolver-ul reutilizabil, apoi cere detaliul
        complet (`matches/view/full`, singurul endpoint cu xG+lineup,
        confirmat live). match_id nerezolvat -> None, niciodată aproximat."""
        home_team = params["home_team"]
        away_team = params["away_team"]
        kickoff_date = params["kickoff_date"]
        league = params["league"]

        match_id = self._resolver.resolve(home_team, away_team, kickoff_date, league)
        if match_id is None:
            return None
        detail = self._client.get_match_detail(match_id)
        if not detail:
            return None
        return {
            "home_team": home_team, "away_team": away_team, "kickoff_date": kickoff_date,
            "detail": detail,
        }

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        if not raw_payload:
            return []
        from mappings import normalize_team_name

        detail = raw_payload["detail"]
        home = normalize_team_name(raw_payload["home_team"])
        away = normalize_team_name(raw_payload["away_team"])

        team_a = detail.get("teamA") or {}
        team_b = detail.get("teamB") or {}
        home_stats = _team_stats(team_a)
        away_stats = _team_stats(team_b)

        referee = (detail.get("referee") or {}).get("name")
        stadium = (detail.get("stadium") or {}).get("name")

        record = {
            "home_team": home, "away_team": away,
            "kickoff_date": raw_payload["kickoff_date"],
            "home_possession": home_stats["possession"],
            "away_possession": away_stats["possession"],
            "home_xg_actual": home_stats["xg_actual"],
            "away_xg_actual": away_stats["xg_actual"],
            "home_shots": home_stats["shots"],
            "away_shots": away_stats["shots"],
            "home_shots_on_target": home_stats["shots_on_target"],
            "away_shots_on_target": away_stats["shots_on_target"],
            "home_shots_off_target": home_stats["shots_off_target"],
            "away_shots_off_target": away_stats["shots_off_target"],
            "home_corners": home_stats["corners"],
            "away_corners": away_stats["corners"],
            "home_fouls": home_stats["fouls"],
            "away_fouls": away_stats["fouls"],
            "home_offsides": home_stats["offsides"],
            "away_offsides": away_stats["offsides"],
            "home_yellow_cards": home_stats["yellow_cards"],
            "away_yellow_cards": away_stats["yellow_cards"],
            "home_red_cards": home_stats["red_cards"],
            "away_red_cards": away_stats["red_cards"],
            "home_penalties": home_stats["penalties"],
            "away_penalties": away_stats["penalties"],
            "home_substitutions": home_stats["substitutions"],
            "away_substitutions": away_stats["substitutions"],
            "home_lineup": _team_lineup(team_a),
            "away_lineup": _team_lineup(team_b),
            "home_manager": _team_manager(team_a),
            "away_manager": _team_manager(team_b),
            "referee": referee,
            "stadium": stadium,
            "provider_raw_json": {
                "provider": "soccerfootballinfo",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "endpoint": "matches/view/full",
                "raw": detail,
            },
            "stats_source": "soccerfootballinfo",
        }
        return [record]

    # Câmpuri de bază — dacă TOATE lipsesc, restul rândului e aproape sigur
    # gol și el (payload incomplet/neașteptat), rândul e exclus (Regula #8).
    _CORE_FIELDS = (
        "home_possession", "away_possession", "home_xg_actual", "away_xg_actual",
        "home_shots", "away_shots", "home_corners", "away_corners",
    )

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție (Regula #8). Respinge rânduri fără
        cheia naturală (home/away/kickoff_date) SAU fără nicio valoare utilă
        din câmpurile de bază."""
        valid: list[dict] = []
        for r in records:
            if not r.get("home_team") or not r.get("away_team") or not r.get("kickoff_date"):
                logger.warning("[SoccerFootballInfoMatchStatisticsAdapter] rând fără cheie naturală, exclus: %r", r)
                continue
            has_value = any(r.get(k) is not None for k in self._CORE_FIELDS)
            if not has_value:
                logger.debug("[SoccerFootballInfoMatchStatisticsAdapter] rând fără nicio valoare utilă, exclus: %r", r)
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        """`upsert_match()` — RPC canonic `upsert_match_canonical`, COALESCE-only
        (ADR-036) — nu suprascrie niciodată o valoare deja scrisă de alt
        owner. Toate coloanele folosite aici există deja în `match_history`
        (migrarea `add_match_statistics_extended_fields`, Sprint 1 Faza 1)."""
        from database.queries import upsert_match

        ok = True
        for r in records:
            success = upsert_match(r)
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """Coverage e deja aplicată corect la nivelul League Mapping v2
        (`mappings.LEAGUE_PROVIDERS[league].supported["soccerfootballinfo"]`)
        — verificată explicit de resolver (`_championship_id`), nu duplicată
        aici (același tipar ca `ApiFootballHealthAdapter`)."""
        return True
