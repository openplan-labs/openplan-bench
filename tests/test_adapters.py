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
