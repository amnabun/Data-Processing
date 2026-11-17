"""Small, deliberately unsorted PGNs with results that can be checked by hand."""

import pytest

from chess_analytics.preprocess import preprocess, zstd


def pgn_game(**overrides):
    headers = {
        "Event": "Rated Blitz game",
        "Site": "https://lichess.org/example",
        "Date": "2026.08.01",
        "Round": "-",
        "White": "Alice",
        "Black": "Bob",
        "Result": "1-0",
        "UTCDate": "2026.08.01",
        "UTCTime": "10:00:00",
        "WhiteElo": "1500",
        "BlackElo": "1400",
        "WhiteRatingDiff": "+10",
        "BlackRatingDiff": "-10",
        "Opening": "Sicilian Defense: Dragon Variation",
        "TimeControl": "180+0",
    }
    headers.update(overrides)
    tags = "\n".join(f'[{key} "{value}"]' for key, value in headers.items() if value is not None)
    return tags + "\n\n1. e4 c5 1-0\n\n"


@pytest.fixture
def make_dataset(tmp_path):
    sequence = 0

    def make(games, *, compressed=True):
        nonlocal sequence
        sequence += 1
        source = tmp_path / f"games-{sequence}.pgn{'.zst' if compressed else ''}"
        content = "".join(pgn_game(**game) for game in games).encode("utf-8")
        source.write_bytes(zstd.compress(content) if compressed else content)
        output = tmp_path / f"games-{sequence}.sqlite"
        summary = preprocess(source, output)
        return output, summary, source

    return make
