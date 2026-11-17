"""Stream PGN headers into an atomic, disk-backed dataset.

PGN skimming follows python-chess's HeadersBuilder API:
https://python-chess.readthedocs.io/en/latest/pgn.html#skimming
Moves are deliberately not parsed or stored; this application analyses metadata.
"""

import os
import sqlite3
import tempfile
from collections import Counter
from dataclasses import astuple, dataclass, field
from pathlib import Path
from typing import Callable

import chess.pgn

try:
    from compression import zstd
except ImportError:  # Python 3.10-3.13 use the same API via the maintained backport.
    from backports import zstd

from .models import DataError, Game
from .storage import APPLICATION_ID, INDEXES, SCHEMA, SCHEMA_VERSION


@dataclass
class ImportSummary:
    seen: int = 0
    saved: int = 0
    excluded: int = 0
    invalid: int = 0
    reasons: Counter = field(default_factory=Counter)

    def describe(self) -> str:
        lines = [
            f"Read {self.seen:,} games; saved {self.saved:,}; "
            f"excluded time controls: {self.excluded:,}; invalid metadata: {self.invalid:,}."
        ]
        lines.extend(f"  {count:,}: {reason}" for reason, count in self.reasons.most_common())
        return "\n".join(lines)


class UniqueHeaders(chess.pgn.HeadersBuilder):
    """Reject ambiguous duplicate tags instead of silently keeping the last value."""

    def visit_header(self, tagname: str, tagvalue: str) -> None:
        if tagname in self.headers:
            raise DataError(f"Duplicate PGN header: {tagname}.")
        super().visit_header(tagname, tagvalue)


def preprocess(
    source: str | Path,
    destination: str | Path,
    *,
    overwrite: bool = False,
    progress: Callable[[int], None] | None = None,
) -> ImportSummary:
    """Import valid games, report skipped records, and publish only a complete file.

    Missing metadata is never invented. Recoverable record errors are counted;
    unreadable, corrupt or truncated streams abort without replacing the output.
    Equal timestamps retain source order through the generated game IDs.
    """
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if not source.is_file():
        raise DataError(f"Raw data file does not exist: {source}")
    if source == destination or (destination.exists() and os.path.samefile(source, destination)):
        raise DataError("Input and output must be different files.")
    if destination.exists() and not overwrite:
        raise DataError("The output already exists. Choose another file or use --overwrite.")
    if not destination.parent.is_dir():
        raise DataError(f"Output folder does not exist: {destination.parent}")

    summary = ImportSummary()
    fd, temporary_name = tempfile.mkstemp(prefix=".cw2-", suffix=".sqlite", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(SCHEMA)
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        # Detect compressed input by its magic bytes, not only the filename.
        with source.open("rb") as probe:
            magic = probe.read(4)
        compressed = magic == b"\x28\xb5\x2f\xfd" or source.suffix.lower() == ".zst"
        opener = zstd.open if compressed else open
        batch = []
        with opener(source, "rt", encoding="utf-8-sig") as stream:
            while (headers := chess.pgn.read_game(stream, Visitor=UniqueHeaders)) is not None:
                summary.seen += 1
                try:
                    game = Game.from_headers(headers)
                except DataError as exc:
                    summary.invalid += 1
                    summary.reasons[str(exc)] += 1
                else:
                    if game is None:
                        summary.excluded += 1
                    else:
                        batch.append(astuple(game))
                        summary.saved += 1
                if len(batch) >= 5000:
                    connection.executemany(
                        "INSERT INTO games VALUES (NULL, ?,?,?,?,?,?,?,?,?,?)", batch
                    )
                    connection.commit()
                    batch.clear()
                if progress and summary.seen % 10000 == 0:
                    progress(summary.seen)
        if summary.seen == 0 or (summary.saved == 0 and summary.invalid > 0):
            raise DataError("No usable game metadata was found. " + summary.describe())
        connection.executemany("INSERT INTO games VALUES (NULL, ?,?,?,?,?,?,?,?,?,?)", batch)
        connection.commit()
        connection.executescript(INDEXES)
        connection.execute("ANALYZE")
        connection.commit()
        connection.close()
        connection = None
        if overwrite:
            os.replace(temporary, destination)
        elif os.name == "nt":
            # Windows rename refuses an existing destination and works on volumes
            # where hard links are unavailable (including some synced folders).
            os.rename(temporary, destination)
        else:
            # Hard-link publication is atomic and fails if another process created
            # the destination during import. Both paths are on the same filesystem.
            os.link(temporary, destination)
            temporary.unlink()
        return summary
    except (zstd.ZstdError, EOFError, UnicodeError) as exc:
        raise DataError(
            f"Cannot decode the raw file; it may be corrupt, truncated or not UTF-8: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
