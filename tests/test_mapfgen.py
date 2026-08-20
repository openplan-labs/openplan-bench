"""The shared MAPF generator. Determinism here is what makes the MAPF table a
comparison rather than two unrelated columns."""

from __future__ import annotations

import pytest

from openplan_bench.mapfgen import (
    GenerationError,
    _largest_component,
    feasible,
    instance_id,
    random_grid_instance,
)


def test_same_seed_gives_a_byte_identical_instance():
    a = random_grid_instance(12, 12, 4, 0.15, seed=7)
    b = random_grid_instance(12, 12, 4, 0.15, seed=7)
    assert a == b


def test_different_seeds_give_different_instances():
    a = random_grid_instance(12, 12, 4, 0.15, seed=0)
    b = random_grid_instance(12, 12, 4, 0.15, seed=1)
    assert a["occupancy"] != b["occupancy"] or a["starts"] != b["starts"]


def test_border_is_solid_and_agents_are_on_free_cells():
    spec = random_grid_instance(10, 14, 5, 0.2, seed=3)
    grid = spec["occupancy"]
    assert all(cell == 1 for cell in grid[0])
    assert all(cell == 1 for cell in grid[-1])
    assert all(rowdata[0] == 1 and rowdata[-1] == 1 for rowdata in grid)
    for row, col in spec["starts"] + spec["goals"]:
        assert grid[row][col] == 0


def test_starts_and_goals_are_distinct_and_mutually_reachable():
    spec = random_grid_instance(14, 14, 6, 0.18, seed=5)
    cells = [tuple(c) for c in spec["starts"] + spec["goals"]]
    assert len(set(cells)) == len(cells)
    component = set(_largest_component(spec["occupancy"]))
    assert all(cell in component for cell in cells)


def test_impossible_request_raises_rather_than_shrinking():
    """Silently placing fewer agents would mislabel every row that followed."""
    with pytest.raises(GenerationError):
        random_grid_instance(5, 5, 40, 0.1, seed=0, attempts=4)


def test_bad_parameters_are_rejected():
    with pytest.raises(ValueError):
        random_grid_instance(10, 10, 2, density=0.95)
    with pytest.raises(ValueError):
        random_grid_instance(10, 10, 0, 0.1)
    with pytest.raises(ValueError):
        random_grid_instance(2, 2, 1, 0.1)


def test_feasibility_precheck():
    assert feasible(20, 20, 8, 0.15)
    assert not feasible(6, 6, 40, 0.15)


def test_instance_id_is_stable_and_parseable():
    from openplan_bench.aggregate import parse_token

    ident = instance_id("random_obstacles", 16, 16, 8, 0.15)
    assert ident == "random_obstacles/16x16/n8/d0.15"
    assert parse_token(ident, "n") == 8.0
    assert parse_token(ident, "d") == 0.15
