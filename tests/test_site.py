"""The dashboard: it must build from nothing, and must not hide bad outcomes."""

from __future__ import annotations

import json

from openplan_bench import site
from openplan_bench.records import RunRecord, write_csv, write_json


def _results(tmp_path):
    # Every row carries the budget it was run under, because the harness stamps
    # it onto every row including the ones it never attempted. The site reads
    # the budget off these columns, so a fixture without them would be testing
    # a shape the harness never produces.
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
            timeout_s=20.0,
            memory_limit_mb=3072,
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
            # Measured elapsed at the stop, past the budget — not the budget.
            wall_time_s=20.14,
            timeout_s=20.0,
            memory_limit_mb=3072,
            note="planner stopped on its internal time limit",
        ),
        RunRecord(
            suite="demo",
            family="mapf",
            adapter="cuplan",
            instance="random_obstacles/16x16/n8/d0.15",
            planner="pibt",
            outcome="skipped",
            timeout_s=20.0,
            memory_limit_mb=3072,
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


def test_every_suite_table_states_its_budget(tmp_path):
    """Coverage without a stated budget is not a number.

    The budget is read off the rows, so it cannot drift from the measurement
    the way a hand-written suite description can.
    """
    site.build(_results(tmp_path), tmp_path / "docs", render_figures=False)
    index = (tmp_path / "docs" / "index.html").read_text()

    # One caption per table, and the suite has two of them.
    assert index.count("Per-instance budget: 20 s wall clock") >= 2
    assert "<caption>" in index
    # The methodology page repeats every suite's budget in one table.
    page = (tmp_path / "docs" / "methodology.html").read_text()
    assert "Budgets" in page
    assert "20 s" in page


def test_a_single_sample_is_not_presented_as_a_range(tmp_path):
    """One seed and one repetition gives one number, not a min-max band."""
    site.build(_results(tmp_path), tmp_path / "docs", render_figures=False)
    index = (tmp_path / "docs" / "index.html").read_text().replace("\n", " ")
    assert "Single-sample timings" in index
    assert "Every cell in this suite is" in " ".join(index.split())


def test_the_timeout_column_says_what_it_holds(tmp_path):
    """The docs and the data have to agree on what wall_time_s is."""
    site.build(_results(tmp_path), tmp_path / "docs", render_figures=False)
    page = (tmp_path / "docs" / "methodology.html").read_text().replace("\n", " ")
    assert "<code>timeout_s</code> is the budget" in page
    assert "elapsed time at which the run" in page
    index = (tmp_path / "docs" / "index.html").read_text().replace("\n", " ")
    assert "wall_time_s" in index


def test_timestamp_provenance_is_described_as_recorded(tmp_path):
    """The demo rows share one stamp; the page must not imply a per-row clock."""
    results = site.load_results(_results(tmp_path))
    # Every demo row is unstamped, so there is nothing to claim.
    assert results[0].stamped == "no run timestamp recorded"

    from openplan_bench.records import RunRecord

    one = site.SuiteResults(
        name="x", rows=[RunRecord(timestamp_utc="2026-01-01T00:00:00+00:00")], meta={}
    )
    assert "one stamp for the whole run" in one.stamped
    many = site.SuiteResults(
        name="x",
        rows=[
            RunRecord(timestamp_utc="2026-01-01T00:00:00+00:00"),
            RunRecord(timestamp_utc="2026-01-01T00:00:09+00:00"),
        ],
        meta={},
    )
    assert many.stamped.startswith("rows stamped")


def test_reproduce_page_clones_the_right_url_and_names_a_real_file(tmp_path):
    """A snippet that 404s or FileNotFoundErrors is not a reproduction recipe."""
    site.build(_results(tmp_path), tmp_path / "docs", render_figures=False)
    page = (tmp_path / "docs" / "reproduce.html").read_text()
    assert "git clone https://github.com/openplan-labs/openplan-bench.git" in page
    # The corpus goes where the suite files actually resolve corpus_root to.
    assert "corpus/pddl-examples" in page
    # The example path is taken from the committed results, never hardcoded.
    assert "results/demo/2026-01-01.csv" in page


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
    from openplan_bench.records import SCHEMA_VERSION

    assert payload["schema_version"] == SCHEMA_VERSION
    assert len(payload["rows"]) == 3
    assert payload["rows"][1]["outcome"] == "timeout"
