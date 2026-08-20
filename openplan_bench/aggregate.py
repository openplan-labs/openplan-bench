"""Turn per-run rows into the numbers a table or a chart shows.

Nothing is aggregated on disk. Results files hold one row per measurement and
every summary is recomputed from them, so a question nobody thought to ask when
the sweep ran can still be answered from the committed data.

Three conventions, all inherited from ``cuplan``'s sweep analysis and all
load-bearing:

* **Median over seeds, band from min to max.** A mean is dragged around by one
  scheduling hiccup; a standard deviation over three seeds is not a meaningful
  statistic. The median with the observed range says exactly what was seen.
* **Timing statistics come from solved runs only.** Averaging a timeout's
  budget into a runtime makes the slow planner look fast the moment it starts
  failing.
* **Coverage counts valid solutions, over conclusive-or-timeout runs.** A run
  that never happened (``not-installed``, ``skipped``) is not a failure and
  must not be in the denominator.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .records import RunRecord

#: Outcomes where the planner got its fair chance. The coverage denominator.
MEASURED = ("solved", "unsolved", "timeout", "memory", "error")


@dataclass
class Cell:
    """Every repetition of one (configuration, instance) pair."""

    adapter: str
    label: str
    instance: str
    instance_group: str
    rows: list[RunRecord] = field(default_factory=list)

    @property
    def measured(self) -> list[RunRecord]:
        return [r for r in self.rows if r.outcome in MEASURED]

    @property
    def solved_rows(self) -> list[RunRecord]:
        return [r for r in self.rows if r.outcome == "solved" and r.valid]

    @property
    def n_measured(self) -> int:
        return len(self.measured)

    @property
    def n_solved(self) -> int:
        return len(self.solved_rows)

    @property
    def solved_all_seeds(self) -> bool:
        """True when every measured repetition returned a valid solution."""
        return self.n_measured > 0 and self.n_solved == self.n_measured

    @property
    def status(self) -> str:
        """One word for the whole cell, worst-case first."""
        if not self.rows:
            return "none"
        if self.n_measured == 0:
            return self.rows[0].outcome  # not-installed / skipped
        if self.n_solved == self.n_measured:
            return "solved"
        outcomes = {r.outcome for r in self.measured}
        for candidate in ("error", "memory", "timeout", "unsolved"):
            if candidate in outcomes:
                return candidate if self.n_solved == 0 else f"partial ({candidate})"
        return "partial"

    def stat(self, field_name: str) -> tuple[float | None, float | None, float | None]:
        """``(median, min, max)`` of ``field_name`` over solved runs."""
        values = [
            float(getattr(row, field_name))
            for row in self.solved_rows
            if getattr(row, field_name) is not None
        ]
        if not values:
            return None, None, None
        return statistics.median(values), min(values), max(values)

    @property
    def median_time(self) -> float | None:
        return self.stat("wall_time_s")[0]


def cells(rows: list[RunRecord]) -> list[Cell]:
    """Group rows by (adapter, configuration, instance)."""
    buckets: dict[tuple[str, str, str], Cell] = {}
    for row in rows:
        key = (row.adapter, row.label, row.instance)
        cell = buckets.get(key)
        if cell is None:
            cell = buckets[key] = Cell(
                adapter=row.adapter,
                label=row.label,
                instance=row.instance,
                instance_group=row.instance_group,
            )
        cell.rows.append(row)
    return sorted(buckets.values(), key=lambda c: (c.adapter, c.label, c.instance))


@dataclass
class ConfigSummary:
    """A leaderboard line: one planner configuration over a whole suite."""

    adapter: str
    label: str
    family: str
    instances: int = 0
    solved: int = 0
    timeouts: int = 0
    errors: int = 0
    unsolved: int = 0
    not_run: int = 0
    invalid: int = 0
    total_time_solved: float = 0.0
    median_time: float | None = None
    total_expanded: int | None = None
    solve_times: list[float] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of instances with a valid plan on every seed."""
        return self.solved / self.instances if self.instances else 0.0


def summarize(rows: list[RunRecord]) -> list[ConfigSummary]:
    """One :class:`ConfigSummary` per (adapter, configuration).

    An instance counts as solved for a configuration only when *every* seed
    solved it validly. Reporting a coverage that a re-run would not reproduce
    is the failure mode this rule exists to prevent.
    """
    by_config: dict[tuple[str, str], ConfigSummary] = {}
    family: dict[tuple[str, str], str] = {}
    expanded: dict[tuple[str, str], list[int]] = defaultdict(list)

    for cell in cells(rows):
        key = (cell.adapter, cell.label)
        family.setdefault(key, cell.rows[0].family)
        summary = by_config.get(key)
        if summary is None:
            summary = by_config[key] = ConfigSummary(
                adapter=cell.adapter, label=cell.label, family=family[key]
            )
        summary.instances += 1
        status = cell.status

        if cell.solved_all_seeds:
            summary.solved += 1
            median = cell.median_time
            if median is not None:
                summary.solve_times.append(median)
                summary.total_time_solved += median
        elif status.startswith("timeout") or "timeout" in status:
            summary.timeouts += 1
        elif "error" in status or "memory" in status:
            summary.errors += 1
        elif status in ("not-installed", "skipped"):
            summary.not_run += 1
            summary.instances -= 1  # never asked to compete on this one
        else:
            summary.unsolved += 1

        if any(r.outcome == "solved" and not r.valid for r in cell.rows):
            summary.invalid += 1
        for row in cell.solved_rows:
            if row.expanded is not None:
                expanded[key].append(int(row.expanded))

    for key, summary in by_config.items():
        if summary.solve_times:
            summary.median_time = statistics.median(summary.solve_times)
        if expanded[key]:
            summary.total_expanded = sum(expanded[key])

    return sorted(
        by_config.values(),
        key=lambda s: (s.family, -s.coverage, s.total_time_solved),
    )


def cactus(rows: list[RunRecord]) -> dict[str, list[float]]:
    """Per-configuration solve times, sorted ascending — the cactus plot.

    Read it as: "with a per-instance budget of *y* seconds, this configuration
    solves *x* instances". It is the standard planning-competition figure
    because it answers the question a user actually has, rather than the
    question a bar chart of mean runtime answers.
    """
    series: dict[str, list[float]] = defaultdict(list)
    for cell in cells(rows):
        if not cell.solved_all_seeds:
            continue
        median = cell.median_time
        if median is not None:
            series[f"{cell.adapter}:{cell.label}"].append(median)
    return {name: sorted(times) for name, times in sorted(series.items())}


def scaling(
    rows: list[RunRecord],
    x_key: str = "n_agents",
) -> dict[str, tuple[list[float], list[float], list[float], list[float]]]:
    """MAPF scaling curves: ``{label: (xs, medians, mins, maxs)}``.

    ``x_key`` is read out of the instance id (``.../n16/...``), which keeps
    this function independent of any adapter's payload shape.
    """
    # Each bucket holds one (median, min, max) triple per contributing cell.
    # The band must be the min and max actually *observed* across seeds, not
    # the spread of per-cell medians — medians of medians would shrink the band
    # towards the centre and understate the variance the reader is being shown.
    buckets: dict[str, dict[float, list[tuple[float, float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    token = x_key_token(x_key)
    for cell in cells(rows):
        if not cell.solved_all_seeds:
            continue
        x = parse_token(cell.instance, token)
        median, low, high = cell.stat("wall_time_s")
        if x is None or median is None:
            continue
        buckets[f"{cell.adapter}:{cell.label}"][x].append((median, low, high))

    out: dict[str, tuple[list[float], list[float], list[float], list[float]]] = {}
    for label, by_x in sorted(buckets.items()):
        xs = sorted(by_x)
        out[label] = (
            xs,
            [statistics.median([t[0] for t in by_x[x]]) for x in xs],
            [min(t[1] for t in by_x[x]) for x in xs],
            [max(t[2] for t in by_x[x]) for x in xs],
        )
    return out


def x_key_token(x_key: str) -> str:
    return {"n_agents": "n", "grid": "x", "density": "d"}.get(x_key, "n")


def parse_token(instance_id: str, token: str) -> float | None:
    """Pull ``n16`` / ``d0.15`` out of a generated instance id."""
    for part in instance_id.split("/"):
        if part.startswith(token) and part != token:
            try:
                return float(part[len(token) :])
            except ValueError:
                return None
    return None


def timeout_points(rows: list[RunRecord], x_key: str = "n_agents") -> dict:
    """``{label: [(x, budget), ...]}`` for cells that ran out of budget.

    Charts draw these as hollow marks at the cap so a curve that simply stops
    is visibly distinguishable from one that was never measured.
    """
    token = x_key_token(x_key)
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for cell in cells(rows):
        if cell.solved_all_seeds:
            continue
        if not any(r.outcome in ("timeout", "memory") for r in cell.rows):
            continue
        x = parse_token(cell.instance, token)
        if x is None:
            continue
        budget = max((r.timeout_s for r in cell.rows), default=0.0)
        out[f"{cell.adapter}:{cell.label}"].append((x, budget))
    return {label: sorted(points) for label, points in sorted(out.items())}


def outcome_counts(rows: list[RunRecord]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.outcome] += 1
    return dict(sorted(counts.items()))


def quality_pairs(
    rows: list[RunRecord], left: str, right: str, metric: str = "sum_of_costs"
) -> list[tuple[float, float]]:
    """Paired ``metric`` values on instances *both* configurations solved.

    Comparing solution quality over each configuration's own solved set
    compares two different problem sets and flatters whichever one gave up on
    the hard instances.
    """
    by_key: dict[str, dict[str, float]] = defaultdict(dict)
    for cell in cells(rows):
        if not cell.solved_all_seeds:
            continue
        name = f"{cell.adapter}:{cell.label}"
        if name not in (left, right):
            continue
        median, _, _ = cell.stat(metric)
        if median is not None:
            by_key[cell.instance][name] = median
    return [
        (values[left], values[right])
        for values in by_key.values()
        if left in values and right in values
    ]
