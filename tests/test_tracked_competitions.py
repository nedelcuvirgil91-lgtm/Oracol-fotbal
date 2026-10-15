"""
Gărzi pentru lista canonică de competiții urmărite (`mappings.TRACKED_COMPETITIONS`).

**Defectul pe care îl previn, și care a stat un sezon întreg în producție:**
`log_challenger_shadow_for_week()` (batch-ul de noapte, ADR-056) chema
`get_matches_for_week()` fără argumentul `competitions`, iar acela cădea pe
`list(ODDS_SPORT_KEYS.keys())` — un dicționar DERIVAT, al cărui înțeles e
„ligile acoperite de The Odds API", 16 din 18.

Consecința măsurată pe sezonul 2026/27, înainte de corecție: **198 de meciuri**
(147 Conference League + 51 HNL) fără niciun rând `control` — invizibile pentru
radarul de value bets, absente din experimentul Challenger, neauditabile până
la sursă (North Star #9). Interfața le arăta corect, fiindcă `app.py` pasa
lista completă explicit; de aici asimetria care a ascuns defectul: pe ecran
existau, în pipeline nu.

Gărzile de aici impun invariantul, nu lista: „ce competiții urmărim" nu se
deduce niciodată din „ce acoperă un provider de cote", iar interfața și
pipeline-ul nu au voie să diveargă.

Zero rețea, zero Supabase. Verificările structurale citesc codul prin AST —
un `ast.parse` ignoră din construcție comentariile, deci nicio gardă nu-și
poate găsi propria explicație (eroare comisă deja de trei ori în proiect).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import oracle_engine
from mappings import LEAGUE_PROVIDERS, ODDS_SPORT_KEYS, TRACKED_COMPETITIONS

RADACINA = Path(__file__).resolve().parents[1]
APP = RADACINA / "app.py"
MAPPINGS = RADACINA / "mappings.py"


# ── Lista canonică ───────────────────────────────────────────────────────────

def test_lista_canonica_e_derivata_din_sursa_unica():
    """ADR-001 face `LEAGUE_PROVIDERS` sursa canonică unică. O listă scrisă de
    mână lângă ea ar fi exact mecanismul de desincronizare pe care fișierul îl
    numește în comentariul secțiunii de dicționare derivate."""
    assert list(TRACKED_COMPETITIONS) == list(LEAGUE_PROVIDERS.keys())


def test_lista_canonica_e_strict_mai_mare_decat_acoperirea_odds_api():
    """Invariantul central. Dacă cele două ar deveni egale, defectul original
    ar redeveni invizibil: batch-ul ar funcționa „din întâmplare", până la
    prima competiție neacoperită de The Odds API."""
    canonic, odds = set(TRACKED_COMPETITIONS), set(ODDS_SPORT_KEYS)
    assert odds < canonic, (
        "acoperirea Odds API nu mai e strict inclusă în lista canonică — "
        f"doar în Odds API: {sorted(odds - canonic)}")


def test_cele_doua_ligi_pierdute_sunt_in_lista_canonica():
    """Cazul concret care a produs defectul. Numit explicit: dacă vreodată
    dispare una, testul spune CARE, nu doar „ceva nu mai e la fel"."""
    for liga in ("Conference League", "HNL"):
        assert liga in TRACKED_COMPETITIONS, liga
        assert liga not in ODDS_SPORT_KEYS, (
            f"{liga} a intrat în Odds API — vestea e bună, dar atunci acest "
            "test nu mai dovedește nimic și trebuie ales alt exemplu")


def test_lista_canonica_nu_e_scrisa_de_mana():
    """Gardă structurală: `TRACKED_COMPETITIONS` trebuie să fie o expresie
    derivată din `LEAGUE_PROVIDERS`, nu un literal. Un literal ar trece azi
    toate testele de mai sus și s-ar desincroniza la prima ligă adăugată."""
    arbore = ast.parse(MAPPINGS.read_text(encoding="utf-8"))
    atribuiri = [n for n in ast.walk(arbore)
                 if isinstance(n, ast.AnnAssign)
                 and isinstance(n.target, ast.Name)
                 and n.target.id == "TRACKED_COMPETITIONS"]
    assert atribuiri, "`TRACKED_COMPETITIONS` nu mai e definită în mappings.py"
    sursa = ast.unparse(atribuiri[0].value)
    assert "LEAGUE_PROVIDERS" in sursa, sursa
    assert not isinstance(atribuiri[0].value, (ast.List, ast.Tuple, ast.Set)), (
        f"listă scrisă de mână: {sursa}")


# ── Interfața și pipeline-ul nu au voie să diveargă ──────────────────────────

def _competitii_din_interfata() -> set[str]:
    text = APP.read_text(encoding="utf-8")
    bloc = re.search(r"COMPETITIONS_META\s*=\s*\[(.*?)\n\]", text, re.S)
    assert bloc, "COMPETITIONS_META nu mai poate fi citită din app.py"
    return set(re.findall(r'"key"\s*:\s*"([^"]+)"', bloc.group(1)))


def test_interfata_si_pipeline_ul_urmaresc_aceleasi_competitii():
    """Garda care prinde CLASA defectului, nu instanța lui.

    Asimetria dintre ecran (18 competiții, pasate explicit) și batch (16, prin
    implicit) a ascuns problema un sezon: utilizatorul VEDEA meciurile, deci
    nimic nu părea stricat. Orice divergență viitoare cade aici, în ambele
    direcții."""
    interfata = _competitii_din_interfata()
    canonic = set(TRACKED_COMPETITIONS)
    assert interfata == canonic, (
        f"doar în interfață: {sorted(interfata - canonic)} · "
        f"doar în pipeline: {sorted(canonic - interfata)}")


# ── Batch-ul cere explicit competițiile ──────────────────────────────────────

def _apelul_din_batch() -> ast.Call:
    arbore = ast.parse((RADACINA / "oracle_engine.py").read_text(encoding="utf-8"))
    functie = next(
        (n for n in ast.walk(arbore)
         if isinstance(n, ast.FunctionDef) and n.name == "log_challenger_shadow_for_week"),
        None)
    assert functie is not None, "`log_challenger_shadow_for_week` a dispărut"
    apeluri = [n for n in ast.walk(functie)
               if isinstance(n, ast.Call)
               and ast.unparse(n.func).endswith("get_matches_for_week")]
    assert len(apeluri) == 1, f"aștept exact un apel, am găsit {len(apeluri)}"
    return apeluri[0]


def test_batch_ul_paseaza_competitiile_explicit():
    """Defectul original, în forma lui exactă: apel fără `competitions`."""
    apel = _apelul_din_batch()
    chei = {kw.arg for kw in apel.keywords}
    assert "competitions" in chei, (
        "batch-ul cheamă `get_matches_for_week()` fără competiții — cade pe "
        "implicitul `ODDS_SPORT_KEYS` și pierde din nou cele două ligi")


def test_batch_ul_nu_foloseste_dictionarul_de_chei_odds():
    """A doua formă a aceluiași defect: competiții pasate explicit, dar luate
    tot din sursa greșită. Ar trece testul de mai sus și n-ar repara nimic."""
    apel = _apelul_din_batch()
    valoare = next(kw.value for kw in apel.keywords if kw.arg == "competitions")
    sursa = ast.unparse(valoare)
    assert "ODDS_SPORT_KEYS" not in sursa, sursa
    assert "TRACKED_COMPETITIONS" in sursa, sursa


# ── Comportament, nu doar structură ──────────────────────────────────────────

class _ApiFals:
    def __init__(self):
        self.competitii_primite: list[list[str] | None] = []

    def get_matches_for_week(self, days_ahead=7, competitions=None):
        self.competitii_primite.append(competitions)
        return []


class _Motor:
    log_challenger_shadow_for_week = (
        oracle_engine.FootballOracleEngine.log_challenger_shadow_for_week)

    def __init__(self):
        self.api = _ApiFals()

    def evaluate_match(self, m):  # pragma: no cover — lista e goală
        return object()


def test_batch_ul_cere_efectiv_cele_18_competitii():
    motor = _Motor()
    motor.log_challenger_shadow_for_week(days_ahead=7)

    cerute = motor.api.competitii_primite[0]
    assert cerute is not None, "batch-ul n-a pasat nicio competiție"
    assert set(cerute) == set(TRACKED_COMPETITIONS)
    assert {"Conference League", "HNL"} <= set(cerute)


def test_batch_ul_nu_modifica_lista_canonica():
    """Pasarea unei referințe vii ar permite unui apelant din aval să mute
    `TRACKED_COMPETITIONS` sub picioarele tuturor celorlalți consumatori."""
    inainte = list(TRACKED_COMPETITIONS)
    motor = _Motor()
    motor.log_challenger_shadow_for_week(days_ahead=7)
    cerute = motor.api.competitii_primite[0]
    cerute.append("Liga Inventata")
    assert list(TRACKED_COMPETITIONS) == inainte


# ── Contrapondere ────────────────────────────────────────────────────────────

def test_contrapondere_lista_nu_e_goala():
    """Dacă `LEAGUE_PROVIDERS` ar fi golită sau redenumită, toate testele de
    mai sus ar trece VID — mulțimile goale sunt egale între ele."""
    assert len(TRACKED_COMPETITIONS) >= 15, len(TRACKED_COMPETITIONS)
    assert len(ODDS_SPORT_KEYS) >= 10, len(ODDS_SPORT_KEYS)
