# Prompt Folder Guide

This folder is for active, reusable execution prompts. A prompt belongs here
only while it describes work that is not yet complete or a run procedure that
will be reused.

When a prompt's work is implemented, tested, and committed, move the prompt to
`docs/archive/` with any related status notes. This is required cleanup for
completed prompts, not optional housekeeping. Do not leave completed prompts in
this folder. If a prompt is superseded by a newer prompt, archive or delete the
old one in the same commit that adds the replacement.

## Adding New Prompts

When adding a prompt:

- Add a row to the inventory below in the same commit.
- Include the prompt's purpose, scope, prerequisites, validation expectation,
  and current status.
- Name the file around the work, not the agent. Prefer
  `thing_to_do_execution_prompt.md` over broad names like `next_prompt.md`.
- State whether the prompt is for implementation, verification, long-running
  execution, investigation, or post-run review.
- Include clear stop conditions: when to ask the user, when to stop and report,
  and what evidence is needed before making a code or data change.
- If the prompt mentions paths, presets, flags, or line numbers, include an
  "update before use" note so future agents verify them against current code.

## Removing Prompts

Remove or archive a prompt when any of these are true:

- The work is complete and committed.
- The prompt describes a one-off run that has already been performed and
  reported.
- The prompt is contradicted by current code or newer documentation.
- The prompt mixes multiple unrelated objectives and cannot be executed safely
  without rewriting.

Archive completed prompt packs under `docs/archive/`, ideally with a short
status note or findings file when the work produced important decisions.

## Prompt Writing Tips

Good prompts in this repo are specific, testable, and conservative.

- Start with a short version that says exactly what to do.
- Separate context, objective, scope, constraints, validation, and deliverables.
- Prefer concrete file paths, function names, output paths, and config flags.
- Say what is out of scope, especially for mapping/data/methodology decisions.
- Require `git status --short` up front and preservation of unrelated changes.
- For long workflow runs, require detached execution, timestamped logs, and
  polling no more frequently than `AGENTS.md` allows.
- For validation failures, require root-cause classification before fixes.
- Avoid stale line numbers where a function name or `rg` search will work.
- Avoid combined prompts that ask for both a refactor and a large production
  run unless that coupling is essential.
- Keep instructions ASCII unless the source file already requires non-ASCII.

## Current Inventory

Reviewed on 2026-07-10.

| Prompt | Type | Status | Basic Details | Notes Before Use |
|---|---|---|---|---|
| `supply_reconciliation_full_baselineseed_run_execution_prompt.md` | Long-running execution and post-run review | Valid, active | Runs the full `_PRESET_BASELINE_SEED` workflow for all 21 economies and all three scenarios, with detached logs, deferred errors, timestamp-based output checks, and consolidated findings review. | Verify current `ACTIVE_PRESET`, `ECONOMIES`, `SCENARIOS`, and `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS` before launch. This is expensive and should usually wait until implementation prompts that affect outputs are complete. |
| `supply_reconciliation_results_update_execution_prompt.md` | Targeted long-running execution | Valid, active | Runs `_PRESET_RESULTS_UPDATE` for one provided economy and requested scenario scope using LEAP balance exports as the prerequisite input. | Requires the user to name an economy/scope. Verify the balance workbook exists under `data/leap balances exports/<economy>/` before launch. |
| `patch_baseline_seeds_module_verification_prompt.md` | Verification / patch workflow | Valid, active | Guides direct use of `run_patch()` and `validate_seed_files()` for module-specific baseline seed refresh and equivalence checks. | Use for patcher verification, not full reconciliation. Some module verdicts remain suspect and should be updated as verification completes. |
| `id_verification_consolidation_execution_prompt.md` | Implementation and verification | Valid, active, high value | Consolidates duplicated LEAP ID / branch matching logic and shared preflight-state override code, with tests and real-data equivalence checks. | Line numbers are point-in-time and must be rechecked. Item 1 is highest risk; Item 2 Part A is still live because `_apply_preflight_compressed_state` and `_apply_preflight_results_update_state` remain separate. |
| `workflow_folder_migration_and_reconciliation_verification_prompt.md` | Refactor plus run verification | Invalid as written | The objective is to move workflow entrypoints into `codebase/workflows/`, while the short version describes a baseline-seed run with a specific economy order. | Do not execute without rewriting. It mixes unrelated objectives, contains stale wording/encoding artifacts, and references a `codebase/workflows/` migration that has not been started. Split into separate migration and run prompts if this work is still desired. |
| `cross_repo_dependency_documentation_prompt.md` | Investigation and documentation | Valid, active | Audits all three repositories and creates a cross-repository data-lineage, ownership, dependency, and refresh guide with Mermaid maps. | Verify sibling paths, archive locations, current workflow names, and existing centralisation documentation before use. |
| `export_zero_fill_consolidation_execution_prompt.md` | Implementation (staged refactor with equivalence verification) | Valid, active | Consolidates the four independent "zero unfilled rows from the full model export" mechanisms (own-use proxy, transformation aux/feedstock/output, demand zeroing, import-export reset) into a shared `export_zero_fill` helper, in three separately committable stages with before/after workbook equivalence checks. | Prerequisite: the own-use LEAP-sheet zero-fill fix (2026-07-15) should be committed first. Verify function names with `rg` before editing; stage 3 (transformation) is optional if the parameterization gets contorted. No production runs. |
| `transformation_multi_output_default_verification_prompt.md` | Verification (post-run, deliberately deferred) | Valid, active | Verifies the 2026-07-16 change defaulting `multi_output=True` for all esto transformation flow sectors (fixes dropped co-product outputs, e.g. AUS coke ovens Coal tar Output Share was a false zero). Only spot-verified for `20_USA` so far. | Wait for the next full baseline-seed run (bundling other fixes) to complete before running broader checks, per user instruction to keep this separate. Re-check `multi_output` default location with `rg` before use. |
| `baseline_seed_aus_things_to_check.md` | Post-run review | Valid, active | Records specific Australia baseline-seed behaviours to verify on the next full run, including feedstock shares, own-use zero-fill, and the confirmed multi-output correction. | Treat it as a focused review checklist; verify paths and source vintage before use. |

## Recommended Tackling Order

1. `id_verification_consolidation_execution_prompt.md`
   - Highest code-risk prompt. Tackle after proxy semantics are stable.
   - Start with tests around the shared ID-resolution primitive before changing
     producer output behavior.
   - Commit Item 1 separately from preflight-state cleanup if possible.

2. `patch_baseline_seeds_module_verification_prompt.md`
   - Use after ID validation changes so patcher checks use the consolidated
   behavior.
   - Work module by module and update module verdicts as each is proven.

3. `supply_reconciliation_results_update_execution_prompt.md`
   - Run when a specific economy needs a targeted results update or after a
     targeted fix that should not require the full 21-economy run.

4. `supply_reconciliation_full_baselineseed_run_execution_prompt.md`
   - Run after implementation and patcher-verification prompts are stable.
   - This is the full integration check and should produce the consolidated
     decision table for any remaining findings.

5. `workflow_folder_migration_and_reconciliation_verification_prompt.md`
   - Do not tackle in its current form.
   - If still needed, rewrite as two prompts: one for workflow-folder migration,
     one for post-migration supply reconciliation verification.

## Recently Archived

- `other_loss_own_use_proxy_hardening_prompt.md`
- `other_loss_own_use_initialisation_post_initialisation_prompt.md`
- `leap_mappings_prompt_folder_agents_review_prompt.md`

## Known Folder Issues

- Several prompt files contain mojibake encoding artifacts. Clean these when
  the prompt is next edited.
- Some prompts include line numbers from earlier code reads. Treat line numbers
  as hints only; verify function names and call sites with `rg`.
- There is a deleted prompt tracked in git status:
  `docs/prompts/supply_reconciliation_full_run_execution_prompt.md`. Confirm
  whether the newer `supply_reconciliation_full_baselineseed_run_execution_prompt.md`
  fully supersedes it before committing any prompt cleanup that touches it.
