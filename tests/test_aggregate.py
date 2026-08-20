"""Aggregation rules — the ones that decide what the leaderboard claims."""

from __future__ import annotations

import pytest

from openplan_bench import aggregate
from openplan_bench.records import RunRecord


def row(instance, planner, outcome="solved", t=1.0, seed=0, **kwargs):
    return RunRecord(
        adapter="fake",
        family="classical",
        instance=instance,
        planner=planner,
        outcome=outcome,
        solved=outcome == "solved",
        valid=kwargs.pop("valid", outcome == "solved"),
        wall_time_s=t,
        seed=seed,
        timeout_s=kwargs.pop("timeout_s", 30.0),
        **kwargs,
    )


def test_median_over_seeds_with_min_max_band():
    rows = [
        row("i1", "p", t=1.0, seed=0),
        row("i1", "p", t=5.0, seed=1),
        row("i1", "p", t=2.0, seed=2),
    ]
    cell = aggregate.cells(rows)[0]
    median, low, high = cell.stat("wall_time_s")
    assert median == 2.0  # not the mean, which the outlier would drag to 2.67
    assert (low, high) == (1.0, 5.0)


def test_an_instance_counts_as_solved_only_when_every_seed_solved_it():
    rows = [
        row("i1", "p", seed=0),
        row("i1", "p", outcome="timeout", seed=1),
        row("i1", "p", seed=2),
    ]
    summary = aggregate.summarize(rows)[0]
    assert summary.solved == 0
    assert summary.timeouts == 1
    assert summary.instances == 1
    assert summary.coverage == 0.0


def test_timing_ignores_timeouts():
    """A timeout's budget must not be averaged into a runtime."""
    rows = [
        row("i1", "p", t=1.0),
        row("i2", "p", outcome="timeout", t=30.0),
    ]
    summary = aggregate.summarize(rows)[0]
    assert summary.median_time == 1.0
    assert summary.total_time_solved == 1.0


def test_runs_that_never_happened_are_not_failures():
    rows = [
        row("i1", "p"),
        row("i2", "p", outcome="not-installed"),
        row("i3", "p", outcome="skipped"),
    ]
    summary = aggregate.summarize(rows)[0]
    assert summary.instances == 1  # only the one that actually competed
    assert summary.solved == 1
    assert summary.not_run == 2
    assert summary.coverage == 1.0


def test_an_invalid_plan_does_not_count_as_solved():
    rows = [row("i1", "p", valid=False)]
    summary = aggregate.summarize(rows)[0]
    assert summary.solved == 0
    assert summary.invalid == 1
    assert summary.coverage == 0.0


def test_cactus_series_are_sorted_ascending():
    rows = [
        row("i1", "p", t=3.0),
        row("i2", "p", t=1.0),
        row("i3", "p", t=2.0),
        row("i4", "p", outcome="timeout", t=30.0),
    ]
    series = aggregate.cactus(rows)
    assert series["fake:p"] == [1.0, 2.0, 3.0]  # the timeout contributes nothing


def test_scaling_reads_the_agent_count_out_of_the_instance_id():
    rows = [
        row("random_obstacles/16x16/n4/d0.15", "cbs", t=0.1, seed=0),
        row("random_obstacles/16x16/n4/d0.15", "cbs", t=0.3, seed=1),
        row("random_obstacles/16x16/n8/d0.15", "cbs", t=1.0, seed=0),
        row("random_obstacles/16x16/n8/d0.15", "cbs", t=1.0, seed=1),
    ]
    xs, medians, lows, highs = aggregate.scaling(rows)["fake:cbs"]
    assert xs == [4.0, 8.0]
    assert medians == [pytest.approx(0.2), 1.0]
    assert lows == [0.1, 1.0]
    assert highs == [0.3, 1.0]


def test_timeout_points_mark_the_budget():
    rows = [
        row("g/16x16/n32/d0.15", "cbs", outcome="timeout", t=20.0, timeout_s=20.0),
    ]
    points = aggregate.timeout_points(rows)
    assert points["fake:cbs"] == [(32.0, 20.0)]


def test_quality_pairs_use_only_shared_instances():
    rows = [
        row("i1", "a", sum_of_costs=10, cost=10.0),
        row("i1", "b", sum_of_costs=12, cost=12.0),
        row("i2", "a", sum_of_costs=20, cost=20.0),  # b never solved i2
    ]
    pairs = aggregate.quality_pairs(rows, "fake:a", "fake:b", metric="sum_of_costs")
    assert pairs == [(10.0, 12.0)]


def test_cell_status_words():
    assert aggregate.cells([row("i", "p")])[0].status == "solved"
    assert aggregate.cells([row("i", "p", outcome="timeout")])[0].status == "timeout"
    mixed = aggregate.cells(
        [row("i", "p", seed=0), row("i", "p", outcome="timeout", seed=1)]
    )[0]
    assert mixed.status.startswith("partial")
    assert (
        aggregate.cells([row("i", "p", outcome="not-installed")])[0].status
        == "not-installed"
    )


def test_outcome_counts_covers_everything():
    rows = [row("i1", "p"), row("i2", "p", outcome="timeout")]
    assert aggregate.outcome_counts(rows) == {"solved": 1, "timeout": 1}


def test_empty_input_is_not_an_error():
    assert aggregate.summarize([]) == []
    assert aggregate.cactus([]) == {}
    assert aggregate.scaling([]) == {}


def test_a_configuration_that_never_ran_has_no_coverage():
    """Not "a coverage of zero" — printing 0% would claim it solved nothing."""
    rows = [row("i1", "p", outcome="not-installed")]
    summary = aggregate.summarize(rows)[0]
    assert summary.was_run is False
    assert summary.not_run == 1
    assert summary.instances == 0


def test_a_configuration_that_ran_and_failed_does_have_coverage():
    rows = [row("i1", "p", outcome="timeout")]
    summary = aggregate.summarize(rows)[0]
    assert summary.was_run is True
    assert summary.coverage == 0.0
