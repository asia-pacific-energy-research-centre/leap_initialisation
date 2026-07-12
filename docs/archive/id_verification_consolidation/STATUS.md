# ID Verification Consolidation — Status

Archived 2026-07-11. Executed on branch `consolidate-id-verification`.

## Outcome

| Part | Status | Commit |
| --- | --- | --- |
| Item 1 — four ID/branch-match implementations | Done, verified | `10e382a` |
| Item 2 Part A — preflight state-override dedup | Done, verified | `535f09e` |
| Item 2 Part B — diagnostic-CSV report helper | Done (2026-07-11 follow-up) | `e89765a` |

## What was done

- `enrich_seed_ids_from_template` split into `build_template_id_lookup` +
  `apply_template_ids` (plus `TemplateIdLookup`, `normalize_template_key`) in
  `codebase/functions/baseline_seed_validation.py`. Behavior unchanged.
- The results saver's nested `_merge_ids_from_reference_export` replaced by
  module-level `_resolve_ids_and_filter_unmatched_export_rows`, which delegates
  ID resolution to the shared lookup. Retain/drop rule (CROSS-001), unmatched
  report shape, and the `nonzero_missing_id_rows` contract preserved.
- `validate_seed_files` (patch_baseline_seeds) now derives expected IDs from
  the same shared lookup; its bespoke per-row matching removed.
- `_apply_preflight_results_update_state` merged into a parameterized
  `_apply_preflight_compressed_state(mode=...)` with a pure
  `_build_preflight_config_overrides`; the two compressed preflights themselves
  remain separate per INIT-009.
- Tests: `tests/test_id_matching_consolidation.py` (15 tests) and per-mode
  override-dict tests in `tests/test_preflight_compressed_results_update.py`.

## Verification

Before/after equivalence run on real data (02_BD, `_PRESET_BASELINE_SEED`;
01_AUS was blocked by the unrelated pump-storage strict-check issue in the
then-uncommitted own-use work):

- `leap_import_baseline_seed_02_BD_*.xlsx` — cell-identical.
- `combined_st_02_BD_*` rule findings / issue groups / duplicate groups /
  documented exclusions and consolidated findings — byte-identical.
- Unmatched-ID report absent in both runs; source diagnostics identical.
- `validate_seed_files` output identical on all real seed files.
- `supply_recon_run_baseline_seed_02_BD_*.xlsx` — one intentional difference:
  1288 cells, all `ScenarioID`. The old Branch+Variable fallback stamped the
  first template row's ScenarioID (always Current Accounts = 1) on
  Reference/Target rows; the shared per-column matching yields the correct
  IDs (Reference→2, Target→3). A latent-bug fix, not a regression.

Full suite at completion: 466 passed, 3 failed (the pre-existing
`BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS=True` failures
documented in INIT-005 History), 11 skipped.

## Corrections to the prompt

The prompt's "wasted-computation chain" premise was wrong:
`save_results_linked_single_workbook` writes the terminal consolidated
`supply_recon_run_*.xlsx` (nothing re-reads it), it runs *after*
`write_per_economy_combined_workbooks`, and `supply_leap_imports_*.xlsx` files
come from `supply_export_builder.py`. Its ID computation was therefore live
output, not dead work. Resolution (user decision): keep (A) stamping IDs but
compute them via the shared primitive extracted from (B).

## Left open

Nothing. Part B was completed as a follow-up (`e89765a`): a shared
`_write_diagnostic_report` helper now serves the metadata-mismatch and
config-mapping-mismatch reports. Note the prompt's "trio" had drifted — the
gigajoule rows now feed a merged unit-review report with its own single-WARN
shape, so only the two preview-style blocks shared the boilerplate; the
unit-review block was deliberately left unchanged.
