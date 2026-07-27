#%%
"""
Notebook controls for the read-only baseline-seed balance diagnostic.

The supporting comparison, mapping-cardinality, and output functions live in
``codebase/functions/baseline_seed_balance_diagnostics.py``.
"""

from codebase.functions.baseline_seed_balance_diagnostics import (
    DEFAULT_OUTPUT_DIR,
    run_baseline_seed_balance_diagnostics,
)


# --- Notebook run controls ----------------------------------------------------

RUN_DIAGNOSTICS = False
ECONOMIES = ["20_USA"]
YEARS = [2022, 2023]
SCENARIOS = ["Reference", "Target"]
DATE_IDS_BY_ECONOMY: dict[str, dict[str, str | None]] = {}
OUTPUT_DIR = DEFAULT_OUTPUT_DIR

if RUN_DIAGNOSTICS:
    DIAGNOSTIC_RESULTS = run_baseline_seed_balance_diagnostics(
        economies=ECONOMIES,
        years=YEARS,
        scenarios=SCENARIOS,
        date_ids_by_economy=DATE_IDS_BY_ECONOMY,
        output_dir=OUTPUT_DIR,
    )

#%%
