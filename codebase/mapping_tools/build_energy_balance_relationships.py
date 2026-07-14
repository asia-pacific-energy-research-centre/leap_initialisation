#%%
"""
Build compiled LEAP / ESTO / 9th energy-balance relationships.

This workflow reads outlook_mappings_master.xlsx, applies explicit rollup rules
before cardinality checks, preserves removed rows as excluded relationships,
and writes generated relationship and QA outputs.
"""

#%%
from pathlib import Path
import sys

import pandas as pd

from codebase.mapping_tools.excel_sheet_utils import safe_excel_sheet_name

#%%
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.mapping_tools.mapping_rollups import (  # noqa: E402
    build_all_effective_mappings,
    build_qa_tables,
    build_relationship_catalogue,
    build_relationship_rows,
)

#%%
MAPPING_WORKBOOK_PATH = Path(r"C:\Users\Work\github\leap_mappings\config\outlook_mappings_master.xlsx")
OUTPUT_DIR = REPO_ROOT / "results" / "mapping_relationships"
QA_DIR = OUTPUT_DIR / "qa"

OUTPUT_CSV_PATH = OUTPUT_DIR / "energy_balance_relationships.csv"
OUTPUT_XLSX_PATH = OUTPUT_DIR / "energy_balance_relationships.xlsx"
RELATIONSHIP_CATALOGUE_CSV_PATH = OUTPUT_DIR / "relationship_catalogue.csv"
ROLLED_MAPPING_ROWS_CSV_PATH = OUTPUT_DIR / "rolled_mapping_rows.csv"

RUN_BUILD_ENERGY_BALANCE_RELATIONSHIPS = True
FAIL_ON_MANY_TO_MANY_AFTER_ROLLUP = False


#%%
def save_relationship_outputs(
    relationship_df: pd.DataFrame,
    relationship_catalogue_df: pd.DataFrame,
    rolled_mapping_rows_df: pd.DataFrame,
    qa_tables: dict[str, pd.DataFrame],
    output_dir: Path,
    output_csv_path: Path,
    output_xlsx_path: Path,
    relationship_catalogue_csv_path: Path,
    rolled_mapping_rows_csv_path: Path,
    qa_dir: Path,
) -> None:
    """Save relationship, catalogue, rolled-row, and QA outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    relationship_df.to_csv(output_csv_path, index=False)
    relationship_catalogue_df.to_csv(relationship_catalogue_csv_path, index=False)
    rolled_mapping_rows_df.to_csv(rolled_mapping_rows_csv_path, index=False)
    for qa_name, qa_df in qa_tables.items():
        qa_df.to_csv(qa_dir / f"{qa_name}.csv", index=False)

    with pd.ExcelWriter(output_xlsx_path, engine="openpyxl") as writer:
        relationship_df.to_excel(writer, sheet_name="energy_balance_relationships", index=False)
        relationship_catalogue_df.to_excel(writer, sheet_name="relationship_catalogue", index=False)
        rolled_mapping_rows_df.to_excel(writer, sheet_name="rolled_mapping_rows", index=False)
        used_sheet_names: set[str] = {
            "energy_balance_relationships",
            "relationship_catalogue",
            "rolled_mapping_rows",
        }
        for qa_name, qa_df in qa_tables.items():
            sheet_name = safe_excel_sheet_name(qa_name, used_sheet_names)
            qa_df.to_excel(writer, sheet_name=sheet_name, index=False)


def build_energy_balance_relationships(
    mapping_workbook_path: Path,
    output_dir: Path,
    fail_on_many_to_many_after_rollup: bool = False,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build compiled relationship outputs from the mapping workbook."""
    output_csv_path = output_dir / "energy_balance_relationships.csv"
    output_xlsx_path = output_dir / "energy_balance_relationships.xlsx"
    relationship_catalogue_csv_path = output_dir / "relationship_catalogue.csv"
    rolled_mapping_rows_csv_path = output_dir / "rolled_mapping_rows.csv"
    qa_dir = output_dir / "qa"

    effective_tables, rollup_qa = build_all_effective_mappings(mapping_workbook_path, include_reverse=True)
    relationship_df = build_relationship_rows(effective_tables)
    relationship_catalogue_df = build_relationship_catalogue(relationship_df)
    rolled_mapping_rows_df = pd.concat(effective_tables.values(), ignore_index=True)
    qa_tables = build_qa_tables(effective_tables, relationship_df, rollup_qa)

    save_relationship_outputs(
        relationship_df=relationship_df,
        relationship_catalogue_df=relationship_catalogue_df,
        rolled_mapping_rows_df=rolled_mapping_rows_df,
        qa_tables=qa_tables,
        output_dir=output_dir,
        output_csv_path=output_csv_path,
        output_xlsx_path=output_xlsx_path,
        relationship_catalogue_csv_path=relationship_catalogue_csv_path,
        rolled_mapping_rows_csv_path=rolled_mapping_rows_csv_path,
        qa_dir=qa_dir,
    )

    many_to_many_after = qa_tables["qa_many_to_many_after_rollup"]
    print(f"Relationship rows created: {len(relationship_df):,}")
    print(f"Relationship catalogue rows: {len(relationship_catalogue_df):,}")
    print(f"Rolled mapping rows: {len(rolled_mapping_rows_df):,}")
    print(f"Many-to-many before rollup rows: {len(qa_tables['qa_many_to_many_before_rollup']):,}")
    print(f"Many-to-many after rollup rows: {len(many_to_many_after):,}")
    print(f"Duplicate effective relationships: {len(qa_tables['qa_duplicate_effective_relationships']):,}")
    print(f"Wrote relationships CSV: {output_csv_path}")
    print(f"Wrote relationships workbook: {output_xlsx_path}")
    print(f"Wrote QA files to: {qa_dir}")

    if not many_to_many_after.empty:
        message = (
            "High severity: unresolved many-to-many mappings remain after rollup. "
            f"Review {qa_dir / 'qa_many_to_many_after_rollup.csv'}."
        )
        if fail_on_many_to_many_after_rollup:
            raise ValueError(message)
        print(message)

    return relationship_df, qa_tables


#%%
try:
    if RUN_BUILD_ENERGY_BALANCE_RELATIONSHIPS:
        RELATIONSHIP_DF, QA_TABLES = build_energy_balance_relationships(
            mapping_workbook_path=MAPPING_WORKBOOK_PATH,
            output_dir=OUTPUT_DIR,
            fail_on_many_to_many_after_rollup=FAIL_ON_MANY_TO_MANY_AFTER_ROLLUP,
        )
except Exception as exc:
    print("Energy-balance relationship build failed.")
    print(f"Error: {exc}")
    raise

#%%
