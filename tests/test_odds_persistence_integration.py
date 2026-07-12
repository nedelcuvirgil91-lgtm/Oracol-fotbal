"""
Teste de INTEGRARE reale — folosesc supabase_client.py real (nu un fake),
deci ating efectiv Supabase, prin funcția RPC `upsert_odds_snapshot` deja
creată și testată direct în SQL.

[LIMITARE ONESTĂ] Acest fișier NU poate fi rulat din sandbox-ul de
dezvoltare (fără SUPABASE_URL/SUPABASE_SECRET_KEY reale, la fel ca la toate
testele anterioare de acest tip din proiect). Funcția RPC în sine a fost
deja validată exhaustiv, direct în Postgres, cu SQL brut (INSERT inițial,
scriere identică → fără efect, scriere diferită → actualizează doar
closing_*, opening_* neatins). Ce NU s-a testat încă e strict apelul
`client.rpc(...)` din `supabase-py` — verifică asta o singură dată, în
mediul real (Streamlit Cloud), rulând acest fișier sau echivalentul lui.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/claude/stubs")

from services.odds_persistence_service import OddsPersistenceService
import supabase_client as sb


def test_full_insert_then_update_cycle_against_real_supabase():
    """
    Testul complet: INSERT inițial (opening=closing), apoi UPDATE closing
    diferit — prin Python, prin RPC, prin funcția SQL deja validată.
    Rulează DOAR cu credențiale reale disponibile (SUPABASE_URL/
    SUPABASE_SECRET_KEY) - altfel service.persist_odds_snapshot ridică
    RuntimeError la primul _upsert(), confirmat de test_graceful_* de mai jos.

    [NOTĂ] Curățarea datelor de test (DELETE) necesită dezactivarea
    temporară a trigger-ului de imutabilitate (documentat explicit în
    ODDS_PERSISTENCE_DESIGN.md §7 - "escape hatch" administrativ). Nu există
    o funcție RPC dedicată pentru asta în acest proiect - curățarea rămâne o
    acțiune manuală de operator (SQL direct), nu parte a suitei automate.
    Testul de mai jos NU face curățare automată din acest motiv explicit.
    """
    client = sb.get_client()
    if client is None:
        print("  [SKIP] Fără credențiale Supabase reale în acest mediu — "
              "rulați acest test în mediul de producție pentru validare completă.")
        return

    service = OddsPersistenceService()
    fixture_id = "integration_test_fx_001"
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Prima scriere
    r1 = service.persist_odds_snapshot([{
        "fixture_id": fixture_id, "kickoff_utc": future,
        "home_odds": 2.00, "draw_odds": 3.20, "away_odds": 3.50,
        "bookmaker": "integration_test_bk",
    }])
    assert r1.written == 1, "prima scriere trebuia sa reuseasca"

    # A doua scriere, valori diferite -> update closing
    r2 = service.persist_odds_snapshot([{
        "fixture_id": fixture_id, "kickoff_utc": future,
        "home_odds": 2.10, "draw_odds": 3.25, "away_odds": 3.40,
        "bookmaker": "integration_test_bk",
    }])
    assert r2.written == 1, "a doua scriere (closing diferit) trebuia sa reuseasca"

    # A treia scriere, valori IDENTICE cu a doua -> fara efect (§8)
    r3 = service.persist_odds_snapshot([{
        "fixture_id": fixture_id, "kickoff_utc": future,
        "home_odds": 2.10, "draw_odds": 3.25, "away_odds": 3.40,
        "bookmaker": "integration_test_bk",
    }])
    assert r3.written == 0, "scriere identica nu trebuia sa produca niciun UPDATE"

    # Confirmare directa: opening a ramas neschimbat
    row = client.table("odds_history").select("*").eq(
        "fixture_id", fixture_id).eq("bookmaker", "integration_test_bk").execute()
    data = row.data[0]
    assert float(data["opening_home"]) == 2.00, "opening_home nu trebuia atins"
    assert float(data["closing_home"]) == 2.10, "closing_home trebuia actualizat la valoarea finala"

    print("  [PASS] ciclu complet INSERT->UPDATE->no-op confirmat prin Python, live")
    print("  [ATENȚIE] rândul de test 'integration_test_fx_001' a rămas în odds_history "
          "- curățare manuală necesară (vezi nota din docstring).")


def test_graceful_error_without_real_credentials():
    """Confirma ca, fara credentiale, serviciul esueaza clar (RuntimeError),
    nu silentios."""
    service = OddsPersistenceService()
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = service.persist_odds_snapshot([{
        "fixture_id": "will_fail", "kickoff_utc": future,
        "home_odds": 2.0, "draw_odds": 3.2, "away_odds": 3.5, "bookmaker": "x",
    }])
    # daca nu exista credentiale, _upsert arunca RuntimeError, prins si
    # inregistrat in errors - NU propagat, NU opreste lotul
    if sb.get_client() is None:
        assert len(result.errors) == 1
        assert result.written == 0
