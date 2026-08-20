"""Focused coverage for scenario-aware transfer fallback classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase import transfers_workflow  # noqa: E402


def test_projection_availability_classifies_all_four_states() -> None:
    historical = pd.DataFrame([
        {"economy": "01_AUS", "flows": "08.99 Transfers nonspecified", "products": "07.01 Motor gasoline", 2022: 10.0},
        {"economy": "02_BD", "flows": "08.99 Transfers nonspecified", "products": "07.01 Motor gasoline", 2022: 20.0},
        {"economy": "03_CDA", "flows": "08.99 Transfers nonspecified", "products": "07.01 Motor gasoline", 2022: 0.0},
        {"economy": "04_CHL", "flows": "08.99 Transfers nonspecified", "products": "07.01 Motor gasoline", 2022: 15.0},
    ])
    ninth = pd.DataFrame([
        {"economy": "01_AUS", "scenarios": "reference", "subtotal_results": False, 2023: 1e-12, 2024: 0.0},
        {"economy": "01_AUS", "scenarios": "reference", "subtotal_results": False, 2023: -1e-12, 2024: 0.0},
        {"economy": "02_BD", "scenarios": "reference", "subtotal_results": False, 2023: 0.0, 2024: 0.0},
        {"economy": "03_CDA", "scenarios": "reference", "subtotal_results": False, 2023: 0.0, 2024: 0.0},
    ])

    result = transfers_workflow.classify_transfer_projection_availability(
        historical, ninth, "Reference", 2022, [2023, 2024]
    ).set_index("economy")

    assert result.loc["01_AUS", "projection_availability"] == "projection_supplied"
    assert result.loc["02_BD", "projection_availability"] == "projection_unavailable"
    assert result.loc["03_CDA", "projection_availability"] == "structural_zero"
    assert result.loc["04_CHL", "projection_availability"] == "no_ninth_rows"


def test_fallback_preserves_explicit_projection_zeroes() -> None:
    transfers = pd.DataFrame([
        {"economy": "01_AUS", "flows": "08.99 Transfers nonspecified", 2022: 10.0, 2023: 0.0},
        {"economy": "02_BD", "flows": "08.99 Transfers nonspecified", 2022: 20.0, 2023: 0.0},
    ])
    availability = pd.DataFrame([
        {"economy": "01_AUS", "projection_availability": "projection_supplied"},
        {"economy": "02_BD", "projection_availability": "projection_unavailable"},
    ])

    result = transfers_workflow.apply_transfer_projection_fallback(
        transfers, availability, 2022, [2023]
    ).set_index("economy")

    assert result.loc["01_AUS", 2023] == 0.0
    assert result.loc["02_BD", 2023] == 20.0
