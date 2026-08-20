"""Declarative suite files.

A suite says what to run, on what, how many times, and for how long. Keeping
it in YAML rather than in Python means the exact experiment behind a published
table is one reviewable file, and re-running someone else's numbers is
``openplan-bench run suites/their-suite.yaml``.

Schema::

    name: classical-smoke          # required; also the results directory
    title: Classical smoke test    # shown on the dashboard
    description: >
      One paragraph. Says what the suite is FOR.
    seeds: [0, 1, 2]               # >= 3 for anything with variance
    repetitions: 1                 # timing repeats per seed
    timeout_s: 30                  # hard wall-clock budget per run
    memory_limit_mb: 4096          # hard address-space cap per run
    runner_grade: false            # true => times are not a hardware comparison
    groups:
      - adapter: jupyddl
        corpus_root: ../pddl-examples
        instances: [...]           # adapter-specific
        planners: [...]            # adapter-specific

Unknown top-level keys are rejected. A typo in a benchmark configuration that
silently does nothing is how you publish a table that measures something other
than what its caption says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_TOP_LEVEL = {
    "name",
    "title",
    "description",
    "seeds",
    "repetitions",
    "timeout_s",
    "memory_limit_mb",
    "runner_grade",
    "groups",
}


class SuiteError(ValueError):
    """Raised for a malformed suite file, naming the file and the key."""


@dataclass
class Group:
    """One adapter's slice of a suite: its instances and its configurations."""

    adapter: str
    spec: dict[str, Any] = field(default_factory=dict)
    seeds: list[int] | None = None
    repetitions: int | None = None
    timeout_s: float | None = None
    memory_limit_mb: int | None = None


@dataclass
class Suite:
    name: str
    title: str = ""
    description: str = ""
    seeds: list[int] = field(default_factory=lambda: [0, 1, 2])
    repetitions: int = 1
    timeout_s: float = 60.0
    memory_limit_mb: int = 4096
    runner_grade: bool = False
    groups: list[Group] = field(default_factory=list)
    path: str = ""

    def seeds_for(self, group: Group) -> list[int]:
        return list(group.seeds if group.seeds is not None else self.seeds)

    def repetitions_for(self, group: Group) -> int:
        value = group.repetitions if group.repetitions is not None else self.repetitions
        return max(1, int(value))

    def timeout_for(self, group: Group) -> float:
        value = group.timeout_s if group.timeout_s is not None else self.timeout_s
        return float(value)

    def memory_for(self, group: Group) -> int:
        value = (
            group.memory_limit_mb
            if group.memory_limit_mb is not None
            else self.memory_limit_mb
        )
        return int(value)


def load_suite(path: str | Path) -> Suite:
    """Parse and validate a suite file.

    Relative paths inside the suite (``corpus_root``) are resolved against the
    suite file's own directory, so a suite is portable: it works from any
    working directory and from a checkout at any location.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise SuiteError(f"No such suite file: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise SuiteError(f"{path}: not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise SuiteError(f"{path}: top level must be a mapping")

    unknown = set(raw) - _TOP_LEVEL
    if unknown:
        raise SuiteError(
            f"{path}: unknown top-level key(s) {sorted(unknown)}. "
            f"Known keys: {sorted(_TOP_LEVEL)}"
        )
    if "name" not in raw:
        raise SuiteError(f"{path}: 'name' is required")
    if not raw.get("groups"):
        raise SuiteError(f"{path}: at least one entry under 'groups' is required")

    groups: list[Group] = []
    for index, entry in enumerate(raw["groups"]):
        if not isinstance(entry, dict) or "adapter" not in entry:
            raise SuiteError(f"{path}: groups[{index}] needs an 'adapter' key")
        spec = {
            key: value
            for key, value in entry.items()
            if key
            not in ("adapter", "seeds", "repetitions", "timeout_s", "memory_limit_mb")
        }
        if "corpus_root" in spec:
            root = Path(str(spec["corpus_root"])).expanduser()
            if not root.is_absolute():
                root = (path.parent / root).resolve()
            spec["corpus_root"] = str(root)
        groups.append(
            Group(
                adapter=str(entry["adapter"]),
                spec=spec,
                seeds=list(entry["seeds"]) if "seeds" in entry else None,
                repetitions=entry.get("repetitions"),
                timeout_s=entry.get("timeout_s"),
                memory_limit_mb=entry.get("memory_limit_mb"),
            )
        )

    suite = Suite(
        name=str(raw["name"]),
        title=str(raw.get("title", raw["name"])),
        description=str(raw.get("description", "")).strip(),
        seeds=[int(s) for s in raw.get("seeds", [0, 1, 2])],
        repetitions=int(raw.get("repetitions", 1)),
        timeout_s=float(raw.get("timeout_s", 60.0)),
        memory_limit_mb=int(raw.get("memory_limit_mb", 4096)),
        runner_grade=bool(raw.get("runner_grade", False)),
        groups=groups,
        path=str(path),
    )
    if not suite.seeds:
        raise SuiteError(f"{path}: 'seeds' must not be empty")
    return suite


def discover_suites(directory: str | Path = "suites") -> list[Path]:
    """Every ``*.yaml`` under ``directory``, sorted."""
    return sorted(Path(directory).glob("*.yaml"))
