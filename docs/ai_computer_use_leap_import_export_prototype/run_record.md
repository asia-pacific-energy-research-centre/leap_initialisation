# AUS GUI pilot run record -- 2026-08-20

## Outcome

The Target scenario completed successfully. The result is included as
`artifacts/AUS TGT 20260820 CHATGPT.xlsx`.

The Reference scenario has **not** been exported. Computer Use was stopped by
the operator while a blank Reference destination workbook was being created;
no further GUI action was taken and the recurring wait/check automation was
cancelled.

## Inputs and area

| Item | Value |
| --- | --- |
| Economy | `01_AUS` |
| LEAP area title | `aus clean slate 18_08` |
| Local backup selected | `LEAP_backups/AUS clean slate 18_08.leap` |
| Baseline seed | `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/SEED_ALL_TEMPLATE_20260820_R3_01_AUS/leap_import_baseline_seed_01_AUS_20260820.xlsx` |
| Seed SHA-256 recorded in register | `eca94623d675db58ee410354db4bbf7ce4fa05dc37e4d6ed3c9b6f17a57eaf74` |

## Completed GUI sequence

1. Opened the staged local `.leap` backup through LEAP, without manually
   touching `C:\LEAP_Areas`.
2. Activated the seed workbook's `LEAP` sheet and used **Analysis -> Import
   from Excel Template**.
3. Selected **Data**; left **Only replace constants, Interp, Step and Smooth
   expressions** unchecked; selected matching branches, variables, scenarios,
   and regions by name.
4. Accepted the expected blank-Excel-area versus `aus clean slate 18_08` area
   warning. No other import error or rejected-row warning occurred.
5. Saved through LEAP's own Save control. LEAP confirmed there were no pending
   changes.
6. Opened Results, which triggered calculation. LEAP completed in **30.58
   seconds**.
7. Opened Energy Balance and confirmed:
   - Target scenario
   - `Columns: Fuels`
   - `Thousand Petajoule`
   - `Detail: Sectors & Subsectors (Level 2)`
   - visibly indented balance rows
8. Used the green Excel button and selected **All**. LEAP completed the full
   Target time-series export.
9. Saved the intended named workbook explicitly after export and verified its
   on-disk contents with a read-only check.

## Target-output verification

| Check | Result |
| --- | --- |
| Output | `AUS TGT 20260820 CHATGPT.xlsx` |
| Sheet count | 40 |
| Years | 2022--2060 inclusive |
| First-sheet title | `Energy Balance for Area "aus clean slate 18_08"` |
| First-sheet scenario | Target |
| Units | Thousand Petajoule |
| SHA-256 of archived copy | `3bd59fe5eed9945e688ef6fa3483f982b0a6aba8d19a005c12d230c9b9cb7dd5` |

## Operational lessons

- Opening an Excel file with a direct command is appropriate for known local
  files. Use LEAP's GUI only for its own Open, Import, Results, and Export
  operations.
- LEAP writes the export into the active Excel workbook, but the workbook can
  contain the data only in memory until it is explicitly saved. A file-size or
  read-only verification before saving can therefore report a stale blank
  workbook.
- Before each export, activate **and click a normal worksheet cell** in the
  declared destination workbook, return to LEAP, select **All**, then save the
  Excel workbook and inspect its sheets on disk. This is stronger than relying
  on the Excel window title alone.
- For Level 2 exports, leave LEAP untouched and check visible completion at
  10-minute intervals. For Level 4 or more detailed exports, use one-hour
  intervals.
- Checkpoint screenshots are useful only at area confirmation, import outcome,
  export settings/destination, and completed export; they are not needed for
  every intermediate action.

## Resume plan: Reference

1. Create and save a blank workbook at
   `data/leap balances exports/01_AUS/AUS REF 20260820 CHATGPT.xlsx`.
2. Click a normal cell in that workbook so it is LEAP's active Excel target.
3. In LEAP Energy Balance retain Columns: Fuels, Thousand Petajoule, and Level
   2; change only the Scenario dropdown to **Reference** and wait for redraw.
4. Use the green Excel button -> **All**; wait on the Level-2 policy.
5. Save the workbook, inspect all 2022--2060 sheets and its first-sheet area,
   scenario, units, and hierarchy, then add a copy and its SHA-256 to this
   package.

Do not upload either export to an external dashboard unless the operator gives
an explicit confirmation immediately before upload.
