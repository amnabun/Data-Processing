import subprocess
import sys
from pathlib import Path

import pytest

from chess_analytics.cli import main


@pytest.mark.parametrize(
    "args",
    [
        ["--unknown"],
        ["--top10"],
        ["--top10", "--datafile=x"],
        ["--top10", "--datafile=x", "--time-control=classical"],
        ["--raw-data=x"],
        ["--raw-data=x", "--outfile=y", "--datafile=z"],
        ["--popular-openings", "--datafile=x", "--min-rating=abc"],
        ["--popular-openings", "--datafile=x", "--min-rating=-1"],
        ["--popular-openings", "--datafile=x", "--min-rating=2000", "--max-rating=1000"],
        ["--players-similar-to=Alice", "--datafile=x"],
        ["--players-similar-to=Alice", "--datafile=x", "--time-formats", "--black-openings"],
        ["--top10", "--datafile=x", "--time-control=blitz", "--min-rating=0"],
        ["--top10", "--datafile=x", "--time-control=blitz", "--time-formats"],
        ["--popular-openings", "--datafile=x", "--overwrite"],
        ["--popular-openings", "--top10", "--datafile=x"],
    ],
)
def test_bad_argument_combinations(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_end_to_end(make_dataset, tmp_path):
    path, _, source = make_dataset([{}, {"White": "Carol"}])
    entry = Path(__file__).resolve().parents[1] / "cw2.py"
    commands = [
        [f"--raw-data={source}", f"--outfile={tmp_path / 'fresh.db'}"],
        [f"--datafile={path}", "--top10", "--time-control=blitz"],
        [f"--datafile={path}", "--players-similar-to=Alice", "--time-formats"],
        [f"--datafile={path}", "--players-similar-to=Bob", "--black-openings"],
        [f"--datafile={path}", "--popular-openings", f"--save-chart={tmp_path / 'chart.png'}"],
    ]
    for args in commands:
        result = subprocess.run(
            [sys.executable, str(entry), *args], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr
    assert (tmp_path / "chart.png").read_bytes().startswith(b"\x89PNG")


def test_errors_do_not_show_traceback(tmp_path, capsys):
    path = tmp_path / "broken.db"
    path.write_text("not a database", encoding="utf-8")
    assert main([f"--datafile={path}", "--top10", "--time-control=blitz"]) == 1
    error = capsys.readouterr().err
    assert "Error:" in error and "Traceback" not in error


def test_chart_cannot_overwrite_data(make_dataset, capsys):
    path, _, _ = make_dataset([{}])
    original = path.read_bytes()
    assert main([f"--datafile={path}", "--popular-openings", f"--save-chart={path}"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert path.read_bytes() == original


def test_no_arguments_launches_gui(monkeypatch):
    import chess_analytics.gui

    launched = []
    monkeypatch.setattr(chess_analytics.gui, "launch", lambda: launched.append(True))
    assert main([]) == 0
    assert launched == [True]
