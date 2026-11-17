"""Tkinter interface; worker threads never read or update Tk widgets."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .analysis import most_improved, popular_openings
from .charts import draw_openings
from .models import DataError, TimeControl
from .preprocess import preprocess
from .similarity import METRICS, similar_players
from .storage import DataStore


class ChessApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chess Data Analytics")
        self.root.geometry("1120x800")
        self.root.minsize(900, 680)
        self.events = queue.Queue()
        self.busy = False
        self.controls = []
        self.dataset = tk.StringVar()
        self.status = tk.StringVar(
            value="Start by importing raw games or opening a processed dataset."
        )
        self.chart_canvas = None
        self.chart_figure = None
        self.chart_toolbar = None
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=lambda: self._guard(command))
        self.controls.append((button, "normal"))
        return button

    def _combo(self, parent, variable, values, width=20):
        combo = ttk.Combobox(
            parent, textvariable=variable, values=values, state="readonly", width=width
        )
        self.controls.append((combo, "readonly"))
        return combo

    def _entry(self, parent, variable, **kwargs):
        entry = ttk.Entry(parent, textvariable=variable, **kwargs)
        self.controls.append((entry, "normal"))
        return entry

    def _build(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Chess Data Analytics", font=("TkDefaultFont", 21, "bold")).pack(
            anchor="w"
        )
        ttk.Label(outer, text="Explore openings, rating improvement and player preferences.").pack(
            anchor="w", pady=(4, 14)
        )
        file_row = ttk.Frame(outer)
        file_row.pack(fill="x", pady=(0, 12))
        self._button(file_row, "Open processed dataset...", self.open_dataset).pack(side="left")
        ttk.Entry(file_row, textvariable=self.dataset, state="readonly").pack(
            side="left", padx=(10, 0), fill="x", expand=True
        )

        # Reserve the footer before the expanding notebook so a large chart's
        # requested size cannot push progress and error messages off the window.
        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(12, 5))
        ttk.Label(footer, textvariable=self.status, wraplength=1000).pack(anchor="w")
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.tabs = {}
        for name in ("Import games", "Opening popularity", "Most improved", "Similar players"):
            frame = ttk.Frame(notebook, padding=16)
            notebook.add(frame, text=name)
            self.tabs[name] = frame
        self._build_import(self.tabs["Import games"])
        self._build_popularity(self.tabs["Opening popularity"])
        self._build_improvement(self.tabs["Most improved"])
        self._build_similarity(self.tabs["Similar players"])

    def _build_import(self, frame):
        ttk.Label(frame, text="Prepare a dataset", font=("TkDefaultFont", 15, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="Select a Lichess .pgn.zst (or uncompressed .pgn) file and an output location.\n"
            "Only bullet, blitz and rapid games with complete metadata are kept.",
        ).pack(anchor="w", pady=12)
        self.raw_path = tk.StringVar()
        self.output_path = tk.StringVar()
        for label, variable, command in (
            ("Raw games", self.raw_path, self.choose_raw),
            ("Save dataset", self.output_path, self.choose_output),
        ):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=6)
            ttk.Label(row, text=label, width=15).pack(side="left")
            ttk.Entry(row, textvariable=variable, state="readonly").pack(
                side="left", fill="x", expand=True
            )
            self._button(row, "Browse...", command).pack(side="left", padx=(8, 0))
        self._button(frame, "Preprocess games", self.import_games).pack(anchor="w", pady=14)
        self.import_log = tk.Text(frame, height=12, wrap="word", state="disabled", relief="flat")
        self.import_log.pack(fill="both", expand=True)

    def _build_popularity(self, frame):
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.pop_control = tk.StringVar(value="All")
        self.min_rating = tk.StringVar()
        self.max_rating = tk.StringVar()
        ttk.Label(controls, text="Time control").pack(side="left")
        self._combo(controls, self.pop_control, ["All", *[t.value for t in TimeControl]], 10).pack(
            side="left", padx=8
        )
        validate = (
            self.root.register(
                lambda value: (
                    value == "" or (value.isascii() and value.isdecimal() and len(value) <= 10)
                )
            ),
            "%P",
        )
        for label, variable in (("Min rating", self.min_rating), ("Max rating", self.max_rating)):
            ttk.Label(controls, text=label).pack(side="left", padx=(8, 4))
            self._entry(
                controls, variable, width=10, validate="key", validatecommand=validate
            ).pack(side="left")
        self._button(controls, "Show chart", self.plot_popularity).pack(side="left", padx=12)
        ttk.Label(
            frame,
            text="Leave a rating bound blank for no limit. Bounds are inclusive; only openings at or above 1% are shown.",
        ).pack(anchor="w", pady=10)
        self.chart_frame = ttk.Frame(frame)
        self.chart_frame.pack(fill="both", expand=True)

    def _build_improvement(self, frame):
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 12))
        self.improve_control = tk.StringVar(value="blitz")
        ttk.Label(controls, text="Time control").pack(side="left", padx=(0, 8))
        self._combo(controls, self.improve_control, [t.value for t in TimeControl]).pack(
            side="left"
        )
        self._button(controls, "Find top 10", self.find_improved).pack(side="left", padx=12)
        ttk.Label(
            frame,
            text="Change = last post-game rating minus first pre-game rating, in chronological order.",
        ).pack(anchor="w", pady=(0, 12))
        self.improvement_table = self._table(
            frame, ("Player", "Initial rating", "Final rating", "Change", "Games")
        )

    def _build_similarity(self, frame):
        search_row = ttk.Frame(frame)
        search_row.pack(fill="x", pady=(0, 10))
        self.player_query = tk.StringVar()
        ttk.Label(search_row, text="Search players").pack(side="left", padx=(0, 8))
        entry = self._entry(search_row, self.player_query, width=30)
        entry.pack(side="left")
        entry.bind(
            "<Return>", lambda _event: self._guard(self.search_players) if not self.busy else None
        )
        self._button(search_row, "Find names", self.search_players).pack(side="left", padx=8)
        ttk.Label(
            frame,
            text="Select an exact name below. Up to 200 matches are shown; narrow the search if needed.",
        ).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=12)
        self.player = tk.StringVar()
        self.player_combo = self._combo(row, self.player, [], 30)
        self.player_combo.pack(side="left")
        self.metric_name = tk.StringVar(value="Time formats")
        self._combo(row, self.metric_name, ["Time formats", "Black openings"], 18).pack(
            side="left", padx=10
        )
        self._button(row, "Find similar players", self.find_similar).pack(side="left")
        ttk.Label(
            frame,
            text="Smaller distance means greater similarity. Tied favourite openings are resolved alphabetically.",
        ).pack(anchor="w", pady=(0, 12))
        self.similarity_table = self._table(frame, ("Player", "Distance", "Preferences"))
        self.similarity_table.column("Preferences", width=510)

    @staticmethod
    def _table(parent, columns):
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill="both", expand=True)
        table = ttk.Treeview(wrapper, columns=columns, show="headings", height=12)
        for column in columns:
            table.heading(column, text=column)
            table.column(column, width=140, minwidth=80)
        vertical = ttk.Scrollbar(wrapper, orient="vertical", command=table.yview)
        horizontal = ttk.Scrollbar(wrapper, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        return table

    @staticmethod
    def _fill_table(table, rows):
        table.delete(*table.get_children())
        for row in rows:
            table.insert("", "end", values=row)

    def _guard(self, command):
        try:
            command()
        except Exception as exc:
            self._error(exc)

    def _error(self, error):
        self.status.set("The task could not be completed. You can correct the input and try again.")
        messagebox.showerror(
            "Unable to complete task", str(error) or type(error).__name__, parent=self.root
        )

    def _start(self, label, work, done):
        if self.busy:
            return
        self.busy = True
        for widget, _state in self.controls:
            widget.configure(state="disabled")
        self.status.set(label)
        self.progress.start(12)

        def worker():
            try:
                result = work()
            except Exception as exc:
                self.events.put(("error", exc, None))
            else:
                self.events.put(("done", result, done))

        threading.Thread(target=worker, daemon=False).start()

    def _poll(self):
        try:
            while True:
                kind, value, done = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(f"Preprocessing: {value:,} games read...")
                    continue
                self.busy = False
                self.progress.stop()
                for widget, state in self.controls:
                    widget.configure(state=state)
                if kind == "error":
                    self._error(value)
                else:
                    self._guard(lambda: done(value))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _with_data(self, function):
        path = self.dataset.get()
        if not path:
            raise DataError("Open a processed dataset first.")

        def work():
            with DataStore(path) as store:
                return function(store)

        return work

    def open_dataset(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open processed dataset",
            filetypes=[("SQLite dataset", "*.sqlite *.db"), ("All files", "*")],
        )
        if path:

            def work():
                with DataStore(path) as store:
                    return store.game_count(), store.search_players()

            self._start(
                "Checking dataset...", work, lambda result: self._dataset_loaded(path, result)
            )

    def _dataset_loaded(self, path, result):
        count, players = result
        self.dataset.set(path)
        self.player_query.set("")
        self._set_players(players)
        self._fill_table(self.improvement_table, [])
        self._fill_table(self.similarity_table, [])
        self._clear_chart()
        self.status.set(f"Loaded {count:,} games from {Path(path).name}.")

    def choose_raw(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Select raw games",
            filetypes=[("PGN files", "*.zst *.pgn"), ("All files", "*")],
        )
        if path:
            self.raw_path.set(path)

    def choose_output(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save processed dataset",
            defaultextension=".sqlite",
            filetypes=[("SQLite dataset", "*.sqlite")],
        )
        if path:
            self.output_path.set(path)

    def import_games(self):
        source, output = self.raw_path.get(), self.output_path.get()
        if not source or not output:
            raise DataError("Select both a raw games file and an output file.")
        overwrite = Path(output).exists()
        if overwrite and not messagebox.askyesno(
            "Replace dataset?",
            "Replace the selected output after a successful import?",
            parent=self.root,
        ):
            return

        def work():
            summary = preprocess(
                source,
                output,
                overwrite=overwrite,
                progress=lambda count: self.events.put(("progress", count, None)),
            )
            with DataStore(output) as store:
                return summary, store.search_players()

        def done(result):
            summary, players = result
            self._dataset_loaded(output, (summary.saved, players))
            self.import_log.configure(state="normal")
            self.import_log.delete("1.0", "end")
            self.import_log.insert("1.0", summary.describe())
            self.import_log.configure(state="disabled")
            self.status.set("Import complete. The new dataset is ready for analysis.")

        self._start("Preprocessing games...", work, done)

    def plot_popularity(self):
        category = None if self.pop_control.get() == "All" else self.pop_control.get()
        lower = int(self.min_rating.get()) if self.min_rating.get() else None
        upper = int(self.max_rating.get()) if self.max_rating.get() else None
        subtitle = f"{category or 'All time controls'} | Rating: {lower if lower is not None else 'unbounded'} to {upper if upper is not None else 'unbounded'}"

        def done(result):
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            from matplotlib.figure import Figure

            total, rows = result
            self._clear_chart()
            self.chart_figure = Figure(figsize=(11, 6), dpi=100)
            draw_openings(self.chart_figure, rows, total, subtitle)
            self.chart_canvas = FigureCanvasTkAgg(self.chart_figure, master=self.chart_frame)
            self.chart_toolbar = NavigationToolbar2Tk(
                self.chart_canvas, self.chart_frame, pack_toolbar=False
            )
            self.chart_toolbar.pack(side="bottom", fill="x")
            self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
            self.chart_canvas.draw()
            self.status.set(f"{total:,} matching games; {len(rows)} openings at or above 1%.")

        self._start(
            "Calculating opening popularity...",
            self._with_data(lambda store: popular_openings(store, category, lower, upper)),
            done,
        )

    def _clear_chart(self):
        # Clearing a Figure updates its toolbar, so do this while Tk widgets exist.
        if self.chart_figure:
            self.chart_figure.clear()
            self.chart_figure = None
        if self.chart_canvas:
            self.chart_canvas.get_tk_widget().destroy()
            self.chart_canvas = None
        if self.chart_toolbar:
            self.chart_toolbar.destroy()
            self.chart_toolbar = None

    def find_improved(self):
        category = self.improve_control.get()

        def done(rows):
            self._fill_table(
                self.improvement_table,
                [
                    (r.player, r.initial_rating, r.final_rating, f"{r.improvement:+d}", r.games)
                    for r in rows
                ],
            )
            self.status.set(f"Showing {len(rows)} players for {category}.")

        self._start(
            "Finding rating improvement...",
            self._with_data(lambda store: most_improved(store, category)),
            done,
        )

    def _set_players(self, players):
        self.player_combo.configure(values=players)
        self.player.set(players[0] if players else "")

    def search_players(self):
        query = self.player_query.get().strip()

        def done(players):
            self._set_players(players)
            self.status.set(
                f"Found {len(players)} names (maximum 200). Select a player to compare."
            )

        self._start(
            "Searching player names...",
            self._with_data(lambda store: store.search_players(query)),
            done,
        )

    def find_similar(self):
        player = self.player.get()
        if not player:
            raise DataError("Find and select a player from this dataset first.")
        metric = METRICS[
            "time-formats" if self.metric_name.get() == "Time formats" else "black-openings"
        ]

        def done(rows):
            self._fill_table(
                self.similarity_table, [(r.player, f"{r.distance:.4f}", r.details) for r in rows]
            )
            self.status.set(f"Found {len(rows)} similar players for {player}.")

        self._start(
            "Comparing players...",
            self._with_data(lambda store: similar_players(store, player, metric)),
            done,
        )

    def close(self):
        if self.busy:
            messagebox.showinfo(
                "Task running",
                "Please wait for the current task to finish before closing.",
                parent=self.root,
            )
            return
        self._clear_chart()
        self.root.destroy()


def launch():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise DataError(
            "The GUI needs a desktop display and Tk support. You can still use the command-line options."
        ) from exc
    ChessApp(root)
    root.mainloop()
