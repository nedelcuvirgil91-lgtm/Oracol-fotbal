"""Gărzi pentru adăugarea unei competiții noi (ADAUGAT 2026-10-17).

**De ce există.** Adăugarea Austriei, Elveției și Danemarcei a scos la iveală
că o ligă nouă atinge **șapte** locuri, nu două cum estimasem: `LEAGUE_PROVIDERS`,
`LEAGUE_BASELINES`, `LEAGUE_ALIASES`, `FLASHSCORE_TRACKED_COMPETITIONS`,
ponderile per ligă din `oracle_engine`, `COMPETITIONS_META` din `app.py`, și
workflow-ul de catch-up. Două dintre ele nu aveau nicio gardă, iar una ascundea
o capcană activă.

**Capcana găsită în timpul adăugării, înainte de a produce pagubă:**
`ALIAS_TO_CANONICAL_LEAGUE` se construiește prin **suprascriere tăcută**, fără
nicio detecție de coliziuni, iar potrivirea e case-insensitive. Intenționasem
să adaug `"Superliga"` ca alias pentru Danemarca — ceea ce ar fi făcut ca un
șir care azi rămâne NESCHIMBAT (comportamentul sigur, documentat explicit în
nota de design a `LEAGUE_ALIASES`) să se mapeze la Danemarca, deși liga
românească se numește literal „SuperLiga". O regresie introdusă de o adăugare,
nu un defect preexistent — verificat: azi există **zero** coliziuni.

Zero rețea, zero Supabase.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

import oracle_engine
from mappings import (
    LEAGUE_ALIASES,
    LEAGUE_BASELINES,
    LEAGUE_PROVIDERS,
    ODDS_SPORT_KEYS,
    TRACKED_COMPETITIONS,
    normalize_league_name,
)
from providers.flashscore.discovery import FLASHSCORE_TRACKED_COMPETITIONS

RADACINA = Path(__file__).resolve().parents[1]

LIGI_NOI = ("Austria Bundesliga", "Swiss Super League", "Danish Superliga")


# ── Coliziuni de alias ───────────────────────────────────────────────────────

def test_niciun_alias_nu_e_revendicat_de_doua_competitii():
    """Invariantul, nu lista. Harta inversă se construiește prin suprascriere,
    deci o coliziune nu ar da nicio eroare — ar schimba tăcut unde se mapează
    un nume, iar ultima ligă declarată ar câștiga."""
    revendicari: dict[str, set[str]] = defaultdict(set)
    for canonic, alias_uri in LEAGUE_ALIASES.items():
        revendicari[canonic.lower()].add(canonic)
        for alias in alias_uri:
            revendicari[alias.lower()].add(canonic)

    coliziuni = {k: sorted(v) for k, v in revendicari.items() if len(v) > 1}
    assert not coliziuni, f"alias revendicat de mai multe competiții: {coliziuni}"


def test_superliga_goala_nu_se_mapeaza_la_danemarca():
    """Cazul concret pe care l-am evitat, fixat ca test ca să nu fie
    reintrodus de o adăugare viitoare „logică".

    `"Superliga"` trebuie să rămână NEnormalizat — nu se poate ști din șirul
    gol dacă e România sau Danemarca, iar regula documentată e „mai bine
    nenormalizată decât mapată greșit"."""
    for forma in ("Superliga", "superliga", "SuperLiga", "Super League", "super league"):
        assert normalize_league_name(forma) == forma.strip(), (
            f"'{forma}' s-a mapat la '{normalize_league_name(forma)}' — formă "
            "ambiguă, trebuie să rămână neschimbată")


@pytest.mark.parametrize("cod,asteptat", [
    ("AUT", "Austria Bundesliga"),
    ("SUI", "Swiss Super League"),
    ("DEN", "Danish Superliga"),
])
def test_codurile_istorice_de_tara_se_mapeaza_la_liga_noua(cod, asteptat):
    """Cele trei coduri există REAL în `match_history` — AUT 644 de meciuri,
    SUI 655, DEN 655, toate cu rezultat — iar că sunt primele divizii e
    confirmat: toate cele 12 echipe din clasamentul live al fiecărei ligi se
    regăsesc în codul corespunzător (36 din 36).

    Fără maparea asta, aceeași competiție ar purta două etichete: `AUT` pe
    rândurile istorice și `Austria Bundesliga` pe cele noi.

    Testul există și ca urmă a unei erori de metodă: prima versiune a codului
    le-a omis deliberat, justificat cu „zero meciuri în istoric" — concluzie
    produsă de un filtru (`league ilike '%austri%'`) care nu PUTEA găsi un cod
    de trei litere."""
    assert normalize_league_name(cod) == asteptat
    assert normalize_league_name(cod.lower()) == asteptat


def test_formele_neambigue_se_mapeaza_corect():
    """Contrapondere: dacă testul de mai sus ar trece fiindcă normalizarea nu
    mai face nimic pentru nimeni, asta ar prinde-o."""
    assert normalize_league_name("Danish Superliga") == "Danish Superliga"
    assert normalize_league_name("Superligaen") == "Danish Superliga"
    assert normalize_league_name("Denmark") == "Danish Superliga"
    assert normalize_league_name("Switzerland") == "Swiss Super League"
    assert normalize_league_name("Austria") == "Austria Bundesliga"
    # Si o liga veche, ca sa se vada ca nu s-a rupt nimic existent.
    assert normalize_league_name("ROM") == "Romania SuperLiga"


# ── Nicio ligă pe jumătate ───────────────────────────────────────────────────

@pytest.mark.parametrize("liga", LIGI_NOI)
def test_liga_noua_e_prezenta_in_toate_locurile_obligatorii(liga):
    """Defectul celor 16 din 18 competiții a existat un sezon întreg fiindcă o
    ligă era într-un loc și nu în altul. Aici se cere prezența simultană."""
    assert liga in LEAGUE_PROVIDERS, "lipsă din LEAGUE_PROVIDERS (sursa canonică)"
    assert liga in TRACKED_COMPETITIONS, "lipsă din TRACKED_COMPETITIONS"
    assert liga in FLASHSCORE_TRACKED_COMPETITIONS, "lipsă din discovery Flashscore"
    assert liga in LEAGUE_BASELINES, "lipsă din LEAGUE_BASELINES"
    assert liga in LEAGUE_ALIASES, "lipsă din LEAGUE_ALIASES"
    assert liga in oracle_engine.DEFAULT_WEIGHTS["league_weights"], "lipsă din ponderile per ligă"


def test_fiecare_competitie_urmarita_de_flashscore_e_si_canonica():
    """Invariantul general, în direcția care contează: Flashscore nu are voie
    să colecteze o competiție pe care sursa canonică nu o cunoaște — ar
    produce rânduri cu o `league` necunoscută restului sistemului."""
    necanonice = set(FLASHSCORE_TRACKED_COMPETITIONS) - set(TRACKED_COMPETITIONS)
    assert not necanonice, f"colectate de Flashscore dar necunoscute canonic: {sorted(necanonice)}"


# ── Ponderile nu sunt o schimbare de model ───────────────────────────────────

@pytest.mark.parametrize("liga", LIGI_NOI)
def test_ponderile_ligilor_noi_sunt_IDENTICE_cu_default(liga):
    """Regula din CLAUDE.md: orice modificare a parametrilor matematici ai
    Oracle e un experiment de calibrare separat, cu aprobare proprie, niciodată
    bundle-uit într-un alt task.

    O ligă nouă nu are calibrare reală (`sample_count=0`), deci singura valoare
    onestă e cea implicită. Garda asta transformă „am copiat default-ul" din
    afirmație în fapt verificat — și ar cădea dacă cineva ar strecura o
    recalibrare sub forma unei adăugări de ligă."""
    ligi = oracle_engine.DEFAULT_WEIGHTS["league_weights"]
    assert ligi[liga] == ligi["default"], (
        f"{liga} are ponderi diferite de 'default' — asta e o schimbare de "
        "parametru matematic, nu o adăugare de ligă")


def test_contrapondere_default_ul_nu_e_gol():
    """Dacă `default` ar deveni `{}`, toate testele de egalitate de mai sus ar
    trece VID — dicționarele goale sunt egale între ele."""
    implicit = oracle_engine.DEFAULT_WEIGHTS["league_weights"]["default"]
    assert len(implicit) >= 7, implicit
    for cheie in ("form_weight", "base_weight", "home_advantage", "away_penalty"):
        assert cheie in implicit, cheie


# ── Baseline-urile sunt date, nu valori alese ────────────────────────────────

@pytest.mark.parametrize("liga", LIGI_NOI)
def test_baseline_ul_e_in_banda_fotbalistica_plauzibila(liga):
    """Nu verifică valoarea exactă (aceea e o cifră citată, cu sursa în
    comentariu), ci că nu e absurdă. Un baseline e jumătate din media de
    goluri pe meci, deci ~1.0-1.8 acoperă orice campionat real; în afara
    benzii înseamnă aproape sigur o eroare de unitate — valoarea întreagă
    scrisă în loc de jumătate, tiparul cel mai probabil."""
    assert 1.0 <= LEAGUE_BASELINES[liga] <= 1.8, LEAGUE_BASELINES[liga]


def test_sursa_fiecarui_baseline_nou_e_scrisa_in_cod():
    """Precedentul din 2026-08-04 citează sursa fiecărei cifre. O cifră fără
    sursă nu se poate reverifica, deci devine folclor la prima întrebare
    „de unde vine 1.29?"."""
    text = (RADACINA / "mappings.py").read_text(encoding="utf-8")
    # Ancorat pe ATRIBUIREA reală (început de linie + `:`), nu pe simpla
    # apariție a numelui. Prima versiune folosea `re.search("LEAGUE_BASELINES
    # .*?\\n\\}")` și a prins un docstring de la începutul fișierului care
    # menționează numele — garda își găsea propriul subiect într-un comentariu.
    # A patra instanță a acestei clase în proiect, după `pipefail` (27 aug),
    # numele de secrete (14 oct) și docstring-ul ADR-073 (14 oct).
    bloc = re.search(r"^LEAGUE_BASELINES\s*:.*?\n\}", text, re.S | re.M)
    assert bloc, "LEAGUE_BASELINES nu mai poate fi citită"
    assert "default" in bloc.group(0), "blocul citit nu e dicționarul de baseline-uri"
    for cifra in ("2.978", "3.140", "2.583"):
        assert cifra in bloc.group(0), (
            f"calculul care produce baseline-ul ({cifra}) nu mai e scris lângă valoare")


# ── Cotele: Flashscore, nu The Odds API ──────────────────────────────────────

@pytest.mark.parametrize("liga", LIGI_NOI)
def test_ligile_noi_NU_sunt_in_odds_sport_keys(liga):
    """Intenționat, nu o omisiune: nu avem nicio cheie The Odds API confirmată
    live pentru aceste ligi, iar una ghicită ar produce cereri către un sport
    inexistent. Cotele vin prin `odds_fallback_flashscore` (ADR-043) —
    verificat live pentru Austria, 6 case pe un meci real.

    Efect secundar util: invariantul `odds ⊂ canonic` (strict) se întărește."""
    assert liga not in ODDS_SPORT_KEYS
    assert LEAGUE_PROVIDERS[liga].provider_ids["odds"] is None


@pytest.mark.parametrize("liga", LIGI_NOI)
def test_niciun_provider_nedovedit_nu_e_marcat_incercabil(liga):
    """`football_providers.py:158` tratează `"necunoscut"` ca „încearcă
    oricum". Pentru o ligă fără NICIUN id de provider, asta ar irosi cereri pe
    apeluri garantat fără țintă. `False` nu e aici o aproximare a unei stări
    necunoscute (North Star #8) — e un fapt: fără id, providerul nu POATE
    servi liga."""
    definitie = LEAGUE_PROVIDERS[liga]
    for provider, id_ in definitie.provider_ids.items():
        if id_ is None:
            assert definitie.supported[provider] is False, (
                f"{liga}/{provider}: fără id, dar marcat "
                f"'{definitie.supported[provider]}' — ar genera cereri inutile")


# ── Catch-up-ul istoric nu intră în night_sync ───────────────────────────────

def test_ligile_noi_nu_sunt_in_setul_de_baza_night_sync():
    """Precedentul din 2026-08-10, scris explicit în `sync/run_night.py`:
    ligile noi rulează separat, ca să nu îngreuneze procesul de noapte.
    `night_sync` are deja cel mai strâns buget de timp din proiect (a fost
    anulat la 180 min pe 16 oct)."""
    text = (RADACINA / "sync" / "run_night.py").read_text(encoding="utf-8")
    bloc = re.search(r"_NIGHT_SYNC_LEAGUES\s*=\s*\[(.*?)\]", text, re.S)
    assert bloc, "_NIGHT_SYNC_LEAGUES nu mai poate fi citită"
    for liga in LIGI_NOI:
        assert liga not in bloc.group(1), (
            f"{liga} a intrat în setul de bază night_sync — decizie care cere "
            "aprobare explicită, nu o adăugare implicită")


def test_catch_up_ul_acopera_toate_cele_sase_ligi_extra():
    """Cele 3 ligi noi primesc catch-up-ul istoric în workflow-ul dedicat, cu
    timeout de 90 min, nu în `live_sync` (50 min, tăiat deja de două ori).

    `live_sync` le va colecta oricum zilnic, fiindcă rulează cu
    `leagues=None` → toate competițiile urmărite de Flashscore; dar prima
    trecere, cea scumpă, are nevoie de marjă."""
    text = (RADACINA / ".github" / "workflows" / "flashscore_extra_leagues.yml").read_text(
        encoding="utf-8")
    for liga in LIGI_NOI + ("Jupiler Pro League", "Ekstraklasa", "Scottish Premiership"):
        assert f"'{liga}'" in text, f"{liga} lipsește din workflow-ul de catch-up"
