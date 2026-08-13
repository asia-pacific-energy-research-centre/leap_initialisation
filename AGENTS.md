# AGENTS.md

These are project-level instructions for Codex (and similar agents).

## Economy-code reminder

- `02_BD` means **Brunei Darussalam**. It does not mean Bangladesh.
- `20_USA` means **United States of America**.
- The complete dashboard economy code/name list is maintained in the sibling repository at `C:\Users\Work\github\leap_dashboard\config\common_esto_dashboard\series_config.json`.
- That dashboard file uses compact keys (`02BD`, `20USA`); workflow/data inputs commonly use underscore-normalized codes (`02_BD`, `20_USA`).

## Repository routing

- This repo is the active home for LEAP area initialisation workflows.
- Use this repo for `codebase/supply_reconciliation_workflow.py`, baseline seed work, supply/transformation/transfers integration, patching baseline seeds, and related LEAP import/export setup.
- `C:\Users\Work\github\leap_utilities` is the old workspace where this initialisation code was built. Do not use `leap_utilities` for active initialisation or supply reconciliation work anymore unless the user explicitly asks for legacy cleanup or comparison.
- For mapping-only maintenance, use `C:\Users\Work\github\leap_mappings` instead.

## Cross-repo access

In Claude Code sessions all three repos are configured as additional working directories and are directly accessible:

- `C:\Users\Work\github\leap_initialisation` (this repo)
- `C:\Users\Work\github\leap_mappings`
- `C:\Users\Work\github\leap_dashboard`

Agents can read, search, and edit files in any of them. When a task here involves mapping concepts, read `C:\Users\Work\github\leap_mappings\docs\mappings_system.md` first rather than inferring from context.

## Running the supply reconciliation workflow

`codebase/supply_reconciliation_workflow.py` is a long-running workflow. When an
agent runs it, **let it run to completion — do not interrupt or kill it to check
on it.** Launch it in the background and poll its progress at most once every
**10 minutes**. Frequent polling wastes effort and risks disturbing the run;
the workflow reports its own per-stage progress, so a 10-minute cadence is
sufficient to notice a stall or failure.

### Launching a run — three traps that have each cost a run

**1. Pin the interpreter explicitly.** A bare `python` or a `nohup python ...`
resolves through the shell's PATH and can pick up the Windows Store shim
(`AppData/Local/Microsoft/WindowsApps/python.exe`, a *different* Python with
*different* pandas/numpy) instead of miniconda. A run launched that way appears
healthy — it imports, allocates, burns CPU — but its output is not reproducible
against the toolchain every test and A/B was verified under. Always:

```bash
"C:/Users/Work/miniconda3/python.exe" codebase/supply_reconciliation_workflow.py
```

Verify after launching, not just that a process exists but *which* one:
`Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'"` and read the
`CommandLine`. Note the process may be named `python3.13.exe`, so
`Get-Process python` silently matches nothing and makes a live run look dead.

**2. A killed run leaves stale locks that block the next one.** The workflow
takes one lock per economy under
`outputs/leap_exports/supply_reconciliation/supporting_files/runtime/economy_locks/`
and does not clean them up if the process is killed. Each lock is JSON with the
owning `pid`. Before clearing any, confirm the pid is actually dead — a lock
whose process is alive means a real run is in flight and must not be disturbed.

**3. `RUN_OUTPUT_LABEL = "auto"` can collide with an existing run.** The
automatic label is derived from a hash of the economy set, so it is *stable
across runs*: for the standard 21 economies it always resolves to
`SEED_21ECON_0E555F_TGT_REF_CA`, which already exists. A second run would write
into the first one's directory and interleave outputs. For any run whose output
you intend to keep, set an explicit dated label, and restore `"auto"` afterwards.

### Running more than one economy

Bounded process-based economy parallelism is implemented and was verified on
2026-07-23. Use `codebase/supply_reconciliation/parallel_runner.py`; it launches one
OS process per economy and passes an isolated `LEAP_WORKER_SNAPSHOT_JSON`
snapshot containing the economy, run label, and test horizon. Per-economy locks
and run-specific output trees prevent two workers from writing the same scope.
See `docs/current_execution_roadmap.md` and the "Concurrent runs" section of
`docs/supply_reconciliation_workflow_guide.md`.

Do not create parallelism by editing `ECONOMIES` or `RUN_OUTPUT_LABEL` between
two bare invocations of `supply_reconciliation_workflow.py`. A late import can
re-read those module literals from disk. Sequential execution remains the
safest default; use the runner, unique labels, and a deliberately bounded
`max_workers` value when parallel execution is justified. Deterministic parent
CSV views cover validation findings, issue groups, source diagnostics,
template matching, and F5 conservation families. A combined-workbook merge
helper also exists, but the runner does not invoke it and its production
acceptance remains decision-gated. Consume worker seed workbooks directly
unless that separate merge has been explicitly selected and verified.

## Prompt docs workflow

- Multi-step agent prompts (plan-first implementation tasks, investigation prompts, prompt packs) live in `docs/prompts/`.
- Once the work a prompt describes is complete (implemented, tested, and committed), move that prompt file out of `docs/prompts/` into `docs/archive/` — see `leap_mappings/docs/archive/common_esto_lineage_validation/` for the pattern (a prompt pack archived together with its own status/findings/TODO notes once superseded or finished). Do not leave completed prompts in `docs/prompts/`; that folder should only contain active or pending work.

## Rebuild scope and active documentation

This repository is being rebuilt. All new workflow code goes here, not in `leap_utilities`.

Key dependency: `leap_mappings` (`C:\Users\Work\github\leap_mappings`) is the canonical source for all fuel, sector, and flow mappings between LEAP, ESTO, and the 9th Outlook. Workflow scripts in this repo should use mappings from `leap_mappings` rather than defining fuel or sector relationships internally. See `leap_mappings/docs/mappings_system.md`.

Active documentation being developed:

- **`docs/work_queue.md` — START HERE for outstanding work.** What is left, in what
  order, and what blocks what; plus recorded traps that have already cost time,
  and known pre-existing test failures that are *not* regressions. Read this
  before picking up any supply-reconciliation / baseline-seed task.
- `docs/check_registry.md` — directory of every "getting ready before sending
  out" check across five families (gap-fill/reset, artifact invariants,
  LEAP-import readiness, preflight, conservation), with the boundary-vs-local and
  gateability rules. Enforced by `tests/test_check_registry.py`: if you add, move
  or rename a check, update this file or that test fails.
- `docs/supply_reconciliation_workflow_guide.md` — guide to the supply reconciliation workflow and the broader initialisation context.
- `docs/special_rules_and_design_decisions.md` — human-selected rules, provisional assumptions, and unresolved semantic decisions found during end-to-end runs.
- `docs/baseline_seed_rule_inventory.md` — the SEED-C rule detail behind the baseline-seed validator.

## When editing draw.io diagrams

- No repository-specific `AGENTS_DRAWIO.md` exists in this checkout. Preserve
  existing diagram source and export conventions, and verify both the editable
  source and rendered output when changing a diagram.

## Workflow Timing History

`WorkflowTimer.write_csv()` writes both a current-run CSV and a timestamped copy
in a `history/` subfolder next to the main timing CSV. History filenames encode:

```text
workflow_stage_timings_YYYYMMDD_HHMMSS_e{n_economies}_s{n_scenarios}_y{year_start}-{year_end}-n{n_years}_{run_type}_{commit7}.csv
```

`load_history_summary(path, n_economies=N, n_scenarios=N)` averages history runs:

- Filters by matching economy count, scenario count, horizon (`year_start`, `year_end`, `n_years`), and `run_type` (`"full"` vs `"preflight"`). Pass the active run's horizon whenever querying history so two-year smoke timings never affect full-horizon expectations.
- Older history files without the `y...` segment remain readable, but have unknown horizon metadata and do not match an explicit horizon filter.
- Prefers runs from the current git commit if any exist
- Removes per-stage outliers via IQR before averaging (requires ≥4 runs per stage)
- Preflight runs (`preflight_compressed_projection/`) are already isolated in a separate history directory and excluded automatically when querying the full-run history path

**Resetting timing expectations after a commit that changes runtime significantly:**
Delete files from the `history/` subdirectory next to the timing CSV. For `supply_reconciliation`:

```text
outputs/leap_exports/supply_reconciliation/supporting_files/runtime/history/
```

Deleting individual files is fine — just leave at least one to preserve a baseline, or delete all to start fresh. The next successful run will seed the new history.

## Small guide for humans

- Put instructions here that you want Codex to follow every time it edits this repo.
- Keep rules short and specific; avoid large, complex policies.
- Do not use this repo for LEAP dashboard implementation or dashboard template edits. Use `C:\Users\Work\github\leap_dashboard` for LEAP dashboard work unless the user explicitly asks for shared `leap_utilities` code changes.
- For file-specific rules, include path globs like `docs/leap-system*.drawio`.
- Workflow-file pattern for small projects: create/maintain one `*_workflow.py` entry script per task area and make it notebook-safe.
- In workflow scripts, always define `REPO_ROOT = Path(__file__).resolve().parents[1]` (or correct repo level), add it to `sys.path` only if missing, and resolve all relative paths via a `_resolve()` helper against `REPO_ROOT`.
- Why: notebooks run with arbitrary CWD, so this prevents `FileNotFoundError` and import failures.
- Normalize user-provided path strings by replacing `\\` with `/` before `Path(...)` when needed.
- When updating transfer category mappings, re-run `codebase/scrapbook/transfers_mapping_exploration.py`
  and paste the printed `TRANSFER_PROCESS_CONFIG` into `codebase/transfers_workflow.py`.
- When referring to files in replies, prefer paths relative to the active repo root
  (for example, `outputs/example.csv`) instead of absolute `/mnt/c/...` or
  `C:\...` paths. Use absolute paths only for files outside the repo or when needed
  to disambiguate.

## Converting documentation to Word

`scripts/convert_docs.py` converts Markdown files in `docs/` to `.docx` using Pandoc.
It fixes encoding mojibake, renders Mermaid diagrams to PNG, and suppresses auto-captions.

```powershell
# Convert all .md files individually
python scripts/convert_docs.py

# Combine the main docs into one Word document
python scripts/convert_docs.py --combine

# Convert only a subdirectory
python scripts/convert_docs.py --docs-dir docs/transformation_supply_docs
```

Output goes to `docs/docx/`. Mermaid PNGs go to `docs/docx/mermaid/`.

Requirements (one-time install):

- `winget install JohnMacFarlane.Pandoc`
- `npm install -g @mermaid-js/mermaid-cli`

## Output clarity

- Keep output folders small and easy to inspect.
- Prefer a few clearly named primary outputs.
- Do not create extra files unless they serve a clear human-facing purpose.
- Keep primary outputs narrow: include important columns only.
- Put debug-heavy or trace-heavy artifacts in `extra_detail` or `diagnostics`, not beside the main outputs.
- Make sure there is a clear file for inspecting errors when needed.

## LEAP mapping maintenance

- The maintained mapping sheets contain only relationships believed to be
  correct. Rejected relationships are removed; review history belongs in notes,
  QA evidence, or Git history rather than inactive guardrail rows.
- When checking mapping gaps, treat
  `counterpart_presence_state == removed_only` as unavailable, not as evidence
  that a former row should be restored.
- Before adding or replacing a relationship, check complete sibling coverage
  and unintended many-to-many effects. Prefer the agreed coarse mapping when
  LEAP, ESTO, and the 9th Outlook use different levels of detail.

## LEAP Export File Structure

- See `C:\\Users\\Work\\.codex\\AGENTS_LEAP_EXPORT.md` for LEAP export structure requirements.

## LEAP balance total checks

- LEAP balance ingestion runs total-balance checks by default in
  `codebase/utilities/leap_results_dashboard_balance.py`.
- The checks compare LEAP `Total` fuel rows for `Total Primary Supply`,
  `Total Transformation`, and `Total Final Energy Demand` against signed
  mapped component sums on both ESTO and 9th axes.
- Signs are preserved from the extracted balance table; exports, bunkers,
  stock changes, and transformation inputs should already carry the correct
  negative/positive sign in the LEAP workbook.
- Output is available as `total_balance_checks` in conversion results and,
  for `codebase/old_workflows/leap_balance_to_esto_long_workflow.py`, as
  `supporting_files/checks/leap_balance_total_checks.csv`.
- Mismatches are also appended to runtime issues with
  `reason == total_balance_mapping_check`.
- There is no repository-level
  `config/leap_results_balance_known_issues.json` in this checkout. Override
  behavior at the call site:
  `run_total_balance_checks=False` disables the checks and
  `total_balance_check_tolerance_pj=<value>` changes the tolerance.
- Callers that already supply a `known_issues` dictionary may use its
  `total_balance_checks.enabled`, `tolerance_pj`, and `fail_on_error` keys.
  `fail_on_error` raises instead of only writing issue rows.

## Balance Table Structures (ESTO vs 9th)

- See `C:\\Users\\Work\\.codex\\AGENTS_BALANCE_TABLES.md` for balance table structure details.

These two balance tables are core inputs for
`codebase/transformation_workflow.py` and the shared supply/transformation
functions. Keep this structure in mind when adding transformations or
debugging source-data issues.

### 9th structure (sector/fuel hierarchy)

- Source file: `data/merged_file_energy_ALL_20251106.csv` (loaded as "9th" in the script).
  - Use `data/merged_file_energy_ALL_20251106.csv` and
    `data/9th merged_file_energy_00_APEC_20251106.csv` when you need the
    maintained all-economy and APEC-aggregate projection inputs.
- Key columns:
  - `scenarios`, `economy`
  - Sector hierarchy: `sectors`, `sub1sectors`, `sub2sectors`, `sub3sectors`, `sub4sectors`
  - Fuel hierarchy: `fuels`, `subfuels`
  - Subtotal flags: `subtotal_layout`, `subtotal_results`
  - Year columns (as strings before normalization): `1980` ... `2070`
- Coding style:
  - Codes use underscores, e.g., `09_06_gas_processing_plants`, `10_01_03_liquefaction_regasification_plants`.
  - `"x"` means "not used" for a given hierarchy level.
- Usage in transformations:
  - Supports detailed subsector selection (e.g., LNG uses `sub2sectors` and `subfuels`).
  - Filtered to `scenarios == reference` before calculations.
- 9th subtotal rows are filtered from the `subtotal_layout` and
  `subtotal_results` flags.

### ESTO (Matt) structure (flow/product table)

- Source file: `data/00APEC_2024_low_with_subtotals.csv`, the configured
  initialisation base table.
- Key columns:
  - `economy`
  - `flows` (balance rows like production, transformation, own use, losses)
  - `products` (fuel/product codes)
  - Year columns: `1990` ... `2022`
- Coding style:
  - Economy codes are compact (e.g., `01AUS`), normalized to `01_AUS` to align with 9th.
  - Flow codes match the 09/10 transformation and loss lists (e.g., `09.08.01 Coke ovens`, `10.01.05 Coke ovens`).
- Usage in transformations:
  - Used for most transformation flows when sector detail is not required.
  - No `sub*sectors` columns are present, so selection is done via `flows` and `products`.

### Shared sign conventions (both tables)

- Positive values represent outputs from a transformation flow.
- Negative values represent inputs to a transformation flow (feedstock or auxiliary fuels).
- Loss/own-use flows are treated as auxiliary fuel use (absolute values are used in ratios).

## Baseline Seed Validation (`patch_baseline_seeds.py`)

`validate_seed_files()` checks `leap_import_baseline_seed_*.xlsx` files against
the LEAP export template resolved for the target economy. Two ignore sets
control which rows are silently skipped:

- **`VALIDATION_IGNORE_PREFIXES`** — branch path *prefixes* for sectors known to be absent from
  the template (e.g. `Transformation\Biofuels processing\` — confirmed zero energy in ESTO).
- **`VALIDATION_IGNORE_FUEL_NAMES`** — final path *segments* that are 9th-edition aggregate
  category labels and are not real LEAP branches in any sector.  Current members:
  `Biomass`, `Coal`, `Gas`, `Others`, `Municipal solid waste non and renewable`.
  Note: `Solar` is **not** in this set — unallocated solar codes (`12_solar`,
  `12_solar_unallocated`) are remapped to `Solar nonspecified` by
  `_safe_power_interim_display_label()` before reaching the output filter.

When the aggregated demand workflow or another source emits rows for a fuel that isn't a real
LEAP branch and the validation flags it as "unknown path", first check whether the fuel name
belongs in `VALIDATION_IGNORE_FUEL_NAMES` before treating it as a genuine error.  If the fuel
*should* exist in the model, investigate the aggregated demand workbook or the relevant
workflow instead.

## Python Environment

- This repo's `.venv` is a WSL-created venv (`home = /usr/bin` in `pyvenv.cfg`) and cannot be used from Windows shells (PowerShell, cmd, or the Bash tool when running in a Git-Bash context on Windows).
- Use `/c/Users/Work/miniconda3/python.exe` for all Python scripts run via the Bash tool (Git-Bash on Windows).
- Do **not** attempt to activate `.venv/bin/activate` from the Bash tool — it will fail silently or error.

- Do **not** use PowerShell's `python` or `py` aliases — output is swallowed and exit codes are unreliable.

---


## Historical planning material

The obsolete June–July 2026 refactor plan, LOC table, and duplicated sibling
backlogs were removed on 2026-08-13. Git history retains that planning
snapshot. Current work is owned only by:

- `docs/work_queue.md`, `docs/handover_work_queue_20260728.md`, and
  `docs/current_execution_roadmap.md` for initialisation;
- `../leap_mappings/docs/work_queue.md` for mapping work; and
- `../leap_dashboard/docs/work_queue.md` for dashboard work.
