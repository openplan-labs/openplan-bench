"""Seeded MAPF instance generation, owned by the harness rather than a backend.

Every MAPF adapter is handed the *same* generated instance and converts it into
its own problem type. That is what makes sum-of-costs comparable across
``pymapf`` and ``cuplan``: if each library generated its own map from the same
seed, the two would diverge the moment either changed its RNG, and the costs in
the table would be measuring different problems.

Only the standard library is used, so the generator is reproducible across
NumPy versions and Python builds: ``random.Random(seed)`` has a documented,
stable algorithm.

An instance is a plain dict — occupancy rows of 0/1, and two equal-length lists
of ``(row, col)`` cells:

    {"height": 12, "width": 12, "occupancy": [[1,1,...], ...],
     "starts": [[1,1], ...], "goals": [[9,9], ...]}
"""

from __future__ import annotations

import random
from collections import deque
from typing import Any

Cell = tuple[int, int]


class GenerationError(RuntimeError):
    """Raised when no instance of the requested shape could be built."""


def _neighbours(cell: Cell, height: int, width: int):
    row, col = cell
    if row > 0:
        yield (row - 1, col)
    if row + 1 < height:
        yield (row + 1, col)
    if col > 0:
        yield (row, col - 1)
    if col + 1 < width:
        yield (row, col + 1)


def _largest_component(occupancy: list[list[int]]) -> list[Cell]:
    """The biggest 4-connected region of free cells, in row-major order."""
    height, width = len(occupancy), len(occupancy[0])
    seen: set[Cell] = set()
    best: list[Cell] = []
    for row in range(height):
        for col in range(width):
            if occupancy[row][col] or (row, col) in seen:
                continue
            component: list[Cell] = []
            queue = deque([(row, col)])
            seen.add((row, col))
            while queue:
                current = queue.popleft()
                component.append(current)
                for nb in _neighbours(current, height, width):
                    if nb not in seen and not occupancy[nb[0]][nb[1]]:
                        seen.add(nb)
                        queue.append(nb)
            if len(component) > len(best):
                best = component
    return sorted(best)


def random_grid_instance(
    height: int = 16,
    width: int = 16,
    n_agents: int = 6,
    density: float = 0.15,
    seed: int = 0,
    attempts: int = 64,
) -> dict[str, Any]:
    """Build one random-obstacle MAPF instance.

    Walls are sampled i.i.d. at ``density`` inside a solid border, then starts
    and goals are drawn without replacement from the largest connected free
    region — so every agent can reach its goal ignoring the others, and no two
    agents share a start or a goal. Retries up to ``attempts`` times when the
    sampled map leaves too little room.

    Raise :class:`GenerationError` rather than returning a degenerate instance:
    silently shrinking the agent count would put a mislabelled row in the
    results file.
    """
    if not 0.0 <= density < 0.9:
        raise ValueError("density must be in [0, 0.9)")
    if n_agents < 1:
        raise ValueError("n_agents must be at least 1")
    if height < 3 or width < 3:
        raise ValueError("grid must be at least 3x3 (the border is solid)")

    rng = random.Random(seed)
    for _ in range(attempts):
        occupancy = [
            [
                1
                if (row in (0, height - 1) or col in (0, width - 1))
                else int(rng.random() < density)
                for col in range(width)
            ]
            for row in range(height)
        ]
        component = _largest_component(occupancy)
        if len(component) < 2 * n_agents:
            continue
        picked = rng.sample(component, 2 * n_agents)
        starts = picked[:n_agents]
        goals = picked[n_agents:]
        return {
            "height": height,
            "width": width,
            "density": density,
            "n_agents": n_agents,
            "seed": seed,
            "occupancy": occupancy,
            "starts": [list(cell) for cell in starts],
            "goals": [list(cell) for cell in goals],
        }
    raise GenerationError(
        f"could not place {n_agents} agents on a {height}x{width} grid "
        f"at density {density} in {attempts} attempts"
    )


def feasible(height: int, width: int, n_agents: int, density: float) -> bool:
    """Cheap pre-check: starts and goals may fill at most half the free cells.

    Borrowed from ``cuplan``'s sweep — it keeps a sweep from spending its
    ``attempts`` budget on cells that cannot exist.
    """
    free = (height - 2) * (width - 2) * (1.0 - density)
    return 2 * n_agents <= free * 0.5


def instance_id(builder: str, height: int, width: int, n: int, d: float) -> str:
    """The stable id a generated instance carries in the results file."""
    return f"{builder}/{height}x{width}/n{n}/d{d:g}"
