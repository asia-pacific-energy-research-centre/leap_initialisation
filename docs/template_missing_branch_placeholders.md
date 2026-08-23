# Missing branch placeholders in LEAP export templates

`codebase/mapping_tools/add_validation_exception_template_rows.py` formally
turns enabled, material paths in `config/baseline_seed_validation_exception_sets.xlsx`
into visible proposed branches in every available economy template. LEAP areas
are structurally consistent by design; `economies_that_need_it` records where
the data was material, not where the structural placeholder should exist.

Use the notebook-safe `apply_material_exception_placeholders` operation:

```python
# First run: no files change. It validates every intended sibling profile.
plan = apply_material_exception_placeholders(apply_changes=False)

# Only after the plan is clean: append ID-99 proposal rows and refresh coverage.
result = apply_material_exception_placeholders(apply_changes=True)
```

The apply operation always repeats its dry-run preflight before editing any
template. It then validates the written paths and refreshes the ledger's
per-economy template coverage. Every enabled exception path is proposed in
every economy template.

`baseline_seed_validation_exceptions` automatically refreshes the read-only
`baseline_seed_exception_placeholder_review.xlsx` whenever a baseline-seed run
adds a material path or disables a stale exception after a completed relevance
audit. The workbook has an `ALERTS` sheet plus one sheet per economy; economy
sheets preserve only that template's own columns. This refresh never modifies a
LEAP export template. Template edits remain an explicit later call to
`apply_material_exception_placeholders(apply_changes=True)`.

Each proposed leaf clones the complete `Variable + Scenario + Region` profile
of an unambiguous direct sibling in that same template. It retains the local
variable, scenario, and region IDs, updates the branch path and Level columns,
and sets `BranchID` to `99`. The `99` value is only a placeholder for review:
the branch still needs to be created in the corresponding LEAP area before it
can receive a real BranchID and be used for import.

If a path already exists as a real branch in one economy template, the tool
leaves it untouched. If direct siblings have conflicting largest profiles, it
raises rather than guessing which branch structure should be proposed.

After fresh exports from the LEAP areas replace every `99` placeholder with a
real local BranchID, run `sync_exception_resolution_status()`. It updates
`economies_resolved_in_templates` (using `all` only when appropriate). It does
not disable an exception: relevance audits own that decision, based on whether
the path still triggers material seed data.
