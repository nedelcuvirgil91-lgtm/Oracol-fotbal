"""
================================================================================
FOOTBALL ORACLE — Odds Persistence Service
================================================================================
Implementează contractul deja Frozen:
  - docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md
  - ADR-005 (governance closure)
  - ADR-006 (operational clarifications: date invalide, UTC, scope 1X2, no-retry)

Responsabilitate strictă (§3 din design):
  1. Citește cotele deja atașate pe obiectele `match` (via oracle_api._attach_odds()).
  2. Mapează la fixture_id canonic — deja prezent pe obiectul `match`, nicio
     rezoluție de identitate proprie (§5 — evită dubla sursă de adevăr).
  3. Scrie/actualizează în odds_history, respectând regula opening/closing.

NU calculează probabilități, NU ajustează xG, NU ia decizii de predicție.

Domain service — independent de orice orchestrator. `sync/run_daily.py` îl
apelează, dar nu îl "deține"; poate fi importat identic din backfill, CLI
manual, un cron cu altă cadență, sau un worker viitor (§9 din design —
"designul nu impune o anumită frecvență").
================================================================================
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("FootballOracle.OddsPersistenceService")

# Piața acoperită — ADR-006 §3. Orice altă piață (O/U, BTTS, Asian Handicap)
# e explicit în afara scopului acestui serviciu.
MARKET = "1X2"


@dataclass
class PersistenceResult:
    """Rezultatul unei rulări complete a serviciului, pt observabilitate/audit."""
    attempted: int = 0
    written: int = 0
    skipped_ineligible: int = 0   # kickoff deja trecut (§9)
    skipped_invalid: int = 0      # date invalide/incomplete (ADR-006 §1)
    skipped_no_odds: int = 0      # meciul nu are deloc cote atașate
    errors: list[str] = field(default_factory=list)


class OddsPersistenceService:
    """
    Persistă cote de piață (1X2) în `odds_history`, respectând exact
    contractul deja înghețat. Fără stare între apeluri (safe de reutilizat/
    reinstanțiat oricând).
    """

    def __init__(self, supabase_client=None):
        # lazy import — nu creăm o dependință grea la nivel de modul
        if supabase_client is None:
            import supabase_client as sb
            supabase_client = sb
        self._sb = supabase_client

    # ── Validare (ADR-006 §1) ───────────────────────────────────────────
    @staticmethod
    def _is_valid_price(value) -> bool:
        """O cotă zecimală validă e mereu strict > 1, finită, numerică."""
        if value is None:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if math.isnan(v) or math.isinf(v):
            return False
        if v <= 1:
            return False
        return True

    @classmethod
    def _is_valid_odds_set(cls, home, draw, away) -> bool:
        return (
            cls._is_valid_price(home)
            and cls._is_valid_price(draw)
            and cls._is_valid_price(away)
        )

    # ── Eligibilitate — UTC explicit (ADR-006 §2) ───────────────────────
    @staticmethod
    def _is_eligible(match: dict) -> bool:
        """
        Un fixture e eligibil doar dacă kickoff-ul (UTC) nu a trecut încă.
        Folosește `kickoff_utc` (deja prezent pe obiectul match, produs de
        oracle_api.py pentru toate sursele) — nu necesită nicio citire
        suplimentară din DB (mai simplu decât presupunea design-ul inițial,
        care presupunea o citire separată din validated.fixtures.event_date).
        """
        kickoff_utc = match.get("kickoff_utc")
        if not kickoff_utc:
            return False
        try:
            ko = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
            if ko.tzinfo is None:
                ko = ko.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return False
        return ko > datetime.now(timezone.utc)

    # ── Persistare per lot de meciuri ────────────────────────────────────
    def persist_odds_snapshot(self, matches: list[dict]) -> PersistenceResult:
        """
        Punctul de intrare principal. Fiecare `match` din listă e cel produs
        de `oracle_api.get_matches_for_week()` (deja trecut prin
        `_attach_odds()`) — se așteaptă `fixture_id`, `kickoff_utc`,
        `home_odds`/`draw_odds`/`away_odds`, `bookmaker`.

        Un eșec izolat (un singur fixture/bookmaker) nu oprește restul
        lotului — consistent cu izolarea per-fixture deja stabilită în
        PIPELINE_SPEC.md. Fără retry în aceeași rulare (ADR-006 §4).
        """
        result = PersistenceResult()

        for match in matches:
            result.attempted += 1
            fixture_id = match.get("fixture_id")
            home_name = match.get("home_team", "?")
            away_name = match.get("away_team", "?")

            if not fixture_id:
                result.errors.append(f"meci fără fixture_id: {home_name} vs {away_name}")
                continue

            if not self._is_eligible(match):
                result.skipped_ineligible += 1
                continue

            home_odds = match.get("home_odds")
            draw_odds = match.get("draw_odds")
            away_odds = match.get("away_odds")
            bookmaker = match.get("bookmaker")

            if home_odds is None and draw_odds is None and away_odds is None:
                result.skipped_no_odds += 1
                continue

            if not bookmaker or not self._is_valid_odds_set(home_odds, draw_odds, away_odds):
                result.skipped_invalid += 1
                logger.warning(
                    "[OddsPersistence] set invalid/incomplet, respins integral: "
                    "fixture=%s (%s vs %s) bookmaker=%r (%r/%r/%r)",
                    fixture_id, home_name, away_name, bookmaker, home_odds, draw_odds, away_odds,
                )
                continue

            try:
                wrote = self._upsert(
                    fixture_id, bookmaker,
                    float(home_odds), float(draw_odds), float(away_odds),
                )
                if wrote:
                    result.written += 1
            except Exception as exc:
                # ADR-006 §4: fără retry în aceeași rulare — se loghează,
                # se continuă cu restul lotului; reevaluat la rularea următoare.
                result.errors.append(f"{fixture_id}/{bookmaker}: {exc}")
                logger.error(
                    "[OddsPersistence] scriere eșuată (fără retry acum, "
                    "reevaluat la următoarea execuție programată): %s", exc,
                )
                continue

        logger.info(
            "[OddsPersistence] rulare completă: %d încercate, %d scrise, "
            "%d neeligibile, %d invalide, %d fără cote, %d erori",
            result.attempted, result.written, result.skipped_ineligible,
            result.skipped_invalid, result.skipped_no_odds, len(result.errors),
        )
        return result

    # ── Operațiune atomică unică (§10 din design) ───────────────────────
    def _upsert(self, fixture_id: str, bookmaker: str,
                home: float, draw: float, away: float) -> bool:
        """
        Un singur apel RPC → o singură instrucțiune SQL atomică
        (`upsert_odds_snapshot`, deja creată/testată în Supabase):
        INSERT ... ON CONFLICT (fixture_id, bookmaker) DO UPDATE SET
        closing_* — opening_* nu apare niciodată în clauza SET, prin
        construcție, nu prin disciplină de cod (§10). Fără check-then-act.

        Returnează True dacă s-a scris efectiv ceva (INSERT nou, sau UPDATE
        cu valori diferite) — False dacă nu s-a schimbat nimic (§8).
        """
        client = self._sb.get_client()
        if client is None:
            raise RuntimeError("Supabase indisponibil — imposibil de scris odds_history")

        now_iso = datetime.now(timezone.utc).isoformat()
        res = client.rpc("upsert_odds_snapshot", {
            "p_fixture_id": fixture_id,
            "p_bookmaker": bookmaker,
            "p_home": home,
            "p_draw": draw,
            "p_away": away,
            "p_now": now_iso,
        }).execute()
        return bool(res.data)
