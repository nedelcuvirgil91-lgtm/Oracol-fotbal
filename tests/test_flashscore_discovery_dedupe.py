"""Teste pentru `dedupe_by_mid` (R5) — acelasi meci descoperit de mai multe ori.

CONTEXT (rularea reala din 2026-08-23): Discovery a intors 4 mid-uri de doua
ori — 4xKntFxe (Premier League), zkSijgL7 (Ligue 1), nqbcPVHG (Super Lig),
EJFII9Il (Ekstraklasa). Hub-urile /fixtures/ si /results/ pot lista acelasi
meci, iar un meci in desfasurare apare in ambele.

Trei au fost sarite la a doua trecere prin Delta Sync — munca irosita (7 tab-uri
Playwright degeaba). Al patrulea (4xKntFxe, Newcastle - Liverpool, in
desfasurare in timpul rularii) a picat pe validare de identitate si a facut
workflow-ul ROSU, desi fusese colectat cu succes la prima trecere.

Fara retea, fara Supabase.
"""
from __future__ import annotations

from providers.flashscore.discovery import DiscoveredMatch, dedupe_by_mid


def _m(mid: str, league: str = "Premier League", source: str = "fixtures") -> DiscoveredMatch:
    return DiscoveredMatch(
        league=league, match_base_url=f"https://flashscore.com/{mid}", mid=mid, source=source,
    )


def test_acelasi_mid_din_doua_surse_ramane_o_singura_data():
    """Cazul real: acelasi meci listat si in /fixtures/ si in /results/."""
    out = dedupe_by_mid([_m("4xKntFxe", source="fixtures"), _m("4xKntFxe", source="results")])
    assert len(out) == 1
    assert out[0].source == "fixtures", "se pastreaza PRIMA aparitie"


def test_mid_uri_distincte_raman_toate():
    intrare = [_m("a"), _m("b"), _m("c")]
    assert dedupe_by_mid(intrare) == intrare


def test_ordinea_se_pastreaza():
    out = dedupe_by_mid([_m("a"), _m("b"), _m("a"), _m("c")])
    assert [m.mid for m in out] == ["a", "b", "c"]


def test_lista_goala():
    assert dedupe_by_mid([]) == []


def test_acelasi_mid_sub_doua_ligi_se_logheaza_ca_avertisment(caplog):
    """Un meci listat sub doua competitii nu e zgomot — e o informatie despre
    maparea competitiilor, deci se ridica la WARNING, nu la INFO."""
    with caplog.at_level("INFO"):
        out = dedupe_by_mid([_m("x", league="Champions League"), _m("x", league="Europa League")])

    assert len(out) == 1
    assert out[0].league == "Champions League"
    assert "DOUA ligi diferite" in caplog.text


def test_duplicat_in_aceeasi_liga_se_logheaza_doar_informativ(caplog):
    with caplog.at_level("INFO"):
        dedupe_by_mid([_m("y", source="fixtures"), _m("y", source="results")])

    assert "DOUA ligi diferite" not in caplog.text
    assert "de mai multe ori" in caplog.text


def test_obiect_fara_mid_nu_se_pierde():
    """Regula: deduplicarea nu are voie sa ARUNCE date. Fara `mid` nu putem
    decide daca e duplicat, deci il pastram — o stare necunoscuta nu devine
    o eliminare tacita (Regula #8)."""
    class _FaraMid:
        mid = None

    a, b = _FaraMid(), _FaraMid()
    out = dedupe_by_mid([a, b])
    assert out == [a, b]


def test_trei_aparitii_ale_aceluiasi_mid():
    out = dedupe_by_mid([_m("z"), _m("z"), _m("z")])
    assert len(out) == 1


def test_discover_matches_chiar_aplica_deduplicarea():
    """GARDA de cablare. Testele de mai sus verifica functia PURA; niciunul nu
    ar prinde stergerea apelului din `discover_matches()` — care ruleaza sub
    Playwright si nu poate fi apelata in teste fara retea. Verificare la nivel
    de AST: `discover_matches` trebuie sa intoarca `dedupe_by_mid(...)`."""
    import ast
    import inspect

    from providers.flashscore import discovery

    arbore = ast.parse(inspect.getsource(discovery.discover_matches))
    returnuri = [n for n in ast.walk(arbore) if isinstance(n, ast.Return)]
    assert returnuri, "discover_matches() nu are niciun return"

    def _e_dedupe(nod) -> bool:
        return isinstance(nod, ast.Call) and getattr(nod.func, "id", None) == "dedupe_by_mid"

    # [INTARIT 2026-08-25, ADR-067] Varianta anterioara cerea LITERAL
    # `return dedupe_by_mid(...)`. A cazut cand functia a fost refactorizata in
    # `rezultate = dedupe_by_mid(results)` / `return rezultate` — desi
    # deduplicarea se aplica in continuare. Era un fals pozitiv: garda verifica
    # FORMA, nu invariantul. Acum verifica invariantul real — tot ce se
    # intoarce a trecut prin dedupe_by_mid — deci accepta si varianta prin
    # variabila, dar respinge in continuare disparitia apelului.
    nume_dedupate = {
        t.id
        for n in ast.walk(arbore) if isinstance(n, ast.Assign) and _e_dedupe(n.value)
        for t in n.targets if isinstance(t, ast.Name)
    }

    for r in returnuri:
        direct = _e_dedupe(r.value)
        prin_variabila = isinstance(r.value, ast.Name) and r.value.id in nume_dedupate
        assert direct or prin_variabila, (
            "fiecare return din discover_matches() trebuie sa treaca prin "
            "dedupe_by_mid() — altfel duplicatele din hub-uri ajung la fetch"
        )
