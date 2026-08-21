"""
Invarianti de identitate a echipelor — ADR-058 (F2).

Doua familii de teste, cu scopuri diferite:

  (A) GARDA AST — impune Decizia ADR-058 §2.2: "orice writer care persista
      un nume de echipa trece prin normalize_team_name()". E o garda
      STRUCTURALA: un writer viitor, catre o tabela cu coloane de echipa,
      nu poate ocoli normalizarea fara sa pice acest test. Precedent de
      stil: tests/test_canonical_feature_ownership.py.

  (B) INVARIANTI DE VOCABULAR — impun Decizia ADR-058 §2.4 ("nicio fuziune
      fara dovada"): cluburi distincte cu nume similare NU au voie sa
      convearga. Acestea sunt testele care ar fi prins regresia v1.2
      (fuzzy prefix-matching, 141+ coliziuni).

IMPORTANT: testele care depind de F3 (vocabularul extins) sunt marcate
`skip` explicit — F3 e BLOCAT la data scrierii lor (vezi ADR-058 §7).
Sunt scrise acum, complet, ca sa fie activate prin stergerea unei singure
linii cand F3 primeste GO — nu rescrise atunci de la zero.

Fara retea, fara Supabase.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import database.queries as q
import shadow_testing as st
import supabase_client as sb
from mappings import ALIAS_TO_CANONICAL, TEAM_ALIASES, normalize_team_name

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tabele care contin coloane cu NUME de echipa (nu 'home'/'away' ca eticheta).
# Verificat prin inspectia schemei live, 2026-08-21.
_TEAM_NAME_TABLES = {
    "match_history",
    "flashscore_match_context",
    "flashscore_standings_snapshot",
    "shadow_predictions",
    "consensus_capture_samples",
}

# RPC-uri care scriu nume de echipa (ocolesc `.table(...)`).
_TEAM_NAME_RPCS = {"upsert_match_canonical", "upsert_matches_canonical"}

# Orice apel care conteaza drept "am normalizat".
_NORMALIZERS = {
    "normalize_team_name",
    "_normalize_team_fields",
    "_normalize_context_team_fields",
}

_MODULES_WITH_WRITERS = [
    "database/queries.py",
    "supabase_client.py",
    "shadow_testing.py",
]


# ════════════════════════════════════════════════════════════════════════
# (A) GARDA AST
# ════════════════════════════════════════════════════════════════════════

def _string_constants(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _called_names(node: ast.AST) -> set[str]:
    """Numele tuturor functiilor apelate in subarbore — atat `f()` cat si
    `obj.f()`."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


def _writes_team_names(fn: ast.FunctionDef) -> bool:
    """Functia scrie intr-o tabela/RPC cu nume de echipa?"""
    consts = _string_constants(fn)
    calls = _called_names(fn)
    hits_table = bool(consts & _TEAM_NAME_TABLES) and bool(calls & {"upsert", "insert"})
    hits_rpc = bool(consts & _TEAM_NAME_RPCS) and "rpc" in calls
    return hits_table or hits_rpc


def _collect_writer_functions() -> list[tuple[str, ast.FunctionDef]]:
    found: list[tuple[str, ast.FunctionDef]] = []
    for rel in _MODULES_WITH_WRITERS:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and _writes_team_names(node):
                found.append((rel, node))
    return found


def test_ast_guard_finds_the_known_writers():
    """Meta-test: garda trebuie sa VADA writerii reali. Daca detectia se
    strica (refactor, redenumire), restul gardei devine vacuu adevarata —
    exact modul in care o garda AST moare in tacere."""
    names = {fn.name for _, fn in _collect_writer_functions()}
    for expected in (
        "upsert_match",
        "upsert_matches_bulk",
        "upsert_match_and_get_id",
        "upsert_match_context",
        "upsert_standings_snapshot",
        "upsert_match_history",
        "log_shadow_prediction",
        "save_consensus_capture_sample",
    ):
        assert expected in names, (
            f"garda AST nu mai detecteaza writer-ul {expected!r} — detectia s-a stricat, "
            f"nu writer-ul. Detectati: {sorted(names)}"
        )


def test_every_team_name_writer_normalizes():
    """INVARIANTA CENTRALA (ADR-058 §2.2). O tabela noua cu coloane de
    echipa, scrisa fara normalizare, pica aici."""
    offenders = [
        f"{rel}::{fn.name}"
        for rel, fn in _collect_writer_functions()
        if not (_called_names(fn) & _NORMALIZERS)
    ]
    assert not offenders, (
        "Writeri care persista nume de echipa FARA normalizare: "
        + ", ".join(offenders)
        + " — vezi ADR-058 §2.2."
    )


# ════════════════════════════════════════════════════════════════════════
# (B) INVARIANTI DE VOCABULAR — valabili AZI, inainte de F3
# ════════════════════════════════════════════════════════════════════════

def test_normalization_is_idempotent():
    """normalize(normalize(x)) == normalize(x) pe TOT vocabularul curent."""
    for alias in ALIAS_TO_CANONICAL:
        once = normalize_team_name(alias)
        assert normalize_team_name(once) == once, f"neidempotent pentru {alias!r}"


def test_no_alias_chains():
    """Nicio valoare canonica nu are voie sa fie ea insasi alias al altui
    canonic — un lant A->B->C ar face rezultatul dependent de ordinea de
    iterare a dictionarului."""
    canonicals = set(TEAM_ALIASES.keys())
    for canonical, aliases in TEAM_ALIASES.items():
        for alias in aliases:
            assert alias not in canonicals or alias == canonical, (
                f"{alias!r} e alias al lui {canonical!r} DAR si cheie canonica proprie — lant de alias-uri"
            )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Clasa C, ADR-058: cluburi DISTINCTE cu nume similare.
        ("Forest Green", "Nottingham Forest"),
        ("Atletico-MG", "Atletico Madrid"),
        ("Atletico GO", "Atletico Madrid"),
        ("Wisla Krakow", "Wisla Plock"),
        ("Dundee FC", "Dundee Utd"),
        ("Inter Escaldes", "Inter Milan"),
        ("Paris FC", "Paris Saint-Germain"),  # regresia v1.2, exact cazul citat
    ],
)
def test_distinct_clubs_never_merge(a, b):
    """Clasa C nu are voie sa convearga NICIODATA — nici azi, nici dupa F3."""
    assert normalize_team_name(a) != normalize_team_name(b), (
        f"{a!r} si {b!r} sunt cluburi DIFERITE dar normalizeaza la aceeasi valoare "
        f"({normalize_team_name(a)!r}) — fuziune interzisa, ADR-058 §2.4 / clasa C."
    )


def test_unknown_team_stays_unchanged():
    """Decizia ADR-058 §2.3: fara potrivire exacta, numele ramane NESCHIMBAT.
    Niciodata ghicit."""
    for unknown in ("FC O Echipa Complet Inexistenta", "Zzz United 1899"):
        assert normalize_team_name(unknown) == unknown


def test_empty_alias_list_still_yields_self_mapping():
    """Verificarea V1 din auditul F0, codificata permanent: o cheie canonica
    cu lista goala de alias-uri TREBUIE sa fie auto-mapata
    (`mappings.py:371`, necorditionat, inaintea buclei de alias-uri).
    Cele 54 de baze propuse pentru F3 depind integral de asta."""
    empty_keyed = [c for c, aliases in TEAM_ALIASES.items() if not aliases]
    assert empty_keyed, "nicio cheie canonica fara alias-uri — testul si-a pierdut subiectul"
    for canonical in empty_keyed:
        assert normalize_team_name(canonical) == canonical
        assert ALIAS_TO_CANONICAL[canonical.lower()] == canonical


def test_writer_normalization_helpers_exist_and_are_pure():
    """Cele trei helper-e de normalizare nu au voie sa mute dict-ul primit —
    apelantii isi refolosesc randurile (ex. persistence.py transmite acelasi
    `base` mai departe dupa upsert)."""
    row = {"home_team": "Man Utd", "away_team": "Inter", "subject_team": "Bayern"}
    snapshot = dict(row)
    q._normalize_team_fields(row)
    q._normalize_context_team_fields(row)
    assert row == snapshot, "helper-ul a mutat dict-ul apelantului"


def test_context_normalizer_handles_all_three_columns():
    out = q._normalize_context_team_fields(
        {"home_team": "Man Utd", "away_team": "Inter", "subject_team": "Bayern", "category": "h2h"}
    )
    assert out["home_team"] == "Manchester United"
    assert out["away_team"] == "Inter Milan"
    assert out["subject_team"] == "Bayern Munich"
    assert out["category"] == "h2h", "cheile non-echipa nu au voie sa fie atinse"


def test_context_normalizer_tolerates_missing_keys():
    row = {"context_match_id": 7, "category": "form"}
    assert q._normalize_context_team_fields(row) == row


# ── Writeri: normalizarea chiar ajunge in payload ────────────────────────

class _CapturingTable:
    def __init__(self, sink):
        self.sink = sink

    def upsert(self, payload, **kwargs):
        self.sink.append(payload)
        return self

    def execute(self):
        class _R:
            data = []
        return _R()


class _CapturingClient:
    def __init__(self):
        self.payloads = []

    def table(self, _name):
        return _CapturingTable(self.payloads)


def test_log_shadow_prediction_normalizes(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(sb, "get_client", lambda: client)
    ok = st.log_shadow_prediction(
        fixture_id="x1", experiment_name="e", experiment_version="v1",
        home_xg=1.0, away_xg=1.0, prob_home=0.4, prob_draw=0.3, prob_away=0.3,
        home_team="Man Utd", away_team="Inter",
    )
    assert ok is True
    sent = client.payloads[0]
    assert sent["home_team"] == "Manchester United"
    assert sent["away_team"] == "Inter Milan"


def test_save_consensus_capture_sample_normalizes(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(sb, "get_client", lambda: client)
    ok = sb.save_consensus_capture_sample(
        fixture_id="x2", league="Premier League",
        home_team="Man Utd", away_team="Inter",
        kickoff_date="2026-01-01", raw_predictions=[],
    )
    assert ok is True
    sent = client.payloads[0]
    assert sent["home_team"] == "Manchester United"
    assert sent["away_team"] == "Inter Milan"


# ════════════════════════════════════════════════════════════════════════
# (C) TESTE F3 — ACTIVE de la 2026-08-21 (vocabularul extins, ADR-058 §7)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("suffixed", "expected"),
    [
        ("Ajax (NED)", "Ajax"),
        ("AC Milan (ITA)", "AC Milan"),
        ("Gent (BEL)", "Gent"),
        ("Din. Zagreb (CRO)", "Din. Zagreb"),
        ("Lincoln Red Imps (GIB)", "Lincoln Red Imps"),
    ],
)
def test_f3_country_suffix_resolves(suffixed, expected):
    assert normalize_team_name(suffixed) == expected


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("Nottingham", "Nottingham Forest"),
        ("Atl. Madrid", "Atletico Madrid"),
        ("B. Monchengladbach", "Borussia Monchengladbach"),
        ("Schalke", "Schalke 04"),
        ("FC Schalke 04", "Schalke 04"),
        ("Leuven", "Oud-Heverlee Leuven"),
        ("Telstar", "Telstar 1963"),
        ("Sittard", "Fortuna Sittard"),
        ("For Sittard", "Fortuna Sittard"),
        ("Zwolle", "PEC Zwolle"),
        ("Heerenveen", "SC Heerenveen"),
        ("sc Heerenveen", "SC Heerenveen"),
    ],
)
def test_f3_abbreviations_resolve(variant, expected):
    assert normalize_team_name(variant) == expected


@pytest.mark.parametrize(
    "suffixed_without_twin",
    ["Dinamo City (ALB)", "Tre Fiori (SAN)", "Inter Escaldes (AND)"],
)
def test_f3_suffixed_without_known_base_stays_unchanged(suffixed_without_twin):
    """Cele 98 de nume cu sufix FARA geamana in match_history nu au voie sa
    fie modificate — regula de strip e cheie de CAUTARE, nu iesire
    (ADR-058 §2.3)."""
    assert normalize_team_name(suffixed_without_twin) == suffixed_without_twin
