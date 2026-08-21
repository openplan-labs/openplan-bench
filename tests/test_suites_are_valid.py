"""Every shipped suite must parse, name real adapters, and plan real jobs.

A suite file that is broken is only discovered when someone waits ten minutes
for a benchmark that produces nothing. These tests cost milliseconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openplan_bench.adapters import available_adapters, get_adapter
from openplan_bench.runner import plan_group
from openplan_bench.suite import discover_suites, load_suite

SUITES = discover_suites(Path(__file__).resolve().parent.parent / "suites")


def test_there_are_suites_to_run():
    assert SUITES, "suites/ must contain at least one suite"


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.stem)
def test_suite_parses_and_plans(path):
    suite = load_suite(path)
    assert suite.name == path.stem, "suite name must match its filename"
    assert suite.title and suite.description
    assert suite.timeout_s > 0
    assert suite.memory_limit_mb > 0

    total = 0
    for group in suite.groups:
        assert group.adapter in available_adapters()
        adapter = get_adapter(group.adapter)
        jobs = plan_group(suite, group, adapter)
        assert jobs, f"{path.name}: group '{group.adapter}' plans no runs"
        total += len(jobs)
    assert total > 0


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.stem)
def test_seeded_suites_use_at_least_three_seeds(path):
    """Anything with real variance needs enough seeds for a median to mean something.

    Classical planning is deterministic, so those suites legitimately use one
    seed and repeat the timing instead; MAPF instances differ per seed and must
    sweep at least three.
    """
    suite = load_suite(path)
    for group in suite.groups:
        if get_adapter(group.adapter).family != "mapf":
            continue
        assert len(suite.seeds_for(group)) >= 3, (
            f"{path.name}: MAPF group '{group.adapter}' uses "
            f"{len(suite.seeds_for(group))} seed(s)"
        )


#: Classical groups that take exactly one sample per cell, so their median,
#: minimum and maximum are one number printed three times. Both are recorded
#: under "Known limitations" in the README and both put a single-sample note
#: above their table on the dashboard.
SINGLE_SAMPLE_CLASSICAL = {"classical-coverage", "ci-weekly"}


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.stem)
def test_classical_timing_samples_are_declared(path):
    """A classical group takes seeds x repetitions samples of each cell.

    This used to assert ``samples >= 1``, which every possible suite satisfies
    — a test whose name claimed a repetition rule it did not check. What is
    worth pinning is *which* suites take a single sample, because that is the
    thing the dashboard has to caption and the README has to list. Adding a
    third quietly should fail here.
    """
    suite = load_suite(path)
    for group in suite.groups:
        if get_adapter(group.adapter).family != "classical":
            continue
        samples = len(suite.seeds_for(group)) * suite.repetitions_for(group)
        assert samples >= 1
        if samples == 1:
            assert suite.name in SINGLE_SAMPLE_CLASSICAL, (
                f"{path.name}: a classical group takes one sample per cell, so "
                "its median is not a median. Either raise 'repetitions', or add "
                "the suite to SINGLE_SAMPLE_CLASSICAL and to the README's known "
                "limitations."
            )


def test_the_ci_suite_is_labelled_runner_grade():
    """Times from a shared runner must never be presented as a hardware result."""
    suite = load_suite(Path(__file__).resolve().parent.parent / "suites/ci-weekly.yaml")
    assert suite.runner_grade is True


def test_no_suite_silently_omits_a_timeout():
    for path in SUITES:
        suite = load_suite(path)
        assert suite.timeout_s <= 120, (
            f"{path.name}: a budget above two minutes makes the suite unusable in CI"
        )
