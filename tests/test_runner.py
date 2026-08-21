"""The harness invariant: every requested run produces exactly one row.

These tests use the fake adapter, so they are fast, deterministic, and do not
need a planner installed. The behaviours worth defending are all failure
behaviours — anyone can write a harness that records a success.
"""

from __future__ import annotations

import textwrap

import pytest

from openplan_bench import runner
from openplan_bench.adapters import get_adapter
from openplan_bench.runner import plan_group, run_suite, save
from openplan_bench.suite import SuiteError, load_suite


def write_suite(tmp_path, body: str):
    path = tmp_path / "suite.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return load_suite(path)


BASIC = """
    name: unit
    title: Unit suite
    seeds: [0, 1, 2]
    repetitions: 1
    timeout_s: 20
    groups:
      - adapter: fake
        instances:
          - id: alpha
          - id: beta
        planners:
          - planner: p1
          - planner: p2
            heuristic: h
"""


def test_every_requested_run_produces_one_row(tmp_path):
    suite = write_suite(tmp_path, BASIC)
    rows = run_suite(suite)
    # 2 instances x 2 configurations x 3 seeds
    assert len(rows) == 12
    assert all(row.outcome == "solved" for row in rows)
    assert all(row.suite == "unit" for row in rows)
    assert {row.seed for row in rows} == {0, 1, 2}


def test_rows_carry_provenance(tmp_path):
    suite = write_suite(tmp_path, BASIC)
    row = run_suite(suite)[0]
    assert row.timestamp_utc
    assert row.python_version
    assert row.cpu_model
    assert row.harness_version
    assert row.harness_sha  # "unknown" outside a checkout, but never empty
    assert "openplan-bench" in row.package_versions
    assert row.wall_time_s > 0


def test_each_row_is_stamped_when_it_is_produced(tmp_path):
    """The schema advertises a per-row timestamp, so record one.

    Collecting one stamp at the start of the run and copying it onto every row
    — which is what schema 2 did — makes a results file claim provenance it
    does not carry. The stamps must be non-decreasing in the order the rows
    were measured.
    """
    suite = write_suite(
        tmp_path,
        """
        name: stamped
        seeds: [0]
        repetitions: 4
        groups:
          - adapter: fake
            instances: [{id: a}, {id: b}]
            planners: [{planner: p}]
        """,
    )
    rows = run_suite(suite)
    stamps = [row.timestamp_utc for row in rows]
    assert all(stamps)
    assert stamps == sorted(stamps)
    from openplan_bench.records import SCHEMA_VERSION

    assert all(row.schema_version == SCHEMA_VERSION for row in rows)
    assert SCHEMA_VERSION >= 3


def test_repetitions_are_recorded_separately(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: reps
        seeds: [0]
        repetitions: 4
        groups:
          - adapter: fake
            instances: [{id: only}]
            planners: [{planner: p}]
        """,
    )
    rows = run_suite(suite)
    assert len(rows) == 4
    assert sorted(row.repetition for row in rows) == [0, 1, 2, 3]


def test_a_raising_adapter_becomes_an_error_row(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: boom
        seeds: [0]
        groups:
          - adapter: fake
            instances: [{id: bad, payload: {behaviour: raise}}]
            planners: [{planner: p}]
        """,
    )
    rows = run_suite(suite)
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert "asked to fail" in rows[0].error


def test_a_hanging_run_becomes_a_timeout_row_carrying_budget_and_elapsed(tmp_path):
    """The row must exist, say 'timeout', and keep the budget and the elapsed
    time in separate columns.

    ``timeout_s`` is the budget the run was given; ``wall_time_s`` is measured,
    and on a killed run it is the elapsed time at the kill — past the budget by
    the grace period. Neither is a guess at how long a solution would have
    taken, and the two must not be conflated into one column.
    """
    suite = write_suite(
        tmp_path,
        """
        name: slow
        seeds: [0]
        timeout_s: 1
        groups:
          - adapter: fake
            instances: [{id: slow}]
            planners:
              - planner: p
                options: {behaviour: hang, sleep: 90}
        """,
    )
    rows = run_suite(suite)
    assert len(rows) == 1
    assert rows[0].outcome == "timeout"
    assert rows[0].solved is False
    assert rows[0].timeout_s == pytest.approx(1.0)
    # Measured, and past the budget: the child was killed at budget + grace.
    assert rows[0].wall_time_s >= 1.0
    assert rows[0].wall_time_s == pytest.approx(1.0 + runner.GRACE_S, abs=5.0)
    assert "grace" in rows[0].note


def test_unsolved_is_not_an_error(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: nosol
        seeds: [0]
        groups:
          - adapter: fake
            instances: [{id: x, payload: {behaviour: unsolved}}]
            planners: [{planner: p}]
        """,
    )
    row = run_suite(suite)[0]
    assert row.outcome == "unsolved"
    assert row.error == ""


def test_memory_guard_produces_a_memory_row(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: hog
        seeds: [0]
        timeout_s: 30
        memory_limit_mb: 200
        groups:
          - adapter: fake
            instances: [{id: hog}]
            planners:
              - planner: p
                options: {behaviour: hog, bytes: 1073741824}
        """,
    )
    row = run_suite(suite)[0]
    assert row.outcome == "memory"
    assert row.solved is False


def test_missing_backend_is_reported_not_raised(tmp_path, monkeypatch):
    """A planner nobody installed must still produce a row per requested run."""
    adapter = get_adapter("fake")
    monkeypatch.setattr(
        type(adapter), "available", lambda self: (False, "pip install something")
    )
    suite = write_suite(tmp_path, BASIC)
    rows = run_suite(suite)
    assert len(rows) == 12
    assert all(row.outcome == "not-installed" for row in rows)
    assert all("pip install something" in row.note for row in rows)


def test_plan_group_is_deterministic(tmp_path):
    suite = write_suite(tmp_path, BASIC)
    adapter = get_adapter("fake")
    first = [j.describe() for j in plan_group(suite, suite.groups[0], adapter)]
    second = [j.describe() for j in plan_group(suite, suite.groups[0], adapter)]
    assert first == second


def test_save_never_overwrites_history(tmp_path):
    suite = write_suite(tmp_path, BASIC)
    rows = run_suite(suite)
    first, _ = save(rows, suite, tmp_path / "results")
    second, latest = save(rows, suite, tmp_path / "results")
    assert first != second
    assert first.exists() and second.exists()
    assert latest.name == "latest.json"


def test_unknown_adapter_does_not_kill_the_run(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: mixed
        seeds: [0]
        groups:
          - adapter: no-such-planner
            instances: [{id: x}]
            planners: [{planner: p}]
          - adapter: fake
            instances: [{id: y}]
            planners: [{planner: p}]
        """,
    )
    rows = run_suite(suite)
    assert len(rows) == 1
    assert rows[0].instance == "y"


# --- suite validation ------------------------------------------------------
def test_typo_in_a_top_level_key_is_rejected(tmp_path):
    with pytest.raises(SuiteError, match="unknown top-level key"):
        write_suite(
            tmp_path,
            """
            name: typo
            timout_s: 10
            groups:
              - adapter: fake
                instances: [{id: x}]
                planners: [{planner: p}]
            """,
        )


def test_suite_requires_a_name_and_groups(tmp_path):
    with pytest.raises(SuiteError, match="'name' is required"):
        write_suite(tmp_path, "groups: [{adapter: fake}]")
    with pytest.raises(SuiteError, match="groups"):
        write_suite(tmp_path, "name: empty")


def test_group_overrides_beat_suite_defaults(tmp_path):
    suite = write_suite(
        tmp_path,
        """
        name: override
        seeds: [0, 1, 2]
        timeout_s: 60
        groups:
          - adapter: fake
            seeds: [7]
            timeout_s: 5
            instances: [{id: x}]
            planners: [{planner: p}]
        """,
    )
    group = suite.groups[0]
    assert suite.seeds_for(group) == [7]
    assert suite.timeout_for(group) == 5.0
    rows = run_suite(suite)
    assert len(rows) == 1 and rows[0].seed == 7


def test_corpus_root_resolves_against_the_suite_file(tmp_path):
    nested = tmp_path / "suites"
    nested.mkdir()
    path = nested / "s.yaml"
    path.write_text(
        textwrap.dedent(
            """
            name: rooted
            groups:
              - adapter: fake
                corpus_root: ../corpus
                instances: [{id: x}]
                planners: [{planner: p}]
            """
        ),
        encoding="utf-8",
    )
    suite = load_suite(path)
    assert suite.groups[0].spec["corpus_root"] == str(tmp_path / "corpus")
