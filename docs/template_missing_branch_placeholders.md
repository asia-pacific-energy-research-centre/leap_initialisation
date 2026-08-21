# Missing branch placeholders in LEAP export templates

`codebase/mapping_tools/add_validation_exception_template_rows.py` turns each
enabled path in `config/baseline_seed_validation_exception_sets.xlsx` into a
visible proposed branch in every available LEAP Export template.

Run the notebook-safe `update_all_templates(apply_changes=False)` first. It
reports the exact number of rows each template would receive. Re-run with
`apply_changes=True` to append rows for paths that are genuinely absent in a
given economy template.

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
real local BranchID, run `sync_exception_resolution_status()`. It updates the
`resolved_in_all_templates` boolean in the exception workbook and sets
`enabled` to `False` only when the branch is real in every available template.
