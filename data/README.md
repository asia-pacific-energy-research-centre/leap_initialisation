# Data Folder Guide

This folder holds model inputs, manually exported LEAP workbooks, reference
tables, and local caches used by the workflow scripts. Most generated workflow
outputs should go under `outputs/`, not here.

## Portable Data Bundle

The large source inputs are intentionally not stored in Git. **Bundle creation
and installation are coordinated with the sibling `leap_mappings` repository.**
Clone both repositories beside each other before running either bundle script:
`.../leap_initialisation` and `.../leap_mappings`. Running
`scripts/create_data_bundle.py` in either repository deliberately rebuilds
both bundles, so mapping inputs and initialisation inputs are refreshed at the
same time. The script stops with a clear error if the sibling checkout is
missing.

Each repository receives its own dated, commit-labelled ZIP under
`data_bundles/`. This repository's ZIP contains the maintained ESTO/9th tables,
active top-level export templates, current LEAP balance exports, and
`config/baseline_seed_validation_exception_sets.xlsx`. The exception workbook
is intentionally bundled because it contains the approved baseline-seed
validation rules. Archive folders and generated outputs are excluded.

After cloning both repositories, place the matching ZIP in each repository's
`data_bundles/` folder and run `scripts/extract_data_bundle.py` (or
`scripts/setup_clone.py`) from either checkout. It deliberately installs both
bundles. It checks that both manifests have the same `bundle_pair_id` before
installing either one; never combine ZIPs from different bundle pairs. The
extractor validates each manifest and ZIP contents, refuses unsafe paths, and
does not overwrite different local files unless `ALLOW_OVERWRITE` is deliberately
changed to `True`. The ZIPs are ignored by Git and are intended to be shared
separately through restricted storage such as Google Drive.

### Publication checklist

When publishing a code update that changes bundled inputs or their bundle
contract (normally alongside the Git push), rebuild and validate this ZIP,
upload it to the restricted Google Drive data-bundles folder, then move the
superseded ZIP for this repository into that folder's `archive/` subfolder.
Keep the newest verified ZIP in the top-level folder; do not delete historical
bundles.

## Main Reference Tables

These CSVs are the common historical/projection data sources used across
mapping, dashboard, demand, supply, and transformation workflows.

### ESTO Historical Tables

- `00APEC_2024_low_with_subtotals.csv`
  - **Current shared initialisation default**, owned by
    `codebase/configuration/workflow_config.py`.
  - Base year is configured separately as 2022; do not infer it from the
    filename.
  - Key columns are `economy`, `flows`, `products`, subtotal fields, and year
    columns.

- `00APEC_2025_low_with_subtotals.csv`
  - Retained newer-vintage comparison input used by selected utilities, such
    as the default fallback in `codebase/functions/leap_series_comparison.py`.
  - It is not the current shared supply-reconciliation default.

- `00APEC_2026_low_with_subtotals_PRELIMINARY.csv`
  - **Current shared initialisation default**, owned by
    `codebase/configuration/workflow_config.py`.
  - Preliminary 2026 ESTO issue: it may contain missing economies or
    backfilled/proxy figures. The portable data bundle includes it so a clean
    collaborator checkout has the configured source table.

The former non-subtotal filenames `00APEC_2024_low.csv` and
`00APEC_2025_low.csv` are not present in this checkout. Historical and archived
documents may still name them when describing older workflows.

### 9th Projection Tables

- `merged_file_energy_ALL_20251106.csv`
  - **Current shared initialisation projection default** for exact 9th edition
    matching, owned by `codebase/configuration/workflow_config.py`.
  - Used across active reconciliation, comparison, remap, and diagnostic
    helpers.

- `9th merged_file_energy_00_APEC_20251106.csv`
  - APEC aggregate version of the current 9th projection data.
  - The filename includes the `9th ` prefix in this checkout. The shared APEC
    source resolver recognizes this portable-bundle location directly; no
    manual duplicate under `APEC_aggregates/` is required.

- `merged_file_energy_ALL_20251106 - for chatgpt.csv`
  - Historical review/export filename; not present in this checkout and not a
    workflow source of truth.

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

The resolver matches the economy letter code as a filename token, so final
exports may carry modeller-friendly names and dates. Current examples include
`USA clean slate 28_07.xlsx`, `NZ clean slate 27_07.xlsx`, and provisional
`leap_export_template 03_CDA_COMP_GEN.xlsx`.

Resolved by `codebase/utilities/leap_export_template_resolver.py`; never build
the path by hand or assume the old
`leap_export_template <economy>.xlsx` filename shape.

**Inventory verified 2026-07-28:** all 21 economies resolve. Eleven have final
economy exports. Ten remain provisional (`03_CDA`, `04_CHL`, `06_HKC`,
`07_INA`, `08_JPN`, `09_ROK`, `14_PE`, `16_RUS`, `17_SGP`, `18_CT`).

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

The counts and named gaps below are a preserved 2026-07-17 migration snapshot,
not the current template inventory. By 2026-07-28 many additional
`* clean slate 28_07.xlsx` exports had been added. Use the resolver inventory
and fresh structural comparison for current decisions; keep this section for
the rationale and evidence that motivated per-economy ID handling.

`12_NZ` is the reference/target state. `01_AUS` was migrated to match it on
2026-07-17. Unique branch paths per area:

| Branch family | `12_NZ` | `01_AUS` | `20_USA` | Target |
| --- | --- | --- | --- | --- |
| `Demand\Other loss and own use\Oil refineries` | 0 | 0 | 21 | **0 everywhere** |
| `Demand\Other loss and own use\Non specified own uses` | 12 | 12 | 0 | **12 everywhere** |
| `Transformation\Non specified transformation\Auxiliary Fuels` | 0 | 0 | 11 | **0 everywhere** |
| `Transformation\Oil Refining\...\Auxiliary Fuels` | 23 | 23 | 23 | 23 (already aligned) |
| total branch paths | 646 | 645 | 714 | converging |

1. **Refinery own use moves to the refining process's auxiliary fuels.**
   `Demand\Other loss and own use\Oil refineries` is being deleted from every
   area; refinery own use is carried by
   `Transformation\Oil Refining\Processes\Oil Refining\Auxiliary Fuels`, which
   already exists identically (23 paths) in every area — and is already what the
   code writes. Done for `12_NZ` and `01_AUS`; pending everywhere else.
2. **Non-specified own use becomes a Demand branch.**
   `Demand\Other loss and own use\Non specified own uses` is being introduced in
   every area, replacing
   `Transformation\Non specified transformation\Auxiliary Fuels` for that
   purpose. Done for `12_NZ` and `01_AUS`; pending everywhere else.

**What "identical apart from IDs" looks like in practice.** `01_AUS` and `12_NZ`
are now migrated to the same structure: they share **644** branch paths and
differ on **143** of their `BranchID`s. Same shape, own numbering — that is the
target state, and it is exactly why an ID must never be borrowed across areas.
The one remaining structural gap is
`Transformation\Electricity interim\...\Feedstock Fuels\Ammonia`, present in
`12_NZ` and absent from `01_AUS`.

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

Aggregate sentinels (`00_APEC`, `ALL_ECONOMIES`) span areas and have no single
economy template. Active callers must inject an explicit reviewed fallback;
they must not silently borrow one economy's IDs.

### `full model export.xlsx` (retired legacy filename)

This former canonical workbook was equivalent to an older `20_USA` template.
The exact file is no longer present. Active reconciliation resolves the current
USA template through `leap_export_template_resolver.py` for shared catalog or
verification uses and resolves real-economy IDs from that economy's own
template. Archived, scrapbook, and old-workflow code may still name
`data/full model export.xlsx`; those references are historical or cleanup
evidence, not instructions to recreate the file. See
`docs/full_model_export_retirement_scope.md` for the preserved migration
rationale.

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

- a filename containing the economy's letter code as its own token; no
  `COMP_GEN` token for a final export (that token marks a provisional file);
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

- `industry export.xlsx`, `buildings export.xlsx`, related dummy-building
  variants, and `power export.xlsx`
  - Retired prototype/template filenames retained in historical documents and
    some configuration compatibility constants.
  - They are not present in this checkout and are not active
    supply-reconciliation inputs. Current generic import/export examples live
    under `codebase/examples/`; active demand and electricity/heat generation
    uses the integrated workflows.

- `refining model export.xlsx`
  - Legacy refining import workbook formerly used by the archived
    `codebase/old_workflows/refining_workflow.py`.
  - Active Oil Refining generation uses ESTO/9th inputs through
    `codebase/transformation_workflow.py`.

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

The extractor converts balance sheets into long rows and converts values to
petajoules. Canonical mapping semantics come from the sibling
`leap_mappings/config/outlook_mappings_master.xlsx`; the retired local
`config/leap_mappings.xlsx` name may appear in archived migration notes but is
not the current mapping authority.

### `leap results tables/`

Rendered LEAP Results-view workbook templates and refreshed outputs. These were
the older source for dashboard/result workflows. They remain useful to
`codebase/old_workflows/` probes and selected comparison/template utilities,
but the current dashboard consumes Common ESTO outputs and current
reconciliation uses Energy Balance exports.

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
