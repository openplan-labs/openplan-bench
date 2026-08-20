"""Adapter registry.

Adding a planner to the leaderboard is adding a module here and one line to
:data:`_BUILTIN`. Nothing else in the harness needs to change — the runner,
the CSV schema, the aggregation and the site are all adapter-agnostic.

Registration is lazy: importing this package must not import ``jupyddl``,
``pymapf`` or ``cuda-planning``, because the harness has to work on a machine
that has none of them.
"""

from __future__ import annotations

from importlib import import_module

from .base import Adapter, RunConfig, missing

__all__ = ["Adapter", "RunConfig", "missing", "get_adapter", "available_adapters"]

#: adapter name -> "module:ClassName", imported on first use.
_BUILTIN: dict[str, str] = {
    "jupyddl": "openplan_bench.adapters.jupyddl_adapter:JupyddlAdapter",
    "pymapf": "openplan_bench.adapters.pymapf_adapter:PymapfAdapter",
    "cuplan": "openplan_bench.adapters.cuplan_adapter:CuplanAdapter",
    "fake": "openplan_bench.adapters.fake:FakeAdapter",
}

_EXTRA: dict[str, type[Adapter]] = {}


def register(name: str, cls: type[Adapter]) -> None:
    """Register an out-of-tree adapter under ``name`` (used by tests/plugins)."""
    _EXTRA[name] = cls


def available_adapters() -> list[str]:
    return sorted(set(_BUILTIN) | set(_EXTRA))


def get_adapter(name: str) -> Adapter:
    """Instantiate the adapter registered as ``name``."""
    key = name.strip().lower()
    if key in _EXTRA:
        return _EXTRA[key]()
    try:
        target = _BUILTIN[key]
    except KeyError as error:
        raise ValueError(
            f"Unknown adapter {name!r}. Available: {', '.join(available_adapters())}"
        ) from error
    module_name, _, class_name = target.partition(":")
    return getattr(import_module(module_name), class_name)()
