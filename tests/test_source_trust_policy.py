from source_trust_policy import SOURCE_TRUST_RANK, SourceTrustProvider


def test_known_sources_have_distinct_ranks():
    ranks = list(SOURCE_TRUST_RANK.values())
    assert len(ranks) == len(set(ranks))


def test_football_data_is_most_trusted():
    assert SourceTrustProvider.get_rank("football_data") == 1


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
        "football_data", "espn", "odds_api", "kaggle_historical",
    }
