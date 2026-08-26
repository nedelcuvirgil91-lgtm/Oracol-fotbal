"""ADR-069 — retenția Foundation Data Layer, pe sezoane ancorate în date reale.

DE CE ARATĂ AȘA. Retenția e singurul mecanism din acest sistem care ȘTERGE.
Toate celelalte greșeli de până acum au fost recuperabile — un rând scris greșit
s-a putut corecta, o coloană pierdută s-a putut restaura din migrarea anterioară.
O ștergere nu. De aceea testele de aici verifică cu prioritate ce se întâmplă
când ceva NU e sigur: fără calendar, fără dată pe rând, cu backup eșuat, cu
config necitibil. În toate, răspunsul corect e același — nu se șterge.

Cifrele folosite ca fixture sunt cele MĂSURATE pe producție (2026-08-26):
prag conservator 2021-02-21, 459 candidați, 311 rânduri fără dată, 12.573 total.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

from datetime import date

import pytest

from providers.flashscore import retention as R


# ── pragul: ancorat în date reale, niciodată inventat ────────────────────────

def test_pragul_e_cel_mai_devreme_start_minus_cinci_ani():
    """Cifrele REALE din `competition_season`: MLS începe cel mai devreme."""
    starts = ["2026-08-21", "2026-02-21", "2026-08-28", "2026-07-17"]
    assert R.compute_retention_threshold(starts) == "2021-02-21"


def test_pragul_foloseste_minimul_nu_maximul_si_nu_media():
    """GARDĂ. `max` ar da 2021-08-28 și ar șterge rânduri încă în fereastră
    pentru MLS — exact eroarea pe care conservatorismul din ADR o evită."""
    assert R.compute_retention_threshold(["2026-02-21", "2026-08-28"]) == "2021-02-21"


def test_fara_niciun_calendar_nu_exista_prag():
    """'Nu știu unde e pragul' NU degenerează într-un prag implicit."""
    assert R.compute_retention_threshold([]) is None
    assert R.compute_retention_threshold(["", None]) is None


def test_starturile_neparsabile_sunt_ignorate_nu_ghicite():
    assert R.compute_retention_threshold(["nu-e-o-data", "2026-02-21"]) == "2021-02-21"
    assert R.compute_retention_threshold(["nu-e-o-data"]) is None


def test_pragul_respecta_numarul_de_sezoane_pastrate():
    assert R.compute_retention_threshold(["2026-02-21"], seasons_kept=6) == "2021-02-21"
    assert R.compute_retention_threshold(["2026-02-21"], seasons_kept=1) == "2026-02-21"
    assert R.compute_retention_threshold(["2026-02-21"], seasons_kept=3) == "2024-02-21"


def test_seasons_kept_invalid_arunca():
    with pytest.raises(ValueError):
        R.compute_retention_threshold(["2026-02-21"], seasons_kept=0)


def test_29_februarie_coboara_in_directia_sigura():
    """2024-02-29 minus 5 ani = 2019-02-29, care nu există. Coborârea la 28
    face pragul mai VECHI cu o zi, deci păstrează un rând în plus — niciodată
    șterge unul în plus."""
    assert R.compute_retention_threshold(["2024-02-29"]) == "2019-02-28"
    assert R._minus_years(date(2024, 2, 29), 5) == date(2019, 2, 28)


# ── împărțirea rândurilor ────────────────────────────────────────────────────

def _r(rid, d):
    return {"id": rid, "meeting_date": d}


def test_randurile_vechi_sunt_candidate_cele_recente_nu():
    p = R.partition_by_retention(
        [_r(1, "1967-11-10"), _r(2, "2026-08-25"), _r(3, "2019-03-04")],
        "2021-02-21", "meeting_date",
    )
    assert [r["id"] for r in p["candidati"]] == [1, 3]
    assert [r["id"] for r in p["pastrate"]] == [2]


def test_randul_exact_pe_prag_se_PASTREAZA():
    """Comparația e strict `<`. Un rând chiar în ziua de start a celui mai
    vechi sezon păstrat aparține acelui sezon — nu iese odată cu cele
    dinaintea lui."""
    p = R.partition_by_retention([_r(1, "2021-02-21")], "2021-02-21", "meeting_date")
    assert p["candidati"] == []
    assert len(p["pastrate"]) == 1


def test_randurile_fara_data_sunt_o_clasa_PROPRIE():
    """GARDA CENTRALĂ. Vechime necunoscută nu înseamnă vechime mare. Cele 311
    rânduri reale din această situație nu au voie să ajungă niciodată candidate
    — nici măcar prin contopire tăcută cu 'păstrate', fiindcă atunci nimeni
    n-ar mai ști că există."""
    p = R.partition_by_retention(
        [_r(1, None), _r(2, ""), {"id": 3}, _r(4, "1967-11-10")],
        "2021-02-21", "meeting_date",
    )
    assert [r["id"] for r in p["fara_data"]] == [1, 2, 3]
    assert [r["id"] for r in p["candidati"]] == [4]
    assert p["pastrate"] == []


def test_data_neparsabila_e_tratata_ca_necunoscuta_nu_ca_veche():
    p = R.partition_by_retention([_r(1, "data-stricata")], "2021-02-21", "meeting_date")
    assert len(p["fara_data"]) == 1
    assert p["candidati"] == []


def test_fara_prag_nimic_nu_e_candidat():
    """Absența reperului nu autorizează nicio ștergere."""
    p = R.partition_by_retention(
        [_r(1, "1967-11-10"), _r(2, "1974-02-23")], None, "meeting_date",
    )
    assert p["candidati"] == []
    assert len(p["pastrate"]) == 2


def test_lista_goala_nu_arunca():
    p = R.partition_by_retention([], "2021-02-21", "meeting_date")
    assert p == {"candidati": [], "pastrate": [], "fara_data": []}


def test_proportiile_reale_de_productie():
    """Reconstituie forma măsurată: 12.573 rânduri, 459 candidați, 311 fără
    dată. Dacă logica se schimbă, cifrele care au motivat ADR-ul nu mai ies."""
    randuri = (
        [_r(i, "1970-01-01") for i in range(459)]
        + [_r(1000 + i, None) for i in range(311)]
        + [_r(9000 + i, "2026-08-01") for i in range(11803)]
    )
    p = R.partition_by_retention(randuri, "2021-02-21", "meeting_date")
    assert len(p["candidati"]) == 459
    assert len(p["fara_data"]) == 311
    assert len(p["pastrate"]) == 11803
    assert len(randuri) == 12573


# ── integritate ──────────────────────────────────────────────────────────────

def test_integritatea_trece_cand_aritmetica_si_protejatele_sunt_ok():
    v = R.verify_integrity(inainte=12573, sterse=459, dupa=12114,
                           fara_data_inainte=311, fara_data_dupa=311)
    assert v["ok"] is True


def test_integritatea_cade_daca_s_a_sters_mai_mult_decat_s_a_cerut():
    v = R.verify_integrity(inainte=12573, sterse=459, dupa=12000,
                           fara_data_inainte=311, fara_data_dupa=311)
    assert v["ok"] is False
    assert v["aritmetica_ok"] is False
    assert v["randuri_protejate_intacte"] is True


def test_integritatea_cade_separat_daca_s_au_atins_randurile_protejate():
    """Cele două invariante spun lucruri DIFERITE — un raport care le contopește
    nu ajută pe nimeni să înțeleagă ce s-a stricat."""
    v = R.verify_integrity(inainte=12573, sterse=459, dupa=12114,
                           fara_data_inainte=311, fara_data_dupa=300)
    assert v["ok"] is False
    assert v["aritmetica_ok"] is True
    assert v["randuri_protejate_intacte"] is False


def test_integritatea_raporteaza_cifrele_nu_doar_un_bool():
    v = R.verify_integrity(inainte=100, sterse=10, dupa=90,
                           fara_data_inainte=5, fara_data_dupa=5)
    assert v["randuri_dupa_asteptat"] == 90
    assert v["randuri_inainte"] == 100 and v["randuri_sterse"] == 10


# ── flag-ul: pornit STINS, degradare spre a NU sterge ────────────────────────

def test_flagul_e_stins_implicit(monkeypatch):
    import supabase_client
    monkeypatch.setattr(supabase_client, "load_config", lambda default=None: {})
    assert R.delete_enabled() is False


def test_doar_True_explicit_activeaza(monkeypatch):
    """Nu „truthy" — un `1`, un `"da"` sau un `"true"` rămas dintr-o editare
    manuală de config nu au voie să pornească o ștergere."""
    import supabase_client
    for valoare in (True, False, 1, 0, "true", "da", None, [], {}):
        monkeypatch.setattr(
            supabase_client, "load_config",
            lambda default=None, v=valoare: {R.FLAG_DELETE_ENABLED: v},
        )
        assert R.delete_enabled() is (valoare is True), f"valoare={valoare!r}"


def test_config_necitibil_lasa_stergerea_OPRITA(monkeypatch):
    """Direcție opusă lui ADR-063: acolo fallback-ul e `True` fiindcă degradarea
    ar însemna mai puține meciuri; aici ar însemna ȘTERGERE pe o eroare."""
    import supabase_client

    def cade(default=None):
        raise RuntimeError("supabase indisponibil")

    monkeypatch.setattr(supabase_client, "load_config", cade)
    assert R.delete_enabled() is False


# ── cele trei porti inainte de DELETE ────────────────────────────────────────

class _Tabela:
    def __init__(self, jurnal, nume, date_map):
        self._j, self._n, self._d = jurnal, nume, date_map
        self._sterge = False
        self._ids = None

    def select(self, *a, **k): return self
    def delete(self): self._sterge = True; return self
    def in_(self, col, values): self._ids = (col, list(values)); return self
    def eq(self, *a, **k): return self
    def single(self): return self

    def execute(self):
        if self._sterge:
            self._j.append(("DELETE", self._n, self._ids))
            return type("R", (), {"data": []})()
        return type("R", (), {"data": self._d.get(self._n, [])})()


class _Client:
    def __init__(self, date_map):
        self.jurnal: list = []
        self._d = date_map

    def table(self, nume):
        return _Tabela(self.jurnal, nume, self._d)


def _mediu(monkeypatch, *, flag=True, backup_ok=True):
    date_map = {
        "competition_season": [{"start_date": "2026-02-21"}],
        "flashscore_match_context": [
            {"id": 1, "meeting_date": "1967-11-10"},
            {"id": 2, "meeting_date": "2026-08-01"},
            {"id": 3, "meeting_date": None},
        ],
    }
    client = _Client(date_map)
    import database.queries as q
    import providers.flashscore.backup as B
    import supabase_client
    monkeypatch.setattr(q, "get_client", lambda: client)
    monkeypatch.setattr(supabase_client, "load_config",
                        lambda default=None: {R.FLAG_DELETE_ENABLED: flag})
    monkeypatch.setattr(B, "run_backup", lambda *a, **k: {"ok": backup_ok})
    return client


def test_dry_run_nu_sterge_nimic_chiar_cu_flagul_pornit(monkeypatch):
    c = _mediu(monkeypatch, flag=True)
    raport = R.execute_retention(dry_run=True)
    assert raport["delete_executat"] is False
    assert raport["motiv_fara_stergere"] == "dry_run"
    assert not [x for x in c.jurnal if x[0] == "DELETE"]


def test_flagul_stins_opreste_stergerea(monkeypatch):
    c = _mediu(monkeypatch, flag=False)
    raport = R.execute_retention(dry_run=False)
    assert raport["delete_executat"] is False
    assert R.FLAG_DELETE_ENABLED in raport["motiv_fara_stergere"]
    assert not [x for x in c.jurnal if x[0] == "DELETE"]


def test_backupul_esuat_OPRESTE_stergerea(monkeypatch):
    """Poarta care lipsește cel mai des: fără ea, prima ștergere pe care ai
    vrea s-o poți întoarce e exact cea pentru care n-ai backup."""
    c = _mediu(monkeypatch, flag=True, backup_ok=False)
    raport = R.execute_retention(dry_run=False)
    assert raport["delete_executat"] is False
    assert "backup" in raport["motiv_fara_stergere"]
    assert not [x for x in c.jurnal if x[0] == "DELETE"]


def test_cu_toate_portile_deschise_sterge_doar_candidatii(monkeypatch):
    c = _mediu(monkeypatch, flag=True, backup_ok=True)
    raport = R.execute_retention(dry_run=False)
    stergeri = [x for x in c.jurnal if x[0] == "DELETE"]
    assert len(stergeri) == 1
    _, tabela, (coloana, ids) = stergeri[0]
    assert tabela == "flashscore_match_context"
    assert coloana == "id"
    assert ids == [1], "doar randul din 1967; nici cel recent, nici cel fara data"
    assert raport["delete_executat"] is True


def test_stergerea_se_face_pe_ID_uri_nu_pe_conditia_de_data(monkeypatch):
    """GARDĂ. Un `DELETE ... WHERE meeting_date < prag` ar re-evalua filtrul în
    momentul ștergerii și ar putea prinde rânduri apărute între raport și
    execuție — rânduri pe care nimeni nu le-a văzut și care nu sunt în backup."""
    c = _mediu(monkeypatch, flag=True)
    R.execute_retention(dry_run=False)
    _, _, (coloana, _) = [x for x in c.jurnal if x[0] == "DELETE"][0]
    assert coloana == "id"


def test_raportul_arata_pragul_si_cheia_folosita(monkeypatch):
    _mediu(monkeypatch, flag=False)
    raport = R.execute_retention(dry_run=True)
    assert raport["prag"] == "2021-02-21"
    assert "season" in raport["cheie"] and "captured_at" in raport["cheie"]
    t = raport["tabele"]["flashscore_match_context"]
    assert t["cheie_de_data"] == "meeting_date"
    assert (t["candidati"], t["pastrate"], t["fara_data"]) == (1, 1, 1)


# ── scope: nu se largeste tacit ──────────────────────────────────────────────

def test_scope_ul_de_stergere_e_o_singura_tabela():
    """ADR-069 decizia 5. Dacă cineva adaugă o tabelă aici, o face deliberat —
    nu prin extinderea tăcută a unei bucle."""
    assert R.RETENTION_DELETE_SCOPE == ("flashscore_match_context",)


def test_istoricul_ML_si_odds_history_nu_sunt_NICIODATA_in_scope():
    """Regula moștenită din ADR-044, netransgresabilă: istoricul ML își are
    adâncimea deliberat, iar `odds_history` e document Frozen."""
    interzise = {"match_history", "match_events", "player_match_stats", "odds_history"}
    assert interzise.isdisjoint(R.RETENTION_DATE_SOURCES)
    assert interzise.isdisjoint(R.RETENTION_DELETE_SCOPE)


def test_captured_at_nu_e_cheie_de_retentie_pentru_nicio_tabela():
    """`captured_at` spune când am văzut NOI pagina, nu la ce sezon aparține
    faptul — un rând capturat ieri poate descrie un meci din 1967."""
    assert "captured_at" not in R.RETENTION_DATE_SOURCES.values()


def test_tabelele_fara_data_de_meci_raman_in_afara_scopului():
    """`flashscore_raw_extraction` are data doar în slug; standings e un
    snapshot al clasamentului curent. Ambele cer decizie proprie."""
    assert "flashscore_raw_extraction" not in R.RETENTION_DATE_SOURCES
    assert "flashscore_standings_snapshot" not in R.RETENTION_DATE_SOURCES


# ── cablarea in night_sync ───────────────────────────────────────────────────

def _arbore_stage_cleanup():
    import ast
    import inspect

    from sync import run_night

    return ast.parse(inspect.getsource(run_night._stage_cleanup).strip())


def test_raportul_e_chiar_cablat_in_night_sync():
    """Fără asta, modulul poate fi corect și totuși niciodată rulat — clasa de
    defect de la ADR-066 (extragere bună, fir netăiat)."""
    import ast

    arbore = _arbore_stage_cleanup()
    apeluri = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "execute_retention"
    ]
    assert apeluri, "`_stage_cleanup` nu apeleaza `execute_retention`"


def test_night_sync_apeleaza_STRICT_in_dry_run():
    """GARDA CRITICĂ. Orchestratorul de noapte rulează nesupravegheat. Un
    `dry_run=False` strecurat aici ar transforma un raport într-o ștergere
    automată — exact ce ADR-069 interzice (prima rulare reală cere aprobare
    separată)."""
    import ast

    arbore = _arbore_stage_cleanup()
    apel = next(
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "execute_retention"
    )
    dry = [k for k in apel.keywords if k.arg == "dry_run"]
    assert dry, "`dry_run` trebuie dat EXPLICIT, niciodata lasat pe implicit"
    assert isinstance(dry[0].value, ast.Constant) and dry[0].value.value is True, (
        "night_sync nu are voie sa ceara altceva decat dry_run=True"
    )
    assert not apel.args, "niciun argument pozitional — dry_run trebuie sa fie vizibil dupa nume"


def test_raportul_pe_season_nu_a_fost_inlocuit():
    """Contrapondere: ADR-069 ADAUGĂ o cheie, nu taie raportul existent. Cele
    două spun lucruri diferite și ambele sunt oneste."""
    import inspect

    from sync import run_night

    sursa = inspect.getsource(run_night._stage_cleanup)
    assert "build_cleanup_dry_run_report" in sursa
    assert "cleanup_candidates" in sursa
