"""Integration regression for retained ESTO projection allocation anchors."""

#%%

from pathlib import Path

import pytest

from codebase import transformation_workflow
from codebase.functions import transformation_analysis_utils as core


def _year_total(record: dict, year: int) -> float:
    """Return the total process output for one year."""
    return sum(
        float(values.get(year, 0.0) or 0.0)
        for values in record.get("output_values", {}).values()
    )


def test_prepare_then_collect_target_retains_usa_gas_parent_anchor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The real preparation-to-collection path keeps blending beside direct LNG."""
    required_paths = [
        Path(core.ESTO_DATA_PATH),
        Path(core.NINTH_DATA_PATH),
        Path(core.NINTH_TO_ESTO_MAPPING_PATH[0]),
    ]
    if not all(path.exists() for path in required_paths):
        pytest.skip("USA transformation integration inputs are not available")

    # Keep the real data preparation, mapping, allocation, and analysis path,
    # while isolating its optional diagnostic side effects from repository outputs.
    monkeypatch.setattr(
        core.workflow_common,
        "archive_config_dir_once_per_day",
        lambda: None,
    )
    monkeypatch.setattr(
        core,
        "write_projection_diagnostics",
        lambda *args, **kwargs: tmp_path / "projection.csv",
    )
    monkeypatch.setattr(
        core,
        "save_unallocated_projection_diagnostics",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        core,
        "save_missing_ninth_fill_diagnostics",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(core, "save_dropped_fuel_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(core, "PRINT_SECTOR_ROWS", False)
    monkeypatch.setattr(core, "PRINT_GAS_PROCESSING_SUMMARY", False)

    core.DATASET_MAP = None
    core.prepare_transformation_assets()

    parent_key = (
        core.esto_projection_anchor_data["economy"].eq("20_USA")
        & core.esto_projection_anchor_data["flows"].eq("09.06 Gas processing plants")
        & core.esto_projection_anchor_data["products"].eq("08.01 Natural gas")
    )
    parent_rows = core.esto_projection_anchor_data.loc[parent_key]
    assert len(parent_rows) == 1
    assert float(parent_rows.iloc[0][2022]) == pytest.approx(46.94349)
    assert parent_rows.iloc[0]["is_subtotal"] in (True, 1)
    assert not core.esto_data_raw["flows"].eq("09.06 Gas processing plants").any()

    reference_blending = core.esto_data.loc[
        core.esto_data["economy"].eq("20_USA")
        & core.esto_data["flows"].eq("09.06.03 Natural gas blending plants")
        & core.esto_data["products"].eq("08.01 Natural gas")
    ]
    assert len(reference_blending) == 1
    assert float(reference_blending.iloc[0][2023]) == pytest.approx(46.94349)
    assert float(reference_blending.iloc[0][2050]) == pytest.approx(46.94349)
    assert not core.esto_data["flows"].isin(
        ["09.06 Gas processing plants", "09.08 Coal transformation"]
    ).any()

    records = transformation_workflow.collect_transformation_rows(
        economies=["20_USA"],
        projection_scenario="target",
    )

    blending = next(
        record
        for record in records
        if record.get("sector_title") == "Natural gas blending plants"
        and record.get("process_name") == "Natural gas blending plants"
    )
    lng = next(
        record
        for record in records
        if record.get("sector_title") == "NG Liquefaction"
        and record.get("process_name") == "Liquefaction"
    )
    assert _year_total(blending, 2023) == pytest.approx(46.94349)
    assert _year_total(blending, 2050) == pytest.approx(46.94349)
    assert _year_total(lng, 2023) == pytest.approx(4218.798521)
    assert _year_total(lng, 2030) == pytest.approx(7535.907154)
    assert _year_total(lng, 2050) == pytest.approx(16699.89974)

    aggregate_titles = {"Gas processing plants", "Coal transformation"}
    assert not any(record.get("sector_title") in aggregate_titles for record in records)


#%%
