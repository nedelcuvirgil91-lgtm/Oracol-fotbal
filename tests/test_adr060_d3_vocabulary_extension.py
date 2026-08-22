"""Gărzi de regresie pentru extinderea vocabularului D3 (ADR-060, Faza 2,
2026-08-22, `mappings.py`).

Aceste 53 de identități au fost descoperite mecanic (`scripts/
detect_identity_alias_candidates.py`, GitHub Actions run 32561462931), fără
nicio potrivire fuzzy — doar dovadă factuală (același meci sub două nume) +
veto absolut (dacă s-au înfruntat vreodată, sunt cluburi diferite). Testul nu
re-verifică dovada (asta a rulat deja pe date reale) — verifică doar că
vocabularul din `mappings.py` reflectă corect decizia luată, ca un refactor
viitor să nu o poată strica tăcut.
"""
from __future__ import annotations

from mappings import normalize_team_name


# (canonic, [alias1, alias2, ...]) — exact grupurile aplicate în mappings.py.
CLUSTERS: list[tuple[str, list[str]]] = [
    # Extinderi ale unor chei canonice deja existente înainte de ADR-060.
    ("Twente", ["FC Twente '65"]),
    ("Marseille", ["Olympique Marseille"]),
    ("Nijmegen", ["NEC", "NEC Nijmegen"]),
    ("Benfica", ["SL Benfica"]),
    ("Sporting CP", ["Sp Lisbon"]),
    ("Braga", ["Sp Braga", "Sporting Braga"]),
    # 47 de chei canonice noi.
    ("AZ Alkmaar", ["AZ"]),
    ("Ad. Demirspor", ["Adana Demirspor"]),
    ("Ajaccio", ["AC Ajaccio"]),
    ("Almere City FC", ["Almere City"]),
    ("Belenenses", ["Belenenses SAD"]),
    ("Bielefeld", ["Arminia Bielefeld"]),
    ("Boavista", ["Boavista FC"]),
    ("Bodrum FK", ["Bodrumspor"]),
    ("Bordeaux", ["Girondins Bordeaux"]),
    ("Buyuksehyr", ["İstanbul Başakşehir"]),
    ("CD Nacional", ["Nacional"]),
    ("CD Santa Clara", ["Santa Clara"]),
    ("CD Tondela", ["Tondela"]),
    ("CF Estrela da Amadora", ["Estrela"]),
    ("Cambuur", ["SC Cambuur"]),
    ("Casa Pia AC", ["Casa Pia"]),
    ("Estoril", ["GD Estoril", "GD Estoril Praia"]),
    ("Eyupspor", ["Eyüpspor"]),
    ("FC Arouca", ["Arouca"]),
    ("FC Famalicão", ["Famalicao"]),
    ("FC Groningen", ["Groningen"]),
    ("FC Utrecht", ["Utrecht"]),
    ("FC Vizela", ["Vizela"]),
    ("FC Volendam", ["Volendam"]),
    ("GD Chaves", ["Chaves"]),
    ("Gaziantep", ["Gaziantep FK"]),
    ("Gil Vicente", ["Gil Vicente FC"]),
    ("Goztep", ["Goztepe", "Göztepe"]),
    ("Greuther Furth", ["SpVgg Greuther Fürth 1903"]),
    ("Guimaraes", ["Vitória Guimarães", "Vitória SC"]),
    ("Heracles Almelo", ["Heracles"]),
    ("Hertha", ["Hertha BSC"]),
    ("Kasimpasa", ["Kasımpaşa SK"]),
    ("Maritimo", ["CS Marítimo"]),
    ("Moreirense FC", ["Moreirense"]),
    ("Pacos Ferreira", ["Paços de Ferreira"]),
    ("Portimonense SC", ["Portimonense"]),
    ("Rio Ave FC", ["Rio Ave"]),
    ("Rizespor", ["Çaykur Rizespor"]),
    ("SBV Excelsior", ["Excelsior"]),
    ("SC Farense", ["Farense"]),
    ("Sampdoria", ["UC Sampdoria"]),
    ("Spezia", ["Spezia Calcio"]),
    ("Troyes", ["ESTAC Troyes"]),
    ("Vitesse", ["SBV Vitesse"]),
    ("Waalwijk", ["RKC Waalwijk"]),
    ("Willem II", ["Willem II Tilburg"]),
]

# Cele 3 coincidențe respinse explicit de mecanismul de veto (au meciuri
# directe reale în match_history) — trebuie să rămână identități distincte.
VETOED_PAIRS = [
    ("FCSB", "Sepsi OSK"),
    ("CFR Cluj", "Chindia Targoviste"),
    ("Din. Bucuresti", "Farul Constanța"),
]


def test_toate_cele_53_clustere_unifica_corect():
    for canon, aliases in CLUSTERS:
        canon_norm = normalize_team_name(canon)
        for alias in aliases:
            assert normalize_team_name(alias) == canon_norm, (
                f"{alias!r} -> {normalize_team_name(alias)!r}, "
                f"asteptat {canon_norm!r} (canonic {canon!r})"
            )


def test_fiecare_alias_normalizeaza_stabil_idempotent():
    """normalize_team_name(normalize_team_name(x)) == normalize_team_name(x) —
    aplicarea repetată nu trebuie să oscileze."""
    for canon, aliases in CLUSTERS:
        for name in [canon, *aliases]:
            once = normalize_team_name(name)
            twice = normalize_team_name(once)
            assert once == twice


def test_perechile_vetoate_raman_distincte():
    """Regresia critică: mecanismul de veto (scripts/
    detect_identity_alias_candidates.py) a exclus explicit aceste 3 perechi
    fiindcă au meciuri directe reale — un refactor care le-ar uni ar
    contopi două cluburi diferite (regresie clasa 141+ fuziuni false, v1.2)."""
    for a, b in VETOED_PAIRS:
        assert normalize_team_name(a) != normalize_team_name(b), (
            f"{a!r} si {b!r} nu au voie sa devina aceeasi identitate — "
            "au meciuri directe reale intre ele."
        )


def test_niciun_alias_nou_nu_e_deja_folosit_pentru_alt_canonic():
    """Fiecare alias nou trebuie să aparțină exact unui singur canonic — o
    coliziune ar însemna că am asignat din greșeală același nume brut la
    două identități diferite."""
    from mappings import ALIAS_TO_CANONICAL

    for canon, aliases in CLUSTERS:
        for alias in aliases:
            assert ALIAS_TO_CANONICAL[alias.lower()] == normalize_team_name(canon)


def test_clusterele_cu_trei_nume_sunt_complet_tranzitive():
    """Cele 4 clustere de 3 nume (Braga/Sp Braga/Sporting Braga etc.) trebuie
    să fie complet conectate — nu doar pereche-cu-pereche, ci toate 3
    normalizând identic."""
    triple = [
        ("Braga", "Sp Braga", "Sporting Braga"),
        ("Estoril", "GD Estoril", "GD Estoril Praia"),
        ("Nijmegen", "NEC", "NEC Nijmegen"),
        ("Guimaraes", "Vitória Guimarães", "Vitória SC"),
    ]
    for a, b, c in triple:
        na, nb, nc = normalize_team_name(a), normalize_team_name(b), normalize_team_name(c)
        assert na == nb == nc, f"{a!r}/{b!r}/{c!r} nu formeaza o singura identitate: {na!r}/{nb!r}/{nc!r}"
