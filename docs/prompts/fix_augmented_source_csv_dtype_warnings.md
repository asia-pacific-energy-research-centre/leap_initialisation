# Fix augmented-source CSV dtype warnings

Type: focused implementation and regression-test prompt.
Status: pending. Do not begin while a supply-reconciliation run is active if the
fix would edit a file imported by that workflow.

## Problem

Long supply-reconciliation runs currently emit pandas `DtypeWarning`s from
`codebase/utilities/master_config.py` (currently its CSV-reader path around
line 222) when loading augmented ESTO and 9th source tables. The mixed columns
reported are metadata/flag columns such as:

- ESTO: `is_subtotal`, `_synthetic_esto_row`, `_synthetic_rule_name`;
- 9th: `_synthetic_ninth_row`, `_synthetic_rule_name`.

The warning is noisy and leaves the inferred type of source metadata dependent
on pandas chunking. It must be fixed at the source-loading boundary, rather
than suppressed globally.

## Read first

1. `AGENTS.md`, including the source-data and workflow-run rules.
2. `codebase/utilities/master_config.py`, especially the function that calls
   `pd.read_csv` for these augmented inputs.
3. Every caller of that reader and the source table schema/augmentation code.
4. Existing loader tests, including `tests/test_workflow_utils.py` and related
   ESTO/9th projection tests.

## Goal

Load the augmented ESTO and 9th CSVs deterministically without pandas
`DtypeWarning`s, preserving the existing value semantics for all workflow
consumers. Numeric year columns must remain numeric after the normal workflow
normalisation; metadata flags must retain their intended boolean/string meaning.

## Required approach

1. Reproduce the warning with the real configured 2022-base augmented inputs
   in a small read-only test or notebook-safe exploration. Identify the actual
   distinct values and intended semantics of each offending column.
2. Choose the narrowest explicit loader contract. Prefer a per-column `dtype`
   map and/or intentional post-read coercion in the shared loader. Do not use
   a blanket `low_memory=False` merely to hide the warning unless measurement
   demonstrates that it is necessary and the memory cost is accepted.
3. Keep source identifiers, rule names, and flags lossless. In particular,
   distinguish real `False`/missing metadata from string placeholders created
   during CSV augmentation.
4. Add focused regression tests using small mixed-type fixtures. They should
   assert both that no `DtypeWarning` is emitted and that each affected column
   has the expected values/type after loading.
5. Run the affected focused tests, then a representative projection or
   reconciliation preflight. Confirm that its stderr contains no warning from
   this reader and that it has no changed conservation or allocation results.

## Acceptance criteria

- No `DtypeWarning` from `master_config.py` while loading the configured
  augmented ESTO and 9th source CSVs.
- Existing consumers receive the same semantic data, including subtotal and
  synthetic-row flags.
- New regression coverage fails before the fix and passes after it.
- Focused tests and one representative preflight pass.
- Commit the implementation and tests in one small commit, then move this
  completed prompt to `docs/archive/` with a short findings note.

