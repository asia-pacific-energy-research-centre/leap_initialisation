"""pytest configuration and shared fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_transformation_analysis_utils_globals():
    """Snapshot mutable module-level globals in transformation_analysis_utils before each
    test and restore them afterwards so no test leaks state into the next.

    Also forces ENABLE_DEBUG_BREAKPOINTS=False in esto_data_utils for the duration of
    every test to prevent accidental breakpoint() calls from hanging the suite.
    """
    import codebase.functions.esto_data_utils as edu
    import codebase.functions.transformation_analysis_utils as tau

    prior_debug = edu.ENABLE_DEBUG_BREAKPOINTS
    edu.ENABLE_DEBUG_BREAKPOINTS = False

    snapshot = dict(
        DATASET_MAP=tau.DATASET_MAP,
        code_to_name_mapping=dict(tau.code_to_name_mapping),
        ESTO_IMPORT_EXPORT_REFERENCE_DATA=tau.ESTO_IMPORT_EXPORT_REFERENCE_DATA,
        ESTO_IMPORT_EXPORT_YEAR_COLS=list(tau.ESTO_IMPORT_EXPORT_YEAR_COLS),
        esto_data_raw=tau.esto_data_raw,
        ninth_data_raw=tau.ninth_data_raw,
        esto_year_cols=list(tau.esto_year_cols),
        ninth_year_cols=list(tau.ninth_year_cols),
        esto_year_cols_raw=list(tau.esto_year_cols_raw),
        esto_data=tau.esto_data,
        ninth_data=tau.ninth_data,
        dropped_input_fuel_log=list(tau._dropped_input_fuel_log),
        analyzed_sector_titles=set(tau._analyzed_sector_titles),
    )

    yield

    tau.DATASET_MAP = snapshot["DATASET_MAP"]
    tau.code_to_name_mapping = snapshot["code_to_name_mapping"]
    tau.ESTO_IMPORT_EXPORT_REFERENCE_DATA = snapshot["ESTO_IMPORT_EXPORT_REFERENCE_DATA"]
    tau.ESTO_IMPORT_EXPORT_YEAR_COLS = snapshot["ESTO_IMPORT_EXPORT_YEAR_COLS"]
    tau.esto_data_raw = snapshot["esto_data_raw"]
    tau.ninth_data_raw = snapshot["ninth_data_raw"]
    tau.esto_year_cols = snapshot["esto_year_cols"]
    tau.ninth_year_cols = snapshot["ninth_year_cols"]
    tau.esto_year_cols_raw = snapshot["esto_year_cols_raw"]
    tau.esto_data = snapshot["esto_data"]
    tau.ninth_data = snapshot["ninth_data"]
    tau._dropped_input_fuel_log[:] = snapshot["dropped_input_fuel_log"]
    tau._analyzed_sector_titles.clear()
    tau._analyzed_sector_titles.update(snapshot["analyzed_sector_titles"])

    edu.ENABLE_DEBUG_BREAKPOINTS = prior_debug
