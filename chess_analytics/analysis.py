"""Opening frequencies and chronological rating improvement."""

from .models import DataError, OpeningPopularity, PlayerImprovement, TimeControl
from .storage import APPEARANCES, DataStore


def popular_openings(
    store: DataStore,
    time_control: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
) -> tuple[int, list[OpeningPopularity]]:
    """Return the matching game count and openings used in at least 1% of them.

    Both rating bounds are inclusive. Percentages use every matching game as
    their denominator, including openings that fall below the display threshold.
    """
    clauses, values = [], []
    if time_control is not None:
        TimeControl(time_control)
        clauses.append("time_control = ?")
        values.append(time_control)
    for bound in (min_rating, max_rating):
        if bound is not None and (type(bound) is not int or not 0 <= bound <= 2**31 - 1):
            raise DataError("Rating bounds must be integers between 0 and 2147483647.")
    if min_rating is not None and max_rating is not None and min_rating > max_rating:
        raise DataError("Minimum rating cannot be greater than maximum rating.")
    if min_rating is not None:
        clauses.append("game_rating >= ?")
        values.append(min_rating)
    if max_rating is not None:
        clauses.append("game_rating <= ?")
        values.append(max_rating)
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
    """First pre-game to last post-game rating, restricted to one time control.

    Source order resolves equal timestamps. Rating changes are not summed:
    games missing from the sample may have changed a player's rating too.
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
