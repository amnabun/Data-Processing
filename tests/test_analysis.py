from math import sqrt

import pytest

from chess_analytics.analysis import most_improved, popular_openings
from chess_analytics.models import DataError
from chess_analytics.similarity import BlackOpeningMetric, TimeFormatMetric, similar_players
from chess_analytics.storage import DataStore


def test_popularity_threshold_and_denominator(make_dataset):
    games = [{"Opening": "Common: A"}] * 197 + [{"Opening": "Boundary"}] * 2 + [{"Opening": "Rare"}]
    path, _, _ = make_dataset(games)
    with DataStore(path) as store:
        total, rows = popular_openings(store)
    assert total == 200
    assert [(r.opening, r.games, r.percentage) for r in rows] == [
        ("Common", 197, 98.5),
        ("Boundary", 2, 1.0),
    ]


def test_filters_are_inclusive_and_preserve_half_ratings(make_dataset):
    path, _, _ = make_dataset(
        [
            {"WhiteElo": "1500", "BlackElo": "1500"},
            {"WhiteElo": "1501", "BlackElo": "1500"},
            {"WhiteElo": "1501", "BlackElo": "1501"},
            {"TimeControl": "60+0", "WhiteElo": "1500", "BlackElo": "1500"},
        ]
    )
    with DataStore(path) as store:
        assert popular_openings(store, "blitz", 1500, 1501)[0] == 3
        assert popular_openings(store, "blitz", 1500, 1500)[0] == 1
        assert popular_openings(store, min_rating=1501)[0] == 1
        assert popular_openings(store, max_rating=1500)[0] == 2
        assert popular_openings(store, min_rating=-1)[0] == 4
        assert popular_openings(store, max_rating=-1) == (0, [])
        assert popular_openings(store, min_rating=-(10**30), max_rating=10**30)[0] == 4
        assert popular_openings(store, min_rating=10**30) == (0, [])
        assert popular_openings(store, max_rating=-(10**30)) == (0, [])
        assert popular_openings(store, "rapid") == (0, [])
        with pytest.raises(DataError):
            popular_openings(store, min_rating=2000, max_rating=1000)


def test_improvement_uses_first_and_last_not_sum_or_file_order(make_dataset):
    path, _, _ = make_dataset(
        [
            {"UTCTime": "12:00:00", "WhiteElo": "1600", "WhiteRatingDiff": "+20"},
            {"UTCTime": "09:00:00", "WhiteElo": "1400", "WhiteRatingDiff": "+5"},
            {
                "UTCTime": "10:00:00",
                "White": "Carol",
                "Black": "Alice",
                "BlackElo": "1500",
                "BlackRatingDiff": "-10",
            },
            {"UTCTime": "23:00:00", "WhiteElo": "2800", "TimeControl": "60+0"},
        ]
    )
    with DataStore(path) as store:
        rows = most_improved(store, "blitz")
        assert most_improved(store, "rapid") == []
    alice = next(row for row in rows if row.player == "Alice")
    assert (alice.initial_rating, alice.final_rating, alice.improvement, alice.games) == (
        1400,
        1620,
        220,
        3,
    )
    assert rows[0].player == "Alice"


def test_equal_timestamps_use_source_order(make_dataset):
    path, _, _ = make_dataset([{"WhiteElo": "1400"}, {"WhiteElo": "1600"}])
    with DataStore(path) as store:
        alice = next(r for r in most_improved(store, "blitz") if r.player == "Alice")
    assert (alice.initial_rating, alice.final_rating) == (1400, 1610)


def test_top_ten_and_name_ties(make_dataset):
    path, _, _ = make_dataset([{"White": f"Player{i:02}"} for i in range(15)])
    with DataStore(path) as store:
        rows = most_improved(store, "blitz")
    assert [r.player for r in rows] == [f"Player{i:02}" for i in range(10)]


def test_time_format_percentages_and_euclidean_distance(make_dataset):
    path, _, _ = make_dataset(
        [
            {"White": "Target", "Black": "Exact", "TimeControl": "60+0"},
            {"White": "Target", "Black": "Exact", "TimeControl": "180+0"},
            {"White": "BulletOnly", "Black": "Other", "TimeControl": "60+0"},
        ]
    )
    metric = TimeFormatMetric()
    with DataStore(path) as store:
        assert metric.profiles(store)["Target"] == (50, 50, 0)
        rows = similar_players(store, "Target", metric)
    assert rows[0].player == "Exact"
    assert rows[0].distance == 0
    assert rows[1].distance == pytest.approx(sqrt(50**2 + 50**2))
    assert "Target" not in [r.player for r in rows]


def test_black_openings_only_same_favourite_and_black_denominator(make_dataset):
    games = (
        [{"Black": "Target", "Opening": "Sicilian"}] * 3
        + [{"Black": "Target", "Opening": "French"}]
        + [{"Black": "Close", "Opening": "Sicilian"}] * 4
        + [{"Black": "Close", "Opening": "French"}]
        + [{"Black": "Different", "Opening": "French"}] * 4
        + [{"White": "Target", "Black": "WhiteOpponent", "Opening": "Other"}] * 10
    )
    path, _, _ = make_dataset(games)
    metric = BlackOpeningMetric()
    with DataStore(path) as store:
        assert metric.profiles(store)["Target"].percentage == 75
        rows = similar_players(store, "Target", metric)
        with pytest.raises(DataError, match="no games"):
            similar_players(store, "Alice", metric)
        with pytest.raises(DataError, match="does not appear"):
            similar_players(store, "Missing", metric)
    assert [(r.player, r.distance) for r in rows] == [("Close", 5)]


def test_favourite_ties_are_alphabetical(make_dataset):
    path, _, _ = make_dataset([{"Opening": "Zebra"}, {"Opening": "Alpha"}])
    with DataStore(path) as store:
        profile = BlackOpeningMetric().profiles(store)["Bob"]
    assert (profile.opening, profile.percentage) == ("Alpha", 50)


def test_new_metric_works_without_changing_sorter(make_dataset):
    class NameLengthMetric:
        def profiles(self, store):
            return {name: len(name) for name in store.search_players()}

        def distance(self, reference, candidate):
            return abs(reference - candidate)

        def describe(self, profile):
            return f"{profile} letters"

    path, _, _ = make_dataset(
        [{"White": "Alice", "Black": "Brian"}, {"White": "Alice", "Black": "Bo"}]
    )
    with DataStore(path) as store:
        rows = similar_players(store, "Alice", NameLengthMetric())
    assert [(r.player, r.distance) for r in rows] == [("Brian", 0), ("Bo", 3)]
