"""Gardă ADR-076: extragerea Flashscore trebuie să funcționeze pe AMBELE
generații de markup, iar o a treia redenumire trebuie să fie ZGOMOTOASĂ.

DE CE EXISTĂ
Extragerea statisticilor a murit tăcut de două ori — 8-9 septembrie 2026
(`wcl-statistics-category`/`-value` dispărute) și ~22 septembrie
(`wcl-scores-simple-text-01` -> `wcl-simple-text-01`, `wcl-scores-overline-02`
-> `wcl-overline-02`). 39 de zile, 693 de meciuri fără xG real, 691 dintre ele
marcate `has_stats = true`, deci cu providerii de rezervă săriți. Nimic n-a
semnalat nimic: un dicționar gol și un meci fără statistici produc exact
aceeași scriere, fiindcă RPC-ul canonic e `COALESCE(existent, nou)`.

CE APĂRĂ
  1. Forma NOUĂ de markup se extrage corect — pe HTML REAL, copiat din pagina
     Everton-Chelsea (17.10.2026), nu reconstruit de mine.
  2. Forma VECHE continuă să se extragă identic (cascadă, nu înlocuire).
  3. Eticheta NU se poluează cu valorile din jur — garda pentru defectul real
     prins în candidat înainte de a ajunge în producție (`startswith("wcl-
     label")` prinde și `wcl-labelRow_*`, părintele întregului rând).
  4. Partea oaspetelui se ia SEMANTIC (`wcl-awayValue*`), nu din ordinea DOM.
  5. Container prezent + copii nepotriviți => se loghează ERROR. Verificat
     prin CONTOR de apeluri, nu prin excepție — lecția M4 din ADR-073: un
     `except Exception` din codul de producție poate înghiți exact asertarea
     pe care se sprijină garda.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import logging

import pytest

bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup  # noqa: E402

from providers.flashscore import normalizer as nz  # noqa: E402

# ════════════════════════════════════════════════════════════════════════
# HTML REAL, copiat din pagina live (job GitHub Actions 117434543468).
# Hash-urile de clasă (`_Ywp3J`, `_sO4bA`, `_42JBQ`, `_smmfR`) sunt păstrate
# EXACT ca în sursă — tocmai ca testul să dovedească faptul care contează:
# potrivirea nu depinde de ele.
# ════════════════════════════════════════════════════════════════════════
RAND_NOU_REAL = """
<div class="wcl-statistics_vZTGP fp-fullWidthRow_RbMZx" data-testid="wcl-statistics" data-size="small">
  <div class="wcl-labelRow_42JBQ">
    <div><div class="wcl-value_Ywp3J wcl-small_B9bSY">0.45</div></div>
    <div class="wcl-label_sO4bA">
      <span class="wcl-bold_NZXv6 wcl-simple-text-01_EaZ9- wcl-scores_Na715 wcl-name_2lXWg"
            data-testid="wcl-simple-text-01">Expected goals (xG)</span>
      <svg viewBox="0 0 20 20" data-testid="wcl-icon-settings-info-rounded"
           class="wcl-icon_WGKvC wcl-infoIcon_ryx7L" aria-label="Info about Expected goals (xG)"></svg>
    </div>
    <div class="wcl-awayValue_smmfR"><div class="wcl-value_Ywp3J wcl-small_B9bSY">1.54</div></div>
  </div>
  <div class="wcl-chart_iOT3p"><div class="wcl-bar_jX9q- wcl-barHome_RSl6A" data-side="home"></div></div>
</div>
"""

# Forma de DINAINTE de 8 septembrie, reprodusă din codul care o citea
# (`normalizer.py`, versiunea de dinainte de ADR-076) — nu din memorie.
RAND_VECHI = """
<div data-testid="wcl-statistics">
  <div data-testid="wcl-statistics-value">0.45</div>
  <div data-testid="wcl-statistics-category">Expected goals (xG)</div>
  <div data-testid="wcl-statistics-value">1.54</div>
</div>
"""


def _pairs(html: str) -> dict:
    return nz._extract_labeled_stat_pairs(BeautifulSoup(html, "html.parser"))


# ════════════════════════════════════════════════════════════════════════
# 1 + 2. Ambele generații
# ════════════════════════════════════════════════════════════════════════

def test_forma_noua_reala_se_extrage_corect():
    assert _pairs(RAND_NOU_REAL) == {"Expected goals (xG)": ("0.45", "1.54")}


def test_forma_veche_ramane_functionala():
    """Cascada, nu înlocuire: HTML-ul salvat anterior trebuie să dea identic
    ce dădea înainte de reparație."""
    assert _pairs(RAND_VECHI) == {"Expected goals (xG)": ("0.45", "1.54")}


def test_eticheta_mapeaza_pe_coloana_canonica():
    """Fără asta, extragerea poate fi corectă și tot să nu scrie nimic:
    `normalize_match_statistics` caută exact cheile din STAT_LABEL_TO_FIELDS."""
    eticheta = next(iter(_pairs(RAND_NOU_REAL)))
    assert eticheta in nz.STAT_LABEL_TO_FIELDS
    assert nz.STAT_LABEL_TO_FIELDS[eticheta] == ("home_xg_actual", "away_xg_actual")


# ════════════════════════════════════════════════════════════════════════
# 3. Eticheta poluată — defectul real prins în candidat
# ════════════════════════════════════════════════════════════════════════

def test_eticheta_nu_inghite_valorile_din_jur():
    """`wcl-labelRow_*` conține valoare + etichetă + valoare. O potrivire pe
    PREFIX de șir îl prinde (e părintele), și eticheta devine
    "0.45Expected goals (xG)1.54" — cheie care nu există în nicio mapare.
    Testul fixează exact granița token/prefix."""
    chei = list(_pairs(RAND_NOU_REAL))
    assert chei == ["Expected goals (xG)"]
    assert "0.45" not in chei[0]
    assert "1.54" not in chei[0]


def test_token_de_clasa_nu_se_potriveste_cu_un_nume_mai_lung():
    """Nivelul de dedesubt al aceleiași reguli, verificat direct."""
    sup = BeautifulSoup('<div class="wcl-labelRow_42JBQ"><b class="wcl-label_x">A</b></div>',
                        "html.parser")
    rand_row = sup.select_one(".wcl-labelRow_42JBQ")
    assert nz._has_class_token(rand_row, "wcl-labelRow") is True
    assert nz._has_class_token(rand_row, "wcl-label") is False
    assert len(nz._select_class_token(sup, "wcl-label")) == 1


def test_iconita_de_informatii_nu_ajunge_in_eticheta():
    """`svg` n-are text azi, dar are `aria-label` cu exact textul etichetei.
    Preferăm span-ul marcat tocmai ca o schimbare viitoare să nu-l aducă."""
    assert "Info about" not in next(iter(_pairs(RAND_NOU_REAL)))


# ════════════════════════════════════════════════════════════════════════
# 4. Partea oaspetelui, semantic
# ════════════════════════════════════════════════════════════════════════

def test_partea_oaspetelui_vine_din_container_nu_din_ordine():
    """Inversez ordinea DOM, păstrând containerele semantice. Dacă valorile
    s-ar lua pozițional, rezultatul s-ar inversa."""
    html = """
    <div data-testid="wcl-statistics"><div class="wcl-labelRow_1">
      <div class="wcl-awayValue_z"><div class="wcl-value_a">1.54</div></div>
      <div class="wcl-label_b"><span data-testid="wcl-simple-text-01">Expected goals (xG)</span></div>
      <div><div class="wcl-value_a">0.45</div></div>
    </div></div>
    """
    assert _pairs(html) == {"Expected goals (xG)": ("0.45", "1.54")}


def test_fara_container_semantic_se_cade_pe_ordinea_dom():
    html = """
    <div data-testid="wcl-statistics"><div class="wcl-labelRow_1">
      <div class="wcl-value_a">11</div>
      <div class="wcl-label_b"><span data-testid="wcl-simple-text-01">Corner kicks</span></div>
      <div class="wcl-value_a">22</div>
    </div></div>
    """
    assert _pairs(html) == {"Corner kicks": ("11", "22")}


def test_doar_partea_oaspetelui_prezenta_nu_se_ghiceste_gazda(caplog):
    """North Star #8: o stare necunoscută rămâne necunoscută, nu se deduce
    din singura valoare prezentă."""
    html = """
    <div data-testid="wcl-statistics"><div class="wcl-labelRow_1">
      <div class="wcl-label_b"><span data-testid="wcl-simple-text-01">Fouls</span></div>
      <div class="wcl-awayValue_z"><div class="wcl-value_a">9</div></div>
    </div></div>
    """
    with caplog.at_level(logging.WARNING, logger=nz.logger.name):
        assert _pairs(html) == {"Fouls": (None, "9")}
    assert any("fara valoare de gazda" in r.getMessage() for r in caplog.records)


# ════════════════════════════════════════════════════════════════════════
# 5. Semnalul: container prezent, copii nepotriviți
# ════════════════════════════════════════════════════════════════════════

class _ContorDeErori(logging.Handler):
    """Contor, nu asertare în interiorul codului de producție. Un
    `AssertionError` ridicat de o gardă poate fi înghițit de un
    `except Exception` din producție, iar testul ar trece degeaba (M4,
    ADR-073)."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.mesaje: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mesaje.append(record.getMessage())


@pytest.fixture()
def contor_erori():
    handler = _ContorDeErori()
    nz.logger.addHandler(handler)
    try:
        yield handler
    finally:
        nz.logger.removeHandler(handler)


HTML_A_TREIA_REDENUMIRE = """
<div data-testid="wcl-statistics"><div class="wcl-rowOfTheFuture_q">
  <div class="wcl-brandNewValue_q">0.45</div>
  <div class="wcl-brandNewLabel_q">Expected goals (xG)</div>
</div></div>
"""


def test_container_prezent_zero_etichete_se_logheaza_ca_eroare(contor_erori):
    assert _pairs(HTML_A_TREIA_REDENUMIRE) == {}
    assert len(contor_erori.mesaje) == 1
    assert "STRUCTURA SCHIMBATA" in contor_erori.mesaje[0]
    assert "ADR-076" in contor_erori.mesaje[0]


def test_meci_fara_statistici_NU_logheaza_eroare(contor_erori):
    """Contraponderea care face semnalul util: absența containerului e
    starea normală a unui meci nejucat. Dacă ar țipa și aici, semnalul ar
    fi din nou zgomot de ignorat."""
    assert _pairs("<div><p>nimic</p></div>") == {}
    assert contor_erori.mesaje == []


# ════════════════════════════════════════════════════════════════════════
# P2 — roster + scor la pauză
# ════════════════════════════════════════════════════════════════════════
# Structura e cea MĂSURATĂ pe pagina reală (21 rânduri `-left`, 24 `-right`,
# text de jucător via `wcl-simple-text-01`, 3 span-uri pe rând), dar HTML-ul
# de mai jos e o reconstrucție minimală, NU o copie — spre deosebire de
# RAND_NOU_REAL. Diferența e consemnată, nu ascunsă: proba end-to-end rămâne
# rularea reală, măsurată în Supabase (ADR-076 §5.6).

def _roster(testid_text: str) -> list[dict]:
    html = f"""
    <div>
      <div data-testid="wcl-lineupsParticipantGeneral-left">
        <span data-testid="{testid_text}">1</span>
        <span data-testid="{testid_text}">Pickford J.</span>
        <span data-testid="{testid_text}">(G)</span>
      </div>
      <div data-testid="wcl-lineupsParticipantGeneral-right">
        <span data-testid="{testid_text}">34</span>
        <span data-testid="{testid_text}">Acheampong J.</span>
      </div>
    </div>
    """
    return nz._extract_roster_rows(BeautifulSoup(html, "html.parser"))


@pytest.mark.parametrize("testid", ["wcl-scores-simple-text-01", "wcl-simple-text-01"])
def test_roster_merge_pe_ambele_generatii(testid):
    rows = _roster(testid)
    assert [(r["team"], r["player_name"], r["shirt_number"]) for r in rows] == [
        ("home", "Pickford J.", 1),
        ("away", "Acheampong J.", 34),
    ]


def test_roster_container_prezent_zero_jucatori_se_logheaza(contor_erori):
    rows = _roster("wcl-textul-de-maine")
    assert rows == []
    assert len(contor_erori.mesaje) == 1
    assert "ZERO jucatori" in contor_erori.mesaje[0]


def test_roster_fara_aliniamente_publicate_NU_logheaza(contor_erori):
    assert nz._extract_roster_rows(BeautifulSoup("<div></div>", "html.parser")) == []
    assert contor_erori.mesaje == []


@pytest.mark.parametrize("testid", ["wcl-scores-overline-02", "wcl-overline-02"])
def test_scor_la_pauza_pe_ambele_generatii(testid):
    html = f"""
    <div class="wclHeaderSection--summary">
      <span data-testid="{testid}">1st Half</span>
      <span data-testid="{testid}">2 - 0</span>
    </div>
    """
    assert nz._extract_half_time_score(BeautifulSoup(html, "html.parser")) == (2, 0)


# ════════════════════════════════════════════════════════════════════════
# P3 — clasa 7 din check_data_health e chiar CABLATĂ
# ════════════════════════════════════════════════════════════════════════
# Fără asta, invariantul poate fi scris corect și niciodată rulat — clasa de
# defect de la ADR-066 (extragere bună, fir netăiat), și exact ce a permis
# tăcerea pe care ADR-076 o repară.

def test_clasa_7_e_cablata_in_check_data_health():
    import inspect

    from scripts import check_data_health

    sursa = inspect.getsource(check_data_health.main)
    assert "match_statistics_extended" in sursa, "sonda de statistici lipsește"
    assert "player_match_stats" in sursa, "sonda de roster lipsește"
    # [ACTUALIZAT 2026-10-19, ADR-078: 7 -> 8, clasa „un id Flashscore cu
    # două etichete".] Numărul e deliberat literal — vezi nota din
    # `test_clasa_6_e_chiar_cablata_in_raport`.
    assert "findings}/8" in sursa, "sumarul nu numără clasa 7"


def test_clasa_7_incrementeaza_findings():
    """Un semnal care se tipărește dar nu schimbă codul de ieșire e un semnal
    pe care CI-ul îl ignoră."""
    import ast
    import inspect

    from scripts import check_data_health

    arbore = ast.parse(inspect.getsource(check_data_health.main).strip())
    sub_semnal = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.If)
        and "ZERO rânduri noi" in ast.dump(n)
        and any(isinstance(x, ast.AugAssign) and getattr(x.target, "id", None) == "findings"
                for x in ast.walk(n))
    ]
    assert sub_semnal, "ramura care raportează zero scrieri nu incrementează `findings`"


def test_clasa_7_nu_da_verdict_sub_pragul_de_meciuri():
    """North Star #8: într-o pauză internațională fereastra poate fi legitim
    goală. Atunci nu se afirmă nici defect, nici sănătate."""
    import inspect

    from scripts import check_data_health

    sursa = inspect.getsource(check_data_health.main)
    assert "MIN_MECIURI_PENTRU_VERDICT" in sursa
    assert "INSUFICIENTE DATE" in sursa


def test_cascada_nu_amesteca_doua_generatii():
    """Dacă ambele forme ar fi prezente, se folosește PRIMA din cascadă,
    întreagă — nu o reuniune a celor două, care ar putea încurca ordinea."""
    sup = BeautifulSoup(
        '<div><span data-testid="wcl-scores-simple-text-01">vechi</span>'
        '<span data-testid="wcl-simple-text-01">nou</span></div>', "html.parser")
    gasite = nz._select_first_testid(sup, nz._TEXT_TESTIDS)
    assert [g.get_text(strip=True) for g in gasite] == ["vechi"]
