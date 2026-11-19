import time
import tkinter as tk

import pytest

from chess_analytics.gui import ChessApp

pytestmark = pytest.mark.gui


def finish(root, app):
    deadline = time.monotonic() + 20
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert not app.busy, "Background task did not finish"


def test_multiple_tasks_and_error_recovery(make_dataset, monkeypatch, tmp_path):
    from chess_analytics import gui

    path, _, source = make_dataset([{}, {"White": "Carol"}, {"Black": "Diana"}])
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("A desktop display is required")
    root.withdraw()
    app = ChessApp(root)
    try:
        app._guard(app.find_improved)
        assert errors and "dataset" in errors[-1][1]
        monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kwargs: str(path))
        app.open_dataset()
        finish(root, app)
        assert app.dataset.get() == str(path)
        assert str(app.player_combo.cget("state")) == "readonly"
        assert set(app.player_combo.cget("values")) == {"Alice", "Bob", "Carol", "Diana"}
        app.find_improved()
        finish(root, app)
        assert len(app.improvement_table.get_children()) == 4
        app.player.set("Alice")
        app.metric_combo.current(1)
        app.metric_combo.event_generate("<<ComboboxSelected>>")
        finish(root, app)
        assert set(app.player_combo.cget("values")) == {"Bob", "Diana"}
        assert not app.player.get()
        app.player_query.set("alice")
        app.search_players()
        finish(root, app)
        assert not app.player_combo.cget("values")
        assert "No matching players" in app.status.get()
        app.player_query.set("")
        app.search_players()
        finish(root, app)
        app.player.set("Bob")
        app.find_similar()
        finish(root, app)
        assert len(app.similarity_table.get_children()) == 1
        app.min_rating.set("2000")
        app.max_rating.set("1000")
        app.plot_popularity()
        finish(root, app)
        assert "Minimum" in errors[-1][1]
        app.min_rating.set("-1")
        app.max_rating.set("")
        app.plot_popularity()
        finish(root, app)
        assert app.chart_canvas is not None
        app.plot_popularity()
        finish(root, app)
        assert app.chart_canvas is not None
        app.player_query.set("car")
        app.metric_combo.current(0)
        app.metric_combo.event_generate("<<ComboboxSelected>>")
        finish(root, app)
        assert tuple(app.player_combo.cget("values")) == ("Carol",)
        app.search_players()
        finish(root, app)
        assert app.player.get() == "Carol"
        app.raw_path.set(str(source))
        app.output_path.set(str(tmp_path / "gui-import.sqlite"))
        app.import_games()
        finish(root, app)
        assert "saved 3" in app.import_log.get("1.0", "end")
        assert app.dataset.get().endswith("gui-import.sqlite")
        assert app.chart_canvas is None
        assert len(errors) == 2
    finally:
        app.close()
