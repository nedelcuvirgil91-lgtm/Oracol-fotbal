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
# Header-e standard, complete — NU pretind identitate, doar completeaza o
# cerere HTTP normala (orice client bine format le trimite; absenta lor
# in cererea minimala anterioara ar putea fi cauza reala a raspunsului
# 202 gol, nu neaparat User-Agent-ul - se testeaza separat, nu se
# presupune care e cauza).
_STANDARD_HEADERS = {
    **_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}
_POLITE_DELAY_SECONDS = 3.0
_TIMEOUT_S = 20

_PREMIER_LEAGUE_URL = "https://www.transfermarkt.com/premier-league/startseite/wettbewerb/GB1"
_PREMIER_LEAGUE_URL_US = "https://www.transfermarkt.us/premier-league/startseite/wettbewerb/GB1"
_HOMEPAGE_URL = "https://www.transfermarkt.com/"
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


def _get(url: str, headers: dict | None = None) -> tuple[int | None, str | None, float, dict]:
    """`headers=None` -> User-Agent onest implicit (`_HEADERS`).
    `headers={}` -> DELIBERAT explicit, fara niciun header custom (testeaza
    User-Agent-ul implicit al bibliotecii `requests`, nu al lui `_HEADERS`)
    — distincția None-vs-{} contează aici, `{} or _HEADERS` ar fi cazut
    silențios pe `_HEADERS` (dict gol e falsy în Python)."""
    import requests
    t0 = time.perf_counter()
    effective_headers = _HEADERS if headers is None else headers
    try:
        resp = requests.get(url, headers=effective_headers, timeout=_TIMEOUT_S)
        latency_ms = (time.perf_counter() - t0) * 1000
        return resp.status_code, resp.text, latency_ms, dict(resp.headers)
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return None, f"EXCEPTION: {exc}", latency_ms, {}


def _looks_blocked(body: str | None) -> str | None:
    if not body:
        return None
    lower = body.lower()
    for marker in _BLOCK_MARKERS:
        if marker in lower:
            return marker
    return None


def _diagnose_202_empty() -> list[dict]:
    """[ADAUGAT — a 2-a trecere] Prima rulare a primit HTTP 202, corp GOL,
    pe cererea minimală (un singur header User-Agent onest). Nu se
    presupune cauza (User-Agent? domeniu? header-e lipsă?) — se testează
    fiecare variabilă separat, onest (fără impersonare de browser), și se
    raportează exact ce diferă. Niciuna din variantele de mai jos pretinde
    o identitate falsă — doar completează cererea (header-e standard) sau
    testează un domeniu alternativ REAL, deja documentat structural
    (`transfermarkt.us`, folosit chiar de proiectul open-source de
    referință)."""
    variants = [
        ("com_minimal_ua", _PREMIER_LEAGUE_URL, _HEADERS),
        ("com_standard_headers", _PREMIER_LEAGUE_URL, _STANDARD_HEADERS),
        ("com_default_requests_ua", _PREMIER_LEAGUE_URL, None),
        ("us_minimal_ua", _PREMIER_LEAGUE_URL_US, _HEADERS),
        ("us_standard_headers", _PREMIER_LEAGUE_URL_US, _STANDARD_HEADERS),
        ("com_homepage_minimal_ua", _HOMEPAGE_URL, _HEADERS),
    ]
    results = []
    for label, url, headers in variants:
        time.sleep(_POLITE_DELAY_SECONDS)
        status, body, latency, resp_headers = _get(url, headers=headers if headers else {})
        entry = {
            "label": label, "url": url,
            "headers_sent": headers if headers else "requests-default",
            "status": status, "latency_ms": round(latency, 1),
            "body_length": len(body) if body else 0,
            "response_headers": resp_headers,
        }
        if body and status == 200:
            _save_evidence(f"diagnose_{label}", body)
            entry["blocked_marker"] = _looks_blocked(body)
        elif body and (status != 200 or not resp_headers.get("Content-Length") == "0"):
            entry["body_excerpt"] = body[:300]
        results.append(entry)
    return results


def _save_evidence(label: str, body: str) -> None:
    safe_name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:120]
    (EVIDENCE_DIR / f"{safe_name}_raw.html").write_text(body, encoding="utf-8")


def _pick_working_variant(diagnostics: list[dict]) -> dict | None:
    """Alege prima variantă care a întors o pagină reală (200, corp
    nevid, fără marcaj de blocare) — nu presupune care e cea corectă,
    citește rezultatele diagnosticului."""
    for d in diagnostics:
        if d.get("status") == 200 and d.get("body_length", 0) > 1000 and not d.get("blocked_marker"):
            return d
    return None


def _discover_clubs(base_url: str, headers: dict) -> dict:
    """Extrage link-uri REALE de club din pagina reală a Premier League —
    nu ID-uri ghicite. `href`-urile Transfermarkt pentru club au forma
    `/<slug>/startseite/verein/<id>` — extrase prin regex pe HTML brut
    (fără BeautifulSoup, ca să nu adaug o dependență nouă pentru un POC
    temporar)."""
    status, body, latency, resp_headers = _get(base_url, headers=headers)
    entry = {"label": "premier_league_hub", "url": base_url,
              "status": status, "latency_ms": round(latency, 1),
              "body_length": len(body) if body else 0}
    if status == 200 and body:
        _save_evidence("premier_league_hub", body)
        entry["blocked_marker"] = _looks_blocked(body)
    elif body:
        entry["error_body_excerpt"] = body[:300]

    domain_root = re.match(r"(https?://[^/]+)", base_url).group(1)
    clubs: list[dict] = []
    if status == 200 and body and not entry.get("blocked_marker"):
        seen_ids: set[str] = set()
        for m in re.finditer(r'href="(/([a-z0-9-]+)/startseite/verein/(\d+))"', body):
            path, slug, club_id = m.group(1), m.group(2), m.group(3)
            if club_id in seen_ids:
                continue
            seen_ids.add(club_id)
            clubs.append({"slug": slug, "club_id": club_id,
                           "profile_url": f"{domain_root}{path}"})
            if len(clubs) >= _CLUBS_TO_TEST:
                break
    return {"discovery_check": entry, "clubs": clubs, "domain_root": domain_root}


def _check_club_injuries(club: dict, headers: dict, domain_root: str) -> dict:
    result: dict = {"club": club}

    # Pas 1 — pagina de profil a clubului, cauta link real spre accidentari.
    status, body, latency, _ = _get(club["profile_url"], headers=headers)
    profile_entry = {"status": status, "latency_ms": round(latency, 1),
                      "body_length": len(body) if body else 0}
    if status == 200 and body:
        _save_evidence(f"{club['slug']}_profile", body)
        profile_entry["blocked_marker"] = _looks_blocked(body)
        found_links = set()
        for pat in _INJURY_LINK_PATTERNS:
            for m in re.finditer(rf'href="([^"]*{pat}[^"]*)"', body, re.IGNORECASE):
                href = m.group(1)
                full = href if href.startswith("http") else f"{domain_root}{href}"
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
            f"{domain_root}/{club['slug']}/sperrenundverletzungen/verein/{club['club_id']}",
        ]
        profile_entry["fallback_url_used"] = True

    injury_checks = []
    for link in injury_links[:2]:
        time.sleep(_POLITE_DELAY_SECONDS)
        i_status, i_body, i_latency, _ = _get(link, headers=headers)
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

    diagnostics = _diagnose_202_empty()
    result["diagnostics"] = diagnostics

    working = _pick_working_variant(diagnostics)
    result["working_variant"] = working["label"] if working else None
    if not working:
        result["summary"] = {
            "clubs_discovered": 0, "clubs_with_any_200_injury_page": 0,
            "clubs_with_market_value_on_injury_page": 0,
            "conclusion": "NICIO varianta onesta (header-e standard, domeniu .us, UA implicit "
                           "requests) nu a intors continut real - toate au primit acelasi tipar "
                           "de raspuns gol/blocat ca cererea minimala initiala.",
        }
        return result

    headers = working["headers_sent"] if isinstance(working["headers_sent"], dict) else {}
    domain_root = re.match(r"(https?://[^/]+)", working["url"]).group(1)

    time.sleep(_POLITE_DELAY_SECONDS)
    discovery = _discover_clubs(f"{domain_root}/premier-league/startseite/wettbewerb/GB1", headers)
    result["discovery"] = discovery

    clubs = discovery.get("clubs") or []
    club_results = []
    for club in clubs:
        time.sleep(_POLITE_DELAY_SECONDS)
        club_results.append(_check_club_injuries(club, headers, domain_root))
    result["clubs_checked"] = club_results

    result["summary"] = {
        "working_variant": working["label"],
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
