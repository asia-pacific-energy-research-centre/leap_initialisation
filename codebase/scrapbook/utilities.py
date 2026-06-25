#%%
# Summary: Label and optionally export subtotal rows in the ESTO (Matt) dataset.
import os
from pathlib import Path
import pandas as pd

from codebase.utilities.master_config import read_config_table

# Production-quality functions live in esto_reference_loader; re-exported here
# for any existing scrapbook callers.
from codebase.utilities.esto_reference_loader import (
    apply_esto_subtotal_mapping as apply_matt_subtotal_mapping,
    filter_esto_subtotals as filter_matt_subtotals,
    load_augmented_reference_tables,
    save_subtotal_labeled_data,
)
#%%

#%%
######### CONSTANTS (UNLIKELY TO CHANGE) #########
ENABLE_DEBUG_BREAKPOINTS = True
#%%

#%%
######### FUNCTIONS #########
def ensure_repo_root():
    """Move to repo root if running from the scrapbook folder."""
    try:
        if os.getcwd().endswith("scrapbook"):
            os.chdir("../../")
    except Exception as exc:
        print(f"Failed to set repo root: {exc}")
        try_debug_breakpoint()
        raise


def try_debug_breakpoint():
    """Trigger a debug breakpoint when enabled (safe to call anywhere)."""
    if not ENABLE_DEBUG_BREAKPOINTS:
        return
    try:
        breakpoint()
    except Exception as breakpoint_exc:
        print(f"Debug breakpoint failed: {breakpoint_exc}")



######### CONSTANTS (LIKELY TO CHANGE) #########
RUN_LABEL_SUBTOTALS = False
ESTO_DATA_PATH = "data/00APEC_2024_low.csv"
SUBTOTAL_MAPPING_PATH = "config/ESTO_subtotal_mapping.xlsx"
SAVE_ESTO_SUBTOTAL_LABELED = False
ESTO_SUBTOTAL_LABELED_OUTPUT_PATH = "data/00APEC_2024_low_with_subtotals.csv"
#%%

#%%
######### RUN LABELING (TOGGLE) #########
if RUN_LABEL_SUBTOTALS:
    try:
        ensure_repo_root()
        raw_df = read_config_table(ESTO_DATA_PATH)
        labeled = apply_matt_subtotal_mapping(raw_df, SUBTOTAL_MAPPING_PATH)
        if SAVE_ESTO_SUBTOTAL_LABELED:
            save_subtotal_labeled_data(
                labeled,
                ESTO_SUBTOTAL_LABELED_OUTPUT_PATH,
                "ESTO (Matt) data",
            )
        cleaned = filter_matt_subtotals(labeled)
        print(
            "Subtotal labeling complete. "
            f"Rows: raw={raw_df.shape[0]}, labeled={labeled.shape[0]}, "
            f"cleaned={cleaned.shape[0]}"
        )
    except Exception as exc:
        print(f"Failed to run subtotal labeling: {exc}")
        try_debug_breakpoint()
#%%
