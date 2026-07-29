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

# Eticheta reala (verificata pe fixture-ul din tab-ul "Statistici",
# /summary/stats/) -> perechea de coloane canonice match_history
# (migratiile 008/026/032). Doar campuri cu dovada directa - extins la
# Foundation Data Layer (2026-07-29) cu cele 7 campuri gasite reale pe
# tab-ul dedicat, niciodata vizitat pana acum (corners/fouls/cards/
# offsides/saves/shots_on_target - toate au deja coloana in match_history).
STAT_LABEL_TO_FIELDS: dict[str, tuple[str, str]] = {
    "Expected goals (xG)": ("home_xg_actual", "away_xg_actual"),
    "Ball possession": ("home_possession", "away_possession"),
    "Total shots": ("home_shots", "away_shots"),
    "Shots on target": ("home_shots_on_target", "away_shots_on_target"),
    "Corner kicks": ("home_corners", "away_corners"),
    "Fouls": ("home_fouls", "away_fouls"),
    "Yellow cards": ("home_yellow_cards", "away_yellow_cards"),
    "Red cards": ("home_red_cards", "away_red_cards"),
    "Offsides": ("home_offsides", "away_offsides"),
    "Goalkeeper saves": ("home_goalkeeper_saves", "away_goalkeeper_saves"),
}

_DATETIME_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})")
_H2H_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})$")
_LEADING_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Vocabular REAL de pozitii Flashscore (verificat pe fixture, tab "Statistici
# jucatori" - 32 randuri, ambele echipe) - gasit prin testare directa,
# NU presupus: regex-ul initial `^(.+?\.)\s+(.+)$` presupunea ca numele
# jucatorului se termina mereu cu "X." (ca "Pop A."), dar 2 din 32 randuri
# reale au nume NEabreviate, fara punct ("Teles Wingback", "Heriberto
# Tavares Forward") - eșuau silentios sa se desparta de pozitie, ceea ce
# rupea join-ul cu roster-ul la persist() (gasit prin testul de
# idempotenta, nu prin citire de cod). Potrivire pe SUFIX cunoscut
# (nu pe punct) - mai lung intai (ordinea conteaza: "Attacking
# midfielder" trebuie verificat inaintea lui "Midfielder", altfel
# sufixul mai scurt s-ar potrivi gresit primul). Pozitie noua,
# neintalnita aici -> name ramane textul intreg, position None (fallback
# onest "necunoscut", nu crash, nu ghicit - North Star #8).
_KNOWN_POSITION_LABELS: tuple[str, ...] = tuple(sorted((
    "Goalkeeper", "Defender", "Centre back", "Fullback", "Wingback",
    "Winger", "Midfielder", "Attacking midfielder", "Forward", "Striker",
), key=len, reverse=True))


def _split_player_name_position(text: str) -> tuple[str, str | None]:
    for label in _KNOWN_POSITION_LABELS:
        if text == label:
            return "", label
        suffix = " " + label
        if text.endswith(suffix):
            return text[: -len(suffix)].strip(), label
    return text, None

# Cele 8 coloane reale ale tabelului "Statistici jucatori" (dupa Rating) -
# verificate pe fixture: header + un rand real, ordine confirmata.
PLAYER_TABLE_EXTENDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("total_shots", "Total shots"),
    ("xg", "Expected goals (xG)"),
    ("accurate_passes", "Accurate passes"),
    ("touches", "Touches"),
    ("touches_in_opposition_box", "Touches in opposition box"),
    ("successful_dribbles", "Successful dribbles"),
    ("duels", "Duels"),
)


def _parse_numeric(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().rstrip("%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_numeric_loose(raw: str | None) -> float | None:
    """Ia primul numar gasit la inceputul stringului - acopera valori
    compuse reale gasite pe tab-ul de statistici ("85% (314/371)" -> 85.0,
    "12/17 (71%)" -> 12.0) si valori lipsa ("-" -> None)."""
    if raw is None:
        return None
    m = _LEADING_NUMBER_RE.match(raw.strip())
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_int_loose(raw: str | None) -> int | None:
    """Pentru valori intregi cu spatii/spatii-fixe ca separator de mii
    (ex. "7 128" pentru attendance) - verificat real pe fixture."""
    if raw is None:
        return None
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else None


def _slugify(label: str) -> str:
    return re.sub(r"[^\w]+", "_", label.strip().lower()).strip("_")


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
    """Forma acceptata de `upsert_match_canonical` (subset COALESCE-safe).

    [ACTUALIZAT Foundation Data Layer] Preferat: tab-ul dedicat "stats"
    (/summary/stats/, 36 categorii reale) - fallback pe "summary" (5
    categorii din widget-ul restrans) daca "stats" nu e in pages (pastreaza
    compatibilitatea cu cele 9 fixture-uri din primul POC, care nu au tab
    "stats" capturat). Echipe/data raman pe orice pagina disponibila -
    verificat, header-ul e comun tuturor tab-urilor. Referee/Venue/
    Attendance/Capacity raman EXCLUSIV pe "summary" (verificat - absente
    din "stats")."""
    stats_page_html = pages.get("stats") or pages.get("summary")
    if not stats_page_html:
        return {}
    stats_soup = BeautifulSoup(stats_page_html, "html.parser")

    home_team, away_team = _extract_team_names(stats_soup)
    kickoff_date = _extract_kickoff_iso(stats_soup)
    stats = _extract_labeled_stat_pairs(stats_soup)

    summary_html = pages.get("summary")
    info = _extract_labeled_info_pairs(BeautifulSoup(summary_html, "html.parser")) if summary_html else {}

    result: dict[str, Any] = {
        "home_team": home_team,
        "away_team": away_team,
        "kickoff_date": kickoff_date,
        "referee": info.get("Referee:"),
        "stadium": info.get("Venue:"),
        "attendance": _parse_int_loose(info.get("Attendance:")),
        "capacity": _parse_int_loose(info.get("Capacity:")),
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


def normalize_match_statistics_extended(pages: dict[str, str], match_id: int) -> list[dict[str, Any]]:
    """Randuri `match_statistics_extended` (EAV, migratia 035) - toate
    categoriile reale din tab-ul "stats" FARA coloana dedicata in
    match_history (nu duplica STAT_LABEL_TO_FIELDS). ~26 categorii reale
    verificate pe fixture (xGOT, blocked shots, duels won, tackles, etc.)."""
    stats_page_html = pages.get("stats") or pages.get("summary")
    if not stats_page_html:
        return []
    soup = BeautifulSoup(stats_page_html, "html.parser")
    stats = _extract_labeled_stat_pairs(soup)
    rows: list[dict[str, Any]] = []
    for label, (home_raw, away_raw) in stats.items():
        if label in STAT_LABEL_TO_FIELDS:
            continue
        rows.append({
            "match_id": match_id,
            "stat_key": _slugify(label),
            "stat_label": label,
            "home_value_raw": home_raw,
            "away_value_raw": away_raw,
            "home_value_numeric": _parse_numeric_loose(home_raw),
            "away_value_numeric": _parse_numeric_loose(away_raw),
            "source": "flashscore",
        })
    return rows


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


def normalize_player_match_stats_table(pages: dict[str, str]) -> list[dict[str, Any]]:
    """Randuri brute din tab-ul "Statistici jucatori" (/summary/player-
    stats/) - nume, pozitie, rating + 7 statistici avansate (EAV). Tabelul
    combina ambele echipe FARA coloana de echipa - team se rezolva la
    persist(), prin join dupa nume cu roster-ul din `_extract_roster_rows`
    (acelasi meci) - nu aici, ca sa nu amestecam extractia cu rezolvarea
    de identitate. Verificat pe fixture: 32 randuri, 9 coloane
    (nume+pozitie, rating, + cele 7 din PLAYER_TABLE_EXTENDED_COLUMNS)."""
    html = pages.get("player_stats")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows_out: list[dict[str, Any]] = []
    for row in soup.select("[data-testid='wcl-tableBodyRow']"):
        cells = row.select("[data-testid='wcl-tableBodyCell']")
        if len(cells) < 2 + len(PLAYER_TABLE_EXTENDED_COLUMNS):
            continue
        name_pos_text = cells[0].get_text(" ", strip=True)
        name, position = _split_player_name_position(name_pos_text)
        if not name:
            continue
        extended = []
        for (key, label), cell in zip(PLAYER_TABLE_EXTENDED_COLUMNS, cells[2:]):
            raw = cell.get_text(strip=True)
            extended.append({
                "stat_key": key, "stat_label": label,
                "value_raw": raw, "value_numeric": _parse_numeric_loose(raw),
            })
        rows_out.append({
            "player_name": name,
            "position": position,
            "rating": _parse_numeric_loose(cells[1].get_text(strip=True)),
            "extended_stats": extended,
        })
    return rows_out


def normalize_match_context(
    pages: dict[str, str], match_id: int, home_team: str | None, away_team: str | None,
) -> list[dict[str, Any]]:
    """Randuri `flashscore_match_context` (migratia 035) - segmentate pe 3
    categorii REALE (verificate live, `wcl-headerSection-text`):
    "Head-to-head matches" (h2h_overall), "Last matches: <echipa acasa>"
    (recent_form_home), "Last matches: <echipa oaspete>" (recent_form_away).
    NU amestecate intr-un flux nediferentiat - fiecare rand real cu data
    (DD.MM.YY -> ISO), competitie, echipe, scor, dintr-un singur <a
    class="h2h__row"> auto-continut per meci istoric."""
    html = pages.get("h2h")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows_out: list[dict[str, Any]] = []
    for header in soup.select("[data-testid='wcl-headerSection-text']"):
        header_text = header.get_text(strip=True)
        category: str | None = None
        if header_text.startswith("Head-to-head"):
            category = "h2h_overall"
        elif header_text.startswith("Last matches:"):
            team_name = header_text.split(":", 1)[1].strip()
            if home_team and team_name == home_team:
                category = "recent_form_home"
            elif away_team and team_name == away_team:
                category = "recent_form_away"
        if category is None:
            continue
        section = header.find_parent(class_="h2h__section")
        if section is None:
            continue
        for order, link in enumerate(section.select("a[href*='/match/']")):
            date_el = link.select_one("[data-testid='wcl-stageTime']")
            event_el = link.select_one(".h2h__event")
            participants = link.select("[data-testid='wcl-matchRow-participant']")
            scores = link.select("[data-testid='wcl-tableScore']")
            if len(participants) < 2 or len(scores) < 2:
                continue
            rows_out.append({
                "context_match_id": match_id,
                "category": category,
                "meeting_order": order,
                "meeting_date": _parse_h2h_date(date_el.get_text(strip=True) if date_el else None),
                "competition_code": event_el.get_text(strip=True) if event_el else None,
                "home_team": participants[0].get_text(strip=True),
                "away_team": participants[1].get_text(strip=True),
                "home_score": _parse_int_loose(scores[0].get_text(strip=True)),
                "away_score": _parse_int_loose(scores[1].get_text(strip=True)),
                "source": "flashscore",
            })
    return rows_out


def _parse_h2h_date(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _H2H_DATE_RE.search(raw.strip())
    if not m:
        return None
    day, month, yy = m.groups()
    try:
        return datetime(2000 + int(yy), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def normalize_standings(pages: dict[str, str], competition: str) -> list[dict[str, Any]]:
    """Randuri `flashscore_standings_snapshot` (migratia 035) - clasament
    curent. NOTA de robustete (raportata explicit): structura foloseste
    clase CSS (`.ui-table__row`, `.tableCellParticipant__name`), NU
    `data-testid` standard ca restul site-ului - mai fragil potential la
    schimbari viitoare de build decat restul extractorilor. P/W/D/L
    identificate pozitional (primele 4 `.table__cell--value` din rand,
    dupa convenția standard confirmată pe fixture) - Scor/GD/Puncte au
    clase specifice, mai robuste."""
    html = pages.get("standings")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows_out: list[dict[str, Any]] = []
    for row in soup.select(".ui-table__row"):
        team_el = row.select_one("a.tableCellParticipant__name")
        if team_el is None:
            continue
        rank_el = row.select_one(".tableCellRank")
        values = row.select(".table__cell--value")
        score_el = row.select_one(".table__cell--score")
        gd_el = row.select_one(".table__cell--goalsForAgainstDiff")
        points_el = row.select_one(".table__cell--points")
        goals_for = goals_against = None
        if score_el is not None:
            parts = score_el.get_text(strip=True).split(":")
            if len(parts) == 2:
                goals_for = _parse_int_loose(parts[0])
                goals_against = _parse_int_loose(parts[1])
        rows_out.append({
            "competition": competition,
            "team": team_el.get_text(strip=True),
            "rank": _parse_int_loose(rank_el.get_text(strip=True)) if rank_el else None,
            "played": _parse_int_loose(values[0].get_text(strip=True)) if len(values) > 0 else None,
            "won": _parse_int_loose(values[1].get_text(strip=True)) if len(values) > 1 else None,
            "drawn": _parse_int_loose(values[2].get_text(strip=True)) if len(values) > 2 else None,
            "lost": _parse_int_loose(values[3].get_text(strip=True)) if len(values) > 3 else None,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "goal_diff": _parse_int_loose(gd_el.get_text(strip=True)) if gd_el else None,
            "points": _parse_int_loose(points_el.get_text(strip=True)) if points_el else None,
            "source": "flashscore",
        })
    return rows_out


def normalize_odds(pages: dict[str, str]) -> list[dict[str, Any]]:
    """Randuri crude 1X2 per bookmaker din tab-ul dedicat Cote
    (`/odds/?mid=X`) - sursa pentru `odds_fallback_flashscore` (ADR-043,
    migratia 032), DAR fara `fixture_id` (rezolvarea identitatii
    cross-provider ramane un pas SEPARAT, la persist() - normalizer-ul nu
    rezolva identitate, vezi docstring modul).

    Structura reala verificata pe fixture (`.ui-table.oddsCell__odds` ->
    `.ui-table__row`): numele bookmaker-ului traieste in atributul
    `title` al link-ului din `.oddsCell__bookmakerPart` (identic cu
    `img[alt]`, verificat). Cele 3 valori `.oddsCell__odd` sunt
    identificate robust prin `data-analytics-label`
    (`..._1`=home, `..._0`=draw, `..._2`=away - confirmat pe fixture,
    NU presupus din ordinea DOM). Randuri fara nicio cota (bookmaker fara
    piata pentru acest meci - gasit real pe fixture) sunt EXCLUSE, nu
    aproximate cu 0 (North Star #8)."""
    html = pages.get("odds")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".ui-table.oddsCell__odds")
    if container is None:
        return []
    rows_out: list[dict[str, Any]] = []
    for row in container.select(".ui-table__row"):
        bm_link = row.select_one(".oddsCell__bookmakerPart a[title]")
        bookmaker = bm_link.get("title") if bm_link else None
        if not bookmaker:
            continue
        by_outcome: dict[str, str | None] = {}
        for cell in row.select(".oddsCell__odd"):
            label = cell.get("data-analytics-label") or ""
            span = cell.select_one("span")
            value = span.get_text(strip=True) if span else None
            if label.endswith("_1"):
                by_outcome["home"] = value
            elif label.endswith("_0"):
                by_outcome["draw"] = value
            elif label.endswith("_2"):
                by_outcome["away"] = value
        if not by_outcome:
            continue
        rows_out.append({
            "bookmaker": bookmaker,
            "home": _parse_numeric_loose(by_outcome.get("home")),
            "draw": _parse_numeric_loose(by_outcome.get("draw")),
            "away": _parse_numeric_loose(by_outcome.get("away")),
            "source": "flashscore",
        })
    return rows_out


def normalize_upcoming_match(raw_record: dict) -> dict[str, Any]:
    """[Afara scope M0] Pre-Match Sync - fereastra 7 zile, upcoming_matches/
    upcoming_lineups/upcoming_match_features (design §3.5) - nu face parte
    din Critical Path M0-M4 (doar meciuri finalizate, capturate). Ramane
    neimplementat deliberat."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: afara scope M0 (Pre-Match Sync, nu Bootstrap/Night "
        "Sync pe meciuri finalizate) - vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
    )
