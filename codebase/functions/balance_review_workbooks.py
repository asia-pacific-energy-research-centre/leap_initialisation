#%%
"""Build one balance-shaped comparison workbook per selected review cell."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from codebase.utilities.leap_balance_export_resolver import BalanceExportSheet


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILDER_PATH = REPO_ROOT / "codebase" / "balance_structure_review_workbook_workflow.mjs"
DEFAULT_TEMP_ROOT = REPO_ROOT / ".tmp" / "balance_reviews"


def _resolve(path: Path | str) -> Path:
    raw = Path(str(path).replace("\\", "/"))
    return raw if raw.is_absolute() else REPO_ROOT / raw


def _safe_filename_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip())
    return token.strip("_") or "unknown"


def _resolve_node_executable(node_executable: Path | str | None) -> str:
    if node_executable is not None:
        resolved = _resolve(node_executable)
        if not resolved.exists():
            raise FileNotFoundError(f"Configured Node executable does not exist: {resolved}")
        return str(resolved)
    discovered = shutil.which("node")
    if discovered:
        return discovered
    raise FileNotFoundError(
        "Node.js was not found. Set NODE_EXECUTABLE in the notebook workflow "
        "to the Node runtime that provides @oai/artifact-tool."
    )


def build_balance_review_workbooks(
    *,
    diagnostic_results: dict[str, dict[str, Any]],
    diagnostics_directory: Path | str,
    output_directory: Path | str | None = None,
    node_executable: Path | str | None = None,
    builder_path: Path | str = DEFAULT_BUILDER_PATH,
    render_previews: bool = False,
) -> list[dict[str, Any]]:
    """Build isolated review workbooks for every selected economy/scenario/year."""
    diagnostics_dir = _resolve(diagnostics_directory)
    output_dir = (
        _resolve(output_directory)
        if output_directory is not None
        else diagnostics_dir / "comparison_workbooks"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    builder = _resolve(builder_path)
    if not builder.exists():
        raise FileNotFoundError(f"Balance review workbook builder does not exist: {builder}")
    node = _resolve_node_executable(node_executable)

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
            temp_directory = (
                DEFAULT_TEMP_ROOT
                / _safe_filename_token(economy)
                / f"{scenario_token}_{selected.year}"
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "BALANCE_REVIEW_ECONOMY": str(economy),
                    "BALANCE_REVIEW_SOURCE_WORKBOOK": str(selected.path),
                    "BALANCE_REVIEW_SOURCE_SHEET": str(selected.sheet_name),
                    "BALANCE_REVIEW_DIAGNOSTICS_DIRECTORY": str(diagnostics_dir),
                    "BALANCE_REVIEW_OUTPUT_WORKBOOK": str(output_path),
                    "BALANCE_REVIEW_TEMP_DIRECTORY": str(temp_directory),
                    "BALANCE_REVIEW_RENDER_PREVIEWS": (
                        "true" if render_previews else "false"
                    ),
                }
            )
            completed = subprocess.run(
                [node, str(builder)],
                cwd=REPO_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            try:
                json_start = completed.stdout.rfind("\n{")
                payload = (
                    completed.stdout[json_start + 1 :]
                    if json_start >= 0
                    else completed.stdout
                )
                build_result = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "Balance review builder completed but returned invalid JSON. "
                    f"stdout={completed.stdout[-2000:]!r}, "
                    f"stderr={completed.stderr[-2000:]!r}"
                ) from exc
            build_results.append(build_result)
            print(f"[INFO] Wrote balance review workbook: {output_path}")
    return build_results


#%%
