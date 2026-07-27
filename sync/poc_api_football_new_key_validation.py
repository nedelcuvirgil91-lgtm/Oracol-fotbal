"""
================================================================================
POC IZOLAT — validare cheie nouă API-Football (api-sports.io)
================================================================================
Etapa C, Regula 1 (chei API = infrastructură critică) — aprobată explicit,
2026-07-27, cu ajustările din runda a doua de aprobare (protecție de log,
banner de audit, raport comparativ pe 7 dimensiuni). Pașii 1-4 din procesul
de migrare obligatoriu: adaugă cheia nouă ca secret SEPARAT, validează
autentificarea, validează endpoint-urile, compară răspunsurile cu ce
așteaptă codul de producție azi.

Interdicții explicite, respectate structural (verificate de
`tests/test_poc_api_football_new_key_validation.py`, gărzi AST):
  - NU importă `key_manager` — nu poate atinge `PROVIDERS["apifootball"]`.
  - NU importă `football_providers` — nu poate atinge providerul activ.
  - NU citește NICIODATĂ variabila de mediu `API_FOOTBALL_KEY` (cea veche) —
    doar `API_FOOTBALL_KEY_NEW`.
  - NU e importat de niciun cod de producție (tipar `poc_*`, deja stabilit).
  - NU scrie nimic în cache/Supabase — doar stdout, pentru inspecție manuală.
  - Rulează DOAR manual (`workflow_dispatch`) — niciun alt trigger.

Regula 2 (zero regresii funcționale) — comparația NU se face contra unui
apel live pe cheia veche (ar consuma-o, interzis) — se face contra formei
STATICE așteptate de parserul de producție (`football_providers.py`,
citat exact, cu linia sursă) și contra faptelor deja documentate despre
cheia veche în auditul Frozen (`docs/03_ENGINE/
API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md`) — nu o a doua sursă de adevăr
paralelă, obținută printr-un apel interzis.

Buget: plan Free, 100 cereri/zi — tratat ca resursă limitată, nu ca resursă
de test. Plafon dur implicit 5 apeluri per rulare (`--max-calls`), niciodată
depășit peste `_HARD_CEILING`, indiferent de argumentul primit.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

logger = logging.getLogger("FootballOracle.POC.ApiFootballNewKey")

BASE_URL = "https://v3.football.api-sports.io"
HEADER_KEY_NAME = "x-apisports-key"
NEW_KEY_ENV_VAR = "API_FOOTBALL_KEY_NEW"
_HARD_CEILING = 20  # niciodată depășit, indiferent de --max-calls

POC_MODE_BANNER = (
    "POC MODE\n"
    "NO PRODUCTION CODE TOUCHED\n"
    "OLD API KEY NOT READ\n"
    "NEW API KEY ONLY"
)

# Fapte documentate despre cheia VECHE — sursă statică (audit Frozen), NU un
# apel live (interzis, ar consuma cheia veche). Orice comparație de plan/
# cotă de mai jos e făcută contra acestor valori, nu contra unui răspuns nou.
OLD_KEY_DOCUMENTED_FACTS = {
    "plan": "Free (api-sports.io)",
    "daily_limit": 100,
    "per_minute_limit": 10,
    "host": "v3.football.api-sports.io",
    "header": HEADER_KEY_NAME,
    "source": "docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md §5, §13",
}

# Catalog static (subset relevant) — din același audit Frozen, §1/§3 — folosit
# doar pentru raportare ("ce mai există, ce NU testează acest POC"), nu
# declanșează apeluri suplimentare fără aprobare separată.
ENDPOINT_CATALOG = {
    "status":              {"tested_by_default": True,  "dw_value": "reconciliere cotă — fără valoare de date"},
    "teams":                {"tested_by_default": True,  "dw_value": "rezolvare ID echipă — deja activ în producție (R-Sync-2)"},
    "injuries":             {"tested_by_default": True,  "dw_value": "Team Health — deja activ în producție (R-Sync-2)"},
    "coachs":               {"tested_by_default": True,  "dw_value": "Team Health — deja activ în producție (R-Sync-2)"},
    "fixtures/statistics":  {"tested_by_default": False, "dw_value": "Match Statistics — golul central Etapa A (home_shots/corners doar 6.5% populate) — NETESTAT în acest POC"},
    "fixtures/lineups":     {"tested_by_default": False, "dw_value": "Lineups — domeniu neconstruit — NETESTAT"},
    "standings":            {"tested_by_default": False, "dw_value": "P3, doar cu dovadă de valoare ML — NETESTAT"},
}


def _get_new_key() -> str | None:
    """Singurul punct de citire a cheii noi — DOAR API_FOOTBALL_KEY_NEW,
    niciodată API_FOOTBALL_KEY (cea veche, neatinsă de acest fișier)."""
    key = os.environ.get(NEW_KEY_ENV_VAR, "").strip()
    return key or None


def print_poc_mode_banner() -> None:
    """Item 2 din aprobare — confirmare instant-vizibilă în orice log că
    aceasta e o rulare izolată, nu o cale de producție."""
    print("\n" + "=" * 78)
    print(POC_MODE_BANNER)
    print("=" * 78 + "\n")


def print_audit_banner() -> None:
    """Item 3 din aprobare — afișat ÎNAINTE de primul apel real, nu pentru
    funcționalitate, pentru audit."""
    print("Provider:")
    print("  API-Football NEW\n")
    print("Environment variable:")
    print(f"  {NEW_KEY_ENV_VAR}\n")
    print("Production provider:")
    print("  UNTOUCHED\n")
    print("Old key:")
    print("  NOT READ\n")


class CallBudget:
    """Contor explicit, dur — fiecare apel logat cu motiv, niciodată tăcut."""

    def __init__(self, max_calls: int):
        self.max_calls = min(max(0, max_calls), _HARD_CEILING)
        self.used = 0
        self.log: list[str] = []

    def can_call(self) -> bool:
        return self.used < self.max_calls

    def record(self, endpoint: str, reason: str) -> None:
        self.used += 1
        entry = f"apel #{self.used}/{self.max_calls}: GET {endpoint} — motiv: {reason}"
        self.log.append(entry)
        logger.info("[NewKeyPOC] %s", entry)


def _make_session():
    from requests import Session
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    s = Session()
    r = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
               allowed_methods=["GET"], raise_on_status=False)
    a = HTTPAdapter(max_retries=r)
    s.mount("https://", a)
    return s


def _call(session, key: str, budget: CallBudget, path: str, params: dict, reason: str) -> dict:
    """Întoarce {"payload": dict|None, "latency_ms": float}."""
    if not budget.can_call():
        logger.warning("[NewKeyPOC] plafon de apeluri atins (%d/%d) — sar peste %s",
                        budget.used, budget.max_calls, path)
        return {"payload": None, "latency_ms": None}
    budget.record(path, reason)
    headers = {HEADER_KEY_NAME: key}
    start = time.monotonic()
    payload = None
    try:
        resp = session.get(f"{BASE_URL}/{path}", headers=headers, params=params, timeout=12)
        if resp.ok:
            try:
                payload = resp.json()
            except Exception as exc:
                logger.error("[NewKeyPOC] răspuns non-JSON pentru %s: %s", path, exc)
        else:
            logger.warning("[NewKeyPOC] HTTP %s pentru %s — body: %s", resp.status_code, path, resp.text[:500])
    except Exception as exc:
        logger.error("[NewKeyPOC] eroare request %s: %s", path, exc)
    latency_ms = (time.monotonic() - start) * 1000
    return {"payload": payload, "latency_ms": round(latency_ms, 1)}


# ════════════════════════════════════════════════════════════════════════════
# Comparație structurală PURĂ (fără I/O) — forma așteptată e citată exact din
# football_providers.py, nu presupusă din nou aici.
# ════════════════════════════════════════════════════════════════════════════

def compare_status_shape(payload: dict | None) -> list[str]:
    if payload is None:
        return ["/status — niciun răspuns (eroare de rețea sau auth)"]
    issues = []
    if "response" not in payload:
        issues.append("/status — lipsește cheia 'response' de nivel superior")
        return issues
    resp = payload.get("response") or {}
    if "requests" not in resp:
        issues.append("/status — lipsește 'response.requests' (contor cotă)")
    if "subscription" not in resp:
        issues.append("/status — lipsește 'response.subscription' (plan activ)")
    return issues


def compare_team_shape(payload: dict | None) -> list[str]:
    """Oglindă exactă a `ApiFootballProvider.resolve_team_id()`,
    football_providers.py:245-280 — 'team.id' e singurul câmp de care
    depinde azi codul de producție."""
    if payload is None:
        return ["/teams — niciun răspuns (eroare de rețea sau auth)"]
    issues = []
    response = payload.get("response")
    if not response:
        issues.append("/teams — 'response' lipsă sau gol (echipa nu s-a găsit)")
        return issues
    first = response[0]
    if not isinstance(first, dict):
        issues.append(f"/teams — primul element din 'response' nu e dict: {first!r}")
        return issues
    team_obj = first.get("team") or {}
    if team_obj.get("id") is None:
        issues.append("/teams — 'response[0].team.id' lipsă — resolve_team_id() ar întoarce None")
    if team_obj.get("name") is None:
        issues.append("/teams — 'response[0].team.name' lipsă (folosit doar informativ, nu blocant)")
    return issues


def compare_injury_shape(payload: dict | None) -> list[str]:
    """Oglindă exactă a `_normalize_injury()`, football_providers.py:306-328."""
    if payload is None:
        return ["/injuries — niciun răspuns (eroare de rețea sau auth)"]
    issues = []
    if "response" not in payload:
        issues.append("/injuries — lipsește cheia 'response' de nivel superior")
        if payload.get("errors"):
            issues.append(f"/injuries — 'errors' populat: {payload['errors']!r}")
        return issues
    for idx, item in enumerate(payload["response"] or []):
        if not isinstance(item, dict):
            issues.append(f"/injuries — response[{idx}] nu e dict: {item!r}")
            continue
        player = item.get("player") or {}
        injury_type = item.get("type") or player.get("type")
        reason = item.get("reason") or player.get("reason")
        if injury_type is None and reason is None:
            issues.append(f"/injuries — response[{idx}]: nici 'type' nici 'reason' găsite "
                           "(nici la nivel de item, nici sub 'player') — parserul ar produce "
                           "'necunoscut' pentru ambele")
    return issues


def compare_coach_shape(payload: dict | None) -> list[str]:
    """Oglindă exactă a `_normalize_coach()`, football_providers.py:417-431."""
    if payload is None:
        return ["/coachs — niciun răspuns (eroare de rețea sau auth)"]
    issues = []
    if "response" not in payload:
        issues.append("/coachs — lipsește cheia 'response' de nivel superior")
        return issues
    for idx, item in enumerate(payload["response"] or []):
        if not isinstance(item, dict):
            issues.append(f"/coachs — response[{idx}] nu e dict: {item!r}")
            continue
        if item.get("id") is None:
            issues.append(f"/coachs — response[{idx}]: 'id' lipsă (parserul ar produce 'necunoscut')")
        if item.get("name") is None:
            issues.append(f"/coachs — response[{idx}]: 'name' lipsă (parserul ar produce 'necunoscut')")
        if "career" in item and not isinstance(item["career"], list):
            issues.append(f"/coachs — response[{idx}]: 'career' prezent dar nu e listă — "
                           "'appointed_date' nu s-ar putea deriva")
    return issues


def compare_plan_vs_old_key(status_payload: dict | None) -> dict:
    """Comparație STATICĂ contra documentației Frozen despre cheia veche —
    cheia veche NU e apelată de acest POC (Regula 1/2)."""
    if status_payload is None:
        return {"comparable": False, "reason": "niciun răspuns /status de la cheia nouă"}
    resp = status_payload.get("response") or {}
    requests_info = resp.get("requests") or {}
    subscription = resp.get("subscription") or {}
    new_daily_limit = requests_info.get("limit_day")

    differences = []
    if new_daily_limit is not None and new_daily_limit != OLD_KEY_DOCUMENTED_FACTS["daily_limit"]:
        differences.append(
            f"limita zilnică observată la cheia nouă ({new_daily_limit}) diferă de cea "
            f"documentată pentru cheia veche ({OLD_KEY_DOCUMENTED_FACTS['daily_limit']})"
        )

    return {
        "comparable": True,
        "old_key_documented": dict(OLD_KEY_DOCUMENTED_FACTS),
        "new_key_observed": {"plan": subscription.get("plan"), "daily_limit": new_daily_limit},
        "differences": differences,
        "note": "Comparație STATICĂ contra auditului Frozen — cheia veche nu a fost apelată din acest POC.",
    }


def estimate_data_warehouse_impact(checks: dict) -> str:
    """Rule-based, pe baza rezultatelor reale — nu o presupunere din faptul
    că cheia e nouă (regulă explicită, aprobată)."""
    core_checks = [name for name in ("status", "teams", "injuries", "coaches") if name in checks]
    core_ok = all(not checks[name]["issues"] for name in core_checks)
    if not core_ok:
        return (
            "Diferențe structurale găsite pe segmentul deja activ în producție (Team Health: "
            "/teams, /injuries, /coachs — R-Sync-2). Per Regula 2, cheia nouă NU poate deveni "
            "providerul principal până nu se rezolvă. Fără impact estimat asupra Data "
            "Warehouse-ului până la validare completă."
        )
    return (
        "Segmentul deja activ în producție (Team Health: /teams, /injuries, /coachs, R-Sync-2) "
        "e compatibil structural cu cheia nouă — echivalență demonstrată, nu presupusă. Acest "
        "POC NU testează /fixtures/statistics, /fixtures/lineups sau /standings — golurile reale "
        "ale Data Warehouse-ului azi, per Etapa A/B (`DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_2026-07-27.md`). "
        "Orice concluzie despre extinderea reală a Data Warehouse-ului cu această cheie necesită "
        "o probă separată, explicit aprobată, pe acele endpoint-uri, cu propriul buget de cereri."
    )


# ════════════════════════════════════════════════════════════════════════════
# Orchestrare — I/O, subțire, apelează doar funcțiile pure de mai sus
# ════════════════════════════════════════════════════════════════════════════

def run(team_name: str, max_calls: int) -> dict:
    print_poc_mode_banner()

    key = _get_new_key()
    if not key:
        logger.error("[NewKeyPOC] %s nu e setată — nimic de validat. "
                      "(NU citesc niciodată API_FOOTBALL_KEY, cea veche.)", NEW_KEY_ENV_VAR)
        return {"ok": False, "reason": f"{NEW_KEY_ENV_VAR} lipsă"}

    print_audit_banner()

    budget = CallBudget(max_calls)
    session = _make_session()
    report: dict = {"ok": True, "checks": {}, "call_log": []}

    status_result = _call(session, key, budget, "status", {}, "reconciliere cotă / validare auth")
    status_payload, status_latency = status_result["payload"], status_result["latency_ms"]
    status_issues = compare_status_shape(status_payload)
    report["checks"]["status"] = {"issues": status_issues, "raw_present": status_payload is not None,
                                   "latency_ms": status_latency}
    report["plan_comparison"] = compare_plan_vs_old_key(status_payload)

    if status_payload is None:
        # Autentificare eșuată — restul verificărilor n-ar avea sens.
        report["ok"] = False
        report["call_log"] = budget.log
        report["endpoints_tested"] = ["status"]
        logger.error("[NewKeyPOC] AUTENTIFICARE EȘUATĂ — cheia nouă nu răspunde la /status.")
        return report

    team_result = _call(session, key, budget, "teams", {"search": team_name},
                         f"rezolvare ID echipă test ('{team_name}')")
    team_payload, team_latency = team_result["payload"], team_result["latency_ms"]
    team_issues = compare_team_shape(team_payload)
    report["checks"]["teams"] = {"issues": team_issues, "raw_present": team_payload is not None,
                                  "latency_ms": team_latency}

    team_id = None
    if team_payload and team_payload.get("response"):
        first = team_payload["response"][0]
        if isinstance(first, dict):
            team_id = (first.get("team") or {}).get("id")

    endpoints_tested = ["status", "teams"]

    if team_id is not None:
        from datetime import date as _date
        season = _date.today().year

        injuries_result = _call(session, key, budget, "injuries", {"team": team_id, "season": season},
                                 f"validare formă /injuries pt echipa test (id={team_id})")
        injuries_payload, injuries_latency = injuries_result["payload"], injuries_result["latency_ms"]
        injuries_issues = compare_injury_shape(injuries_payload)
        report["checks"]["injuries"] = {"issues": injuries_issues, "raw_present": injuries_payload is not None,
                                         "latency_ms": injuries_latency}
        endpoints_tested.append("injuries")

        coaches_result = _call(session, key, budget, "coachs", {"team": team_id},
                                f"validare formă /coachs pt echipa test (id={team_id})")
        coaches_payload, coaches_latency = coaches_result["payload"], coaches_result["latency_ms"]
        coaches_issues = compare_coach_shape(coaches_payload)
        report["checks"]["coaches"] = {"issues": coaches_issues, "raw_present": coaches_payload is not None,
                                        "latency_ms": coaches_latency}
        endpoints_tested.append("coachs")
    else:
        logger.warning("[NewKeyPOC] team_id nu s-a rezolvat — /injuries și /coachs sărite (nimic de testat).")

    all_issues = [issue for check in report["checks"].values() for issue in check["issues"]]
    report["ok"] = len(all_issues) == 0
    report["call_log"] = budget.log
    report["endpoints_tested"] = endpoints_tested
    report["endpoints_catalog"] = ENDPOINT_CATALOG
    report["data_warehouse_impact_estimate"] = estimate_data_warehouse_impact(report["checks"])
    return report


def render_report(report: dict) -> str:
    lines = []
    lines.append("=" * 78)
    lines.append("RAPORT COMPARATIV — cheie nouă API-Football (izolat, cheie veche neatinsă)")
    lines.append("=" * 78)

    lines.append("\n1. AUTENTIFICARE")
    status_check = report.get("checks", {}).get("status")
    if status_check is None:
        lines.append(f"   EȘUATĂ — {report.get('reason', 'motiv necunoscut')}")
    elif status_check["raw_present"] and not status_check["issues"]:
        lines.append("   OK — /status a răspuns cu forma așteptată")
    else:
        lines.append("   PROBLEMĂ — vezi secțiunea 3 (structură răspuns)")

    lines.append("\n2. LATENȚĂ (ms, per endpoint)")
    for name, check in report.get("checks", {}).items():
        lines.append(f"   {name}: {check.get('latency_ms')}")

    lines.append("\n3. STRUCTURĂ RĂSPUNS / 4. COMPATIBILITATE CU ADAPTOARELE EXISTENTE")
    for name, check in report.get("checks", {}).items():
        status = "COMPATIBIL" if not check["issues"] else "DIFERENȚE GĂSITE"
        lines.append(f"   [{name}] {status}")
        for issue in check["issues"]:
            lines.append(f"       - {issue}")

    lines.append("\n5. ENDPOINT-URI DISPONIBILE")
    tested = set(report.get("endpoints_tested", []))
    for ep, meta in report.get("endpoints_catalog", ENDPOINT_CATALOG).items():
        marker = "testat în această rulare" if ep in tested else "NETESTAT"
        lines.append(f"   {ep} — {marker} — {meta['dw_value']}")

    lines.append("\n6. DIFERENȚE FAȚĂ DE PROVIDERUL VECHI")
    plan_cmp = report.get("plan_comparison", {})
    if not plan_cmp.get("comparable"):
        lines.append(f"   Necomparabil — {plan_cmp.get('reason', 'fără date')}")
    else:
        lines.append(f"   Cheie veche (documentat, {plan_cmp['old_key_documented']['source']}): "
                      f"{plan_cmp['old_key_documented']['daily_limit']}/zi, "
                      f"{plan_cmp['old_key_documented']['per_minute_limit']}/min, "
                      f"plan {plan_cmp['old_key_documented']['plan']}")
        lines.append(f"   Cheie nouă (observat live): {plan_cmp['new_key_observed']}")
        if plan_cmp["differences"]:
            for d in plan_cmp["differences"]:
                lines.append(f"       - {d}")
        else:
            lines.append("       - nicio diferență găsită față de ce e documentat pentru cheia veche")

    lines.append("\n7. IMPACT ESTIMAT ASUPRA DATA WAREHOUSE")
    lines.append(f"   {report.get('data_warehouse_impact_estimate', 'n/a — autentificare eșuată')}")

    lines.append("\n" + "-" * 78)
    if report.get("ok"):
        lines.append("VERDICT: PASS — nicio diferență structurală pe segmentul testat.")
        lines.append("Notă: PASS NU înseamnă 'activează cheia nouă' — doar compatibilitate")
        lines.append("structurală pe ce s-a testat azi. Decizia de integrare rămâne separată,")
        lines.append("per Regula 1 (aprobare explicită, pas cu pas).")
    else:
        lines.append("VERDICT: FAIL / auth eșuată — cheia nouă NU devine activă (Regula 2).")
    lines.append("=" * 78)
    return "\n".join(lines)


def _cli() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", default="Arsenal", help="Echipă de test pentru rezolvare ID (implicit: Arsenal)")
    parser.add_argument("--max-calls", type=int, default=5,
                         help=f"Plafon apeluri live (implicit 5, niciodată peste {_HARD_CEILING})")
    args = parser.parse_args()

    report = run(args.team, args.max_calls)

    for line in report.get("call_log", []):
        print(f"  {line}")

    print(render_report(report))
    print("\n" + json.dumps(report, indent=2, ensure_ascii=False, default=str))

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
