"""Teste pentru scripts/check_identity_drift.py — detectia recurentei
fragmentarii de identitate (ADR-059, sectiunea "Gol ramas deschis").

`compute_drift()` e o functie pura, testata direct, fara Supabase/fisiere.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_identity_drift import compute_drift  # noqa: E402


def _baseline(known=(), hard_conflict=(), unknown_source=()):
    return {
        "reconciled_group_keys": list(known),
        "hard_conflict_keys": list(hard_conflict),
        "unknown_source_keys": list(unknown_source),
    }


def test_no_drift_when_current_matches_baseline_exactly():
    baseline = _baseline(known=["a||b||2026-01-01", "c||d||2026-01-02"])
    diff = compute_drift(baseline, ["a||b||2026-01-01", "c||d||2026-01-02"], [], [])
    assert diff["new_groups"] == []
    assert diff["resolved_groups"] == []
    assert diff["new_hard_conflicts"] == []
    assert diff["new_unknown_source"] == []


def test_new_group_is_detected():
    """Cazul central: un grup absent din baseline apare acum — exact tiparul
    F3-dimineata/TSDB-noaptea din 2026-08-21."""
    baseline = _baseline(known=["a||b||2026-01-01"])
    diff = compute_drift(baseline, ["a||b||2026-01-01", "iberia 1999||jagiellonia||2026-08-27"], [], [])
    assert diff["new_groups"] == ["iberia 1999||jagiellonia||2026-08-27"]


def test_resolved_group_is_reported_but_not_as_new():
    """Un grup care dispare (marcat superseded de o executie aprobata separat)
    apare in `resolved_groups`, nu in `new_groups` — nu e o cauza de esec."""
    baseline = _baseline(known=["a||b||2026-01-01", "c||d||2026-01-02"])
    diff = compute_drift(baseline, ["a||b||2026-01-01"], [], [])
    assert diff["resolved_groups"] == ["c||d||2026-01-02"]
    assert diff["new_groups"] == []


def test_count_unchanged_does_not_hide_a_swapped_group():
    """Motivul explicit pentru care compararea e pe SET, nu pe numar: un grup
    vechi dispare in aceeasi rulare in care unul nou apare — numarul total
    ramane identic (1 == 1), dar setul de chei s-a schimbat complet."""
    baseline = _baseline(known=["old||pair||2026-01-01"])
    diff = compute_drift(baseline, ["new||pair||2026-01-01"], [], [])
    assert diff["baseline_known_count"] == diff["current_known_count"] == 1
    assert diff["new_groups"] == ["new||pair||2026-01-01"]
    assert diff["resolved_groups"] == ["old||pair||2026-01-01"]


def test_new_hard_conflict_is_detected_separately_from_groups():
    baseline = _baseline(known=[], hard_conflict=["liverpool||psg||2025-03-11"])
    diff = compute_drift(
        baseline, [], ["liverpool||psg||2025-03-11", "x||y||2026-05-01"], [],
    )
    assert diff["new_hard_conflicts"] == ["x||y||2026-05-01"]


def test_new_unknown_source_is_detected():
    baseline = _baseline()
    diff = compute_drift(baseline, [], [], ["z||w||2026-06-01"])
    assert diff["new_unknown_source"] == ["z||w||2026-06-01"]


def test_missing_baseline_keys_default_to_empty_not_crash():
    """Un baseline minimal (fara hard_conflict_keys/unknown_source_keys) nu
    trebuie sa arunce — `.get(..., [])` acopera fisiere baseline mai vechi."""
    baseline = {"reconciled_group_keys": ["a||b||2026-01-01"]}
    diff = compute_drift(baseline, ["a||b||2026-01-01"], ["new||conflict||2026-01-01"], [])
    assert diff["new_hard_conflicts"] == ["new||conflict||2026-01-01"]


def test_empty_baseline_flags_every_current_group_as_new():
    """Un baseline gol (inainte de prima captura) trateaza TOT ce se
    descopera azi ca nou — comportament corect, nu o eroare de citit."""
    baseline = _baseline()
    diff = compute_drift(baseline, ["a||b||2026-01-01", "c||d||2026-01-02"], [], [])
    assert len(diff["new_groups"]) == 2
