# LEAP review tools: developer mode and portable releases

Two supported ways to run the same two tools — the Common ESTO dashboard
renderer and the balance-review workbook builder.

| | Developer mode | Portable release mode |
|---|---|---|
| Who | the maintainer | a colleague |
| Needs | the three repository checkouts, Python, Git | nothing but Windows |
| Code source | the live working copies, as they stand right now | an exact set of pinned commits |
| Build step | none — an edit applies on the next run | rebuild required for any code change |
| Reproducible | only as far as the working tree is clean | yes, from the manifest alone |

Both modes run the *same* command implementations
(`codebase/portable_release/commands.py`) with the same input validation and the
same run manifest. The only thing that differs is the `RuntimeContext` that says
where code, configuration, outputs, and logs live. That is deliberate: the two
modes cannot drift apart in behaviour.

---

## 1. Developer mode

### One-time setup

Developer mode reads exactly one settings file. Nothing is inferred from the
current working directory, so the launcher behaves identically from a notebook,
a terminal, or an IDE run configuration.

```bash
"C:/Users/Work/miniconda3/python.exe" -c "import sys; sys.path.insert(0,'.'); from codebase.portable_release.settings import write_example_settings; print(write_example_settings())"
```

That writes `%LOCALAPPDATA%\leap-review-tools\developer_settings.toml`,
pre-filled with the repositories it can detect. Edit the paths if needed. A
tracked example is at
[`config/leap_review_tools_settings.example.toml`](../config/leap_review_tools_settings.example.toml).
Set `LEAP_REVIEW_TOOLS_SETTINGS` to use a file elsewhere.

The file is kept outside the repositories on purpose: it holds machine-specific
absolute paths that must not be committed.

### Checking where a run will read from

```python
from codebase.portable_release import developer_launcher as dev
dev.print_status()
```

This prints the resolved repositories, configuration assets, output folders, a
preflight result for every required location, and each repository's commit and
dirty state. Run it before anything you intend to keep.

### Running the tools

```python
from codebase.portable_release import developer_launcher as dev

result = dev.run_balance_review(
    economy="20_USA",
    scenario="Target",
    year=2022,
    balance_export_workbook=r"C:\Users\Work\github\leap_initialisation\data\leap balances exports\20_USA\TGT 0308.xlsx",
    diagnostics_directory=r"C:\Users\Work\github\leap_initialisation\outputs\leap_exports\supply_reconciliation\supporting_files\baseline_seed_balance_diagnostics\results_update_preview_20260803_usa_tgt",
)

result = dev.run_dashboard(
    economy="20_USA",
    comparison_data_path=r"C:\Users\Work\github\leap_mappings\results\common_esto\common_esto_comparison_data.csv",
    common_rows_path=r"C:\Users\Work\github\leap_mappings\results\common_esto\common_esto_rows.csv",
)

result = dev.run_balance_review_from_export(
    economy="20_USA",
    scenario="Target",
    year=2022,
    balance_export_workbook=r"C:\Users\Work\github\leap_initialisation\data\leap balances exports\20_USA\TGT 0408.xlsx",
)

result = dev.run_dashboard_from_export(
    economy="20_USA",
    export_dir=r"C:\Users\Work\github\leap_initialisation\data\leap balances exports\20_USA",
)
```

`codebase/portable_release/developer_launcher.py` also has a `#%%` notebook
block at the bottom: set `RUN_DEVELOPER_LAUNCHER = True`, choose
`DEVELOPER_ACTION`, fill the constants, and run the cell.

`dev.default_developer_inputs()` returns the live upstream paths developer mode
normally reads, so you do not have to remember them.

Every run writes its results, `run_manifest.json`, `run_manifest.txt`, and
`validation_report.txt` into a dated folder under the configured `output_root`,
and a log under `log_root`. Developer-mode manifests record each repository's
commit **and** whether its working tree was dirty — a dirty tree means the run
used code that is in no commit and cannot be reproduced.

### Updating the repositories safely

Nothing pulls silently. Plain `git pull` in each checkout is perfectly good; if
you want it driven from the launcher:

```python
dev.plan_repository_update()          # shows what it would do, fetches nothing
dev.update_repositories()             # prints the plan, still pulls nothing
dev.update_repositories(confirm=True) # fast-forwards, skipping dirty repos
```

It refuses any repository with uncommitted changes, and any branch with no
upstream. It only ever runs `git pull --ff-only`.

---

## 2. Portable release mode (for colleagues)

A release is a folder (or ZIP of one). Extract it anywhere and run the
executable — there is no installer, no Python, and no repository.

```
leap-review-tools-0.1.0/
  leap-review-tools.exe      the program
  _internal/                 its bundled runtime (do not edit)
  mapping-chain/             isolated leap_mappings worker executable + runtime
  config/                    approved mapping and template files (editable)
  data/                      pinned mapping artifacts and source tables
  input/                     put your input files here
  output/                    one dated folder per run
  logs/                      run logs
  licenses/                  third-party licence texts
  README.md
  release_manifest.json      exactly which commits this was built from
```

Double-click the executable for a guided flow that lists the commands, explains
each input, and asks for them one at a time. Or drive it from a terminal:

```bash
leap-review-tools.exe info
```

```bash
leap-review-tools.exe selfcheck
```

```bash
leap-review-tools.exe list
```

`selfcheck` imports everything a run needs, confirms each standard-library
module it relies on is the real one, and checks that every configuration file
and package folder is present. Run it first if anything looks wrong — it is also
what the builder runs against a freshly frozen executable before accepting it.

```bash
leap-review-tools.exe balance-review --economy 20_USA --scenario Target --year 2022 --balance-export-workbook "input\TGT 0308.xlsx" --diagnostics-directory "input\usa_tgt_diagnostics"
```

```bash
leap-review-tools.exe dashboard --economy 20_USA --comparison-data-path "input\common_esto_comparison_data.csv" --common-rows-path "input\common_esto_rows.csv"
```

The export-first commands are the normal colleague workflow. With balance
exports under `input\leap balances exports\<ECONOMY>\`, no long input paths are
needed:

```bash
leap-review-tools.exe balance-review-from-export --economy 20_USA --scenario Target --year 2022
```

```bash
leap-review-tools.exe dashboard-from-export --economy 20_USA
```

Add `--support-bundle` to any run to get a ZIP of the run manifest, validation
report, effective settings, and logs. It never contains input data — the
manifest records each input's path, size, and SHA-256 instead, which is what a
diagnosis needs.

### Windows prerequisites

- **Excel is not required.** The balance-review workbook is written with
  `openpyxl`; the dashboard is HTML and JavaScript. Excel is only needed to
  *open* the resulting workbook. The workbook is saved with full-recalculation
  flags set, so Excel recalculates its formulas on first open.
- **SmartScreen.** The executable is not code-signed. Windows will show
  "Windows protected your PC" on first run; the colleague must choose
  *More info → Run anyway*, or an administrator must whitelist it. Signing the
  executable would remove this and has not been set up.
- **Antivirus.** PyInstaller one-folder builds are occasionally flagged as
  suspicious by heuristic scanners. Distribute as a ZIP from a trusted internal
  location.
- **Path length.** The package contains deeply nested runtime files. Extract it
  somewhere short (`C:\Tools\leap-review-tools-0.1.0`), not inside a deep
  OneDrive tree.

---

## 3. What input data each command needs

### `balance-review-from-export` (recommended)

Input mode: **LEAP Energy Balance export**.

| Input | What it is |
|---|---|
| `economy`, `scenario`, `year` | The review slice, for example `20_USA`, `Target`, `2022`. |
| `balance_export_workbook` | Optional explicit Level 2+ export workbook. If omitted, the newest matching workbook is resolved from `input/leap balances exports/<ECONOMY>/`. |
| `esto_table_path` | Optional ESTO base-table override; normally omit it to use the pinned table in `data/`. |

The command runs balance diagnostics and then builds the workbook. The release
contains the read-only ESTO and 9th-edition source tables required by the first
step, so a results update, LEAP COM connection, Python, or a pre-existing
diagnostics folder is not required.

### `balance-review` (existing diagnostics)

Input mode: **existing comparison/diagnostic artifacts**.

| Input | What it is |
|---|---|
| `balance_export_workbook` | The LEAP Energy Balance export workbook (`.xlsx`) the diagnostics were computed against, exported at Level 2 detail or deeper. |
| `diagnostics_directory` | A folder containing `leap_balance_source_review.csv` and `leap_balance_source_differences.csv` (both required) and `leap_balance_mapping_issues.csv` (optional). |
| `economy`, `scenario`, `year` | Which cell of those diagnostics to build. |

> The workbook's content is the *comparison* between LEAP and the source data,
> and that comparison is computed by the **balance diagnostics** step, which is
> separate from the workbook build. There are two ways to obtain the diagnostics
> directory:
>
> 1. **Generate it from a LEAP balance export** — use
>    `balance-review-from-export` in either mode, or run
>    `codebase/balance_update_workflow.py` with `_PRESET_REVIEW_ONLY`, which
>    calls `run_baseline_seed_balance_diagnostics` and then builds the workbook
>    in one go. A fresh Level 2+ export is all you need; the diagnostics step
>    computes the comparison itself.
> 2. **Use a diagnostics folder that already exists** — this is the legacy
>    `balance-review` command and remains useful when reviewing a preserved run.
>
> **A results update / supply reconciliation run is *not* required.** That
> workflow writes values back into LEAP and is a separate, optional activity.
> Producing a review workbook does not involve it. (An earlier version of this
> document said otherwise; it was wrong.)
>
> The release deliberately accepts the larger package size so those read-only
> source tables can be bundled and identified by SHA-256.

### `dashboard-from-export` (recommended)

Input mode: **a folder of LEAP Energy Balance exports**.

| Input | What it is |
|---|---|
| `economy` | Economy to render, for example `20_USA`. |
| `export_dir` | Optional export folder; defaults to `input/leap balances exports/<ECONOMY>/`. |
| `comparison_data_path`, `common_rows_path` | Optional paired escape hatch that skips conversion and uses existing Common ESTO inputs. |

The main executable invokes the isolated `mapping-chain` worker to parse the
exports, convert LEAP results to ESTO structure, and build comparison data. It
then renders the dashboard in `output/<ECONOMY>/dashboard/`.

### `dashboard` (existing comparison data)

Input mode: **existing Common ESTO comparison data**.

| Input | What it is |
|---|---|
| `comparison_data_path` | `common_esto_comparison_data.csv` from the `leap_mappings` pipeline. |
| `common_rows_path` | `common_esto_rows.csv` from the same run. |
| `economy` | Which economy to render, e.g. `20_USA`. |

The comparison file can be close to a gigabyte for the full economy set. The
export-first command avoids transferring it; the older `dashboard` command
continues to accept it directly. Validation streams it row by row rather than
loading it, so a wrong economy is reported in seconds.

---

## 4. Changing mappings or settings without rebuilding

Everything under a release's `config/` folder is read at start-up and its
SHA-256 is recorded in every run manifest:

| File | Role |
|---|---|
| `config/dashboard/common_esto_dashboard_template.json` | page rules, chart generation, sign semantics |
| `config/dashboard/series_config.json` | series labels, visible-series rules, economy list |
| `config/dashboard/code_colors.json` | per-axis ESTO code colours |
| `config/mappings/all_demand_aggregated_components.json` | which demand sectors have no separately modelled LEAP detail |
| `config/mappings/outlook_mappings_master.xlsx` | canonical LEAP-to-ESTO mapping workbook used by the mapping worker and balance diagnostics |
| `config/mappings/source_branch_fallback_rules.csv` | interim-branch fallback rules |
| `config/balance_review/synthetic_reference_rows.csv` | synthetic reference rows for ESTO vintage alignment |
| `config/balance_review/leap_results_sheet_map.csv` | LEAP sheet/scenario resolution |
| `config/balance_review/leap_explicit_reassignments.csv` | reviewed explicit balance-row reassignments |
| `config/balance_review/balance_error_signal_rules.csv` | balance-variable roles and error-signal rules |

Replacing one of these with an approved newer version changes the next run's
behaviour immediately, with **no rebuild**, and the change is never invisible:
the new hash appears in that run's `run_manifest.json`. This is verified by
`tests/test_portable_release_package.py::test_editing_a_config_file_changes_the_next_run_manifest_hash`.

The canonical mapping workbook is packaged as an external configuration asset,
not embedded in either executable. The release never edits it. Make maintained
mapping changes in `leap_mappings`, regenerate the mapping-chain artifacts, and
build a new tested release so the workbook and pinned data stay consistent.

Note that developer mode reads these files from the live checkouts (CRLF line
endings on Windows) while a release reads them from Git blobs (LF), so the same
logical file has a different SHA-256 in the two modes. That is expected: the
hash identifies the bytes actually read.

### When a new tested release is needed instead

A **code** change always needs a new release. Configuration edits do not. In
practice:

| Change | New release? |
|---|---|
| Dashboard template, series config, colours, aggregated-components config | No — replace the file in `config/` |
| A bug in the chart generation, the workbook builder, the validation, or the run manifest | **Yes** |
| A new mapping *concept* that needs code to interpret it | **Yes** |
| A new supported command or a changed input contract | **Yes** (the manifest declares them) |
| A dependency upgrade (pandas, plotly, openpyxl) | **Yes** — the runtime is bundled |

---

## 5. Release and versioning procedure

The release contract is
[`config/portable_release_manifest.toml`](../config/portable_release_manifest.toml).
It declares the semantic version, the exact 40-character commit of each
participating repository, every source path that may be copied, every external
configuration asset, the supported commands and their input/output contract, and
the runtime packages.

### Steps

1. **Land and test the code first.** Every allowlisted path must exist at the
   commit you are about to pin, so the code commits come before the manifest
   commit.
2. **Update the manifest** — bump `release.version`, and set each repository's
   `commit` to the SHA you tested:
   ```bash
   git -C C:/Users/Work/github/leap_initialisation rev-parse HEAD
   ```
3. **Validate without building anything:**
   ```python
   from codebase.portable_release import build_release
   build_release.validate_only()
   ```
   This checks that every commit and file exists, that no path escapes a
   repository root or sits under a private/generated/cache directory, that
   source allowlists carry whole Python modules only, that no configuration
   asset is oversized, and that every declared command has an implementation.
4. **Stage, then freeze:**
   ```python
   build_release.build(freeze=False)   # staged folder only, fast
   build_release.build(freeze=True)    # staged folder + PyInstaller --onedir
   ```
   The builder reads every file with `git cat-file` at the pinned commit. It
   never checks out, resets, stashes, or otherwise touches a working tree, so
   uncommitted work-in-progress cannot reach a colleague's copy. The freeze step
   runs PyInstaller in a **subprocess from a directory containing none of the
   repositories** — running it in-process from a checkout silently baked the
   live `codebase` package into the executable.
   After freezing, the builder runs the main executable's `info` and
   `selfcheck`, plus the mapping worker's `--self-test`, and refuses the package
   if any fail. A package can start and print its version while a missing hidden
   import or a shadowed standard-library module waits to break the first real
   run, so all three checks matter.
5. **Read the release report** in `release_build/reports/`. It lists every
   staged file with its SHA-256, every configuration asset with its source
   commit, and the full package file list.
6. **Run the verification tests** (section 7).
7. **Distribute** the folder under `release_build/package/` as a ZIP. Do not
   send a release to colleagues without the user's explicit approval.

Generated staging, build, and package trees all live under `release_build/`,
which is git-ignored and contains no links, so it can be deleted by hand at any
time.

### Rollback

A release is fully described by its manifest, so rolling back is rebuilding an
older one:

1. `git log -- config/portable_release_manifest.toml` to find the version.
2. `git show <commit>:config/portable_release_manifest.toml > rollback.toml`.
3. `build_release.build("rollback.toml")`.

Because every commit is pinned, the rebuild is byte-identical in its source
content regardless of what the repositories look like now. If you only need to
identify what a colleague is running, `release_manifest.json` in their package
folder names every commit.

Do not overwrite a released version number with different content. Bump the
patch version instead, so a run manifest always identifies exactly one build.

---

## 6. Known limitations

- **The package is large.** It carries the ESTO base table, the all-economy
  9th-edition projection table, and four pre-built mapping-chain artifacts so
  both tools can start from LEAP exports. Extract it somewhere short and allow
  adequate disk space.
- **The dashboard's mapping-diagnostics page, full mapping tree explorer, and
  capacity-unmet convergence page are not in the portable release.** They read
  `leap_mappings` QA artifacts and a `leap_initialisation` run CSV — in one case
  a 22 MB structural artifact — that a package does not carry. Use
  `leap_dashboard/codebase/common_esto_dashboard_workflow.py` for those.
- **No upstream data refresh.** Source tables and mapping-chain artifacts are
  snapshots pinned into the release. Refreshing mappings or source vintages
  requires regenerating the artifacts and building a new release.
- **`leap_initialisation/codebase/__init__.py` is deliberately excluded** from
  the package. It is a re-export hub that pulls in the LEAP COM API, Excel I/O,
  and the comparison stack, none of which the supported commands need and much
  of which cannot run off a modelling workstation. Omitting it makes `codebase`
  an implicit namespace package (PEP 420) inside the release. If you add a
  command that genuinely needs something from that hub, import the owning module
  directly rather than re-adding the hub.
- **Sheet-image previews are unavailable.** `build_balance_review_workbooks(...,
  render_previews=True)` prints a warning and does nothing: the Python builder
  writes XLSX and verifies it structurally, but does not render sheet images.
  This is the one capability the pre-Python builder had that is not replaced.
- **A full dashboard render is slow** — a few minutes per economy, dominated by
  writing Plotly chart bundles. Budget accordingly when rendering several.

### Codex-only functionality

There is none left in the supported commands, and this was checked rather than
assumed. The balance-review workbook builder was migrated off
`@oai/artifact-tool` and Node.js to pure Python and `openpyxl`
(`codebase/functions/balance_review_workbook_builder.py`); `leap_mappings`
migrated its own workbook builders the same way. The only casualty of that
migration is preview rendering, above.

What was verified: the release's declared dependency closure contains no Node.js
package and no Codex-managed component; the built package contains a Python
runtime and nothing else executable; and all four declared command variants run
from the frozen package, whose bundles contain no Node.js. That is a property of the
package, not of the build machine — this machine does have Node.js installed,
and the package neither needs nor invokes it.

No command in the release depends on a Codex-managed runtime, and none was
substituted with a different spreadsheet engine.

---

## 7. Verification

```bash
"C:/Users/Work/miniconda3/python.exe" -m pytest tests/test_portable_release.py tests/test_portable_release_golden_balance_review.py tests/test_portable_release_package.py -q
```

| Test file | What it defends |
|---|---|
| `tests/test_portable_release.py` | manifest parsing and validation, path safety, developer settings, run manifest, runtime context, input validation messages |
| `tests/test_portable_release_golden_balance_review.py` | the USA 2022 golden case: structural contract, selected core values, exact reproduction of the historical reference workbook, and that no source input was modified |
| `tests/test_portable_release_package.py` | a staged package: layout, no private/generated content, **no imports from the live repositories**, a real run's outputs and manifest, config-edit detection, invalid-input behaviour |

In `leap_dashboard`:

```bash
"C:/Users/Work/miniconda3/python.exe" -m pytest tests/test_common_esto_dashboard_portable.py -q
```

The golden and package tests skip cleanly on a machine without the large local
inputs (`data/leap balances exports/`, the diagnostics output tree), which are
not tracked in Git.
