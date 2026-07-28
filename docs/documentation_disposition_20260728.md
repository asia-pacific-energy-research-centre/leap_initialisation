# Markdown documentation disposition — 2026-07-28

This is the preservation-first, document-by-document disposition for all 102
tracked Markdown files that existed when the exhaustive audit began. The audit
checked current code/config/data paths, repository ownership, prompt completion
evidence, inbound relative links, and Git history where status was disputed.
This matrix itself is the only additional Markdown file created by the pass.

Decision meanings:

- **Keep-live** — maintained operating or design documentation.
- **Keep-active** — active/pending reusable prompt.
- **Keep-reference** — useful point-in-time evidence or specialist reference;
  not the main runbook.
- **Keep-historical** — settled archive record; preserved without treating its
  instructions as current.
- **Update-live** — corrected or relabeled during this audit.
- **Archive-move** — preserved with a status banner under `docs/archive/`.

No document was deleted, and no unique open item was discarded.

## Root, codebase, and data documentation

| Document at audit start | Role / verified status | Evidence and unique information | Decision |
|---|---|---|---|
| `AGENTS.md` | Contributor rules; partly stale | Unique launch traps and repo rules; parallelism and historical backlog claims contradicted current code. | Update-live |
| `README.md` | Repository introduction | Useful examples and current routing; two referenced screenshots do not exist. | Update-live |
| `Untitled-2.md` | Raw workflow stdout, not a guide | Unique zero-skeleton run evidence; no inbound references. Renamed and preserved in archive. | Archive-move |
| `codebase/mapping_code/README_dashboard_mapping_starter.md` | Frozen prototype note | Explains the nested dashboard-mapping starter; active ownership is now sibling repos. | Keep-reference |
| `codebase/old_workflows/README.md` | Legacy-code boundary | Prevents old entrypoints being mistaken for active workflows. | Keep-live |
| `data/README.md` | Data inventory and ownership guide | Current source vintages, template resolver, provisional-template meaning, and retired inputs. | Keep-live |
| `data/leap balances exports/README.md` | Input naming/placement contract | Canonical LEAP Energy Balance export location and filename rules. | Keep-live |

## Live and reference documents

| Document | Role / verified status | Evidence and unique information | Decision |
|---|---|---|---|
| `docs/README.md` | Documentation index | Main navigation; prior prompt-count and overview warnings were stale after this pass. | Update-live |
| `docs/aggregate_preflight_source_routing_contract.md` | Runtime contract | Unique `00_APEC` compressed-preflight routing rules; matched code. | Keep-live |
| `docs/aus_2022_balance_export_investigation_findings.md` | Dated findings | Preserves AUS balance evidence and follow-ups; not general instruction. | Keep-reference |
| `docs/balance_demand_conservation_check.md` | Check design | Current demand-conservation methodology and outputs. | Keep-live |
| `docs/baseline_seed_balance_diagnostics.md` | Diagnostic runbook | Current cyclical balance diagnostic design and notebook usage. | Keep-live |
| `docs/baseline_seed_rule_inventory.md` | Rule registry | Unique SEED-C rule definitions used by validation. | Keep-live |
| `docs/baseline_seed_unit_review.md` | Specialist QA note | Unit/scale review evidence and checking method. | Keep-reference |
| `docs/canonical_mapping_migration_notes.md` | Migration record | Useful C1–C7 evidence; some future-tense sections are historical and routed by the queues. | Keep-reference |
| `docs/canonical_migration_diagnostics/README.md` | Diagnostic artifact guide | Explains retained migration CSV evidence. | Keep-reference |
| `docs/check_registry.md` | Enforced check directory | Current F1–F5 ownership and gateability; covered by a repository test. | Keep-live |
| `docs/colleague_intro_all_demand_aggregated.md` | Colleague-facing guide | Unique nontechnical explanation; malformed local CSV link corrected. | Update-live |
| `docs/cross_repo_handover_index.md` | Cross-repo contract index | Current owner/consumer boundaries and refresh routing. | Keep-live |
| `docs/current_execution_roadmap.md` | Operational roadmap | Current run policy; stale “parallelism unavailable” bullet corrected against landed runner. | Update-live |
| `docs/documentation_audit_20260728.md` | First-pass audit evidence | D-01–D-13 discovery record; explicitly incomplete for archives before this follow-up. | Update-live |
| `docs/full_model_export_retirement_scope.md` | Completed execution plan | Unique dependency inventory; active file is already retired, so banner prevents re-execution. | Update-live |
| `docs/handover/supply_reconciliation_agent_guide.md` | Agent runbook | Current environment, safety, execution, and diagnostic routing. | Keep-live |
| `docs/handover/supply_reconciliation_guide.md` | Handover guide | Current end-to-end repository-owned explanation. | Keep-live |
| `docs/handover_work_queue_20260728.md` | Dated controlling queue | Prioritized evidence and handover sequencing; audit items updated after completion. | Update-live |
| `docs/leap_all_demand_aggregated_branch_guide.md` | Branch guide | Unique model-branch instructions; malformed local CSV link corrected. | Update-live |
| `docs/leap_balance_export_centralisation_audit.md` | Ownership migration record | Evidence for canonical input location across repositories. | Keep-reference |
| `docs/leap_export_readiness_plan.md` | Dated readiness plan | Useful template/ID acceptance reasoning; current status comes from newer audits. | Keep-reference |
| `docs/leap_initialisation zip_extraction_plan.md` | Completed migration/sync record | Unique inter-PC extraction and cleanup evidence; not a clean-checkout runbook. | Keep-reference |
| `docs/nz_baseline_seed_readiness_audit_20260717.md` | Dated readiness audit | Unique NZ template/ID findings. | Keep-reference |
| `docs/nz_target_results_update_20260728.md` | Dated run record | Current evidence for the NZ subtotal-mismatch blocker and required owner decision. | Keep-reference |
| `docs/process_map_agent.md` | Technical orientation | Current module/stage map; dated line-number hints are explicitly non-authoritative. | Keep-live |
| `docs/process_map_human.md` | Modeller orientation | Current plain-English process map. | Keep-live |
| `docs/refining_workflow_retirement_audit.md` | Retirement evidence | Proves active Oil Refining ownership moved to transformation workflow. | Keep-reference |
| `docs/results_update_dry_run_preview.md` | Results-update contract/history | Current update-strategy configuration and cycle evidence. | Keep-live |
| `docs/special_rules_and_design_decisions.md` | Decision log | Unique INIT/SEED/CROSS modelling decisions; authoritative for intentional exceptions. | Keep-live |
| `docs/supply_conservation_checks.md` | Check methodology | Current supply preservation and closure checks. | Keep-live |
| `docs/supply_reconciliation_workflow_guide.md` | Main modeller runbook | Current workflow, manual LEAP loop, export procedure, and reconciliation rules. | Keep-live |
| `docs/system_overview_for_rewrite.md` | Long-form architecture snapshot | Valuable pre-refactor context; current paths and historical pain points now clearly labeled. | Update-live |
| `docs/work_queue.md` | Detailed engineering log | Unique traps, evidence, and settled/open technical detail; navigation to moved prompt corrected. | Update-live |
| `docs/workflow_inventory.md` | Entry-point inventory | Current/legacy boundary; retired minor-demand and refining entrypoints corrected. | Update-live |

## Documents already archived when the audit began

All files in this section remain historical. They were checked for role,
status, unique evidence, and links; none should be moved back into live
navigation merely because an old instruction differs from current code.

| Document | Role / verified status | Evidence and unique information | Decision |
|---|---|---|---|
| `docs/archive/12_nz_baseline_seed_hardening_readiness_20260717.md` | Dated readiness record | NZ hardening state before later execution evidence. | Keep-historical |
| `docs/archive/OLD chat - fixing transfomaiton sectors.md` | Raw historical discussion | Early transformation reasoning; filename and content are intentionally archival. | Keep-historical |
| `docs/archive/aus_2022_balance_structure_review_workbook_execution_prompt.md` | Completed prompt | Preserves workbook-review procedure behind later AUS findings. | Keep-historical |
| `docs/archive/balance_demand_conservation_check_prompt.md` | Completed prompt | Implementation provenance for the live check document. | Keep-historical |
| `docs/archive/balance_demand_mapping_fixes_prompt.md` | Completed prompt | Historical mapping-fix scope and constraints. | Keep-historical |
| `docs/archive/capacity_unmet_convergence_diagnostics_prompt.md` | Completed prompt | Design provenance for current convergence diagnostics. | Keep-historical |
| `docs/archive/compressed_results_update_preflight_prompt.md` | Completed prompt | Provenance for compressed preflight behavior. | Keep-historical |
| `docs/archive/demand_conservation_lineage_feasibility_prompt.md` | Completed investigation prompt | Cross-repo feasibility reasoning retained. | Keep-historical |
| `docs/archive/demand_conservation_lineage_leap_mappings_planning_prompt.md` | Completed planning prompt | Mapping-side lineage design history. | Keep-historical |
| `docs/archive/demand_conservation_realignment_prompt.md` | Completed prompt | Explains the realigned conservation target. | Keep-historical |
| `docs/archive/export_zero_fill_consolidation_execution_prompt.md` | Completed prompt | Durable zero-fill design provenance; live check registry links here intentionally. | Keep-historical |
| `docs/archive/extend_conservation_verification_to_supply_and_transformation.md` | Completed planning prompt | Scope history for extending conservation checks. | Keep-historical |
| `docs/archive/id_verification_consolidation/STATUS.md` | Completion status | Commit/evidence summary for the consolidated ID work. | Keep-historical |
| `docs/archive/id_verification_consolidation/id_verification_consolidation_execution_prompt.md` | Completed prompt | Detailed implementation and verification history. | Keep-historical |
| `docs/archive/investigate_aus_2022_balance_export_for_seed_improvements.md` | Completed investigation prompt | Code-side completion plus manual-cycle caveat. | Keep-historical |
| `docs/archive/leap_mappings_prompt_folder_agents_review_prompt.md` | Completed cross-repo prompt | Historical prompt-governance review. | Keep-historical |
| `docs/archive/leap_mappings_stage3_anchor_validation_hotspots.md` | Completed cross-repo prompt | Stage 3 performance hotspot evidence. | Keep-historical |
| `docs/archive/managed_leap_initialisation_resume_20_usa_prompt.md` | Superseded run prompt | Preserves exact USA resume procedure for run archaeology. | Keep-historical |
| `docs/archive/managed_leap_initialisation_run_prompt.md` | Superseded run prompt | Original managed run procedure and assumptions. | Keep-historical |
| `docs/archive/other_loss_own_use_initialisation_post_initialisation_prompt.md` | Completed prompt | Proxy and post-initialisation provenance. | Keep-historical |
| `docs/archive/other_loss_own_use_proxy_hardening_prompt.md` | Completed prompt | Hardening constraints behind the current workflow. | Keep-historical |
| `docs/archive/refining_workflow_scoped_review.md` | Completed review | Evidence for refining retirement and shared-process boundary. | Keep-historical |
| `docs/archive/split_supply_reconciliation_output_by_pass_mode.md` | Completed prompt | Output-layout design history. | Keep-historical |
| `docs/archive/stop_balance_demand_parent_subtotal_double_count.md` | Completed prompt | Root-cause and guardrail history for subtotal double counting. | Keep-historical |
| `docs/archive/update_resume_prompt_after_balance_demand_fixes.md` | Completed prompt | Historical companion-prompt update. | Keep-historical |
| `docs/archive/usa_target_results_update_failure_investigation_findings.md` | Dated findings | Unique USA Target failure evidence. | Keep-historical |
| `docs/archive/usa_target_results_update_failure_investigation_prompt.md` | Completed prompt | Investigation procedure behind the findings. | Keep-historical |

## Prompt folder

| Document at audit start | Role / verified status | Evidence and unique information | Decision |
|---|---|---|---|
| `docs/prompts/AGENTS.md` | Folder policy/inventory | Inventory covered less than half the folder and named an already archived prompt; rewritten from the filesystem and evidence. | Update-live |
| `docs/prompts/advance_repo_20260722_execution_prompt.md` | Superseded session prompt | Main `[18]` work landed; roadmap owns current state. | Archive-move |
| `docs/prompts/aggregated_demand_scoped_review.md` | Partial scoped review | Cache measurement and remaining checklist still open. | Keep-active |
| `docs/prompts/baseline_seed_aus_things_to_check.md` | Active post-run checklist | Remaining AUS-specific review evidence is not duplicated elsewhere. | Keep-active |
| `docs/prompts/centralise_leap_balance_exports_across_repos.md` | Completed prompt | Centralisation is documented by the live audit/index. | Archive-move |
| `docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md` | Superseded handoff | Parallelism landed; explicit-zero design is preserved in final-owned-seed prompt. | Archive-move |
| `docs/prompts/continuation_20260723_next_session.md` | Superseded handoff | Current queues supersede its session state. | Archive-move |
| `docs/prompts/cross_repo_dependency_documentation_prompt.md` | Completed prompt | Required handover/contract set now exists. | Archive-move |
| `docs/prompts/final_owned_seed_completion_execution_prompt.md` | Deferred active design | Preserves exact owned-key/zero semantics and resume conditions. | Keep-active |
| `docs/prompts/fix_augmented_source_csv_dtype_warnings.md` | Pending implementation | Warning still recorded as open; narrow scope. | Keep-active |
| `docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` | Completed handoff | Audit work executed; remaining cleanup is in queue/cleanup plan. | Archive-move |
| `docs/prompts/initialisation_refactor_continuation.md` | Active T-register | Durable refactor decision context; moved-prompt link corrected. | Update-live |
| `docs/prompts/initialisation_refactor_thread_execution_prompt.md` | Reusable execution prompt | Current one-thread-at-a-time procedure. | Keep-active |
| `docs/prompts/nz_baseline_seed_hardening_readiness_prompt.md` | Completed prompt | NZ readiness audit and later run record supersede it. | Archive-move |
| `docs/prompts/other_loss_own_use_proxy_scoped_review.md` | Completed review | Remaining items are in the work queue. | Archive-move |
| `docs/prompts/patch_baseline_seeds_module_verification_prompt.md` | Active composite verification | Some verdicts complete; durable final evidence/caveats remain. Links to archived transformation-specific brief corrected. | Update-live |
| `docs/prompts/phase_2_configuration_standardisation_execution.md` | Active partial plan | Tests/default reconciliation remain; original “move wiring” framing requires current queue interpretation. | Keep-active |
| `docs/prompts/phase_3_canonical_mapping_migration_execution.md` | Active partial verification | D3.4/D3.5 remain; migration itself landed. | Keep-active |
| `docs/prompts/phase_4_monolith_decomposition_execution.md` | Active partial refactor brief | State-boundary remainder and historical rationale remain useful. | Keep-active |
| `docs/prompts/phase_5_feature_improvements_execution.md` | Active partial feature brief | Some independent slices remain after convergence/parallelism landed. | Keep-active |
| `docs/prompts/preset_forwarding_fix_execution_prompt.md` | Completed prompt | Work queue `[17]` is settled with five commits. | Archive-move |
| `docs/prompts/repo_cleanup_and_consolidation_plan_20260723.md` | Active partial cleanup plan | Unique measured output buckets and diagnostic/dead-code options feed INITQ-022–024. | Keep-active |
| `docs/prompts/review_nz_unmapped_leap_branch_fuel_combinations.md` | Completed one-off review | Durable outcomes are in NZ/mapping audit evidence. | Archive-move |
| `docs/prompts/run_real_template_baseline_seeds_in_three_sequential_batches.md` | Reusable long-run prompt | Still valid, but template census must be rechecked before use. | Keep-active |
| `docs/prompts/session_handoff_20260722.md` | Superseded handoff | Current roadmap and queues preserve durable state. | Archive-move |
| `docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md` | Reusable long-run prompt | Current full integration procedure; expensive and gated. | Keep-active |
| `docs/prompts/supply_reconciliation_presets_scoped_review.md` | Active scoped review | Useful preset-contract review beyond settled forwarding defect. | Keep-active |
| `docs/prompts/supply_reconciliation_results_update_execution_prompt.md` | Reusable targeted run prompt | Current named-economy results-update procedure. | Keep-active |
| `docs/prompts/supply_reconciliation_runtime_profiling_execution.md` | Completed prompt | Instrumentation and measured loop landed. | Archive-move |
| `docs/prompts/transformation_final_handoff_and_verification_prompt.md` | Completed session prompt | Current patch verification prompt preserves any durable caveat. | Archive-move |
| `docs/prompts/transformation_multi_output_default_verification_prompt.md` | Active post-run verification | Broader economy evidence remains intentionally deferred. | Keep-active |
| `docs/prompts/transformation_patch_rewire_exploration_prompt.md` | Active investigation | Rewire decision remains evidence-gated. | Keep-active |
| `docs/prompts/transformation_patch_ungate_final_verification_prompt.md` | Superseded verification prompt | Current composite patch prompt records the durable verdict/caveat. | Archive-move |
| `docs/prompts/workflow_folder_migration_and_reconciliation_verification_prompt.md` | Invalid mixed prompt | Combines unrelated refactor and production run; preserved with warning. | Archive-move |

## Result

The live surface is now intentionally small: indexes and runbooks point to
current workflow guidance; dated investigations remain reference evidence;
`docs/prompts/` contains only active/pending work; and completed prompt/session
material remains recoverable under `docs/archive/`. Future audits should update
this matrix rather than creating another competing classification.
