"""Teste pentru provider_call_classification.py (ADR-041 Faza 2, Sprint 1.1
#3) — funcție pură, fără rețea."""
from __future__ import annotations

import requests

from provider_call_classification import classify_failure


def test_status_429_classified_as_quota():
    assert classify_failure(429) == (429, "quota")


def test_status_403_classified_as_forbidden():
    assert classify_failure(403) == (403, "forbidden")


def test_status_500_classified_as_upstream_5xx():
    assert classify_failure(500) == (500, "upstream_5xx")


def test_status_502_classified_as_upstream_5xx():
    assert classify_failure(502) == (502, "upstream_5xx")


def test_status_599_classified_as_upstream_5xx():
    assert classify_failure(599) == (599, "upstream_5xx")


def test_status_600_not_classified_as_5xx():
    assert classify_failure(600) == (600, "other_error")


def test_unrecognized_status_classified_as_other_error():
    assert classify_failure(418) == (418, "other_error")


def test_no_status_no_exception_returns_none_none():
    assert classify_failure(None) == (None, None)


def test_timeout_exception_classified_as_timeout():
    exc = requests.exceptions.ConnectTimeout("connect timed out")
    assert classify_failure(None, exc=exc) == (None, "timeout")


def test_read_timeout_also_classified_as_timeout():
    """ReadTimeout e subclasă a requests.exceptions.Timeout — trebuie
    prinsă de același isinstance check."""
    exc = requests.exceptions.ReadTimeout("read timed out")
    assert classify_failure(None, exc=exc) == (None, "timeout")


def test_generic_connection_error_classified_as_network():
    exc = requests.exceptions.ConnectionError("connection refused")
    assert classify_failure(None, exc=exc) == (None, "network")


def test_generic_exception_classified_as_network():
    exc = RuntimeError("something unexpected")
    assert classify_failure(None, exc=exc) == (None, "network")


def test_exception_preserves_status_code_if_known():
    """Caz rar dar posibil: un status a fost deja citit inainte ca o alta
    eroare sa apara (ex. parsare JSON) — status_code-ul cunoscut e pastrat,
    nu aruncat."""
    exc = ValueError("malformed json")
    assert classify_failure(200, exc=exc) == (200, "network")
