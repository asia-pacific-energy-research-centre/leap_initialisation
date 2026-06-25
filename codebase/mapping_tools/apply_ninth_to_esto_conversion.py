#%%
"""
Convert raw 9th Outlook rows to ESTO-style flow/product rows.

This script consumes energy_balance_relationships rows for the
ninth_to_esto_balance_conversion use case and writes grouped ESTO rows.
"""

#%%
from pathlib import Path

import pandas as pd

#%%
REQUIRED_NINTH_COLUMNS = ["ninth_sector", "ninth_fuel", "value"]
GROUP_COLUMNS = ["source_system", "economy", "scenario", "year", "target_flow", "target_product"]

#%%
def _find_repo_root(start_path: Path) -> Path:
    """Find the leap_utilities repo root from a nested workflow path."""
    for candidate in [start_path, *start_path.parents]:
        if (candidate / "AGENTS.md").exists() and (candidate / "config" / "leap_mappings.xlsx").exists():
            return candidate
    raise FileNotFoundError(f"Could not find repo root above: {start_path}")


def read_table(path: Path) -> pd.DataFrame:
    """Read CSV or Excel input."""
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def load_ninth_to_esto_relationships(relationships_path: Path) -> pd.DataFrame:
    """Load included 9th-to-ESTO conversion relationships."""
    relationships_df = pd.read_csv(relationships_path)
    relationships_df["include_in_use_case"] = relationships_df["include_in_use_case"].astype(str).str.lower().isin(["true", "1", "yes"])
    mapping_df = relationships_df[
        (relationships_df["use_case"] == "ninth_to_esto_balance_conversion")
        & relationships_df["include_in_use_case"]
        & (relationships_df["source_system"] == "NINTH")
        & (relationships_df["target_system"] == "ESTO")
    ].copy()
    return mapping_df


def convert_ninth_results_to_esto(
    ninth_results_df: pd.DataFrame,
    relationships_df: pd.DataFrame,
) -> pd.DataFrame:
    """Join raw 9th rows to ESTO targets and aggregate values."""
    missing_columns = [column for column in REQUIRED_NINTH_COLUMNS if column not in ninth_results_df.columns]
    if missing_columns:
        raise ValueError(f"9th results are missing required columns: {missing_columns}")

    merged_df = ninth_results_df.merge(
        relationships_df,
        left_on=["ninth_sector", "ninth_fuel"],
        right_on=["source_flow", "source_product"],
        how="left",
    )
    missing_mapping_df = merged_df[merged_df["target_flow"].isna() | merged_df["target_product"].isna()]
    if not missing_mapping_df.empty:
        print(f"Warning: 9th result rows without included ESTO mapping: {len(missing_mapping_df):,}")

    merged_df["source_system"] = "NINTH"
    keep_group_columns = [column for column in GROUP_COLUMNS if column in merged_df.columns]
    converted_df = (
        merged_df.dropna(subset=["target_flow", "target_product"])
        .groupby(keep_group_columns, as_index=False)["value"]
        .sum()
    )
    return converted_df


def run_conversion(
    ninth_results_path: Path,
    relationships_path: Path,
    output_path: Path,
) -> pd.DataFrame:
    """Run 9th-to-ESTO conversion."""
    ninth_results_df = read_table(ninth_results_path)
    relationships_df = load_ninth_to_esto_relationships(relationships_path)
    converted_df = convert_ninth_results_to_esto(ninth_results_df, relationships_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    converted_df.to_csv(output_path, index=False)
    print(f"Raw 9th rows read: {len(ninth_results_df):,}")
    print(f"Conversion relationships used: {len(relationships_df):,}")
    print(f"Converted ESTO rows written: {len(converted_df):,}")
    print(f"Wrote converted results: {output_path}")
    return converted_df

#%%
# User-tuned constants / flags.
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = _find_repo_root(SCRIPT_PATH.parent)

RELATIONSHIP_DIR = REPO_ROOT / "results" / "mapping_relationships"
NINTH_RESULTS_PATH = RELATIONSHIP_DIR / "raw_ninth_results_placeholder.csv"
RELATIONSHIPS_PATH = RELATIONSHIP_DIR / "energy_balance_relationships.csv"
OUTPUT_PATH = RELATIONSHIP_DIR / "ninth_results_converted_to_esto.csv"

RUN_NINTH_TO_ESTO_CONVERSION = False

#%%
try:
    if RUN_NINTH_TO_ESTO_CONVERSION:
        run_conversion(
            ninth_results_path=NINTH_RESULTS_PATH,
            relationships_path=RELATIONSHIPS_PATH,
            output_path=OUTPUT_PATH,
        )
    else:
        print("Set RUN_NINTH_TO_ESTO_CONVERSION = True after setting NINTH_RESULTS_PATH.")
except Exception as exc:
    print("9th-to-ESTO conversion failed.")
    print(f"Error: {exc}")
    raise

#%%
