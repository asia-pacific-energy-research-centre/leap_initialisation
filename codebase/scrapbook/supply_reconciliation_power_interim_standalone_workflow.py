#%%
"""Generate electricity/CHP/heat-plant interim workbooks outside the main run.

The long-running supply_reconciliation_workflow only builds these three power
interim modules when RUN_ELECTRICITY_HEAT_INTERIM is True for the active
preset. Economies processed while that flag was effectively off (see the
_sync_results_saver_overrides propagation bug) never got an interim workbook.
This side runner builds them directly from ESTO/9th data for any economy that
already has a supply workbook on disk, writing into the same workbooks/
folder so supply_reconciliation_combine_everything_workflow.py can pick them
up as the "electricity_heat_interim_workflow" source.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions import transformation_analysis_utils as core
from codebase import electricity_heat_interim_workflow
from codebase.scrapbook.supply_reconciliation_combine_everything_workflow import (
    WORKBOOKS_DIR,
    _economies_from_supply_workbooks,
)

SCENARIOS = ["Current Accounts", "Reference", "Target"]


def run_power_interim_standalone(
    economies: list[str] | None = None,
) -> list[Path]:
    """Build electricity+heat interim workbooks for the given (or discovered) economies."""
    economy_list = list(economies) if economies else _economies_from_supply_workbooks()
    if not economy_list:
        print("[INFO] No economies with supply workbooks found; nothing to do.")
        return []
    core.prepare_transformation_assets()
    written = electricity_heat_interim_workflow.assemble_electricity_heat_interim_workbook(
        economies=economy_list,
        scenarios=SCENARIOS,
        export_output_dir=WORKBOOKS_DIR,
    )
    return written


# --- Run toggles ---
RUN_POWER_INTERIM_STANDALONE = True
ONLY_ECONOMIES: list[str] = []


if __name__ == "__main__":
    if RUN_POWER_INTERIM_STANDALONE:
        _economies = ONLY_ECONOMIES or None
        _written = run_power_interim_standalone(economies=_economies)
        print(f"[INFO] Wrote {len(_written)} power interim workbook(s).")

#%%
