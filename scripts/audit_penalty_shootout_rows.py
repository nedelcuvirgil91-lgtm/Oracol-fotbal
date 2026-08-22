"""
================================================================================
FOOTBALL ORACLE — Audit: scoruri corupte de bugul penalty-shootout
================================================================================
Module: scripts/audit_penalty_shootout_rows.py

STRICT read-only. Nu scrie nimic in Supabase. Nu modifica niciun rand.

--------------------------------------------------------------------------------
DE CE EXISTA
--------------------------------------------------------------------------------
`sync/sources/football_data.py::_parse_match()` citea `score.fullTime` fara sa
se uite la `score.duration`. Pentru un meci decis la penalty-uri,
football-data.org raporteaza in `fullTime` suma regulamentar + loviturile de
departajare, iar scorul REAL al meciului sta in `score.regularTime`. Bugul a
fost reparat la sursa (fix in acest repo), dar randurile deja scrise raman
corupte — un fix la sursa nu rescrie istoria.

Cazul care a declansat auditul: `fd_524100` (Liverpool - Paris Saint-Germain,
2025-03-11) persistat ca 1-5, in timp ce meciul s-a terminat 0-1 (1-1 la
general, 4-1 la penalty-uri). Randul e si singura coliziune care blocheaza
redenumirea categoriei D2, si singurul HARD CONFLICT ramas dupa ADR-025 Faza 4.

--------------------------------------------------------------------------------
DE CE AUDITEAZA TOT, NU DOAR CHAMPIONS LEAGUE
--------------------------------------------------------------------------------
Loviturile de departajare apar, teoretic, doar in competitii cu eliminare
directa — dintre cele 8 competitii cu randuri `fd_`, doar Champions League e
asa. Dar "teoretic" nu e o verificare. Cele 24 de perechi (liga, sezon) cer 24
de apeluri API, adica sub 3 minute de cota — cost neglijabil fata de riscul de
a rata un rand corupt pentru ca am presupus ca o liga interna nu poate avea
asa ceva. Se auditeaza tot ("Verificat, nu presupus").

--------------------------------------------------------------------------------
CUM
--------------------------------------------------------------------------------
Refoloseste componentele de productie, nemodificate: `_rate_limited_get`,
`COMPETITION_CODES`, `FD_BASE_URL`. NU refoloseste `_parse_match()` — acela
returneaza deja forma corectata, iar auditul are nevoie de campurile BRUTE
(`score.duration`, `score.fullTime`, `score.regularTime`) ca sa poata arata
exact ce a citit gresit versiunea veche.

Pentru fiecare rand `fd_*` din `match_history`, compara scorul persistat cu
adevarul din API:
    duration == "PENALTY_SHOOTOUT"  ->  adevarul e `score.regularTime`
    altfel                          ->  adevarul e `score.fullTime`

Raporteaza FIECARE nepotrivire, indiferent de cauza — nu doar cele explicabile
prin shootout. O nepotrivire de alt fel e la fel de importanta si nu are voie
sa fie tacuta doar pentru ca nu e ce cautam.

Utilizare:
    python scripts/audit_penalty_shootout_rows.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def season_to_api_year(season: str | None) -> int | None:
    """'2023-2024' -> 2023. Un sezon necunoscut/absent ramane None si randul e
    raportat ca neverificabil — NU e presupus corect (North Star #8)."""
    if not season:
        return None
    head = str(season).split("-")[0].strip()
    return int(head) if head.isdigit() and len(head) == 4 else None


def truth_from_score(score: dict) -> tuple[int | None, int | None, str]:
    """Scorul REAL al meciului, din payload-ul brut football-data.org.

    Functie PURA — testata direct pe payload-uri sintetice
    (`tests/test_audit_penalty_shootout_rows.py`), fara retea.

    Returneaza `(home, away, duration)`. Pentru un meci decis la penalty-uri
    adevarul e `regularTime`; `fullTime` include loviturile de departajare si
    NU e scorul meciului. Daca `regularTime` lipseste, se intoarce (None, None)
    — necunoscut explicit, niciodata aproximat din `fullTime`.
    """
    duration = (score.get("duration") or "").upper()
    if duration == "PENALTY_SHOOTOUT":
        rt = score.get("regularTime") or {}
        return rt.get("home"), rt.get("away"), duration
    ft = score.get("fullTime") or {}
    return ft.get("home"), ft.get("away"), duration


def _fetch_fd_rows(client) -> list[dict]:
    rows: list[dict] = []
    offset, page_size = 0, 1000
    while True:
        batch = (
            client.table("match_history")
            .select("id,fixture_id,home_team,away_team,kickoff_date,league,season,"
                    "actual_home_goals,actual_away_goals,actual_result,superseded_by")
            .like("fixture_id", "fd\\_%")
            .range(offset, offset + page_size - 1)
            .execute().data
        ) or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from sync.sources.football_data import (
        COMPETITION_CODES, FD_BASE_URL, _rate_limited_get,
    )

    print(BAR)
    print("  AUDIT — scoruri corupte de bugul penalty-shootout (fd_*)")
    print("  STRICT read-only. Zero scrieri.")
    print(BAR)

    rows = _fetch_fd_rows(sb.get_client())
    print(f"  Randuri fd_* in match_history : {len(rows)}")

    pairs: dict[tuple[str, int], list[dict]] = defaultdict(list)
    fara_sezon: list[dict] = []
    for r in rows:
        yr = season_to_api_year(r.get("season"))
        lg = r.get("league")
        if yr is None or lg not in COMPETITION_CODES:
            fara_sezon.append(r)
            continue
        pairs[(lg, yr)].append(r)

    print(f"  Perechi (liga, sezon) de interogat : {len(pairs)}")
    print(f"  Randuri neverificabile (sezon/liga necunoscuta) : {len(fara_sezon)}")
    print(BAR)

    nepotriviri: list[dict] = []
    shootout_total = 0
    negasite = 0
    verificate = 0

    for (league, year) in sorted(pairs):
        code = COMPETITION_CODES[league]
        data = _rate_limited_get(
            f"{FD_BASE_URL}/competitions/{code}/matches",
            params={"season": year, "status": "FINISHED"},
        )
        if not data:
            print(f"  [!] {league} {year}: API nu a raspuns — randurile raman NEVERIFICATE")
            continue

        api: dict[int, dict] = {}
        for m in data.get("matches", []):
            try:
                api[int(m.get("id"))] = m.get("score") or {}
            except (TypeError, ValueError):
                continue

        n_shootout = sum(
            1 for s in api.values() if (s.get("duration") or "").upper() == "PENALTY_SHOOTOUT"
        )
        shootout_total += n_shootout

        for r in pairs[(league, year)]:
            try:
                mid = int(str(r["fixture_id"]).split("_", 1)[1])
            except (KeyError, IndexError, ValueError):
                negasite += 1
                continue
            score = api.get(mid)
            if score is None:
                negasite += 1
                continue

            verificate += 1
            th, ta, duration = truth_from_score(score)
            if th is None or ta is None:
                continue
            ph, pa = r.get("actual_home_goals"), r.get("actual_away_goals")
            if ph is None or pa is None:
                continue
            if int(ph) != int(th) or int(pa) != int(ta):
                nepotriviri.append({**r, "_true_home": th, "_true_away": ta,
                                    "_duration": duration})

        print(f"  {league:<18} {year}: {len(api)} in API, "
              f"{len(pairs[(league, year)])} in DB, {n_shootout} decise la penalty-uri")

    print(BAR)
    print(f"  Randuri verificate contra API      : {verificate}")
    print(f"  Randuri negasite in API            : {negasite}")
    print(f"  Meciuri decise la penalty-uri (API): {shootout_total}")
    print(f"  NEPOTRIVIRI DE SCOR                : {len(nepotriviri)}")
    print(BAR)

    if not nepotriviri:
        print("  Niciun rand corupt. Nimic de corectat.")
        print(BAR)
        return 0

    print("  Detaliu (persistat -> adevar API):")
    for r in sorted(nepotriviri, key=lambda x: (x.get("league") or "", x.get("kickoff_date") or "")):
        live = "LIVE" if r.get("superseded_by") is None else "superseded"
        print(f"    id={r['id']:<8} {r['fixture_id']:<14} [{r['_duration'] or 'REGULAR':<17}] {live}")
        print(f"      {r['home_team']} vs {r['away_team']} @ {r['kickoff_date']} ({r['league']})")
        print(f"      persistat {r['actual_home_goals']}-{r['actual_away_goals']}"
              f"   ->   adevar {r['_true_home']}-{r['_true_away']}")
    print(BAR)
    print("  ZERO scriere efectuata. Corectia e o decizie separata, cu SQL aratat explicit.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
