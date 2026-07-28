# Build an AUS 2022 balance-structure diagnostic workbook

Archived 2026-07-28 after implementation, workbook generation, visual
verification, and repository validation.

## Short version

Create a reusable workbook builder that places the AUS 2022 diagnostic results
back into the same row/column structure and formatting as the LEAP Energy
Balance export. The final workbook must make the problem visible spatially:

1. `LEAP Values` - the supplied LEAP balance values, unchanged;
2. `LEAP - Source Error` - `LEAP - source` values in red;
3. `Correct Source Values` - source values in blue; and
4. `Missing Combinations` - every source-unavailable, unmapped, or
   structure-unresolved sector/fuel combination.

Use `@oai/artifact-tool` for all workbook reading and authoring. Render and
visually inspect every sheet before completion.

## Type and current status

- Type: implementation plus spreadsheet verification.
- Status: ready to execute.
- Scope: the corrected `01_AUS`, Reference, 2022 diagnostic cycle.
- Reusability: keep economy, year, scenario, source workbook, diagnostics
  directory, and output path as clear constants or explicit function inputs.

## Update before use

Paths and filenames below are current as of 2026-07-28. Before running:

1. run `git status --short` and preserve unrelated changes;
2. verify each input exists;
3. inspect the source workbook metadata rather than trusting its folder name;
4. verify the diagnostic CSV schemas with a compact read; and
5. use the current spreadsheet skill and loader-provided runtime paths.

Do not use a workbook from the preserved invalid USA-labelled comparison:
`20_USA_2022_20260728_INVALID_MISFILED_AUS`.

## Inputs

### LEAP balance structure and actual values

```text
C:\Users\Work\github\leap_initialisation\data\
leap balances exports - testing\01_AUS\2022.xlsx
```

Required metadata:

- Area title identifies the AUS area;
- Scenario is `Reference`;
- Year is `2022`; and
- Units are `Petajoule`.

### Corrected AUS diagnostic outputs

```text
C:\Users\Work\github\leap_initialisation\outputs\leap_exports\
supply_reconciliation\supporting_files\
baseline_seed_balance_diagnostics\01_AUS_2022_POST_EFF_FIX_20260728\
```

Required files:

- `leap_balance_source_differences.csv`;
- `leap_balance_source_review.csv`; and
- `leap_balance_mapping_issues.csv`.

The worktree copies are equivalent, but the main-repository copies above are
the user-facing sources and should be preferred.

### Optional comparison context

The earlier stable issue register is useful for spot checks and labels, but it
must not override the new numerical results:

```text
outputs/leap_exports/supply_reconciliation/supporting_files/
baseline_seed_balance_diagnostics/01_AUS_2022/
aus_2022_mismatch_issue_register.csv
```

## Output

Write exactly one final workbook to the normal main-repository output tree:

```text
C:\Users\Work\github\leap_initialisation\outputs\leap_exports\
supply_reconciliation\supporting_files\
baseline_seed_balance_diagnostics\01_AUS_2022_POST_EFF_FIX_20260728\
aus_2022_balance_structure_review.xlsx
```

Do not make the worktree output the only user-facing copy. The user must be
able to open the final path directly in File Explorer.

## Required implementation

### 1. Preserve the source layout

- Import the source `2022.xlsx`.
- Render and inspect it before changing anything.
- Preserve the visible 39-column by 138-row Energy Balance structure, including
  row hierarchy/indentation, fuel headers, number formats, widths, heights,
  fills, fonts, borders, and metadata rows.
- Rename or copy the original sheet to `LEAP Values`; its values must remain
  unchanged.
- Create the two balance-shaped diagnostic sheets by copying the same layout
  and formatting. Do not reconstruct an approximate table from scratch.
- Keep freeze panes, gridline behaviour, merged cells, and print-oriented
  layout where the artifact API preserves them.

### 2. Map diagnostics to balance cells explicitly

Use the visible balance-row/fuel pair as the cell key:

- source workbook row label: column A, normalized only for surrounding
  whitespace/indentation;
- source workbook fuel label: the row-3 column header;
- diagnostic row label: prefer `leap_balance_row`, with documented fallback to
  `leap_sector_names`;
- diagnostic fuel label: prefer `leap_balance_fuel`, with documented fallback
  to `leap_fuel_names`.

Do not silently choose among duplicate normalized keys. If a diagnostic pair
does not resolve to exactly one balance cell, list it on `Missing Combinations`
with `structure_resolution_status` and the candidate count.

Every diagnostic row must end in exactly one auditable state:

- mapped to one balance cell;
- reference/source unavailable;
- missing explicit LEAP-to-ESTO pair;
- absent from the visible balance structure; or
- ambiguous structure resolution.

Write summary counts and assert that no input diagnostic row is silently lost.

### 3. `LEAP Values`

- Preserve the original numeric cells exactly.
- Change only the sheet name and, if helpful, add a compact sheet-specific
  descriptor without obscuring the original area/scenario/year metadata.
- No diagnostic colour overlay is needed on this sheet.

### 4. `LEAP - Source Error`

- Keep the copied row/column labels and source formatting.
- Clear the copied body values before populating diagnostics so stale LEAP
  values cannot be mistaken for errors.
- For a comparable mapped pair, write `difference_pj`, whose definition is:

```text
LEAP value - source value
```

- Store errors as numeric values, not formatted text.
- Use dark red font and a restrained pale-red fill for nonzero mismatches.
- Show exact or within-tolerance matches as numeric zero with neutral/subtle
  formatting.
- Do not invent aggregate totals. Populate a total only when a diagnostic row
  explicitly supplies that exact row/fuel comparator; otherwise leave it blank
  and account for it on `Missing Combinations`.
- Update the metadata/title text so the sheet cannot be confused with actual
  LEAP values.

### 5. `Correct Source Values`

- Keep the copied row/column labels and source formatting.
- Clear copied body values before populating diagnostics.
- For each comparable mapped pair, show the correct `source_value_pj`.
- Prefer an auditable formula:

```excel
='LEAP Values'!B4-'LEAP - Source Error'!B4
```

  using the actual corresponding cell address. If artifact-tool formula
  support or source precision makes this unsafe, write the numeric
  `source_value_pj` and record the reason in the build summary.
- Style populated correct values with dark blue font and restrained pale-blue
  fill.
- Keep values numeric and retain Petajoule number formatting.
- Update the metadata/title text so the sheet cannot be confused with actual
  LEAP values.

### 6. Missing and unavailable combinations

Create a fourth sheet named `Missing Combinations`. Include:

- all `reference_unavailable` rows from the differences/review data;
- all `missing_esto_pair` rows from the mapping-issues data;
- all diagnostics that cannot resolve to exactly one source-layout cell;
- the three `total_balance_mapping_check` rows, clearly labelled as aggregate
  comparison-boundary errors rather than ordinary missing cell mappings; and
- any source-layout cell that is deliberately left blank because an exact
  comparable diagnostic does not exist, if it is material or otherwise
  important for interpreting totals.

Use a narrow, inspectable table with at least:

- category;
- economy;
- scenario;
- year;
- LEAP balance row;
- LEAP fuel;
- LEAP value (PJ), when available;
- diagnostic/source status;
- reason/details;
- present in visible structure;
- candidate cell count;
- intended cell address, when uniquely identified; and
- recommended interpretation.

Use pale yellow for unavailable/mapping-review rows and pale red for aggregate
boundary errors. Freeze the header and add filters if supported.

Where a missing/unavailable pair resolves to a visible balance cell, also mark
that cell on both diagnostic-shaped sheets with a pale-yellow fill while
leaving the value blank. The dedicated sheet remains the full audit trail.

### 7. Legend and explanation

Make colour meaning explicit without altering the balance shape:

- red = `LEAP - source` mismatch;
- blue = correct source value;
- yellow blank = no safe source comparator or unresolved mapping;
- uncoloured/zero = within tolerance.

A compact legend may be placed in unused cells to the right/below the used
balance range only if it does not expand or distort the main print layout.
Otherwise put the legend at the top of `Missing Combinations`.

## Important interpretation constraints

- This workbook is a diagnostic view, not an update file for LEAP.
- Do not modify the source workbook.
- Do not apply corrections to LEAP, baseline seeds, mappings, or ESTO data.
- Do not treat `reference_unavailable` as numeric zero.
- Do not fabricate row-level values from aggregate comparisons.
- Do not silently divide a shared/aggregate difference across cells.
- Do not treat the invalid USA-labelled run as evidence.
- Retain signs exactly as reported.

## Implementation shape

- Use one executable `.mjs` builder and the loader-provided Node runtime and
  `node_modules`.
- Keep the builder reusable through clear constants and small functions; avoid
  a framework or speculative abstraction.
- Work in a writable task-specific temporary/output directory and create the
  required `node_modules` junction there. Never modify the loader dependency
  directory.
- Use block reads/writes where practical.
- Use `apply_patch` for repository file changes.
- If a reusable source file is added to the repository, give it a clear
  workflow-oriented name and a short top comment describing the output.

## Verification

The task is not complete until all of the following pass:

1. Input metadata is `01_AUS`, `Reference`, `2022`, `Petajoule`.
2. The original source workbook remains byte-for-byte unchanged.
3. `LEAP Values` has the same row/column labels and numeric values as the
   source sheet.
4. The two diagnostic sheets have the same structural labels and formatting.
5. A representative set of cells reconciles:

```text
LEAP value - error = correct source value
```

   Include at least:
   - a large supply mismatch;
   - a transformation mismatch;
   - an own-use mismatch;
   - an exact/near match; and
   - a missing/unavailable comparator.
6. Workbook summary counts reconcile with the corrected run:
   - 195 comparison rows;
   - 102 mismatches;
   - 56 matches;
   - 37 reference-unavailable rows;
   - 152 mapping/check issue rows;
   - 149 missing ESTO-pair rows; and
   - 3 total-balance mapping-check rows.
7. No formula errors are present.
8. Render and visually inspect all four sheets. Also inspect representative
   regions containing large mismatches, transformations, and own use so colour
   and alignment are legible.
9. The final workbook opens from the main-repository path.
10. Run relevant repository tests and `git diff --check`.

Save render previews only as temporary verification artifacts; do not publish
them beside the final workbook unless they are needed to explain a limitation.

## Documentation and git

- Add a brief note to `docs/work_queue.md` item `[21]` describing the new
  balance-shaped review surface.
- Commit only files created or changed for this feature.
- Prefix the commit message with `codex:`.
- After implementation, testing, and commit, move this prompt from
  `docs/prompts/` to `docs/archive/` and remove its row from the active prompt
  inventory in `docs/prompts/AGENTS.md`.

## Stop conditions

Stop and ask the user if:

- the source workbook metadata is not AUS / Reference / 2022 / Petajoule;
- the source workbook is locked in a way that prevents a safe read;
- duplicate normalized row/fuel keys make a material diagnostic ambiguous and
  cannot be represented explicitly on `Missing Combinations`;
- preserving the source formatting requires an unsupported artifact-tool
  operation that would materially change the requested result; or
- writing the final workbook would overwrite an existing, unverified workbook.

Do not stop merely because mappings are missing: exposing those missing
combinations is a required output of this task.
