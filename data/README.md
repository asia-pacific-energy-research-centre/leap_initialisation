# Data Folder Guide

This folder holds model inputs, manually exported LEAP workbooks, reference
tables, and local caches used by the workflow scripts. Most generated workflow
outputs should go under `outputs/`, not here.

## Main Reference Tables

These CSVs are the common historical/projection data sources used across
mapping, dashboard, demand, supply, and transformation workflows.

### ESTO Historical Tables

- `00APEC_2024_low.csv`
  - Historical ESTO-style balance data used by older supply, transformation,
    industry, buildings, power, refining, and minor-demand workflows.
  - Key columns are `economy`, `flows`, `products`, and year columns such as
    `1990` through the latest base year in the file.

- `00APEC_2024_low_with_subtotals.csv`
  - Same 2024 ESTO source with subtotal labels added.
  - Used where workflows need to identify subtotal rows explicitly, especially
    transfer, detailed-balance, and older mapping checks.

- `00APEC_2025_low.csv`
  - Newer ESTO-style historical table.
  - Keep when comparing behavior across 2024 vs 2025 data vintages.

- `00APEC_2025_low_with_subtotals.csv`
  - Current preferred ESTO historical source for dashboard and balance-table
    comparison workflows.
  - Used by `codebase/leap_results_dashboard*_workflow.py`,
    `codebase/leap_balance_to_esto_long_workflow.py`,
    `codebase/leap_results_workflow.py`, and balance-demand logic in
    `codebase/supply_reconciliation_workflow.py`.

### 9th Projection Tables

- `merged_file_energy_ALL_20251106.csv`
  - Older 9th projection input used by several established transformation,
    supply, industry, and minor-demand workflows.
  - Keep this file because some workflow defaults still point to it.

- `merged_file_energy_ALL_20251106.csv`
  - Current preferred 9th projection table for exact 9th edition matching.
  - Used by the dashboard, balance-table, mapping-refresh, and
    `supply_reconciliation` balance-demand paths.

- `merged_file_energy_00_APEC_20251106.csv`
  - APEC aggregate version of the current 9th projection data.
  - Used by mapping and comparison preparation scripts that need aggregate
    projection rows.

- `merged_file_energy_ALL_20251106 - for chatgpt.csv`
  - Review/export copy for external inspection.
  - Do not treat it as the workflow source of truth unless a script is changed
    to point to it explicitly.

## LEAP Import Template Workbooks

These are workbook-shaped inputs that mirror LEAP Analysis-view import/export
structure. They are used as templates or reference schemas when building manual
LEAP import workbooks.

### `leap_export_templates/`

Per-economy Analysis-view export workbooks. **These are the canonical LEAP
structure and ID reference.** Each economy is a separate LEAP area, so its
`BranchID`/`VariableID`/`ScenarioID`/`RegionID` values are its own and must not
be borrowed from another economy: 134 of the 634 branch paths that `12_NZ` and
`20_USA` share carry a different `BranchID` (21%), in Resources and Demand
alike. A borrowed ID resolves and imports — into the wrong branch.

```text
leap_export_templates/leap_export_template 20_USA.xlsx
leap_export_templates/leap_export_template 12_NZ.xlsx
leap_export_templates/leap_export_template 05_PRC_COMP_GEN.xlsx
```

Resolved by `codebase/utilities/leap_export_template_resolver.py`; never build
the path by hand.

#### Areas are structurally identical by intent

**Every LEAP area is meant to have the same branch structure.** The only
differences that are legitimate are:

1. the `BranchID`/`VariableID` values themselves (each area numbers its own), and
2. possibly the distribution of fuels within the `Resources` branch.

Everything else being equal is the design. So **a structural difference between
two areas is a migration that has not finished yet — not a fact about those
economies, and not something to design around.** Do not add fallback logic,
per-area special cases, or "this economy legitimately lacks X" reasoning to
accommodate one. Finish the migration in LEAP instead.

This matters because the opposite reading is seductive and wrong. `12_NZ` has no
own-use `Oil refineries` branch, and it is true that New Zealand's only refinery
closed in 2022 — so the gap *looks* like it encodes a real fact about the
economy. It does not. `12_NZ` is simply the first area migrated; the branch is
being removed everywhere.

#### In-flight area migrations (as of 2026-07-17)

`12_NZ` is the reference/target state — it is ahead, not different. Unique branch
paths per area:

| Branch family | `12_NZ` | `20_USA` | `01_AUS` | Target |
| --- | --- | --- | --- | --- |
| `Demand\Other loss and own use\Oil refineries` | 0 | 21 | 21 | **0 everywhere** |
| `Demand\Other loss and own use\Non specified own uses` | 12 | 0 | 0 | **12 everywhere** |
| `Transformation\Non specified transformation\Auxiliary Fuels` | 0 | 11 | 11 | **0 everywhere** |
| `Transformation\Oil Refining\...\Auxiliary Fuels` | 23 | 23 | 23 | 23 (already aligned) |
| total branch paths | 646 | 714 | 665 | converging |

1. **Refinery own use moves to the refining process's auxiliary fuels.**
   `Demand\Other loss and own use\Oil refineries` is being deleted from every
   area; refinery own use is carried by
   `Transformation\Oil Refining\Processes\Oil Refining\Auxiliary Fuels`, which
   already exists identically (23 paths) in every area — and is already what the
   code writes. Done for `12_NZ`; pending everywhere else.
2. **Non-specified own use becomes a Demand branch.**
   `Demand\Other loss and own use\Non specified own uses` is being introduced in
   every area, replacing
   `Transformation\Non specified transformation\Auxiliary Fuels` for that
   purpose. Done for `12_NZ`; pending everywhere else.

**Consequence — expected `-1` rows while a migration is in flight.** A seed built
against an un-migrated area emits `BranchID=-1` for branches that area has not
caught up on, and against a migrated area emits `-1` for branches it has already
dropped. For `12_NZ` this accounts for exactly its 156 `-1` seed rows: 123
own-use refinery + 33 non-specified-transformation auxiliary fuel, **all
zero-valued**. That is the intended signal, not a defect (see the `-1` rules
below). A *nonzero* `-1` row remains actionable.

#### The `_COMP_GEN` suffix

A `_COMP_GEN` suffix marks a **provisional** template: computer-generated from
another economy's area rather than exported from its own. It carries that other
area's IDs — the current set are `20_USA`'s rows with the `Region` column
relabelled — so anything derived from one may route into the wrong branch.

They resolve and work (they reproduce the behaviour of the single shared export
they replaced), but every use prints a `[WARN]` naming the economy. To finalize
one, export that economy's Analysis view from its own LEAP area and save it
without the suffix. **A final template automatically supersedes the provisional
file**, so you can drop real exports in one at a time and delete the
`_COMP_GEN` copy whenever convenient.

`find_shared_template_areas()` reports two *final* templates claiming the same
LEAP area name, which means one was copied rather than exported. Provisional
templates are exempt — sharing the source area is what being provisional means.

Aggregate sentinels (`00_APEC`, `ALL_ECONOMIES`) span areas and have no
template; code paths fall back to `full model export.xlsx` for them.

### `full model export.xlsx` (legacy single export)

The former canonical workbook, equivalent to `20_USA`'s template. Still the
fallback for aggregate runs and for economies without a template, and still
read by workflows that have not been routed to the resolver yet (see
`docs/check_registry.md`). **Prefer `leap_export_templates/` for new code.**

#### Maintaining the export templates

These workbooks are the canonical snapshot of LEAP model structure used by
initialisation. They are a routing and schema reference, not the source of the
initialisation values. Generated expressions are written by the workflows;
the export tells those workflows which LEAP branch and variable each value can
be written to.

The workflow uses the workbook to:

- match `Branch Path`, `Variable`, `Scenario`, and `Region` to `BranchID`,
  `VariableID`, `ScenarioID`, and `RegionID`;
- validate that generated branch paths exist in the current LEAP model;
- copy or check `Scale`, `Units`, and `Per...` metadata;
- discover Resources fuels and their `Primary`/`Secondary` roots;
- discover transformation modules, processes, and their `Output Fuels`,
  `Feedstock Fuels`, and `Auxiliary Fuels` leaves;
- derive the transformation reset and zeroing scope; and
- validate completed baseline-seed workbooks before import.

Refresh an economy's template from **that economy's own LEAP area** whenever its
model structure or internal IDs may have changed. This includes adding,
deleting, renaming, moving, or deleting and recreating a branch; changing a
transformation module, process, or fuel leaf; moving a Resources fuel between
`Primary` and `Secondary`; changing an available variable; changing scenarios;
or switching to a different LEAP area. Deleting and recreating a visibly
identical branch still requires a refresh because its internal `BranchID` may
change.

Refreshing one economy's template does not affect the others. Never copy a
refreshed template across economies: that is what `_COMP_GEN` records, and its
IDs belong to the area it came from.

A refresh is not normally required for numerical changes only, such as new
ESTO/9th values, recalculated LEAP results, changed projection expressions, or
a mapping edit that does not change the LEAP branch structure.

The refreshed Analysis-view export must retain:

- filename `data/leap_export_templates/leap_export_template {economy}.xlsx`,
  e.g. `leap_export_template 12_NZ.xlsx` (no `_COMP_GEN` suffix — that marks a
  provisional file);
- sheet name `Export`;
- the two LEAP preamble rows and the header on Excel row 3;
- all branches and variables used by initialisation;
- Current Accounts, Reference, and Target scenarios;
- all four ID columns, readable key columns, metadata columns, and hierarchy
  level columns.

Archive the previous workbook before replacement. After replacing it, rerun
ID/path validation, duplicate-key checks, metadata checks, reset-scope checks,
share-total checks, and the baseline-seed comparison against the previous
accepted output for **that economy**. The exact LEAP menu sequence and export
selections still need to be captured as part of the modeller-facing LEAP export
guide.

An economy's own template is also the reference its seed is validated against:
`patch_baseline_seeds.validate_seed_files()` resolves the template per seed file
from the economy in its filename. Checking a seed against another economy's
template hides real errors — the wrong IDs match that template by construction.

#### ID integrity and `-1` values

The readable logical key for an import instruction is:

```text
Branch Path + Variable + Scenario + Region
```

The corresponding ID tuple routes the instruction inside LEAP:

```text
BranchID + VariableID + ScenarioID + RegionID
```

IDs are specific to the LEAP model and must not be guessed or copied from an
unrelated area. The workflows use `-1` when no valid lookup is available.
For ordinary Resources, Transformation, and Demand branch rows, a final `-1`
means the row cannot be relied on to import.

A nonzero row with any unresolved required ID is actionable because an
intended value may be skipped. A zero-valued `-1` row is not automatically
safe: it can still be intended to clear an existing LEAP value. Treat it as a
no-op only when the branch is deliberately absent or the row is otherwise
proved irrelevant. System-level rows exported by LEAP can legitimately have a
missing `BranchID`; they are not precedents for generated model-branch rows.

Every final logical key should occur once. Identical duplicates are redundant;
duplicates with different expressions are invalid until their source and
intended value are resolved. Do not sum physical duplicate rows when checking
shares. First resolve duplicate keys and ID validity, then check Output Share,
Process Share, and Feedstock Fuel Share across the valid sibling leaves.

- `industry export.xlsx`
  - LEAP import/export template for industry demand branches.
  - Used by `codebase/industry_workflow.py` and as the template for
    minor-demand workflows.

- `buildings export.xlsx`, `dummy buildings export.xlsx`,
  `buildings_dummy_20_USA todo add fuels to buildings export then import as banches into leap.xlsx`
  - Buildings-sector templates and working variants.
  - Used by `codebase/buildings_workflow.py` and
    `codebase/buildings_dummy_workflow.py`.

- `power export.xlsx`
  - Power-sector import workbook used by `codebase/power_workflow.py`.

- `refining model export.xlsx`
  - Refining import workbook used by `codebase/refining_workflow.py`.

- `detailed balance table output example.xlsx`
  - Template/example workbook for detailed balance-table generation.

## LEAP Results Inputs

### `leap balances exports/`

Manual Energy Balance exports from LEAP. These are now the main source for
balance-demand extraction and dashboard-independent LEAP balance tables.

See `leap balances exports/README.md` for filename rules and extraction
details. In short, workflows read workbooks like:

```text
leap balances exports/20_USA/full model output all years 04092026 REF.xlsx
leap balances exports/20_USA/full model output all years 04092026 TGT.xlsx
```

The extractor converts balance sheets into long rows, converts values to
petajoules, then maps LEAP sector/fuel pairs to ESTO flow/product pairs using
`config/leap_mappings.xlsx`.

### `leap results tables/`

Rendered LEAP Results-view workbook templates and refreshed outputs. These were
the older source for dashboard/result workflows and are still used by
`codebase/leap_results_workflow.py`, old extraction probes, and some comparison
utilities.

Typical active files are:

```text
leap results tables/transformation_results_20_USA_Reference.xlsx
leap results tables/transformation_results_20_USA_Target.xlsx
leap results tables/supply_results_20_USA_Reference.xlsx
leap results tables/supply_results_20_USA_Target.xlsx
leap results tables/industry_results_20_USA_Reference.xlsx
leap results tables/industry_results_20_USA_Target.xlsx
leap results tables/buildings_results_20_USA_Reference.xlsx
leap results tables/buildings_results_20_USA_Target.xlsx
```

Files under `leap results tables/processed tables/` are derived helper tables
for dashboards, such as transformation auxiliary own-use and derived metrics.

## Other Reference Inputs

- `Data for comparison  - APERC outlooks .xlsx`
  - External comparison workbook used by older APERC reference aggregation and
    mapping preparation scripts.

- `usa proejcted simplifeid.csv`
  - Older simplified USA projection artifact.
  - Treat as reference/scratch unless a workflow explicitly points to it.

- `population/`
  - World Population Prospects 2024 files.
  - Used as reference data for workflows or checks that need population
    indicators. These are external input files, not generated outputs.

## Cache, Archive, and Scratch Areas

- `.cache/`
  - Local pandas cache files for expensive reference-table loads.
  - Safe to regenerate. Do not edit manually.

- `archive/`
  - Old source files, backups, and damaged/corrupted workbook copies kept for
    provenance.
  - Workflows should not normally read from here unless explicitly configured.

- `temp/`
  - Scratch mapping and unmapped-label artifacts.
  - Safe to clean only after confirming no active mapping task depends on the
    files.

## Editing Rules

- Prefer adding new generated artifacts under `outputs/`, not `data/`.
- Keep canonical input filenames stable unless you also update every workflow
  constant that references them.
- When replacing a canonical CSV or workbook, archive the old copy first.
- Keep files that are manually exported from LEAP in the matching LEAP folder:
  Energy Balance exports go in `leap balances exports/`; Results-view exports
  go in `leap results tables/`.
- For current balance/dashboard work, default to
  `00APEC_2025_low_with_subtotals.csv` and
  `merged_file_energy_ALL_20251106.csv` unless the workflow explicitly requires
  an older data vintage.
