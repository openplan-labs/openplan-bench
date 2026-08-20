"""The harness: turn a suite into rows, with nothing swept under the rug.

The invariant the whole project rests on is that **every requested measurement
produces exactly one row**. Not "every successful measurement" — every one. A
planner that is not installed, a GPU that is not present, a run that exhausted
its budget, a run that raised: each is a row with an outcome and a reason. The
only way to be missing from a results file is to not have been asked for.

Runs are executed one at a time in a child process (:mod:`.worker`). Serial
execution is deliberate: benchmarking wall-clock time on N cores while N-1
other measurements compete for cache and memory bandwidth does not measure the
planner, it measures the scheduler.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import provenance
from .adapters import get_adapter
from .adapters.base import Adapter, RunConfig
from .records import Instance, RunRecord, write_csv, write_json
from .suite import Group, Suite
from .worker import SENTINEL

#: Extra seconds a child gets past its own budget before we kill it. The child
#: usually stops itself on the backend's internal limit; this is the backstop.
GRACE_S = 15.0

Progress = Callable[[RunRecord], None]


@dataclass
class Job:
    """One planned measurement, before it has been taken."""

    suite: str
    adapter: str
    instance: Instance
    config: RunConfig
    seed: int
    repetition: int
    timeout_s: float
    memory_limit_mb: int

    def payload(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "adapter": self.adapter,
            "instance": {
                "id": self.instance.id,
                "group": self.instance.group,
                "payload": self.instance.payload,
            },
            "config": {
                "planner": self.config.planner,
                "heuristic": self.config.heuristic,
                "options": self.config.options,
            },
            "seed": self.seed,
            "repetition": self.repetition,
            "timeout_s": self.timeout_s,
            "memory_limit_mb": self.memory_limit_mb,
        }

    def describe(self) -> str:
        return (
            f"{self.adapter}:{self.config.label} on {self.instance.id} "
            f"seed={self.seed} rep={self.repetition}"
        )


def plan_group(suite: Suite, group: Group, adapter: Adapter) -> list[Job]:
    """Every measurement ``group`` asks for, in a deterministic order."""
    instances = adapter.instances(group.spec)
    configs = adapter.configs(group.spec)
    seeds = suite.seeds_for(group)
    repetitions = suite.repetitions_for(group)
    timeout_s = suite.timeout_for(group)
    memory_limit_mb = suite.memory_for(group)

    jobs: list[Job] = []
    for instance in instances:
        for config in configs:
            for seed in seeds:
                for repetition in range(repetitions):
                    jobs.append(
                        Job(
                            suite=suite.name,
                            adapter=adapter.name,
                            instance=instance,
                            config=config,
                            seed=seed,
                            repetition=repetition,
                            timeout_s=timeout_s,
                            memory_limit_mb=memory_limit_mb,
                        )
                    )
    return jobs


def _stub(job: Job, adapter: Adapter, outcome: str, reason: str) -> RunRecord:
    """A row for a measurement that was never attempted, saying why."""
    record = adapter.blank(
        job.instance,
        job.config,
        seed=job.seed,
        timeout_s=job.timeout_s,
    )
    record.suite = job.suite
    record.repetition = job.repetition
    record.memory_limit_mb = job.memory_limit_mb
    record.outcome = outcome
    record.error = reason if outcome == "error" else ""
    record.note = reason
    return record


def _parse_child(stdout: str) -> dict[str, Any] | None:
    """Pull the result document out of the child's stdout, ignoring its chatter."""
    marker = stdout.rfind(SENTINEL)
    if marker < 0:
        return None
    tail = stdout[marker + len(SENTINEL) :].strip()
    if not tail:
        return None
    try:
        return json.loads(tail)
    except json.JSONDecodeError:
        return None


def execute(job: Job, adapter: Adapter, python: str | None = None) -> RunRecord:
    """Run one job in a child process and return its row, whatever happened."""
    command = [python or sys.executable, "-m", "openplan_bench.worker"]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(job.payload()),
            capture_output=True,
            text=True,
            timeout=job.timeout_s + GRACE_S,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except subprocess.TimeoutExpired:
        record = _stub(
            job,
            adapter,
            "timeout",
            f"killed after {job.timeout_s + GRACE_S:g}s "
            f"({job.timeout_s:g}s budget + {GRACE_S:g}s grace)",
        )
        # The budget is what we report, never an extrapolation of what it
        # "would have" taken. A cactus plot reads this as "did not finish".
        record.wall_time_s = job.timeout_s
        return record

    payload = _parse_child(completed.stdout)
    if payload is None:
        record = _stub(job, adapter, "error", "child produced no parseable result")
        record.error = (completed.stderr or completed.stdout or "")[-800:].strip()
        record.wall_time_s = time.perf_counter() - started
        # A child killed by the OOM killer or a fatal signal lands here.
        if completed.returncode and completed.returncode < 0:
            record.outcome = "memory" if completed.returncode == -9 else "error"
            record.note = f"child terminated by signal {-completed.returncode}"
        return record

    if payload.get("ok"):
        known = set(RunRecord.__dataclass_fields__)
        return RunRecord(
            **{k: v for k, v in payload["record"].items() if k in known}
        )

    kind = payload.get("kind", "error")
    record = _stub(job, adapter, kind, payload.get("error", "unknown failure"))
    record.error = payload.get("error", "")
    record.wall_time_s = time.perf_counter() - started
    if payload.get("traceback"):
        record.note = payload["traceback"].strip().splitlines()[-1][:300]
    return record


def run_suite(
    suite: Suite,
    *,
    on_record: Progress | None = None,
    on_message: Callable[[str], None] | None = None,
    python: str | None = None,
    limit: int | None = None,
) -> list[RunRecord]:
    """Run every group in ``suite`` and return one row per requested run."""
    say = on_message or (lambda _msg: None)
    prov = provenance.collect()
    rows: list[RunRecord] = []

    for group in suite.groups:
        try:
            adapter = get_adapter(group.adapter)
        except ValueError as error:
            say(f"  ! {error}")
            continue

        usable, reason = adapter.available()
        jobs = plan_group(suite, group, adapter)
        if limit is not None:
            jobs = jobs[:limit]
        say(
            f"  {adapter.name}: {len(jobs)} run(s)"
            + ("" if usable else f" — SKIPPED, {reason}")
        )

        for job in jobs:
            if not usable:
                record = _stub(job, adapter, "not-installed", reason)
            else:
                skip = getattr(adapter, "skip_reason", lambda _c: "")(job.config)
                if skip:
                    record = _stub(job, adapter, "skipped", skip)
                else:
                    record = execute(job, adapter, python=python)
            record.suite = suite.name
            record.with_provenance(prov)
            rows.append(record)
            if on_record is not None:
                on_record(record)
    return rows


def iter_summary(rows: list[RunRecord]) -> Iterator[str]:
    """Terminal lines summarising a completed run, one per outcome."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.outcome] = counts.get(row.outcome, 0) + 1
    for outcome in sorted(counts):
        yield f"{outcome:>14}: {counts[outcome]}"


def save(
    rows: list[RunRecord],
    suite: Suite,
    out_dir: str | Path = "results",
) -> tuple[Path, Path]:
    """Write ``results/<suite>/<date>.csv`` and refresh ``latest.json``.

    The dated file is never overwritten within a day either — a second run on
    the same date gets a ``-2`` suffix. Benchmark history is the asset; losing
    yesterday's numbers to today's re-run is how a leaderboard stops being
    evidence.
    """
    directory = Path(out_dir) / suite.name
    directory.mkdir(parents=True, exist_ok=True)
    stamp = provenance.now_utc()[:10]
    csv_path = directory / f"{stamp}.csv"
    counter = 2
    while csv_path.exists():
        csv_path = directory / f"{stamp}-{counter}.csv"
        counter += 1
    write_csv(rows, csv_path)

    json_path = write_json(
        rows,
        directory / "latest.json",
        suite=suite.name,
        title=suite.title,
        description=suite.description,
        runner_grade=suite.runner_grade,
        source_csv=csv_path.name,
        machine=provenance.describe(),
        generated_utc=provenance.now_utc(),
    )
    return csv_path, json_path
