#%%
"""Combine existing supply reconciliation exports into one LEAP import workbook.

This notebook-safe runner scans the current supply_reconciliation workbooks,
adds the latest aggregated-demand and other-loss/own-use proxy workbooks, and
writes a final combined workbook only for economies that have a complete source
set on disk.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions.baseline_seed_validation import BaselineSeedValidationError
from codebase.functions.supply_leap_io import write_per_economy_combined_workbooks
from codebase.utilities import workflow_common

# --- Stable paths ---
SUPPLY_RECONCILIATION_ROOT = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"
WORKBOOKS_DIR = SUPPLY_RECONCILIATION_ROOT / "workbooks"
OTHER_LOSS_DIR = REPO_ROOT / "outputs" / "leap_exports" / "standalone"
OUTPUT_DIR = SUPPLY_RECONCILIATION_ROOT / "combined_everything"

# --- Workflow settings ---
SCENARIOS = ["Current Accounts", "Reference", "Target"]
ECONOMY_PATTERN = re.compile(r"^supply_leap_imports_(\d{2}_[A-Za-z]+)_")


def _latest_matching_file(directory: Path, pattern: str) -> Path | None:
    """Return the newest matching file for a glob pattern."""
    directory = Path(directory)
    matches = sorted(
        directory.glob(pattern),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    return matches[-1] if matches else None


def _scenario_token(scenario: str) -> str:
    """Return the filename token used by the existing exports."""
    return workflow_common.format_filename_segment(str(scenario))


def _economies_from_supply_workbooks() -> list[str]:
    """Discover economies that have at least one supply workbook in the folder."""
    economies: set[str] = set()
    for path in WORKBOOKS_DIR.glob("supply_leap_imports_*_*.xlsx"):
        match = ECONOMY_PATTERN.match(path.name)
        if match:
            economies.add(match.group(1))
    return sorted(economies)


def _build_source_workbooks_for_economy(economy: str) -> tuple[dict[str, list[Path]], list[str]]:
    """Collect the newest workbook for each source family needed by the writer."""
    missing: list[str] = []

    supply = _latest_matching_file(
        WORKBOOKS_DIR,
        f"supply_leap_imports_{economy}_*.xlsx",
    )
    if supply is None:
        missing.append("supply_workflow")

    transformation_paths: list[Path] = []
    for scenario in SCENARIOS:
        scenario_token = _scenario_token(scenario)
        path = _latest_matching_file(
            WORKBOOKS_DIR,
            f"transformation_leap_imports_{economy}_{scenario_token}.xlsx",
        )
        if path is None:
            missing.append(f"transformation_workflow:{scenario}")
        else:
            transformation_paths.append(path)

    transfer_paths: list[Path] = []
    for scenario in SCENARIOS:
        scenario_token = _scenario_token(scenario)
        path = _latest_matching_file(
            WORKBOOKS_DIR,
            f"transfer_leap_imports_{economy}_{scenario_token}.xlsx",
        )
        if path is None:
            missing.append(f"transfers_workflow:{scenario}")
        else:
            transfer_paths.append(path)

    aggregated_demand = _latest_matching_file(
        WORKBOOKS_DIR,
        f"aggregated_demand_{economy}*.xlsx",
    )
    if aggregated_demand is None:
        missing.append("aggregated_demand_workflow")

    other_loss = _latest_matching_file(
        OTHER_LOSS_DIR,
        f"other_loss_own_use_proxy_{economy}*.xlsx",
    )
    if other_loss is None:
        missing.append("other_loss_own_use_proxy_workflow")

    if missing:
        return {}, missing

    assert supply is not None
    assert aggregated_demand is not None
    assert other_loss is not None

    return {
        "supply_workflow": [supply],
        "transformation_workflow": transformation_paths,
        "transfers_workflow": transfer_paths,
        "aggregated_demand_workflow": [aggregated_demand],
        "other_loss_own_use_proxy_workflow": [other_loss],
    }, []


def discover_complete_economies(economies: list[str] | None = None) -> tuple[list[str], dict[str, list[str]]]:
    """Return the economies that have a complete source set and a skip map."""
    economy_list = list(economies) if economies else _economies_from_supply_workbooks()
    complete: list[str] = []
    skipped: dict[str, list[str]] = {}
    for economy in economy_list:
        source_map, missing = _build_source_workbooks_for_economy(economy)
        if missing:
            skipped[economy] = missing
            continue
        if source_map:
            complete.append(economy)
    return complete, skipped


def run_combine_everything_workflow(
    *,
    economies: list[str] | None = None,
    output_dir: Path | str = OUTPUT_DIR,
) -> list[Path]:
    """Write the final combined workbook for each economy with complete inputs."""
    economy_list, skipped = discover_complete_economies(economies)
    if skipped:
        for economy, missing in skipped.items():
            print(f"[INFO] Skipping {economy}: missing {', '.join(missing)}")

    written: list[Path] = []
    for economy in economy_list:
        source_workbooks_by_workflow, _ = _build_source_workbooks_for_economy(economy)
        if not source_workbooks_by_workflow:
            continue
        try:
            out = write_per_economy_combined_workbooks(
                economies=[economy],
                output_dir=output_dir,
                source_workbooks_by_workflow=source_workbooks_by_workflow,
                enforce_validation=False,
            )
        except BaselineSeedValidationError as exc:
            print(f"[WARN] [{economy}] combined workbook was not written: {exc}")
            continue
        except Exception as exc:
            print(f"[WARN] [{economy}] combined workbook failed: {exc!r}")
            continue
        written.extend(out)
    return written


# --- Run toggles ---
RUN_COMBINE_EVERYTHING = True
ONLY_ECONOMIES: list[str] = []


if __name__ == "__main__":
    if RUN_COMBINE_EVERYTHING:
        _economies = ONLY_ECONOMIES or None
        _written = run_combine_everything_workflow(economies=_economies)
        print(f"[INFO] Wrote {len(_written)} combined workbook(s).")

#%%
