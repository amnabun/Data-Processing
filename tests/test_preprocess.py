import sqlite3
from pathlib import Path

import pytest
from conftest import pgn_game

from chess_analytics.models import DataError, classify_time_control
from chess_analytics.preprocess import preprocess, zstd
from chess_analytics.storage import DataStore


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        ("0+0", None),
        ("29+0", None),
        ("30+0", "bullet"),
        ("179+0", "bullet"),
        ("180+0", "blitz"),
        ("479+0", "blitz"),
        ("480+0", "rapid"),
        ("1499+0", "rapid"),
        ("1500+0", None),
        ("60+3", "blitz"),
        ("0+12", "rapid"),
        ("-", None),
    ],
)
def test_time_control_boundaries(clock, expected):
    assert classify_time_control(clock) == expected


@pytest.mark.parametrize("clock", ["", "?", "60", "-1+0", "1.5+2", "60+1+2", "bullet"])
def test_invalid_clock(clock):
    with pytest.raises(DataError):
        classify_time_control(clock)


def test_derived_fields_and_plain_input(make_dataset):
    path, summary, _ = make_dataset([{"WhiteElo": "1501"}], compressed=False)
    assert (summary.seen, summary.saved, summary.invalid) == (1, 1, 0)
    with DataStore(path) as store:
        row = store.connection.execute("SELECT * FROM games").fetchone()
        assert (row["white"], row["black"]) == ("Alice", "Bob")
        assert (row["white_pre"], row["black_pre"], row["white_post"], row["black_post"]) == (
            1501,
            1400,
            1511,
            1390,
        )
        assert row["game_rating"] == 1450.5
        assert row["opening"] == "Sicilian Defense"
        assert row["played_at"] == "2026-08-01T10:00:00Z"
        assert row["time_control"] == "blitz"


def test_invalid_records_are_reported_and_not_invented(make_dataset):
    path, summary, _ = make_dataset(
        [
            {},
            {"WhiteRatingDiff": None},
            {"WhiteElo": "?"},
            {"UTCDate": "2026.02.30"},
            {"Opening": ": variation"},
            {"TimeControl": "1500+0"},
            {"BlackRatingDiff": "-2000"},
            {"White": "Bob"},
        ]
    )
    assert (summary.seen, summary.saved, summary.excluded, summary.invalid) == (8, 1, 1, 6)
    assert "WhiteRatingDiff" in summary.describe()
    with DataStore(path) as store:
        assert store.game_count() == 1


def test_concatenated_zstd_frames(tmp_path):
    source = tmp_path / "frames.zst"
    source.write_bytes(
        zstd.compress(pgn_game().encode()) + zstd.compress(pgn_game(White="Carol").encode())
    )
    assert preprocess(source, tmp_path / "out.db").saved == 2


@pytest.mark.parametrize("data", [b"", b"not pgn", b'[White "Alice"]\n\n*\n'])
def test_unusable_input_leaves_no_output(tmp_path, data):
    source, target = tmp_path / "input.pgn", tmp_path / "output.db"
    source.write_bytes(data)
    with pytest.raises(DataError):
        preprocess(source, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".cw2-*"))


def test_truncated_compression_preserves_previous_output(tmp_path):
    source, target = tmp_path / "input.zst", tmp_path / "output.db"
    source.write_bytes(zstd.compress(pgn_game().encode())[:-3])
    target.write_bytes(b"previous dataset")
    with pytest.raises(DataError, match="truncated"):
        preprocess(source, target, overwrite=True)
    assert target.read_bytes() == b"previous dataset"
    assert not list(tmp_path.glob(".cw2-*"))


def test_corrupt_compression(tmp_path):
    source = tmp_path / "corrupt.zst"
    source.write_bytes(b"not compressed data")
    with pytest.raises(DataError):
        preprocess(source, tmp_path / "out.db")


def test_non_utf8_input(tmp_path):
    source = tmp_path / "invalid.pgn"
    source.write_bytes(b"\xff\xfe" + pgn_game().encode())
    with pytest.raises(DataError, match="UTF-8"):
        preprocess(source, tmp_path / "out.db")


def test_duplicate_headers_rejected(tmp_path):
    source = tmp_path / "duplicate.pgn"
    source.write_text('[White "Wrong"]\n' + pgn_game(), encoding="utf-8")
    with pytest.raises(DataError, match="Duplicate"):
        preprocess(source, tmp_path / "out.db")


def test_duplicate_headers_skip_only_the_affected_game(tmp_path):
    source = tmp_path / "mixed.pgn.zst"
    content = (
        pgn_game() + '[White "Duplicate"]\n' + pgn_game(White="Carol") + pgn_game(White="Diana")
    )
    source.write_bytes(zstd.compress(content.encode("utf-8")))

    output = tmp_path / "out.db"
    summary = preprocess(source, output)

    assert (summary.seen, summary.saved, summary.invalid) == (3, 2, 1)
    assert summary.reasons == {"Duplicate PGN header: White.": 1}
    with DataStore(output) as store:
        assert store.search_players() == ["Alice", "Bob", "Diana"]


def test_input_output_safety(make_dataset, tmp_path):
    path, _, source = make_dataset([{}])
    original = path.read_bytes()
    with pytest.raises(DataError, match="already exists"):
        preprocess(source, path)
    with pytest.raises(DataError, match="different"):
        preprocess(source, source, overwrite=True)
    with pytest.raises(DataError, match="does not exist"):
        preprocess(tmp_path / "missing.pgn", path)
    assert path.read_bytes() == original
    assert preprocess(source, path, overwrite=True).saved == 1


def test_read_only_store_and_search(make_dataset):
    path, _, _ = make_dataset(
        [{"White": "A_One", "Black": "B_One"}, {"White": "AXOne", "Black": "B_One"}]
    )
    with DataStore(path) as store:
        assert store.search_players("_") == ["A_One", "B_One"]
        assert store.search_players("_", black_only=True) == ["B_One"]
        assert store.search_players("A_One", black_only=True) == []
        assert store.search_players("a_one") == ["A_One"]
        with pytest.raises(sqlite3.OperationalError):
            store.connection.execute("DELETE FROM games")


def test_bad_database(tmp_path):
    path = tmp_path / "wrong.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other (id INTEGER)")
    with pytest.raises(DataError, match="supported"):
        DataStore(path)
    path.write_bytes(b"invalid database")
    with pytest.raises(sqlite3.DatabaseError):
        DataStore(path)


def test_paths_with_unicode_spaces_and_uri_characters(make_dataset):
    path, _, _ = make_dataset([{}])
    renamed = path.with_name("данные # 100%.sqlite")
    Path(path).rename(renamed)
    with DataStore(renamed) as store:
        assert store.game_count() == 1
