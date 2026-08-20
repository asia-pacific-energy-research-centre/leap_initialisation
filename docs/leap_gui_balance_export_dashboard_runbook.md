# LEAP GUI balance export and dashboard review runbook

## Purpose

This is the supervised, repeatable route from a completed LEAP-import workbook
to a durable dashboard-review archive. It is written both for an operator and
for a GUI-using agent working beside that operator.

The outcome is one canonical raw LEAP Energy Balance workbook per
economy/scenario, followed by a completed web-review run and a locally saved
ZIP archive. The review app is diagnostic: it does **not** modify the LEAP area.

## Scope and responsibilities

Use a copied/sandbox LEAP area for a new seed or experiment. Do not import into
a colleague's open area or a production area without the model owner's explicit
approval.

The operator must provide or confirm:

- the intended LEAP area and the workbook to import;
- the scenario to export (`Reference` or `Target`);
- the economy code, such as `01_AUS` or `20_USA`;
- the review year(s); and
- approval that the produced export is the one to retain.

A GUI agent may navigate, wait for screens to settle, select the declared
scenario, export, upload, and download. It must stop for the operator if the
visible LEAP area, workbook, scenario, or economy identity differs from the
declared one. It must not guess.

## Naming and storage contract

Store the canonical workbook directly in:

```text
data/leap balances exports/<ECONOMY>/
```

For resolver-managed source exports, use this filename, with an ISO date to
avoid day/month ambiguity:

```text
full model output all years YYYYMMDD REF.xlsx
full model output all years YYYYMMDD TGT.xlsx
```

For example, an Australia Reference export made on 20 August 2026 is:

```text
data/leap balances exports/01_AUS/full model output all years 20260820 REF.xlsx
```

`REF` is for `Reference`; `TGT` is for `Target`. The resolver scans only files
directly in the economy folder and normally selects the newest recognized date.
Move superseded exports into that economy's `archive/` folder so they cannot be
selected accidentally. See [the raw-export README](../data/leap%20balances%20exports/README.md)
for the full resolver contract.

For a GUI-agent export intended for immediate upload to the review website, use
the visible, agent-attributed filename:

```text
<ECONOMY_SHORT> <SCENARIO_CODE> <YYYYMMDD> CHATGPT.xlsx
```

For example:

```text
data/leap balances exports/01_AUS/AUS TGT 20260820 CHATGPT.xlsx
```

The review website reads the economy and scenario from the workbook sheets, so
this descriptive filename is safe for an upload. It is *not* a resolver-managed
canonical input name: move it to `archive/` after the website run, or rename a
verified copy to the resolver-safe `full model output all years ...` pattern if
another workflow must discover it automatically.

## Before starting

Record the following in the run log or handover note before touching LEAP:

| Item | Example |
|---|---|
| Economy | `01_AUS` |
| LEAP area shown in the title bar | `aus clean slate 20_08` |
| Imported workbook | `leap_import_baseline_seed_01_AUS_20260820.xlsx` |
| Scenario to export | `Reference` (`REF`) |
| Review year(s) | `2022, 2030, 2040` |
| Export destination | `data/leap balances exports/01_AUS/AUS TGT 20260820 CHATGPT.xlsx` |

Confirm that no calculation, import, or export is already running. A stale or
half-loaded LEAP screen is not a safe starting point.

### Excel focus rule (critical)

LEAP uses the **last Excel workbook clicked/activated** for both Excel imports
and Energy Balance exports. Treat the active workbook, not merely an open
workbook, as part of the command.

- Before an import, open the declared baseline seed, click it to make it the
  active Excel workbook, then start the LEAP import. Do not click another open
  workbook between that activation and the import command.
- Before an export, close the baseline seed. Create and save a **new blank
  workbook** in the intended economy folder with the complete final filename,
  for example `AUS TGT 20260820 CHATGPT.xlsx`. Click that workbook's `LEAP`
  worksheet tab (shown in the supplied example) or otherwise activate it last.
  Do not click another workbook until LEAP finishes exporting.
- If more than one Excel workbook is open and the last active workbook is not
  known with certainty, stop and re-establish the intended one. Never export
  into the baseline seed and then try to recover it by copying sheets.

## GUI procedure

### 1. Import the workbook into LEAP

1. Open the declared workbook in Excel **before** starting the LEAP import and
   click it to make it the last active workbook. LEAP discovers the workbook
   through the open Excel session; do not use **Area → Install from File**,
   which is for a LEAP area rather than a seed workbook.
2. Open the declared LEAP area and confirm its name in the title bar or area
   selector against the run log.
3. In LEAP's top navigation, select **Analysis → Import from Excel Template**.

   ![Analysis menu with Import from Excel Template selected](assets/leap_gui_balance_runbook/02_analysis_import_menu.png)

4. In **Import from Excel**, choose **Data**. Leave **Only replace constants,
   Interp, Step and Smooth expressions** unchecked. Check **Match branches,
   variables, scenarios & regions by names instead of by IDs**, then select
   **OK**.

   ![Required Import from Excel settings](assets/leap_gui_balance_runbook/01_import_settings.png)

5. Wait for the import to finish. Do not click through a progress dialog or
   assume a frozen-looking screen has completed.
6. A warning that the workbook and LEAP area names differ is expected for this
   workflow and may be accepted. For any other import error or rejected-row
   message, stop immediately, leave the error visible for the operator, and do
   not attempt a workaround or retry.
7. Recalculate the model if LEAP requires it after the import. Wait until the
   calculation has completed and the interface is responsive.

Success condition: the intended workbook has been accepted into the intended
LEAP area, without an unresolved warning.

### 2. Open and verify Energy Balance

1. Select **Energy Balance** from the left-side results/navigation pane.

   ![Energy Balance selected in the left navigation](assets/leap_gui_balance_runbook/03_energy_balance_navigation.png)

2. Wait for the table to load fully. A table refresh, spinner, disabled controls,
   or blank data grid means it is still loading.
3. Find the **Details** control. Set it to **Level 2**. If it is already at
   Level 2 or a more detailed setting, leave it there.

   ![Energy Balance controls before changing detail](assets/leap_gui_balance_runbook/04_balance_controls.png)

   In the dropdown, choose **Sectors & Subsectors (Level 2)**.

   ![Detail dropdown with Sectors and Subsectors Level 2 selected](assets/leap_gui_balance_runbook/05_detail_level2.png)

4. Wait again for the balance grid to redraw. Confirm that at least one child
   row is visibly indented beneath a parent row. This is the practical proof of
   `Level 2+` detail.
5. Find the scenario dropdown. Read its current value before changing it. If it
   is not the declared scenario, select the declared scenario and wait for the
   grid to redraw. Re-read the selected value after redraw.

Do not accept **Level 1**. It flattens the balance; downstream review rejects
it because it cannot preserve transformation and own-use detail. The web-app
guide also requires **Columns: Fuels**, not Fuel Groupings, and Energy Balance
units in the Joule family (preferably Petajoules).

Success condition: Energy Balance is loaded, shows indented Level-2-or-deeper
rows, uses fuel columns, and visibly shows the declared scenario.

### 3. Export all Energy Balance years

1. In Excel, close the baseline seed. Create a blank workbook, save it directly
   in the destination economy folder using the agreed `CHATGPT` filename, and
   activate that destination workbook last. Verify its full path in Excel's
   title bar. This is required because LEAP writes to the last Excel workbook
   clicked.
2. Click the small green Excel/export button on the right side of the Energy
   Balance view, then choose **All** (not **One**). LEAP's status bar describes
   this action as exporting all energy balances to Excel, one sheet per year and
   region.

   ![Green Excel export menu with All selected](assets/leap_gui_balance_runbook/06_export_all.png)

3. Do not export only the current table/year when the dashboard needs a time
   series.
4. Wait until LEAP has completed writing the active destination workbook.
   Completion means the export dialog is closed and the file has a stable size;
   it is not merely that the export button became clickable again.
5. Confirm that the baseline seed was not modified and that the destination
   workbook contains the exported year sheets. Do not overwrite a same-date /
   same-scenario file without checking that it is the intended replacement.

Example final path:

```text
data/leap balances exports/01_AUS/AUS REF 20260820 CHATGPT.xlsx
```

### 4. Validate the exported workbook before upload

Open the completed file read-only, or let the web app inspect it on upload, and
confirm:

- the title row identifies the expected LEAP area;
- the workbook declares only the intended scenario for this upload;
- the workbook contains the intended years, including the selected review year;
- the units are Petajoules or another supported Joule-family scale; and
- the sheets contain indented child rows, proving `Level 2+` detail.

If any item fails, return to LEAP and re-export. Do not rename a wrong-scenario,
wrong-area, or Level-1 workbook to make it appear valid.

### 5. Run the online balance-review dashboard

For the first post-import AUS review, use the **single-export review path**:
one scenario export, the detailed workbook, and the dashboard. It gives an
operator a manageable fix-list before comparing scenarios. Use the multi-export
dashboard path only after that first pass is understood.

1. Open the online LEAP Review Tools web app and select **Guide** if a screen
   needs confirming. The guide includes the required Level-2-and-deeper,
   Petajoule, and fuel-column export settings.
2. Upload the one `CHATGPT` workbook exported in the preceding step. Wait for
   its readout rather than pressing Run immediately.
3. Verify the readout reports the expected economy (`01_AUS`), LEAP area,
   single scenario, supported Joule-family units, available years, and Level 2+
   detail. The app reads these from workbook sheets, not the filename. An
   economy-override box appears only when the area name cannot be identified;
   use it only with the operator-approved economy code.
4. Keep both **Workbook** and **Dashboard** selected. The workbook is the
   detailed, cell-by-cell worklist; the dashboard is the across-years visual
   review. Enter the agreed workbook year or years, for example
   `2022, 2030, 2040`. Each requested year creates a workbook.
5. Start the run and keep the tab open until the Results panel appears. The app
   first validates the export, then produces diagnostics, the selected
   workbook(s), dashboard pages, and an archive. This can take several minutes;
   do not submit the export again while the run is active.
6. At completion, confirm the technical summary says the workbook and
   dashboard succeeded, then confirm Results offers the review workbook(s), an
   **Open dashboard** link, and **Complete run archive (.zip)**. Open the
   dashboard and confirm its fixed economy/scenario banner before downloading.

The multi-export dashboard path is for a later comparison, not this initial
pilot: upload the relevant `REF` and `TGT` exports (or exports for several
economies), deselect **Workbook** because it requires exactly one export, keep
**Dashboard** selected, and verify each dashboard's economy and available
scenario toggle after the run.

Success condition: the app exposes the completed dashboard and archive, with
the expected economy/scenario in the run summary.

### 6. Inspect and archive the result

1. Open the dashboard link and confirm its fixed banner and available pages
   describe the intended economy and scenario(s).
2. Download **Complete run archive (.zip)** and save it in the browser's
   Downloads folder. Keep the supplied filename unless the team has a separate
   archive registry. The app keeps at most three recent dashboard views in the
   current browser; those are convenient, not durable records.
3. Confirm the downloaded ZIP exists and opens. It is the durable output: the
   app's saved dashboard views are browser-local convenience copies, retain only
   a small recent history, and are not a backup.
4. Record the final export filename and downloaded archive filename/path in the
   run log.

## Agent execution checklist

Use the following state transitions for a GUI automation. Each transition must
be verified from the visible interface before continuing.

```text
READY
  -> AREA_CONFIRMED
  -> IMPORT_COMPLETE
  -> CALCULATION_COMPLETE
  -> ENERGY_BALANCE_LOADED
  -> LEVEL2_CONFIRMED
  -> SCENARIO_CONFIRMED
  -> EXPORT_STARTED
  -> EXPORT_FILE_STABLE
  -> EXPORT_IDENTITY_CONFIRMED
  -> WEB_UPLOAD_CONFIRMED
  -> WEB_RUN_COMPLETE
  -> ZIP_DOWNLOADED_AND_OPENED
```

Stop and ask the operator at any mismatch, unexpected warning, missing green
export control, unavailable scenario, timeout, changed area name, unsupported
units, or failed Level-2 check. Never proceed by silently choosing the closest
available scenario or exporting a different area.

## Recovery guide

| Symptom | Action |
|---|---|
| Energy Balance remains blank or controls are disabled | Wait; if it does not settle, capture the visible state and ask the operator rather than re-clicking repeatedly. |
| Details is Level 1 | Change to Level 2, wait for redraw, and confirm indented child rows. Re-export if an earlier file was Level 1. |
| Scenario dropdown changes but table has not refreshed | Wait until the grid redraw completes, then read the scenario value again. |
| The intended scenario is absent from Energy Balance | Open the top-toolbar **Scenarios** window and ensure its checkbox is selected. LEAP calculates results only for checked scenarios; close the dialog, wait for calculation, then return to Energy Balance. |
| LEAP exports into the baseline seed or another workbook | Stop. Do not continue with that file. Close the seed, create and save the correctly named blank destination workbook in the economy folder, activate it last, then restart the export. |
| Web app says area/economy is unknown | Check the LEAP area title and select the explicitly approved economy override. Do not infer from the filename alone. |
| Web app refuses the upload for insufficient detail | Re-export from LEAP at Level 2+; do not bypass the check. |
| Dashboard is not finished after several minutes | Keep the tab open and use the app's refresh control. If it reports failure, save the status/error and ZIP/logs if offered. |
| Completed dashboard later disappears from Saved review | This is expected for browser-local history. Use the downloaded Complete run archive ZIP. |

## Evidence to retain

For a teaching run, retain the input workbook name, exact LEAP area, scenario,
export filename, export folder, app run summary, dashboard URL/title, and ZIP
archive filename. A short screenshot at the Level-2/scenario check and another
at the completed Results panel make the run reproducible without retaining a
screen recording.

## Scenario-calculation setting

If a scenario is missing from the Energy Balance scenario dropdown, open the
top-toolbar **Scenarios** control. Tick the checkbox beside the required
scenario (for example, `REF: Reference` or `TAR: Target`). The dialog states
that results are calculated for checked scenarios; uncheck only when reducing
calculation time is an explicitly approved choice. Close the dialog, let LEAP
calculate, and then return to Energy Balance.

![Scenarios dialog showing Reference and Target checked for calculation](assets/leap_gui_balance_runbook/07_scenarios_calculated.png)
