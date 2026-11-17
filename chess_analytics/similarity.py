"""Pluggable similarity metrics and one shared ranking routine."""

from dataclasses import dataclass
from heapq import nsmallest
from math import dist
from typing import Any, Iterable, Protocol

from .models import DataError, SimilarPlayer
from .storage import APPEARANCES, DataStore


class SimilarityMetric(Protocol):
    """Implement these three methods to add a metric without changing the sorter."""

    def profiles(self, store: DataStore) -> dict[str, Any]: ...

    def distance(self, reference: Any, candidate: Any) -> float | None:
        """Return None to exclude an incompatible candidate."""
        ...

    def describe(self, profile: Any) -> str: ...


class TimeFormatMetric:
    def profiles(self, store: DataStore) -> dict[str, tuple[float, float, float]]:
        rows = store.connection.execute(f"""
            WITH appearances AS ({APPEARANCES})
            SELECT player, sum(time_control = 'bullet'), sum(time_control = 'blitz'),
                   sum(time_control = 'rapid'), count(*)
            FROM appearances GROUP BY player
        """)
        return {row[0]: tuple(100 * count / row[4] for count in row[1:4]) for row in rows}

    def distance(self, reference, candidate) -> float:
        return dist(reference, candidate)

    def describe(self, profile) -> str:
        return "Bullet {:.2f}% | Blitz {:.2f}% | Rapid {:.2f}%".format(*profile)


@dataclass(frozen=True)
class BlackOpeningProfile:
    opening: str
    percentage: float


class BlackOpeningMetric:
    def profiles(self, store: DataStore) -> dict[str, BlackOpeningProfile]:
        # A tied favourite is resolved alphabetically, consistently for every player.
        # White games do not contribute to either the count or the denominator.
        rows = store.connection.execute("""
            WITH counts AS (
                SELECT black AS player, opening, count(*) AS games
                FROM games GROUP BY black, opening
            ), favourites AS (
                SELECT player, opening, games,
                       sum(games) OVER (PARTITION BY player) AS total,
                       row_number() OVER (PARTITION BY player ORDER BY games DESC, opening) AS place
                FROM counts
            )
            SELECT player, opening, 100.0 * games / total FROM favourites WHERE place = 1
        """)
        return {row[0]: BlackOpeningProfile(row[1], row[2]) for row in rows}

    def distance(
        self, reference: BlackOpeningProfile, candidate: BlackOpeningProfile
    ) -> float | None:
        if reference.opening != candidate.opening:
            return None
        return abs(reference.percentage - candidate.percentage)

    def describe(self, profile: BlackOpeningProfile) -> str:
        return f"{profile.opening}: {profile.percentage:.2f}% of black games"


METRICS: dict[str, SimilarityMetric] = {
    "time-formats": TimeFormatMetric(),
    "black-openings": BlackOpeningMetric(),
}


def similar_players(
    store: DataStore,
    player: str,
    metric: SimilarityMetric,
    limit: int = 10,
) -> list[SimilarPlayer]:
    """Rank using the supplied metric; exclude the reference player and break ties by name."""
    if not store.has_player(player):
        raise DataError(
            f"Player '{player}' does not appear in this dataset. Names are case-sensitive."
        )
    profiles = metric.profiles(store)
    if player not in profiles:
        raise DataError(
            f"Player '{player}' has no games eligible for this metric (no games as black)."
        )
    reference = profiles[player]

    def candidates() -> Iterable[SimilarPlayer]:
        for name, profile in profiles.items():
            if name != player:
                distance = metric.distance(reference, profile)
                if distance is not None:
                    yield SimilarPlayer(name, distance, metric.describe(profile))

    return nsmallest(limit, candidates(), key=lambda item: (item.distance, item.player))
