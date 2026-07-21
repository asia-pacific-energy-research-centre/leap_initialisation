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

### Running two economies at once — supported by the workflow, blocked by the config

The workflow itself supports this. Locks are per-economy, each run gets its own
labelled output tree, and a second run touching an economy already being written
stops with a clear error rather than overwriting. See "Concurrent runs" in
`docs/supply_reconciliation_workflow_guide.md`. For concurrent runs keep
`RUN_OUTPUT_LABEL = "auto"` — the automatic label encodes the economy scope, so
two different scopes get two different folders. (The `"auto"` collision trap
above is the *opposite* case: the **same** scope run twice.)

**But you cannot currently launch them safely from one working tree**, because
`ECONOMIES` is a module-level literal in `codebase/supply_reconciliation_workflow.py`
and there is no per-process override. Launching a second run means editing that
file while the first is running, and that is not safe here:

When the workflow is run as a script, the entry point is `__main__`, so
`codebase.supply_reconciliation_workflow` is **not** in `sys.modules`.
`supply_preflight` then performs a late `from codebase.supply_reconciliation_workflow
import ...` during the preflight, which **re-reads the source file from disk**.
Any edit made between launch and that moment is picked up by the *running*
process. This is the same duplicate-module behaviour recorded under T1 in the
register — it is observed, not theoretical.

So, in order of preference:

1. **Run economies sequentially.** The default, and correct until the config
   surface changes.
2. If you genuinely need parallelism, the fix is small and worth doing properly:
   give `ECONOMIES` and `RUN_OUTPUT_LABEL` a per-process override — an
   environment variable or CLI argument read at startup — so two runs need no
   file edit at all. That change belongs in the Phase 2 configuration work
   (`work_queue.md` [14]), not improvised the day you need it.
3. **Do not** edit `ECONOMIES` to launch a second run while one is in flight.

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

- See `AGENTS_DRAWIO.md` for draw.io-specific requirements.

## Workflow Timing History

`WorkflowTimer.write_csv()` writes both a current-run CSV and a timestamped copy
in a `history/` subfolder next to the main timing CSV. History filenames encode:

```text
workflow_stage_timings_YYYYMMDD_HHMMSS_e{n_economies}_s{n_scenarios}_{run_type}_{commit7}.csv
```

`load_history_summary(path, n_economies=N, n_scenarios=N)` averages history runs:

- Filters by matching economy count, scenario count, and `run_type` (`"full"` vs `"preflight"`)
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

- Removed rows in `leap_combined_esto` and `leap_combined_ninth` are often deliberate guardrails, not obsolete data.
- Many removed rows are rows that would create many-to-many mappings if active, usually because LEAP, ESTO, and 9th Outlook have different levels of detail.
- When checking mapping gaps, treat `counterpart_presence_state == removed_only` as unavailable rather than as a missing row to restore.
- Before reactivating or adding rows, check whether the change would create a many-to-many relationship and prefer the narrowest mapping needed for the workflow.

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
- To switch checks off for a run, set this in
  `config/leap_results_balance_known_issues.json`:

```json
{
  "total_balance_checks": {
    "enabled": false
  }
}
```

- Optional keys: `tolerance_pj` controls numeric tolerance and
  `fail_on_error` raises instead of only writing issue rows.

## Balance Table Structures (ESTO vs 9th)

- See `C:\\Users\\Work\\.codex\\AGENTS_BALANCE_TABLES.md` for balance table structure details.

These two balance tables are the core inputs for `codebase/transformation_analysis_workflow.py`.
Keep this structure in mind when adding new transformations or debugging data issues.

### 9th structure (sector/fuel hierarchy)

- Source file: `data/merged_file_energy_ALL_20251106.csv` (loaded as "9th" in the script).
  - Use `data/merged_file_energy_ALL_20251106.csv` and `data/merged_file_energy_00_APEC_20251106` when you need to exactly match 9th edition projections.
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
- Subtotals are removed using the subtotal mapping in `config/ESTO_subtotal_mapping.xlsx`.

### ESTO (Matt) structure (flow/product table)

- Source file: `data/00APEC_2024_low.csv` (loaded as "ESTO (Matt) data" in the script).
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

`validate_seed_files()` checks all `leap_import_baseline_seed_*.xlsx` files against the full
model export template.  Two ignore sets control which rows are silently skipped:

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

## Planned workflow improvements

Core items are mirrored in `docs/supply_reconciliation_workflow_guide.md` — keep in sync.

### Approach: refactor, not rewrite

Do not rewrite from scratch. The `codebase/functions/` directory (transformation analysis, supply pipeline, LEAP API, Excel I/O) is well-written and heavily reused — preserve it. The problem is the workflow scripts on top: they duplicate shared infrastructure and the main reconciliation script is a 13,628-LOC monolith. A phased refactor is lower risk and faster.

Exception: `other_loss_own_use_proxy_workflow.py` (2,923 LOC) is so internally tangled that rewriting it from scratch — keeping the existing output format as a contract — may be cleaner than refactoring in place.

### Current state (from codebase review, June 2026)

| Script | LOC | Config style | Key quality issues |
|---|---|---|---|
| `aggregated_demand_workflow.py` | 1,212 | Top-level dicts | Hardcoded mapping paths, magic numbers, large helper dicts |
| `electricity_heat_interim_workflow.py` | 1,258 | Top-level dicts | Global caches, label magic strings, large frozensets |
| `other_loss_own_use_proxy_workflow.py` | 2,923 | Top-level large dicts | 2,900-line monolith; 300-line fuel lists; complex fallback logic |
| `refining_workflow.py` | 535 | Top-level constants | Hardcoded economy/paths, sparse docs |
| `supply_workflow.py` | 197 | Minimal (delegation) | Clean wrapper — good template for others |
| `transformation_workflow.py` | 730 | Top-level flags | Tight coupling to core flags |
| `transfers_workflow.py` | 1,802 | Top-level nested dicts | 1,000+ LOC hardcoded config dict, manual copy-paste maintenance |
| `supply_reconciliation_workflow.py` | 13,628 | External JSON + inline | Extreme monolith; dynamic config; global state; no convergence tracking |

#### Duplication across all scripts

- Path resolution (`_resolve()`), economy normalisation (`_normalize_economy()`), year column normalisation — defined separately in 3+ scripts
- ESTO/9th CSV loading copy-pasted across aggregated_demand, other_loss_own_use_proxy, transformation scripts
- Workbook building patterns (preamble row, header row, Level columns) repeated in aggregated_demand and demand_zeroing
- Scenario handling list comprehensions appear 3+ times

#### Mapping file inconsistency

- `aggregated_demand_workflow.py` and `other_loss_own_use_proxy_workflow.py` read `leap_mappings.xlsx` (old)
- `electricity_heat_interim_workflow.py` reads `master_config.xlsx` (old)
- `outlook_mappings_master.xlsx` (new canonical) is **not connected to any workflow script** — this is a critical blocker (see mapping pipeline tasks below)

### Implementation phases

#### Phase 1 — Shared utilities (partially complete; finish migration and hardening)

`codebase/utilities/workflow_utils.py` already provides `_resolve(path)`,
`_normalize_economy(e)`, `_normalize_year_columns(df)`, and process-level ESTO/
9th CSV loaders. The reconciliation/configuration modules and own-use proxy
already import parts of it; `tests/test_workflow_utils.py` covers the initial
utility contract.

Remaining work is deliberately narrow:

- migrate the remaining safe raw ESTO/9th readers to the shared API, beginning
  with the own-use proxy; do not replace selective-column readers in
  `aggregated_demand_workflow.py` with an unconditional full 9th load without
  measuring memory/runtime;
- add cache invalidation keyed to source-file signature, plus an explicit
  cache-clear helper for notebook use, so changed inputs cannot be silently
  reused in a long-lived process;
- add focused loader/migration smoke tests before moving each workflow.

#### Phase 2 — Config standardisation

**Status 2026-07-21 — started.** `70613de` applies the first low-risk change
to `supply_workflow.py`; the detailed script-by-script order and guardrails are
maintained in `docs/work_queue.md` [14].

Apply this concrete standard across the seven scripts:

- Config dict near the top of each file (or near `if __name__ == "__main__"`)
- Economy-specific overrides loaded from a structured JSON that is *generated* by a helper script, not hand-edited
- `supply_workflow.py` is the target pattern — stays <200 LOC by delegating everything

For `supply_reconciliation_workflow.py` specifically: move cap sentinels (`CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS`, `CAPACITY_UNMET_PRODUCTION_UPPER_LIMITS`, and related helpers) inline rather than in the external JSON. The external JSON should only hold economy-specific numeric values, not the structural config.

#### Phase 3 — Connect to `outlook_mappings_master.xlsx`

This is a dependency on the mapping pipeline blocker (see mapping pipeline tasks). Until M2 is done, the workflow scripts remain on the old workbooks. Once M2 is done, update mapping file reads in all seven scripts to use `outlook_mappings_master.xlsx` and validate the expected sheets and columns before processing begins (currently failures occur deep in processing with no upfront check).

#### Phase 4 — Break up the monoliths

Split `supply_reconciliation_workflow.py` (13,628 LOC) into:

- `supply_reconciliation_config.py` — config loading and sentinel definitions
- `supply_reconciliation_allocation.py` — the `capacity_unmet_iterative_balanced` algorithm
- `supply_reconciliation_history.py` — run history, convergence tracking, run removal
- `supply_reconciliation_workflow.py` — slim orchestrator (target: <500 LOC)

Consider rewriting `other_loss_own_use_proxy_workflow.py` from scratch using its current output format as the contract.

#### Phase 5 — Feature improvements

Once the codebase is clean enough to work in confidently:

- **Convergence diagnostics and run history** — capacity-unmet convergence rows now carry run ids, per-run diagnostics can print/write per-fuel allocation and unresolved-gap summaries, latest-two comparisons are available, and `remove_convergence_run()` removes rows for a deliberately reverted run. Files: `codebase/functions/capacity_unmet_convergence_diagnostics.py`, `codebase/supply_reconciliation_history.py`, `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/`
- **All demand aggregated output improvements** — per-sector filename IDs; pre-generate all unique demand branch subset combinations; record individual branch contributions within the aggregated output file. Files: `codebase/aggregated_demand_workflow.py`
- **Per-economy parallelism** — the reconciliation loop is currently single-economy sequential; the scripts are independent per economy and can run in parallel with minimal changes.

### Additional improvements identified in the codebase review

#### Auto-generate `TRANSFER_PROCESS_CONFIG`

This is a 1,000+ LOC hardcoded dict in `transfers_workflow.py` maintained by copy-pasting from `codebase/scrapbook/transfers_mapping_exploration.py`. The scrapbook script should *write* the config to a JSON file; the workflow should read it. Currently a major maintenance trap.

#### Separate dev/test flags from production config

`electricity_heat_interim_workflow.py` has a `SAVE_FEEDSTOCK_CATALOG_CSV` flag at module level. Several scripts mix debug output switches with production config. These should be separated so production runs are not cluttered with dev switches.

#### Notebook-mode entry points

The `supply_workflow.py` pattern (slim wrapper, delegates to pipeline module) should be the target for all seven scripts — makes them easier to call from notebooks and keeps the entry-point file short.

---

## Redevelopment readiness

This section consolidates all outstanding tasks across all three repos. Tasks are split by area. Full task descriptions follow the build order below.

### Recommended build order

Work through in this sequence. Items marked *(depends on X)* must wait for X to be complete.

**Mapping pipeline (`leap_mappings`) — do first:**

1. **M2** — Connect pipeline to `outlook_mappings_master.xlsx` + apply rollup rules at Stage 1 *(critical blocker — nothing downstream produces real data until done)*
2. **M1** — Create `outlook_mapping_maintenance_workflow.py` *(depends on M2 to verify its output)*
3. **M6** — Define subtotal↔non-subtotal mismatch rules *(design decision; implement result in M1)*
4. **M3** — Build hierarchical tree structure CSV + recursive validation *(callable from M1 once built)*
5. **M5** — Document Stage 2 QA outputs in `mappings_system.md` *(after M2 has been run end-to-end)*
6. **M7** — Resolve `mappings_system.md` pipeline overview todo *(after M1 is built)*

**Dashboard (`leap_dashboard`) — can start once M2 produces real data:**

1. **D5, D6** — Review `common_esto_dashboard_plan.md` for accuracy *(do before implementing DB2+, so the spec is correct)*
2. **DB1** — Fix prototype correctness bugs: frontier check + comparison year pairing *(do before any other dashboard work — bugs affect every chart)*
3. **DB2** — Total demand page + summary aggregate charts
4. **DB3** — Difference traces on line charts + series suppression with audit trail
5. **DB4** — Auto docs/ copy for GitHub Pages publishing
6. **DB5** — Deferred: Sankey diagrams, economy switcher, scope-specific charts, port from `test/` to main repo *(do not block DB1–DB4)*

**Initialisation repo refactor (`leap_initialisation`) — independent track, can run alongside mapping/dashboard work:**

1. **Phase 1** — Finish shared-utility migration and cache hardening
2. **Phase 2** — Config standardisation across all seven workflow scripts
3. **Phase 3** — Connect workflow scripts to `outlook_mappings_master.xlsx` *(depends on M2)*
4. **Phase 4** — Break up `supply_reconciliation_workflow.py` monolith; consider rewrite of `other_loss_own_use_proxy_workflow.py`
5. **Phase 5** — Feature improvements: convergence tracking, per-economy parallelism, demand aggregation improvements

**Documentation — independent, can be done at any time:**

- **D1** — Complete: surplus/shortfall rules are documented in guide section 12b.
- **D2** — Complete: the LEAP Energy Balance export procedure is in guide section 9b.
- **D3** — Complete: guide section "The initialisation workflow scripts" describes all seven supporting scripts.
- **D4** — Pending: update iteration-count guidance once real results-update pass-count data is available.

---

### Would redevelopment go smoothly right now?

**No — there is one critical blocker and several slower gaps.**

**Critical blocker — pipeline is disconnected from the new workbook.**
All three Stage 1–3 pipeline scripts (`build_energy_balance_relationships.py`, `build_common_esto_structure.py`, `apply_common_esto_structure.py`) still read the old `config/leap_mappings.xlsx`. The new canonical workbook (`config/outlook_mappings_master.xlsx`) is completely disconnected from the pipeline. This means:

- No `common_esto_comparison_data.csv` can be generated for any real economy.
- The dashboard can only run against the pre-generated USA sample data in `test/inputs/`.
- `build_common_esto_structure.py` has never been run against the new workbook — it is unknown whether it handles the rollup rule sheets at all.

Until mapping pipeline task 2 (below) is done, nothing downstream works on real data.

**Slower gaps:**

- No maintenance workflow — nothing validates `outlook_mappings_master.xlsx` before the pipeline runs, and the subtotal/cardinality computed columns are empty.
- Dashboard prototype is in `test/` and has correctness bugs (frontier check missing — parent and child rows both get line charts, double-counting). It needs porting to the main repo before it can be used in production.
- Supply reconciliation guide is missing three significant sections that modellers need before they can run the workflow independently.
- `common_esto_dashboard_plan.md` has not been reviewed for accuracy past line 264.

---

## Build tasks: mapping pipeline (`leap_mappings`)

Tasks from `C:\Users\Work\github\leap_mappings\docs\mappings_system.md`. Work through in order — later items depend on earlier ones.

### M1. Create `outlook_mapping_maintenance_workflow.py`

**Status:** Not built. Described as Stage 0 of the pipeline — maintains `config/outlook_mappings_master.xlsx`.

**What it needs to do:**

- Read `config/outlook_mappings_master.xlsx`: `leap_combined_esto`, `leap_combined_ninth`, `ninth_pairs_to_esto_pairs`, and the three rollup rule sheets.
- Load ESTO (`data/00APEC_2025_low_with_subtotals.csv`) and 9th Outlook (`data/merged_file_energy_ALL_20251106.csv`) source data.
- Compute and write back `leap_is_subtotal`, `esto_pair_is_subtotal`, `ninth_pair_is_subtotal` columns (added to workbook June 2026; nothing populates them yet).
  - ESTO: use `is_subtotal` column from source CSV.
  - 9th: logical OR of `subtotal_layout` and `subtotal_results`.
  - LEAP: any branch that has children — requires reading the LEAP branch structure.
- Compute and write back `pair_mapping_cardinality_raw` and `pair_mapping_cardinality_after_rollup` per sheet.
- Apply rollup rules to check rollup-aware cardinality.
- Validate ESTO flow totals (top-level now; extend to full recursive once M3 is built).
- Find duplicate and conflicting mappings across the three base sheets.
- Flag ESTO/9th rows with no active mapping.
- Detect crosswalk target conflicts.
- Produce QA outputs.
- Model structure on `leap_mapping_refresh_workflow.py` but operate on the new workbook column conventions.

**Files:** New `C:\Users\Work\github\leap_mappings\codebase\outlook_mapping_maintenance_workflow.py`

---

### M2. Connect pipeline scripts to `outlook_mappings_master.xlsx` ⚠️ Critical blocker

**Status:** Not built. All three pipeline scripts read `config/leap_mappings.xlsx` (old workbook). Without this, no `common_esto_comparison_data.csv` can be generated for real economies.

**What it requires:**

- Audit column-name differences between `leap_mappings.xlsx` and `outlook_mappings_master.xlsx` for each sheet used by Stage 1.
- Update `MAPPING_WORKBOOK_PATH` and `SHEET_CONFIGS` in `build_energy_balance_relationships.py`.
- Update `_find_repo_root` in all three scripts — currently checks for `config/leap_mappings.xlsx`; change to check for `config/outlook_mappings_master.xlsx` or `AGENTS.md` alone.
- **Apply rollup rules at the end of Stage 1** (`build_energy_balance_relationships.py`), after compiling base relationship rows:
  - Read `leap_rollup_rules`, `esto_rollup_rules`, and `ninth_rollup_rules` sheets from `outlook_mappings_master.xlsx`.
  - For each relationship row, check whether the source category matches any active (`include=True`) rollup rule; if so, replace the category with the rolled version.
  - Apply `leap_to_esto` context rollups universally. Context-specific rollups (`road_comparison`, `transport_comparison`, `tfc_comparison`, `tfec_comparison`) are additional rollup passes that create context-tagged rows alongside base rows — one rollup applies per source category per row (no multiple contexts simultaneously on the same row).
  - Rollup sheet columns (as of June 2026): `rollup_context`, input pair, rolled pair, `include`, `Note`. Three removed columns (`rollup_group_id`, `rollup_reason`, `priority`) were stripped from all three sheets.
- `build_common_esto_structure.py` does **not** need to read rollup rules — it does pure graph partitioning on the already-rolled rows from Stage 1. No changes needed there for rollup support.
- **Simplify `codebase/functions/unified_name_lookup.py`** — currently a consensus resolver pulling from 8 sources across `leap_mappings.xlsx` and `master_config.xlsx`. Replace with: (1) read `leap_display_names` sheet from `outlook_mappings_master.xlsx`; (2) for any code not found there, fall back to stripping the leading numeric prefix from the code string. The 8-source consensus logic can be removed entirely. The public API (`resolve_name`, `build_unified_name_lookup`, `load_source_records`) should be preserved so call sites do not need to change.
- **Update `build_common_esto_structure.py` name lookup** — currently reads `sector_fuel_code_to_name` from `master_config.xlsx` (line ~229). Change to read `leap_display_names` from `outlook_mappings_master.xlsx` instead, using the same fallback logic as the simplified `unified_name_lookup.py`.
- `leap_display_names` sheet columns (as of June 2026): `code_type` (`esto_flow`/`esto_product`/`ninth_sector`/`ninth_fuel`), `code`, `auto_name` (for reference only — pipeline should re-derive this, not read it), `leap_display_name`, `matches_original_product_flow_name` (bool — True = auto-derived name is correct, False = override required). Only rows where `matches_original_product_flow_name` is False are genuine overrides; all other rows can be served by the fallback.
- Verify `apply_common_esto_structure.py` output format is unchanged.
- Keep `leap_mappings.xlsx` and `master_config.xlsx` as legacy reference but not primary inputs.

**Files:** `build_energy_balance_relationships.py`, `build_common_esto_structure.py`, `apply_common_esto_structure.py`, `codebase/functions/unified_name_lookup.py` in `C:\Users\Work\github\leap_mappings\`

---

### M3. Build hierarchical tree structure CSV and full recursive validation

**Status:** Not built. Only top-level ESTO validation exists in `leap_mapping_refresh_workflow.py`.

**What it requires:**

- **ESTO tree:** Parse dot-separated numeric codes to infer parent-child relationships (`09` → `09.06` → `09.06.01`).
- **9th tree:** Use `sub1sector`–`sub4sector` columns for the sector hierarchy; `fuels`/`subfuels` for fuel hierarchy.
- **LEAP tree:** Parse slash-separated branch paths from LEAP export data.
- **Common comparison tree:** ESTO dot-notation for standard rows; graph-generated categories treated as leaf-level.
- Output four tree CSVs to `results/tree_structure/`.
- Recursively validate parent = sum(children) at every level for all datasets.
- Make this callable from M1 once built.

**Files:** New `C:\Users\Work\github\leap_mappings\codebase\mapping_tools\build_dataset_tree_structure.py`

---

### M4. Populate rollup rules in `outlook_mappings_master.xlsx` ✓ Done

All rollup rule sheets are populated. Corrections applied June 2026:

- Rollup contexts updated from generic `leap_to_esto` to specific contexts (`road_comparison`, `other_sector_comparison`, `transport_comparison`, `tfc_comparison`, `tfec_comparison`).
- Own-use/loss ESTO rows now roll to `(including own use)` suffixed comparison categories.
- Own-use/loss 9th rows now roll to `_incl_own_use` suffixed comparison categories.
- `Refinery & blending transfers` renamed to `Refinery and blending transfers` in `codebase/transfers_workflow.py`.
- Rollup sheet columns simplified June 2026: removed `rollup_group_id`, `rollup_reason`, and `priority` from all three rollup sheets (`leap_rollup_rules`, `esto_rollup_rules`, `ninth_rollup_rules`). Remaining columns: `rollup_context`, input pair, rolled pair, `include`, `Note`.

---

### M5. Verify Stage 2 QA outputs ✓ Partially done

Stage 1 QA outputs documented in `mappings_system.md` with actual file names. Remaining:

- Stage 2 outputs (`build_common_esto_structure.py`) — not yet run; todo note left in docs.
- Maintenance workflow outputs — not yet built (M1).

---

### M6. Define subtotal↔non-subtotal mismatch rules

**Status:** Design question. Docs flag: "Establish when a subtotal↔non-subtotal mapping is actually a problem."

**What it requires:** Decide the criteria — candidate rule: it is a problem only when a leaf-level source maps to an aggregate target AND a more detailed target is available. Once agreed, implement in M1 and update docs.

---

### M7. One outstanding doc cleanup in `mappings_system.md`

The pipeline overview section has a todo: "Check whether anything from the mapping maintenance workflow section should be called out explicitly in this pipeline overview." Resolve once M1 is built and the pipeline is running end-to-end.

---

## Documentation status: supply reconciliation guide

Status of the documentation tasks for
`C:\Users\Work\github\leap_initialisation\docs\supply_reconciliation_workflow_guide.md`.

### D1. Surplus and shortfall rules - complete

Completed in guide section 12b. It documents shortfall and surplus rule choices,
module ordering, Resources behaviour, and the diagnosis of unexpected imports
or exports.

### D2. LEAP export process - complete

Completed in guide section 9b, including results view, units, detail level,
Malaysia exception, export action, expected time, and placement guidance.

### D3. Seven supporting workflow scripts - complete

Completed in the guide's "The initialisation workflow scripts" table. Keep it
updated if a producer's role or output contract changes.

### D4. Iteration count section update - pending real evidence

Section 11 remains qualitative until enough real results-update runs have
recorded comparable pass counts and convergence outcomes. Do not infer a
numeric expectation from a baseline-seed fleet run alone.

---

## Documentation gaps: dashboard plan

Gaps in `C:\Users\Work\github\leap_dashboard\test\common_esto_dashboard_agent_pack_transfer_rules\common_esto_dashboard_plan.md`.

### D5. Review content after line 264 for accuracy

The doc has `> todo UPTO HERE — review remaining content below for accuracy` at line 264. Everything from that point (dashboard input files, chart generation logic, configuration, production build plan, page structure) needs to be checked against the current prototype code in `src/` and marked as accurate or updated.

### D6. Review "Recommended development workflow" section

Line 748 flags the recommended development workflow and surrounding content for accuracy review.

---

## Build tasks: dashboard (`leap_dashboard`)

Ordered phases from the production build plan in `common_esto_dashboard_plan.md`. The prototype lives in `test/common_esto_dashboard_agent_pack_transfer_rules/src/` and must be ported to the main repo (open question: timing and target path).

### DB1. Phase 1 — Core correctness (do first, everything else depends on these)

**1.1 Frontier check for parent/child rows.**
The prototype generates a line chart for every flow/product pair. When a parent flow and a child flow both appear in the dataset, both get line charts — double-counting the parent. Fix: before chart generation, detect whether any child rows exist for a given flow code; if so, exclude the parent from line chart generation (it still gets an area chart).

**1.2 Correct comparison year pairing in sorting metrics.**
`abs_diff` and `pct_diff` must use the correct comparison pair per year: LEAP vs ESTO for years at or below the base year, LEAP vs 9th Outlook for years above. Missing LEAP data must not be treated as zero — exclude that year from difference calculations.

### DB2. Phase 2 — Missing pages and chart families

**2.1 Total demand page with supply line.** Aggregate demand across end-use sectors; include a supply line that adds international bunkers so aggregate supply and aggregate demand are comparable on one chart.

**2.2 Summary aggregate charts.** The third chart family between the per-page overview area charts and individual flow/product line charts. Generated from the common ESTO structure; no manual graph IDs.

### DB3. Phase 3 — Difference traces and suppression

**3.1 Difference traces on line charts.** LEAP minus ESTO for historical years, LEAP minus 9th for projection years. Pre-computed during chart generation; stored in chart manifest. Off by default, toggled via Plotly legend.

**3.2 Series suppression with audit trail.** Charts below a configurable total-absolute-value threshold are suppressed from display but written to manifest with `suppressed: true`. Never silently dropped.

### DB4. Phase 4 — Publishing

**4.1 Auto docs/ copy after each run.** After each workflow run, copy dashboard files (`*.html`, `*.js`, `*.json`) from `outputs/<economy>/` to `docs/<economy>/`. Supporting files (CSVs) stay in `outputs/` only. Then commit and push `docs/` to publish via GitHub Pages.

### DB5. Phase 5 — Deferred (do not block earlier phases)

- Sankey diagrams — routing rules need separate design work.
- Economy/dashboard switcher in the header.
- Scope-specific charts (e.g. transport subsectors, datacentres) for sectors where LEAP and 9th have more detail than ESTO.
- Port prototype from `test/` to main repo — timing and target path not yet decided.

---

### Notes on ordering

**Mapping pipeline:** M2 is the critical blocker — unblock it first. M1 and M3 can follow. M6 is a design decision that should precede its implementation in M1.

**Dashboard:** DB1 must be done before DB2–DB4, as correctness bugs in DB1 affect every chart. The prototype cannot be used in production until DB1 is complete. DB5 items should not block DB1–DB4.

**Docs:** D1–D4 are independent and can be done at any time. D5–D6 should be done before any significant dashboard code work begins so the spec is accurate.
