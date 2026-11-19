"""Argument validation and small adapters around the shared application functions."""

import argparse
import sqlite3
import sys
from pathlib import Path

from .models import DataError, TimeControl, parse_rating_bound


def rating_value(value: str) -> int:
    try:
        return parse_rating_bound(value)
    except DataError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyse Lichess game metadata. Run without arguments to open the GUI.",
        allow_abbrev=False,
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--raw-data", metavar="FILE", help="preprocess a .pgn.zst or .pgn file")
    actions.add_argument(
        "--popular-openings",
        action="store_true",
        help="plot openings used in at least 1%% of games",
    )
    actions.add_argument("--top10", action="store_true", help="list the ten most improved players")
    actions.add_argument(
        "--players-similar-to", metavar="NAME", help="list the ten closest players"
    )
    parser.add_argument("--outfile", metavar="FILE", help="processed SQLite output for --raw-data")
    parser.add_argument(
        "--overwrite", action="store_true", help="allow replacement of an import output"
    )
    parser.add_argument("--datafile", metavar="FILE", help="a previously processed SQLite dataset")
    parser.add_argument("--time-control", choices=[item.value for item in TimeControl])
    parser.add_argument("--min-rating", type=rating_value)
    parser.add_argument("--max-rating", type=rating_value)
    metric = parser.add_mutually_exclusive_group()
    metric.add_argument("--time-formats", action="store_true")
    metric.add_argument("--black-openings", action="store_true")
    parser.add_argument(
        "--save-chart", metavar="PNG", help="save the popularity chart instead of opening a window"
    )
    return parser


def validate_args(parser, args) -> None:
    if args.raw_data is not None:
        if not args.outfile:
            parser.error("--raw-data requires --outfile")
        if (
            any(
                value is not None
                for value in (
                    args.datafile,
                    args.time_control,
                    args.min_rating,
                    args.max_rating,
                    args.save_chart,
                )
            )
            or args.time_formats
            or args.black_openings
        ):
            parser.error("analysis options cannot be used with --raw-data")
        return
    if not args.datafile:
        parser.error("analysis requires --datafile")
    if args.outfile is not None or args.overwrite:
        parser.error("--outfile and --overwrite are only valid with --raw-data")
    if args.top10 and args.time_control is None:
        parser.error("--top10 requires --time-control")
    if args.players_similar_to is not None:
        if not (args.time_formats or args.black_openings):
            parser.error("choose --time-formats or --black-openings for player similarity")
        if args.time_control is not None:
            parser.error("--time-control is not a filter for player similarity")
    elif args.time_formats or args.black_openings:
        parser.error("similarity metrics require --players-similar-to")
    if not args.popular_openings and any(
        value is not None for value in (args.min_rating, args.max_rating, args.save_chart)
    ):
        parser.error("rating bounds and --save-chart require --popular-openings")
    if (
        args.min_rating is not None
        and args.max_rating is not None
        and args.min_rating > args.max_rating
    ):
        parser.error("--min-rating cannot exceed --max-rating")


def print_table(headers, rows) -> None:
    if not rows:
        print("No matching players.")
        return
    strings = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(header), *(len(row[i]) for row in strings)) for i, header in enumerate(headers)
    ]
    for row in [headers, ["-" * width for width in widths], *strings]:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))


def run_analysis(args) -> None:
    from .analysis import most_improved, popular_openings
    from .similarity import METRICS, similar_players
    from .storage import DataStore

    with DataStore(args.datafile) as store:
        if args.popular_openings:
            from .charts import show_openings

            if args.save_chart:
                chart = Path(args.save_chart).expanduser().resolve()
                if chart.exists():
                    raise DataError("Chart output already exists. Choose a new filename.")
                if chart.suffix.lower() != ".png":
                    raise DataError("--save-chart requires a .png filename.")
            total, rows = popular_openings(
                store, args.time_control, args.min_rating, args.max_rating
            )
            print(f"{total:,} matching games; {len(rows)} openings meet the 1% threshold.")
            subtitle = f"{args.time_control or 'All time controls'} | Rating: {args.min_rating if args.min_rating is not None else 'unbounded'} to {args.max_rating if args.max_rating is not None else 'unbounded'}"
            show_openings(rows, total, subtitle, args.save_chart)
        elif args.top10:
            rows = most_improved(store, args.time_control)
            print_table(
                ["Player", "Initial", "Final", "Change", "Games"],
                [
                    (r.player, r.initial_rating, r.final_rating, f"{r.improvement:+d}", r.games)
                    for r in rows
                ],
            )
        else:
            metric = METRICS["time-formats" if args.time_formats else "black-openings"]
            rows = similar_players(store, args.players_similar_to, metric)
            print(f"Players closest to {args.players_similar_to} (smaller distance is closer):")
            print_table(
                ["Player", "Distance", "Preferences"],
                [(r.player, f"{r.distance:.4f}", r.details) for r in rows],
            )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if not argv:
            from .gui import launch

            launch()
            return 0
        parser = build_parser()
        args = parser.parse_args(argv)
        validate_args(parser, args)
        if args.raw_data is not None:
            from .preprocess import preprocess

            summary = preprocess(args.raw_data, args.outfile, overwrite=args.overwrite)
            print(summary.describe())
        else:
            run_analysis(args)
        return 0
    except ImportError as exc:
        print(
            f"Error: missing dependency ({exc}). Run: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
    except (DataError, OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    return 1
