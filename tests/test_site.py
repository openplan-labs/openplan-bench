"""The dashboard: it must build from nothing, and must not hide bad outcomes."""

from __future__ import annotations

import json

from openplan_bench import site
from openplan_bench.records import RunRecord, write_csv, write_json


def _results(tmp_path):
    rows = [
        RunRecord(
            suite="demo",
            family="classical",
            adapter="jupyddl",
            instance="miconic/s1-0",
            instance_group="miconic",
            planner="astar",
            heuristic="lmcut",
            outcome="solved",
            solved=True,
            valid=True,
            wall_time_s=0.42,
            cost=4,
            plan_length=4,
            expanded=17,
            cpu_model="Test CPU",
            cpu_count=4,
        ),
        RunRecord(
            suite="demo",
            family="classical",
            adapter="jupyddl",
            instance="miconic/s10-0",
            planner="astar",
            heuristic="lmcut",
            outcome="timeout",
            wall_time_s=20.0,
            timeout_s=20.0,
            note="budget exhausted",
        ),
        RunRecord(
            suite="demo",
            family="mapf",
            adapter="cuplan",
            instance="random_obstacles/16x16/n8/d0.15",
            planner="pibt",
            outcome="skipped",
            note="no working CUDA device",
        ),
    ]
    directory = tmp_path / "results" / "demo"
    write_csv(rows, directory / "2026-01-01.csv")
    write_json(
        rows,
        directory / "latest.json",
        suite="demo",
        title="Demo suite",
        description="A suite for the tests.",
        runner_grade=True,
        machine="Test CPU (4 logical CPUs)",
    )
    return tmp_path / "results"


def test_site_builds_with_no_results_at_all(tmp_path):
    written = site.build(tmp_path / "nothing", tmp_path / "docs")
    index = (tmp_path / "docs" / "index.html").read_text()
    assert "No results are committed yet" in index
    assert (tmp_path / "docs" / ".nojekyll").exists()
    assert any(p.name == "tokens.css" for p in written)


def test_site_shows_timeouts_and_skips(tmp_path):
    results = _results(tmp_path)
    site.build(results, tmp_path / "docs", render_figures=False)
    index = (tmp_path / "docs" / "index.html").read_text()

    assert "Demo suite" in index
    assert "miconic/s10-0" in index
    assert "timeout" in index
    assert "no working CUDA device" in index
    assert "runner-grade" in index
    assert "Runner-grade timings" in index


def test_every_page_is_theme_aware_and_self_contained(tmp_path):
    results = _results(tmp_path)
    site.build(results, tmp_path / "docs", render_figures=False)
    css = (tmp_path / "docs" / "assets" / "tokens.css").read_text()
    # All three viewer states.
    assert ":root {" in css
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root:not([data-theme="light"])' in css

    for name in ("index.html", "methodology.html", "reproduce.html"):
        page = (tmp_path / "docs" / name).read_text()
        assert "assets/tokens.css" in page
        assert "assets/site.js" in page
        # No external script or stylesheet beyond the branding marks.
        assert "cdn." not in page
        assert "<script src=\"assets/site.js\"></script>" in page


def test_methodology_states_what_is_not_measured(tmp_path):
    site.build(_results(tmp_path), tmp_path / "docs", render_figures=False)
    page = (tmp_path / "docs" / "methodology.html").read_text()
    assert "does <em>not</em> measure" in page
    assert "not a planner competition" in page
    assert "timeout is not a proof of unsolvability" in page.replace(
        "\n", " "
    ) or "not a proof of unsolvability" in page


def test_figures_render_light_and_dark(tmp_path):
    results = _results(tmp_path)
    site.build(results, tmp_path / "docs")
    figures = tmp_path / "docs" / "figures" / "demo"
    for stem in ("cactus", "coverage", "outcomes"):
        assert (figures / f"{stem}.png").exists()
        assert (figures / f"{stem}-dark.png").exists()


def test_load_results_reads_the_header_beside_the_rows(tmp_path):
    results = site.load_results(_results(tmp_path))
    assert len(results) == 1
    assert results[0].title == "Demo suite"
    assert results[0].runner_grade is True
    assert len(results[0].rows) == 3


def test_latest_json_is_machine_readable(tmp_path):
    results = _results(tmp_path)
    payload = json.loads((results / "demo" / "latest.json").read_text())
    assert payload["schema_version"] == 1
    assert len(payload["rows"]) == 3
    assert payload["rows"][1]["outcome"] == "timeout"
