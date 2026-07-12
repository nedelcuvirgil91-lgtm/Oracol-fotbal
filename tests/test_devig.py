import sys

sys.path.insert(0, "/home/claude/stubs")

from oracle_engine import FootballOracleEngine


# ── Suma normalizata trebuie sa fie 1.0 (cu toleranta numerica) ──────────

def test_devig_sum_equals_one_for_typical_bookmaker_odds():
    """Cote tipice, cu marja bookmaker reala (~5-8% overround)."""
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 1/3.80  # suma bruta > 1 (are marja)
    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    assert abs((fh + fd + fa) - 1.0) < 1e-9


def test_devig_sum_equals_one_for_heavy_favorite():
    impl_h, impl_d, impl_a = 1/1.10, 1/9.00, 1/15.00
    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    assert abs((fh + fd + fa) - 1.0) < 1e-9


# ── Probabilitatile raman in (0, 1) ──────────────────────────────────────

def test_devig_probabilities_stay_in_valid_range():
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 1/3.80
    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    for p in (fh, fd, fa):
        assert 0.0 < p < 1.0


# ── Cazuri limita ─────────────────────────────────────────────────────────

def test_devig_all_odds_missing_returns_zeros_not_division_error():
    fh, fd, fa = FootballOracleEngine._devig_probabilities(0.0, 0.0, 0.0)
    assert (fh, fd, fa) == (0.0, 0.0, 0.0)


def test_devig_one_odd_missing_still_normalizes_correctly():
    """Doar home+draw disponibile (away lipsa/invalida -> impl_a=0)."""
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 0.0
    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    assert fa == 0.0
    assert abs((fh + fd) - 1.0) < 1e-9


def test_devig_very_short_odds_close_to_one():
    """Cota foarte mica (favorit masiv, aproape de limita 1.0)."""
    impl_h, impl_d, impl_a = FootballOracleEngine._implied(1.01), FootballOracleEngine._implied(15.0), FootballOracleEngine._implied(25.0)
    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    assert abs((fh + fd + fa) - 1.0) < 1e-9
    assert fh > 0.9  # favoritul ramane clar dominant si dupa normalizare


def test_devig_invalid_odds_below_one_produce_zero_implied():
    """_implied() insusi trebuie sa respinga cote <=1 (deja acoperit de
    _implied, dar verificam ca de-vig gestioneaza corect intrarea 0.0)."""
    impl_h = FootballOracleEngine._implied(0.5)   # cota invalida -> 0.0
    assert impl_h == 0.0


# ── Comparatie explicita: brut vs de-vig-uit ─────────────────────────────

def test_devig_fair_probability_always_less_than_or_equal_raw_when_margin_exists():
    """Cu marja pozitiva (cazul normal la orice bookmaker real), suma bruta
    > 1, deci fiecare probabilitate FAIR trebuie sa fie STRICT mai mica
    decat cea bruta corespunzatoare (impartire la un numar >1)."""
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 1/3.80
    raw_sum = impl_h + impl_d + impl_a
    assert raw_sum > 1.0, "testul presupune cote cu marja reala (suma bruta > 1)"

    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)

    assert fh < impl_h
    assert fd < impl_d
    assert fa < impl_a


def test_devig_reduces_apparent_margin_to_exactly_zero():
    """Diferenta cheie fata de valorile brute: suma brutelor = marja
    bookmakerului (>0), suma celor de-vig-uite = exact 0 marja (=1.0)."""
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 1/3.80
    raw_margin = (impl_h + impl_d + impl_a) - 1.0
    assert raw_margin > 0.0  # marja reala, pozitiva

    fh, fd, fa = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)
    fair_margin = (fh + fd + fa) - 1.0
    assert abs(fair_margin) < 1e-9  # exact zero dupa normalizare


def test_edge_calculation_uses_fair_not_raw_changes_result():
    """Verificare end-to-end a impactului: edge calculat cu fair trebuie sa
    difere (de regula sa fie MAI MARE) fata de edge calculat cu impl brut,
    exact motivul pentru care de-vig conteaza."""
    impl_h, impl_d, impl_a = 1/2.00, 1/3.40, 1/3.80
    fair_h, _, _ = FootballOracleEngine._devig_probabilities(impl_h, impl_d, impl_a)

    model_p = 0.55  # modelul crede 55% sansa la victorie gazde
    edge_raw = FootballOracleEngine._edge(model_p, impl_h)
    edge_fair = FootballOracleEngine._edge(model_p, fair_h)

    assert edge_fair > edge_raw, (
        "edge-ul calculat cu probabilitatea fair (mai mica decat bruta, "
        "din cauza eliminarii marjei) trebuie sa fie mai mare decat edge-ul "
        "vechi, calculat gresit cu probabilitatea umflata de marja"
    )
