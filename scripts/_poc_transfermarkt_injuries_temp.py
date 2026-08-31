"""
================================================================================
UDAL — POC_TRANSFERMARKT_INJURIES (izolat, temporar, GitHub Actions)
================================================================================
POC izolat, temporar — verifică LIVE dacă Transfermarkt e o sursă viabilă
de accidentări/suspendări, cu valoare de piață inclusă (câmpul care lipsea
la Flashscore, vezi CLAUDE.md, ADR-070 §gol aliniamente, 2026-08-30).

Semnal de pornire, NU dovadă: proiecte open-source publice
(`felipeall/transfermarkt-api`) extrag date Transfermarkt cu `requests`
simplu + un singur header User-Agent, fără proxy/retry/stealth — sugerează
protecție ușoară, spre deosebire de SofaScore (Akamai, blocat 14/14+4/4,
verificat live pe 2026-08-30). Nu se importă acel cod — doar tiparul de
URL confirmat structural (`{feature}/verein/{id}`) e refolosit ca punct
de pornire pentru propria cerere onestă.

Regulă strictă, identică precedentelor (SofaScore, Flashscore): NU se
încearcă nicio ocolire a protecției anti-bot — fără header-e care pretind
a fi un browser real (proiectul de referință folosește un User-Agent Chrome
fals; NU se copiază aici, deliberat — User-Agent-ul de mai jos se
identifică onest ca cercetare izolată). Dacă situl respinge cererea
onestă, răspunsul e "blocat" — se raportează exact așa, nu se ocolește.

Descoperire, nu presupunere: cluburile de testat se extrag din pagina
reală a Premier League (link-uri reale găsite pe pagină), nu din ID-uri
ghicite. Pentru fiecare club, se caută link-ul real „Injuries"/„Sperren
und Verletzungen" pe pagina lui, apoi se vizitează și se inspectează
conținutul pentru date structurate reale (nume, motiv, valoare de piață).

Nu importă `key_manager.py`/`scraper_registry.py`/orice modul de
producție. NU scrie nicăieri în Supabase. Rulează DOAR pe
`workflow_dispatch` manual. Se șterge din cod după închiderea
investigației (tiparul stabilit) — dovada rămâne în istoricul rulării
GitHub Actions + CLAUDE.md.
================================================================================
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

EVIDENCE_DIR = root / "docs" / "06_UDAL" / "poc_evidence" / "transfermarkt_injuries"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Onest, auto-identificat — NU imită un browser real (fără Chrome UA).
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FootballOracleUDAL-POC/1.0; "
                  "isolated architecture-validation research, single run, "
                  "see docs/06_UDAL/ in source repo)",
}
_POLITE_DELAY_SECONDS = 3.0
_TIMEOUT_S = 20

_PREMIER_LEAGUE_URL = "https://www.transfermarkt.com/premier-league/startseite/wettbewerb/GB1"
_CLUBS_TO_TEST = 3

# Semnale de blocare — identice cu cele verificate deja pentru alte surse.
_BLOCK_MARKERS = (
    "checking your browser", "attention required", "captcha-delivery",
    "access denied", "ray id", "sorry, you have been blocked",
    "just a moment...", "verify you are human", "unusual traffic",
    "please verify you are a human", "forbidden",
)

# Semnale textuale ca pagina de club chiar contine link spre accidentari/
# suspendari — cautate in href-uri, nu presupuse ca format fix.
_INJURY_LINK_PATTERNS = [
    r"sperrenundverletzungen", r"injuries", r"verletzungen",
]


def _get(url: str) -> tuple[int | None, str | None, float]:
    import requests
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        latency_ms = (time.perf_counter() - t0) * 1000
        return resp.status_code, resp.text, latency_ms
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return None, f"EXCEPTION: {exc}", latency_ms


def _looks_blocked(body: str | None) -> str | None:
    if not body:
        return None
    lower = body.lower()
    for marker in _BLOCK_MARKERS:
        if marker in lower:
            return marker
    return None


def _save_evidence(label: str, body: str) -> None:
    safe_name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:120]
    (EVIDENCE_DIR / f"{safe_name}_raw.html").write_text(body, encoding="utf-8")


def _discover_clubs_from_premier_league() -> list[dict]:
    """Extrage link-uri REALE de club din pagina reală a Premier League —
    nu ID-uri ghicite. `href`-urile Transfermarkt pentru club au forma
    `/<slug>/startseite/verein/<id>` — extrase prin regex pe HTML brut
    (fără BeautifulSoup, ca să nu adaug o dependență nouă pentru un POC
    temporar)."""
    status, body, latency = _get(_PREMIER_LEAGUE_URL)
    entry = {"label": "premier_league_hub", "url": _PREMIER_LEAGUE_URL,
              "status": status, "latency_ms": round(latency, 1),
              "body_length": len(body) if body else 0}
    if status == 200 and body:
        _save_evidence("premier_league_hub", body)
        entry["blocked_marker"] = _looks_blocked(body)
    elif body:
        entry["error_body_excerpt"] = body[:300]

    clubs: list[dict] = []
    if status == 200 and body and not entry.get("blocked_marker"):
        seen_ids: set[str] = set()
        for m in re.finditer(r'href="(/([a-z0-9-]+)/startseite/verein/(\d+))"', body):
            path, slug, club_id = m.group(1), m.group(2), m.group(3)
            if club_id in seen_ids:
                continue
            seen_ids.add(club_id)
            clubs.append({"slug": slug, "club_id": club_id,
                           "profile_url": f"https://www.transfermarkt.com{path}"})
            if len(clubs) >= _CLUBS_TO_TEST:
                break
    return {"discovery_check": entry, "clubs": clubs}


def _check_club_injuries(club: dict) -> dict:
    result: dict = {"club": club}

    # Pas 1 — pagina de profil a clubului, cauta link real spre accidentari.
    status, body, latency = _get(club["profile_url"])
    profile_entry = {"status": status, "latency_ms": round(latency, 1),
                      "body_length": len(body) if body else 0}
    if status == 200 and body:
        _save_evidence(f"{club['slug']}_profile", body)
        profile_entry["blocked_marker"] = _looks_blocked(body)
        found_links = set()
        for pat in _INJURY_LINK_PATTERNS:
            for m in re.finditer(rf'href="([^"]*{pat}[^"]*)"', body, re.IGNORECASE):
                href = m.group(1)
                full = href if href.startswith("http") else f"https://www.transfermarkt.com{href}"
                found_links.add(full)
        profile_entry["injury_links_found_on_page"] = sorted(found_links)
    elif body:
        profile_entry["error_body_excerpt"] = body[:300]
    result["profile_page"] = profile_entry

    # Pas 2 — daca s-a gasit un link real, il vizitam si verificam continutul.
    injury_links = profile_entry.get("injury_links_found_on_page") or []
    # Fallback structural — DOAR daca pagina de profil n-a expus niciun link
    # (posibil randat prin JS) — tiparul e confirmat structural (nu ghicit
    # orbeste), vezi docstring modul.
    if not injury_links:
        injury_links = [
            f"https://www.transfermarkt.com/{club['slug']}/sperrenundverletzungen/verein/{club['club_id']}",
        ]
        profile_entry["fallback_url_used"] = True

    injury_checks = []
    for link in injury_links[:2]:
        time.sleep(_POLITE_DELAY_SECONDS)
        i_status, i_body, i_latency = _get(link)
        entry = {"url": link, "status": i_status, "latency_ms": round(i_latency, 1),
                  "body_length": len(i_body) if i_body else 0}
        if i_status == 200 and i_body:
            _save_evidence(f"{club['slug']}_injuries", i_body)
            entry["blocked_marker"] = _looks_blocked(i_body)
            # Semnal de continut real: tabel cu nume de jucatori + o coloana
            # de "Market value" — exact campul care lipsea la Flashscore.
            entry["has_market_value_column"] = bool(
                re.search(r"market\s*value", i_body, re.IGNORECASE),
            )
            entry["injury_keyword_hits"] = len(
                re.findall(r"injury|injured|suspension|suspended", i_body, re.IGNORECASE),
            )
        elif i_body:
            entry["error_body_excerpt"] = i_body[:300]
        injury_checks.append(entry)
    result["injury_page_checks"] = injury_checks
    return result


def run() -> dict:
    result: dict = {"run_at": datetime.now(timezone.utc).isoformat()}

    discovery = _discover_clubs_from_premier_league()
    result["discovery"] = discovery

    clubs = discovery.get("clubs") or []
    club_results = []
    for club in clubs:
        time.sleep(_POLITE_DELAY_SECONDS)
        club_results.append(_check_club_injuries(club))
    result["clubs_checked"] = club_results

    result["summary"] = {
        "clubs_discovered": len(clubs),
        "clubs_with_any_200_injury_page": sum(
            1 for c in club_results
            if any(chk.get("status") == 200 and not chk.get("blocked_marker")
                   for chk in c.get("injury_page_checks", []))
        ),
        "clubs_with_market_value_on_injury_page": sum(
            1 for c in club_results
            if any(chk.get("has_market_value_column") for chk in c.get("injury_page_checks", []))
        ),
    }
    return result


if __name__ == "__main__":
    output = run()
    report_path = EVIDENCE_DIR / "poc_transfermarkt_injuries_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
