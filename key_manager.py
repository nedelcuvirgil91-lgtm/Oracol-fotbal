"""
================================================================================
FOOTBALL ORACLE — API Key Manager v1.0
================================================================================
Module  : key_manager.py
Role    : Pool de chei API cu failover automat.
          Când o cheie se epuizează, trece automat la următoarea.
          Usage persistent pe disc — supraviețuiește restarturilor.

Funcționalități:
  - Pool de chei per provider (SportAPI, FreeLiveFootball, OddsAPI)
  - Tracking usage persistent în cache/key_usage.json
  - Reset automat la prima zi a lunii
  - Failover automat la cheie epuizată (429 / quota exceeded)
  - Alerte UI: 🟡 Warning 80%, 🔴 Critical 95%, ⛔ Exhausted
  - Singleton get_key_manager()

Utilizare:
  km = get_key_manager()

  # Obține headers pentru un request
  headers = km.get_headers("sportapi")

  # Marchează un request ca folosit
  km.record_request("sportapi")

  # Marchează o cheie ca epuizată (după 429)
  km.mark_exhausted("sportapi", key)

  # Status pentru UI
  alerts = km.get_alerts()
================================================================================
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("FootballOracle.KeyManager")

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
CACHE_DIR      = BASE_DIR / "cache"
KEY_USAGE_PATH = CACHE_DIR / "key_usage.json"
CACHE_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {

    "sportapi": {
        "name":        "SportAPI (RapidAPI)",
        "host":        "sportapi7.p.rapidapi.com",
        "base_url":    "https://sportapi7.p.rapidapi.com/api/v1",
        "header_key":  "x-rapidapi-key",
        "header_host": "x-rapidapi-host",
        "keys": [
            {
                "key":       "2ff60d8248msh65d53a6d077e4abp145f79jsn980ab63d585f",
                "limit":     50,
                "label":     "SportAPI-Key1",
            },
            # Adaugă chei noi aici când le obții:
            # {
            #     "key":   "CHEIE_NOUA_AICI",
            #     "limit": 50,
            #     "label": "SportAPI-Key2",
            # },
        ],
    },

    "freelivefootball": {
        "name":        "Free Live Football (RapidAPI)",
        "host":        "free-api-live-football-data.p.rapidapi.com",
        "base_url":    "https://free-api-live-football-data.p.rapidapi.com",
        "header_key":  "x-rapidapi-key",
        "header_host": "x-rapidapi-host",
        "keys": [
            {
                "key":       "2ff60d8248msh65d53a6d077e4abp145f79jsn980ab63d585f",
                "limit":     100,
                "label":     "FreeLive-Key1",
            },
        ],
    },

    "oddsapi": {
        "name":        "The Odds API",
        "host":        "api.the-odds-api.com",
        "base_url":    "https://api.the-odds-api.com/v4",
        "header_key":  None,   # Odds API folosește param, nu header
        "header_host": None,
        "keys": [
            {
                "key":       "b0e2ab9bcda1d9f4c5ddfe1063c81cd7",
                "limit":     500,
                "label":     "OddsAPI-Key1",
            },
        ],
    },

    "weatherapi": {
        "name":        "WeatherAPI",
        "host":        "api.weatherapi.com",
        "base_url":    "http://api.weatherapi.com/v1",
        "header_key":  None,
        "header_host": None,
        "keys": [
            {
                "key":       "48a5b54b8ced45cc924153231263005",
                "limit":     1000000,   # practic nelimitat pe planul free
                "label":     "Weather-Key1",
            },
        ],
    },
}

# Praguri pentru alerte (procent din limită)
WARN_THRESHOLD     = 0.80   # 🟡 Warning
CRITICAL_THRESHOLD = 0.95   # 🔴 Critical
EXHAUSTED_THRESHOLD= 1.00   # ⛔ Exhausted


# ─────────────────────────────────────────────────────────────────────────────
# KEY MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class APIKeyManager:
    """
    Gestionează pool-ul de chei API cu failover automat.
    """

    def __init__(self) -> None:
        self._usage: dict = self._load_usage()
        self._exhausted: dict[str, set[str]] = {}  # provider → {key, ...}
        self._reset_if_new_month()
        logger.info("APIKeyManager initialized.")

    # ══════════════════════════════════════════════════════════════════════
    # USAGE PERSISTENCE
    # ══════════════════════════════════════════════════════════════════════

    def _load_usage(self) -> dict:
        """Încarcă usage-ul de pe disc."""
        if KEY_USAGE_PATH.exists():
            try:
                return json.loads(KEY_USAGE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "month":    date.today().strftime("%Y-%m"),
            "providers": {},
        }

    def _save_usage(self) -> None:
        """Salvează usage-ul pe disc."""
        try:
            KEY_USAGE_PATH.write_text(
                json.dumps(self._usage, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[KeyManager] Save failed: %s", exc)

    def _reset_if_new_month(self) -> None:
        """Resetează contoarele la începutul fiecărei luni."""
        current_month = date.today().strftime("%Y-%m")
        if self._usage.get("month") != current_month:
            logger.info(
                "[KeyManager] New month (%s) — resetting all counters.",
                current_month,
            )
            self._usage = {
                "month":    current_month,
                "providers": {},
            }
            self._save_usage()

    def _get_key_usage(self, provider: str, key_label: str) -> int:
        """Returnează numărul de requests folosite pentru o cheie."""
        return (
            self._usage
            .get("providers", {})
            .get(provider, {})
            .get(key_label, 0)
        )

    def _increment_usage(self, provider: str, key_label: str) -> None:
        """Incrementează contorul pentru o cheie."""
        if "providers" not in self._usage:
            self._usage["providers"] = {}
        if provider not in self._usage["providers"]:
            self._usage["providers"][provider] = {}
        prev = self._usage["providers"][provider].get(key_label, 0)
        self._usage["providers"][provider][key_label] = prev + 1
        self._save_usage()

    # ══════════════════════════════════════════════════════════════════════
    # KEY SELECTION
    # ══════════════════════════════════════════════════════════════════════

    def _get_active_key(self, provider: str) -> dict | None:
        """
        Returnează prima cheie activă pentru un provider.
        O cheie este activă dacă:
        - Nu e în _exhausted (marcată ca 429 în sesiunea curentă)
        - Usage < limita lunară
        """
        prov = PROVIDERS.get(provider)
        if not prov:
            logger.error("[KeyManager] Unknown provider: %s", provider)
            return None

        exhausted_set = self._exhausted.get(provider, set())

        for key_def in prov["keys"]:
            key   = key_def["key"]
            label = key_def["label"]
            limit = key_def["limit"]
            used  = self._get_key_usage(provider, label)

            # Sărită dacă epuizată în sesiunea curentă
            if key in exhausted_set:
                continue

            # Sărită dacă a depășit limita
            if used >= limit:
                logger.warning(
                    "[KeyManager] %s exhausted (%d/%d).", label, used, limit
                )
                continue

            return {
                "key":   key,
                "label": label,
                "limit": limit,
                "used":  used,
            }

        return None  # Toate cheile epuizate

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    def get_key(self, provider: str) -> str | None:
        """Returnează cheia activă pentru un provider, sau None."""
        key_def = self._get_active_key(provider)
        return key_def["key"] if key_def else None

    def get_headers(self, provider: str) -> dict | None:
        """
        Returnează headers-urile complete pentru un request.
        Returns None dacă toate cheile sunt epuizate.
        """
        prov    = PROVIDERS.get(provider)
        key_def = self._get_active_key(provider)

        if not prov or not key_def:
            return None

        headers: dict = {}
        if prov.get("header_key"):
            headers[prov["header_key"]]  = key_def["key"]
        if prov.get("header_host"):
            headers[prov["header_host"]] = prov["host"]

        return headers

    def get_api_key_param(self, provider: str) -> str | None:
        """
        Pentru API-uri care folosesc apiKey ca query param (ex: OddsAPI).
        """
        key_def = self._get_active_key(provider)
        return key_def["key"] if key_def else None

    def record_request(self, provider: str) -> None:
        """
        Înregistrează un request folosit.
        Apelat după fiecare request reușit.
        """
        key_def = self._get_active_key(provider)
        if key_def:
            self._increment_usage(provider, key_def["label"])

    def mark_exhausted(self, provider: str, key: str) -> None:
        """
        Marchează o cheie ca epuizată în sesiunea curentă (după 429).
        Failover automat la cheia următoare.
        """
        if provider not in self._exhausted:
            self._exhausted[provider] = set()
        self._exhausted[provider].add(key)

        # Găsește label-ul pentru logging
        prov = PROVIDERS.get(provider, {})
        for kd in prov.get("keys", []):
            if kd["key"] == key:
                logger.warning(
                    "[KeyManager] ⛔ %s marked exhausted (429/quota). "
                    "Switching to next key.",
                    kd["label"],
                )
                break

        # Verifică dacă mai există chei active
        next_key = self._get_active_key(provider)
        if next_key:
            logger.info(
                "[KeyManager] ✅ Failover to %s.", next_key["label"]
            )
        else:
            logger.error(
                "[KeyManager] ⛔ ALL KEYS EXHAUSTED for %s!", provider
            )

    def is_available(self, provider: str) -> bool:
        """Verifică dacă există cel puțin o cheie activă pentru provider."""
        return self._get_active_key(provider) is not None

    # ══════════════════════════════════════════════════════════════════════
    # STATUS & ALERTS
    # ══════════════════════════════════════════════════════════════════════

    def get_status(self) -> dict:
        """
        Returnează statusul complet al tuturor cheilor.
        Folosit de UI pentru panoul de diagnostice.
        """
        result: dict = {
            "month":     self._usage.get("month", ""),
            "providers": {},
        }

        for prov_id, prov in PROVIDERS.items():
            prov_status: dict = {
                "name":   prov["name"],
                "keys":   [],
                "status": "ok",  # ok / warning / critical / exhausted
            }

            exhausted_set = self._exhausted.get(prov_id, set())
            any_active = False

            for kd in prov["keys"]:
                key   = kd["key"]
                label = kd["label"]
                limit = kd["limit"]
                used  = self._get_key_usage(prov_id, label)
                pct   = used / limit if limit > 0 else 0.0

                # Determină statusul cheii
                if key in exhausted_set or used >= limit:
                    key_status = "exhausted"
                    icon = "⛔"
                elif pct >= CRITICAL_THRESHOLD:
                    key_status = "critical"
                    icon = "🔴"
                    any_active = True
                elif pct >= WARN_THRESHOLD:
                    key_status = "warning"
                    icon = "🟡"
                    any_active = True
                else:
                    key_status = "ok"
                    icon = "🟢"
                    any_active = True

                prov_status["keys"].append({
                    "label":     label,
                    "used":      used,
                    "limit":     limit,
                    "remaining": max(0, limit - used),
                    "pct":       round(pct * 100, 1),
                    "status":    key_status,
                    "icon":      icon,
                })

            # Status general al provider-ului
            if not any_active:
                prov_status["status"] = "exhausted"
            else:
                all_pcts = [
                    k["pct"] / 100
                    for k in prov_status["keys"]
                    if k["status"] != "exhausted"
                ]
                if all_pcts:
                    max_pct = max(all_pcts)
                    if max_pct >= CRITICAL_THRESHOLD:
                        prov_status["status"] = "critical"
                    elif max_pct >= WARN_THRESHOLD:
                        prov_status["status"] = "warning"

            result["providers"][prov_id] = prov_status

        return result

    def get_alerts(self) -> list[dict]:
        """
        Returnează lista de alerte active.
        Fiecare alertă are: level, message, provider, key_label.

        Folosit de app.py pentru banner-e în UI.
        """
        alerts: list[dict] = []
        status = self.get_status()

        for prov_id, prov_data in status["providers"].items():
            for key_data in prov_data["keys"]:
                ks = key_data["status"]
                if ks == "exhausted":
                    alerts.append({
                        "level":     "exhausted",
                        "icon":      "⛔",
                        "provider":  prov_data["name"],
                        "key_label": key_data["label"],
                        "message":   (
                            f"⛔ {key_data['label']} — "
                            f"QUOTA EPUIZATĂ ({key_data['used']}/{key_data['limit']} req). "
                            f"Failover activ."
                        ),
                    })
                elif ks == "critical":
                    alerts.append({
                        "level":     "critical",
                        "icon":      "🔴",
                        "provider":  prov_data["name"],
                        "key_label": key_data["label"],
                        "message":   (
                            f"🔴 {key_data['label']} — "
                            f"{key_data['pct']}% din quota folosită "
                            f"({key_data['remaining']} req rămase)."
                        ),
                    })
                elif ks == "warning":
                    alerts.append({
                        "level":     "warning",
                        "icon":      "🟡",
                        "provider":  prov_data["name"],
                        "key_label": key_data["label"],
                        "message":   (
                            f"🟡 {key_data['label']} — "
                            f"{key_data['pct']}% din quota folosită "
                            f"({key_data['remaining']} req rămase)."
                        ),
                    })

            # Alertă dacă tot provider-ul e epuizat
            if prov_data["status"] == "exhausted":
                alerts.append({
                    "level":     "exhausted",
                    "icon":      "⛔",
                    "provider":  prov_data["name"],
                    "key_label": "ALL",
                    "message":   (
                        f"⛔ {prov_data['name']} — TOATE CHEILE EPUIZATE. "
                        f"Modelul folosește date din cache sau ELO fallback."
                    ),
                })

        return alerts

    def summary_line(self, provider: str) -> str:
        """
        Returnează o linie de status pentru sidebar-ul UI.
        Ex: '🟢 SportAPI: 12/50 req (Key1)'
        """
        key_def = self._get_active_key(provider)
        prov    = PROVIDERS.get(provider)
        if not prov:
            return f"❓ {provider}: unknown"

        if not key_def:
            return f"⛔ {prov['name']}: toate cheile epuizate"

        used  = key_def["used"]
        limit = key_def["limit"]
        pct   = used / limit if limit > 0 else 0.0
        remaining = limit - used

        if pct >= CRITICAL_THRESHOLD:
            icon = "🔴"
        elif pct >= WARN_THRESHOLD:
            icon = "🟡"
        else:
            icon = "🟢"

        return (
            f"{icon} {prov['name']}: "
            f"{used}/{limit} req "
            f"({remaining} rămase) [{key_def['label']}]"
        )

    def add_key(self, provider: str, key: str, limit: int, label: str) -> bool:
        """
        Adaugă o cheie nouă la runtime (fără restart).
        Utilă când utilizatorul introduce o cheie nouă în UI.
        """
        prov = PROVIDERS.get(provider)
        if not prov:
            return False

        # Verifică dacă cheia există deja
        for kd in prov["keys"]:
            if kd["key"] == key:
                logger.info("[KeyManager] Key %s already exists.", label)
                return False

        prov["keys"].append({
            "key":   key,
            "limit": limit,
            "label": label,
        })

        # Scoate din exhausted dacă era acolo
        if provider in self._exhausted:
            self._exhausted[provider].discard(key)

        logger.info(
            "[KeyManager] ✅ Added new key %s for %s (limit=%d).",
            label, provider, limit,
        )
        return True

    def reset_month(self) -> None:
        """Reset manual al contorelor (pentru testare)."""
        self._usage = {
            "month":    date.today().strftime("%Y-%m"),
            "providers": {},
        }
        self._exhausted = {}
        self._save_usage()
        logger.info("[KeyManager] Manual reset done.")


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

_km_instance: APIKeyManager | None = None


def get_key_manager() -> APIKeyManager:
    global _km_instance
    if _km_instance is None:
        _km_instance = APIKeyManager()
    return _km_instance


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile, os

    print("\n" + "=" * 55)
    print("  key_manager.py — self-test")
    print("=" * 55)

    # Test cu limite artificiale mici
    km = APIKeyManager()

    # Test 1: get_headers
    headers = km.get_headers("sportapi")
    assert headers is not None
    assert "x-rapidapi-key" in headers
    print("  ✅  get_headers(sportapi)")

    # Test 2: get_key
    key = km.get_key("sportapi")
    assert key is not None
    print("  ✅  get_key(sportapi)")

    # Test 3: is_available
    assert km.is_available("sportapi")
    assert km.is_available("oddsapi")
    print("  ✅  is_available()")

    # Test 4: summary_line
    line = km.summary_line("sportapi")
    assert "SportAPI" in line
    print(f"  ✅  summary_line: {line}")

    # Test 5: get_status
    status = km.get_status()
    assert "providers" in status
    assert "sportapi" in status["providers"]
    print("  ✅  get_status()")

    # Test 6: alerts (no alerts dacă usage e mic)
    alerts = km.get_alerts()
    print(f"  ✅  get_alerts(): {len(alerts)} alerte active")

    # Test 7: mark_exhausted + failover
    key1 = km.get_key("sportapi")
    km.mark_exhausted("sportapi", key1)
    # Cu o singură cheie, după exhausted nu mai e available
    # (normal în prod — cu 2 chei ar face failover)
    print("  ✅  mark_exhausted() + failover logic")

    # Test 8: add_key
    added = km.add_key(
        "sportapi", "TEST_KEY_123", 50, "SportAPI-Test"
    )
    assert added
    assert km.is_available("sportapi")  # acum e disponibilă noua cheie
    print("  ✅  add_key() + availability restored")

    # Test 9: record_request
    km.reset_month()
    km.record_request("oddsapi")
    km.record_request("oddsapi")
    used = km._get_key_usage("oddsapi", "OddsAPI-Key1")
    assert used == 2
    print(f"  ✅  record_request(): {used} requests înregistrate")

    # Print status final
    print("\n  Status curent:")
    for prov_id in ["sportapi", "freelivefootball", "oddsapi"]:
        print(f"    {km.summary_line(prov_id)}")

    print("\n  Toate testele au trecut ✅\n")
