"""
================================================================================
FOOTBALL ORACLE — Cache Manager v1.0
================================================================================
Module  : cache_manager.py
Role    : Persistent disc cache organizat pe categorii.
          Supraviețuiește restarturilor Streamlit.

Structura disc:
  cache/
  ├── seasons/     {team_id}_{league}.json          TTL: 24h
  ├── form/        {team_id}_form.json               TTL: 6h
  ├── h2h/         {team_a}_vs_{team_b}.json         TTL: 48h
  ├── corners/     {team_id}_{league}_corners.json   TTL: 24h
  ├── cards/       {team_id}_{league}_cards.json     TTL: 24h
  ├── injuries/    {team_id}_injuries.json           TTL: 2h
  ├── lineups/     {event_id}_lineup.json            TTL: 1h
  ├── standings/   {league}_{season}.json            TTL: 12h
  └── meta/        cache_stats.json                  (statistici utilizare)

API:
  cm = CacheManager()

  # Scriere
  cm.set("seasons", "2672_Bundesliga", data)

  # Citire
  data = cm.get("seasons", "2672_Bundesliga")  # None dacă expirat

  # Verificare
  cm.exists("injuries", "2672")

  # Statistici
  cm.stats()
================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("FootballOracle.Cache")

# ─────────────────────────────────────────────────────────────────────────────
# TTL CONFIG  (ore)
# ─────────────────────────────────────────────────────────────────────────────
CATEGORY_TTL: dict[str, float] = {
    "seasons":   24.0,   # statistici sezon — se schimbă rar
    "form":       6.0,   # formă recentă — după fiecare etapă
    "h2h":       48.0,   # H2H — stabil, rar se adaugă meciuri noi
    "corners":   24.0,   # cornere per meci sezon
    "cards":     24.0,   # cartonașe per meci sezon
    "injuries":   2.0,   # accidentați/suspendați — critice, se schimbă zilnic
    "lineups":    1.0,   # lineupuri confirmate — doar cu 1h înainte de meci
    "standings": 12.0,   # clasamente — după fiecare etapă
    "odds":       4.0,   # cote — se schimbă frecvent
    "elo":       24.0,   # ELO ratings
    "events":     0.5,   # meciuri live/scheduled — 30 min
}

# ─────────────────────────────────────────────────────────────────────────────
# CACHE MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class CacheManager:
    """
    Cache persistent pe disc cu TTL per categorie.
    Thread-safe pentru scriere (atomic write via temp file).
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            base_dir = Path(__file__).parent / "cache"
        self.base = Path(base_dir)
        self._init_dirs()
        logger.info("CacheManager initialized at %s", self.base)

    def _init_dirs(self) -> None:
        """Creează toate directoarele necesare."""
        for category in list(CATEGORY_TTL.keys()) + ["meta"]:
            (self.base / category).mkdir(parents=True, exist_ok=True)

    def _path(self, category: str, key: str) -> Path:
        """Returnează calea completă pentru un cache entry."""
        # Sanitizează key-ul pentru filesystem
        safe_key = (
            key.replace("/", "_")
               .replace("\\", "_")
               .replace(":", "_")
               .replace(" ", "_")
               .replace("|", "_")
        )
        return self.base / category / f"{safe_key}.json"

    def _is_fresh(self, path: Path, category: str) -> bool:
        """Verifică dacă un fișier cache este încă valid (în TTL)."""
        if not path.exists():
            return False
        try:
            ttl_hours = CATEGORY_TTL.get(category, 24.0)
            mtime = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
            age_hours = (
                datetime.now(timezone.utc) - mtime
            ).total_seconds() / 3600
            return age_hours < ttl_hours
        except Exception:
            return False

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    def get(self, category: str, key: str) -> Any | None:
        """
        Returnează datele din cache dacă sunt fresh, altfel None.

        Parameters
        ----------
        category : str  — ex: "seasons", "injuries", "h2h"
        key      : str  — ex: "2672_Bundesliga", "argentina_vs_croatia"
        """
        path = self._path(category, key)

        if not self._is_fresh(path, category):
            if path.exists():
                logger.debug("[Cache STALE] %s/%s", category, key)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.debug("[Cache HIT] %s/%s", category, key)
            self._log_hit(category)
            return data
        except Exception as exc:
            logger.warning("[Cache READ ERROR] %s/%s: %s", category, key, exc)
            return None

    def set(self, category: str, key: str, data: Any) -> bool:
        """
        Salvează date în cache.
        Folosește scriere atomică (temp file + rename) pentru siguranță.

        Returns True dacă salvarea a reușit.
        """
        if data is None:
            return False

        path = self._path(category, key)
        tmp_path = path.with_suffix(".tmp")

        try:
            # Adaugă metadata
            envelope = {
                "_cached_at": datetime.now(timezone.utc).isoformat(),
                "_category":  category,
                "_key":       key,
                "_ttl_hours": CATEGORY_TTL.get(category, 24.0),
                "data":       data,
            }
            tmp_path.write_text(
                json.dumps(envelope, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(path)  # atomic rename
            logger.debug("[Cache SET] %s/%s", category, key)
            self._log_write(category)
            return True
        except Exception as exc:
            logger.warning("[Cache WRITE ERROR] %s/%s: %s", category, key, exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return False

    def get_raw(self, category: str, key: str) -> Any | None:
        """
        Returnează datele brute din envelope (câmpul 'data').
        Identic cu get() dar mai explicit.
        """
        result = self.get(category, key)
        if result is None:
            return None
        # Dacă e envelope nou cu câmpul 'data'
        if isinstance(result, dict) and "data" in result and "_cached_at" in result:
            return result["data"]
        return result

    def exists(self, category: str, key: str) -> bool:
        """Verifică dacă există un cache fresh pentru key."""
        return self._is_fresh(self._path(category, key), category)

    def invalidate(self, category: str, key: str) -> bool:
        """Șterge un entry specific din cache."""
        path = self._path(category, key)
        try:
            if path.exists():
                path.unlink()
                logger.info("[Cache INVALIDATE] %s/%s", category, key)
                return True
        except Exception as exc:
            logger.warning("[Cache INVALIDATE ERROR] %s", exc)
        return False

    def invalidate_category(self, category: str) -> int:
        """Șterge toate entry-urile dintr-o categorie. Returns numărul șters."""
        cat_dir = self.base / category
        count = 0
        try:
            for f in cat_dir.glob("*.json"):
                f.unlink(missing_ok=True)
                count += 1
            logger.info("[Cache CLEAR] %s: %d files deleted.", category, count)
        except Exception as exc:
            logger.warning("[Cache CLEAR ERROR] %s: %s", category, exc)
        return count

    def invalidate_all(self) -> int:
        """Șterge tot cache-ul. Returns numărul total de fișiere șterse."""
        total = 0
        for category in CATEGORY_TTL:
            total += self.invalidate_category(category)
        logger.info("[Cache CLEAR ALL] %d files deleted.", total)
        return total

    def get_age_hours(self, category: str, key: str) -> float | None:
        """Returnează vârsta în ore a unui cache entry, sau None dacă nu există."""
        path = self._path(category, key)
        if not path.exists():
            return None
        try:
            mtime = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
            return (
                datetime.now(timezone.utc) - mtime
            ).total_seconds() / 3600
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════════
    # CONVENIENCE METHODS  (pentru tipurile de date specifice)
    # ══════════════════════════════════════════════════════════════════════

    def get_seasons(self, team_id: int | str, league: str) -> dict | None:
        key = f"{team_id}_{league.replace(' ', '_')}"
        return self.get_raw("seasons", key)

    def set_seasons(self, team_id: int | str, league: str, data: dict) -> bool:
        key = f"{team_id}_{league.replace(' ', '_')}"
        return self.set("seasons", key, data)

    def get_form(self, team_id: int | str) -> list | None:
        return self.get_raw("form", str(team_id))

    def set_form(self, team_id: int | str, data: list) -> bool:
        return self.set("form", str(team_id), data)

    def get_h2h(self, team_a: str, team_b: str) -> dict | None:
        # Normalizare key — întotdeauna în ordine alfabetică
        key = "_vs_".join(sorted([
            team_a.lower().replace(" ", "_"),
            team_b.lower().replace(" ", "_"),
        ]))
        return self.get_raw("h2h", key)

    def set_h2h(self, team_a: str, team_b: str, data: dict) -> bool:
        key = "_vs_".join(sorted([
            team_a.lower().replace(" ", "_"),
            team_b.lower().replace(" ", "_"),
        ]))
        return self.set("h2h", key, data)

    def get_injuries(self, team_id: int | str) -> list | None:
        return self.get_raw("injuries", str(team_id))

    def set_injuries(self, team_id: int | str, data: list) -> bool:
        return self.set("injuries", str(team_id), data)

    def get_lineup(self, event_id: int | str) -> dict | None:
        return self.get_raw("lineups", str(event_id))

    def set_lineup(self, event_id: int | str, data: dict) -> bool:
        return self.set("lineups", str(event_id), data)

    def get_standings(self, league: str, season: int | str) -> dict | None:
        key = f"{league.replace(' ', '_')}_{season}"
        return self.get_raw("standings", key)

    def set_standings(
        self, league: str, season: int | str, data: dict
    ) -> bool:
        key = f"{league.replace(' ', '_')}_{season}"
        return self.set("standings", key, data)

    def get_corners(self, team_id: int | str, league: str) -> dict | None:
        key = f"{team_id}_{league.replace(' ', '_')}_corners"
        return self.get_raw("corners", key)

    def set_corners(
        self, team_id: int | str, league: str, data: dict
    ) -> bool:
        key = f"{team_id}_{league.replace(' ', '_')}_corners"
        return self.set("corners", key, data)

    def get_cards(self, team_id: int | str, league: str) -> dict | None:
        key = f"{team_id}_{league.replace(' ', '_')}_cards"
        return self.get_raw("cards", key)

    def set_cards(
        self, team_id: int | str, league: str, data: dict
    ) -> bool:
        key = f"{team_id}_{league.replace(' ', '_')}_cards"
        return self.set("cards", key, data)

    # ══════════════════════════════════════════════════════════════════════
    # STATISTICI
    # ══════════════════════════════════════════════════════════════════════

    def stats(self) -> dict:
        """
        Returnează statistici despre cache-ul curent.
        Util pentru panoul de diagnostice din UI.
        """
        result: dict = {
            "total_files":   0,
            "total_size_kb": 0.0,
            "by_category":   {},
            "stale_files":   0,
        }

        for category in CATEGORY_TTL:
            cat_dir = self.base / category
            files   = list(cat_dir.glob("*.json"))
            fresh   = sum(
                1 for f in files if self._is_fresh(f, category)
            )
            stale   = len(files) - fresh
            size_kb = sum(
                f.stat().st_size for f in files if f.exists()
            ) / 1024

            result["by_category"][category] = {
                "files":    len(files),
                "fresh":    fresh,
                "stale":    stale,
                "size_kb":  round(size_kb, 1),
                "ttl_hours": CATEGORY_TTL[category],
            }
            result["total_files"]   += len(files)
            result["total_size_kb"] += size_kb
            result["stale_files"]   += stale

        result["total_size_kb"] = round(result["total_size_kb"], 1)
        return result

    def _log_hit(self, category: str) -> None:
        self._update_meta("hits", category)

    def _log_write(self, category: str) -> None:
        self._update_meta("writes", category)

    def _update_meta(self, event_type: str, category: str) -> None:
        meta_path = self.base / "meta" / "cache_stats.json"
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                meta = {"hits": {}, "writes": {}, "last_reset": datetime.now(timezone.utc).isoformat()}

            if event_type not in meta:
                meta[event_type] = {}
            meta[event_type][category] = meta[event_type].get(category, 0) + 1

            meta_path.write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # meta logging e non-critică

    def get_meta(self) -> dict:
        meta_path = self.base / "meta" / "cache_stats.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON  (importat de oracle_api și oracle_engine)
# ─────────────────────────────────────────────────────────────────────────────

_cache_instance: CacheManager | None = None


def get_cache() -> CacheManager:
    """
    Returnează singleton-ul CacheManager.
    Folosit de oracle_api.py și oracle_engine.py.
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager()
    return _cache_instance


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    print("\n" + "=" * 55)
    print("  cache_manager.py — self-test")
    print("=" * 55)

    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(base_dir=tmp)

        # Test set/get
        cm.set("seasons", "2672_Bundesliga", {"avg_gf": 3.59, "avg_ga": 1.06})
        data = cm.get_seasons(2672, "Bundesliga")
        assert data == {"avg_gf": 3.59, "avg_ga": 1.06}, f"FAIL: {data}"
        print("  ✅  set/get seasons")

        # Test H2H key normalization
        cm.set_h2h("Argentina", "Croatia", {"meetings": 5, "home_wins": 3})
        d1 = cm.get_h2h("Argentina", "Croatia")
        d2 = cm.get_h2h("Croatia", "Argentina")  # ordine inversă → același key
        assert d1 == d2 == {"meetings": 5, "home_wins": 3}
        print("  ✅  H2H bidirectional key")

        # Test injuries
        cm.set_injuries(2672, [{"name": "Sané", "status": "injured", "impact": -0.07}])
        inj = cm.get_injuries(2672)
        assert len(inj) == 1
        print("  ✅  injuries set/get")

        # Test stale (TTL=0 → always stale)
        CATEGORY_TTL["seasons"] = 0.0
        stale = cm.get_seasons(2672, "Bundesliga")
        CATEGORY_TTL["seasons"] = 24.0
        assert stale is None
        print("  ✅  TTL expiry")

        # Test invalidate
        cm.set("form", "2672", [{"result": "W"}, {"result": "W"}])
        cm.invalidate("form", "2672")
        assert cm.get("form", "2672") is None
        print("  ✅  invalidate")

        # Test stats
        s = cm.stats()
        assert "by_category" in s
        print("  ✅  stats()")

        print(f"\n  Total categories: {len(CATEGORY_TTL)}")
        print(f"  TTL config: {CATEGORY_TTL}")

    print("\n  Toate testele au trecut ✅\n")
