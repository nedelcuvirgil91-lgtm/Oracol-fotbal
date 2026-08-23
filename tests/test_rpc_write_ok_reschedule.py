"""Teste pentru database.queries._rpc_write_ok — interpretarea rezultatului
RPC-ului canonic, inclusiv actiunea noua `reschedule` (migrarea 048).

CONTEXT: `_upsert_match_canonical_locked` cauta randul dupa cheia naturala
(gazda, oaspete, data). Cand un provider muta un meci pe alta data, lookup-ul
esueaza, functia cade pe INSERT, iar INSERT-ul violeaza indexul UNIQUE pe
fixture_id — exceptie, si intregul pas de sincronizare pica. Un singur meci
reprogramat (Celta Vigo - Osasuna) a blocat flashscore_weekly_fixtures.yml
timp de 10 zile.

Migrarea 048 intoarce `reschedule` in acest caz. Testele de aici verifica
invariantul care conteaza: `reschedule` e o scriere REUSITA, nu un esec —
altfel apelantii ar raporta pierdere de date exact cand fix-ul functioneaza.

Fara retea, fara Supabase.
"""
from __future__ import annotations

import database.queries as q


class _Res:
    def __init__(self, data):
        self.data = data


_PAYLOAD = {"home_team": "Celta Vigo", "away_team": "CA Osasuna", "kickoff_date": "2026-08-27"}


def test_reschedule_e_scriere_reusita():
    """Invariantul central al migrarii 048."""
    assert q._rpc_write_ok(_Res({"action": "reschedule", "id": 42}), _PAYLOAD, "test") is True


def test_insert_si_update_raman_reusite():
    """Comportamentul preexistent, neschimbat."""
    assert q._rpc_write_ok(_Res({"action": "insert", "id": 1}), _PAYLOAD, "test") is True
    assert q._rpc_write_ok(_Res({"action": "update", "id": 1}), _PAYLOAD, "test") is True


def test_hard_conflict_ramane_esec():
    assert q._rpc_write_ok(_Res({"action": "hard_conflict", "id": 1}), _PAYLOAD, "test") is False


def test_hard_conflict_cu_motiv_nu_arunca():
    """Migrarea 048 adauga un `reason` la hard_conflict-ul de reprogramare
    (`reschedule_target_occupied`) — logat, nu ignorat, si niciodata cauza de
    exceptie."""
    res = _Res({"action": "hard_conflict", "id": 7, "reason": "reschedule_target_occupied"})
    assert q._rpc_write_ok(res, _PAYLOAD, "test") is False


def test_actiune_necunoscuta_e_tratata_ca_esec():
    """O actiune pe care codul nu o cunoaste NU se presupune reusita —
    Regula #8: o stare necunoscuta nu se aproximeaza intr-una favorabila."""
    assert q._rpc_write_ok(_Res({"action": "ceva_nou"}), _PAYLOAD, "test") is False


def test_raspuns_gol_sau_malformat_e_esec():
    for data in (None, {}, [], "text", {"fara_action": 1}):
        assert q._rpc_write_ok(_Res(data), _PAYLOAD, "test") is False, f"data={data!r}"


def test_nu_arunca_daca_res_nu_are_atribut_data():
    class _NoData:
        pass

    assert q._rpc_write_ok(_NoData(), _PAYLOAD, "test") is False
