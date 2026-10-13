"""Gărzi pentru instrumentarea HTTP (`oracle_api._RetryCuJurnal`, `_raporteaza_daca_lenta`).

CE MĂSOARĂ INSTRUMENTAREA
96 de apeluri TheSportsDB pe săptămână se termină între 120.160 și 122.699 ms
— abatere standard 577 ms, deci plafon DETERMINIST — și toate **reușesc**.
Aceleași endpoint-uri răspund normal în 343-508 ms. Consumă ~28 min/zi.

Dar `timeout=12` × 4 încercări + backoff ≈ 51,5 s, nu 120. Două explicații
posibile, cu remedii OPUSE:
  (a) bugetul de reîncercări consumat, ultima reușește → timeout mai mic
      scurtează, fără pierdere de date;
  (b) o singură cerere care primește octeți prea rar ca să declanșeze
      timeout-ul `requests` (care măsoară între octeți, nu total) → timeout
      mai mic n-ar ajuta și ar tăia cereri bune.

Liniile `[HTTP-retry]` dinaintea unui `[HTTP-lent]` disting între ele.

CE APĂRĂ GĂRZILE
  1. Comportamentul de reîncercare rămâne IDENTIC — instrumentarea nu are voie
     să schimbe câte încercări se fac sau pe ce coduri.
  2. `increment()` păstrează subclasa — altfel logarea s-ar opri după prima
     reîncercare, exact unde contează.
  3. Nicio excepție din instrumentare nu scapă într-o cereală reală.
  4. Pragul nu inundă log-ul (97,7% dintre apeluri sunt sub el).

Fără rețea.
"""
from __future__ import annotations

import logging

import pytest

import oracle_api as oa


# ════════════════════════════════════════════════════════════════════════
# 1. Comportamentul de reîncercare e NESCHIMBAT
# ════════════════════════════════════════════════════════════════════════

def test_sesiunea_foloseste_retry_ul_instrumentat():
    s = oa._build_session()
    for schema in ("https://", "http://"):
        retry = s.get_adapter(schema + "x").max_retries
        assert isinstance(retry, oa._RetryCuJurnal), f"{schema} nu e instrumentat"


def test_parametrii_de_reincercare_sunt_identici_cu_cei_dinainte():
    """GARDA CENTRALĂ. Instrumentarea e pur observațională — dacă ar schimba
    bugetul, am măsura alt sistem decât cel pe care vrem să-l înțelegem, iar
    cifra de 120 s n-ar mai fi comparabilă cu cele 96 deja înregistrate."""
    r = oa._build_session().get_adapter("https://x").max_retries
    assert r.total == 3
    assert r.backoff_factor == 0.5
    assert tuple(r.status_forcelist) == (429, 500, 502, 503, 504)
    assert list(r.allowed_methods) == ["GET"]
    assert r.raise_on_status is False


def test_increment_pastreaza_subclasa_pe_tot_lantul():
    """Fără asta, logarea s-ar opri după PRIMA reîncercare: `Retry.increment()`
    construiește un obiect nou, iar dacă acela ar fi un `Retry` simplu,
    reîncercările 2 și 3 — exact cele care disting cazul (a) de (b) — ar trece
    tăcute."""
    r = oa._build_session().get_adapter("https://x").max_retries
    for ramase_asteptate in (2, 1, 0):
        r = r.increment(method="GET", url="https://x/y", error=Exception("timeout"))
        assert isinstance(r, oa._RetryCuJurnal)
        assert r.total == ramase_asteptate


def test_increment_logheaza_fiecare_reincercare(caplog):
    r = oa._build_session().get_adapter("https://x").max_retries
    with caplog.at_level(logging.WARNING, logger="FootballOracle.API"):
        r2 = r.increment(method="GET", url="https://tsdb/eventslast.php?id=1",
                         error=Exception("Read timed out"))
        r2.increment(method="GET", url="https://tsdb/eventslast.php?id=1",
                     error=Exception("Read timed out"))
    linii = [m for m in caplog.messages if "[HTTP-retry]" in m]
    assert len(linii) == 2
    assert "eventslast.php" in linii[0]
    assert "Read timed out" in linii[0]


def test_logarea_nu_rupe_cererea_daca_arunca(monkeypatch, caplog):
    """Instrumentarea e un ajutor, nu o dependență: dacă logger-ul explodează,
    reîncercarea trebuie să continue normal."""
    def explodeaza(*a, **k):
        raise RuntimeError("logger picat")
    monkeypatch.setattr(oa.logger, "warning", explodeaza)
    r = oa._build_session().get_adapter("https://x").max_retries
    nou = r.increment(method="GET", url="https://x/y", error=Exception("t"))
    assert isinstance(nou, oa._RetryCuJurnal) and nou.total == 2


# ════════════════════════════════════════════════════════════════════════
# 2. Raportul de cerere lentă
# ════════════════════════════════════════════════════════════════════════

def _api():
    return oa.FootballOracleAPI.__new__(oa.FootballOracleAPI)


def test_cererile_rapide_nu_se_raporteaza(caplog):
    """97,7% dintre apeluri sunt sub 5 s. Dacă pragul le-ar prinde, raportul
    ar deveni încă o inundare de log — exact problema de la care am pornit."""
    with caplog.at_level(logging.WARNING, logger="FootballOracle.API"):
        _api()._raporteaza_daca_lenta("https://x/y", "thesportsdb", 400, 12, True)
        _api()._raporteaza_daca_lenta("https://x/y", "thesportsdb", 9_999, 12, True)
    assert [m for m in caplog.messages if "[HTTP-lent]" in m] == []


def test_cererile_lente_se_raporteaza_cu_bugetul_alaturi(caplog):
    """Bugetul în aceeași linie e esențial: fără el, „121 s" nu se poate
    interpreta — nu se știe dacă depășește sau nu ce pot explica
    reîncercările."""
    with caplog.at_level(logging.WARNING, logger="FootballOracle.API"):
        _api()._raporteaza_daca_lenta("https://tsdb/eventslast.php", "thesportsdb",
                                       121_000, 12, True)
    linie = next(m for m in caplog.messages if "[HTTP-lent]" in m)
    assert "121.0s" in linie
    assert "timeout=12s" in linie
    assert "buget teoretic" in linie
    assert "reușit" in linie


def test_depasirea_bugetului_e_marcata_explicit(caplog):
    """Semnalul care decide între cele două explicații: peste buget ȘI fără
    linii `[HTTP-retry]` înainte = o singură cerere lentă, nu reîncercări."""
    with caplog.at_level(logging.WARNING, logger="FootballOracle.API"):
        _api()._raporteaza_daca_lenta("https://x/y", "thesportsdb", 121_000, 12, True)
        _api()._raporteaza_daca_lenta("https://x/y", "thesportsdb", 30_000, 12, True)
    linii = [m for m in caplog.messages if "[HTTP-lent]" in m]
    assert "PESTE buget" in linii[0], "121s > 51,5s trebuie marcat"
    assert "PESTE buget" not in linii[1], "30s < 51,5s NU trebuie marcat"


def test_esecul_se_distinge_de_reusita_in_raport(caplog):
    """Cele 96 de apeluri de 120 s REUȘESC — dacă raportul n-ar distinge, am
    pierde exact faptul care face problema interesantă."""
    with caplog.at_level(logging.WARNING, logger="FootballOracle.API"):
        _api()._raporteaza_daca_lenta("https://x/y", "tsdb", 121_000, 12, False)
    assert "eșuat" in next(m for m in caplog.messages if "[HTTP-lent]" in m)


def test_raportul_nu_arunca_niciodata(monkeypatch):
    def explodeaza(*a, **k):
        raise RuntimeError("picat")
    monkeypatch.setattr(oa.logger, "warning", explodeaza)
    _api()._raporteaza_daca_lenta("https://x/y", "tsdb", 121_000, 12, True)   # nu trebuie să arunce


def test_pragul_e_peste_latenta_normala_a_providerului():
    """343-508 ms normal la TheSportsDB; un prag sub o secundă ar raporta tot."""
    assert oa._PRAG_CERERE_LENTA_S >= 5.0
