"""Versioned SQLite storage. Use each connection in the thread that opened it."""

import sqlite3
from pathlib import Path

from .models import DataError

SCHEMA_VERSION = 1
APPLICATION_ID = 0x43483241
GAME_COLUMNS = (
    "id",
    "white",
    "black",
    "white_pre",
    "black_pre",
    "white_post",
    "black_post",
    "game_rating",
    "opening",
    "time_control",
    "played_at",
)
SCHEMA = """
CREATE TABLE games (
    id INTEGER PRIMARY KEY,
    white TEXT NOT NULL CHECK(length(trim(white)) > 0),
    black TEXT NOT NULL CHECK(length(trim(black)) > 0 AND black != white),
    white_pre INTEGER NOT NULL CHECK(typeof(white_pre) = 'integer' AND white_pre >= 0),
    black_pre INTEGER NOT NULL CHECK(typeof(black_pre) = 'integer' AND black_pre >= 0),
    white_post INTEGER NOT NULL CHECK(typeof(white_post) = 'integer' AND white_post >= 0),
    black_post INTEGER NOT NULL CHECK(typeof(black_post) = 'integer' AND black_post >= 0),
    game_rating REAL NOT NULL CHECK(game_rating = (white_pre + black_pre) / 2.0),
    opening TEXT NOT NULL CHECK(length(trim(opening)) > 0),
    time_control TEXT NOT NULL CHECK(time_control IN ('bullet', 'blitz', 'rapid')),
    played_at TEXT NOT NULL CHECK(length(played_at) = 20 AND played_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
);
"""
INDEXES = """
CREATE INDEX games_filter ON games(time_control, game_rating);
CREATE INDEX games_white ON games(white);
CREATE INDEX games_black ON games(black, opening);
"""
APPEARANCES = """
SELECT id, white AS player, white_pre AS pre, white_post AS post, time_control, played_at
FROM games
UNION ALL
SELECT id, black AS player, black_pre AS pre, black_post AS post, time_control, played_at
FROM games
"""


class DataStore:
    """Open a processed dataset read-only. Use a with block to close the connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise DataError(f"Data file does not exist or is not a regular file: {self.path}")
        self.connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA query_only = ON")
            self.connection.execute("PRAGMA trusted_schema = OFF")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            app_id = self.connection.execute("PRAGMA application_id").fetchone()[0]
            columns = tuple(row[1] for row in self.connection.execute("PRAGMA table_info(games)"))
            if version != SCHEMA_VERSION or app_id != APPLICATION_ID or columns != GAME_COLUMNS:
                raise DataError(
                    "Not a supported coursework dataset. Preprocess the raw PGN file first."
                )
            check = self.connection.execute("PRAGMA quick_check(1)").fetchone()[0]
            if check != "ok":
                raise DataError(f"The processed data is damaged: {check}")
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "DataStore":
        return self

    def __exit__(self, *_args) -> None:
        self.connection.close()

    def game_count(self) -> int:
        return self.connection.execute("SELECT count(*) FROM games").fetchone()[0]

    def has_player(self, name: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM games WHERE white = ? OR black = ? LIMIT 1", (name, name)
            ).fetchone()
            is not None
        )

    def search_players(
        self, query: str = "", limit: int = 200, *, black_only: bool = False
    ) -> list[str]:
        # Escape SQL wildcards so a search for '%' matches a literal percent sign.
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        black_query = "SELECT black AS player FROM games WHERE black LIKE ? ESCAPE '\\'"
        if black_only:
            query = f"SELECT DISTINCT player FROM ({black_query})"
            params = (pattern, limit)
        else:
            query = (
                "SELECT white AS player FROM games WHERE white LIKE ? ESCAPE '\\' UNION "
                + black_query
            )
            params = (pattern, pattern, limit)
        rows = self.connection.execute(query + " ORDER BY player LIMIT ?", params)
        return [row[0] for row in rows]
