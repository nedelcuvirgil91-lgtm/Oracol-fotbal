"""
================================================================================
FOOTBALL ORACLE — Diagnostic: sondaj API-Football /fixtures/statistics
================================================================================
Module: diagnostics_api_football.py

Discovery & Instrumentation — NU integrare. Verifică, cu apeluri HTTP reale
complet instrumentate, dacă /fixtures/statistics există pe planul nostru
API-Football, ce câmpuri livrează efectiv (posesie, șuturi, șuturi pe poartă,
cornere, cartonașe, faulturi, xG) și cu ce cod HTTP/mesaj răspunde dacă nu.

Complet izolat de Prediction Engine: nu e importat din oracle_engine.py, nu
scrie în match_history, nu atinge FEATURE_COLUMNS/ML/Learning Core. Singurele
efecte laterale sunt apeluri HTTP reale (contorizate prin key_manager, ca
orice alt apel API-Football) + cache prin CacheManager (L1 disc + L2
Supabase, aceeași infrastructură ADR-003 folosită peste tot în proiect) —
zero scriere în match_history sau alt tabel de producție.

[OPTIMIZARE QUOTA — v2] Selecția de ligă e mereu manuală (nu mai există
"implicit toate"). team_id e cache-uit sub aceeași cheie/categorie folosită
de ApiFootballProvider.resolve_team_id() ("teams", TTL 30 zile) — reutilizează
direct cache-ul deja populat de producție, dacă există. Ultimul fixture jucat
de echipă e cache-uit separat (categoria "api_football_probe", TTL 24h). Dacă
ultimul verdict pe /fixtures/statistics pentru un fixture a fost 403/404,
verdictul e cache-uit 24h — testul NU se repetă (0 apeluri). Rezultat: o
verificare completă, prima dată, costă până la 3 apeluri; orice verificare
ulterioară, în aceeași fereastră de cache, costă 1 apel (sau 0, dacă răspunsul
anterior a fost 403/404) — nu 3 de fiecare dată.

Unde vezi rezultatul primei rulări reale (rețeaua din sandbox-ul Claude Code
e blocată, nu poate rula de aici):
  1. GitHub Actions — workflow_dispatch "Football Oracle — Probă API-Football
     Statistics" (.github/workflows/poc_api_football_statistics.yml) — logul
     rulării.
  2. Diagnostics (Streamlit, tab Setări) — selectează o ligă, buton dedicat,
     NU rulează automat (costă quota reală, comună cu injuries/coaches).

[NOTĂ DE INCERTITUDINE] IMPORTANT_FIELDS de mai jos mapează pe structura
documentată public pentru API-Football v3 (statistics[].type) — NEverificată
live cu cheia noastră, fiindcă acest mediu nu are acces la rețea externă.
Parsarea e defensivă peste tot: dacă structura reală diferă de ce e presupus
aici, raportul spune explicit "structură neașteptată" + arată excerpt-ul brut,
nu inventează niciodată un câmp găsit.
================================================================================
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from cache_manager import get_cache
from football_providers import ApiFootballProvider
from key_manager import get_key_manager

BASE_URL = ApiFootballProvider.BASE_URL

# Un singur reprezentant per ligă — suficient pentru proba TEHNICĂ a
# endpoint-ului (există? ce plan? ce câmpuri?), NU o garanție exhaustivă de
# acoperire per ligă. Competițiile continentale/cupe (Champions League, Europa
# League, Conference League, World Cup 2026) nu sunt probate direct aici:
# "ultimul meci al echipei" nu se poate lega sigur de o competiție specifică
# fără o rezolvare suplimentară de league_id, pe care API-Football nu ne-o dă
# azi (mappings.LEAGUE_PROVIDERS are api_football=None peste tot). Dacă proba
# domestică pentru o echipă participantă reușește, e un indiciu puternic
# (nu o dovadă) că același plan acoperă și competiția continentală.
PROBE_TEAMS: dict[str, str] = {
    "Premier League":   "Arsenal",
    "La Liga":           "Real Madrid",
    "Serie A":            "Juventus",
    "Bundesliga":         "Bayern Munich",
    "Ligue 1":            "Paris Saint-Germain",
    "Romania SuperLiga":  "FCSB",
    "MLS":                "Inter Miami",
}

# label canonic -> alias-uri posibile ale câmpului "type" din statistics[]
# (potrivire "conține", case-insensitive). Sursă: documentația publică
# API-Football v3 — vezi nota de incertitudine din docstring-ul modulului.
IMPORTANT_FIELDS: dict[str, list[str]] = {
    "possession":       ["ball possession"],
    "shots":             ["total shots"],
    "shots_on_target":   ["shots on goal"],
    "corners":           ["corner kicks"],
    "yellow_cards":      ["yellow cards"],
    "red_cards":         ["red cards"],
    "fouls":             ["fouls"],
    "xG":                ["expected_goals", "expected goals"],
}

RAW_EXCERPT_MAX_CHARS = 2000

# Verdictele /fixtures/statistics pentru care merită cache-uit rezultatul (nu
# doar datele) — un plan care nu include endpoint-ul nu se schimbă de pe-o zi
# pe alta; repetarea aceluiași test cu același răspuns risipește quota.
_CACHEABLE_HTTP_STATUSES = (403, 404)


@dataclass
class HttpProbe:
    """Instrumentare brută a UNUI singur apel HTTP — status, timp, mesaj de
    eroare (al API-ului, dacă există), body trunchiat pentru afișare. Nimic
    interpretat aici — interpretarea se face separat, peste aceste date."""
    url:               str
    http_status:       int | None
    ok:                bool
    latency_ms:        float
    error_message:     str = ""
    raw_body_excerpt:  str = ""
    parsed:            dict | list | None = None  # NEtrunchiat — folosit pt. logică


@dataclass
class FieldCheck:
    label:             str
    found:             bool
    matched_raw_type:  str | None = None


@dataclass
class LeagueProbeResult:
    league:                     str
    team_name:                  str
    team_id:                    int | None = None
    resolve_team_probe:         HttpProbe | None = None
    fixture_lookup_probe:       HttpProbe | None = None
    statistics_probe:           HttpProbe | None = None
    team_id_from_cache:         bool = False
    fixture_id_from_cache:      bool = False
    statistics_result_from_cache: bool = False
    fixture_id:                 int | None = None
    home_team:                  str = ""
    away_team:                  str = ""
    fixture_date:                str = ""
    field_checks:                list[FieldCheck] = field(default_factory=list)
    all_raw_types_found:         list[str] = field(default_factory=list)
    verdict:                     str = "necunoscut"
    verdict_detail:              str = ""


@dataclass
class ProbeReport:
    generated_at:  str
    quota_note:    str
    leagues:       list[LeagueProbeResult] = field(default_factory=list)


def _http_get(path: str, params: dict, headers: dict | None, timeout: float = 12.0) -> HttpProbe:
    url = f"{BASE_URL}/{path}"
    start = time.monotonic()
    try:
        r = requests.get(url, headers=headers or {}, params=params, timeout=timeout)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        parsed = None
        api_error_msg = ""
        try:
            parsed = r.json()
            if isinstance(parsed, dict):
                errs = parsed.get("errors")
                if errs:
                    api_error_msg = "; ".join(f"{k}: {v}" for k, v in errs.items()) if isinstance(errs, dict) else str(errs)
        except ValueError:
            parsed = None
        return HttpProbe(
            url=url, http_status=r.status_code, ok=r.ok, latency_ms=latency_ms,
            error_message=api_error_msg,
            raw_body_excerpt=(r.text or "")[:RAW_EXCERPT_MAX_CHARS],
            parsed=parsed,
        )
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return HttpProbe(url=url, http_status=None, ok=False, latency_ms=latency_ms,
                          error_message=str(exc))


def _match_important_fields(raw_types: list[str]) -> list[FieldCheck]:
    lowered = [(t, t.lower()) for t in raw_types]
    checks: list[FieldCheck] = []
    for label, aliases in IMPORTANT_FIELDS.items():
        matched = None
        for raw, low in lowered:
            if any(alias in low for alias in aliases):
                matched = raw
                break
        checks.append(FieldCheck(label=label, found=matched is not None, matched_raw_type=matched))
    return checks


def _team_cache_key(team_name: str) -> str:
    # IDENTIC cu ApiFootballProvider.resolve_team_id() — reutilizează/
    # alimentează același cache de producție (categoria "teams").
    return f"team_id:{team_name.strip().lower()}"


def _extract_team_id(parsed: dict | None) -> int | None:
    if not isinstance(parsed, dict):
        return None
    resp_list = parsed.get("response") or []
    if not resp_list or not isinstance(resp_list[0], dict):
        return None
    team_id = (resp_list[0].get("team") or {}).get("id")
    try:
        return int(team_id) if team_id is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_team_id(team_name: str, headers: dict, km, cache) -> tuple[int | None, HttpProbe | None, bool]:
    """Întoarce (team_id, probe folosit sau None dacă a venit din cache, din_cache)."""
    cache_key = _team_cache_key(team_name)
    cached_raw = cache.get_raw("teams", cache_key) if cache else None
    if cached_raw is not None:
        return _extract_team_id(cached_raw), None, True

    probe = _http_get("teams", {"search": team_name}, headers)
    km.record_request("apifootball")
    if not probe.ok:
        return None, probe, False
    if cache and isinstance(probe.parsed, dict) and probe.parsed.get("response"):
        cache.set("teams", cache_key, probe.parsed, provider="apifootball")
    return _extract_team_id(probe.parsed), probe, False


def _fixture_cache_key(team_id: int) -> str:
    return f"last_fixture:{team_id}"


def _resolve_last_fixture(team_id: int, headers: dict, km, cache) -> tuple[dict | None, HttpProbe | None, bool]:
    """Întoarce (info fixture sau None, probe folosit sau None dacă a venit
    din cache, din_cache). info: {fixture_id, home_team, away_team, fixture_date}."""
    cache_key = _fixture_cache_key(team_id)
    cached = cache.get_raw("api_football_probe", cache_key) if cache else None
    if cached is not None:
        return cached, None, True

    probe = _http_get("fixtures", {"team": team_id, "last": 1}, headers)
    km.record_request("apifootball")
    if not probe.ok:
        return None, probe, False

    info = None
    if isinstance(probe.parsed, dict):
        resp_list = probe.parsed.get("response") or []
        if resp_list and isinstance(resp_list[0], dict):
            fx = resp_list[0]
            fixture_id = (fx.get("fixture") or {}).get("id")
            teams_block = fx.get("teams") or {}
            if fixture_id is not None:
                info = {
                    "fixture_id": fixture_id,
                    "home_team": (teams_block.get("home") or {}).get("name", ""),
                    "away_team": (teams_block.get("away") or {}).get("name", ""),
                    "fixture_date": (fx.get("fixture") or {}).get("date", ""),
                }
    if info and cache:
        cache.set("api_football_probe", cache_key, info, provider="apifootball")
    return info, probe, False


def _statistics_verdict_cache_key(fixture_id: int) -> str:
    return f"statistics_verdict:{fixture_id}"


def probe_league(league: str, team_name: str, key_manager=None, cache=None) -> LeagueProbeResult:
    """Sondaj real, complet instrumentat, pentru O SINGURĂ ligă/echipă
    reprezentativă. Fiecare pas se oprește onest dacă cel anterior eșuează —
    nu inventează date pentru pașii următori. team_id/fixture_id/verdictele
    403-404 sunt cache-uite — vezi nota de optimizare din docstring-ul
    modulului."""
    km = key_manager or get_key_manager()
    cache = cache if cache is not None else get_cache()
    result = LeagueProbeResult(league=league, team_name=team_name)

    if not km.is_available("apifootball"):
        result.verdict = "fara_cheie"
        result.verdict_detail = "Nicio cheie API-Football activă în key_manager."
        return result

    headers = km.get_headers("apifootball")

    # Pas 1 — team_id (cache 30 zile, comun cu producția).
    team_id, probe1, from_cache1 = _resolve_team_id(team_name, headers, km, cache)
    result.resolve_team_probe = probe1
    result.team_id_from_cache = from_cache1
    if probe1 is not None and not probe1.ok:
        result.verdict = "resolve_team_esuat"
        result.verdict_detail = f"HTTP {probe1.http_status or 'eroare rețea'}." + (f" {probe1.error_message}" if probe1.error_message else "")
        return result
    if not team_id:
        result.verdict = "team_id_negasit"
        result.verdict_detail = "Niciun team.id găsit (live sau din cache)."
        return result
    result.team_id = team_id

    # Pas 2 — ultimul fixture jucat de echipă (cache 24h).
    fixture_info, probe2, from_cache2 = _resolve_last_fixture(team_id, headers, km, cache)
    result.fixture_lookup_probe = probe2
    result.fixture_id_from_cache = from_cache2
    if probe2 is not None and not probe2.ok:
        result.verdict = "fixture_lookup_esuat"
        result.verdict_detail = f"HTTP {probe2.http_status or 'eroare rețea'}." + (f" {probe2.error_message}" if probe2.error_message else "")
        return result
    if not fixture_info:
        result.verdict = "niciun_fixture_recent"
        result.verdict_detail = "Niciun meci recent găsit pentru echipă (live sau din cache)."
        return result

    fixture_id = fixture_info["fixture_id"]
    result.fixture_id = fixture_id
    result.home_team = fixture_info.get("home_team", "")
    result.away_team = fixture_info.get("away_team", "")
    result.fixture_date = fixture_info.get("fixture_date", "")

    # Pas 2.5 — verdict cache (doar 403/404): dacă știm deja că endpoint-ul
    # eșuează pentru acest fixture, NU repetăm apelul (0 apeluri suplimentare).
    verdict_key = _statistics_verdict_cache_key(fixture_id)
    cached_verdict = cache.get_raw("api_football_probe", verdict_key) if cache else None
    if cached_verdict is not None:
        result.verdict = cached_verdict.get("verdict", "necunoscut")
        result.verdict_detail = cached_verdict.get("verdict_detail", "") + " [rezultat din cache, TTL 24h — apelul NU s-a mai făcut]"
        result.statistics_probe = HttpProbe(
            url=f"{BASE_URL}/fixtures/statistics",
            http_status=cached_verdict.get("http_status"), ok=False,
            latency_ms=0.0, error_message=cached_verdict.get("error_message", ""),
        )
        result.statistics_result_from_cache = True
        return result

    # Pas 3 — statisticile fixture-ului. Ținta reală a sondajului, singurul
    # apel garantat la fiecare rulare (dacă pașii 1-2 sunt deja în cache).
    probe3 = _http_get("fixtures/statistics", {"fixture": fixture_id}, headers)
    result.statistics_probe = probe3
    km.record_request("apifootball")
    if not probe3.ok:
        result.verdict = "statistics_http_error"
        result.verdict_detail = f"HTTP {probe3.http_status or 'eroare rețea'}." + (f" {probe3.error_message}" if probe3.error_message else "")
        if cache and probe3.http_status in _CACHEABLE_HTTP_STATUSES:
            cache.set("api_football_probe", verdict_key, {
                "verdict": result.verdict, "verdict_detail": result.verdict_detail,
                "http_status": probe3.http_status, "error_message": probe3.error_message,
            }, provider="apifootball")
        return result

    if not isinstance(probe3.parsed, dict):
        result.verdict = "structura_neasteptata"
        result.verdict_detail = "Răspuns HTTP 200, dar body-ul nu e JSON obiect valid — vezi raw_body_excerpt."
        return result

    resp_list = probe3.parsed.get("response")
    if not isinstance(resp_list, list) or not resp_list:
        result.verdict = "statistici_goale"
        result.verdict_detail = "HTTP 200, dar 'response' e gol — posibil plan fără date de statistici pentru acest fixture, sau meci fără statistici colectate de provider."
        return result

    raw_types: list[str] = []
    for team_stats in resp_list:
        if not isinstance(team_stats, dict):
            continue
        for stat in (team_stats.get("statistics") or []):
            t = stat.get("type") if isinstance(stat, dict) else None
            if t and t not in raw_types:
                raw_types.append(t)

    if not raw_types:
        result.verdict = "structura_neasteptata"
        result.verdict_detail = "HTTP 200, 'response' non-gol, dar niciun 'statistics[].type' recunoscut — structura diferă de documentația publică folosită aici. Vezi raw_body_excerpt."
        return result

    result.all_raw_types_found = raw_types
    result.field_checks = _match_important_fields(raw_types)
    result.verdict = "ok"
    result.verdict_detail = f"{len(raw_types)} câmpuri brute găsite."
    return result


def run_probe(leagues: list[str], delay_seconds: float = 1.5) -> ProbeReport:
    """Rulează sondajul DOAR pe ligile date explicit — selecția e mereu
    manuală, nu mai există "implicit toate ligile" (optimizare de quota).
    delay_seconds — pauză între ligi, ca să nu lovim brusc quota zilnică."""
    km = get_key_manager()
    cache = get_cache()
    report = ProbeReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        quota_note=(
            "Plan API-Football gratuit — 100 request-uri/zi, comun cu injuries/coaches din producție. "
            "team_id (cache 30 zile) și fixture_id/verdict 403-404 (cache 24h) — o verificare repetată "
            "în aceeași fereastră costă 1 apel sau 0, nu 3."
        ),
    )
    for i, league in enumerate(leagues):
        team = PROBE_TEAMS.get(league)
        if not team:
            continue
        if i > 0:
            time.sleep(delay_seconds)
        report.leagues.append(probe_league(league, team, key_manager=km, cache=cache))
    return report


def format_report_text(report: ProbeReport) -> str:
    lines = [
        "=" * 70,
        "API-FOOTBALL — Sondaj /fixtures/statistics (Discovery, nu integrare)",
        "=" * 70,
        f"Generat: {report.generated_at}",
        f"Quota: {report.quota_note}",
        "",
    ]
    for r in report.leagues:
        cache_bits = []
        if r.team_id_from_cache: cache_bits.append("team_id din cache")
        if r.fixture_id_from_cache: cache_bits.append("fixture_id din cache")
        if r.statistics_result_from_cache: cache_bits.append("verdict din cache — 0 apeluri")
        cache_note = f"  [{', '.join(cache_bits)}]" if cache_bits else ""
        lines.append(f"League: {r.league}  (echipă probă: {r.team_name}){cache_note}")
        if r.fixture_id:
            date_short = r.fixture_date[:10] if r.fixture_date else "?"
            lines.append(f"Fixture: {r.home_team} vs {r.away_team} ({date_short})")
        stat_probe = r.statistics_probe
        if stat_probe:
            lines.append(f"HTTP: {stat_probe.http_status} ({stat_probe.latency_ms} ms)")
        if r.verdict == "ok":
            lines.append("Available fields:")
            for fc in r.field_checks:
                mark = "✓" if fc.found else "✗"
                extra = f'  ("{fc.matched_raw_type}")' if fc.matched_raw_type else ""
                lines.append(f"  {mark} {fc.label}{extra}")
            lines.append(f"Toate câmpurile brute găsite: {', '.join(r.all_raw_types_found)}")
        else:
            lines.append(f"Verdict: {r.verdict} — {r.verdict_detail}")
            for probe_name, probe in (("resolve_team", r.resolve_team_probe),
                                       ("fixture_lookup", r.fixture_lookup_probe),
                                       ("statistics", r.statistics_probe)):
                if probe is not None:
                    lines.append(f"  [{probe_name}] HTTP {probe.http_status} ({probe.latency_ms} ms) {probe.error_message}")
        lines.append("-" * 70)
    return "\n".join(lines)
