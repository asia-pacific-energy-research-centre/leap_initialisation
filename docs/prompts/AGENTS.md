# Prompt folder guide

This folder is for active, reusable execution prompts. A prompt belongs here
only while it describes work that is incomplete or a run procedure that will
be reused. Completed and superseded prompts belong in `docs/archive/`, with a
short status banner that routes any durable open item to the work queue.

When adding or changing a prompt:

- add or update its row in the inventory below;
- verify paths, presets, flags, function names, and any line-number hints
  against current code;
- state purpose, prerequisites, validation, stop conditions, and current
  status;
- preserve unrelated working-tree changes and require `git status --short`;
- for a long workflow run, follow the launch and polling rules in the root
  `AGENTS.md`;
- archive the prompt in the same commit when its work is complete or it is
  superseded.

## Active prompt inventory

Reviewed exhaustively on 2026-07-28. Every Markdown file currently in this
folder appears exactly once below.

| Prompt | Type and status | Purpose / evidence | Before use |
|---|---|---|---|
| `aggregated_demand_scoped_review.md` | Scoped review; partial | Cache-measurement and any remaining aggregated-demand review work. Earlier implementation slices landed. | Re-check the remaining checklist against `docs/work_queue.md`; do not repeat completed work. |
| `baseline_seed_aus_things_to_check.md` | Post-run review; active | Focused Australia checklist for the next full seed, including the remaining Bitumen/display-name check. | Use only with a fresh comparable AUS run and record the exact source/template vintages. |
| `final_owned_seed_completion_execution_prompt.md` | Implementation; active | Template-aware final completion of explicitly owned missing seed keys. | Start diagnostics-only; do not turn this into blanket zero-fill or migrate an ownership domain without equivalence evidence. |
| `fix_augmented_source_csv_dtype_warnings.md` | Implementation; pending | Removes known augmented-source CSV dtype warnings without changing values. | Confirm the warning still reproduces and no reconciliation run is active before editing shared files. |
| `initialisation_refactor_continuation.md` | Open-thread register; active | Current T-register for refactor decisions and landed work. | Reconcile against `docs/work_queue.md` and the dated handover queue before selecting a thread. |
| `initialisation_refactor_thread_execution_prompt.md` | Execution procedure; active | Procedure and evidence standard for executing one refactor thread at a time. | One thread per task; recommendations are not automatic approval for modelling decisions. |
| `patch_baseline_seeds_module_verification_prompt.md` | Verification; active but partly historical | Durable per-module patch verdicts; transformation-specific ungate work is archived, while final module evidence and losses/own-use strip-scope caveats remain useful. | Treat its status paragraphs independently and re-check the active preset plus current verdict comment. |
| `phase_2_configuration_standardisation_execution.md` | Implementation; active | Completes wrapper configuration standardisation, now primarily through missing forwarding/default tests. | The wiring largely predates this phase; do not mechanically move modelling rules. See INITQ-019. |
| `phase_3_canonical_mapping_migration_execution.md` | Verification/decision; partial | Migration implementation landed; D3.4/D3.5 confirmation and final equivalence/ownership evidence remain. | Canonical mapping ownership belongs to `leap_mappings`; local legacy workbooks are not active authorities. |
| `phase_4_monolith_decomposition_execution.md` | Refactor; partial | Historical split context plus remaining state-boundary decisions. | Re-measure files and use the current roadmap; old LOC figures are not maintained facts. |
| `phase_5_feature_improvements_execution.md` | Feature plan; partial | Convergence history and parallelism largely landed; remaining independently shippable improvements are tracked in the queues. | Select only a still-open slice and verify its dependency gates first. |
| `repo_cleanup_and_consolidation_plan_20260723.md` | Cleanup plan; partial | Preserves measured output-size buckets, diagnostics consolidation options, and dead-code review evidence. | Destructive cleanup needs explicit scope; use INITQ-022 through INITQ-024 as the current decisions. |
| `run_real_template_baseline_seeds_in_three_sequential_batches.md` | Long-running execution; active | Runs the 11 real-template economies in three sequential batches. | Recount real vs `_COMP_GEN` templates immediately before launch and use per-process snapshots; do not infer readiness from filename alone. |
| `supply_reconciliation_full_baselineseed_run_execution_prompt.md` | Long-running execution; active | Full 21-economy baseline-seed integration run and findings review. | Expensive; verify presets, labels, warning gate, and current template census first. |
| `supply_reconciliation_presets_scoped_review.md` | Scoped review; active | Reviews preset contracts and forwarding without broad refactoring. | Cross-check against settled work queue item `[17]`; do not reopen the already-fixed forwarding defect. |
| `supply_reconciliation_results_update_execution_prompt.md` | Long-running execution; active | Runs a targeted results update for a named economy/scenario scope. | Requires current LEAP Energy Balance exports; check mapping/subtotal blockers before launch. |
| `transformation_multi_output_default_verification_prompt.md` | Post-run verification; active | Broadens verification of the `multi_output=True` correction beyond the USA spot-check. | Bundle with the next suitable full seed; keep it separate from new transformation design. |
| `transformation_patch_rewire_exploration_prompt.md` | Investigation; active | Explores whether the transformation patch path should be rewired to the workbook producer. | Investigation only until representative equivalence evidence supports a change. |

## Recently archived by the 2026-07-28 audit

The following completed, superseded, or invalid prompts were moved to
`docs/archive/` with status banners:

- `advance_repo_20260722_execution_prompt.md`
- `centralise_leap_balance_exports_across_repos.md`
- `continuation_20260722_phase4_parallelism_and_release_readiness.md`
- `continuation_20260723_next_session.md`
- `cross_repo_dependency_documentation_prompt.md`
- `handoff_20260723_docs_audit_and_cleanup.md`
- `nz_baseline_seed_hardening_readiness_prompt.md`
- `other_loss_own_use_proxy_scoped_review.md`
- `preset_forwarding_fix_execution_prompt.md`
- `review_nz_unmapped_leap_branch_fuel_combinations.md`
- `session_handoff_20260722.md`
- `supply_reconciliation_runtime_profiling_execution.md`
- `transformation_final_handoff_and_verification_prompt.md`
- `transformation_patch_ungate_final_verification_prompt.md`
- `workflow_folder_migration_and_reconciliation_verification_prompt.md`

The explicit-zero-in-seed question from the archived 2026-07-22 continuation
prompt remains preserved in
`final_owned_seed_completion_execution_prompt.md`. No open item was discarded
by the move.
