"""Tests for what someone opening this for the first time is asked.

The screen a new user sees was written by someone who already knew the answers:
two folder paths, a numbered list, and `Which economy [1]:` — where `[1]` is a
convention, not an instruction, and nothing said what the program was about to
do or what typing anything would produce.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from codebase.portable_release import commands, portable_main


GUIDED_FLOW = inspect.getsource(portable_main._guided_flow)


# ---------------------------------------------------------------------------
# The opening screen
# ---------------------------------------------------------------------------


def test_it_says_what_it_does_before_asking_anything() -> None:
    """Both outputs are named, in words, not as command names."""
    assert "balance-review workbook" in GUIDED_FLOW
    assert "dashboard" in GUIDED_FLOW
    assert "browser" in GUIDED_FLOW


def test_it_says_where_input_comes_from_and_where_results_go() -> None:
    assert "Reading exports from" in GUIDED_FLOW
    assert "Writing results to" in GUIDED_FLOW


def test_it_explains_what_the_bracketed_default_means() -> None:
    """`[1]` reads as a label, a count, or a thing to type - unless you say."""
    assert "press Enter" in GUIDED_FLOW
    assert "default" in GUIDED_FLOW


def test_it_says_a_number_is_what_to_type() -> None:
    assert "Type a number from the list above" in GUIDED_FLOW


def test_the_scenario_prompt_says_what_to_type() -> None:
    assert "Type" in GUIDED_FLOW and "and press Enter." in GUIDED_FLOW


def test_the_year_prompt_says_what_the_year_is_used_for() -> None:
    """A bare 'Which year' does not say the workbook is built for that year."""
    assert "Which year should the balance review compare?" in GUIDED_FLOW
    assert "compares LEAP with the ESTO or 9th balances" in GUIDED_FLOW


def test_the_workbook_is_described_as_a_comparison_not_a_verdict() -> None:
    """"Where LEAP disagrees with ESTO" stated a conclusion and dropped the 9th.

    The workbook compares LEAP against whichever comparator each row has - ESTO
    or the 9th - and reports matches as well as mismatches. Describing it as a
    list of disagreements tells a reader to expect only problems, and to expect
    them from one source.
    """
    assert "disagrees" not in GUIDED_FLOW
    assert "compared with the ESTO or 9th" in GUIDED_FLOW


def test_the_year_prompt_offers_more_than_one_year() -> None:
    assert "separate them with commas" in GUIDED_FLOW
    assert "own workbook" in GUIDED_FLOW


def test_a_wrong_entry_says_what_to_type_instead() -> None:
    assert "or q to quit" in GUIDED_FLOW


# ---------------------------------------------------------------------------
# Several years
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2022", [2022]),
        (2022, [2022]),
        ("2022,2030", [2022, 2030]),
        ("2022, 2030", [2022, 2030]),
        ("2022 2030", [2022, 2030]),
        (" 2022 , 2030 , 2040 ", [2022, 2030, 2040]),
        ("2022,2022", [2022]),
    ],
)
def test_years_are_read_the_way_people_type_them(text, expected) -> None:
    assert commands.parse_years(text) == expected


def test_the_order_typed_is_the_order_run() -> None:
    assert commands.parse_years("2040,2022") == [2040, 2022]


@pytest.mark.parametrize("bad", ["", "   ", ",", "twenty"])
def test_a_year_that_is_not_a_year_is_refused_with_advice(bad) -> None:
    with pytest.raises(ValueError) as caught:
        commands.parse_years(bad)
    message = str(caught.value)
    assert "year" in message.lower()


def test_the_advice_names_the_comma_form() -> None:
    with pytest.raises(ValueError, match="2022,2030"):
        commands.parse_years("2022,banana")


def test_every_requested_year_produces_a_workbook() -> None:
    """The workflow always accepted a list; this command discarded the rest.

    `outcome["review_workbooks"][0]` meant asking for three years produced one
    workbook and no complaint - the worst kind of wrong, because the run looked
    like it had succeeded.
    """
    source = inspect.getsource(commands.run_balance_review_from_export)
    assert 'outcome["review_workbooks"][0]' not in source
    assert "produced_all = list(" in source
    assert '"workbooks": workbooks' in source


def test_extra_years_are_validated_before_the_run_starts() -> None:
    """Otherwise a bad third year appears after two runs of several minutes."""
    signature = inspect.signature(
        __import__(
            "codebase.portable_release.validation", fromlist=["x"]
        ).validate_balance_review_from_export_inputs
    )
    assert "extra_years" in signature.parameters


# ---------------------------------------------------------------------------
# Where the dashboard lands
# ---------------------------------------------------------------------------


def test_the_duplicated_economy_folder_is_removed(tmp_path: Path) -> None:
    run_dir = tmp_path / "20_USA" / "dashboard"
    rendered = run_dir / "20USA"
    (rendered / "dashboards").mkdir(parents=True)
    (rendered / "chart_bundles").mkdir()
    (rendered / "dashboards" / "index.html").write_text("<p>pages</p>", encoding="utf-8")

    result = commands._flatten_dashboard_output(
        run_dir,
        {
            "output_root": str(rendered),
            "dashboard_index": str(rendered / "dashboards" / "index.html"),
            "chart_count": 619,
        },
    )

    assert not rendered.exists()
    assert (run_dir / "dashboards" / "index.html").is_file()
    assert (run_dir / "chart_bundles").is_dir()
    # Reported paths follow the files, or the run manifest points at nothing.
    assert result["dashboard_index"] == str(run_dir / "dashboards" / "index.html")
    assert result["output_root"] == str(run_dir)
    assert result["chart_count"] == 619


def test_a_one_click_entry_point_is_written(tmp_path: Path) -> None:
    run_dir = tmp_path / "dashboard"
    rendered = run_dir / "20USA"
    (rendered / "dashboards").mkdir(parents=True)
    (rendered / "dashboards" / "index.html").write_text("<p>x</p>", encoding="utf-8")

    result = commands._flatten_dashboard_output(run_dir, {"output_root": str(rendered)})

    shortcut = run_dir / commands._DASHBOARD_SHORTCUT_NAME
    assert shortcut.is_file()
    assert "dashboards/index.html" in shortcut.read_text(encoding="utf-8")
    assert result["open_this"] == str(shortcut)


def test_the_pages_themselves_are_not_moved_or_rewritten(tmp_path: Path) -> None:
    """They link to siblings by bare name and to ../chart_bundles/.

    Moving individual pages up would break every chart on every page, which is
    why only the directory level is removed.
    """
    run_dir = tmp_path / "dashboard"
    rendered = run_dir / "20USA"
    (rendered / "dashboards").mkdir(parents=True)
    (rendered / "chart_bundles").mkdir()
    page = rendered / "dashboards" / "supply.html"
    page.write_text('<script src="../chart_bundles/supply__charts.js">', encoding="utf-8")

    commands._flatten_dashboard_output(run_dir, {"output_root": str(rendered)})

    moved = run_dir / "dashboards" / "supply.html"
    assert "../chart_bundles/supply__charts.js" in moved.read_text(encoding="utf-8")
    assert (run_dir / "chart_bundles").is_dir()


def test_flattening_a_second_time_replaces_the_previous_run(tmp_path: Path) -> None:
    """Re-running an economy must not fail on the folders already there."""
    run_dir = tmp_path / "dashboard"
    for body in ("first", "second"):
        rendered = run_dir / "20USA"
        (rendered / "dashboards").mkdir(parents=True)
        (rendered / "dashboards" / "index.html").write_text(body, encoding="utf-8")
        commands._flatten_dashboard_output(run_dir, {"output_root": str(rendered)})
    assert (run_dir / "dashboards" / "index.html").read_text(encoding="utf-8") == "second"


def test_a_result_without_a_rendered_root_is_left_alone(tmp_path: Path) -> None:
    assert commands._flatten_dashboard_output(tmp_path, {"chart_count": 1}) == {
        "chart_count": 1
    }
