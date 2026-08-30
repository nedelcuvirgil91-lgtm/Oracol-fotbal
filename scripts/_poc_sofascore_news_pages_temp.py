"""
================================================================================
UDAL — POC_SOFASCORE_NEWS_PAGES (izolat, temporar, GitHub Actions)
================================================================================
POC izolat, temporar — verifică o suprafață SofaScore NEATINSĂ de
`_poc_scraper_source_01_temp.py` (care testa exclusiv `api.sofascore.com`,
blocat 14/14 cu HTTP 403, Akamai Bot Manager cu amprentare TLS, confirmat
independent de documentația comunității — vezi CLAUDE.md, cercetarea din
2026-08-30).

Ipoteza de verificat, NU presupusă: paginile editoriale de pe
`www.sofascore.com/news/...` (previzualizări de meci scrise de redacția
SofaScore, publicate cu zile înainte de fluier, conțin liste de
accidentări jucător-cu-jucător — confirmat prin căutare web, nu prin
API) ar putea fi servite diferit de endpoint-urile API și deci
accesibile fără protecția Akamai care blochează `api.sofascore.com`.

Regulă strictă, identică precedentului: NU se încearcă nicio ocolire a
protecției anti-bot — fără `curl_cffi`/amprentare TLS falsă, fără
rotație de identitate, fără header-e care pretind a fi un browser real.
User-Agent-ul de mai jos se identifică onest ca cercetare izolată. Dacă
site-ul respinge cererea onestă, răspunsul e "blocat" — se raportează
exact așa, nu se ocolește.

Nu importă `key_manager.py`/`scraper_registry.py`/orice modul de
producție — NU trece prin gate-ul `tos_reviewed`, exact tiparul altor
POC-uri izolate din acest proiect. NU scrie nicăieri în Supabase, NU
atinge `match_history` — pur informativ, evidență locală comisă în repo.
Rulează DOAR pe `workflow_dispatch` manual.

Se șterge din cod după închiderea investigației (același tipar ca
`poc_api_football_new_key_validation.py`, închis 2026-08-30) — dovada
rămâne în istoricul rulării GitHub Actions + CLAUDE.md.
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

EVIDENCE_DIR = root / "docs" / "06_UDAL" / "poc_evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Onest, auto-identificat — NU imită un browser real (fără Chrome UA, fără
# header-e Sec-Fetch/Accept-Language tipice unui browser). Exact opusul
# tehnicii `curl_cffi impersonate="chrome"` documentate ca ocolire Akamai.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FootballOracleUDAL-POC/1.0; "
                  "isolated architecture-validation research, single run, "
                  "see docs/06_UDAL/ in source repo)",
}
_POLITE_DELAY_SECONDS = 3.0

# URL-uri REALE, gasite prin cautare web (nu inventate) — trei previzualizari
# de meci publicate de redactia SofaScore, 2026-08-26..29, fiecare continand
# text de accidentari jucator-cu-jucator, cu zile inainte de fluier.
_KNOWN_PREVIEW_URLS = [
    "https://www.sofascore.com/news/real-madrid-vs-real-sociedad-preview-form-odds-and-key-picks",
    "https://www.sofascore.com/news/rb-leipzig-vs-borussia-mgladbach-preview-trends-lineups-and-odds",
    "https://www.sofascore.com/news/union-berlin-vs-eintracht-frankfurt-preview-h2h-form-and-players-to-watch",
]

_NEWS_HUB_URL = "https://www.sofascore.com/news"

# Semnale textuale simple ca pagina chiar contine continut de accidentari,
# nu doar ca a raspuns cu status 200 (un raspuns 200 cu o pagina de
# "verificare" JS-only ar fi la fel de inutil ca un 403).
_INJURY_SIGNAL_PATTERNS = [
    r"\binjury\b", r"\bout with\b", r"\bsidelined\b", r"\bunavailable\b",
    r"\bdoubtful\b", r"\bsuspend", r"\babsentee",
]


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


def _check_page(label: str, url: str) -> dict:
    status, body, latency = _get(url)
    entry: dict = {
        "label": label,
        "url": url,
        "status": status,
        "latency_ms": round(latency, 1),
        "body_length": len(body) if body else 0,
    }
    if status == 200 and body:
        safe_name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        (EVIDENCE_DIR / f"sofascore_news_{safe_name}_raw.html").write_text(body, encoding="utf-8")

        injury_hits = {
            pat: len(re.findall(pat, body, re.IGNORECASE)) for pat in _INJURY_SIGNAL_PATTERNS
        }
        entry["injury_signal_hits"] = {k: v for k, v in injury_hits.items() if v > 0}
        entry["has_injury_content"] = any(injury_hits.values())

        # Semnal de pagina de provocare (challenge) JS-only, care ar
        # intoarce 200 dar corp aproape gol / doar un loader — deosebit de
        # un raspuns 403 direct, dar la fel de inutil pentru extractie.
        entry["looks_like_js_challenge_shell"] = len(body) < 5000 and "sofascore" not in body.lower()
    elif body:
        entry["error_body_excerpt"] = body[:300]
    return entry


def run() -> dict:
    result: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "checks": []}

    result["checks"].append(_check_page("news_hub", _NEWS_HUB_URL))
    time.sleep(_POLITE_DELAY_SECONDS)

    for i, url in enumerate(_KNOWN_PREVIEW_URLS):
        if i > 0:
            time.sleep(_POLITE_DELAY_SECONDS)
        result["checks"].append(_check_page(f"preview_article_{i + 1}", url))

    result["summary"] = {
        "total_checks": len(result["checks"]),
        "ok_200_with_injury_content": sum(
            1 for c in result["checks"] if c.get("status") == 200 and c.get("has_injury_content")
        ),
        "ok_200_no_injury_content": sum(
            1 for c in result["checks"]
            if c.get("status") == 200 and not c.get("has_injury_content")
        ),
        "blocked_non_200": sum(
            1 for c in result["checks"] if c.get("status") != 200
        ),
    }
    return result


if __name__ == "__main__":
    output = run()
    report_path = EVIDENCE_DIR / "poc_sofascore_news_pages_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
