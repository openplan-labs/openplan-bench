"""Frontier-branded figures for the leaderboard.

MIGRATION NOTE
--------------
Everything below is plotting, and plotting is not this project's job.
``planviz`` (the org's shared Frontier plotting library) shipped 1.0.0, so this
module should now become a thin shim over it: the palette dictionaries, the
``_style`` context manager and the axis helpers all have direct equivalents
there. Keeping every matplotlib call inside this one module is what makes that
a delete-and-import rather than a refactor. Do not add plotting code anywhere
else in the package.

Brand rules being followed (openplan-labs/branding, brand/figures.md):

* The categorical cycle is the **agent ramp**, not the semantic trio.
  ``--color-path`` means "the returned solution" and ``--color-frontier`` means
  "the open list"; using them for arbitrary planner series would break a legend
  the reader has already learned.
* ``--color-path`` is the only warm colour in the system and is spent on the
  one thing a figure is arguing. Here that is the timeout cap and the
  best-performing series.
* Shape carries the meaning: solved cells are filled circles on a solid line,
  timeouts are hollow triangles. The figures survive greyscale printing.
* Every figure is rendered light and dark, because the dashboard follows the
  reader's theme.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

# --- brand tokens (openplan-labs/branding · tokens/tokens.css) --------------
LIGHT = {
    "bg": "#f2f4f6",
    "raised": "#ffffff",
    "line": "#d9dfe4",
    "heading": "#14181c",
    "body": "#3c464e",
    "muted": "#5e6a73",
    "faint": "#7b8790",
    "path": "#c2472c",
    "frontier": "#127a78",
    "expanded": "#6d8298",
}

DARK = {
    "bg": "#12171a",
    "raised": "#1a2126",
    "line": "#2a343a",
    "heading": "#e8edf0",
    "body": "#aab6bd",
    "muted": "#7d8b93",
    "faint": "#59666e",
    "path": "#e87a5c",
    "frontier": "#3fb3ad",
    "expanded": "#8ba2b7",
}

#: The categorical ramp. Deliberately cooler and flatter than ``path``.
AGENT_RAMP = (
    "#3d6d8f",
    "#4f8a7b",
    "#7a6f9c",
    "#8a6d5a",
    "#5b7f9e",
    "#6b9a8b",
    "#8f7fae",
    "#9c7f6a",
)

#: Marker cycle, paired with the ramp. The brand rule is that no figure may
#: distinguish its series by hue alone — the ramp is deliberately flat and
#: cool, so with six or more planner configurations two colours will always sit
#: close together. Shape is what survives greyscale printing and a colour-blind
#: reader.
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")

_FONTS = ["Libre Franklin", "Helvetica Neue", "Helvetica", "DejaVu Sans"]


@contextmanager
def _style(dark: bool):
    """Apply the Frontier matplotlib style for one figure."""
    tokens = DARK if dark else LIGHT
    settings = {
        "figure.facecolor": tokens["bg"],
        "figure.edgecolor": tokens["bg"],
        "savefig.facecolor": tokens["bg"],
        "savefig.edgecolor": tokens["bg"],
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "axes.facecolor": tokens["raised"],
        "axes.edgecolor": tokens["line"],
        "axes.linewidth": 1.0,
        "axes.labelcolor": tokens["body"],
        "axes.titlecolor": tokens["heading"],
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.titlesize": 12,
        "axes.titleweight": "semibold",
        "axes.labelsize": 10,
        "axes.prop_cycle": plt.cycler("color", list(AGENT_RAMP)),
        "grid.color": tokens["line"],
        "grid.linewidth": 0.6,
        "grid.alpha": 0.9,
        "xtick.color": tokens["muted"],
        "ytick.color": tokens["muted"],
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "text.color": tokens["body"],
        "font.family": "sans-serif",
        "font.sans-serif": _FONTS,
        "font.size": 10,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "lines.markersize": 5,
    }
    with plt.rc_context(settings):
        yield tokens


def _empty(ax, tokens, message: str) -> None:
    """State plainly that there is no data, rather than drawing empty axes."""
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        color=tokens["faint"],
        fontsize=10,
        transform=ax.transAxes,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


def _save(fig, out_dir: Path, stem: str, dark: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (f"{stem}-dark.png" if dark else f"{stem}.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def _series_colors(labels) -> dict[str, str]:
    return {label: AGENT_RAMP[i % len(AGENT_RAMP)] for i, label in enumerate(labels)}


def _series_markers(labels) -> dict[str, str]:
    return {label: MARKERS[i % len(MARKERS)] for i, label in enumerate(labels)}


# ---------------------------------------------------------------------------
def cactus_plot(
    series: dict[str, list[float]],
    out_dir: Path,
    dark: bool,
    budget_s: float | None = None,
) -> Path:
    """Instances solved against per-instance time budget.

    The competition figure. A configuration's curve ending early means it stops
    solving instances at all, not that it got slow — which is precisely the
    distinction a mean runtime hides.

    ``budget_s`` draws the cap the suite actually ran under. Without it the
    figure invites the reader to extrapolate every curve rightwards, which is
    exactly the thing the budget forbids: past the dashed line nothing was
    measured.
    """
    with _style(dark) as tokens:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        if not series:
            _empty(ax, tokens, "No instance was solved by any configuration.")
        else:
            colors = _series_colors(series)
            markers = _series_markers(series)
            # The configuration solving the most instances is the argument the
            # figure is making, so it gets the one warm colour.
            best = max(series, key=lambda k: (len(series[k]), -sum(series[k])))
            for label, times in series.items():
                counts = range(1, len(times) + 1)
                is_best = label == best
                ax.step(
                    counts,
                    times,
                    where="post",
                    label=label,
                    color=tokens["path"] if is_best else colors[label],
                    linewidth=2.4 if is_best else 1.8,
                    marker=markers[label],
                    markersize=5 if is_best else 4,
                    zorder=3 if is_best else 2,
                )
            if budget_s and budget_s > 0:
                ax.axhline(
                    budget_s,
                    color=tokens["path"],
                    linestyle="--",
                    linewidth=1.2,
                    zorder=1,
                    label=f"budget ({budget_s:g} s)",
                )
            ax.set_yscale("log")
            ax.set_xlabel("instances solved (all seeds valid)")
            ax.set_ylabel("per-instance time budget (s)")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.legend(loc="upper left")
        ax.set_title("Coverage against time budget")
        return _save(fig, out_dir, "cactus", dark)


def scaling_plot(
    curves: dict[str, tuple[list[float], list[float], list[float], list[float]]],
    timeouts: dict[str, list[tuple[float, float]]],
    out_dir: Path,
    dark: bool,
    xlabel: str = "agents",
    stem: str = "scaling",
) -> Path:
    """Median runtime against instance size, with the observed min–max band."""
    with _style(dark) as tokens:
        fig, ax = plt.subplots(figsize=(7.2, 4.4))
        if not curves and not timeouts:
            _empty(ax, tokens, "No solved run to plot.")
        else:
            names = sorted(set(curves) | set(timeouts))
            colors = _series_colors(names)
            markers = _series_markers(names)
            for label, (xs, medians, lows, highs) in curves.items():
                ax.plot(
                    xs,
                    medians,
                    label=label,
                    color=colors[label],
                    marker=markers[label],
                    zorder=3,
                )
                ax.fill_between(
                    xs, lows, highs, color=colors[label], alpha=0.15, linewidth=0
                )
            for _label, points in timeouts.items():
                if not points:
                    continue
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ax.scatter(
                    xs,
                    ys,
                    facecolors="none",
                    edgecolors=tokens["path"],
                    marker="^",
                    s=46,
                    linewidths=1.4,
                    zorder=4,
                    label=None,
                )
            ax.set_yscale("log")
            ax.set_xlabel(xlabel)
            ax.set_ylabel("median wall time (s), band = min–max over seeds")
            if len({x for xs, *_ in curves.values() for x in xs}) < 2:
                # One x position is not a curve. Say so on the figure rather
                # than letting five lone markers read as a trend.
                ax.set_xlabel(f"{xlabel} (held constant — single point, no trend)")
            handles, labels = ax.get_legend_handles_labels()
            if any(points for points in timeouts.values()):
                handles.append(
                    plt.Line2D(
                        [],
                        [],
                        marker="^",
                        linestyle="none",
                        markerfacecolor="none",
                        markeredgecolor=tokens["path"],
                        markeredgewidth=1.4,
                        markersize=8,
                    )
                )
                labels.append("did not finish (at budget)")
            ax.legend(handles, labels, loc="upper left")
        ax.set_title(f"Runtime against {xlabel}")
        return _save(fig, out_dir, stem, dark)


def coverage_bars(summaries, out_dir: Path, dark: bool) -> Path:
    """Coverage per configuration, with the unsolved remainder broken out."""
    with _style(dark) as tokens:
        rows = [s for s in summaries if s.instances]
        fig, ax = plt.subplots(figsize=(7.2, max(3.0, 0.42 * len(rows) + 1.6)))
        if not rows:
            _empty(ax, tokens, "No configuration was measured.")
            ax.set_title("Coverage")
            return _save(fig, out_dir, "coverage", dark)

        rows = sorted(rows, key=lambda s: s.coverage)
        labels = [f"{s.adapter}:{s.label}" for s in rows]
        positions = range(len(rows))
        solved = [s.solved for s in rows]
        timeouts = [s.timeouts for s in rows]
        others = [s.instances - s.solved - s.timeouts for s in rows]

        ax.barh(positions, solved, color=tokens["frontier"], label="solved (valid)")
        ax.barh(
            positions,
            timeouts,
            left=solved,
            color=tokens["path"],
            label="timed out",
        )
        ax.barh(
            positions,
            others,
            left=[a + b for a, b in zip(solved, timeouts, strict=True)],
            color=tokens["expanded"],
            alpha=0.55,
            label="unsolved / error",
        )
        ax.set_yticks(list(positions))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel("instances")
        # Instance counts are integers; 2.5 instances is not a thing.
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        # Above the axes rather than inside: the bars are sorted ascending, so
        # every inside corner is occupied by some bar at some data size.
        ax.legend(
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            ncol=3,
            borderaxespad=0.0,
        )
        ax.set_title("Coverage per configuration", pad=34)
        return _save(fig, out_dir, "coverage", dark)


def outcome_bars(counts: dict[str, int], out_dir: Path, dark: bool) -> Path:
    """Every outcome in the suite, including the ones that never ran.

    This chart exists so nobody has to take "the benchmark passed" on trust.
    """
    order = [
        "solved",
        "unsolved",
        "timeout",
        "memory",
        "error",
        "skipped",
        "not-installed",
    ]
    with _style(dark) as tokens:
        fig, ax = plt.subplots(figsize=(7.2, 3.4))
        present = [(k, counts[k]) for k in order if counts.get(k)]
        present += [(k, v) for k, v in counts.items() if k not in order and v]
        if not present:
            _empty(ax, tokens, "No run was recorded.")
        else:
            palette = {
                "solved": tokens["frontier"],
                "unsolved": tokens["expanded"],
                "timeout": tokens["path"],
                "memory": tokens["path"],
                "error": tokens["path"],
                "skipped": tokens["faint"],
                "not-installed": tokens["faint"],
            }
            names = [p[0] for p in present]
            values = [p[1] for p in present]
            bars = ax.bar(
                names, values, color=[palette.get(n, AGENT_RAMP[0]) for n in names]
            )
            for bar, value in zip(bars, values, strict=True):
                ax.annotate(
                    str(value),
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    color=tokens["muted"],
                )
            ax.set_ylabel("runs")
            ax.margins(y=0.16)
        ax.set_title("Every run, by outcome")
        return _save(fig, out_dir, "outcomes", dark)


def render_suite(rows, out_dir: str | Path) -> list[Path]:
    """Render the whole figure set for one suite, light and dark."""
    from . import aggregate

    out_dir = Path(out_dir)
    series = aggregate.cactus(rows)
    summaries = aggregate.summarize(rows)
    counts = aggregate.outcome_counts(rows)
    # Draw against whatever the suite actually swept. Hardcoding agent count
    # gave mapf-density — a density sweep at a fixed sixteen agents — a chart
    # with one x position holding a median over six densities.
    x_key = aggregate.varying_x_key(rows) or "n_agents"
    curves = aggregate.scaling(rows, x_key)
    caps = aggregate.timeout_points(rows, x_key)
    # The budget the rows were actually run under, not the one the suite file
    # asks for. Where a suite gives its groups different budgets, the largest
    # is the only cap that holds for the whole figure.
    budgets = {float(row.timeout_s) for row in rows if row.timeout_s}
    budget_s = max(budgets) if budgets else None

    written: list[Path] = []
    for dark in (False, True):
        written.append(cactus_plot(series, out_dir, dark, budget_s))
        written.append(coverage_bars(summaries, out_dir, dark))
        written.append(outcome_bars(counts, out_dir, dark))
        if curves or caps:
            written.append(
                scaling_plot(
                    curves,
                    caps,
                    out_dir,
                    dark,
                    xlabel=aggregate.X_LABELS.get(x_key, x_key),
                )
            )
    return written
