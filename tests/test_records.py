"""The results schema: it has to survive a round trip through a CSV."""

from __future__ import annotations

from openplan_bench.records import (
    CONCLUSIVE,
    FIELDNAMES,
    OUTCOMES,
    RunRecord,
    read_csv,
    read_json,
    write_csv,
    write_json,
)


def _sample() -> list[RunRecord]:
    return [
        RunRecord(
            suite="s",
            family="classical",
            adapter="fake",
            instance="a/1",
            instance_group="a",
            planner="astar",
            heuristic="lmcut",
            outcome="solved",
            solved=True,
            valid=True,
            wall_time_s=1.25,
            cost=12.0,
            plan_length=12,
            expanded=340,
            generated=900,
            seed=3,
        ),
        RunRecord(
            suite="s",
            family="classical",
            adapter="fake",
            instance="a/2",
            planner="bfs",
            outcome="timeout",
            wall_time_s=30.0,
            timeout_s=30.0,
            note="killed",
        ),
        RunRecord(
            suite="s",
            family="mapf",
            adapter="cuplan",
            instance="g/1",
            planner="pibt",
            outcome="skipped",
            note="no GPU",
        ),
    ]


def test_round_trip_preserves_values(tmp_path):
    rows = _sample()
    path = write_csv(rows, tmp_path / "r.csv")
    back = read_csv(path)

    assert len(back) == 3
    assert back[0].cost == 12.0
    assert back[0].plan_length == 12
    assert back[0].solved is True
    assert back[0].valid is True
    assert back[0].seed == 3
    assert back[1].outcome == "timeout"
    assert back[1].solved is False
    assert back[2].note == "no GPU"


def test_optional_numerics_round_trip_as_none(tmp_path):
    """An unmeasured metric must come back as None, never as 0."""
    path = write_csv(_sample(), tmp_path / "r.csv")
    back = read_csv(path)
    assert back[1].cost is None
    assert back[1].expanded is None
    assert back[2].makespan is None


def test_json_round_trip_keeps_header(tmp_path):
    rows = _sample()
    path = write_json(rows, tmp_path / "latest.json", suite="s", runner_grade=True)
    import json

    payload = json.loads(path.read_text())
    assert payload["suite"] == "s"
    assert payload["runner_grade"] is True
    assert len(read_json(path)) == 3


def test_unknown_columns_are_ignored(tmp_path):
    """A results file from a newer schema must still be readable."""
    path = tmp_path / "future.csv"
    path.write_text(
        ",".join(FIELDNAMES + ["a_column_from_the_future"])
        + "\n"
        + ",".join([""] * len(FIELDNAMES) + ["surprise"])
        + "\n",
        encoding="utf-8",
    )
    rows = read_csv(path)
    assert len(rows) == 1


def test_label_and_conclusive():
    assert RunRecord(planner="astar", heuristic="lmcut").label == "astar/lmcut"
    assert RunRecord(planner="bfs").label == "bfs"
    assert RunRecord(outcome="solved").conclusive
    assert RunRecord(outcome="unsolved").conclusive
    assert not RunRecord(outcome="timeout").conclusive


def test_outcome_vocabulary_is_closed():
    assert set(CONCLUSIVE) <= set(OUTCOMES)
    assert "timeout" in OUTCOMES
    assert "not-installed" in OUTCOMES
