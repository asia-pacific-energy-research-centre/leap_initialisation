# Baseline-seed unit review

## Purpose

The baseline-seed workflow checks the unit metadata on generated LEAP import
rows against the selected economy's reviewed LEAP export template. This is
useful when reviewing transformation rules from a clean slate: energy
fuel/product rows should normally use `Petajoule`, while a template row
configured as `Gigajoule` needs human review.

## Where the diagnostic is implemented

The implementation is in:

`codebase/supply_reconciliation/results_saver.py`

The relevant parts are:

- `_collect_gigajoule_template_rows()` identifies generated rows whose
  canonical template unit is exactly `Gigajoule`.
- The final writer combines those rows with ordinary generated/template unit
  mismatches.
- The combined report is written as
  `supply_reconciliation_unit_review.csv`.

## Where the report is written

For the current shared supporting-files output:

`outputs/leap_exports/supply_reconciliation/supporting_files/checks/supply_reconciliation_unit_review.csv`

For a labelled run, the same filename is written below that run's
`supporting_files/checks/` directory.

## Current report snapshot

The report currently contains 489 rows:

- 441 ordinary unit mismatches.
- 48 rows flagged with `template_uses_gigajoule`.
- The report includes transformation rows, not only resource rows.

The key columns are:

- `Branch Path`, `Variable`, `Scenario`, and `Region`: the LEAP row identity.
- `generated_units`: the unit produced by the workflow.
- `template_units`: the unit configured in the canonical LEAP template.
- `review_reason`: why the row needs attention.

## Important interpretation

This diagnostic does not silently change the LEAP model's unit metadata. The
canonical template is authoritative for the final export, so the report is a
review list for deciding whether a fuel/product branch in the LEAP model
should be changed from `Gigajoule` to `Petajoule`. After making that model
change, rerun the baseline-seed workflow and confirm that the relevant rows no
longer appear as `template_uses_gigajoule`.
