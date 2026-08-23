"""Teste pentru raportarea motivului la validare de identitate esuata (R3).

CONTEXT: din cele 3 esecuri ale rularii flashscore_weekly_fixtures din
2026-08-23, doua au fost "validare identitate esuata" — un sir generic, fara
niciun detaliu. Erau COMPLET nediagnosticabile: la validare esuata
`persist()` nu se mai apeleaza, deci nu se scrie nici macar RAW in
`flashscore_raw_extraction`. Zero urma forensica.

`validate_flat_identity` respinge pentru un singur motiv posibil
(`missing_natural_key`), deci informatia utila nu e motivul, ci CARE dintre
home_team / away_team / kickoff_date lipsea.

Fara retea, fara Supabase.
"""
from __future__ import annotations

from providers.flashscore.discovery import _describe_identity_gaps


class _Rejected:
    """Aceeasi forma ca `udal_validation.RejectedRecord` (record, reason)."""

    def __init__(self, record: dict, reason: str = "missing_natural_key"):
        self.record = record
        self.reason = reason


def test_raporteaza_exact_campul_lipsa():
    out = _describe_identity_gaps([
        _Rejected({"home_team": "Rennes", "away_team": "PSG", "kickoff_date": None}),
    ])
    assert "kickoff_date" in out
    assert "home_team" not in out, "campurile PREZENTE nu se raporteaza ca lipsa"
    assert "missing_natural_key" in out


def test_raporteaza_mai_multe_campuri_lipsa():
    out = _describe_identity_gaps([
        _Rejected({"home_team": "", "away_team": None, "kickoff_date": "2026-08-23T18:45:00"}),
    ])
    assert "home_team" in out and "away_team" in out
    assert "kickoff_date" not in out


def test_sirul_gol_e_tratat_ca_lipsa_nu_ca_valoare():
    """Un nume gol NU e un nume — altfel s-ar scrie o echipa fara nume."""
    out = _describe_identity_gaps([_Rejected({"home_team": "", "away_team": "X", "kickoff_date": "z"})])
    assert "home_team" in out


def test_cheie_completa_dar_respinsa_e_semnalata_ca_neasteptat():
    """Regula #8: daca respingerea nu se explica prin cheia naturala, NU se
    presupune un motiv — se spune explicit ca e neasteptat."""
    out = _describe_identity_gaps([
        _Rejected({"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-23"}, reason="altceva"),
    ])
    assert "neasteptat" in out
    assert "altceva" in out


def test_mai_multe_randuri_respinse_apar_toate():
    out = _describe_identity_gaps([
        _Rejected({"home_team": None, "away_team": "B", "kickoff_date": "z"}),
        _Rejected({"home_team": "A", "away_team": "B", "kickoff_date": None}),
    ])
    assert out.count("missing_natural_key") == 2
    assert "home_team" in out and "kickoff_date" in out


def test_lista_goala_nu_arunca_si_nu_minte():
    """Fara randuri respinse nu se inventeaza un motiv."""
    out = _describe_identity_gaps([])
    assert "niciun rand respins" in out


def test_record_lipsa_sau_malformat_nu_arunca():
    """Robustete: functia e apelata pe o cale de EROARE — daca ea insasi
    arunca, pierdem si putinul diagnostic pe care il aveam."""
    class _Gol:
        pass

    out = _describe_identity_gaps([_Gol()])
    assert isinstance(out, str) and out
    assert "home_team" in out  # toate cele trei lipsesc


def test_validate_detailed_pastreaza_contractul_lui_validate():
    """`validate()` ramane metoda de contract SyncAdapter, neschimbata —
    `validate_detailed()` e strict aditiva."""
    from providers.flashscore.adapter import FlashscoreAdapter

    assert hasattr(FlashscoreAdapter, "validate")
    assert hasattr(FlashscoreAdapter, "validate_detailed")
