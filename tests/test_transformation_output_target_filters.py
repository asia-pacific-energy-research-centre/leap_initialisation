"""Regression tests for zero-only transformation output target filtering."""

import pandas as pd

from codebase.functions import transformation_analysis_utils as utils


def test_gather_output_targets_omits_zero_only_labels(monkeypatch) -> None:
    monkeypatch.setattr(utils, "ESTO_IMPORT_EXPORT_REFERENCE_DATA", pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(utils, "ESTO_IMPORT_EXPORT_YEAR_COLS", [2024])
    monkeypatch.setattr(
        utils,
        "build_est_output_target_dict",
        lambda *args, **kwargs: {2024: 0.0, 2025: 0.0},
    )

    imports, exports = utils.gather_output_target_dicts(
        "01_AUS", ["BKB and PB"], 2024, 2025,
    )

    assert imports == {}
    assert exports == {}


def test_gather_output_targets_retains_nonzero_direction(monkeypatch) -> None:
    monkeypatch.setattr(utils, "ESTO_IMPORT_EXPORT_REFERENCE_DATA", pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(utils, "ESTO_IMPORT_EXPORT_YEAR_COLS", [2024])

    def fake_target_dict(economy, label, sector, *args, **kwargs):
        return {2024: 3.0} if sector == utils.ESTO_EXPORT_SECTOR_LABEL else {2024: 0.0}

    monkeypatch.setattr(utils, "build_est_output_target_dict", fake_target_dict)

    imports, exports = utils.gather_output_target_dicts(
        "01_AUS", ["Other recovered gases"], 2024, 2024,
    )

    assert imports == {}
    assert exports == {"Other recovered gases": {2024: 3.0}}
