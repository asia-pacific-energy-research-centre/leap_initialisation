"""Regression tests for LEAP export region/economy compatibility."""

#%%

import pytest
import pandas as pd

from codebase.functions.transformation_record_builder import (
    validate_export_region_matches_id_lookup,
    validate_export_region_matches_process_economies,
)


def test_export_region_guard_rejects_economy_region_mismatch():
    records = [
        {
            "economy": "01_AUS",
            "sector_title": "Electricity interim",
            "process_name": "Electricity interim",
        }
    ]

    with pytest.raises(ValueError, match="expected LEAP region 'Australia'"):
        validate_export_region_matches_process_economies(records, "United States")


def test_export_region_guard_accepts_matching_region():
    records = [
        {
            "economy": "01_AUS",
            "sector_title": "Electricity interim",
            "process_name": "Electricity interim",
        }
    ]

    validate_export_region_matches_process_economies(records, "Australia")


def test_id_lookup_region_guard_rejects_template_region_mismatch(tmp_path):
    template_path = tmp_path / "full model export.xlsx"
    template = pd.DataFrame({"Region": ["United States"]})
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    with pytest.raises(ValueError, match="Available region\\(s\\): United States"):
        validate_export_region_matches_id_lookup("Australia", template_path)


def test_id_lookup_region_guard_accepts_template_region_match(tmp_path):
    template_path = tmp_path / "full model export.xlsx"
    template = pd.DataFrame({"Region": ["Australia"]})
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        template.to_excel(writer, sheet_name="Export", index=False, startrow=2)

    validate_export_region_matches_id_lookup("Australia", template_path)


#%%
