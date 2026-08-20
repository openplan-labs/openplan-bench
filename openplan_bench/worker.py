"""The sandboxed child that executes exactly one measured run.

Every run happens in a fresh process. That costs an interpreter startup per
row, and buys three things worth much more than the milliseconds:

* **A hard timeout.** A planner stuck in a C extension, or in a loop that never
  checks a flag, cannot be interrupted by a Python-level alarm. It can be
  killed.
* **A hard memory ceiling.** ``RLIMIT_AS`` turns "the machine started swapping
  and the whole sweep became meaningless" into one ``memory`` row.
* **No cross-run contamination.** Nothing a planner caches, imports, monkeypatches
  or leaks can reach the next measurement.

Protocol: one JSON job on stdin, one JSON record on stdout after the
:data:`SENTINEL` line. Anything the planner prints goes to stdout *before* the
sentinel and is ignored, which is why a chatty backend does not corrupt the
result.
"""

from __future__ import annotations

import json
import sys

#: Everything after this line on stdout is the result document.
SENTINEL = "@@OPENPLAN-BENCH-RESULT@@"


def set_limits(memory_limit_mb: int) -> None:
    """Cap the child's address space. A no-op where ``resource`` is unavailable."""
    if memory_limit_mb <= 0:
        return
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return
    limit = int(memory_limit_mb) * 1024 * 1024
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
    except (ValueError, OSError):  # pragma: no cover - hardened kernels
        pass


def peak_rss_mb() -> float | None:
    """This process's peak resident set size, in MiB."""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes.
    divisor = 1024.0 if sys.platform != "darwin" else 1024.0 * 1024.0
    return round(usage / divisor, 2)


def execute(job: dict) -> dict:
    """Run one job and return the record as a plain dict."""
    from .adapters import get_adapter
    from .adapters.base import RunConfig
    from .records import Instance

    set_limits(int(job.get("memory_limit_mb", 0)))

    adapter = get_adapter(job["adapter"])
    instance = Instance(
        id=job["instance"]["id"],
        group=job["instance"].get("group", ""),
        payload=job["instance"].get("payload", {}),
    )
    config = RunConfig(
        planner=job["config"]["planner"],
        heuristic=job["config"].get("heuristic", ""),
        variant=job["config"].get("variant", ""),
        options=job["config"].get("options", {}),
    )

    record = adapter.run(
        instance,
        config,
        seed=int(job.get("seed", 0)),
        timeout_s=float(job.get("timeout_s", 60.0)),
    )
    record.suite = job.get("suite", "")
    record.repetition = int(job.get("repetition", 0))
    record.memory_limit_mb = int(job.get("memory_limit_mb", 0))
    record.peak_rss_mb = peak_rss_mb()
    return record.as_dict()


def main() -> int:
    job = json.loads(sys.stdin.read())
    try:
        payload = {"ok": True, "record": execute(job)}
    except MemoryError:
        payload = {"ok": False, "kind": "memory", "error": "MemoryError"}
    except BaseException as exc:  # noqa: BLE001 - the child reports, never crashes
        import traceback

        payload = {
            "ok": False,
            "kind": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-2000:],
        }
    sys.stdout.write("\n" + SENTINEL + "\n")
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
