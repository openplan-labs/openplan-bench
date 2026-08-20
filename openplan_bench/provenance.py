"""Capture the conditions a measurement was taken under.

Every row in a results file carries these fields. That is redundant — the whole
CSV usually shares one environment — but it survives concatenation, and a
leaderboard that merges files from three machines has to be able to tell them
apart afterwards.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

#: Distributions whose versions are worth recording next to every number.
TRACKED_PACKAGES = (
    "openplan-bench",
    "jupyddl",
    "pymapf",
    "cuda-planning",
    "numpy",
    "matplotlib",
)


@lru_cache(maxsize=1)
def cpu_model() -> str:
    """Best-effort human-readable CPU name, or ``platform.processor()``."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return platform.processor() or platform.machine()
    match = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return platform.processor() or platform.machine()


@lru_cache(maxsize=1)
def harness_version() -> str:
    try:
        return version("openplan-bench")
    except PackageNotFoundError:
        return "0.0.0+source"


@lru_cache(maxsize=1)
def harness_sha() -> str:
    """The git SHA of this checkout, with ``-dirty`` when the tree is modified.

    Returns ``"unknown"`` outside a git checkout — an installed wheel has no
    repository, and a benchmark should still run there.
    """
    root = Path(__file__).resolve().parent.parent
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not sha:
        return "unknown"
    try:
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        dirty = ""
    return f"{sha}-dirty" if dirty else sha


def package_versions(names: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str]:
    """Installed version of each tracked distribution, or ``"not-installed"``."""
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not-installed"
    return out


def cpu_count() -> int:
    return os.cpu_count() or 0


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect() -> dict[str, object]:
    """The provenance block stamped onto every :class:`~.records.RunRecord`."""
    return {
        "timestamp_utc": now_utc(),
        "harness_version": harness_version(),
        "harness_sha": harness_sha(),
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpu_model": cpu_model(),
        "cpu_count": cpu_count(),
        "hostname": socket.gethostname(),
        "package_versions": json.dumps(package_versions(), sort_keys=True),
    }


def describe() -> str:
    """A one-paragraph human summary, for the terminal and the methodology page."""
    prov = collect()
    versions = json.loads(str(prov["package_versions"]))
    installed = ", ".join(
        f"{name} {ver}" for name, ver in versions.items() if ver != "not-installed"
    )
    return (
        f"{prov['cpu_model']} ({prov['cpu_count']} logical CPUs), "
        f"{prov['platform']}, Python {prov['python_version']}, "
        f"harness {prov['harness_version']}@{prov['harness_sha']}. "
        f"Installed: {installed or 'none of the tracked planners'}."
    )


def is_ci() -> bool:
    """True on a shared CI runner, where absolute times are not comparable."""
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def python_executable() -> str:
    return sys.executable
