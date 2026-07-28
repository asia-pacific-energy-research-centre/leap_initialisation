# Hierarchy/subtotal structural contract

`leap_initialisation` consumes structural subtotal truth from the versioned
artifact published by `leap_mappings`. It does not import an arbitrary mappings
checkout and does not reconstruct structural parenthood from source flags.

Use
`codebase/mappings/hierarchy_subtotal_contract_loader.py` with an explicitly
managed artifact directory and expected build/input hashes. Invalid, missing,
stale, or mismatched selections fail without fallback.

`attach_structural_pair_status()` adds:

- `structural_pair_is_subtotal`;
- `structural_pair_resolved`;
- `structural_contract_dataset_id`.
- `declared_output_is_subtotal` when supplied by the selected contract;
- `structural_pair_synthetic_status` when supplied by the selected contract.

Period-specific source fields such as Ninth `subtotal_layout` /
`subtotal_results` and ESTO `is_subtotal` may remain in value-preparation
filters. They are contextual evidence and must not overwrite the structural
columns.

For Common ESTO, `structural_pair_is_subtotal` means ordinary parenthood only.
`declared_output_is_subtotal` additionally covers typed expanding,
non-expanding, and detached output boundaries that must be filtered as
subtotal rows without becoming ordinary parents. Common ESTO rows in
`value_conformance_diagnostics.csv` preserve `run_id`, `comparison_scope`, and
`source_system`, so inherited source inconsistencies remain attributable.

Runtime workflow wiring remains a reviewed migration step because the
initialisation worktree contained active unrelated changes during MAPQ-030.
The loader and compatibility tests are isolated so that integration can be
completed without importing mappings code or disturbing those changes.
