"""Clasa 6 din `check_data_health`: rânduri de clasament sub formă NEcanonică.

CONTEXT. Găsită pe date reale (2026-08-26), ca efect secundar al reîmprospătării
`captured_at`: 19 rânduri orfane în `flashscore_standings_snapshot`, aceeași
echipă sub două nume — „Heerenveen" lângă „SC Heerenveen", „Atl. Madrid" lângă
„Atletico Madrid", „Nottingham" lângă „Nottingham Forest".

Scrise ÎNAINTE de fixul de normalizare din 2026-08-15. `UNIQUE(competition,
team)` le ține ca echipe diferite, deci rândul vechi nu se rescrie niciodată în
loc — rămâne fantomă, cu cifre înghețate în trecut. După curățare, numărătorile
au confirmat mărimile reale ale ligilor (Serie A 20, Ligue 1 18, SuperLiga 16).

DE CE MONITORIZARE, NU DOAR CURĂȚARE: clasa se poate reactiva oricând se ADAUGĂ
un alias nou — o formă azi canonică devine mâine alias, iar rândul ei existent
devine instant orfan. Curățarea rezolvă instanțele; detectorul rezolvă clasa.

Fără rețea, fără Supabase — invariant pur.
"""
from __future__ import annotations

from mappings import normalize_team_name


def _imparte(randuri: list[dict]) -> tuple[list[dict], list[dict]]:
    """Replica exactă a invariantului din `check_data_health`, clasa 6.

    [CORECTAT 2026-08-27] Întoarce (duplicate, unice) — nu o singură listă.
    Motivul e în docstring-ul modulului: cele două cer acțiuni OPUSE."""
    existente = {(r.get("competition"), r.get("team")) for r in randuri}
    duplicate, unice = [], []
    for r in randuri:
        if not r.get("team"):
            continue
        canonic = normalize_team_name(r["team"])
        if canonic == r["team"]:
            continue
        (duplicate if (r.get("competition"), canonic) in existente else unice).append(r)
    return duplicate, unice


def _orfane(randuri: list[dict]) -> list[dict]:
    """Toate rândurile necanonice, indiferent de clasă — pentru testele care
    verifică doar DETECȚIA, nu și acțiunea recomandată."""
    d, u = _imparte(randuri)
    return d + u


def _r(team, comp="Eredivisie", rid=1):
    return {"id": rid, "competition": comp, "team": team}


# ── invariantul de bază ──────────────────────────────────────────────────────

def test_forma_canonica_nu_e_semnalata():
    """Contrapondere: formele corecte nu au voie să producă zgomot."""
    for nume in ("SC Heerenveen", "Atletico Madrid", "Nottingham Forest",
                 "FC Barcelona", "Real Madrid", "FCSB"):
        assert _orfane([_r(nume)]) == [], f"{nume!r} e canonic, nu orfan"


def test_formele_reale_gasite_in_productie_sunt_prinse():
    """CAZURILE REALE, toate cele 19 verificate pe producție 2026-08-26."""
    vechi = ["Groningen", "Utrecht", "Sittard", "Zwolle", "Excelsior",
             "Heerenveen", "Telstar", "Leuven", "Atl. Madrid", "Nottingham",
             "Nacional", "Santa Clara", "Estrela", "Casa Pia", "Arouca",
             "Famalicao", "Moreirense", "Rio Ave", "Goztepe"]
    prinse = _orfane([_r(n, rid=i) for i, n in enumerate(vechi)])
    assert len(prinse) == len(vechi), (
        f"nu toate formele necanonice reale sunt prinse: "
        f"{set(vechi) - {p['team'] for p in prinse}}"
    )


def test_fiecare_orfan_converge_la_o_forma_canonica_diferita():
    """Garanția că semnalul e acționabil: orfanul are unde să fie unificat."""
    for nume in ("Heerenveen", "Atl. Madrid", "Nottingham"):
        canonic = normalize_team_name(nume)
        assert canonic != nume
        assert normalize_team_name(canonic) == canonic, (
            f"{canonic!r} trebuie sa fie punct fix — altfel harta e inconsistenta"
        )


# ── degradare ────────────────────────────────────────────────────────────────

def test_lista_goala():
    assert _orfane([]) == []


def test_rand_fara_nume_nu_arunca():
    assert _orfane([{"id": 1, "competition": "X", "team": None}]) == []
    assert _orfane([{"id": 1, "competition": "X", "team": ""}]) == []
    assert _orfane([{"id": 1, "competition": "X"}]) == []


# ── separarea celor două clase (defect găsit la prima rulare reală în CI) ────

def test_cazul_REAL_gasit_azi_nu_e_duplicat_ci_inregistrare_unica():
    """CAZUL CARE A EXPUS DEFECTUL, 2026-08-27, Bundesliga.

    `Schalke` și `B. Monchengladbach` sunt SINGURELE rânduri pentru acele
    echipe — nu există `Schalke 04`, nu există `Borussia Monchengladbach`.
    Versiunea inițială le raporta ca duplicate și afișa „rândul canonic există
    separat"; ștergerea lor ar fi eliminat două echipe din clasament."""
    bundesliga = [
        _r("Union Berlin", "Bundesliga", 5023),
        _r("Bayern Munich", "Bundesliga", 5025),
        _r("Schalke", "Bundesliga", 5028),
        _r("B. Monchengladbach", "Bundesliga", 5031),
        _r("RB Leipzig", "Bundesliga", 5040),
    ]
    duplicate, unice = _imparte(bundesliga)
    assert duplicate == [], "niciunul nu are geamăn canonic în acest clasament"
    assert {r["team"] for r in unice} == {"Schalke", "B. Monchengladbach"}


def test_cu_geaman_canonic_e_clasificat_ca_DUPLICAT():
    """Cazul de ieri, cel pentru care ștergerea CHIAR e acțiunea corectă."""
    randuri = [
        _r("SC Heerenveen", "Eredivisie", 1),
        _r("Heerenveen", "Eredivisie", 2),
    ]
    duplicate, unice = _imparte(randuri)
    assert [r["id"] for r in duplicate] == [2]
    assert unice == []


def test_geamanul_se_cauta_in_ACEEASI_competitie():
    """GARDĂ PREVENTIVĂ, pe un scenariu care NU poate apărea azi.

    Invariantul: cheia e `UNIQUE(competition, team)`, deci și căutarea
    geamănului trebuie să fie per competiție. Verificarea trebuie să
    corespundă cheii, altfel cele două pot diverge tăcut.

    [CORECTAT 2026-08-27 — formularea mea inițială era exagerată] Descrisesem
    consecința ca fiind „concretă". Nu e. Verificat pe toate cele 248 de
    rânduri reale de producție:
      - nicio echipă nu apare în mai mult de o competiție (zero)
      - rulând mutația „caută geamănul fără competiție" contra datelor reale:
        ZERO divergențe față de versiunea corectă

    Motivul e structural: clasamentele există DOAR pentru cele 14 ligi
    domestice. Champions/Europa/Conference League nu au clasament în date,
    deci un club nu poate apărea decât în liga lui.

    Scenariul de mai jos e deci INVENTAT, ales ca ilustrare a mecanismului —
    nu observat. Devine real doar dacă se adaugă vreodată clasamente pentru
    cupele europene, unde același club apare în două competiții: atunci o
    verificare pe nume simplu l-ar propune spre ștergere din propria ligă
    fiindcă apare și în UCL. Gardă pentru acea extindere plauzibilă, nu plasă
    pentru un defect existent."""
    randuri = [
        _r("SC Heerenveen", "Eredivisie", 1),
        _r("Heerenveen", "Jupiler Pro League", 2),
    ]
    duplicate, unice = _imparte(randuri)
    assert duplicate == [], "geamăn din ALTĂ competiție nu contează"
    assert [r["id"] for r in unice] == [2]


def test_ambele_clase_simultan():
    randuri = [
        _r("SC Heerenveen", "Eredivisie", 1),
        _r("Heerenveen", "Eredivisie", 2),      # duplicat
        _r("Schalke", "Bundesliga", 3),          # unic
    ]
    duplicate, unice = _imparte(randuri)
    assert [r["id"] for r in duplicate] == [2]
    assert [r["id"] for r in unice] == [3]


# ── garda de cablare ─────────────────────────────────────────────────────────

def _arbore_main():
    import ast
    import inspect

    from scripts import check_data_health

    return ast.parse(inspect.getsource(check_data_health.main).strip())


def test_clasa_6_compara_efectiv_cu_forma_canonica():
    """GARDĂ, adăugată după ce o mutație a arătat că lipsea: testele de mai sus
    verifică o REPLICĂ a invariantului, deci rămân verzi chiar dacă filtrul din
    codul real devine `if False`. Aici se verifică expresia reală.

    [REFĂCUTĂ 2026-08-27] Prima versiune cerea ca apelul `normalize_team_name`
    să fie chiar ÎN nodul de comparație. A picat la refactorizarea de azi, care
    a scos apelul într-o variabilă (`canonic = normalize_team_name(...)`) —
    cod echivalent, gardă căzută. Era o gardă legată de FORMĂ, nu de invariant.
    Acum acceptă ambele: apel direct în comparație, SAU comparație pe o
    variabilă provenită din acel apel."""
    import ast

    arbore = _arbore_main()

    # Variabilele care primesc rezultatul lui normalize_team_name(...)
    din_normalizare = {
        t.id
        for n in ast.walk(arbore)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", None) == "normalize_team_name"
        for t in n.targets
        if isinstance(t, ast.Name)
    }

    def _implica_forma_canonica(cmp_nod: ast.Compare) -> bool:
        for sub in ast.walk(cmp_nod):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "normalize_team_name":
                return True
            if isinstance(sub, ast.Name) and sub.id in din_normalizare:
                return True
        return False

    comparatii = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Compare)
        and isinstance(n.ops[0], (ast.NotEq, ast.Eq))
        and _implica_forma_canonica(n)
    ]
    assert comparatii, (
        "clasa 6 trebuie sa compare `team` cu forma lui canonica — fara "
        "comparatia reala, filtrul nu detecteaza nimic"
    )


def test_clasa_6_chiar_separa_duplicatele_de_inregistrarile_unice():
    """GARDA CENTRALĂ a corecturii din 2026-08-27.

    Testele de mai sus verifică o REPLICĂ; dacă în codul real cele două liste
    se contopesc la loc, ele rămân verzi. Aici se verifică sursa: trebuie să
    existe DOUĂ colecții distincte, și decizia dintre ele să depindă de o
    verificare de apartenență (`in existente`) — nu de altceva."""
    import inspect

    from scripts import check_data_health

    sursa = inspect.getsource(check_data_health.main)
    assert "duplicate" in sursa and "unice" in sursa, (
        "cele doua clase trebuie sa fie colectii SEPARATE — au actiuni opuse"
    )
    assert "in existente" in sursa, (
        "decizia duplicat-vs-unic trebuie sa se ia verificand daca forma "
        "canonica EXISTA deja in aceeasi competitie"
    )
    assert "REDENUMIT" in sursa.upper(), (
        "raportul trebuie sa spuna explicit ca inregistrarile unice se "
        "REDENUMESC, nu se sterg — altfel se repeta exact eroarea de azi"
    )


def test_geamanul_se_cauta_pe_PERECHEA_competitie_echipa_in_codul_real():
    """GARDĂ adăugată după o mutație NEPRINSĂ (2026-08-27).

    `test_geamanul_se_cauta_in_ACEEASI_competitie` verifică replica locală, deci
    rămâne verde chiar dacă în codul real `existente` devine un set de nume
    simple. Aici se verifică sursa: atât construcția setului, cât și testul de
    apartenență trebuie să folosească o PERECHE, nu un nume singur.

    [CORECTAT 2026-08-27] Prima formulare spunea „consecința acelei mutații ar
    fi reală". Măsurat pe cele 248 de rânduri de producție: mutația produce
    ZERO divergențe azi, fiindcă nicio echipă nu apare în două competiții.
    Valoarea gărzii nu e că previne un bug existent — e că ține invariantul din
    cod aliniat cu cheia `UNIQUE(competition, team)`, ca cele două să nu poată
    diverge tăcut la o extindere viitoare (clasamente pentru cupele europene).

    Motivul pentru care merită totuși păstrată, în ciuda celor de mai sus:
    divergența dintre o verificare și cheia pe care ar trebui s-o reflecte e
    exact genul de defect care nu se manifestă până în ziua în care se
    manifestă costisitor."""
    import ast

    arbore = _arbore_main()

    perechi_construite = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.SetComp) and isinstance(n.elt, ast.Tuple) and len(n.elt.elts) == 2
    ]
    assert perechi_construite, (
        "`existente` trebuie construit din PERECHI (competitie, echipa) — "
        "un set de nume simple ar confunda competitiile intre ele"
    )

    apartenente_pe_pereche = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Compare)
        and any(isinstance(op, ast.In) for op in n.ops)
        and isinstance(n.left, ast.Tuple) and len(n.left.elts) == 2
    ]
    assert apartenente_pe_pereche, (
        "testul de apartenenta trebuie sa fie pe PERECHEA (competitie, canonic), "
        "nu doar pe numele canonic"
    )


def test_raportul_nu_mai_pretinde_neconditionat_ca_exista_geaman():
    """Propoziția care a produs eroarea: „rândul canonic există separat, cu
    date mai noi", afișată pentru ORICE rând necanonic. Nu are voie să
    reapară ca afirmație necondiționată."""
    import inspect

    from scripts import check_data_health

    corp = inspect.getsource(check_data_health.main)
    # Mesajul poate exista, dar DOAR sub ramura `if duplicate:`.
    if "rândul canonic există separat" in corp:
        dupa_duplicate = corp.split("if duplicate:")[-1]
        assert "rândul canonic există separat" in dupa_duplicate.split("if unice:")[0], (
            "afirmatia ca exista geaman canonic e valida DOAR pentru duplicate"
        )


def test_clasa_6_chiar_ridica_alarma():
    """A doua mutație neprinsă: `if orfane: findings += 1` poate fi neutralizat
    fără ca vreun test să cadă. Detectorul care nu alarmează nu e detector."""
    import ast

    arbore = _arbore_main()
    gardat = any(
        isinstance(n, ast.If)
        and getattr(n.test, "id", None) == "orfane"
        and any(
            isinstance(x, ast.AugAssign) and getattr(x.target, "id", None) == "findings"
            for x in ast.walk(n)
        )
        for n in ast.walk(arbore)
    )
    assert gardat, (
        "constatarile clasei 6 trebuie sa incrementeze `findings` sub `if orfane:`"
    )


def test_clasa_6_e_chiar_cablata_in_raport():
    """Fără asta, invariantul poate fi corect și totuși niciodată rulat —
    exact clasa de defect de la ADR-066 (extragere bună, fir netăiat)."""
    import inspect

    from scripts import check_data_health

    sursa = inspect.getsource(check_data_health.main)
    assert "flashscore_standings_snapshot" in sursa, "clasa 6 nu citeste tabela"
    assert "findings}/6" in sursa, "sumarul inca raporteaza 5 clase, nu 6"
