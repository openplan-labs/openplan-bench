"""A deterministic adapter with no backend, used by the harness's own tests.

Testing a benchmark harness against a real planner would make the test suite
slow, machine-dependent and occasionally wrong for reasons that have nothing
to do with the harness. This adapter produces exactly the behaviour a test
asks for — including sleeping past its budget, exploding, and eating memory —
so the timeout path, the error path and the memory guard are all covered
without a planner installed.

It is also the smallest complete example of the adapter interface, and worth
reading first if you are adding one.
"""

from __future__ import annotations

import time
from typing import Any

from ..records import Instance, RunRecord
from .base import Adapter, RunConfig


class FakeAdapter(Adapter):
    name = "fake"
    family = "synthetic"
    requires = ()

    def available(self) -> tuple[bool, str]:
        return True, ""

    def instances(self, spec: dict[str, Any]) -> list[Instance]:
        out: list[Instance] = []
        for entry in spec.get("instances", []) or []:
            if isinstance(entry, str):
                entry = {"id": entry}
            out.append(
                Instance(
                    id=str(entry["id"]),
                    group=str(entry.get("group", "synthetic")),
                    payload=dict(entry.get("payload", {})),
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
        record = self.blank(instance, config, seed=seed, timeout_s=timeout_s)
        behaviour = str(
            config.options.get("behaviour", instance.payload.get("behaviour", "solve"))
        )

        if behaviour == "raise":
            raise RuntimeError("the fake adapter was asked to fail")
        if behaviour == "hang":
            time.sleep(float(config.options.get("sleep", 30.0)))
        if behaviour == "hog":
            # Enough to trip a small RLIMIT_AS in a test, harmless otherwise.
            _ = bytearray(int(config.options.get("bytes", 512 * 1024 * 1024)))

        elapsed = self.timer()
        # A tiny amount of real work, so wall_time_s is never exactly zero.
        cost = sum(range(1000 + seed))
        record.wall_time_s = max(elapsed(), 1e-6)

        if behaviour == "unsolved":
            record.outcome = "unsolved"
            record.note = "the fake adapter was asked to report no solution"
            return record

        record.outcome = "solved"
        record.solved = True
        record.valid = True
        record.cost = float(int(instance.payload.get("cost", 10)) + seed)
        record.plan_length = int(instance.payload.get("plan_length", 5))
        record.expanded = int(instance.payload.get("expanded", 100)) + seed
        record.generated = (record.expanded or 0) * 3
        record.note = f"deterministic checksum {cost % 9973}"
        return record
