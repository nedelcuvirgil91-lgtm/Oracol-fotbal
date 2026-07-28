"""
================================================================================
UDAL — POC_SCRAPER_SOURCE_01 (izolat, temporar, GitHub Actions)
================================================================================
POC izolat, temporar — prima verificare LIVE reală pentru UDAL, per
instrucțiune explicită a proprietarului produsului ("Pasul 1: Folosește
WorldFootball... Pasul 2:... continuă cu SofaScore"). Rulează DOAR pe
`workflow_dispatch` manual, niciodată pe schedule/push repetat — o
recurență automată ar contrazice spiritul gate-ului `tos_reviewed` (o
sursă neaprobată nu trebuie accesată repetat, automat, fără supraveghere).

Nu importă `scraper_registry.py`/`scraper_adapter_base.py` — NU trece
prin gate-ul de producție (`tos_reviewed`), exact tiparul altor POC-uri
izolate din acest proiect (ex. `poc_api_football_league_lookup.py`) —
un POC de verificare explicit aprobat de proprietarul produsului nu e
"producție", nu se preface că e.

Reutilizează STRICT `udal_extraction.py` (extractor generic, neatins) —
nu duplică logica de parsare. Scrie rezultate + HTML/JSON brut ca dovadă
în `docs/06_UDAL/poc_evidence/` — workflow-ul le comite înapoi (log
download rămâne blocat în mediul de dezvoltare curent, tiparul deja
stabilit în această sesiune pentru POC-uri live).

NU scrie nicăieri în Supabase, NU atinge `match_history` sau orice
tabelă canonică — pur informativ, evidență locală comisă în repo.
================================================================================
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

EVIDENCE_DIR = root / "docs" / "06_UDAL" / "poc_evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FootballOracleUDAL-POC/1.0; "
                  "isolated architecture-validation research, single run, "
                  "see docs/06_UDAL/ in source repo)",
}
_POLITE_DELAY_SECONDS = 2.0


def _get(url: str, timeout: int = 20) -> tuple[int | None, str | None, float]:
    import requests
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        latency_ms = (time.perf_counter() - t0) * 1000
        return resp.status_code, resp.text, latency_ms
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return None, f"EXCEPTION: {exc}", latency_ms


# ════════════════════════════════════════════════════════════════════════════
# PASUL 1 — WorldFootball
# ════════════════════════════════════════════════════════════════════════════

def run_worldfootball() -> dict:
    from bs4 import BeautifulSoup
    from udal_extraction import CSS_RESOLVER, extract

    result: dict = {"source": "worldfootball", "calls": []}

    hub_url = "https://www.worldfootball.net/competition/co66/romania-liga-1/"
    status, html, latency = _get(hub_url)
    result["calls"].append({"url": hub_url, "status": status, "latency_ms": round(latency, 1)})
    if status != 200 or not html:
        result["error"] = "hub_page_fetch_failed"
        return result
    (EVIDENCE_DIR / "worldfootball_hub_raw.html").write_text(html, encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    report_links = sorted({
        a["href"] for a in soup.find_all("a", href=True) if "/report/" in a["href"]
    })
    result["report_links_found"] = len(report_links)
    result["report_links_sample"] = report_links[:5]

    if not report_links:
        result["error"] = "no_report_links_found_on_hub_page"
        return result

    time.sleep(_POLITE_DELAY_SECONDS)
    match_url = report_links[0]
    if match_url.startswith("/"):
        match_url = "https://www.worldfootball.net" + match_url
    status2, html2, latency2 = _get(match_url)
    result["calls"].append({"url": match_url, "status": status2, "latency_ms": round(latency2, 1)})
    if status2 != 200 or not html2:
        result["error"] = "match_report_fetch_failed"
        return result
    (EVIDENCE_DIR / "worldfootball_match_report_raw.html").write_text(html2, encoding="utf-8")

    match_soup = BeautifulSoup(html2, "html.parser")

    # Strategie robusta 1: <title> - de obicei stabil chiar daca CSS-ul se
    # schimba ("TeamA - TeamB 2:1 - Liga 1 2025/2026 - worldfootball.net").
    title_text = match_soup.title.get_text(strip=True) if match_soup.title else None

    # Strategie robusta 2: cautare eticheta text (Referee/Attendance),
    # fara sa presupunem o clasa CSS anume.
    page_text = match_soup.get_text(" ", strip=True)
    referee_match = re.search(r"Referee:?\s*([A-Za-zÀ-ž.\-\s]{3,40})", page_text)
    attendance_match = re.search(r"Attendance:?\s*([\d.,]{2,10})", page_text)

    # Strategie 3: harta CSS din Faza 1.5 (worldfootball_extraction_map.json)
    # - ghicita, neconfirmata pe pagina reala, incercata oricum, cost zero.
    faza1_5_map_path = root / "docs" / "06_UDAL" / "site_configs" / "worldfootball_extraction_map.json"
    faza1_5_map = json.loads(faza1_5_map_path.read_text(encoding="utf-8"))
    faza1_5_map.pop("extraction_type", None)
    css_extraction = extract(match_soup, faza1_5_map, CSS_RESOLVER)

    result["extracted"] = {
        "title_tag": title_text,
        "referee_via_text_search": referee_match.group(1).strip() if referee_match else None,
        "attendance_via_text_search": attendance_match.group(1).strip() if attendance_match else None,
        "css_selector_map_faza1_5_result": css_extraction,
    }
    result["match_url"] = match_url
    return result


# ════════════════════════════════════════════════════════════════════════════
# PASUL 2 — SofaScore (API JSON neoficiala)
# ════════════════════════════════════════════════════════════════════════════

def run_sofascore() -> dict:
    result: dict = {"source": "sofascore", "calls": []}

    found_event: dict | None = None
    checked_dates: list[str] = []
    today = datetime.now(timezone.utc).date()
    for days_back in range(1, 15):
        target_date = (today - timedelta(days=days_back)).isoformat()
        checked_dates.append(target_date)
        url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{target_date}"
        status, body, latency = _get(url)
        result["calls"].append({"url": url, "status": status, "latency_ms": round(latency, 1)})
        if status == 200 and body:
            try:
                payload = json.loads(body)
            except Exception:
                payload = None
            if payload:
                for ev in payload.get("events", []):
                    tname = ((ev.get("tournament") or {}).get("name") or "")
                    if "Liga I" in tname or "Liga 1" in tname or "Romania" in tname:
                        found_event = ev
                        break
        if found_event:
            break
        time.sleep(_POLITE_DELAY_SECONDS)

    result["dates_checked"] = checked_dates
    if not found_event:
        result["error"] = "no_romania_liga_1_event_found_in_checked_window"
        return result

    (EVIDENCE_DIR / "sofascore_scheduled_event_raw.json").write_text(
        json.dumps(found_event, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    event_id = found_event.get("id")
    result["event_id"] = event_id
    result["event_summary"] = {
        "home": (found_event.get("homeTeam") or {}).get("name"),
        "away": (found_event.get("awayTeam") or {}).get("name"),
        "tournament": (found_event.get("tournament") or {}).get("name"),
        "status": ((found_event.get("status") or {}).get("description")),
    }

    time.sleep(_POLITE_DELAY_SECONDS)
    stats_url = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
    status_s, body_s, latency_s = _get(stats_url)
    result["calls"].append({"url": stats_url, "status": status_s, "latency_ms": round(latency_s, 1)})
    stats_payload = None
    if status_s == 200 and body_s:
        try:
            stats_payload = json.loads(body_s)
            (EVIDENCE_DIR / "sofascore_statistics_raw.json").write_text(
                json.dumps(stats_payload, indent=2, ensure_ascii=False), encoding="utf-8",
            )
        except Exception:
            pass

    time.sleep(_POLITE_DELAY_SECONDS)
    lineups_url = f"https://api.sofascore.com/api/v1/event/{event_id}/lineups"
    status_l, body_l, latency_l = _get(lineups_url)
    result["calls"].append({"url": lineups_url, "status": status_l, "latency_ms": round(latency_l, 1)})
    lineups_payload = None
    if status_l == 200 and body_l:
        try:
            lineups_payload = json.loads(body_l)
            (EVIDENCE_DIR / "sofascore_lineups_raw.json").write_text(
                json.dumps(lineups_payload, indent=2, ensure_ascii=False), encoding="utf-8",
            )
        except Exception:
            pass

    result["statistics_endpoint_ok"] = stats_payload is not None
    result["lineups_endpoint_ok"] = lineups_payload is not None
    result["statistics_top_level_keys"] = list(stats_payload.keys()) if stats_payload else None
    result["lineups_top_level_keys"] = list(lineups_payload.keys()) if lineups_payload else None

    return result


if __name__ == "__main__":
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "worldfootball": run_worldfootball(),
    }
    time.sleep(_POLITE_DELAY_SECONDS)
    output["sofascore"] = run_sofascore()

    report_path = EVIDENCE_DIR / "poc_scraper_source_01_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
