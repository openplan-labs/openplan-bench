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


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 0.001:
        return f"{seconds * 1e6:.0f} µs"
    if seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    return f"{seconds:.2f} s"


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


def _leaderboard_table(summaries) -> str:
    if not summaries:
        return '<p class="empty">No configuration produced a row.</p>'
    head = (
        "<thead><tr>"
        "<th>Configuration</th><th>Family</th>"
        '<th class="num">Coverage</th><th class="num">Solved</th>'
        '<th class="num">Instances</th><th class="num">Timeouts</th>'
        '<th class="num">Errors</th><th class="num">Unsolved</th>'
        '<th class="num">Median time</th><th class="num">Total time (solved)</th>'
        '<th class="num">Expanded</th>'
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
    )


def _cell_table(cells) -> str:
    if not cells:
        return '<p class="empty">No run was recorded for this suite.</p>'
    head = (
        "<thead><tr>"
        "<th>Instance</th><th>Configuration</th><th>Outcome</th>"
        '<th class="num">Median time</th><th class="num">Min</th><th class="num">Max</th>'
        '<th class="num">Cost</th><th class="num">Length</th>'
        '<th class="num">Makespan</th><th class="num">Expanded</th>'
        '<th class="num">Seeds</th><th>Note</th>'
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
            f"<td>{esc(note[:160])}</td>"
            "</tr>"
        )
    return (
        '<div class="tablewrap"><table data-sortable>'
        + head
        + "<tbody>"
        + "".join(body)
        + "</tbody></table></div>"
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

    figures = "".join(
        [
            _figure(
                "cactus",
                "Instances solved as the per-instance time budget grows. "
                "A curve that stops has run out of instances it can solve, "
                "not out of speed.",
                result.name,
            ),
            _figure(
                "coverage",
                "Instances solved on every seed, with the timed-out and "
                "unsolved remainder broken out.",
                result.name,
            ),
            _figure(
                "outcomes",
                "Every run in this suite by outcome, including runs that were "
                "never attempted because a backend was absent.",
                result.name,
            ),
            _figure(
                "scaling",
                "Median wall time against agent count; the band is the observed "
                "min–max over seeds. Hollow triangles mark cells that hit the "
                "budget.",
                result.name,
            )
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
     {esc(result.generated)} &middot; results: {history_links or "—"}</p>
{runner_note}
  <div class="stats">
    <div class="stat"><span class="k">Rows recorded</span><span class="v">{total}</span></div>
    <div class="stat"><span class="k">Runs attempted</span><span class="v">{attempted}</span></div>
    <div class="stat"><span class="k">Solved</span><span class="v accent">{solved}</span></div>
    <div class="stat"><span class="k">Timed out</span><span class="v">{counts.get("timeout", 0)}</span></div>
    <div class="stat"><span class="k">Errored</span><span class="v">{counts.get("error", 0)}</span></div>
    <div class="stat"><span class="k">Not run</span><span class="v">{counts.get("not-installed", 0) + counts.get("skipped", 0)}</span></div>
  </div>

  <h3>Leaderboard</h3>
{_leaderboard_table(summaries)}

  <h3>Figures</h3>
  <div class="figs">
{figures}  </div>

  <h3>Every instance</h3>
  <div data-tablescope="{index}">
{_controls(sorted(counts), str(index))}
{_cell_table(cells)}
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


def render_methodology(results: list[SuiteResults]) -> str:
    machines = sorted({r.machine for r in results}) or ["no results committed yet"]
    machine_items = "\n".join(f"    <li><code>{esc(m)}</code></li>" for m in machines)
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
  <dd>The wall-clock budget was exhausted. The recorded time is the
    <em>budget</em>, never an extrapolation of how long the run would have
    taken. Solvability is unknown. This is the single most important
    distinction on the page: a timeout is not a proof of unsolvability.</dd>
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

<h3>Hardware these numbers came from</h3>
<ul class="tight">
{machine_items}
</ul>
<p>Every row carries its own CPU model, platform, Python version, package
versions, timestamp, seed and the harness git SHA, so results files from
different machines stay interpretable after they are concatenated.</p>

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
  <li><strong>No memory profiling.</strong> Peak RSS is recorded per run as a
    coarse figure, not measured carefully.</li>
  <li><strong>No GPU results unless a suite says so.</strong> The CUDA arm is
    skipped, visibly, wherever no working device was found.</li>
</ul>
</div>
"""
        + _foot()
    )


def render_reproduce(results: list[SuiteResults]) -> str:
    suites = "\n".join(
        f"python -m openplan_bench run suites/{esc(r.name)}.yaml --out results/"
        for r in results
    ) or "python -m openplan_bench run suites/classical-smoke.yaml --out results/"
    return (
        _head("Reproduce", "reproduce.html")
        + f"""<div class="prose">
<h2>Running this yourself</h2>
<p>Everything on the leaderboard comes from files in the repository. There is no
hidden state and no database.</p>

<pre><code>git clone {REPO}
cd openplan-bench
git clone https://github.com/openplan-labs/pddl-examples ../pddl-examples

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
    That is a real result and it will be recorded as a timeout.</li>
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
planner, instance, seed, outcome, metrics <em>and</em> the machine, package
versions and harness SHA that produced it.</p>

<pre><code>import openplan_bench.records as records
rows = records.read_csv("results/classical-smoke/2026-08-21.csv")
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
