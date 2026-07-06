"""Regression tests for the process-efficiency export ceiling."""

#%%

import pytest

from codebase.configuration import workflow_config as workflow_cfg
from codebase.functions import transformation_record_builder as builder


def test_process_efficiency_values_are_capped_at_1000(monkeypatch):
    monkeypatch.setattr(
        workflow_cfg,
        "TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        workflow_cfg,
        "TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT",
        1000.0,
        raising=False,
    )

    capped_value = builder.cap_process_efficiency_value(2558.303207031259)
    capped_map = builder.cap_process_efficiency_value_by_year({2022: 2558.303207031259, 2023: 900.0})

    assert capped_value == pytest.approx(1000.0)
    assert capped_map[2022] == pytest.approx(1000.0)
    assert capped_map[2023] == pytest.approx(900.0)


def test_process_efficiency_ceiling_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        workflow_cfg,
        "TRANSFORMATION_CLIP_PROCESS_EFFICIENCY_TO_MAX",
        False,
        raising=False,
    )

    capped_value = builder.cap_process_efficiency_value(2558.303207031259)
    capped_map = builder.cap_process_efficiency_value_by_year({2022: 2558.303207031259})

    assert capped_value == pytest.approx(2558.303207031259)
    assert capped_map[2022] == pytest.approx(2558.303207031259)


#%%
