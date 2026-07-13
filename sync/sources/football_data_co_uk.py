"""
================================================================================
FOOTBALL ORACLE — Importer football-data.co.uk (istoric, cote)
================================================================================
Module: sync/sources/football_data_co_uk.py

Importer generic pentru oglinda football-data.co.uk folosită de
BackfillOddsService (services/odds_backfill_service.py). Nu conține nicio
logică specifică unei ligi — `division` e un cod opac (ex. "E0"), primit ca
parametru, niciodată hardcodat.

Acces la rețea: football-data.co.uk direct e blocat de politica de rețea a
mediului (demonstrat, FOOTBALL_DATA_CO_UK_AUDIT_2026-07-13.md). Sursa reală
folosită aici e o oglindă GitHub (xgabora/Club-Football-Match-Data-2000-2025),
accesibilă direct — un singur fișier CSV, toate ligile, filtrat pe `division`.

Limitări demonstrate ale acestei surse (raportate, nu ascunse):
  - Un singur preț per meci/bookmaker (Bet365 + Market Max) — NU o pereche
    opening/closing distinctă. Writer-ul scrie opening_*=closing_*=acest preț.
  - Datele se opresc la sfârșitul sezonului 2024/25 — nu acoperă sezonul curent.
================================================================================
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging

import requests

logger = logging.getLogger("FootballOracle.FootballDataCoUk")

MATCHES_CSV_URL = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"

# Piața 1X2 — strict cele două seturi de cote validate (ADR-006 §3: scope
# 1X2, nimic altceva). Cheia e numele de bookmaker scris în odds_history.
_BOOKMAKER_FIELDS: dict[str, tuple[str, str, str]] = {
    "Bet365": ("OddHome", "OddDraw", "OddAway"),
    "Market_Max": ("MaxHome", "MaxDraw", "MaxAway"),
}


def _is_valid_price(value) -> bool:
    if value in (None, ""):
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return v > 1


def fetch_football_data_co_uk_rows(division: str, season: str | None, min_date: str) -> list[dict]:
    """
    Importer generic — implementează contractul cerut de BackfillOddsService:
    (division, season, min_date) -> listă de rânduri brute.

    `season` nefolosit de acest importer (sursa nu e împărțită pe fișiere de
    sezon) — rezervat pentru un importer viitor bazat pe fișiere per-sezon
    (ex. football-data.co.uk direct, mmz4281/{season}/{division}.csv).

    Fiecare rând returnat corespunde unei perechi (meci, bookmaker) cu preț
    valid. Un meci fără scor final cunoscut e sărit — nu poate fi verificat
    ulterior prin matching de scor (fail-closed, nu aproximare).
    """
    resp = requests.get(MATCHES_CSV_URL, timeout=90)
    resp.raise_for_status()
    text = resp.content.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    rows: list[dict] = []

    for r in reader:
        if r.get("Division") != division:
            continue
        match_date = (r.get("MatchDate") or "")[:10]
        if not match_date or match_date < min_date:
            continue

        try:
            home_goals = int(float(r["FTHome"]))
            away_goals = int(float(r["FTAway"]))
        except (ValueError, TypeError, KeyError):
            continue  # scor necunoscut -> nu poate fi verificat, sarit

        home_team_raw = r.get("HomeTeam", "")
        away_team_raw = r.get("AwayTeam", "")
        if not home_team_raw or not away_team_raw:
            continue

        # hash pe rândul brut complet din sursă — detectează orice revizuire
        # tăcută ulterioară a acestui rând specific, nu doar a fișierului întreg
        row_repr = ",".join(f"{k}={r.get(k, '')}" for k in fieldnames)
        row_hash = hashlib.sha256(row_repr.encode("utf-8")).hexdigest()

        for bookmaker, (h_key, d_key, a_key) in _BOOKMAKER_FIELDS.items():
            h, d, a = r.get(h_key), r.get(d_key), r.get(a_key)
            if not (_is_valid_price(h) and _is_valid_price(d) and _is_valid_price(a)):
                continue
            rows.append({
                "match_date": match_date,
                "home_team_raw": home_team_raw,
                "away_team_raw": away_team_raw,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "bookmaker": bookmaker,
                "price_home": float(h), "price_draw": float(d), "price_away": float(a),
                "source_hash": row_hash,
                "source_url": MATCHES_CSV_URL,
            })

    logger.info(
        "[FootballDataCoUk] division=%s min_date=%s: %d randuri (meci,bookmaker) extrase",
        division, min_date, len(rows),
    )
    return rows
