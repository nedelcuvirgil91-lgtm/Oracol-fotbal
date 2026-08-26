"""Linia de baza a monitorizarii sanatatii datelor.

DE CE EXISTA. `check_data_health.py` a esuat la TOATE cele 5 rulari de pana
acum. Nu pentru ca e stricat — a rulat curat de fiecare data — ci pentru ca
iese cu cod 1 la orice constatare, iar clasa 1 contine constatari care nu se
vor rezolva singure curand. Un monitor permanent rosu nu mai e citit de nimeni,
deci inceteaza sa fie monitor.

CE S-A DOVEDIT, verificat extern 2026-08-25: din cele 4 meciuri Flashscore
raportate ca „fixture-uri trecute fara rezultat", TREI erau de fapt AMANATE —
Braga–Gil Vicente, Rijeka–Dinamo Zagreb, si CFR Cluj–U Cluj (amanat oficial de
LPF, reprogramat pe 8 octombrie). Nu lipseau rezultate; meciurile nu se
jucasera. `match_history` nu poate exprima starea „amanat".

REGULA IMPUSA AICI: intrarile din linia de baza raman AFISATE integral, cu
motivul lor. Se schimba doar codul de iesire. A fi in lista inseamna „stim de
ce", nu „rezolvat".

Fara retea, fara Supabase — functii pure.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_data_health import BASELINE_PATH, load_baseline, split_known


def _r(fid, zi="2026-08-16"):
    return {"fixture_id": fid, "kickoff_date": zi, "league": "L",
            "home_team": "A", "away_team": "B"}


# ── split_known ──────────────────────────────────────────────────────────────

def test_cunoscutele_nu_ridica_alarma():
    noi, cunoscute = split_known([_r("x"), _r("y")], {"x": {"motiv": "amanat"}})
    assert [r["fixture_id"] for r in noi] == ["y"]
    assert [r["fixture_id"] for r in cunoscute] == ["x"]


def test_o_constatare_noua_trece_prin_linia_de_baza():
    """GARDA CENTRALA: linia de baza nu are voie sa ascunda probleme NOI."""
    noi, _ = split_known([_r("necunoscut")], {"altceva": {"motiv": "x"}})
    assert len(noi) == 1


def test_linie_de_baza_goala_lasa_totul_ca_nou():
    noi, cunoscute = split_known([_r("x"), _r("y")], {})
    assert len(noi) == 2 and cunoscute == []


def test_lista_goala_nu_arunca():
    assert split_known([], {"x": {}}) == ([], [])


def test_ordinea_se_pastreaza_in_ambele_liste():
    randuri = [_r("a"), _r("b"), _r("c"), _r("d")]
    noi, cunoscute = split_known(randuri, {"b": {}, "d": {}})
    assert [r["fixture_id"] for r in noi] == ["a", "c"]
    assert [r["fixture_id"] for r in cunoscute] == ["b", "d"]


# ── incarcarea fisierului ────────────────────────────────────────────────────

def test_fisier_lipsa_raporteaza_tot(tmp_path, capsys):
    """GARDA. Degradarea merge spre ZGOMOT, niciodata spre TACERE: un monitor
    care amuteste din cauza unei erori de configurare e mai rau decat unul
    zgomotos, pentru ca pare sanatos."""
    out = load_baseline(tmp_path / "nu_exista.json")
    assert out == {}
    assert "se raporteaza TOATE" in capsys.readouterr().out


def test_fisier_corupt_raporteaza_tot(tmp_path, capsys):
    f = tmp_path / "stricat.json"
    f.write_text("{ asta nu e json", encoding="utf-8")
    assert load_baseline(f) == {}
    assert "se raporteaza TOATE" in capsys.readouterr().out


def test_cheile_de_documentatie_sunt_ignorate(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"_despre": ["text"], "fixture_stale": {"x": {}}}), encoding="utf-8")
    assert set(load_baseline(f)) == {"fixture_stale"}


# ── fisierul REAL din repo ───────────────────────────────────────────────────

def test_fisierul_real_se_incarca():
    b = load_baseline()
    assert "fixture_stale" in b and b["fixture_stale"]


def test_fiecare_intrare_reala_are_motiv_si_marcaj_de_verificare():
    """Fara motiv, o intrare e doar o problema ascunsa sub covor."""
    for fid, intrare in load_baseline()["fixture_stale"].items():
        assert intrare.get("motiv"), f"{fid}: fara motiv"
        assert isinstance(intrare.get("verificat_extern"), bool), f"{fid}: fara marcaj"
        assert intrare.get("verificat_la"), f"{fid}: fara data verificarii"
        if intrare["verificat_extern"]:
            assert intrare.get("sursa"), f"{fid}: pretinde verificare externa fara sursa"


def test_amanarile_confirmate_sunt_marcate_ca_verificate():
    """Starile confirmate pe surse independente — daca cineva le retrogradeaza
    la 'neverificat', testul cade si obliga la o explicatie.

    [EXTINS 2026-08-26] De la 3 la 7. Cele 4 adaugate au fost confirmate pe
    comunicate OFICIALE de liga sau de club (SPFL, Ekstraklasa, KNVB/Eredivisie,
    NEC), nu doar pe agregatoare de scoruri."""
    b = load_baseline()["fixture_stale"]
    for fid in ("flashscore_rX6GkgVb", "flashscore_W4Nlhbwh", "flashscore_KWAKPPdt",
                "flashscore_h4o7BhBL", "flashscore_jFwdNbHj", "flashscore_ILVso29c",
                "flashscore_UozGEIIk"):
        assert b[fid]["verificat_extern"] is True, fid
        assert "AMANAT" in b[fid]["motiv"].upper(), fid


def test_toate_cele_sapte_amanari_flashscore_sunt_documentate():
    """Toate fixture-urile-fantoma Flashscore cunoscute au aceeasi cauza —
    calificarile europene. Daca apare unul NOU, nu e in lista si monitorizarea
    il semnaleaza: exact comportamentul dorit, nu unul de suprimat aici."""
    b = load_baseline()["fixture_stale"]
    flashscore = {k: v for k, v in b.items() if k.startswith("flashscore_")}
    assert len(flashscore) == 7, (
        "numarul s-a schimbat — daca un meci si-a capatat data noua, intrarea "
        "lui e moarta si trebuie STEARSA, nu lasata sa putrezeasca"
    )
    assert all(v["verificat_extern"] for v in flashscore.values())


def test_fisierul_e_json_valid_pe_disc():
    json.loads(Path(BASELINE_PATH).read_text(encoding="utf-8"))
