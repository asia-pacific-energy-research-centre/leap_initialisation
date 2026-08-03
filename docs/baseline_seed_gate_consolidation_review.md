# Baseline-seed final-artifact gate consolidation review

Date: 2026-08-03
Scope: final `leap_import_baseline_seed_*.xlsx` workbooks and the run-level
evidence needed to decide whether they are safe to import. This review separates
runtime checks from pytest coverage, and contract severity from enforcement.

## Decision summary

The central gate is additive and audit-only. No existing runtime check or test is
removed in this change.

- Pre-compute checks remain local because their source or modelling state is not
  recoverable from a saved seed.
- Producer conservation and zero-fill checks remain local and are also consumed
  as evidence by the final gate when explicit manifests/expected rows are supplied.
- Duplicate, ID, branch, share, scenario, and year validation is intentionally
  retained both before and after serialization. Both executions use functions in
  `codebase/functions/baseline_seed_validation.py`; there is no second share or
  duplicate algorithm.
- Workbook layout, artifact-set completeness, serialized-value conservation, and
  diagnostics/manifest completeness are final-only checks.
- `run_export_readiness` remains in place for producer-level repair reports. The
  run-level gate supersets, but does not replace, that useful per-workbook report.
- Promotion remains independent of the new manifest during audit qualification.

## Runtime-check inventory and disposition

Abbreviations: final = final-workbook observable; central = required in the
run-level gate.

| Existing check | Existing location and execution stage | Required information | Existing callers | Existing automated tests | Final | Central | Recommended disposition | Reason and migration risk | Test disposition / proof retained |
|---|---|---|---|---|---:|---:|---|---|---|
| `resolve_logical_duplicates` (`SEED-001`, `SEED-002`; SEED-C001–C004) | `baseline_seed_validation.py`, pre-write emit boundary | Assembled or reopened rows | full writer, results verification, patcher through `prepare_seed_rows_for_write` | `test_baseline_seed_comparison_workflow.py::{test_duplicate_resolution_prefers_only_valid_id_row_without_row_order,test_duplicate_classification_exact_and_multiple_valid_rows,test_share_validation_uses_resolved_rows_not_duplicate_physical_rows,test_conflicting_valid_rows_write_diagnostics_before_raising}`; writer and output-share duplicate tests | yes | yes, BSA-003 | intentionally retain at both layers; reuse shared function | Local execution resolves exact duplicates before write and diagnoses producer collisions; final execution proves no duplicate survived serialization. Risk of moving: invalid physical rows could reach the writer. | Keep all unit tests; new gate tests call the same function through the post-write adapter. |
| `enrich_seed_ids_from_template`, `build_template_id_lookup`, `apply_template_ids` (`SEED-003`–`SEED-005`, `SEED-011`; SEED-C005–C007/C020/C024) | `baseline_seed_validation.py`, pre-write assembly | Assembled rows plus economy template | full writer, results verification, patcher; results saver shares lookup | comparison tests for all IDs, enrichment, zero reset, label rescue, unmatched rows; writer economy-template routing tests | yes | yes, BSA-004/BSA-005 | intentionally retain at both layers; reuse lookup centrally | Producer boundary attaches canonical IDs; final comparison detects stale/wrong IDs or post-write corruption. Risk of moving: invalid IDs would be serialized and local diagnostics would lose provenance. | Keep; new tests verify wrong valid IDs and nonzero unresolved payload after reopen. |
| `complete_canonical_share_groups` (`SEED-006`–`SEED-008`; SEED-C008–C014) | `baseline_seed_validation.py`, pre-write assembly | Rows, template, configured scenario windows, capacity context | full writer, results verification, patcher; merge-only writer uses completion directly | all tests in `test_baseline_seed_canonical_groups.py`, `test_baseline_seed_output_shares.py`, and `test_zero_skeleton_scenario_borrowing.py` | yes | yes, BSA-006 | retain completion locally; reuse pure validation centrally | Completion is an assembly method and must remain pre-write. Final validation proves canonical siblings and 100% totals survived serialization. Risk of moving: the gate could diagnose but could not safely construct a valid workbook. | Keep producer/completion tests; add local/final parity test using `validate_seed_rows`. |
| `_validate_shares`, `_validate_canonical_share_completeness` (`SEED-006`–`SEED-008`) | `baseline_seed_validation.py`, pre-write validation | Rows, template, years | through `validate_seed_rows` / `prepare_seed_rows_for_write` | canonical-group, output-share, comparison, writer tests above | yes | yes, BSA-006 | intentionally retain at both layers; invoke `validate_seed_rows` centrally | It is the shared pure validator requested by the contract. Risk of a new independent implementation is divergent grouping/tolerance logic. | Keep and add final-workbook parity and corruption tests. |
| `_validate_process_efficiency_for_capacity` (`SEED-013`; SEED-C030) | `baseline_seed_validation.py`, pre-write | Final rows including capacity/efficiency expressions | same three boundary callers | `test_baseline_seed_canonical_groups.py::{test_nonzero_capacity_requires_usable_process_efficiency,test_nonzero_capacity_accepts_explicit_process_efficiency,test_process_efficiency_must_match_capacity_scenario_and_region,test_zero_or_nonprocess_capacity_does_not_require_efficiency}`; `test_process_efficiency_zero_fill.py` | yes | yes, under BSA-005 | intentionally retain at both layers through shared validator | Local producer check is more precise; final check proves the usable expression remains. Risk of moving: later diagnosis loses producer context. | Keep; shared-validator gate coverage retains final execution. |
| `check_producer_coverage` (`SEED-012`; SEED-C018) | `baseline_seed_validation.py`, before final write | Explicit expected producer paths and read results | full writer | writer tests for missing producer/path | partly (artifact set alone cannot identify omitted producer) | yes, BSA-001/BSA-010 | retain local and consume explicit producer evidence centrally | A final workbook cannot reveal which producer silently disappeared. The gate therefore requires producer evidence rather than inferring from rows. | Keep; gate tests cover missing required diagnostic/producer evidence. |
| scenario/year checks in `validate_seed_rows` (`SEED-009`, `SEED-010`; SEED-C017/C021) | `baseline_seed_validation.py`, pre-write | Rows and explicit scenario/year policy | three boundary callers | comparison configured-coverage test; writer default-window tests | yes | yes, BSA-007 | intentionally retain at both layers; reuse shared validator | Pre-write catches omissions before serialization; final rerun detects truncation/corruption. Risk of moving: invalid workbook is written before basic diagnosis. | Keep existing tests; new missing-scenario/year final test. |
| `validate_exception_records` and exact exception matching (SEED-C007/C022) | `baseline_seed_validation.py`, validation policy | Explicit narrow exception records | three boundary callers | comparison exception tests; writer zero-reset exception test | yes | yes | reuse exception semantics; do not introduce producer-wide waivers | Contract exceptions remain explicit and traceable. Risk: broad exceptions could hide hard failures. | Keep; new manifest test records applied exceptions. |
| `validate_seed_files`, `_assert_atomic_canonical_share_groups`, `_fill_ids_from_template` | `patch_baseline_seeds.py`, patch post-write/in-place path | Patched seed, template, patch scope | patch workflow | `test_baseline_seed_postprocess.py`, canonical/output-share patch tests, patch-related comparison tests | yes | yes | keep patch-specific atomicity; route eventual acceptance through central gate; follow-up to extract any still-divergent pure logic | Patch atomicity knows the selected patch scope and remains useful. `_fill_ids_from_template` is a remaining divergence risk. Removing now could weaken patch safeguards. | Keep all tests. Final gate adds independent post-serialization coverage; extraction is follow-up, not silently claimed complete. |
| `run_export_readiness`: duplicate keys, IDs, region, legacy transfer paths, fuel catalog | `utilities/leap_export_readiness.py`, post-write per workbook | Workbook, expected region, optional catalog | combined writer and producer wrappers | all tests in `test_leap_export_readiness.py`; writer readiness tests | yes | yes, BSA-003/BSA-004/BSA-005 | keep per-workbook report; central gate reuses baseline validators and records run-level disposition | Readiness provides immediate repair-oriented messages and catalog checks not all owned by the BSA contract. Its duplicate/ID checks are simpler and divergent, so it is not the new authority. Risk of retiring: callers lose established reports/catalog check. | Keep tests. BSA tests cover the run-level authority; future follow-up may adapt readiness to shared findings. |
| `find_leap_header_row`, `read_leap_sheet`, workbook preamble/layout writers | `leap_excel_io.py`, write/read boundary | Physical workbook bytes/sheets | all LEAP workbook readers/writers | all tests in `test_leap_sheet_header_detection.py`; workbook assertions in writer, aggregated-demand, and supply production tests | yes | yes, BSA-002 | reuse centrally | Header detection is already shared. Final gate adds strict required-sheet/preamble/column checks without replacing the generic reader. | Keep; new damaged-preamble/missing-sheet/column tests. |
| `zero_fill_unset_rows`, `zero_data_expression` | `export_zero_fill.py`, producer pre-emit | Producer universe, exclusions, ownership policy | demand zeroing and own-use paths | all tests in `test_export_zero_fill.py`; scenario borrowing/zero-skeleton tests | only rows are visible; authorization is not | yes, BSA-008 with explicit zero-scope evidence | keep local; central gate consumes a zero-scope manifest | The workbook cannot distinguish an authorized reset from an accidental zero. Risk of independent inference: false approval or false failures. | Keep unit tests; new unauthorized-manifest-row test. |
| `build_aux_fuel_zero_rows` capacity/efficiency safeguard | `transformation_record_builder.py`, producer gap-fill | Process ownership and in-flight capacity state | transformation/transfers producers | all tests in `test_process_efficiency_zero_fill.py` | outcome yes, modelling cause no | BSA-005 final outcome only | keep local; shared final seed validator checks resulting capacity/efficiency invariant | Producer offers precise fail-fast diagnosis. Moving loses calculation context. | Keep tests plus final shared-validator execution. |
| demand and supply/transformation reset-scope builders | `aggregated_demand_workflow.py`, `supply_reconciliation_tables.py`, producer/reset stage | Explicit selected scope and original rows | baseline/results workflows | zero-fill tests and writer/postprocess tests | authorization no | yes, BSA-008 via manifest | keep local; do not infer authorization from zeros | A zero value is not evidence of why it was written. | Keep; gate tests require evidence and flag unauthorized declarations. |
| `build_with_conservation_policy` and producer projection conservation | `conservation_policy.py`, post-compute/pre-write | Source allocation inputs and computed projection | five producers | all tests in `test_conservation_policy.py` plus projection tests | no, not by workbook alone | evidence for BSA-009, not moved | keep local; central gate compares explicit expected post-assembly values to serialized values | Producer conservation validates modelling/allocation, while BSA-009 validates serialization. Conflating them would miss both classes of defect. | Keep all; new BSA serialization-conservation test. |
| balance-demand conservation | `balance_demand_conservation.py`, diagnostic post-compute | Independent raw demand and produced demand | results saver/preflight | all tests in `test_balance_demand_conservation.py` | no | diagnostic evidence in BSA-010, not recomputed | keep local | It validates a modelling boundary unavailable in the final seed. | Keep; BSA-010 checks required diagnostic presence, not the calculation again. |
| supply conservation and results-update closure | `supply_conservation.py` / results saver, post-compute | supply references, allocation records, output rows | results saver | all tests in `test_supply_conservation.py` | no | diagnostic evidence in BSA-010; optional expected rows in BSA-009 | keep local | Final rows lack the independent reference and lineage. | Keep; no tests removed. |
| transformation output conservation | `transformation_conservation.py` / results saver, post-compute | process records and source reference | results saver | all tests in `test_transformation_conservation.py` | no | diagnostic evidence in BSA-010; optional expected rows in BSA-009 | keep local | Same reason as supply conservation. | Keep. |
| promotion (`promote_baseline_seed_to_primary_dir`) | `supply_leap_io.py`, immediately after final write/readiness | Run-scoped path and current unverified state | full writer | all tests in `test_baseline_seed_promotion.py` | n/a | eventual consumer of BSA manifest, not in audit phase | leave unchanged | Coupling now would change run/promotion behaviour, explicitly prohibited. Risk of moving: operational interruption. | Keep all promotion tests; add block-mode acceptance-unit test without wiring promotion. |
| parallel findings/workbook merge | `parallel_economy_merge.py`, parent post-worker stage | worker statuses, manifests, workbooks | parallel runner parent | all tests in `test_parallel_economy_merge.py` | yes | future parent-gate caller | keep; do not edit in this task | Master currently has unrelated work in this file. A parent audit invocation is follow-up after that work lands. | Keep tests; sequential/full writer integration is added now. |
| preflights and mapping/fuel-catalog currency checks | `supply_preflight.py`, `fuel_catalog_preflight.py`, pre-compute | source files, mappings, LEAP probe/catalog | long-run presets | preflight, fuel-catalog, resolver tests | no | no (BSA-010 may require their artifacts) | keep local | These answer readiness-to-compute, not readiness-to-emit. | Keep. |

## Automated-test disposition by suite

No relevant test is deleted, moved, weakened, or made irrelevant. The minimum
regression command retains these suites:

- `tests/test_baseline_seed_writer_validation.py` (including its documented
  warning-downgrade xfails), `test_baseline_seed_comparison_workflow.py`,
  `test_baseline_seed_canonical_groups.py`, `test_baseline_seed_output_shares.py`,
  `test_zero_skeleton_scenario_borrowing.py`;
- `tests/test_leap_export_readiness.py`, `test_leap_sheet_header_detection.py`,
  `test_export_zero_fill.py`, `test_process_efficiency_zero_fill.py`;
- `tests/test_conservation_policy.py`, `test_supply_conservation.py`,
  `test_transformation_conservation.py`, `test_balance_demand_conservation.py`;
- `tests/test_baseline_seed_promotion.py`, `test_check_registry.py`, and
  `test_parallel_economy_merge.py`;
- new `tests/test_baseline_seed_artifact_validation.py`, which covers the 20
  acceptance cases from the implementation request.

## Deliberately retained dual execution

The following are deliberately run both locally and in the final gate, through
shared functions: logical-key duplicates, template label/ID resolution, nonzero
unresolved rows, canonical share validity/completeness, process-efficiency for
capacity, and scenario/year coverage. Local execution diagnoses the producer or
assembly defect early; final execution proves the invariant survived workbook
assembly and serialization.

## Remaining divergent implementations

1. `leap_export_readiness` has its own simple duplicate and `-1` ID checks. It is
   retained for compatibility and fuel-catalog/region reporting, but it is not
   the central authority.
2. `patch_baseline_seeds._fill_ids_from_template` and its patch-specific atomic
   share assertion remain separate. Extracting shared adapters requires a focused
   patcher change and equivalence proof.
3. The dormant LEAP API normalization in `leap_core` remains divergent. The API
   is decommissioned and cannot execute; it must be reconciled before any future
   re-enablement.
4. Parallel parent invocation of the BSA gate is deferred until the active
   `parallel_economy_merge.py` work is merged; worker outputs remain auditable
   individually in the meantime.

## Exact existing pytest inventory reviewed

Every test below is retained unchanged unless this change adds an adjacent
writer-integration assertion in the same file. Parametrized cases retain their
existing parameters. This appendix is the exact test-name proof behind the
suite-level dispositions above.

### Verification recorded 2026-08-03

- New gate + writer + registry: **108 passed, 3 xfailed**. The xfails are the
  existing conditional INIT-005 warning-downgrade cases.
- Canonical shares, output shares, scenario borrowing, readiness, zero-fill,
  workbook headers, all requested conservation suites, promotion, and parallel
  merge: **130 passed**.
- A second new-gate/registry rerun after final documentation and input-normalizing
  changes: **81 passed**.
- Additional comparison/postprocess/current-accounts/export-I/O/baseline-balance
  diagnostics: **95 passed, 3 failed**. The three failures are all parametrizations
  of the pre-existing
  `test_transformation_auto_regen_modules_are_gated`: current `MODULE_REGISTRY`
  has `auto_sector_keys=None` for `oil_refineries`, `lng`, and `transformation`,
  so the asserted early `NotImplementedError` no longer occurs and the tests
  enter a real source workflow. In this isolated worktree they then stop on the
  intentionally untracked input
  `data/00APEC_2024_low_with_subtotals.csv`. None of the files changed by this
  task control that registry or patch gate; the stale gate tests / live patch
  policy contradiction remains explicit follow-up work and was not “fixed” by
  weakening its assertions.

- `tests/test_baseline_seed_comparison_workflow.py::test_default_validation_template_resolves_for_requested_economy`
- `tests/test_baseline_seed_comparison_workflow.py::test_explicit_validation_template_bypasses_economy_resolution`
- `tests/test_baseline_seed_comparison_workflow.py::test_semantic_expression_comparison_reports_only_changed_year`
- `tests/test_baseline_seed_comparison_workflow.py::test_data_and_interp_are_not_treated_as_equivalent`
- `tests/test_baseline_seed_comparison_workflow.py::test_added_and_removed_rows_are_reported`
- `tests/test_baseline_seed_comparison_workflow.py::test_share_sum_check_groups_sibling_fuel_leaves`
- `tests/test_baseline_seed_comparison_workflow.py::test_share_sum_check_flags_conflicting_duplicate_key`
- `tests/test_baseline_seed_comparison_workflow.py::test_duplicate_resolution_prefers_only_valid_id_row_without_row_order`
- `tests/test_baseline_seed_comparison_workflow.py::test_duplicate_classification_exact_and_multiple_valid_rows`
- `tests/test_baseline_seed_comparison_workflow.py::test_duplicate_resolution_accepts_mixed_type_column_labels`
- `tests/test_baseline_seed_comparison_workflow.py::test_validator_checks_all_ids_and_distinguishes_zero_reset`
- `tests/test_baseline_seed_comparison_workflow.py::test_missing_aggregated_demand_branch_is_warning_only`
- `tests/test_baseline_seed_comparison_workflow.py::test_aggregated_demand_patch_scope_does_not_strip_entire_demand_tree`
- `tests/test_baseline_seed_comparison_workflow.py::test_losses_own_use_patch_scope_strips_managed_subtree`
- `tests/test_baseline_seed_comparison_workflow.py::test_aggregated_demand_patch_threads_reconciliation_config`
- `tests/test_baseline_seed_comparison_workflow.py::test_aggregated_demand_patch_excludes_active_detailed_branch_sectors`
- `tests/test_baseline_seed_comparison_workflow.py::test_losses_own_use_patch_generates_exact_fresh_workbook_paths`
- `tests/test_baseline_seed_comparison_workflow.py::test_transformation_auto_regen_modules_are_gated`
- `tests/test_baseline_seed_comparison_workflow.py::test_transfers_patch_scope_covers_every_transfer_process_title`
- `tests/test_baseline_seed_comparison_workflow.py::test_missing_id_zero_exception_requires_rule_and_key_scope`
- `tests/test_baseline_seed_comparison_workflow.py::test_validator_handles_inactive_shares_and_configured_coverage`
- `tests/test_baseline_seed_comparison_workflow.py::test_validator_branch_existence_and_explicit_exception`
- `tests/test_baseline_seed_comparison_workflow.py::test_june_usa_fixture_heat_interim_duplicate_is_resolved_to_valid_row`
- `tests/test_baseline_seed_comparison_workflow.py::test_production_preparation_enriches_all_ids_and_collapses_exact_duplicates`
- `tests/test_baseline_seed_comparison_workflow.py::test_zero_reset_is_enriched_with_real_ids`
- `tests/test_baseline_seed_comparison_workflow.py::test_known_leap_label_exception_rescues_branch_and_variable_id`
- `tests/test_baseline_seed_comparison_workflow.py::test_genuinely_unmatched_branch_stays_minus_one`
- `tests/test_baseline_seed_comparison_workflow.py::test_share_validation_uses_resolved_rows_not_duplicate_physical_rows`
- `tests/test_baseline_seed_comparison_workflow.py::test_scenario_specific_year_and_source_coverage_block_when_incomplete`
- `tests/test_baseline_seed_comparison_workflow.py::test_conflicting_valid_rows_write_diagnostics_before_raising`
- `tests/test_process_efficiency_zero_fill.py::test_unset_efficiency_defaults_to_100_across_scenarios`
- `tests/test_process_efficiency_zero_fill.py::test_explicitly_set_efficiency_is_not_overwritten`
- `tests/test_process_efficiency_zero_fill.py::test_case_variant_catalog_branch_is_not_zero_filled`
- `tests/test_process_efficiency_zero_fill.py::test_capacity_present_but_no_efficiency_raises`
- `tests/test_process_efficiency_zero_fill.py::test_capacity_error_is_deferrable_and_skips_placeholder`
- `tests/test_process_efficiency_zero_fill.py::test_zero_capacity_does_not_trigger_error`
- `tests/test_supply_leap_io_zero_id_filter.py::test_final_writer_drops_zero_only_unmatched_transformation_rows`
- `tests/test_leap_export_readiness.py::test_readiness_runner_passes_and_writes_reports`
- `tests/test_leap_export_readiness.py::test_readiness_runner_distinguishes_zero_and_nonzero_unresolved_ids`
- `tests/test_leap_export_readiness.py::test_readiness_runner_catches_region_and_legacy_transfer_path`
- `tests/test_supply_conservation.py::test_supply_artifacts_pass_and_breakdown_reproduces_headline`
- `tests/test_supply_conservation.py::test_supply_dropped_product_is_localized_and_aggregate_is_excluded`
- `tests/test_supply_conservation.py::test_supply_empty_comparison_fails`
- `tests/test_supply_conservation.py::test_ninth_parent_fuel_row_is_excluded_when_detailed_subfuels_exist`
- `tests/test_supply_conservation.py::test_results_update_closure_passes_balanced_row`
- `tests/test_supply_conservation.py::test_results_update_closure_catches_shortfall`
- `tests/test_supply_conservation.py::test_baseline_supply_preservation_catches_unmapped_source_product`
- `tests/test_supply_conservation.py::test_exported_supply_products_exclude_unwritten_aggregate_rows`
- `tests/test_balance_demand_conservation.py::test_conservation_diagnostic_passes_equal_independent_totals`
- `tests/test_balance_demand_conservation.py::test_conservation_diagnostic_catches_value_and_missing_row_mismatches`
- `tests/test_balance_demand_conservation.py::test_conservation_diagnostic_aggregates_mapping_augmentation_duplicates`
- `tests/test_balance_demand_conservation.py::test_conservation_diagnostic_rejects_negative_tolerance`
- `tests/test_balance_demand_conservation.py::test_optional_adapter_can_combine_placeholder_and_detailed_sectors`
- `tests/test_balance_demand_conservation.py::test_results_update_excludes_detailed_leap_sector_rows_from_both_sides`
- `tests/test_balance_demand_conservation.py::test_total_energy_surface_detects_mapping_loss_across_fuels`
- `tests/test_balance_demand_conservation.py::test_raw_reference_is_built_before_fuel_mapping`
- `tests/test_balance_demand_conservation.py::test_breakdown_components_add_back_to_existing_total_difference`
- `tests/test_balance_demand_conservation.py::test_lineage_keeps_source_rows_once_and_does_not_invent_links`
- `tests/test_balance_demand_conservation.py::test_breakdown_labels_direct_proportional_and_estimated_values`
- `tests/test_balance_demand_conservation.py::test_sector_exclusions_are_applied_to_leap_rows_before_aggregation`
- `tests/test_balance_demand_conservation.py::test_breakdown_shows_leap_branch_contributions_and_exclusions`
- `tests/test_balance_demand_conservation.py::test_conservation_holds_when_produced_demand_matches_reference`
- `tests/test_balance_demand_conservation.py::test_injected_leak_in_produced_demand_is_caught_and_localized`
- `tests/test_balance_demand_conservation.py::test_lineage_actual_side_is_produced_demand_not_leap_readback`
- `tests/test_balance_demand_conservation.py::test_diagnostic_flags_compressed_projection_year`
- `tests/test_balance_demand_conservation.py::test_empty_comparison_is_failure_not_silent_pass`
- `tests/test_balance_demand_conservation.py::test_outputs_carry_schema_version`
- `tests/test_balance_demand_conservation.py::test_reference_and_produced_demand_apply_identical_exclusions`
- `tests/test_balance_demand_conservation.py::test_mis_flagged_parent_subtotal_is_excluded_from_reference_and_produced`
- `tests/test_parallel_economy_merge.py::test_merge_concatenates_findings_from_every_successful_worker`
- `tests/test_parallel_economy_merge.py::test_merge_normalizes_legacy_description_heading`
- `tests/test_parallel_economy_merge.py::test_merge_orders_rows_by_economies_run_order_then_rule_id`
- `tests/test_parallel_economy_merge.py::test_merge_skips_a_failed_worker_rather_than_treating_it_as_clean`
- `tests/test_parallel_economy_merge.py::test_merge_with_no_findings_anywhere_writes_empty_reports`
- `tests/test_parallel_economy_merge.py::test_worker_output_dir_matches_the_workflow_own_context_resolution`
- `tests/test_parallel_economy_merge.py::test_merge_parallel_results_workbooks_preserves_sequential_layout_and_data`
- `tests/test_parallel_economy_merge.py::test_merge_parallel_results_workbooks_rejects_failed_or_missing_worker`
- `tests/test_parallel_economy_merge.py::test_merge_parallel_results_workbooks_rejects_layout_drift`
- `tests/test_parallel_economy_merge.py::test_merge_parallel_results_workbooks_uses_later_economy_for_shared_proxy_rows`
- `tests/test_conservation_policy.py::test_default_is_warn_not_error`
- `tests/test_conservation_policy.py::test_check_is_attempted_strict_first`
- `tests/test_conservation_policy.py::test_failure_warns_and_retries_non_strict`
- `tests/test_conservation_policy.py::test_errors_mode_raises_and_does_not_retry`
- `tests/test_conservation_policy.py::test_policy_is_read_at_call_time`
- `tests/test_conservation_policy.py::test_non_valueerror_is_never_swallowed`
- `tests/test_conservation_policy.py::test_no_producer_defines_a_duplicate_strictness_flag`
- `tests/test_conservation_policy.py::test_transformation_assets_does_not_hardcode_strict_conservation`
- `tests/test_conservation_policy.py::test_producers_route_through_the_shared_policy`
- `tests/test_check_registry.py::test_registry_exists`
- `tests/test_check_registry.py::test_registered_check_still_exists`
- `tests/test_check_registry.py::test_registered_check_is_documented`
- `tests/test_check_registry.py::test_registry_cites_only_real_files`
- `tests/test_check_registry.py::test_five_families_are_present`
- `tests/test_check_registry.py::test_decision_rules_are_present`
- `tests/test_transformation_conservation.py::test_equal_output_passes_and_breakdown_reproduces_headline`
- `tests/test_transformation_conservation.py::test_dropped_or_duplicated_output_is_reported`
- `tests/test_transformation_conservation.py::test_negative_inputs_and_zero_skeletons_do_not_enter_outputs`
- `tests/test_transformation_conservation.py::test_raw_reference_drops_subtotal_parent_and_negative_feedstock`
- `tests/test_transformation_conservation.py::test_raw_reference_normalizes_economy_and_maps_current_accounts_to_reference`
- `tests/test_transformation_conservation.py::test_inactive_power_modules_remain_in_scope_audit_but_not_reference_total`
- `tests/test_transformation_conservation.py::test_fan_out_is_retained_once_per_contribution_and_classified_honestly`
- `tests/test_transformation_conservation.py::test_empty_comparison_fails`
- `tests/test_current_accounts_only_baseline_seed.py::test_current_accounts_only_baseline_uses_reference_internally`
- `tests/test_current_accounts_only_baseline_seed.py::test_projection_only_balance_filename_does_not_require_a_workbook`
- `tests/test_leap_sheet_header_detection.py::test_finds_header_directly_at_row_zero`
- `tests/test_leap_sheet_header_detection.py::test_finds_header_below_a_preamble`
- `tests/test_leap_sheet_header_detection.py::test_returns_none_when_absent`
- `tests/test_leap_sheet_header_detection.py::test_scan_is_unlimited_not_capped_at_six_or_eight`
- `tests/test_leap_sheet_header_detection.py::test_detection_is_case_and_whitespace_insensitive`
- `tests/test_leap_sheet_header_detection.py::test_requires_all_tokens_not_just_one`
- `tests/test_leap_sheet_header_detection.py::test_read_leap_sheet_splits_preamble_and_data`
- `tests/test_leap_sheet_header_detection.py::test_read_leap_sheet_drops_empty_rows_by_default`
- `tests/test_leap_sheet_header_detection.py::test_read_leap_sheet_can_keep_empty_rows`
- `tests/test_leap_sheet_header_detection.py::test_blank_columns_are_kept_by_default`
- `tests/test_leap_sheet_header_detection.py::test_blank_columns_can_be_dropped_on_request`
- `tests/test_leap_sheet_header_detection.py::test_missing_header_raises_with_a_useful_message`
- `tests/test_leap_sheet_header_detection.py::test_routed_callers_use_the_shared_detector`
- `tests/test_leap_sheet_header_detection.py::test_patcher_keeps_blank_spacer_removal_and_uses_unlimited_scan`
- `tests/test_leap_sheet_header_detection.py::test_supply_workbook_reader_uses_shared_unlimited_scan`
- `tests/test_leap_sheet_header_detection.py::test_export_reader_keeps_branchid_criterion_with_unlimited_scan`
- `tests/test_leap_sheet_header_detection.py::test_export_key_loader_detects_moved_export_header`
- `tests/test_leap_sheet_header_detection.py::test_results_saver_filter_detects_header_below_long_preamble`
- `tests/test_transfer_no_data_zero_skeleton.py::test_empty_process_records_write_catalog_zero_skeleton`
- `tests/test_transfer_no_data_zero_skeleton.py::test_transfer_override_writer_keeps_no_data_economy`
- `tests/test_transfer_no_data_zero_skeleton.py::test_transfer_override_writer_rejects_legacy_generic_transfer_root`
- `tests/test_transfer_no_data_zero_skeleton.py::test_transfer_projection_routes_generic_crosswalk_flow_to_active_subflow`
- `tests/test_transfer_no_data_zero_skeleton.py::test_transfer_projection_profile_rolls_active_subflow_up_before_allocation`
- `tests/test_export_zero_fill.py::test_zero_fill_only_returns_unset_keys_with_data_style`
- `tests/test_export_zero_fill.py::test_zero_fill_supports_blanket_constant_zero_with_exclusions`
- `tests/test_export_zero_fill.py::test_current_accounts_zero_expression_stays_single_year`
- `tests/test_transformation_historical_only_zero_skeleton.py::test_historical_only_output_label_is_not_added_to_zero_skeleton`
- `tests/test_transformation_lng_zero_skeleton.py::test_inactive_lng_scenario_writes_zero_skeletons`
- `tests/test_baseline_seed_promotion.py::test_promotes_run_scoped_seed_to_primary_dir`
- `tests/test_baseline_seed_promotion.py::test_unlabelled_run_is_a_no_op`
- `tests/test_baseline_seed_promotion.py::test_blocking_findings_tag_the_promoted_copy`
- `tests/test_baseline_seed_promotion.py::test_unverified_marker_composes_with_prelim`
- `tests/test_baseline_seed_promotion.py::test_marked_seeds_stay_discoverable_to_the_patcher`
- `tests/test_baseline_seed_promotion.py::test_existing_primary_seed_is_archived_not_destroyed`
- `tests/test_baseline_seed_postprocess.py::test_rule_inserts_only_triggering_template_row`
- `tests/test_baseline_seed_postprocess.py::test_rule_replaces_existing_logical_key`
- `tests/test_baseline_seed_postprocess.py::test_rule_does_not_insert_when_template_already_has_expected_value`
- `tests/test_baseline_seed_postprocess.py::test_branch_substring_and_variable_can_select_without_exact_path`
- `tests/test_baseline_seed_postprocess.py::test_economy_filter_prevents_cross_economy_override`
- `tests/test_baseline_seed_postprocess.py::test_excluded_branch_path_prevents_automatic_override`
- `tests/test_baseline_seed_postprocess.py::test_load_rules_and_reject_ambiguous_rule`
- `tests/test_baseline_seed_postprocess.py::test_load_excluded_branch_paths_from_configured_workbook`
- `tests/test_baseline_seed_postprocess.py::test_final_seed_writer_applies_enabled_postprocess_rule`
- `tests/test_zero_skeleton_scenario_borrowing.py::test_excluded_zero_skeleton_is_identified_before_name_resolution`
- `tests/test_zero_skeleton_scenario_borrowing.py::test_all_zero_group_borrows_profile_from_other_scenario`
- `tests/test_zero_skeleton_scenario_borrowing.py::test_all_zero_group_without_donor_uses_synthetic_anchor`
- `tests/test_zero_skeleton_scenario_borrowing.py::test_borrow_zero_skeleton_measures_copies_inert_values`
- `tests/test_baseline_seed_writer_validation.py::test_baseline_seed_filename_marks_comp_gen_templates`
- `tests/test_baseline_seed_writer_validation.py::test_persisted_findings_keep_only_actionable_statuses`
- `tests/test_baseline_seed_writer_validation.py::test_unlimited_expression_is_not_a_year_coverage_failure`
- `tests/test_baseline_seed_writer_validation.py::test_nonzero_balance_roots_missing_from_template_are_blocking`
- `tests/test_baseline_seed_writer_validation.py::test_all_zero_optional_roots_do_not_require_template_branches`
- `tests/test_baseline_seed_writer_validation.py::test_all_zero_optional_root_ignores_years_outside_scenario_payload`
- `tests/test_baseline_seed_writer_validation.py::test_default_scenario_windows_use_2022_base_and_2060_final_year`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_collapses_exact_duplicates_and_populates_ids`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_runs_combined_export_readiness`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_runs_central_artifact_gate_after_physical_write`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_retains_workbook_on_combined_readiness_errors`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_writes_diagnostics_before_conflict_blocks`
- `tests/test_baseline_seed_writer_validation.py::test_writer_accumulates_economy_failures_and_writes_no_final_workbook`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_writes_grouped_missing_branch_issue_summary`
- `tests/test_baseline_seed_writer_validation.py::test_missing_branch_issue_group_collapses_variables_and_scenarios`
- `tests/test_baseline_seed_writer_validation.py::test_grouped_share_issues_collapse_to_one_issue_per_share_group`
- `tests/test_baseline_seed_writer_validation.py::test_branch_issue_summary_collapses_rules_variables_and_scenarios`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_exposes_key_scoped_zero_reset_exception`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_preserves_non_branch_ids_for_warning_only_aggregated_demand_rows`
- `tests/test_baseline_seed_writer_validation.py::test_default_reference_validation_window_requires_2023_through_2060`
- `tests/test_baseline_seed_writer_validation.py::test_missing_configured_producer_for_economy_blocks_final_write`
- `tests/test_baseline_seed_writer_validation.py::test_missing_producer_finding_names_nonexistent_workbook_path`
- `tests/test_baseline_seed_writer_validation.py::test_final_writer_can_skip_validation_for_side_combines`
- `tests/test_baseline_seed_writer_validation.py::test_combined_export_blocks_by_default_on_conflicting_duplicates`
- `tests/test_baseline_seed_writer_validation.py::test_combined_export_downgrades_blocking_findings_when_configured`
- `tests/test_baseline_seed_writer_validation.py::test_combined_export_resolves_template_from_economy_label`
- `tests/test_baseline_seed_writer_validation.py::test_combined_export_explicit_template_bypasses_the_resolver`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_projection_difference_marks_cardinality_and_correction`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_base_year_uses_esto_and_matches_across_economy_code_formats`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_full_leap_path_keeps_aggregated_buildings_source_separate`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_international_demand_compares_positive_bunker_magnitude`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_aggregated_international_demand_compares_positive_bunker_magnitude`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_transfer_preserves_signed_leap_balance_mismatch`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_statistical_differences_compares_opposite_source_sign`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_base_year_backfills_mapped_pair_when_comparison_row_is_empty`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_base_year_does_not_backfill_ambiguous_multi_pair_cell`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_single_target_reassigned_base_pair_is_expected_zero`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_oil_refining_base_comparator_adds_only_configured_own_use_flow`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_lng_projection_comparator_does_not_absorb_demand_owned_own_use`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_lng_parent_projection_alias_requires_exactly_one_visible_child`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_direct_lng_fallback_uses_exact_projection_pairs_without_base_shares`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_shared_ninth_pair_across_esto_rows_requires_allocation`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_canonical_projection_allocation_resolves_shared_ninth_pair`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_canonical_projection_allocation_rolls_detailed_flows_to_parent`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_missing_reference_is_visible_but_not_called_a_mismatch`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_pre_base_historical_years_are_rejected_explicitly`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_economy_diagnostic_rejects_level1_before_conversion`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_direct_reference_workbook_uses_metadata_without_target`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_direct_workbook_metadata_accepts_thousand_petajoule`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_direct_workbook_metadata_rejects_unsupported_units`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_review_table_flags_non_comparable_total_final_energy_boundary`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_review_table_uses_imports_as_error_signal_and_protects_other_flows`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_review_marks_seed_process_and_affected_supply_fuels`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_placeholder_scope_is_visible_but_not_silently_excluded`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_more_specific_rule_can_allow_a_non_import_error_signal`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_diagnostic_counts_keep_missing_unmapped_and_total_failures_separate`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_supporting_issues_are_scoped_to_selected_years_and_scenarios`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_multi_economy_runner_writes_one_combined_table`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_mapping_issue_partition_ignores_totals_and_selected_aggregate_rows`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_comparison_partition_ignores_selected_aggregate_boundaries`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_all_demand_subtotal_flows_come_from_mapped_child_rows`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_other_sector_comparator_includes_nonenergy_base_value`
- `tests/test_baseline_seed_balance_diagnostics_workflow.py::test_esto_extraction_mapping_expands_transfer_rollup_components`
- `tests/test_baseline_seed_output_shares.py::test_transfers_unallocated_uses_genuine_output_profile_not_alphabetical_100`
- `tests/test_baseline_seed_output_shares.py::test_chp_interim_projection_years_use_electricity_and_heat_values`
- `tests/test_baseline_seed_output_shares.py::test_all_zero_chp_preserves_zero_profile_for_capacity_gated_completion`
- `tests/test_baseline_seed_output_shares.py::test_all_zero_single_output_share_is_anchored_at_100`
- `tests/test_baseline_seed_output_shares.py::test_all_zero_multi_output_share_group_is_anchored_at_100`
- `tests/test_baseline_seed_output_shares.py::test_final_export_carries_valid_share_profile_over_explicit_zero_year`
- `tests/test_baseline_seed_output_shares.py::test_patch_deduplicates_identical_rows_but_rejects_zero_vs_100_conflict`
- `tests/test_baseline_seed_canonical_groups.py::test_output_share_completion_normalizes_and_uses_nearest_profile`
- `tests/test_baseline_seed_canonical_groups.py::test_zero_capacity_allows_deterministic_complete_share_fallback`
- `tests/test_baseline_seed_canonical_groups.py::test_explicitly_nonzero_capacity_blocks_fallback`
- `tests/test_baseline_seed_canonical_groups.py::test_nonzero_capacity_requires_usable_process_efficiency`
- `tests/test_baseline_seed_canonical_groups.py::test_nonzero_capacity_accepts_explicit_process_efficiency`
- `tests/test_baseline_seed_canonical_groups.py::test_process_efficiency_must_match_capacity_scenario_and_region`
- `tests/test_baseline_seed_canonical_groups.py::test_zero_or_nonprocess_capacity_does_not_require_efficiency`
- `tests/test_baseline_seed_canonical_groups.py::test_unavailable_capacity_still_gets_deterministic_fallback`
- `tests/test_baseline_seed_canonical_groups.py::test_noncanonical_sibling_is_removed_and_remaining_group_sums_to_100`
- `tests/test_baseline_seed_canonical_groups.py::test_partial_group_validation_and_patch_both_block`
- `tests/test_baseline_seed_canonical_groups.py::test_ignored_full_model_export_leaf_is_skipped_in_canonical_share_checks`
- `tests/test_baseline_seed_canonical_groups.py::test_ignored_full_model_export_branch_is_skipped_in_presence_validation`
- `tests/test_supply_export_builder.py::test_format_scenario_label_for_filename_strips_non_alphanumeric_characters`
- `tests/test_supply_export_builder.py::test_get_region_for_economy_uses_apec_map_and_fallback`
- `tests/test_supply_export_builder.py::test_build_supply_log_rows_creates_rows_from_tiny_esto_dataset`
- `tests/test_supply_export_builder.py::test_build_supply_log_rows_records_nonzero_esto_stock_and_statistical_values`
- `tests/test_supply_export_builder.py::test_nonzero_esto_stock_and_statistical_values_survive_to_the_finished_export`
- `tests/test_supply_export_builder.py::test_balance_adjustment_rows_are_created_without_template_branches`
- `tests/test_supply_export_io.py::test_locate_supply_export_finds_explicit_and_latest_matching_files`
- `tests/test_supply_export_io.py::test_extract_export_metadata_parses_scenario_names_from_filename`
- `tests/test_supply_export_io.py::test_get_available_scenarios_reads_leap_header_row`
- `tests/test_supply_export_io.py::test_ensure_region_in_export_raises_for_missing_region`
- `tests/test_supply_export_io.py::test_get_supply_fuels_from_export_extracts_final_branch_path_segments`
