"""
================================================================================
FOOTBALL ORACLE — Flashscore Normalizer (R-Sync-FLASH-01, M0)
================================================================================
Module: providers/flashscore/normalizer.py

Extractie pe baza de ETICHETA (label-as-key), nu pozitionala — pattern
verificat direct in `gustavofariaa/FlashscoreScraping` (licenta permisiva,
The Unlicense — vezi review-ul din sesiunea anterioara),
`src/scraper/services/matches/index.js::extractMatchStatistics`/
`extractMatchInformation`: fiecare rand de statistica e un container
auto-descriptiv (`wcl-statistics` -> `wcl-statistics-category` = eticheta
reala + doua valori `wcl-statistics-value`, home inaintea etichetei, away
dupa — ordine DOAR in interiorul randului, niciodata globala pe pagina).
Motivul explicit pentru care e superior mapari pozitionale globale: robust
la reordonarea/adaugarea de randuri (eticheta e cheia, nu indexul),
auto-descriptiv. Confirmat empiric pe fixture-ul real (POC): widget-ul
"Top Stats" de pe Summary are EXACT 5 categorii (xG, posesie, sut-uri
totale, big chances, touches in opposition box) — NU 10, cum presupunea
designul initial. Corners/fouls/cards/offsides/saves NU au fost gasite in
niciun fixture capturat (traiesc probabil pe tab-ul dedicat "Stats",
niciodata capturat in POC) — DELIBERAT neincluse aici, nu ghicite.

Scope M0 (exact, verificat empiric, nu presupus):
  - match_history: home_team/away_team/kickoff_date (cheia naturala),
    referee, stadium, home/away_possession, home/away_shots,
    home/away_xg_actual, home/away_lineup (XI, din lineups.html).
  - player_match_stats: nume, numar tricou (rating DEFERRED - traieste
    doar in vederea Pitch, fara disambiguare home/away fiabila, vezi
    `_extract_roster_rows`).
  - match_events: DOAR substitutii (structura minut+jucator-iesit+jucator-
    intrat verificata curat; goluri/cartonase NU au minut vizibil in
    structura verificata — deferred, nu ghicit).

Fara retea live — functiile de mai jos primesc HTML deja citit (de
`adapter.py`, mode="fixture" azi, mode="live" dupa tos_reviewed).
================================================================================
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

# Eticheta reala (verificata pe fixture) -> perechea de coloane canonice
# match_history (migratiile 008/026/032). Doar campuri cu dovada directa.
STAT_LABEL_TO_FIELDS: dict[str, tuple[str, str]] = {
    "Expected goals (xG)": ("home_xg_actual", "away_xg_actual"),
    "Ball possession": ("home_possession", "away_possession"),
    "Total shots": ("home_shots", "away_shots"),
}

_DATETIME_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})")


def _parse_numeric(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().rstrip("%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_team_names(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Numele fiecarei echipe apare de 2 ori pe pagina (verificat empiric -
    header compact + header principal, aceeasi clasa) - dedup pastrand
    ordinea, NU doar primele 2 valori brute (bug real gasit prin testare
    directa pe fixture, nu presupus)."""
    raw = [
        el.get_text(strip=True)
        for el in soup.select(".participant__participantName.participant__overflow")
        if el.get_text(strip=True)
    ]
    seen: list[str] = []
    for name in raw:
        if not seen or seen[-1] != name:
            seen.append(name)
    home = seen[0] if len(seen) > 0 else None
    away = seen[1] if len(seen) > 1 else None
    return home, away


def _extract_kickoff_iso(soup: BeautifulSoup) -> str | None:
    el = soup.select_one(".duelParticipant__startTime")
    if el is None:
        return None
    m = _DATETIME_RE.search(el.get_text(" ", strip=True))
    if not m:
        return None
    day, month, year, hour, minute = m.groups()
    try:
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
    except ValueError:
        return None
    return dt.isoformat()


def _extract_labeled_stat_pairs(soup: BeautifulSoup) -> dict[str, tuple[str | None, str | None]]:
    """Un dict {eticheta_reala: (valoare_home, valoare_away)} — vezi
    docstring modul pentru justificarea tehnica a acestei abordari."""
    result: dict[str, tuple[str | None, str | None]] = {}
    for row in soup.select("[data-testid='wcl-statistics']"):
        category_el = row.select_one("[data-testid='wcl-statistics-category']")
        if category_el is None:
            continue
        label = category_el.get_text(strip=True)
        values = row.select("[data-testid='wcl-statistics-value']")
        home_val = values[0].get_text(strip=True) if len(values) > 0 else None
        away_val = values[1].get_text(strip=True) if len(values) > 1 else None
        result[label] = (home_val, away_val)
    return result


def _extract_labeled_info_pairs(soup: BeautifulSoup) -> dict[str, str | None]:
    """Pereche eticheta/valoare din wcl-summaryMatchInformation — copii
    directi alternand (labelWrapper, infoValue), acelasi pattern ca
    `extractMatchInformation` (FlashscoreScraping)."""
    container = soup.select_one("[data-testid='wcl-summaryMatchInformation']")
    if container is None:
        return {}
    children = [c for c in container.find_all("div", recursive=False)]
    result: dict[str, str | None] = {}
    for i in range(0, len(children) - 1, 2):
        label = children[i].get_text(" ", strip=True)
        value = children[i + 1].get_text(" ", strip=True)
        if label:
            result[label.rstrip(":") + ":"] = value or None
    return result


def normalize_match_statistics(pages: dict[str, str]) -> dict[str, Any]:
    """Forma acceptata de `upsert_match_canonical` (subset COALESCE-safe,
    scope M0 - vezi docstring modul)."""
    summary_html = pages.get("summary")
    if not summary_html:
        return {}
    soup = BeautifulSoup(summary_html, "html.parser")

    home_team, away_team = _extract_team_names(soup)
    kickoff_date = _extract_kickoff_iso(soup)
    info = _extract_labeled_info_pairs(soup)
    stats = _extract_labeled_stat_pairs(soup)

    result: dict[str, Any] = {
        "home_team": home_team,
        "away_team": away_team,
        "kickoff_date": kickoff_date,
        "referee": info.get("Referee:"),
        "stadium": info.get("Venue:"),
        "stats_source": "flashscore",
    }
    for label, (home_field, away_field) in STAT_LABEL_TO_FIELDS.items():
        home_val, away_val = stats.get(label, (None, None))
        result[home_field] = _parse_numeric(home_val)
        result[away_field] = _parse_numeric(away_val)

    lineups_html = pages.get("lineups")
    if lineups_html:
        lineup_soup = BeautifulSoup(lineups_html, "html.parser")
        result["home_lineup"], result["away_lineup"] = _extract_lineups(lineup_soup)

    return result


def _extract_roster_rows(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Rand per jucator, din vederea LISTA (`wcl-lineupsParticipantGeneral-
    left/right`) - fiecare element e deja per-jucator, side-ul e in
    testid-ul insusi (`-left`=home, `-right`=away), fara nevoie de
    container de echipa (bug real gasit prin testare: presupusesem un
    container per echipa, dar `-left`/`-right` apare pe FIECARE rand de
    jucator direct - 24 elemente `-left`, nu 1).

    NOTA scope M0: rating de jucator NU e inclus aici - traieste doar in
    vederea PITCH (`wcl-participantPitch`), care nu are o disambiguare
    home/away fiabila in structura (verificat - fara clasa/testid de
    parte in lantul de ancestori) - a lega rating-ul de jucator prin
    potrivire de nume intre cele doua vederi ar fi exact genul de
    implementare fragila cerut explicit sa evit. Deferred, nu ghicit."""
    rows: list[dict[str, Any]] = []
    for side, team in (("left", "home"), ("right", "away")):
        for row in soup.select(f"[data-testid='wcl-lineupsParticipantGeneral-{side}']"):
            # [ROBUSTETE] Wrapper-ul numelui e uneori <button> (jucator
            # fara profil), alteori <a href="/player/..."> (jucator cu
            # profil) - gasit prin testare pe 2 meciuri diferite, nu
            # presupus. Selectam DOAR pe baza de testid + forma
            # continutului (nu de tag-ul wrapper-ului): span[0]=numar
            # (mereu numeric), primul span ulterior care NU incepe cu
            # "(" (exclude marcaje de rol - "(G)"/"(C)") = numele.
            spans = row.select("[data-testid='wcl-scores-simple-text-01']")
            if not spans:
                continue
            number_text = spans[0].get_text(strip=True)
            name_text = next(
                (s.get_text(strip=True) for s in spans[1:]
                 if s.get_text(strip=True) and not s.get_text(strip=True).startswith("(")),
                None,
            )
            if not name_text:
                continue
            rows.append({
                "team": team,
                "player_name": name_text,
                "shirt_number": int(number_text) if number_text.isdigit() else None,
            })
    return rows


def _extract_lineups(soup: BeautifulSoup) -> tuple[list[dict], list[dict]]:
    rows = _extract_roster_rows(soup)
    home = [{"name": r["player_name"], "shirt_number": r["shirt_number"]} for r in rows if r["team"] == "home"]
    away = [{"name": r["player_name"], "shirt_number": r["shirt_number"]} for r in rows if r["team"] == "away"]
    return home, away


def normalize_player_match_stats(pages: dict[str, str], match_id: int) -> list[dict[str, Any]]:
    """Randuri `player_match_stats` (migratia 032) - nume + numar (scope
    M0; `rating` deferred, vezi `_extract_roster_rows`). `match_id` vine
    din rezultatul `persist()`-ului pentru match_history (id-ul rezolvat
    de `upsert_match_canonical`), nu se ghiceste aici."""
    lineups_html = pages.get("lineups")
    if not lineups_html:
        return []
    soup = BeautifulSoup(lineups_html, "html.parser")
    return [
        {
            "match_id": match_id,
            "team": row["team"],
            "player_name": row["player_name"],
            "shirt_number": row["shirt_number"],
            "source": "flashscore",
        }
        for row in _extract_roster_rows(soup)
    ]


def normalize_match_events(pages: dict[str, str], match_id: int) -> list[dict[str, Any]]:
    """Randuri `match_events` (migratia 032/033) - DOAR substitutii,
    scope M0 (vezi docstring modul - goluri/cartonase deferred, structura
    de minut neverificata curat)."""
    lineups_html = pages.get("lineups")
    if not lineups_html:
        return []
    soup = BeautifulSoup(lineups_html, "html.parser")
    events: list[dict[str, Any]] = []
    for side, team in (("left", "home"), ("right", "away")):
        for sub_el in soup.select(f"[data-testid='wcl-lineupsParticipantsSubstitution-{side}']"):
            player_out_el = sub_el.select_one("[data-testid='wcl-scores-simple-text-01']")
            player_in_el = sub_el.select_one(".wcl-subName_irp5W, [class*='wcl-subName']")
            minute_el = sub_el.select_one(".wcl-minute_sXwww, [class*='wcl-minute']")
            if not (player_out_el and player_in_el and minute_el):
                continue
            minute_text = minute_el.get_text(strip=True).rstrip("'")
            if not minute_text.isdigit():
                continue
            events.append({
                "match_id": match_id,
                "team": team,
                "minute": int(minute_text),
                "event_type": "substitution",
                "player_name": player_out_el.get_text(strip=True),
                "related_player_name": player_in_el.get_text(strip=True),
                "source": "flashscore",
            })
    return events


def normalize_upcoming_match(raw_record: dict) -> dict[str, Any]:
    """[Afara scope M0] Pre-Match Sync - fereastra 7 zile, upcoming_matches/
    upcoming_lineups/upcoming_match_features (design §3.5) - nu face parte
    din Critical Path M0-M4 (doar meciuri finalizate, capturate). Ramane
    neimplementat deliberat."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: afara scope M0 (Pre-Match Sync, nu Bootstrap/Night "
        "Sync pe meciuri finalizate) - vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
    )
