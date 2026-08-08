"""Regression coverage for single-owner LNG own-use handling."""

from codebase.functions import transformation_analysis_utils as analysis


def test_lng_transformation_does_not_read_100103_as_auxiliary_fuel() -> None:
    config = analysis.MAJOR_SECTOR_CONFIG["lng"]

    assert config["loss_sub2"] == []
