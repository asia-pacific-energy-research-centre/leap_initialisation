"""One-sided transfer flows must gain a nominal counterpart, not disappear.

`05_PRC` records 5,228 PJ of products transferred out in 2022 with no receiving
product in the active ESTO vintage. Before this behaviour existed the economy
produced no transfer process at all, silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.transfers_workflow import (  # noqa: E402
    AUTO_BALANCE_PRODUCT_LABEL,
    AUTO_BALANCE_LEAP_FUEL_NAME,
    ONE_SIDED_TRANSFER_BALANCE_POLICY,
    balance_one_sided_transfer_flow,
    save_transfer_export,
)
from codebase.functions.transfers_utils import (  # noqa: E402
    _apply_unallocated_policy,
    merge_transfer_rows,
)

YEARS = [2022, 2023]


def _flow_rows(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["economy", "flows", "products", *YEARS])


def test_outflow_only_flow_gains_a_nominal_output() -> None:
    rows = _flow_rows([
        {"economy": "05_PRC", "flows": "08.03 Products transferred",
         "products": "07.08 Fuel oil", 2022: -1054.1, 2023: -1000.0},
    ]).rename(columns={2022: 2022, 2023: 2023})

    balanced, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "05_PRC", "08.03 Products transferred"
    )

    assert diagnostic is not None
    assert diagnostic["measured_side"] == "outflow_only"
    assert diagnostic["counterpart_product"] == AUTO_BALANCE_PRODUCT_LABEL
    assert diagnostic["output_years_added"] == [2022, 2023]

    added = balanced[balanced["products"] == AUTO_BALANCE_PRODUCT_LABEL]
    assert len(added) == 1
    assert added[2022].iloc[0] == pytest.approx(1.0)
    # The measured side is untouched.
    measured = balanced[balanced["products"] == "07.08 Fuel oil"]
    assert measured[2022].iloc[0] == pytest.approx(-1054.1)


def test_inflow_only_flow_gains_a_nominal_input() -> None:
    rows = _flow_rows([
        {"economy": "04_CHL", "flows": "08.02 Interproduct transfers",
         "products": "07.01 Motor gasoline", 2022: 12.7, 2023: 13.0},
    ]).rename(columns={2022: 2022, 2023: 2023})

    balanced, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "04_CHL", "08.02 Interproduct transfers"
    )

    assert diagnostic is not None
    assert diagnostic["measured_side"] == "inflow_only"
    assert diagnostic["counterpart_product"] == AUTO_BALANCE_PRODUCT_LABEL
    added = balanced[balanced["products"] == AUTO_BALANCE_PRODUCT_LABEL]
    # 13.0 PJ peak / 1000% ceiling = 1.3 PJ, above the 1.0 floor.
    assert added[2022].iloc[0] == pytest.approx(-1.3)


def test_two_sided_flow_is_left_alone() -> None:
    rows = _flow_rows([
        {"economy": "12_NZ", "flows": "08.99 Transfers nonspecified",
         "products": "07.01 Motor gasoline", 2022: -1.4, 2023: -1.5},
        {"economy": "12_NZ", "flows": "08.99 Transfers nonspecified",
         "products": "06.03 Refinery feedstocks", 2022: 10.7, 2023: 11.0},
    ]).rename(columns={2022: 2022, 2023: 2023})

    balanced, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "12_NZ", "08.99 Transfers nonspecified"
    )

    assert diagnostic is None
    pd.testing.assert_frame_equal(balanced, rows)


def test_only_one_sided_years_get_a_counterpart() -> None:
    """A flow that is two-sided in one year and one-sided in another."""
    rows = _flow_rows([
        {"economy": "13_PNG", "flows": "08.02 Interproduct transfers",
         "products": "07.03 Naphtha", 2022: -1.3, 2023: -3.2},
        {"economy": "13_PNG", "flows": "08.02 Interproduct transfers",
         "products": "07.01 Motor gasoline", 2022: 0.0, 2023: 1.3},
    ]).rename(columns={2022: 2022, 2023: 2023})

    balanced, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "13_PNG", "08.02 Interproduct transfers"
    )

    assert diagnostic is not None
    # 2022 is one-sided and needs a counterpart; 2023 already balances.
    assert diagnostic["output_years_added"] == [2022]
    added = balanced[balanced["products"] == AUTO_BALANCE_PRODUCT_LABEL]
    assert added[2022].iloc[0] == pytest.approx(1.0)
    assert added[2023].iloc[0] == pytest.approx(0.0)


def test_policy_can_be_disabled() -> None:
    rows = _flow_rows([
        {"economy": "05_PRC", "flows": "08.03 Products transferred",
         "products": "07.08 Fuel oil", 2022: -1054.1, 2023: -1000.0},
    ]).rename(columns={2022: 2022, 2023: 2023})

    balanced, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "05_PRC", "08.03 Products transferred",
        policy={**ONE_SIDED_TRANSFER_BALANCE_POLICY, "enabled": False},
    )

    assert diagnostic is None
    pd.testing.assert_frame_equal(balanced, rows)


def test_inflow_only_reports_the_implied_efficiency() -> None:
    """The implied efficiency drives the ceiling warning, so it must be exact."""
    rows = _flow_rows([
        {"economy": "04_CHL", "flows": "08.02 Interproduct transfers",
         "products": "07.01 Motor gasoline", 2022: 12.7, 2023: 30.0},
    ])

    _, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "04_CHL", "08.02 Interproduct transfers"
    )

    # Counterpart is sized to 30.0 / 10 = 3.0 PJ, landing exactly at the 1000%
    # ceiling instead of blowing through it at 3000%.
    assert diagnostic["counterpart_value"] == pytest.approx(3.0)
    assert diagnostic["max_implied_efficiency_percent"] == pytest.approx(1000.0)


def test_outflow_only_has_no_implied_efficiency_risk() -> None:
    rows = _flow_rows([
        {"economy": "05_PRC", "flows": "08.03 Products transferred",
         "products": "07.08 Fuel oil", 2022: -1054.1, 2023: -1000.0},
    ])

    _, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "05_PRC", "08.03 Products transferred"
    )

    assert diagnostic["max_implied_efficiency_percent"] is None


def _transfer_record_with_one_pj_auto_balance(feedstock: float) -> dict:
    """Build a minimal one-sided transfer record for merge regression tests."""
    output_values = {AUTO_BALANCE_PRODUCT_LABEL: {2022: 1.0, 2023: 1.0}}
    return {
        "economy": "05_PRC",
        "sector_title": "Transfers unallocated",
        "process_name": "Transfers unallocated",
        "output_values": output_values,
        "gross_output_values": output_values,
        "deliverable_output_values": output_values,
        "feedstock_values": {"Fuel oil": {2022: feedstock, 2023: feedstock}},
        "efficiency": {2022: 1.0 / feedstock, 2023: 1.0 / feedstock},
        "input_total": feedstock * 2,
        "output_import_targets": {},
        "output_export_targets": {},
    }


@pytest.mark.parametrize(
    ("merge", "policy"),
    [
        (merge_transfer_rows, None),
        (
            _apply_unallocated_policy,
            {
                "enabled": True,
                "process_name": "Transfers unallocated",
                "max_efficiency_ratio": 0.001,
                "merge_all_when_triggered": True,
            },
        ),
    ],
)
def test_merged_auto_balance_outputs_also_set_the_capacity_output_basis(merge, policy) -> None:
    """Two 1-PJ counterparts must seed 2 PJ capacity, not the first 1 PJ only."""
    records = [
        _transfer_record_with_one_pj_auto_balance(230.270568),
        _transfer_record_with_one_pj_auto_balance(4998.147525),
    ]

    merged = merge(records) if policy is None else merge(records, policy)

    assert len(merged) == 1
    for key in ("output_values", "gross_output_values", "deliverable_output_values"):
        assert merged[0][key][AUTO_BALANCE_PRODUCT_LABEL][2023] == pytest.approx(2.0)
    assert merged[0]["efficiency"][2023] == pytest.approx(2.0 / 5228.418093)


def test_transfer_export_maps_synthetic_auto_balance_to_the_real_leap_leaf(monkeypatch, tmp_path) -> None:
    """The source-only counterpart label must be resolvable during export."""
    from codebase import transfers_workflow as transfers

    captured = {}
    monkeypatch.setattr(transfers.core, "code_to_name_mapping", {"07.01": "Motor gasoline"})
    monkeypatch.setattr(
        transfers.core,
        "save_transformation_export",
        lambda *args, **kwargs: captured.setdefault("mapping", args[4]),
    )
    monkeypatch.setattr(
        transfers.leap_export_template_resolver,
        "resolve_leap_export_template_or_fallback",
        lambda *args, **kwargs: tmp_path / "prc_template.xlsx",
    )

    save_transfer_export([{"economy": "05_PRC"}], scenarios=["Target"], output_dir=tmp_path)

    assert captured["mapping"][AUTO_BALANCE_PRODUCT_LABEL] == AUTO_BALANCE_LEAP_FUEL_NAME
    assert AUTO_BALANCE_PRODUCT_LABEL not in transfers.core.code_to_name_mapping


@pytest.mark.parametrize("measured", [0.5, 10.0, 12.7, 5000.0])
def test_auto_sizing_never_exceeds_the_efficiency_ceiling(measured: float) -> None:
    """The whole point of sizing: the ceiling can no longer be breached."""
    from codebase.configuration import workflow_config as cfg

    rows = _flow_rows([
        {"economy": "04_CHL", "flows": "08.02 Interproduct transfers",
         "products": "07.01 Motor gasoline", 2022: measured, 2023: 0.0},
    ])

    _, diagnostic = balance_one_sided_transfer_flow(
        rows, YEARS, "04_CHL", "08.02 Interproduct transfers"
    )

    ceiling = float(cfg.TRANSFORMATION_PROCESS_EFFICIENCY_MAX_PERCENT)
    assert diagnostic["max_implied_efficiency_percent"] <= ceiling + 1e-6
    # Never smaller than the floor, however tiny the measured side.
    assert diagnostic["counterpart_value"] >= (
        ONE_SIDED_TRANSFER_BALANCE_POLICY["minimum_counterpart_value"]
    )
