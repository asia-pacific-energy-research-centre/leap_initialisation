# `docs/` index

New here? Read in this order: root [`README.md`](../README.md) →
[`process_map_human.md`](process_map_human.md) →
[`supply_reconciliation_workflow_guide.md`](supply_reconciliation_workflow_guide.md).
Agents should read [`process_map_agent.md`](process_map_agent.md) instead of the
human map. Everything else here is reference material or a working backlog.

> **Verify before you trust.** Several documents in this repository have
> misreported their own status — the audit below records six such cases,
> including two that contradict code in this repository. Where a document's
> claim matters, check it against `git` or the code.

## Handover and work queues — start here

| File | What it covers |
|---|---|
| [`handover_work_queue_20260728.md`](handover_work_queue_20260728.md) | **Current work starts here.** Dated git/worktree state, prioritized queue INITQ-001…026, and the four-week handover plan. |
| [`work_queue.md`](work_queue.md) | The detailed engineering log — items `[0]`–`[21]`, recorded traps, and known pre-existing test failures. The reasoning behind the queue above. |
| [`documentation_audit_20260728.md`](documentation_audit_20260728.md) | File-by-file Markdown audit, findings `D-01`–`D-13`, with keep/update/archive actions. |
| [`cross_repo_handover_index.md`](cross_repo_handover_index.md) | This repository's half of the cross-repository contract: what it consumes from `leap_mappings`, what it publishes, schemas, refresh order, failure ownership. Parent document is `leap_mappings/docs/cross_repository_handover_index.md`. |
| [`current_execution_roadmap.md`](current_execution_roadmap.md) | Operational roadmap and run policy. Note `D-02`: its run-policy bullet on parallelism contradicts its own item 2. |

## Orientation

| File | What it covers |
|---|---|
| [`process_map_human.md`](process_map_human.md) | What the loop does and why, for a modeller rather than a programmer. |
| [`process_map_agent.md`](process_map_agent.md) | Module map, stage-by-stage pipeline, config sources, preset delivery, the two parallelism mechanisms, and structural traps. |
| [`workflow_inventory.md`](workflow_inventory.md) | Navigation guide for `codebase/` — live pipeline vs standalone tools vs legacy. |
| [`system_overview_for_rewrite.md`](system_overview_for_rewrite.md) | Long-form system overview. **Unverified since 2026-07-17** — see `D-13` and INITQ-026 before relying on its § 11 pain points. |

## The main workflow

| File | What it covers |
|---|---|
| [`supply_reconciliation_workflow_guide.md`](supply_reconciliation_workflow_guide.md) | The modeller-facing guide: how to run it, the LEAP export procedure (§ 9b), surplus/shortfall rules (§ 12b), and the seven supporting scripts. |
| [`special_rules_and_design_decisions.md`](special_rules_and_design_decisions.md) | The decision log — `INIT-*`, `SEED-*`, `CROSS-*`. Check here before assuming odd behaviour is a bug. |
| [`check_registry.md`](check_registry.md) | Directory of every readiness check across five families (F1–F5), with boundary-vs-local and gateability rules. Enforced by `tests/test_check_registry.py`. |
| [`aggregate_preflight_source_routing_contract.md`](aggregate_preflight_source_routing_contract.md) | How the `00_APEC` compressed preflight selects its source files. |

## Baseline seeds and the results-update loop

| File | What it covers |
|---|---|
| [`baseline_seed_rule_inventory.md`](baseline_seed_rule_inventory.md) | The SEED-C rule detail behind the baseline-seed validator. |
| [`baseline_seed_balance_diagnostics.md`](baseline_seed_balance_diagnostics.md) | Design and notebook usage for the cyclical LEAP balance diagnostics (`[21]`). |
| [`results_update_dry_run_preview.md`](results_update_dry_run_preview.md) | Update-strategy configuration and per-cycle execution history. |
| [`baseline_seed_unit_review.md`](baseline_seed_unit_review.md) | Unit-metadata checks on generated LEAP import rows. |
| [`supply_conservation_checks.md`](supply_conservation_checks.md), [`balance_demand_conservation_check.md`](balance_demand_conservation_check.md) | The conservation check families. |

## Investigations and point-in-time records

Dated findings. Historical context, not live instruction.

| File | Date |
|---|---|
| [`nz_target_results_update_20260728.md`](nz_target_results_update_20260728.md) | 2026-07-28 — the blocked NZ Target run and its two mapping decisions (INITQ-014) |
| [`aus_2022_balance_export_investigation_findings.md`](aus_2022_balance_export_investigation_findings.md) | 2026-07-28 |
| [`nz_baseline_seed_readiness_audit_20260717.md`](nz_baseline_seed_readiness_audit_20260717.md) | 2026-07-17 |
| [`full_model_export_retirement_scope.md`](full_model_export_retirement_scope.md) | 2026-07-21 — largely delivered; see `D-04` |
| [`canonical_mapping_migration_notes.md`](canonical_mapping_migration_notes.md) | 2026-07-23 — its C5 section is stale |
| [`leap_balance_export_centralisation_audit.md`](leap_balance_export_centralisation_audit.md) | 2026-07-13 |
| [`leap_export_readiness_plan.md`](leap_export_readiness_plan.md) | 2026-07-17 |
| [`leap_initialisation zip_extraction_plan.md`](leap_initialisation%20zip_extraction_plan.md) | 2026-07-22 — inter-PC `config.zip`/`data.zip` sync plan |

## Colleague-facing material

| File | What it covers |
|---|---|
| [`colleague_intro_all_demand_aggregated.md`](colleague_intro_all_demand_aggregated.md) | Introduction to the `All demand aggregated` branch for non-developers. |
| [`leap_all_demand_aggregated_branch_guide.md`](leap_all_demand_aggregated_branch_guide.md) | Branch-level guide to the same. |

## `prompts/` and `archive/`

- [`prompts/`](prompts/) — active or pending multi-step agent prompts.
  [`prompts/AGENTS.md`](prompts/AGENTS.md) is the folder policy and inventory of
  record. **Its inventory currently covers 15 of 33 files** — see `D-07`. Per
  `AGENTS.md`, a prompt whose work is complete should move to `archive/` in the
  same commit that updates the inventory; 14 prompts are overdue for that move
  (`D-08`, INITQ-008).
- [`archive/`](archive/) — completed prompt packs with their findings and status
  notes; see `archive/id_verification_consolidation/` for the pattern. Historical
  record, not routine reading.
- `canonical_migration_diagnostics/` — review CSVs from the canonical mapping
  migration, with their own [README](canonical_migration_diagnostics/README.md).

See also `data/README.md` and `codebase/old_workflows/README.md`, placed in those
folders so the guidance is where you need it.
