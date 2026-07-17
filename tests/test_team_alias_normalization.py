"""
Test permanent de infrastructură pentru TEAM_ALIASES / normalize_team_name().

Motivație: auditul din 2026-07-13 (vezi
docs/03_ENGINE/TEAM_ALIASES_INFRASTRUCTURE_AUDIT_2026-07-13.md) a demonstrat
că 9 din 24 echipe din Premier League (37.5%) nu se normalizau la aceeași
formă canonică între sursa football-data.co.uk și match_history — un bug
de infrastructură canonică, nu un bug specific Odds. Acest fișier NU
testează Odds Infrastructure; testează exclusiv corectitudinea
`mappings.normalize_team_name()`, folosită de orice sursă (ELO, Odds, xG,
statistici, competiții noi).

Trei clase de protecție:
  1. Structural — orice alias declarat în TEAM_ALIASES trebuie să
     normalizeze la aceeași formă ca și cheia lui canonică (altfel intrarea
     e inutilă/greșit scrisă).
  2. Anti-coliziune — niciun alias nu poate aparține simultan la două
     grupuri canonice diferite (ar uni silențios două cluburi diferite).
  3. Regresie pe perechi reale — perechi (sursă, match_history) verificate
     direct în producție (Supabase, proiect Prediction) pentru fiecare
     ligă din roadmap. Dacă vreuna din aceste perechi încetează să
     normalizeze identic, infrastructura de matching s-a stricat.
"""
import pytest

from mappings import TEAM_ALIASES, ALIAS_TO_CANONICAL, normalize_team_name


def test_every_alias_normalizes_to_its_canonical_key():
    """Fiecare alias declarat trebuie să ajungă la aceeași formă normalizată
    ca și cheia canonică sub care e listat — altfel intrarea nu are efect
    real (regresie tăcută dacă cineva editează greșit o listă)."""
    failures = []
    for canonical, aliases in TEAM_ALIASES.items():
        target = normalize_team_name(canonical)
        for alias in aliases:
            if normalize_team_name(alias) != target:
                failures.append((canonical, alias, normalize_team_name(alias), target))
    assert not failures, (
        "Aliasuri care nu normalizeaza la propriul canonical:\n" +
        "\n".join(f"  {c!r}: alias {a!r} -> {got!r}, asteptat {exp!r}"
                   for c, a, got, exp in failures)
    )


def test_no_alias_shared_between_different_canonical_groups():
    """Un alias nu poate aparține la doi câștigători canonici diferiți —
    ar contopi silențios doua cluburi reale distincte (ex. riscul deja
    documentat Universitatea Craiova vs U Craiova 1948)."""
    owner: dict[str, str] = {}
    collisions = []
    for canonical, aliases in TEAM_ALIASES.items():
        for name in [canonical, *aliases]:
            key = name.lower()
            if key in owner and owner[key] != canonical:
                collisions.append((name, owner[key], canonical))
            else:
                owner[key] = canonical
    assert not collisions, (
        "Aliasuri duplicate intre grupuri canonice diferite:\n" +
        "\n".join(f"  {n!r} apartine si de {a!r} si de {b!r}" for n, a, b in collisions)
    )


def test_alias_to_canonical_is_derived_not_stale():
    """ALIAS_TO_CANONICAL trebuie sa reflecte exact TEAM_ALIASES curent —
    protectie daca cineva populeaza manual una fara cealalta."""
    rebuilt: dict[str, str] = {}
    for canonical, aliases in TEAM_ALIASES.items():
        rebuilt[canonical.lower()] = canonical
        for alias in aliases:
            rebuilt[alias.lower()] = canonical
    assert ALIAS_TO_CANONICAL == rebuilt


# ── Perechi reale (sursă externă -> formă din match_history), verificate
#    direct in Supabase / football-data.co.uk in cadrul auditului. Fiecare
#    ligă din roadmap e reprezentată. Nu sunt ipotetice — sunt cazuri care
#    au produs efectiv rate de matching gresite inainte de acest fix. ──
REAL_WORLD_PAIRS = [
    # Premier League — cele 8 gap-uri demonstrate initial + 2 promovate
    ("Bournemouth", "AFC Bournemouth"),
    ("Burnley", "Burnley FC"),
    ("Ipswich", "Ipswich Town FC"),
    ("Luton", "Luton Town FC"),
    ("Sheffield United", "Sheffield United FC"),
    ("Southampton", "Southampton FC"),
    ("Nott'm Forest", "Nottingham Forest FC"),
    ("Nottm Forest", "Nottingham Forest FC"),
    ("Brighton", "Brighton & Hove Albion FC"),
    ("Leeds", "Leeds United FC"),
    ("Sunderland", "Sunderland AFC"),
    # La Liga
    ("Ath Bilbao", "Athletic Club"),
    ("Ath Madrid", "Club Atlético de Madrid"),
    ("Sociedad", "Real Sociedad de Fútbol"),
    ("Espanol", "RCD Espanyol de Barcelona"),
    ("Vallecano", "Rayo Vallecano de Madrid"),
    ("Leganes", "CD Leganés"),
    # Serie A
    ("Inter", "FC Internazionale Milano"),
    ("Verona", "Hellas Verona FC"),
    ("Bologna", "Bologna FC 1909"),
    ("Cagliari", "Cagliari Calcio"),
    # Bundesliga
    ("Ein Frankfurt", "Eintracht Frankfurt"),
    ("M'gladbach", "Borussia Mönchengladbach"),
    ("MGladbach", "Borussia Mönchengladbach"),
    ("FC Koln", "1. FC Köln"),
    ("Mainz", "1. FSV Mainz 05"),
    # Ligue 1
    ("Paris SG", "Paris Saint-Germain FC"),
    ("Monaco", "AS Monaco FC"),
    ("Lens", "Racing Club de Lens"),
    ("Rennes", "Stade Rennais FC 1901"),
    ("St Etienne", "AS Saint-Étienne"),
    # Romania SuperLiga — diacritice ASCII vs forma diacritica din DB
    ("Farul Constanta", "Farul Constanța"),
    ("FC Rapid Bucuresti", "Rapid București"),
    ("Univ. Craiova", "Universitatea Craiova"),
    # Champions League / Europa League — forme multiple confirmate direct
    # in match_history (provideri diferiti pentru aceeasi liga)
    ("Chelsea", "Chelsea FC"),
    ("Juventus", "Juventus FC"),
    ("Liverpool", "Liverpool FC"),
    ("Real Madrid", "Real Madrid CF"),
    ("FC PORTO", "FC Porto"),
    ("BSC YOUNG BOYS", "BSC Young Boys"),
    ("CLUB BRUGGE", "Club Brugge KV"),
    ("BENFICA", "Sport Lisboa e Benfica"),
    ("GALATASARAY", "Galatasaray SK"),
]


@pytest.mark.parametrize("source_form,match_history_form", REAL_WORLD_PAIRS)
def test_known_real_world_pair_normalizes_identically(source_form, match_history_form):
    assert normalize_team_name(source_form) == normalize_team_name(match_history_form), (
        f"{source_form!r} si {match_history_form!r} ar trebui sa normalizeze identic "
        f"(perechi reale confirmate in producție) — au ajuns la "
        f"{normalize_team_name(source_form)!r} vs {normalize_team_name(match_history_form)!r}"
    )


def test_universitatea_craiova_and_u_craiova_1948_stay_distinct():
    """Nu se contopesc — sunt doua cluburi reale distincte cu istorie
    disputata, confirmat separat in match_history (Romania SuperLiga)."""
    assert normalize_team_name("Universitatea Craiova") != normalize_team_name("U Craiova 1948")
    assert normalize_team_name("U Craiova 1948") == "U Craiova 1948", (
        "U Craiova 1948 nu are alias inregistrat — trebuie sa ramana neschimbat, "
        "nu aproximat catre Universitatea Craiova"
    )


def test_unknown_team_name_stays_unchanged_not_guessed():
    """Principiul de siguranta al normalize_team_name(): o echipa
    necunoscuta ramane neschimbata, nu e aproximata fuzzy."""
    unknown = "Complet Necunoscut FC Xyz 123"
    assert normalize_team_name(unknown) == unknown
