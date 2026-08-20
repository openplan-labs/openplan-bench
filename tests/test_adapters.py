"""The adapter contract, and the degradations it promises."""

from __future__ import annotations

import pytest

from openplan_bench.adapters import Adapter, available_adapters, get_adapter, register
from openplan_bench.adapters.base import RunConfig
from openplan_bench.records import Instance


def test_every_registered_adapter_answers_available_without_raising():
    """Importing the registry must not import a single planner."""
    for name in available_adapters():
        adapter = get_adapter(name)
        usable, reason = adapter.available()
        assert isinstance(usable, bool)
        assert usable or reason, f"{name} must explain why it cannot run"
        assert adapter.family


def test_a_missing_backend_names_the_install_command():
    from openplan_bench.adapters.cuplan_adapter import CuplanAdapter

    usable, reason = CuplanAdapter().available()
    if not usable:
        assert "install" in reason.lower()


def test_unknown_adapter_names_the_alternatives():
    with pytest.raises(ValueError, match="Available:"):
        get_adapter("definitely-not-a-planner")


def test_out_of_tree_adapters_can_register():
    class Mine(Adapter):
        name = "mine"
        family = "custom"

        def available(self):
            return True, ""

        def instances(self, spec):
            return []

    register("mine", Mine)
    assert "mine" in available_adapters()
    assert isinstance(get_adapter("mine"), Mine)


def test_config_parsing_accepts_bare_names_and_mappings():
    adapter = get_adapter("fake")
    configs = adapter.configs(
        {
            "planners": [
                "bare",
                {"planner": "full", "heuristic": "h", "options": {"w": 2}},
            ]
        }
    )
    assert configs[0] == RunConfig(planner="bare", heuristic="", options={})
    assert configs[1].options == {"w": 2}
    assert configs[1].label == "full/h"


def test_blank_record_carries_the_identifying_columns():
    adapter = get_adapter("fake")
    record = adapter.blank(
        Instance(id="i", group="g"),
        RunConfig(planner="p", heuristic="h", options={"w": 2}),
        seed=5,
    )
    assert record.adapter == "fake"
    assert (record.instance, record.instance_group) == ("i", "g")
    assert record.planner == "p" and record.heuristic == "h"
    assert record.config == '{"w": 2}'
    assert record.seed == 5
    assert record.outcome == "error"  # nothing is a success until it is measured


# --- CUDA gating -----------------------------------------------------------
def test_cuda_is_skipped_cleanly_when_forced_off(monkeypatch):
    from openplan_bench.adapters.cuplan_adapter import CuplanAdapter, cuda_usable

    monkeypatch.setenv("CUPLAN_FORCE_CPU", "1")
    ok, reason = cuda_usable()
    assert ok is False
    assert "CUPLAN_FORCE_CPU" in reason

    adapter = CuplanAdapter()
    cuda = RunConfig(planner="pibt", options={"backend": "cuda"})
    cpu = RunConfig(planner="pibt", options={"backend": "cpu"})
    assert adapter.skip_reason(cuda)
    assert adapter.skip_reason(cpu) == ""


def test_cuda_absence_is_a_skip_row_not_a_failure(tmp_path, monkeypatch):
    """The whole point: no GPU means a row saying so."""
    import textwrap

    from openplan_bench.runner import run_suite
    from openplan_bench.suite import load_suite

    monkeypatch.setenv("CUPLAN_FORCE_CPU", "1")
    path = tmp_path / "s.yaml"
    path.write_text(
        textwrap.dedent(
            """
            name: gpu
            seeds: [0]
            groups:
              - adapter: cuplan
                grid_sizes: [8]
                agent_counts: [2]
                densities: [0.1]
                planners:
                  - planner: pibt
                    options: {backend: cuda}
            """
        ),
        encoding="utf-8",
    )
    rows = run_suite(load_suite(path))
    assert len(rows) == 1
    assert rows[0].outcome in ("skipped", "not-installed")
    assert rows[0].note


# --- jupyddl instance expansion (no planner needed) ------------------------
def test_jupyddl_expands_one_domain_over_many_problems(tmp_path):
    from openplan_bench.adapters.jupyddl_adapter import JupyddlAdapter

    instances = JupyddlAdapter().instances(
        {
            "corpus_root": str(tmp_path),
            "instances": [
                {"dir": "blocksworld"},
                {
                    "dir": "domains/miconic",
                    "group": "miconic",
                    "problems": ["s1-0.pddl", "s1-1.pddl"],
                },
            ],
        }
    )
    assert [i.id for i in instances] == [
        "blocksworld/problem",
        "miconic/s1-0",
        "miconic/s1-1",
    ]
    assert instances[1].payload["domain"].endswith("domains/miconic/domain.pddl")
    assert instances[1].payload["problem"].endswith("s1-0.pddl")


def test_jupyddl_defaults_a_heuristic_onto_informed_planners():
    from openplan_bench.adapters.jupyddl_adapter import JupyddlAdapter

    configs = JupyddlAdapter().configs(
        {
            "default_heuristic": "lmcut",
            "planners": [{"planner": "astar"}, {"planner": "bfs"}],
        }
    )
    assert configs[0].heuristic == "lmcut"  # recorded, not left implicit
    assert configs[1].heuristic == ""


def test_mapf_instance_expansion_drops_infeasible_cells():
    from openplan_bench.adapters.pymapf_adapter import PymapfAdapter

    instances = PymapfAdapter().instances(
        {"grid_sizes": [6], "agent_counts": [2, 500], "densities": [0.1]}
    )
    assert len(instances) == 1
    assert instances[0].id == "random_obstacles/6x6/n2/d0.1"


# --- "gave up" is not "no solution" ----------------------------------------
def test_a_solver_stopping_on_its_own_budget_is_a_timeout():
    """The distinction the whole project exists to preserve.

    pymapf returns a bare ``None`` whether its constraint tree was exhausted or
    its time limit expired. Recording the second as ``unsolved`` would claim
    the solver proved something it never looked at.
    """
    from openplan_bench.adapters.pymapf_adapter import _is_budget_failure

    assert _is_budget_failure("time limit (20s) reached after 811 nodes", 20.0, 20.0)
    assert _is_budget_failure("expansion limit (10000) reached", 0.4, 20.0)
    assert not _is_budget_failure("constraint tree exhausted", 0.004, 20.0)


def test_a_silent_failure_that_ate_the_budget_is_still_a_timeout():
    from openplan_bench.adapters.pymapf_adapter import _is_budget_failure

    assert _is_budget_failure("", 19.9, 20.0)
    assert not _is_budget_failure("", 0.01, 20.0)


def test_the_cuplan_backend_becomes_part_of_the_configuration_label():
    """cpu and cuda are two leaderboard rows, not two samples of one.

    If the backend stayed buried in the options dict the two would share a
    label and the aggregation would take a median across both, reporting a
    number that describes neither.
    """
    from openplan_bench.adapters.cuplan_adapter import CuplanAdapter

    configs = CuplanAdapter().configs(
        {
            "planners": [
                {"planner": "pibt", "options": {"backend": "cpu"}},
                {"planner": "pibt", "options": {"backend": "cuda"}},
                {"planner": "prioritized"},
            ]
        }
    )
    assert [c.label for c in configs] == ["pibt@cpu", "pibt@cuda", "prioritized@cpu"]
    assert len({c.label for c in configs}) == 3


def test_variant_survives_the_subprocess_boundary(tmp_path):
    """The label is only useful if the child sends it back."""
    import textwrap

    from openplan_bench.runner import run_suite
    from openplan_bench.suite import load_suite

    path = tmp_path / "s.yaml"
    path.write_text(
        textwrap.dedent(
            """
            name: variants
            seeds: [0]
            groups:
              - adapter: fake
                instances: [{id: x}]
                planners:
                  - planner: p
                    variant: alpha
                  - planner: p
                    variant: beta
            """
        ),
        encoding="utf-8",
    )
    rows = run_suite(load_suite(path))
    assert sorted(r.label for r in rows) == ["p@alpha", "p@beta"]
    assert sorted(r.variant for r in rows) == ["alpha", "beta"]
