"""Generate the Frontier-branded leaderboard from committed results.

The site is static, dependency-free HTML written into ``docs/`` and served by
GitHub Pages. Everything it shows comes from the results files in the
repository, so the dashboard cannot say anything the committed data does not
support — including the unflattering parts. Timeouts, errors, invalid plans and
uninstalled backends all get rows.

Three pages:

``index.html``       the leaderboard: per-suite tables, per-instance detail, figures
``methodology.html`` what "solved" means, and what these numbers are not
``reproduce.html``   the commands, honestly listing what will differ on your box
"""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import aggregate, charts, provenance
from .records import RunRecord, read_csv
from .runner import GRACE_S

TEMPLATES = Path(__file__).resolve().parent / "templates"

MARK_LIGHT = (
    "https://raw.githubusercontent.com/openplan-labs/branding/main/"
    "assets/logo/mark-accent.svg"
)
MARK_DARK = (
    "https://raw.githubusercontent.com/openplan-labs/branding/main/"
    "assets/logo/mark-dark.svg"
)
FAVICON = (
    "https://raw.githubusercontent.com/openplan-labs/branding/main/"
    "assets/logo/favicon.svg"
)
REPO = "https://github.com/openplan-labs/openplan-bench"

PAGES = (
    ("index.html", "Leaderboard"),
    ("methodology.html", "Methodology"),
    ("reproduce.html", "Reproduce"),
)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def clip(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` without severing a word.

    A plain slice cut an adapter's install hint mid-URL, so the published
    page showed a command that 404s. Back off to the last space instead, and
    mark the cut so a truncated note cannot be read as a complete one.
    """
    text = str(text)
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ")
    if space > limit // 2:
        head = head[:space]
    return head.rstrip(" ,;.") + " …"


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 0.001:
        return f"{seconds * 1e6:.0f} µs"
    if seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    return f"{seconds:.2f} s"


def fmt_budget(seconds: float) -> str:
    """A budget as a reader would say it: ``20 s``, ``500 ms``."""
    if seconds >= 1:
        return f"{seconds:g} s"
    return f"{seconds * 1000:g} ms"


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:g}" if isinstance(value, float) else str(value)


@dataclass
class SuiteResults:
    """One suite's committed rows, plus the header written beside them."""

    name: str
    rows: list[RunRecord]
    meta: dict[str, Any]

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.name)

    @property
    def description(self) -> str:
        return str(self.meta.get("description") or "")

    @property
    def runner_grade(self) -> bool:
        return bool(self.meta.get("runner_grade"))

    @property
    def machine(self) -> str:
        if self.meta.get("machine"):
            return str(self.meta["machine"])
        if self.rows:
            row = self.rows[0]
            return (
                f"{row.cpu_model} ({row.cpu_count} logical CPUs), {row.platform}, "
                f"Python {row.python_version}, harness {row.harness_version}"
                f"@{row.harness_sha}"
            )
        return "unknown"

    @property
    def generated(self) -> str:
        return str(self.meta.get("generated_utc") or "")

    @property
    def stamped(self) -> str:
        """What ``timestamp_utc`` actually says across these rows.

        A schema-2 file carries one stamp for the whole run, repeated on every
        row; from schema 3 each row is stamped as it is produced. Say which of
        the two this file is rather than printing a date and letting the reader
        assume per-row provenance.
        """
        stamps = sorted({row.timestamp_utc for row in self.rows if row.timestamp_utc})
        if not stamps:
            return "no run timestamp recorded"
        if len(stamps) == 1:
            return f"run stamped {stamps[0]} (one stamp for the whole run)"
        return f"rows stamped {stamps[0]} to {stamps[-1]}"

    @property
    def budgets(self) -> list[tuple[float, int]]:
        """Every distinct ``(wall-clock budget, memory cap)`` behind these rows.

        Read off the rows, not off the suite file. The suite file records what
        the harness was *asked* for; the rows record what was actually enforced
        on the measurement, and where the two disagree the table has to show
        the second one.
        """
        seen: list[tuple[float, int]] = []
        for row in self.rows:
            pair = (float(row.timeout_s), int(row.memory_limit_mb))
            if pair not in seen:
                seen.append(pair)
        return sorted(seen)

    @property
    def budget(self) -> str:
        """One sentence naming the budget every row in this suite ran under.

        Coverage without a stated budget is not a number: "solved 9 of 18" says
        nothing until you know whether the planner had twenty seconds or twenty
        minutes. Every table on this site carries this line.
        """
        pairs = self.budgets
        if not pairs:
            return "No per-instance budget is recorded in these rows."
        parts = [
            f"{fmt_budget(timeout_s)} wall clock, "
            + (
                f"{memory_mb:,} MiB address space (RLIMIT_AS)"
                if memory_mb > 0
                else "no memory cap"
            )
            for timeout_s, memory_mb in pairs
        ]
        if len(parts) == 1:
            return f"Per-instance budget: {parts[0]}."
        return (
            "Per-instance budget differs across this suite's groups: "
            + "; ".join(parts)
            + ". Each row's own budget is in its timeout_s and "
            "memory_limit_mb columns."
        )


def load_results(results_dir: str | Path = "results") -> list[SuiteResults]:
    """Read every suite's latest results, newest CSV per suite directory."""
    results_dir = Path(results_dir)
    out: list[SuiteResults] = []
    if not results_dir.exists():
        return out
    for suite_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        csvs = sorted(suite_dir.glob("*.csv"))
        if not csvs:
            continue
        rows = read_csv(csvs[-1])
        meta: dict[str, Any] = {}
        latest = suite_dir / "latest.json"
        if latest.exists():
            try:
                payload = json.loads(latest.read_text(encoding="utf-8"))
                meta = {k: v for k, v in payload.items() if k != "rows"}
            except json.JSONDecodeError:
                meta = {}
        meta.setdefault("history", [p.name for p in csvs])
        out.append(SuiteResults(name=suite_dir.name, rows=rows, meta=meta))
    return out


# ---------------------------------------------------------------------------
def _head(title: str, current: str, depth: int = 0) -> str:
    prefix = "../" * depth
    nav = "\n".join(
        f'      <a href="{prefix}{href}"'
        + (' aria-current="page"' if href == current else "")
        + f">{esc(label)}</a>"
        for href, label in PAGES
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · openplan-bench</title>
<meta name="description" content="Reproducible benchmarks for the OpenPlan Labs planners.">
<link rel="icon" href="{FAVICON}" type="image/svg+xml">
<link rel="stylesheet" href="{prefix}assets/tokens.css">
<link rel="stylesheet" href="{prefix}assets/site.css">
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <div class="brandline">
      <img src="{MARK_LIGHT}" alt="" width="30" height="30"
           data-light="{MARK_LIGHT}" data-dark="{MARK_DARK}">
      <span class="org">OpenPlan Labs</span>
    </div>
    <h1>openplan-bench</h1>
    <p class="tagline">One harness, one problem set, one results schema for
      every planner in the org. Planners not included &mdash; they are extras.</p>
    <nav class="tabs">
{nav}
      <a href="{REPO}">Source</a>
    </nav>
  </div>
</header>
<main class="wrap">
"""


def _foot(depth: int = 0) -> str:
    prefix = "../" * depth
    return f"""</main>
<footer class="foot">
  <div class="wrap">
    <p>Generated by <code>openplan-bench site</code> from the results committed
      in this repository. Every number on this page is reproducible from
      <code>results/</code> and the suite file that produced it.</p>
    <p>Colour, type and figures follow
      <a href="https://github.com/openplan-labs/branding">openplan-labs/branding</a>
      (Frontier). Built {esc(provenance.now_utc())}.</p>
  </div>
</footer>
<script src="{prefix}assets/site.js"></script>
</body>
</html>
"""


def _figure(stem: str, caption: str, suite: str) -> str:
    light = f"figures/{suite}/{stem}.png"
    dark = f"figures/{suite}/{stem}-dark.png"
    return f"""    <figure>
      <img src="{light}" data-light="{light}" data-dark="{dark}"
           alt="{esc(caption)}" loading="lazy">
      <figcaption>{esc(caption)}</figcaption>
    </figure>
"""


def _leaderboard_table(summaries, budget: str) -> str:
    if not summaries:
        return '<p class="empty">No configuration produced a row.</p>'
    head = (
        f"<caption>{esc(budget)} Enforced on every row in this table.</caption>"
        "<thead><tr>"
        "<th>Configuration</th><th>Family</th>"
        '<th class="num">Coverage</th><th class="num">Solved</th>'
        '<th class="num">Instances</th><th class="num">Timeouts</th>'
        '<th class="num">Errors</th><th class="num">Unsolved</th>'
        '<th class="num">Median time<br><small>solved only</small></th>'
        '<th class="num">Total time<br><small>solved only</small></th>'
        '<th class="num">Expanded<br><small>solved only</small></th>'
        "</tr></thead>"
    )
    body: list[str] = []
    for summary in summaries:
        if not summary.was_run:
            # Nothing was attempted, so there is no coverage to report. Showing
            # 0% would read as "solved nothing", which is not what happened.
            body.append(
                "<tr>"
                f'<td class="name">{esc(summary.adapter)}:{esc(summary.label)}</td>'
                f"<td>{esc(summary.family)}</td>"
                f'<td class="num" data-sort="-1"><span class="pill not-installed">'
                f"not run</span></td>"
                + '<td class="num">—</td>' * 8
                + "</tr>"
            )
            continue
        pct = 100.0 * summary.coverage
        invalid = (
            f' <span class="pill error" title="plans rejected by the validator">'
            f"{summary.invalid} invalid</span>"
            if summary.invalid
            else ""
        )
        body.append(
            "<tr>"
            f'<td class="name">{esc(summary.adapter)}:{esc(summary.label)}{invalid}</td>'
            f"<td>{esc(summary.family)}</td>"
            f'<td class="num barcell" data-sort="{summary.coverage:.6f}">'
            f'{pct:.0f}%<span class="bar" style="width:{max(pct, 1.0):.0f}%"></span></td>'
            f'<td class="num">{summary.solved}</td>'
            f'<td class="num">{summary.instances}</td>'
            f'<td class="num">{summary.timeouts}</td>'
            f'<td class="num">{summary.errors}</td>'
            f'<td class="num">{summary.unsolved}</td>'
            f'<td class="num" data-sort="{summary.median_time or 0:.6f}">'
            f"{fmt_time(summary.median_time)}</td>"
            f'<td class="num" data-sort="{summary.total_time_solved:.6f}">'
            f"{fmt_time(summary.total_time_solved)}</td>"
            f'<td class="num">{fmt_num(summary.total_expanded)}</td>'
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table data-sortable>'
        + head
        + "<tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + '<p class="caption"><strong>Coverage</strong> is Solved &divide; '
        "Instances, and both are columns here so the denominator is never "
        "implied. <strong>Median time</strong>, <strong>Total time</strong> "
        "and <strong>Expanded</strong> are computed over the instances a "
        "configuration actually solved, so each row has a different "
        "denominator and none of those three are comparable across rows — "
        "including when you sort by them. A configuration that solves only "
        "the easy instances posts the fastest time and the smallest node "
        "count on this table; that is an artefact of the subset it solved, "
        "not a result. Read them against Coverage and Instances, never "
        "instead of them.</p>"
    )


def _cell_table(cells, budget: str) -> str:
    if not cells:
        return '<p class="empty">No run was recorded for this suite.</p>'
    head = (
        f"<caption>{esc(budget)} Enforced on every row in this table.</caption>"
        "<thead><tr>"
        "<th>Instance</th><th>Configuration</th><th>Outcome</th>"
        '<th class="num">Median time</th><th class="num">Min</th><th class="num">Max</th>'
        '<th class="num">Cost</th><th class="num">Length</th>'
        '<th class="num">Makespan</th><th class="num">Expanded</th>'
        '<th class="num">Samples<br><small>seeds x reps</small></th><th>Note</th>'
        "</tr></thead>"
    )
    body: list[str] = []
    for cell in cells:
        median, low, high = cell.stat("wall_time_s")
        cost, _, _ = cell.stat("cost")
        length, _, _ = cell.stat("plan_length")
        makespan, _, _ = cell.stat("makespan")
        expanded, _, _ = cell.stat("expanded")
        status = cell.status
        pill = status.split(" ")[0].replace("(", "").replace(")", "")
        note = next((r.note for r in cell.rows if r.note), "") or next(
            (r.error for r in cell.rows if r.error), ""
        )
        body.append(
            f'<tr data-outcome="{esc(pill)}">'
            f'<td class="name">{esc(cell.instance)}</td>'
            f'<td class="name">{esc(cell.adapter)}:{esc(cell.label)}</td>'
            f'<td><span class="pill {esc(pill)}">{esc(status)}</span></td>'
            f'<td class="num" data-sort="{median or 0:.6f}">{fmt_time(median)}</td>'
            f'<td class="num" data-sort="{low or 0:.6f}">{fmt_time(low)}</td>'
            f'<td class="num" data-sort="{high or 0:.6f}">{fmt_time(high)}</td>'
            f'<td class="num">{fmt_num(cost)}</td>'
            f'<td class="num">{fmt_num(length)}</td>'
            f'<td class="num">{fmt_num(makespan)}</td>'
            f'<td class="num">{fmt_num(expanded)}</td>'
            f'<td class="num">{cell.n_solved}/{cell.n_measured or len(cell.rows)}</td>'
            f"<td>{esc(clip(note, 160))}</td>"
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table data-sortable>'
        + head
        + "<tbody>"
        + "".join(body)
        + "</tbody></table></div>"
        + '<p class="caption">Median, Min and Max are over the <strong>solved'
        "</strong> repetitions of that cell only, so a partially-solved cell "
        "times the repetitions that finished and a cell that never solved "
        "shows &mdash;. A <span class=\"pill timeout\">timeout</span> row is "
        "therefore absent from every time column here: what it recorded is "
        "<code>wall_time_s</code> in the results file, the elapsed time at "
        "which the run was <em>stopped</em> — slightly past the budget, "
        "because a planner notices its own limit and unwinds — and never an "
        "estimate of how long a solution would have taken. The budget itself "
        "is the separate <code>timeout_s</code> column. Sorting this table "
        "reorders rows whose Samples denominators differ; the Samples column "
        "is shown so that is visible.</p>"
    )


def _controls(outcomes: list[str], scope_id: str) -> str:
    options = "".join(f'<option value="{esc(o)}">{esc(o)}</option>' for o in outcomes)
    return f"""  <div class="controls">
    <input id="q-{scope_id}" type="search" data-filter aria-label="Filter rows"
           placeholder="Filter instances or planners…" size="30">
    <select data-filter-outcome aria-label="Filter by outcome">
      <option value="">every outcome</option>{options}
    </select>
    <span class="count"></span>
  </div>
"""


def _scaling_caption(result: SuiteResults) -> str:
    """Describe the scaling figure in terms of the axis it was actually drawn on.

    The caption used to name the agent count unconditionally, which was wrong
    for a suite that sweeps obstacle density at a fixed agent count.
    """
    x_key = aggregate.varying_x_key(result.rows)
    pooled = aggregate.pooled_x_keys(result.rows, x_key or "")
    if x_key is None:
        axis = "instance size"
        trend = (
            "This suite varies no instance parameter the figure knows how to "
            "plot, so the marks share one x position and are not a trend. "
        )
    else:
        axis = aggregate.X_LABELS[x_key]
        trend = ""
    pooled_note = (
        "Each point is the median over the cells at that x, which here also "
        + " and ".join(f"differ in {aggregate.X_LABELS[key]}" for key in pooled)
        + ". "
        if pooled
        else ""
    )
    return (
        f"Median wall time against {axis}; the band is the observed min–max "
        f"over seeds. {trend}{pooled_note}Every curve is drawn only over the "
        "values that solver solved on every seed, so two curves of different "
        "length cover different instance sets and their heights are not a "
        "like-for-like comparison. Hollow triangles mark cells that hit the "
        f"budget. {result.budget}"
    )


def _sample_note(cells) -> str:
    """Say so where a cell's Median, Min and Max are one measurement repeated.

    ``seeds: [0]`` with ``repetitions: 1`` gives a cell exactly one sample, and
    the aggregation dutifully reports its median, its minimum and its maximum —
    the same number three times. Printed without a note that reads as an
    observed range, which is a spread the run never measured.
    """
    sizes = sorted(cell.n_measured for cell in cells if cell.n_measured)
    if not sizes or sizes[-1] == 0:
        return ""
    single = sum(1 for size in sizes if size == 1)
    if not single:
        return ""
    scope = (
        "Every cell in this suite is"
        if single == len(sizes)
        else f"{single} of the {len(sizes)} cells in this suite are"
    )
    return f"""  <div class="note"><p><strong>Single-sample timings.</strong>
    {scope} one measurement: one seed, one repetition. Median, Min and Max are
    then the same number three times &mdash; a sample, not an observed range.
    Node counts, cost and validity are unaffected, being deterministic; the
    seconds should not be quoted with a spread until the suite is re-run with
    more seeds.</p></div>
"""


def _suite_section(result: SuiteResults, index: int) -> str:
    rows = result.rows
    summaries = aggregate.summarize(rows)
    cells = aggregate.cells(rows)
    counts = aggregate.outcome_counts(rows)
    solved = counts.get("solved", 0)
    total = len(rows)
    attempted = sum(counts.get(k, 0) for k in aggregate.MEASURED)

    badge = (
        '<span class="badge runner">runner-grade</span>' if result.runner_grade else ""
    )
    runner_note = (
        """  <div class="note warn"><p><strong>Runner-grade timings.</strong>
    This suite was measured on a shared GitHub Actions runner. Absolute wall
    times there vary by a factor of two or more between runs and tell you
    nothing about the hardware a planner would see in practice.
    <em>Coverage, plan cost, node counts and validity are still exact</em> —
    those do not depend on how fast the machine was. Compare times within a
    single run of this table, never across runs or against your laptop.</p></div>
"""
        if result.runner_grade
        else ""
    )
    sample_note = _sample_note(cells)

    figures = "".join(
        [
            _figure(
                "cactus",
                "Instances solved as the per-instance time budget grows. "
                "A curve that stops has run out of instances it can solve, "
                "not out of speed. The dashed line is the budget this suite "
                f"actually ran under. {result.budget}",
                result.name,
            ),
            _figure(
                "coverage",
                "Instances solved on every seed, with the timed-out and "
                f"unsolved remainder broken out. {result.budget}",
                result.name,
            ),
            _figure(
                "outcomes",
                "Every run in this suite by outcome, including runs that were "
                "never attempted because a backend was absent.",
                result.name,
            ),
            _figure("scaling", _scaling_caption(result), result.name)
            if any(r.family == "mapf" for r in rows)
            else "",
        ]
    )

    history = result.meta.get("history") or []
    history_links = ", ".join(
        f'<a href="{REPO}/blob/main/results/{esc(result.name)}/{esc(name)}">'
        f"{esc(name)}</a>"
        for name in history[-6:]
    )

    return f"""<section class="suite" id="{esc(result.name)}">
  <h2>{esc(result.title)}{badge}</h2>
  <p class="desc">{esc(result.description)}</p>
  <p class="meta">{esc(result.machine)}<br>
     <strong>{esc(result.budget)}</strong><br>
     {esc(result.stamped)} &middot; published {esc(result.generated)} &middot;
     results: {history_links or "—"}</p>
{runner_note}{sample_note}
  <div class="stats">
    <div class="stat"><span class="k">Rows recorded</span><span class="v">{total}</span></div>
    <div class="stat"><span class="k">Runs attempted</span><span class="v">{attempted}</span></div>
    <div class="stat"><span class="k">Solved</span><span class="v accent">{solved}</span></div>
    <div class="stat"><span class="k">Timed out</span><span class="v">{counts.get("timeout", 0)}</span></div>
    <div class="stat"><span class="k">Errored</span><span class="v">{counts.get("error", 0)}</span></div>
    <div class="stat"><span class="k">Not run</span><span class="v">{counts.get("not-installed", 0) + counts.get("skipped", 0)}</span></div>
  </div>
  <p class="caption">These six count <strong>rows</strong> — one per
    (configuration, instance, seed, repetition). The Solved column in the
    leaderboard below counts <strong>instances</strong>, and only those a
    configuration solved on every seed, so the two numbers are different
    measurements of different things and will not agree.</p>

  <h3>Leaderboard</h3>
{_leaderboard_table(summaries, result.budget)}

  <h3>Figures</h3>
  <div class="figs">
{figures}  </div>

  <h3>Every instance</h3>
  <div data-tablescope="{index}">
{_controls(sorted(counts), str(index))}
{_cell_table(cells, result.budget)}
  </div>
</section>
"""


# ---------------------------------------------------------------------------
def render_index(results: list[SuiteResults]) -> str:
    parts = [_head("Leaderboard", "index.html")]
    if not results:
        parts.append(
            '<p class="empty">No results are committed yet. Run '
            "<code>python -m openplan_bench run suites/classical-smoke.yaml</code> "
            "and rebuild the site.</p>"
        )
    else:
        total_rows = sum(len(r.rows) for r in results)
        parts.append(
            f"""<div class="note"><p><strong>What this is.</strong> Every planner
in OpenPlan Labs, run over shared problem sets by one harness that records
timeouts and errors as results rather than dropping them. {len(results)} suite(s),
{total_rows} recorded runs. <a href="methodology.html">What &ldquo;solved&rdquo;
means</a> &middot; <a href="reproduce.html">How to reproduce this</a>.</p></div>
"""
        )
        for index, result in enumerate(results):
            parts.append(_suite_section(result, index))
    parts.append(_foot())
    return "".join(parts)


def _budget_table(results: list[SuiteResults]) -> str:
    """Every published suite's per-instance budget, read from its own rows."""
    if not results:
        return '<p class="empty">No results are committed yet.</p>'
    rows_out: list[str] = []
    for result in results:
        pairs = result.budgets
        # A suite whose groups carry different budgets gets every one of them
        # in the cell. Showing the first would be a caption that is true of
        # some of the rows and false of the rest.
        wall = " / ".join(fmt_budget(t) for t, _ in pairs) or "—"
        mem = " / ".join(f"{m:,} MiB" if m else "none" for _, m in pairs) or "—"
        rows_out.append(
            "<tr>"
            f'<td class="name">{esc(result.title)}</td>'
            f'<td class="num">{esc(wall)}</td>'
            f'<td class="num">{esc(mem)}</td>'
            f'<td class="num">{len(result.rows)}</td>'
            "</tr>"
        )
    body = "".join(rows_out)
    return (
        '<div class="tablewrap"><table>'
        "<caption>Read from the committed rows, not from the suite files — "
        "these are the budgets the measurements were actually taken under."
        "</caption>"
        "<thead><tr><th>Suite</th><th class=\"num\">Wall clock</th>"
        '<th class="num">Address space</th><th class="num">Rows</th>'
        "</tr></thead><tbody>" + body + "</tbody></table></div>"
    )


def render_methodology(results: list[SuiteResults]) -> str:
    machines = sorted({r.machine for r in results}) or ["no results committed yet"]
    machine_items = "\n".join(f"    <li><code>{esc(m)}</code></li>" for m in machines)
    budget_table = _budget_table(results)
    provenance_grace = GRACE_S
    return (
        _head("Methodology", "methodology.html")
        + f"""<div class="prose">
<h2>What a number here means</h2>
<p>A benchmark that reports only its successes is an advertisement. This one
records every run it was asked to make, and the tables above show the failures
next to the wins because that is the comparison a reader needs.</p>

<h3>Outcomes</h3>
<dl class="defs">
  <dt>solved</dt>
  <dd>The planner returned a plan <em>and</em> an independent validator accepted
    it. For classical planning the plan is replayed through the grounded task
    and the goal is re-checked; for MAPF the returned paths are re-scanned for
    vertex and edge conflicts. A planner's own claim of success is never
    sufficient — a plan the validator rejects is shown as
    <span class="pill error">invalid</span> and does not count towards coverage.</dd>
  <dt>unsolved</dt>
  <dd>The planner terminated on its own and reported no solution. For an
    incomplete planner this is data, not a bug: it means the search strategy
    failed on this instance, not that the instance is unsolvable.</dd>
  <dt>timeout</dt>
  <dd>The wall-clock budget was exhausted. <strong>Two numbers are recorded and
    they are not the same one.</strong> <code>timeout_s</code> is the budget the
    run was given. <code>wall_time_s</code> is the elapsed time at which the run
    was actually stopped — a little <em>past</em> the budget, because a planner
    notices its own limit and unwinds, and so it is a measurement rather than a
    constant. Neither is an extrapolation of how long a solution would have
    taken; solvability is unknown. This is the single most important distinction
    on the page: a timeout is not a proof of unsolvability. Timing statistics in
    the tables are computed from solved runs only, so a timeout moves coverage
    and nothing else.</dd>
  <dt>memory</dt>
  <dd>The address-space limit fired, or the process was killed by the OOM
    killer. As with a timeout, solvability is unknown.</dd>
  <dt>error</dt>
  <dd>The planner raised, crashed, or produced output the adapter could not
    read. The message is kept in the row. Parse failures on a domain a planner
    does not support land here, which is deliberate: "cannot read this domain"
    is a real limitation and belongs in the table.</dd>
  <dt>skipped</dt>
  <dd>Deliberately not run. The CUDA arm on a machine with no working GPU is
    the common case, and the row says so rather than vanishing.</dd>
  <dt>not-installed</dt>
  <dd>The backend was not importable in the environment that produced these
    results. The runs were still enumerated, so a gap in the table is always
    explained.</dd>
</dl>

<h3>Coverage</h3>
<p>An instance counts as solved for a configuration only when <strong>every
seed</strong> returned a valid solution. A configuration that solves an
instance on two seeds out of three is reported as partial, not as solved:
a coverage number that a re-run would not reproduce is not worth printing.
Runs that never happened are excluded from the denominator rather than counted
as failures.</p>

<h3>Timing</h3>
<ul class="tight">
  <li>Wall-clock, <code>time.perf_counter</code>, measured inside the child
    process around the whole call — parsing and grounding included, because that
    is time a user waits.</li>
  <li>Every run happens in a fresh subprocess with a hard kill and an
    <code>RLIMIT_AS</code> cap, so a wedged planner costs one row, not the
    sweep.</li>
  <li>Runs are executed <strong>serially</strong>. Timing N planners on N cores
    measures the memory subsystem, not the planners.</li>
  <li>Reported statistics are the <strong>median over seeds</strong> with the
    observed <strong>min&ndash;max</strong> as the band. Three seeds do not
    support a standard deviation, and a mean is moved by a single scheduling
    hiccup.</li>
  <li>Timing aggregates use solved runs only. Folding a timeout's budget into a
    mean runtime makes a planner look faster as it starts failing.</li>
</ul>

<h3 id="budgets">Budgets</h3>
<p>A coverage number is meaningless without the budget it was measured under:
&ldquo;solved 9 of 18&rdquo; says nothing until you know whether the planner had
twenty seconds or twenty minutes. Every table on this site carries its suite's
budget in its caption; this is all of them in one place.</p>
{budget_table}
<p>The wall-clock budget is enforced twice — the planner is asked to stop itself
at it, and the harness kills the child {provenance_grace:g}&nbsp;s later if it
has not. The address-space figure is a hard <code>RLIMIT_AS</code> set inside
the child before the planner is imported, so exceeding it produces a
<span class="pill memory">memory</span> row rather than a swapping machine and a
meaningless sweep.</p>

<h3>Hardware these numbers came from</h3>
<ul class="tight">
{machine_items}
</ul>
<p>Every row carries the CPU model, platform, Python version, package versions,
seed and harness git SHA it was produced under, so results files from different
machines stay interpretable after they are concatenated.</p>
<p><code>timestamp_utc</code> is the exception and is worth stating exactly:
in a schema&nbsp;2 results file it is <strong>one stamp per suite run</strong>,
taken when the run started and copied onto every row of that file — not a
per-row clock reading, and not the moment any individual measurement was taken.
Rows written from schema&nbsp;3 onwards are stamped as each one is produced.
The published tables above therefore show a run start, not a per-row time, and
say so.</p>

<h3>What this does <em>not</em> measure</h3>
<div class="note warn"><p>Read this section before quoting a number.</p></div>
<ul class="tight">
  <li><strong>It is not a planner competition.</strong> The problem set is what
    <a href="https://github.com/openplan-labs/pddl-examples">pddl-examples</a>
    happens to contain plus generated MAPF grids &mdash; not a stratified
    benchmark set. Coverage here does not transfer to IPC coverage.</li>
  <li><strong>It does not compare these planners to the state of the art.</strong>
    Nothing here is measured against Fast Downward, LAMA, EECBS or any other
    external system. These are pure-Python research implementations and the
    numbers should be read as such.</li>
  <li><strong>Cross-machine times are not comparable.</strong> Suites marked
    <span class="badge runner">runner-grade</span> ran on shared CI hardware.
    Their coverage and costs are exact; their seconds are not a hardware
    comparison and must not be quoted as one.</li>
  <li><strong>Absolute times include Python startup and parsing</strong> inside
    the measured region for classical planning. That is honest for a user
    waiting on a CLI and unfair as an algorithmic comparison; node expansions
    are the metric to use for the latter.</li>
  <li><strong>No replication.</strong> Each suite was measured on one machine,
    once. Where a suite also runs one seed and one repetition, its per-cell
    Median, Min and Max are one sample printed three times and the suite says
    so above its own table. Coverage, node counts, cost and validity do not
    depend on this; the seconds do.</li>
  <li><strong>No memory profiling.</strong> Peak RSS is recorded per run as a
    coarse figure, not measured carefully.</li>
  <li><strong>No GPU results unless a suite says so.</strong> The CUDA arm is
    skipped, visibly, wherever no working device was found.</li>
</ul>
</div>
"""
        + _foot()
    )


def _example_csv(results: list[SuiteResults]) -> str:
    """A results path that exists, taken from the committed files.

    Hardcoding a date here published a snippet that raises ``FileNotFoundError``
    on a fresh clone, which is a bad first impression for a page whose whole
    claim is that the numbers are reproducible.
    """
    for result in results:
        history = [str(name) for name in (result.meta.get("history") or [])]
        source = str(result.meta.get("source_csv") or "")
        name = source if source in history else (history[-1] if history else "")
        if name:
            return f"results/{result.name}/{name}"
    return "results/classical-smoke/<date>.csv"


def render_reproduce(results: list[SuiteResults]) -> str:
    suites = "\n".join(
        f"python -m openplan_bench run suites/{esc(r.name)}.yaml --out results/"
        for r in results
    ) or "python -m openplan_bench run suites/classical-smoke.yaml --out results/"
    example_csv = _example_csv(results)
    return (
        _head("Reproduce", "reproduce.html")
        + f"""<div class="prose">
<h2>Running this yourself</h2>
<p>Everything on the leaderboard comes from files in the repository. There is no
hidden state and no database.</p>

<pre><code>git clone {REPO}.git
cd openplan-bench

# The classical suites resolve corpus_root against the suite file, so the
# corpus belongs at corpus/pddl-examples inside this checkout.
git clone https://github.com/openplan-labs/pddl-examples corpus/pddl-examples

python -m venv .venv &amp;&amp; source .venv/bin/activate
pip install -e '.[all,dev]'

{suites}
python -m openplan_bench report results/
python -m openplan_bench site --results results/ --out docs/</code></pre>

<h3>What will differ on your machine</h3>
<ul class="tight">
  <li><strong>Wall times will differ, possibly a lot.</strong> A faster CPU
    moves every number; a shared or thermally throttled one moves them
    unevenly. Compare within one table.</li>
  <li><strong>Coverage may differ at the boundary.</strong> Instances that
    finished just inside the budget here may time out on a slower machine.
    That is a real result and it will be recorded as a timeout. The budget
    each suite was measured under is on
    <a href="methodology.html#budgets">the methodology page</a> and in every
    table's caption; changing <code>timeout_s</code> in a suite file changes
    what the coverage column means, so say so if you do.</li>
  <li><strong>Node expansions, plan cost, plan length, makespan and validity
    will not differ.</strong> Those are deterministic given the instance and
    the seed. If they differ, something has genuinely changed &mdash; that is
    the comparison worth making after a code change.</li>
  <li><strong>The corpus moves.</strong>
    <a href="https://github.com/openplan-labs/pddl-examples">pddl-examples</a>
    syncs new domains daily. Suites name their instances explicitly so a
    re-run measures the same problems; check out the corpus at the SHA in the
    results if you need byte-identical inputs.</li>
</ul>

<h3>Reading the results files</h3>
<p>Results live in <code>results/&lt;suite&gt;/&lt;date&gt;.csv</code>, one row
per measured run, never overwritten. <code>latest.json</code> beside them holds
the same rows plus the suite header. Rows are wide on purpose: each carries the
planner, instance, seed, outcome, metrics <em>and</em> the budget it ran under,
the machine, the package versions and the harness SHA that produced it.</p>
<p>Two columns are easy to confuse. <code>timeout_s</code> is the budget the run
was given; <code>wall_time_s</code> is what was measured. On a
<code>timeout</code> row that measurement is the elapsed time at which the run
was stopped, which sits a little past the budget — it is not the budget, and it
is not an estimate of how long a solution would have taken.</p>

<pre><code>import openplan_bench.records as records
rows = records.read_csv("{esc(example_csv)}")
print(sum(r.outcome == "timeout" for r in rows), "timeouts")</code></pre>

<h3>Adding your own planner</h3>
<p>Write one adapter, add one line to the registry, and it appears here. The
interface is three methods and is documented in
<a href="{REPO}#adding-a-planner">the README</a>;
<code>openplan_bench/adapters/fake.py</code> is the smallest complete example.</p>
</div>
"""
        + _foot()
    )


# ---------------------------------------------------------------------------
def build(
    results_dir: str | Path = "results",
    out_dir: str | Path = "docs",
    render_figures: bool = True,
) -> list[Path]:
    """Write the whole site, returning every path it created."""
    out_dir = Path(out_dir)
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    results = load_results(results_dir)

    for name in ("tokens.css", "site.css", "site.js"):
        shutil.copyfile(TEMPLATES / name, assets / name)
        written.append(assets / name)

    if render_figures:
        for result in results:
            written += charts.render_suite(
                result.rows, out_dir / "figures" / result.name
            )

    pages = {
        "index.html": render_index(results),
        "methodology.html": render_methodology(results),
        "reproduce.html": render_reproduce(results),
    }
    for name, body in pages.items():
        path = out_dir / name
        path.write_text(body, encoding="utf-8")
        written.append(path)

    # Pages must not run these through Jekyll; underscore-prefixed paths and
    # raw HTML would both be mangled.
    nojekyll = out_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)

    return written
