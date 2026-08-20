"""The adapter contract — the one interface a new planner has to satisfy.

An adapter is a thin translation layer. It knows how to turn a suite's
instance specification into whatever its backend calls a problem, how to run
one configuration on it, and how to read the backend's answer back into a
:class:`~openplan_bench.records.RunRecord`. It does *not* time anything, retry
anything, enforce a budget, or decide what to run: the harness owns all of
that, so every backend is measured the same way.

Two rules make the whole thing hold together:

**A missing backend is a result, not a crash.** :meth:`Adapter.available`
returns ``(False, reason)`` when the import fails, and the harness writes
``not-installed`` rows. Someone with no GPU, or with only ``pymapf``
installed, still gets a complete, honest results file.

**Never claim more than the backend told you.** Leave a metric ``None`` if the
backend does not report it. A zero in an ``expanded`` column that actually
means "not measured" is worse than a blank.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..records import Instance, RunRecord


@dataclass
class RunConfig:
    """One planner configuration, as named in a suite file."""

    planner: str
    heuristic: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.planner}/{self.heuristic}" if self.heuristic else self.planner


class Adapter:
    """Base class for every planner integration.

    Subclasses set :attr:`name` and :attr:`family`, and implement
    :meth:`available`, :meth:`instances` and :meth:`run`.
    """

    #: Short id used in suite files and in the ``adapter`` column.
    name: str = "abstract"
    #: Benchmark family this adapter contributes to ("classical", "mapf", ...).
    family: str = "unknown"
    #: Distributions whose absence means this adapter cannot run.
    requires: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """Return ``(usable, reason)``.

        ``reason`` is shown to the user and written into ``not-installed`` and
        ``skipped`` rows, so make it actionable: name the extra to install.
        """
        raise NotImplementedError

    def instances(self, spec: dict[str, Any]) -> list[Instance]:
        """Expand the suite's ``instances:`` block into concrete instances."""
        raise NotImplementedError

    def configs(self, spec: dict[str, Any]) -> list[RunConfig]:
        """Expand the suite's ``planners:`` block into configurations.

        The default reads a list of ``{planner, heuristic, options}`` mappings
        or bare planner names, which is what almost every adapter wants.
        """
        out: list[RunConfig] = []
        for entry in spec.get("planners", []) or []:
            if isinstance(entry, str):
                out.append(RunConfig(planner=entry))
                continue
            out.append(
                RunConfig(
                    planner=str(entry["planner"]),
                    heuristic=str(entry.get("heuristic", "") or ""),
                    options=dict(entry.get("options", {}) or {}),
                )
            )
        return out

    def run(
        self,
        instance: Instance,
        config: RunConfig,
        *,
        seed: int = 0,
        timeout_s: float = 60.0,
    ) -> RunRecord:
        """Solve ``instance`` with ``config`` and report what happened.

        Called inside a sandboxed child process that already has a wall-clock
        alarm and a memory limit set, so an adapter may run to completion
        without defending itself. Do pass ``timeout_s`` down to the backend
        when it has its own budget knob — a planner that stops cleanly reports
        far better statistics than one that gets killed.

        Return a record with at least ``outcome``, ``solved`` and
        ``wall_time_s`` set. Raising is acceptable; the harness turns an
        exception into an ``error`` row naming the adapter.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    def blank(self, instance: Instance, config: RunConfig, **kwargs: Any) -> RunRecord:
        """A record pre-filled with the identifying columns for this run."""
        import json

        return RunRecord(
            family=self.family,
            adapter=self.name,
            instance=instance.id,
            instance_group=instance.group,
            planner=config.planner,
            heuristic=config.heuristic,
            config=json.dumps(config.options, sort_keys=True) if config.options else "",
            **kwargs,
        )

    @staticmethod
    def timer():
        """A monotonic stopwatch: ``stop = timer(); ...; elapsed = stop()``."""
        started = time.perf_counter()
        return lambda: time.perf_counter() - started


def missing(names: tuple[str, ...]) -> tuple[bool, str]:
    """Import-check ``names``; return the adapter ``available()`` tuple."""
    import importlib

    for module in names:
        try:
            importlib.import_module(module)
        except Exception as exc:  # ImportError, but a broken backend can raise anything
            return False, f"{module} is not importable ({type(exc).__name__}: {exc})"
    return True, ""
