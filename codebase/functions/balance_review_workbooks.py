#%%
"""Build one balance-shaped comparison workbook per selected review cell."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

from codebase.functions.balance_review_workbook_builder import (
    build_balance_structure_review_workbook,
)
from codebase.utilities.leap_balance_export_resolver import BalanceExportSheet


REPO_ROOT = Path(__file__).resolve().parents[2]
def _resolve(path: Path | str) -> Path:
    raw = Path(str(path).replace("\\", "/"))
    return raw if raw.is_absolute() else REPO_ROOT / raw


def _safe_filename_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip())
    return token.strip("_") or "unknown"


def build_balance_review_workbooks(
    *,
    diagnostic_results: dict[str, dict[str, Any]],
    diagnostics_directory: Path | str,
    output_directory: Path | str | None = None,
    render_previews: bool = False,
) -> list[dict[str, Any]]:
    """Build Python-only review workbooks for each selected review cell."""
    if render_previews:
        print(
            "[WARN] render_previews=True is not implemented by the Python workbook "
            "builder; the XLSX files will still be created and verified structurally."
        )
    diagnostics_dir = _resolve(diagnostics_directory)
    output_dir = (
        _resolve(output_directory)
        if output_directory is not None
        else diagnostics_dir / "comparison_workbooks"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    build_results: list[dict[str, Any]] = []
    for economy, result in diagnostic_results.items():
        selected_sheets: Sequence[BalanceExportSheet] = result.get(
            "selected_balance_sheets",
            [],
        )
        if not selected_sheets:
            raise ValueError(
                f"No selected balance sheets were recorded for {economy}; "
                "rerun the diagnostic with the current exact-sheet selector."
            )
        for selected in selected_sheets:
            scenario_token = selected.scenario_code.lower()
            output_path = output_dir / (
                f"balance_review_{_safe_filename_token(economy)}_"
                f"{scenario_token}_{selected.year}.xlsx"
            )
            build_result = build_balance_structure_review_workbook(
                economy=str(economy),
                source_workbook=selected.path,
                source_sheet_name=selected.sheet_name,
                diagnostics_directory=diagnostics_dir,
                output_workbook=output_path,
            )
            build_results.append(build_result)
            print(f"[INFO] Wrote balance review workbook: {output_path}")
    return build_results


#%%
