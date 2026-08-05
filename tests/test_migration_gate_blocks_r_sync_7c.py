"""ADR-040, principiul 8 — garda de blocare a R-Sync-7c: eliminarea căii
vechi de discovery din `oracle_api.get_matches_for_week()` NU poate începe
fără o atestare PASS, proaspătă, verificabilă, pentru `gate_key='R-Sync-7b'`.

Gardă AST, offline, fără Supabase — precedent direct:
`test_canonical_feature_ownership.py`. Azi (R-Sync-7c neînceput), acest
test e un no-op trivial (toate cele 6 apeluri de discovery încă există în
get_matches_for_week()) — devine activ automat în momentul în care cineva
elimină oricare dintre ele, fără nicio schimbare necesară aici."""
from __future__ import annotations

import ast
import inspect
import json
import textwrap

import migration_gate
import oracle_api

_REQUIRED_DISCOVERY_CALLS = {
    "_fetch_events_odds_api", "_fetch_freelf_matches", "_fetch_matches_fd",
    "_fetch_matches_espn", "_fetch_matches_tsdb", "_fetch_matches_api_football",
}


def _r_sync_7c_has_started() -> bool:
    """Detecție structurală: dacă oricare din cele 6 apeluri de discovery
    (pașii 1-6, ADR-039) lipsește, R-Sync-7c a început să înlocuiască calea
    veche. [ACTUALIZAT ADR-053] Cele 6 apeluri au fost extrase din
    get_matches_for_week() în _fetch_live_week_matches() (cascada live
    NESCHIMBATĂ logic, devenită fallback per-ligă sub Database-First) —
    garda inspectează acum sursa combinată a ambelor metode, nu doar a
    fostei metode unice."""
    called: set[str] = set()
    for src in (
        textwrap.dedent(inspect.getsource(oracle_api.FootballOracleAPI.get_matches_for_week)),
        textwrap.dedent(inspect.getsource(oracle_api.FootballOracleAPI._fetch_live_week_matches)),
    ):
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Attribute) and node.attr in _REQUIRED_DISCOVERY_CALLS:
                called.add(node.attr)
    return bool(_REQUIRED_DISCOVERY_CALLS - called)


def test_all_six_discovery_calls_still_present_today():
    """Dovadă structurală că testul de mai jos e încă un no-op azi — dacă
    ACEST test pică, R-Sync-7c a început și testul de blocare devine activ."""
    assert not _r_sync_7c_has_started()


def test_r_sync_7c_blocked_without_fresh_valid_pass_attestation():
    if not _r_sync_7c_has_started():
        return  # R-Sync-7c neînceput -- gate încă neaplicabil, no-op deliberat

    result = migration_gate.verify("R-Sync-7b")
    assert result.valid, (
        "R-Sync-7c pare să fi început (un apel de discovery lipsește din "
        "get_matches_for_week()), dar atestarea pentru gate_key='R-Sync-7b' "
        f"nu e validă/proaspătă. Motive: {result.reasons}"
    )

    payload = json.loads(migration_gate.attestation_path("R-Sync-7b").read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS", (
        "R-Sync-7c a început, dar ultima atestare validă NU e PASS "
        f"(e {payload.get('verdict')}) — migrarea trebuie oprită până "
        "migration_gate status R-Sync-7b confirmă PASS."
    )
