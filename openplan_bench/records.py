"""The one row type every adapter returns, and how it reaches disk.

A benchmark is only as good as the thing it writes down. :class:`RunRecord` is
deliberately wide: it carries the measurement *and* the conditions under which
the measurement was taken, because a number without machine, problem set and
seed is not a result. Every row is self-describing — you can hand a single line
of a CSV to someone and they can tell you what produced it.

Outcomes are a closed vocabulary (:data:`OUTCOMES`). In particular a run that
hits its wall-clock budget is recorded as ``timeout``, never dropped: "we
stopped looking" and "no plan exists" are different facts and the leaderboard
must not conflate them.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

#: Every terminal state a single measured run can be in.
OUTCOMES = (
    "solved",  # a plan/solution was returned
    "unsolved",  # the planner terminated and reported no solution
    "timeout",  # the wall-clock budget was exhausted; solvability unknown
    "memory",  # the memory guard fired; solvability unknown
    "error",  # the planner raised, crashed, or produced unparseable output
    "not-installed",  # the adapter's backend is not importable here
    "skipped",  # deliberately not run (no GPU, filtered out, ...)
)

#: Outcomes that mean "the planner had its fair chance and came back".
CONCLUSIVE = ("solved", "unsolved")


@dataclass
class RunRecord:
    """One measured run of one planner configuration on one instance."""

    # --- what was run -----------------------------------------------------
    suite: str = ""
    family: str = ""  # "classical" | "mapf" | anything an adapter defines
    adapter: str = ""
    instance: str = ""  # unique id of the problem inside the suite
    instance_group: str = ""  # domain / collection / scenario builder
    planner: str = ""
    heuristic: str = ""
    #: A second qualifier that makes two runs of the same planner different
    #: configurations rather than repetitions of one: cuplan's ``cpu`` vs
    #: ``cuda`` backend is the motivating case. Without it the two would share
    #: a leaderboard row and their timings would be averaged together.
    variant: str = ""
    config: str = ""  # JSON of any extra planner knobs

    # --- how it was run ---------------------------------------------------
    seed: int = 0
    repetition: int = 0
    timeout_s: float = 0.0
    memory_limit_mb: int = 0

    # --- what happened ----------------------------------------------------
    outcome: str = "error"
    solved: bool = False
    valid: bool = False
    wall_time_s: float = 0.0

    # --- what it cost (None where the family has no such notion) ----------
    cost: float | None = None
    plan_length: int | None = None
    makespan: int | None = None
    sum_of_costs: int | None = None
    expanded: int | None = None
    generated: int | None = None
    evaluated: int | None = None
    peak_rss_mb: float | None = None

    error: str = ""
    note: str = ""

    # --- under what conditions -------------------------------------------
    timestamp_utc: str = ""
    harness_version: str = ""
    harness_sha: str = ""
    python_version: str = ""
    platform: str = ""
    cpu_model: str = ""
    cpu_count: int = 0
    hostname: str = ""
    package_versions: str = ""  # JSON {dist: version}
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------
    @property
    def conclusive(self) -> bool:
        """True when the planner terminated of its own accord."""
        return self.outcome in CONCLUSIVE

    @property
    def label(self) -> str:
        """How a configuration is named in tables: ``planner/heuristic@variant``."""
        name = f"{self.planner}/{self.heuristic}" if self.heuristic else self.planner
        return f"{name}@{self.variant}" if self.variant else name

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_provenance(self, prov: dict[str, Any]) -> RunRecord:
        """Return a copy stamped with the provenance fields in ``prov``."""
        known = {f.name for f in fields(self)}
        for key, value in prov.items():
            if key in known:
                setattr(self, key, value)
        return self


FIELDNAMES: list[str] = [f.name for f in fields(RunRecord)]


def _coerce(name: str, raw: str) -> Any:
    """Turn one CSV cell back into the type the dataclass declares."""
    if raw == "":
        # Empty means None for the optional numerics, "" for the strings.
        annotation = RunRecord.__dataclass_fields__[name].type
        return None if "None" in str(annotation) else ""
    if name in ("solved", "valid"):
        return raw in ("True", "true", "1")
    annotation = str(RunRecord.__dataclass_fields__[name].type)
    if "int" in annotation and "float" not in annotation:
        try:
            return int(raw)
        except ValueError:
            return None
    if "float" in annotation:
        try:
            return float(raw)
        except ValueError:
            return None
    return raw


def write_csv(rows: list[RunRecord], path: str | Path) -> Path:
    """Write ``rows`` to ``path`` with the full, stable column set."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_dict())
    return path


def read_csv(path: str | Path) -> list[RunRecord]:
    """Read a results CSV back into records, tolerating added columns."""
    path = Path(path)
    out: list[RunRecord] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            values = {
                key: _coerce(key, value)
                for key, value in raw.items()
                if key in RunRecord.__dataclass_fields__
            }
            out.append(RunRecord(**values))
    return out


def write_json(rows: list[RunRecord], path: str | Path, **extra: Any) -> Path:
    """Write ``rows`` plus a small header as JSON (this is ``latest.json``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "rows": [row.as_dict() for row in rows],
        **extra,
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")
    return path


def read_json(path: str | Path) -> list[RunRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    known = set(RunRecord.__dataclass_fields__)
    return [
        RunRecord(**{k: v for k, v in row.items() if k in known})
        for row in payload.get("rows", [])
    ]


@dataclass
class Instance:
    """A problem to be solved, as handed to an adapter.

    ``payload`` is adapter-specific: file paths for PDDL, generator parameters
    for MAPF. The harness never looks inside it.
    """

    id: str
    group: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
