from source_trust_policy import (
    _ADR024_RELATIVE_ORDER,
    SOURCE_TRUST_RANK,
    SourceTrustProvider,
)


def test_known_sources_have_distinct_ranks():
    ranks = list(SOURCE_TRUST_RANK.values())
    assert len(ranks) == len(set(ranks))


def test_flashscore_is_most_trusted():
    """[F4.3] Foundation Data Layer (ADR-044) — singura sursa cu xG real,
    posesie, evenimente si statistici de jucatori, si singura cu copii FK in
    cele 5 tabele derivate. Masurat pe meciuri terminate: 59,0 coloane medii
    non-NULL vs. 38,4 la football_data. Justificarea completa e in antetul
    `source_trust_policy.py`."""
    rank = SourceTrustProvider.get_rank("flashscore")
    other_ranks = [r for s, r in SOURCE_TRUST_RANK.items() if s != "flashscore"]
    assert all(rank < other for other in other_ranks)


def test_kaggle_historical_is_least_trusted():
    kaggle_rank = SourceTrustProvider.get_rank("kaggle_historical")
    other_ranks = [
        rank for source, rank in SOURCE_TRUST_RANK.items()
        if source != "kaggle_historical"
    ]
    assert all(kaggle_rank > rank for rank in other_ranks)


def test_unknown_source_returns_none():
    assert SourceTrustProvider.get_rank("sofascore") is None


def test_all_expected_sources_present():
    assert set(SOURCE_TRUST_RANK) == {
        "flashscore", "football_data", "tsdb", "espn", "odds_api",
        "openfootball", "kaggle_historical",
    }


def test_preexisting_relative_order_is_preserved():
    """[F4.3] Invariantul central al extinderii: inserarea de surse noi nu are
    voie sa redeschida calibrarea ADR-024. Daca ordinea relativa a celor 4
    surse originale s-ar schimba, deciziile deja scrise in productie
    (3.501 grupuri `football_data` > `kaggle_historical` + 3 grupuri World Cup
    `espn` > `odds_api`, executate 2026-07-16) ar deveni retroactiv
    inconsistente cu politica curenta."""
    ranks = [SourceTrustProvider.get_rank(s) for s in _ADR024_RELATIVE_ORDER]
    assert all(r is not None for r in ranks)
    assert ranks == sorted(ranks), (
        f"Ordinea relativa ADR-024 a fost incalcata: {_ADR024_RELATIVE_ORDER} "
        f"-> {ranks}"
    )


def test_historical_adr025_decisions_are_not_reversed():
    """[F4.3] Verificarea directa a celor doua perechi care au produs efectiv
    scrieri in productie la ADR-025 Faza 4. Sub rangurile noi, acelasi rand
    trebuie sa ramana canonic."""
    assert SourceTrustProvider.get_rank("football_data") < SourceTrustProvider.get_rank("kaggle_historical")
    assert SourceTrustProvider.get_rank("espn") < SourceTrustProvider.get_rank("odds_api")


def test_sources_with_real_statistics_outrank_sources_without():
    """[F4.3] Cele doua surse fara nicio statistica de meci (0% shots/corners/
    posesie/xG, masurat live) trebuie sa ramana sub toate sursele care aduc
    statistici reale — altfel merge-ul non-destructiv (ID-025-01, Pasul 3,
    SOFT CONFLICT) ar prefera valoarea sursei mai sarace."""
    statless = ("openfootball", "kaggle_historical")
    with_stats = ("flashscore", "football_data", "tsdb")
    for poor in statless:
        for rich in with_stats:
            assert SourceTrustProvider.get_rank(rich) < SourceTrustProvider.get_rank(poor)


def test_tsdb_stays_below_football_data_despite_better_per_row_profile():
    """[F4.3] Decizie deliberata, nu omisiune: tsdb are cel mai bun profil per
    rand din tot corpusul (69,1 coloane medii, 100% pe toate statisticile) DAR
    pe n=13 meciuri terminate. Plasarea peste football_data (n=7.534) ar fi o
    inferenta din esantion mic — exact ce interzice regula «Verificat, nu
    presupus». Acest test exista ca decizia sa nu fie inversata tacit."""
    assert SourceTrustProvider.get_rank("football_data") < SourceTrustProvider.get_rank("tsdb")
