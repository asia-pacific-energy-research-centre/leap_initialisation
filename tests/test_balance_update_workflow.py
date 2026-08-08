from pathlib import Path

from codebase import balance_update_workflow as workflow


def test_review_and_update_keep_independent_year_horizons(tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def diagnostic_runner(**kwargs):
        calls["diagnostic"] = kwargs
        return {
            "economy_results": {
                "01_AUS": {"selected_balance_sheets": ["stub"]}
            }
        }

    def review_builder(**kwargs):
        calls["review"] = kwargs
        return [{"outputWorkbook": str(tmp_path / "review.xlsx")}]

    def update_runner(**kwargs):
        calls["update"] = kwargs
        return {"status": "complete"}

    result = workflow.run_balance_update_workflow(
        preset=workflow._PRESET_REVIEW_AND_UPDATE,
        economies=["01_AUS"],
        review_years=[2022, 2025],
        review_scenarios=["Reference"],
        update_scenarios=["Reference", "Target"],
        update_horizon="full",
        output_root=tmp_path,
        review_output_label="review_run",
        diagnostic_runner=diagnostic_runner,
        review_workbook_builder=review_builder,
        update_runner=update_runner,
    )

    assert calls["diagnostic"]["years"] == [2022, 2025]
    assert calls["diagnostic"]["scenarios"] == ["Reference"]
    assert calls["update"]["scenarios"] == ["Reference", "Target"]
    assert calls["update"]["update_horizon"] == "full"
    assert result["review_years"] == [2022, 2025]
    assert result["update_horizon"] == "full"


def test_update_only_does_not_call_review(tmp_path: Path) -> None:
    def fail_review(**kwargs):
        raise AssertionError("review stage should not run")

    result = workflow.run_balance_update_workflow(
        preset=workflow._PRESET_UPDATE_ONLY,
        economies=["01_AUS"],
        review_years=[2022],
        review_scenarios=["Reference"],
        update_scenarios=["Target"],
        update_horizon="base_year_plus_one",
        output_root=tmp_path,
        diagnostic_runner=fail_review,
        review_workbook_builder=fail_review,
        update_runner=lambda **kwargs: kwargs,
    )

    assert "diagnostics" not in result
    assert result["results_update"]["update_horizon"] == "base_year_plus_one"
