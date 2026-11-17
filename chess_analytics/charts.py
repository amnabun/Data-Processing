"""A shared chart renderer for the command line and embedded GUI canvas."""

from textwrap import fill

from .models import OpeningPopularity


def draw_openings(figure, rows: list[OpeningPopularity], total: int, subtitle: str = "") -> None:
    figure.clear()
    axis = figure.add_subplot(111)
    axis.set_title(f"Opening popularity - {total:,} matching games\n{subtitle}", pad=16)
    axis.set_xlabel("Opening")
    axis.set_ylabel("Games (%)")
    if rows:
        positions = list(range(len(rows)))
        axis.bar(positions, [row.percentage for row in rows], color="#287c8e", width=0.72)
        axis.set_xticks(positions, [fill(row.opening, 24) for row in rows], rotation=55, ha="right")
        axis.set_ylim(0, min(105, max(row.percentage for row in rows) * 1.15 + 1))
        axis.yaxis.grid(True, alpha=0.2)
        axis.set_axisbelow(True)
    else:
        message = (
            "No games match these filters."
            if total == 0
            else "No opening reaches the 1% threshold."
        )
        axis.text(0.5, 0.5, message, ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
    # Recalculate margins after GUI resizes, including space for long tick labels.
    figure.set_layout_engine("tight", pad=1.4)


def show_openings(rows, total: int, subtitle: str, output: str | None = None) -> None:
    import matplotlib

    if output:
        matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure = plt.figure(figsize=(max(10, len(rows) * 0.45), 7))
    try:
        draw_openings(figure, rows, total, subtitle)
        if output:
            figure.savefig(output, dpi=160, bbox_inches="tight")
        else:
            plt.show()
    finally:
        plt.close(figure)
