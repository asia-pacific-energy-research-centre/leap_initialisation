"""
inject_target_scenario.py

Copies Target-scenario rows from backup seed files into the current seed files.

Use case: supply_reconciliation_workflow.py was run with SCENARIOS = ["Reference",
"Current Accounts"] only, producing new seed files without Target rows.  The
backup directory contains the previous seed files (which had Target rows).  This
script splices those Target rows into the new files.

Usage:
    python scripts/inject_target_scenario.py

Both directories are hard-coded below; edit if needed.
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "outputs" / "leap_exports" / "supply_reconciliation"
BACKUP_DIR = SEED_DIR / "tgt backup"
ARCHIVE_DIR = SEED_DIR / "archive"

TARGET_SCENARIO = "Target"


# ---------------------------------------------------------------------------
# LEAP file helpers (mirrors patch_baseline_seeds._find_header_row logic)
# ---------------------------------------------------------------------------
def _find_header_row(raw: pd.DataFrame) -> tuple[list, pd.DataFrame]:
    for idx in range(min(8, len(raw))):
        vals = [str(v).strip().lower() for v in raw.iloc[idx].tolist()
                if str(v) not in ("nan", "")]
        if "branch path" in vals and "variable" in vals:
            header = raw.iloc[idx].tolist()
            data = raw.iloc[idx + 1:].copy()
            data.columns = header
            return header, data.dropna(how="all").reset_index(drop=True)
    raise ValueError("LEAP header row (Branch Path + Variable) not found")


def _read_seed(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="LEAP", header=None)
    _, data = _find_header_row(raw)
    return data


def _write_seed(path: Path, data: pd.DataFrame) -> None:
    cols = list(data.columns)
    bp_col = next((c for c in cols if str(c).strip().lower() == "branch path"), cols[0])

    preamble = {c: pd.NA for c in cols}
    preamble[bp_col] = "Area:"
    if "Scenario" in cols:
        preamble["Scenario"] = "Ver:"
    if "Region" in cols:
        preamble["Region"] = "2"

    full_df = pd.concat([
        pd.DataFrame([preamble]),
        pd.DataFrame([{c: pd.NA for c in cols}]),
        pd.DataFrame([cols], columns=cols),
        data,
    ], ignore_index=True)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, ARCHIVE_DIR / f"{path.stem}_pre_inject_{stamp}{path.suffix}")

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        full_df.to_excel(writer, sheet_name="LEAP", index=False, header=False)
        full_df.to_excel(writer, sheet_name="FOR_VIEWING", index=False, header=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    backup_files = sorted(BACKUP_DIR.glob("leap_import_baseline_seed_*.xlsx"))
    if not backup_files:
        print(f"[ERROR] No backup seed files found in {BACKUP_DIR}")
        sys.exit(1)

    for backup_path in backup_files:
        current_path = SEED_DIR / backup_path.name
        if not current_path.exists():
            print(f"[SKIP] No matching current file for {backup_path.name}")
            continue

        # Read Target rows from backup
        try:
            backup_data = _read_seed(backup_path)
        except Exception as exc:
            print(f"[ERROR] Could not read backup {backup_path.name}: {exc}")
            continue

        scen_col = next((c for c in backup_data.columns if str(c).strip().lower() == "scenario"), None)
        if scen_col is None:
            print(f"[WARN] No Scenario column in {backup_path.name}; skipping.")
            continue

        target_rows = backup_data[backup_data[scen_col].astype(str).str.strip() == TARGET_SCENARIO].copy()
        if target_rows.empty:
            print(f"[INFO] {backup_path.name}: no Target rows in backup; skipping.")
            continue

        # Read current file, strip any existing Target rows, append backup Target rows
        try:
            current_data = _read_seed(current_path)
        except Exception as exc:
            print(f"[ERROR] Could not read current {current_path.name}: {exc}")
            continue

        scen_col_cur = next((c for c in current_data.columns if str(c).strip().lower() == "scenario"), None)
        if scen_col_cur:
            n_removed = int((current_data[scen_col_cur].astype(str).str.strip() == TARGET_SCENARIO).sum())
            current_data = current_data[
                current_data[scen_col_cur].astype(str).str.strip() != TARGET_SCENARIO
            ].copy()
        else:
            n_removed = 0

        # Align columns: add any columns present in target_rows but missing from current
        for col in target_rows.columns:
            if col not in current_data.columns:
                current_data[col] = pd.NA
        target_rows = target_rows.reindex(columns=current_data.columns)

        combined = pd.concat([current_data, target_rows], ignore_index=True)

        _write_seed(current_path, combined)
        print(
            f"  {current_path.name}: removed {n_removed} existing Target rows, "
            f"injected {len(target_rows)} from backup."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
