"""Classical PDDL planning through ``jupyddl`` (the PythonPDDL distribution).

``jupyddl`` ships its own benchmark module; this adapter deliberately does not
use it. That module loops over instances and configurations itself, which is
exactly the part the harness owns — the timeout policy, the repetition policy
and the provenance stamp have to be identical across families or the
leaderboard is comparing two different experiments. So we call one level down,
at ``jupyddl.api``: ``build_task`` / ``solve_task`` / ``validate_plan``.

Validity is checked by replaying the plan through the task rather than trusting
``result.solved``. A planner that returns a plan the validator rejects is a
much more interesting row than a missing one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..records import Instance, RunRecord
from .base import Adapter, RunConfig, missing

#: Planners that will not run without a heuristic. Kept as a fallback for when
#: ``jupyddl.search`` cannot be imported; the live registry wins when present.
_INFORMED_FALLBACK = (
    "gbfs",
    "astar",
    "wastar",
    "idastar",
    "ehc",
    "hc",
    "beam",
    "bnb",
    "awastar",
)


class JupyddlAdapter(Adapter):
    name = "jupyddl"
    family = "classical"
    requires = ("jupyddl",)

    def available(self) -> tuple[bool, str]:
        ok, reason = missing(self.requires)
        if ok:
            return True, ""
        return False, f"{reason}. Install with: pip install 'openplan-bench[pddl]'"

    # ------------------------------------------------------------------
    def instances(self, spec: dict[str, Any]) -> list[Instance]:
        """Expand the suite's instance block into domain/problem file pairs.

        Two shapes are accepted, because the corpus has two shapes. A folder
        holding ``domain.pddl`` + ``problem.pddl`` is named by ``dir``; a
        folder holding one ``domain.pddl`` and many problem files names the
        problems explicitly with ``problems``.
        """
        root = Path(spec.get("corpus_root", ".")).expanduser()
        out: list[Instance] = []
        for entry in spec.get("instances", []) or []:
            if isinstance(entry, str):
                entry = {"dir": entry}
            folder = root / str(entry["dir"])
            domain = folder / str(entry.get("domain", "domain.pddl"))
            group = str(entry.get("group") or folder.name)
            problems = entry.get("problems") or [entry.get("problem", "problem.pddl")]
            for problem_name in problems:
                problem = folder / str(problem_name)
                stem = Path(str(problem_name)).stem
                ident = str(entry.get("id") or f"{group}/{stem}")
                out.append(
                    Instance(
                        id=ident,
                        group=group,
                        payload={"domain": str(domain), "problem": str(problem)},
                    )
                )
        return out

    def configs(self, spec: dict[str, Any]) -> list[RunConfig]:
        """As the base class, but default a heuristic onto informed planners.

        Writing ``- planner: astar`` in a suite and silently getting whatever
        ``jupyddl`` picks would make the results file lie about what ran, so
        the default is resolved here and recorded in the ``heuristic`` column.
        """
        default = str(spec.get("default_heuristic", "hff"))
        informed = self._informed()
        out: list[RunConfig] = []
        for config in super().configs(spec):
            if not config.heuristic and config.planner in informed:
                config.heuristic = default
            out.append(config)
        return out

    @staticmethod
    def _informed() -> tuple[str, ...]:
        try:
            from jupyddl.search import INFORMED_PLANNERS

            return tuple(INFORMED_PLANNERS)
        except Exception:
            return _INFORMED_FALLBACK

    # ------------------------------------------------------------------
    def run(
        self,
        instance: Instance,
        config: RunConfig,
        *,
        seed: int = 0,
        timeout_s: float = 60.0,
    ) -> RunRecord:
        from jupyddl.api import build_task, solve_task, validate_plan

        record = self.blank(instance, config, seed=seed, timeout_s=timeout_s)
        domain = instance.payload["domain"]
        problem = instance.payload["problem"]

        # Parsing and grounding are charged to the run: an instance nobody can
        # ground is an instance nobody can solve, and hiding that cost would
        # flatter every planner equally but misreport the wall time a user sees.
        elapsed = self.timer()
        task = build_task(domain, problem)
        result = solve_task(
            task,
            config.planner,
            config.heuristic or None,
            time_limit=timeout_s,
            **config.options,
        )
        record.wall_time_s = elapsed()

        stats = getattr(result, "stats", None)
        record.expanded = getattr(stats, "expanded", None)
        record.generated = getattr(stats, "generated", None)
        record.evaluated = getattr(stats, "evaluated", None)

        if result.solved:
            record.outcome = "solved"
            record.solved = True
            record.valid = bool(validate_plan(task, result.plan))
            record.cost = result.cost
            record.plan_length = result.plan_length
            if not record.valid:
                record.note = "planner returned a plan the validator rejected"
        elif getattr(result, "truncated", False):
            # jupyddl stopped on its own budget before our alarm fired.
            record.outcome = "timeout"
            record.note = "planner stopped on its internal time limit"
        else:
            record.outcome = "unsolved"
            record.note = "search space exhausted without finding a plan"
        return record
