"""Gardă statică pentru ADR-039 (Universal Synchronization Architecture) —
R-Sync-5: Oracle Engine nu mai are voie să apeleze
`self.api.get_weather()` (WeatherAPI) direct.

Impune mecanic invariantul, prin inspecție AST a codului de producție —
oglindă directă a gărzilor echivalente de la R-Sync-2/3/4
(test_oracle_engine_provider_independence.py,
test_oracle_engine_footballdata_independence.py,
test_get_elo_rating_never_called_from_oracle_engine).

Notă de scope, explicită: acest test acoperă DOAR `get_weather`
(WeatherAPI, migrat în R-Sync-5). Restul providerilor rămași
(FreeLF/Odds API/descoperire meciuri/TheSportsDB team stats) rămân,
deliberat, neatinse — migrarea lor e R-Sync-6…8, fiecare cu propria
gardă adăugată la momentul ei."""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parse(path: pathlib.Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_oracle_engine_never_calls_get_weather():
    """R-Sync-5: singurul apelant de producție al `get_weather()`
    (oracle_api.py) rămâne Sync Layer (weather_forecast_adapter.py),
    niciodată oracle_engine.py."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "get_weather":
            raise AssertionError(
                f"oracle_engine.py:{node.lineno} referă încă `.get_weather` — "
                "eliminat în R-Sync-5, ADR-039 (citire STRICT din Supabase, "
                "database.queries.get_weather_forecast())."
            )


def test_oracle_engine_reads_weather_only_via_database_queries():
    """Pozitiv: confirmă că înlocuirea chiar există, nu doar că vechea
    cale a dispărut — get_weather_forecast trebuie importat din
    database.queries."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.queries"):
            if any(alias.name == "get_weather_forecast" for alias in node.names):
                found = True
    assert found, (
        "oracle_engine.py trebuie să importe get_weather_forecast din "
        "database.queries (R-Sync-5) — sursa canonică pentru prognoza meteo."
    )
