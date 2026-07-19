"""
================================================================================
FOOTBALL ORACLE — Trace runtime EXACT al fluxului din app.py (nav="matches")
================================================================================
Module: sync/poc_app_runtime_trace.py

Discovery, NU o schimbare de productie. NU importa app.py ca modul (contine
st.set_page_config() si alt cod Streamlit la nivel de modul, care ar esua
sau ar avea efecte secundare in afara unei rulari `streamlit run` reale).

In schimb: extrage COMPETITIONS_META din app.py prin parsare AST a sursei
(literalul EXACT din fisier, nu o copie retastata manual, care ar putea
diverge silentios), apoi reproduce LITERAL, linie cu linie, logica din
app.py liniile 511-524 si 549-551 (bloc nav=="matches"), folosind exact
FootballOracleEngine().api.get_matches_for_week() - acelasi apel pe care
il face aplicatia live.

Raporteaza exact ce a cerut review-ul:
  - commit hash (al checkout-ului curent)
  - len(all_matches)
  - competitiile prezente in all_matches
  - comp_counts (identic cu ce ar afisa cardurile din UI)
  - len(filtered) pentru Romania SuperLiga
  - id() al obiectului all_matches (dovada ca e un obiect nou, proaspat)

Nu poate demonstra ce ruleaza pe deployment-ul live (fara acces la el) -
demonstreaza STRICT ce produce runtime-ul acestui commit, acum, cu date
reale. Compararea cu ce vede utilizatorul in browser ramane un pas separat.

Rulare:
    python sync/poc_app_runtime_trace.py
================================================================================
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def _extract_competitions_meta() -> list[dict]:
    """Parsare AST a app.py — extrage EXACT literalul COMPETITIONS_META,
    fara sa execute vreo linie din app.py (evita st.set_page_config() etc.)."""
    source = (root / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="app.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "COMPETITIONS_META":
                    return ast.literal_eval(node.value)
    raise RuntimeError("COMPETITIONS_META nu a fost gasit in app.py — structura fisierului s-a schimbat?")


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        ).strip()
    except Exception as exc:
        return f"(indisponibil: {exc})"


def main() -> None:
    commit = _git_commit_hash()
    print(f"commit hash (checkout curent, acest runner): {commit}")

    competitions_meta = _extract_competitions_meta()
    keys = [c["key"] for c in competitions_meta]
    print(f"COMPETITIONS_META extras din app.py (AST, sursa literala): {keys}")
    assert "Romania SuperLiga" in keys, "Romania SuperLiga lipseste din COMPETITIONS_META — asta ar fi cauza reala"

    print("\n--- reproducere LITERALA a app.py liniile 511-524 si 549-551 (nav=='matches') ---\n")

    from oracle_engine import FootballOracleEngine
    engine = FootballOracleEngine()

    # app.py linia 513-516, identic
    all_matches = engine.api.get_matches_for_week(
        days_ahead=7,
        competitions=keys,
    )
    print(f"len(all_matches) = {len(all_matches)}")
    print(f"id(all_matches) = {id(all_matches)}  (obiect nou, creat acum, in acest proces)")

    # app.py linia 522-524, identic
    comp_counts: dict[str, int] = {}
    for m in all_matches:
        lg = m.get("league", "")
        comp_counts[lg] = comp_counts.get(lg, 0) + 1
    print(f"\ncomp_counts (identic cu ce ar afisa cardurile din UI):")
    for key in keys:
        print(f"  {key:<20} {comp_counts.get(key, 0)}")

    # app.py linia 551, identic
    sel = "Romania SuperLiga"
    filtered = [m for m in all_matches if m.get("league") == sel]
    print(f"\nfiltered = [m for m in all_matches if m.get('league') == 'Romania SuperLiga']")
    print(f"len(filtered) = {len(filtered)}")
    for m in filtered:
        print(f"  {m.get('home_team')} vs {m.get('away_team')}  ({m.get('kickoff_date')})  source={m.get('source')}")

    print("\n" + "=" * 78)
    if len(filtered) > 0:
        print("VERDICT: runtime-ul (acest commit, executat acum, cu date reale) PRODUCE")
        print("Romania SuperLiga in all_matches/filtered — identic cu ce ar afisa UI-ul")
        print("DACA browserul ar rula exact acest cod, cu o sesiune noua.")
        print("Daca browserul TOT arata 0, discrepanta e intre acest runtime si CEEA CE")
        print("RULEAZA EFECTIV DEPLOYMENT-UL LIVE (commit diferit, proces vechi, cache")
        print("extern) — NU in codul din acest commit.")
    else:
        print("VERDICT: runtime-ul (acest commit) NU produce Romania SuperLiga.")
        print("Bug-ul e in continuare in codul din acest commit, nu in deployment.")
    print("=" * 78)


if __name__ == "__main__":
    main()
