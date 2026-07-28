"""
================================================================================
POC izolat — descoperire championship_id Soccer Football Info per ligă
================================================================================
Discovery, NU integrare (tiparul deja folosit la Romania SuperLiga,
2026-07-27). Apeluri HTTP REALE cu cheia deja configurată
(RAPIDAPI_KEY_FREELIVEFOOTBALL, comună cu FreeLF), prin
`soccerfootballinfo_client.get_matches_for_day()` — funcția deja existentă,
deja cache-uită, nu se rescrie logica HTTP.

NU importă `key_manager.py` ca sursă de adevăr pentru altceva decât cheia
deja folosită de restul Sync Layer-ului. NU modifică niciun workflow
existent. NU e importat de niciun cod de producție. Rulează o singură dată,
manual (`workflow_dispatch`), se șterge din cod după închiderea descoperirii
(dovada rămâne în istoricul rulării GitHub Actions + CHANGELOG).

Scop: pentru fiecare dată din DISCOVERY_DATES, un singur apel
`matches/day/full` (buget: len(DISCOVERY_DATES) cereri, din cota de
200/zi), extrage (championship.id, championship.name, country) distincte —
NU ghicește ID-uri, le citește direct din răspunsul brut.
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from soccerfootballinfo_client import get_soccerfootballinfo_client

# Date alese pentru a acoperi ligile din mappings.LEAGUE_PROVIDERS încă fără
# soccerfootballinfo — sfârșitul sezonului 2025/26 pentru cele 5 mari ligi +
# UEFA, o dată recentă pentru MLS (sezon în curs), o dată din fereastra
# World Cup 2026 (11 iunie - 19 iulie 2026, real).
DISCOVERY_DATES = [
    "2026-05-24",  # PL / La Liga / Serie A — ultima zi de sezon (confirmat, match_history)
    "2026-05-17",  # Bundesliga / Ligue 1 — ultima zi de sezon (confirmat, match_history)
    "2026-05-20",  # fereastră tipică finală UEFA (Champions League / Europa League / Conference League)
    "2026-05-27",  # a doua fereastră finală UEFA, dacă 05-20 nu prinde
    "2026-07-19",  # World Cup 2026 — finala (dată reală)
    "2026-07-12",  # World Cup 2026 — semifinale
    "2026-07-27",  # MLS — sezon în curs (ieri, față de azi 2026-07-28)
]


def main() -> None:
    client = get_soccerfootballinfo_client()
    seen: dict[str, tuple[str, str]] = {}

    for date_iso in DISCOVERY_DATES:
        payload = client.get_matches_for_day(date_iso)
        if not payload:
            print(f"[{date_iso}] payload gol/indisponibil (cheie lipsă, cotă epuizată, sau eroare HTTP)")
            continue
        matches = payload.get("result") or []
        if not isinstance(matches, list):
            print(f"[{date_iso}] 'result' neașteptat: {type(matches)}")
            continue
        print(f"[{date_iso}] {len(matches)} meciuri globale")
        for m in matches:
            champ = m.get("championship") or {}
            cid = str(champ.get("id") or "")
            if not cid or cid in seen:
                continue
            name = champ.get("name") or ""
            country = (champ.get("country") or {}).get("name") if isinstance(champ.get("country"), dict) else champ.get("country")
            seen[cid] = (name, str(country or ""))

    print("\n=== Championship ID-uri distincte găsite (toate, nu doar cele relevante) ===")
    for cid, (name, country) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        print(f"  id={cid!r:20} name={name!r:35} country={country!r}")


if __name__ == "__main__":
    main()
