"""
================================================================================
FOOTBALL ORACLE — Cache Manager v1.0
================================================================================
"""
from __future__ import annotations
import json, logging, os, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("FootballOracle.Cache")

CATEGORY_TTL: dict[str, float] = {
    "seasons": 24.0, "form": 6.0, "h2h": 48.0,
    "corners": 24.0, "cards": 24.0, "injuries": 2.0,
    "lineups": 1.0, "standings": 12.0, "odds": 4.0,
    "elo": 24.0, "events": 0.5,
}

class CacheManager:
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = Path(__file__).parent / "cache"
        self.base = Path(base_dir)
        self._init_dirs()

    def _init_dirs(self):
        for category in list(CATEGORY_TTL.keys()) + ["meta"]:
            (self.base / category).mkdir(parents=True, exist_ok=True)

    def _path(self, category, key):
        safe_key = key.replace("/","_").replace("\\","_").replace(":","_").replace(" ","_").replace("|","_")
        return self.base / category / f"{safe_key}.json"

    def _is_fresh(self, path, category):
        if not path.exists(): return False
        try:
            ttl_hours = CATEGORY_TTL.get(category, 24.0)
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
            return age_hours < ttl_hours
        except Exception: return False

    def get(self, category, key):
        path = self._path(category, key)
        if not self._is_fresh(path, category): return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
        except Exception: return None

    def set(self, category, key, data):
        if data is None: return False
        path = self._path(category, key)
        tmp_path = path.with_suffix(".tmp")
        try:
            envelope = {
                "_cached_at": datetime.now(timezone.utc).isoformat(),
                "_category": category, "_key": key,
                "_ttl_hours": CATEGORY_TTL.get(category, 24.0),
                "data": data,
            }
            tmp_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(path)
            return True
        except Exception:
            if tmp_path.exists(): tmp_path.unlink(missing_ok=True)
            return False

    def get_raw(self, category, key):
        result = self.get(category, key)
        if result is None: return None
        if isinstance(result, dict) and "data" in result and "_cached_at" in result:
            return result["data"]
        return result

    def exists(self, category, key):
        return self._is_fresh(self._path(category, key), category)

    def invalidate(self, category, key):
        path = self._path(category, key)
        try:
            if path.exists(): path.unlink(); return True
        except Exception: pass
        return False

    def invalidate_category(self, category):
        cat_dir = self.base / category
        count = 0
        try:
            for f in cat_dir.glob("*.json"): f.unlink(missing_ok=True); count += 1
        except Exception: pass
        return count

    def invalidate_all(self):
        total = 0
        for category in CATEGORY_TTL: total += self.invalidate_category(category)
        return total

    def get_age_hours(self, category, key):
        path = self._path(category, key)
        if not path.exists(): return None
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            return (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        except Exception: return None

    def get_lineup(self, event_id):
        return self.get_raw("lineups", str(event_id))

    def set_lineup(self, event_id, data):
        return self.set("lineups", str(event_id), data)

    def get_injuries(self, team_id):
        return self.get_raw("injuries", str(team_id))

    def set_injuries(self, team_id, data):
        return self.set("injuries", str(team_id), data)

    def get_h2h(self, team_a, team_b):
        key = "_vs_".join(sorted([team_a.lower().replace(" ","_"), team_b.lower().replace(" ","_")]))
        return self.get_raw("h2h", key)

    def set_h2h(self, team_a, team_b, data):
        key = "_vs_".join(sorted([team_a.lower().replace(" ","_"), team_b.lower().replace(" ","_")]))
        return self.set("h2h", key, data)

    def get_standings(self, league, season):
        key = f"{league.replace(' ','_')}_{season}"
        return self.get_raw("standings", key)

    def set_standings(self, league, season, data):
        key = f"{league.replace(' ','_')}_{season}"
        return self.set("standings", key, data)

    def stats(self):
        result = {"total_files": 0, "total_size_kb": 0.0, "by_category": {}, "stale_files": 0}
        for category in CATEGORY_TTL:
            cat_dir = self.base / category
            files = list(cat_dir.glob("*.json"))
            fresh = sum(1 for f in files if self._is_fresh(f, category))
            stale = len(files) - fresh
            size_kb = sum(f.stat().st_size for f in files if f.exists()) / 1024
            result["by_category"][category] = {"files": len(files), "fresh": fresh, "stale": stale, "size_kb": round(size_kb,1), "ttl_hours": CATEGORY_TTL[category]}
            result["total_files"] += len(files)
            result["total_size_kb"] += size_kb
            result["stale_files"] += stale
        result["total_size_kb"] = round(result["total_size_kb"], 1)
        return result

    def _log_hit(self, category): pass
    def _log_write(self, category): pass
    def get_meta(self): return {}

_cache_instance = None

def get_cache():
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager()
    return _cache_instance
