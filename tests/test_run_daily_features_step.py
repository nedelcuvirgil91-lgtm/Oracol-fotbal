"""
Teste pentru pasul nou din sync/run_daily.py — actualizare feature-uri
derivate (ADR-014), care completează implementarea ADR-004 ("toate
feature-urile se recalculează incremental după fiecare actualizare de
rezultate"). Fără rețea, fără Supabase live — doar dry_run=True (toți
pașii din run() se opresc înainte de orice apel extern) și funcția pură
de raportare.
"""
import io
import contextlib

import sync.run_daily as run_daily


def test_print_features_report_done():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily._print_features_report(
            {"status": "done", "processed": 42, "already_done": 100, "errors": 0}
        )
    out = buf.getvalue()
    assert "42" in out
    assert "100" in out


def test_print_features_report_skipped():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily._print_features_report({"status": "skipped", "message": "--no-features flag"})
    assert "--no-features flag" in buf.getvalue()


def test_print_features_report_error():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily._print_features_report({"status": "error", "message": "boom"})
    assert "boom" in buf.getvalue()


def test_dry_run_includes_features_step_and_skips_it():
    """dry_run=True nu trebuie sa faca niciun apel extern (retea/Supabase) —
    pasul 3/6 trebuie sa apara si sa fie sarit explicit."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_daily.run(dry_run=True)
    out = buf.getvalue()
    assert "Pasul 3/6" in out
    assert "Actualizare feature-uri derivate" in out
    # In dry_run, pasul de feature-uri trebuie sarit explicit, nu executat.
    features_section = out.split("Pasul 3/6")[1].split("Pasul 4/6")[0]
    assert "Sărit (dry run)" in features_section


def test_skip_features_flag_present_in_run_signature():
    """Semnatura run() trebuie sa accepte skip_features, la fel ca skip_elo/skip_ml."""
    import inspect
    params = inspect.signature(run_daily.run).parameters
    assert "skip_features" in params
    assert params["skip_features"].default is False
