"""openplan-bench — one harness for every planner in OpenPlan Labs.

Runs the org's planners over shared problem sets, records every run with full
provenance, and publishes the result as a leaderboard. Planners not included:
they are optional extras (``[pddl]``, ``[mapf]``, ``[cuda]``), and an adapter
whose backend is absent reports that as a row rather than crashing.

    from openplan_bench.suite import load_suite
    from openplan_bench.runner import run_suite, save

    suite = load_suite("suites/classical-smoke.yaml")
    rows = run_suite(suite)
    save(rows, suite, "results/")
"""

from __future__ import annotations

__all__ = ["__version__", "records", "suite", "runner", "aggregate"]

__version__ = "0.1.0"
