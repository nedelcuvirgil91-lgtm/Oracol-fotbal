"""Teste pentru manifestul declarativ PIPELINE_STEPS (sync/run_daily.py,
Sprint 1) — decizie explicită proprietar produs: „gândește run_daily.py ca
un orchestrator de pipeline, nu pași hardcodați". Verifică (1) validarea
statică (fail-fast la dependențe nedeclarate/circulare), (2) prezența și
poziția corectă a noului pas `match_statistics`, (3) integrarea reală în
`run()` — dry_run sare pasul, fără apel extern."""
from __future__ import annotations

import io
import contextlib

import pytest

import sync.run_daily as run_daily


def test_pipeline_steps_is_declared_and_valid():
    # _validate_pipeline_steps() rulează deja la import — dacă am ajuns aici
    # fără excepție, manifestul curent e valid. Verificare explicită oricum.
    run_daily._validate_pipeline_steps(run_daily.PIPELINE_STEPS)


def test_match_statistics_step_declared_with_results_dependency():
    names = {s.name: s for s in run_daily.PIPELINE_STEPS}
    assert "match_statistics" in names
    assert names["match_statistics"].depends_on == ("results",)


def test_results_step_declared_first_with_no_dependencies():
    first = run_daily.PIPELINE_STEPS[0]
    assert first.name == "results"
    assert first.depends_on == ()


def test_match_statistics_declared_before_history_sync():
    order = [s.name for s in run_daily.PIPELINE_STEPS]
    assert order.index("match_statistics") < order.index("history_sync")


def test_provider_call_log_cleanup_step_declared_with_no_dependencies():
    """[ADR-041 Faza 2, Sprint 1.1 #2]"""
    names = {s.name: s for s in run_daily.PIPELINE_STEPS}
    assert "provider_call_log_cleanup" in names
    assert names["provider_call_log_cleanup"].depends_on == ()


def test_team_form_freelf_step_declared_with_no_dependencies():
    """[ADAUGAT Sprint 2, Etapa C — Data Quality]"""
    names = {s.name: s for s in run_daily.PIPELINE_STEPS}
    assert "team_form_freelf" in names
    assert names["team_form_freelf"].depends_on == ()


def test_validate_rejects_forward_reference():
    step = run_daily.PipelineStep
    bad = (step("a", depends_on=("b",)), step("b"))
    with pytest.raises(ValueError, match="depinde de"):
        run_daily._validate_pipeline_steps(bad)


def test_validate_rejects_unknown_dependency():
    step = run_daily.PipelineStep
    bad = (step("a", depends_on=("ghost",)),)
    with pytest.raises(ValueError, match="depinde de"):
        run_daily._validate_pipeline_steps(bad)


def test_validate_rejects_duplicate_step_name():
    step = run_daily.PipelineStep
    bad = (step("a"), step("a"))
    with pytest.raises(ValueError, match="duplicat"):
        run_daily._validate_pipeline_steps(bad)


def test_validate_accepts_valid_chain():
    step = run_daily.PipelineStep
    good = (step("a"), step("b", depends_on=("a",)), step("c", depends_on=("a", "b")))
    run_daily._validate_pipeline_steps(good)  # nu trebuie sa arunce exceptie


# ── Integrare în run() — dry_run, fără apel extern ─────────────────────

def test_dry_run_includes_match_statistics_step_and_skips_it():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily.run(dry_run=True)
    out = buf.getvalue()
    assert "Pasul 1/6" in out
    assert "Match Statistics" in out
    section = out.split("Pasul 1/6")[1].split("Pasul 2/6")[0]
    assert "Sărit (dry run)" in section


def test_dry_run_history_sync_step_renumbered_to_pasul_2():
    """Pasul 'Sincronizare meciuri istorice' era Pasul 1/6, acum e Pasul
    2/6 — noul pas Match Statistics i-a luat locul de 1/6."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily.run(dry_run=True)
    out = buf.getvalue()
    assert "Pasul 2/6 — Sincronizare meciuri istorice" in out


def test_print_match_statistics_report_shows_counts():
    class _R:
        def __init__(self, ran, error=None, task_name="t"):
            self.ran, self.error, self.task_name = ran, error, task_name

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily._print_match_statistics_report([_R(True), _R(True), _R(False, error="boom", task_name="x")])
    out = buf.getvalue()
    assert "2/3" in out
    assert "boom" in out


def test_dry_run_includes_provider_call_log_cleanup_step_and_skips_it():
    """[ADR-041 Faza 2, Sprint 1.1 #2] dry_run sare curatenia, fara apel Supabase."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily.run(dry_run=True)
    out = buf.getvalue()
    assert "provider_call_log" in out
    section = out.split("Curățenie — provider_call_log")[1]
    assert "Sărit (dry run)" in section


def test_dry_run_includes_team_form_freelf_step_and_skips_it():
    """[ADAUGAT Sprint 2, Etapa C — Data Quality] dry_run sare sincronizarea,
    fara apel real la FreeLF."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily.run(dry_run=True)
    out = buf.getvalue()
    assert "Sincronizare formă echipe — FreeLF" in out
    section = out.split("Sincronizare formă echipe — FreeLF")[1]
    assert "Sărit (dry run)" in section


def test_print_match_statistics_report_no_errors_section_when_clean():
    class _R:
        def __init__(self, ran):
            self.ran, self.error, self.task_name = ran, None, "t"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily._print_match_statistics_report([_R(True), _R(True)])
    out = buf.getvalue()
    assert "2/2" in out
    assert "erori" not in out
