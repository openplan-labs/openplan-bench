"""Multi-agent path finding through ``pymapf``.

The instance comes from :mod:`openplan_bench.mapfgen`, not from
``pymapf.scenarios``, so that the ``cuplan`` adapter can be handed the very
same grid, starts and goals. Comparing sum-of-costs across two libraries is
only meaningful when both solved the identical instance.

``pymapf`` solvers take different constructor keywords (``time_limit`` exists
on CBS, not on prioritized planning), so unsupported options are dropped
rather than raised on — one suite file configures every algorithm.
"""

from __future__ import annotations

import inspect
from typing import Any

from ..mapfgen import feasible, instance_id, random_grid_instance
from ..records import Instance, RunRecord
from .base import Adapter, RunConfig, missing


def grid_instances(spec: dict[str, Any], builder: str = "random_obstacles") -> list:
    """Expand a MAPF sweep block into instances.

    The block is a cross product::

        grid_sizes: [12, 16]
        agent_counts: [4, 8, 16]
        densities: [0.1, 0.2]

    Cells that cannot physically hold their agents are dropped here rather than
    failing later — but every cell that *is* generated is run, so an absent row
    always means "not requested", never "it went wrong".
    """
    out: list[Instance] = []
    sizes = spec.get("grid_sizes", [16]) or [16]
    counts = spec.get("agent_counts", [4]) or [4]
    densities = spec.get("densities", [0.15]) or [0.15]
    for size in sizes:
        height = width = int(size)
        for n_agents in counts:
            for density in densities:
                if not feasible(height, width, int(n_agents), float(density)):
                    continue
                out.append(
                    Instance(
                        id=instance_id(
                            builder, height, width, int(n_agents), float(density)
                        ),
                        group=f"{builder}/d{float(density):g}",
                        payload={
                            "height": height,
                            "width": width,
                            "n_agents": int(n_agents),
                            "density": float(density),
                        },
                    )
                )
    return out


def _supported(algorithm: str, options: dict[str, Any]) -> dict[str, Any]:
    """Drop constructor keywords a given ``pymapf`` solver does not accept."""
    from pymapf.core.solver import _REGISTRY

    cls = _REGISTRY.get(algorithm.lower())
    if cls is None:
        return dict(options)
    accepted = inspect.signature(cls.__init__).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in accepted.values()):
        return dict(options)
    return {key: value for key, value in options.items() if key in accepted}


class PymapfAdapter(Adapter):
    name = "pymapf"
    family = "mapf"
    requires = ("pymapf",)

    def available(self) -> tuple[bool, str]:
        ok, reason = missing(self.requires)
        if ok:
            return True, ""
        return False, f"{reason}. Install with: pip install 'openplan-bench[mapf]'"

    def instances(self, spec: dict[str, Any]) -> list[Instance]:
        return grid_instances(spec)

    # ------------------------------------------------------------------
    def run(
        self,
        instance: Instance,
        config: RunConfig,
        *,
        seed: int = 0,
        timeout_s: float = 60.0,
    ) -> RunRecord:
        from pymapf.core.grid import GridMap
        from pymapf.core.solver import Agent, MAPFProblem, get_solver

        record = self.blank(instance, config, seed=seed, timeout_s=timeout_s)
        spec = random_grid_instance(seed=seed, **instance.payload)

        pairs = zip(spec["starts"], spec["goals"], strict=True)
        agents = [
            Agent(f"a{i}", tuple(start), tuple(goal))
            for i, (start, goal) in enumerate(pairs)
        ]
        problem = MAPFProblem(grid=GridMap(spec["occupancy"]), agents=agents)

        options = dict(config.options)
        # Give the solver our budget when it has a knob for it: a solver that
        # returns cleanly reports far better statistics than one we SIGALRM.
        options.setdefault("time_limit", timeout_s)
        solver = get_solver(config.planner, **_supported(config.planner, options))

        elapsed = self.timer()
        solution = solver.solve(problem)
        record.wall_time_s = elapsed()

        if solution is None:
            record.outcome = "unsolved"
            record.note = "solver returned no solution"
            return record

        record.outcome = "solved"
        record.solved = True
        # Validity is the solver-independent conflict check, not a self-report.
        record.valid = bool(solution.is_valid())
        record.sum_of_costs = solution.sum_of_costs
        record.cost = float(solution.sum_of_costs)
        record.makespan = solution.makespan
        record.expanded = getattr(solution, "expansions", None)
        if not record.valid:
            record.note = "returned paths contain a conflict"
        return record
