"""
================================================================================
FOOTBALL ORACLE — API Key Manager v1.0
================================================================================
"""
from __future__ import annotations
import json, logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("FootballOracle.KeyManager")

BASE_DIR       = Path(__file__).parent
CACHE_DIR      = BASE_DIR / "cache"
KEY_USAGE_PATH = CACHE_DIR / "key_usage.json"
CACHE_DIR.mkdir(exist_ok=True)

PROVIDERS: dict[str, dict] = {
    "sportapi": {
        "name": "SportAPI (RapidAPI)",
        "host": "sportapi7.p.rapidapi.com",
        "base_url": "https://sportapi7.p.rapidapi.com/api/v1",
        "header_key": "x-rapidapi-key", "header_host": "x-rapidapi-host",
        "keys": [{"key": "2ff60d8248msh65d53a6d077e4abp145f79jsn980ab63d585f", "limit": 50, "label": "SportAPI-Key1"}],
    },
    "freelivefootball": {
        "name": "Free Live Football (RapidAPI)",
        "host": "free-api-live-football-data.p.rapidapi.com",
        "base_url": "https://free-api-live-football-data.p.rapidapi.com",
        "header_key": "x-rapidapi-key", "header_host": "x-rapidapi-host",
        "keys": [{"key": "2ff60d8248msh65d53a6d077e4abp145f79jsn980ab63d585f", "limit": 100, "label": "FreeLive-Key1"}],
    },
    "oddsapi": {
        "name": "The Odds API",
        "host": "api.the-odds-api.com",
        "base_url": "https://api.the-odds-api.com/v4",
        "header_key": None, "header_host": None,
        "keys": [{"key": "b0e2ab9bcda1d9f4c5ddfe1063c81cd7", "limit": 500, "label": "OddsAPI-Key1"}],
    },
    "weatherapi": {
        "name": "WeatherAPI",
        "host": "api.weatherapi.com",
        "base_url": "http://api.weatherapi.com/v1",
        "header_key": None, "header_host": None,
        "keys": [{"key": "48a5b54b8ced45cc924153231263005", "limit": 1000000, "label": "Weather-Key1"}],
    },
}

WARN_THRESHOLD      = 0.80
CRITICAL_THRESHOLD  = 0.95
EXHAUSTED_THRESHOLD = 1.00

class APIKeyManager:
    def __init__(self):
        self._usage: dict = self._load_usage()
        self._exhausted: dict[str, set[str]] = {}
        self._reset_if_new_month()

    def _load_usage(self):
        if KEY_USAGE_PATH.exists():
            try: return json.loads(KEY_USAGE_PATH.read_text(encoding="utf-8"))
            except Exception: pass
        return {"month": date.today().strftime("%Y-%m"), "providers": {}}

    def _save_usage(self):
        try: KEY_USAGE_PATH.write_text(json.dumps(self._usage, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc: logger.warning("[KeyManager] Save failed: %s", exc)

    def _reset_if_new_month(self):
        current_month = date.today().strftime("%Y-%m")
        if self._usage.get("month") != current_month:
            self._usage = {"month": current_month, "providers": {}}
            self._save_usage()

    def _get_key_usage(self, provider, key_label):
        return self._usage.get("providers", {}).get(provider, {}).get(key_label, 0)

    def _increment_usage(self, provider, key_label):
        if "providers" not in self._usage: self._usage["providers"] = {}
        if provider not in self._usage["providers"]: self._usage["providers"][provider] = {}
        prev = self._usage["providers"][provider].get(key_label, 0)
        self._usage["providers"][provider][key_label] = prev + 1
        self._save_usage()

    def _get_active_key(self, provider):
        prov = PROVIDERS.get(provider)
        if not prov: return None
        exhausted_set = self._exhausted.get(provider, set())
        for key_def in prov["keys"]:
            key = key_def["key"]; label = key_def["label"]; limit = key_def["limit"]
            used = self._get_key_usage(provider, label)
            if key in exhausted_set: continue
            if used >= limit: continue
            return {"key": key, "label": label, "limit": limit, "used": used}
        return None

    def get_key(self, provider):
        key_def = self._get_active_key(provider)
        return key_def["key"] if key_def else None

    def get_headers(self, provider):
        prov = PROVIDERS.get(provider)
        key_def = self._get_active_key(provider)
        if not prov or not key_def: return None
        headers: dict = {}
        if prov.get("header_key"): headers[prov["header_key"]] = key_def["key"]
        if prov.get("header_host"): headers[prov["header_host"]] = prov["host"]
        return headers

    def get_api_key_param(self, provider):
        key_def = self._get_active_key(provider)
        return key_def["key"] if key_def else None

    def record_request(self, provider):
        key_def = self._get_active_key(provider)
        if key_def: self._increment_usage(provider, key_def["label"])

    def mark_exhausted(self, provider, key):
        if provider not in self._exhausted: self._exhausted[provider] = set()
        self._exhausted[provider].add(key)

    def is_available(self, provider):
        return self._get_active_key(provider) is not None

    def get_status(self):
        result = {"month": self._usage.get("month",""), "providers": {}}
        for prov_id, prov in PROVIDERS.items():
            prov_status = {"name": prov["name"], "keys": [], "status": "ok"}
            exhausted_set = self._exhausted.get(prov_id, set())
            any_active = False
            for kd in prov["keys"]:
                key = kd["key"]; label = kd["label"]; limit = kd["limit"]
                used = self._get_key_usage(prov_id, label); pct = used / limit if limit > 0 else 0.0
                if key in exhausted_set or used >= limit: key_status = "exhausted"; icon = "⛔"
                elif pct >= CRITICAL_THRESHOLD: key_status = "critical"; icon = "🔴"; any_active = True
                elif pct >= WARN_THRESHOLD: key_status = "warning"; icon = "🟡"; any_active = True
                else: key_status = "ok"; icon = "🟢"; any_active = True
                prov_status["keys"].append({"label": label, "used": used, "limit": limit, "remaining": max(0, limit-used), "pct": round(pct*100,1), "status": key_status, "icon": icon})
            if not any_active: prov_status["status"] = "exhausted"
            result["providers"][prov_id] = prov_status
        return result

    def get_alerts(self):
        alerts = []
        status = self.get_status()
        for prov_id, prov_data in status["providers"].items():
            for key_data in prov_data["keys"]:
                ks = key_data["status"]
                if ks == "exhausted":
                    alerts.append({"level": "exhausted", "icon": "⛔", "provider": prov_data["name"], "key_label": key_data["label"], "message": f"⛔ {key_data['label']} — QUOTA EPUIZATĂ ({key_data['used']}/{key_data['limit']} req)."})
                elif ks == "critical":
                    alerts.append({"level": "critical", "icon": "🔴", "provider": prov_data["name"], "key_label": key_data["label"], "message": f"🔴 {key_data['label']} — {key_data['pct']}% folosit ({key_data['remaining']} rămase)."})
                elif ks == "warning":
                    alerts.append({"level": "warning", "icon": "🟡", "provider": prov_data["name"], "key_label": key_data["label"], "message": f"🟡 {key_data['label']} — {key_data['pct']}% folosit ({key_data['remaining']} rămase)."})
        return alerts

    def summary_line(self, provider):
        key_def = self._get_active_key(provider)
        prov = PROVIDERS.get(provider)
        if not prov: return f"❓ {provider}: unknown"
        if not key_def: return f"⛔ {prov['name']}: toate cheile epuizate"
        used = key_def["used"]; limit = key_def["limit"]; pct = used / limit if limit > 0 else 0.0
        if pct >= CRITICAL_THRESHOLD: icon = "🔴"
        elif pct >= WARN_THRESHOLD: icon = "🟡"
        else: icon = "🟢"
        return f"{icon} {prov['name']}: {used}/{limit} req ({limit-used} rămase) [{key_def['label']}]"

    def add_key(self, provider, key, limit, label):
        prov = PROVIDERS.get(provider)
        if not prov: return False
        for kd in prov["keys"]:
            if kd["key"] == key: return False
        prov["keys"].append({"key": key, "limit": limit, "label": label})
        if provider in self._exhausted: self._exhausted[provider].discard(key)
        return True

    def reset_month(self):
        self._usage = {"month": date.today().strftime("%Y-%m"), "providers": {}}
        self._exhausted = {}
        self._save_usage()

_km_instance = None

def get_key_manager():
    global _km_instance
    if _km_instance is None:
        _km_instance = APIKeyManager()
    return _km_instance
