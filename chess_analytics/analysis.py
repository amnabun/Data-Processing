"""Opening popularity and player rating changes over time."""

from math import inf

from .models import DataError, OpeningPopularity, PlayerImprovement, TimeControl
from .storage import APPEARANCES, DataStore


def popular_openings(
    store: DataStore,
    time_control: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
) -> tuple[int, list[OpeningPopularity]]:
    """Return the matching game count and openings used in at least 1% of them.

    Both rating bounds are inclusive. Count every matching game in the percentage
    calculation, even if its opening falls below the 1% threshold.
    """
    clauses, values = [], []
    if time_control is not None:
        TimeControl(time_control)
        clauses.append("time_control = ?")
        values.append(time_control)
    for bound in (min_rating, max_rating):
        if bound is not None and type(bound) is not int:
            raise DataError("Rating bounds must be integers.")
    if min_rating is not None and max_rating is not None and min_rating > max_rating:
        raise DataError("Minimum rating cannot be greater than maximum rating.")
    for operator, bound in ((">=", min_rating), ("<=", max_rating)):
        if bound is None:
            continue
        clauses.append(f"game_rating {operator} ?")
        # SQLite binds integers as signed 64-bit values. Use infinity for bounds beyond that range.
        if bound < -(2**63):
            bound = -inf
        elif bound >= 2**63:
            bound = inf
        values.append(bound)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    counts = list(
        store.connection.execute(
            "SELECT opening, count(*) AS games FROM games"
            + where
            + " GROUP BY opening ORDER BY games DESC, opening",
            values,
        )
    )
    total = sum(row["games"] for row in counts)
    return total, [
        OpeningPopularity(row["opening"], row["games"], 100 * row["games"] / total)
        for row in counts
        if row["games"] * 100 >= total
    ]


def most_improved(store: DataStore, time_control: str) -> list[PlayerImprovement]:
    """Rank players by rating gain within one time control.

    Subtract the first game's pre-game rating from the last game's post-game rating.
    This captures changes from games missing from the sample. Use the original file
    order when timestamps match.
    """
    TimeControl(time_control)
    query = f"""
        WITH appearances AS ({APPEARANCES}), ranked AS (
            SELECT player, pre, post,
                   row_number() OVER (PARTITION BY player ORDER BY played_at, id) AS first_game,
                   row_number() OVER (PARTITION BY player ORDER BY played_at DESC, id DESC) AS last_game
            FROM appearances WHERE time_control = ?
        ), totals AS (
            SELECT player,
                   max(CASE WHEN first_game = 1 THEN pre END) AS initial,
                   max(CASE WHEN last_game = 1 THEN post END) AS final,
                   count(*) AS games
            FROM ranked GROUP BY player
        )
        SELECT player, initial, final, games FROM totals
        ORDER BY (final - initial) DESC, player LIMIT 10
    """
    return [PlayerImprovement(*row) for row in store.connection.execute(query, (time_control,))]
