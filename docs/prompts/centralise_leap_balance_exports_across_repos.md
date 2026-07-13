# Prompt: Centralise LEAP balance exports in `leap_initialisation`

## Objective

Refactor the three-repository workflow so that raw LEAP balance-export workbooks have one canonical home:

```text
C:\Users\Work\github\leap_initialisation\data\leap balances exports\
```

The repositories are expected to live together as sibling directories:

```text
C:\Users\Work\github\leap_initialisation\
C:\Users\Work\github\leap_mappings\
C:\Users\Work\github\leap_dashboard\
```

`leap_mappings` should read the raw LEAP balance exports from the canonical `leap_initialisation` location. `leap_dashboard` should not require or duplicate raw LEAP balance-export files; it should consume the generated Common ESTO comparison outputs from `leap_mappings` only. `leap_initialisation` remains responsible for creating/maintaining the LEAP export inputs and its own derived outputs.

Do not delete or move existing folders until all consumers have been identified, migrated, and verified.

## Important current context

- `leap_mappings\codebase\run_mapping_pipeline.py` already contains a local-then-sibling fallback for the `20_USA` LEAP export directory. Convert this into a clear canonical-path policy rather than leaving two equivalent locations.
- `leap_mappings\codebase\leap_mapping_refresh_workflow.py` and related utilities resolve LEAP balance workbooks for mapping checks. These paths must be included in the audit.
- `leap_dashboard\codebase\common_esto_dashboard_workflow.py` consumes:
  - `C:\Users\Work\github\leap_mappings\results\common_esto\common_esto_comparison_data.csv`
  - `C:\Users\Work\github\leap_mappings\results\common_esto\common_esto_rows.csv`
- The dashboard has an optional capacity-unmet convergence page whose current input is under `leap_initialisation\outputs\...`; preserve this intentional derived-output dependency unless the audit shows a better shared interface.
- `leap_initialisation` currently owns raw/derived LEAP-related files under `data\leap balances exports\` and `outputs\leap_exports\`. Distinguish raw input workbooks from generated outputs; do not conflate them.
- Existing worktrees may contain unrelated uncommitted changes. Inspect `git status --short` in all three repositories before editing, preserve unrelated changes, and do not commit files changed by another agent.

## Scope

Work across:

1. `C:\Users\Work\github\leap_initialisation`
2. `C:\Users\Work\github\leap_mappings`
3. `C:\Users\Work\github\leap_dashboard`

First audit all references to:

- `leap balances exports`
- raw LEAP balance workbooks
- `raw_leap_results.csv`
- `leap_results_converted_to_esto.csv`
- `leap_initialisation`
- `outputs\leap_exports`
- dashboard references to raw LEAP files

Include Python modules, configuration files, notebooks/scripts, tests, documentation, and generated-file assumptions. Exclude generated `results/`, `outputs/`, and published dashboard artifacts from code edits unless a clearly documented migration or validation is required.

## Design requirements

### 1. Canonical path resolution

Create or standardise a small, testable path-resolution convention. It should:

- derive sibling repositories from the current repository location where possible;
- resolve the canonical raw export directory as:
  `REPO_ROOT.parent / "leap_initialisation" / "data" / "leap balances exports"` when called from `leap_mappings`;
- avoid hardcoding a developer-specific absolute path as the only option;
- optionally support an explicit environment-variable override for unusual layouts, with a documented name;
- fail early with a useful message when the canonical directory is absent;
- preserve notebook-safe and Windows path handling.

Do not introduce a new package or broad abstraction if a small shared helper in the owning repository is sufficient. Keep the implementation simple and consistent with each repository's existing conventions.

### 2. `leap_mappings`

- Make the canonical `leap_initialisation` data directory the primary and documented source for raw LEAP balance exports.
- Remove the ambiguous local-first behaviour unless there is a concrete backwards-compatibility reason to retain it.
- Update all mapping-pipeline and mapping-refresh consumers, not only `run_mapping_pipeline.py`.
- Ensure both reference and target export discovery work for multiple economies, including future `02_BD` and current `20_USA` layouts.
- Keep generated mapping artifacts in `leap_mappings\results\...`; do not move generated Common ESTO outputs into `leap_initialisation`.
- Add validation that reports which economy/scenario workbooks were discovered and which are missing.

### 3. `leap_dashboard`

- Confirm that production dashboard code does not read raw LEAP balance exports.
- Keep the dashboard input boundary at `leap_mappings\results\common_esto\...`.
- Remove any duplicate raw LEAP export path, local raw-export folder, or stale documentation if it is genuinely unused.
- Preserve the optional convergence-page input from `leap_initialisation` if it is still valid, and document that it is a derived diagnostic rather than a raw balance input.
- Make dashboard errors distinguish missing Common ESTO comparison data from missing optional convergence data.

### 4. `leap_initialisation`

- Document `data\leap balances exports\` as the canonical raw LEAP input location.
- Keep generated LEAP import/export products under the existing `outputs\leap_exports\...` structure unless the audit proves a specific move is necessary.
- Ensure workflows that generate or consume raw balance exports use repository-relative resolution and remain notebook-safe.
- Do not move or rename existing raw workbooks without a migration plan and explicit verification.

### 5. Tests and documentation

Add or update focused tests for:

- sibling-repository path resolution;
- environment override behaviour, if implemented;
- missing canonical-directory diagnostics;
- economy/scenario discovery;
- dashboard startup with Common ESTO inputs and without the optional convergence file;
- ensuring dashboard code does not require raw LEAP export files.

Update the relevant `AGENTS.md`/README/docs instructions in each repository so future agents use the canonical location. Include a short migration note if a legacy local folder remains temporarily supported.

## Verification requirements

Use the documented Windows Python environment:

```powershell
C:\Users\Work\miniconda3\python.exe
```

At minimum:

1. Run focused tests in `leap_mappings` and `leap_dashboard`.
2. Run a path/discovery smoke test from `leap_mappings` using the existing `20_USA` exports.
3. Confirm the mapping pipeline still finds its raw LEAP input without a copy in `leap_mappings`.
4. Render the dashboard for `20_USA` from the existing Common ESTO outputs.
5. Confirm the dashboard still renders `02_BD` from ESTO/9th data even when no Bangladesh LEAP export exists, with the missing LEAP source clearly reported rather than treated as a file-path failure.
6. Verify the expected outputs remain in their owning repositories.
7. Run `git diff --check` in each changed repository.

Do not run the full long-running supply reconciliation workflow unless the implementation genuinely requires it. Do not delete legacy folders during this task unless the user explicitly approves the deletion after the audit.

## Deliverables

- Minimal code/config changes implementing the canonical raw-export path.
- Tests covering the new path policy and dashboard boundary.
- Updated documentation.
- A concise audit report listing every old path found, its replacement, and any intentionally retained compatibility path.
- A verification report listing commands run and results.

Commit only the files belonging to this change, separately in each repository if changes span repositories. Use agent-prefixed commit messages, for example:

```text
codex: centralise raw LEAP balance export discovery
```

Do not commit unrelated pre-existing modifications.
