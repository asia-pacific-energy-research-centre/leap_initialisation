# Handoff — docs/ audit, repo cleanup, and post-run follow-ups (2026-07-23)

Type: handoff / continuation prompt. Written 2026-07-23 while a real
production run (`BASELINE_SEED_7ECON_REAL_20260723`, 7 economies, full
horizon, sequential) is in flight. Two work sections below: **A** is safe to
start immediately, while that run is still going; **B** is longer-term,
mostly safe anytime but a few items explicitly wait for the run to finish.

## Standing rules (apply to everything below)

1. **A real production run may be in flight. Check first.** Run
   `Get-Process python*` (or `tasklist`) and check whether
   `outputs/leap_exports/supply_reconciliation/baseline_seed/runs/BASELINE_SEED_7ECON_REAL_20260723/supporting_files/runtime/supply_reconciliation_workflow.log`
   is still growing. If it's still running: **docs and new test files only,
   no edits to any `codebase/*.py` file** — a mid-run commit/edit to a file
   the process hasn't imported yet can hand it a mixed set of module
   versions and corrupt the run silently (this has happened before in this
   repo; see `docs/work_queue.md`'s "Traps that already cost time" section).
   Once the log stops growing and the process has exited, re-check
   `git status --short` before resuming code work.
2. One issue per commit, `codex:` message convention (see `git log --oneline
   -20` for examples).
3. **Do not trust a doc's own self-reported status.** This session found and
   fixed two cases today where a document said "blocked" or "done" and was
   simply wrong — cross-check every claim against real code/tests before
   acting on it, exactly the same discipline as the rest of this repo.
4. **Never silently re-add something this repo has removed.** This is the
   sharpest risk in section A below: several old docs describe workarounds,
   fallback logic, or config shapes that were *deliberately* retired since
   they were written (e.g. `data/full model export.xlsx`'s retirement,
   the `unified_name_lookup` consolidation API's removal, the legacy
   `config/master_config.xlsx`/`config/leap_mappings.xlsx` move to
   `config/legacy/`). An old doc recommending "add X back" or "restore Y" is
   not evidence X/Y should exist — check whether it was removed on purpose
   first (grep commit messages, check `docs/work_queue.md` for a `DONE`/
   `SETTLED` marker on that removal).
5. This repo moves fast (its own words, `docs/leap_initialisation
   zip_extraction_plan.md`) — a doc more than a few days old should be
   treated as a *lead to verify*, not a source of truth. The most current,
   authoritative live-state documents are (in order of authority):
   `docs/prompts/initialisation_refactor_continuation.md` (today, the
   open-thread register), `docs/work_queue.md` (today, the master backlog),
   `docs/current_execution_roadmap.md` (today, run policy).

---

## Section A — do this while the run is still going (docs/tests only)

### A1. Audit every `docs/*.md` file against the work queue

The task: read every `.md` file under `docs/` (both the top level and
`docs/prompts/`, excluding `docs/archive/` which is already a settled
historical record — see A2 for why some of *that* needs a second look too),
cross-check each one's claims against `docs/work_queue.md` and
`docs/prompts/initialisation_refactor_continuation.md`, and for each file
decide: **is its content still live, and if so, is it already tracked in the
work queue?** If a doc raises something genuinely open and not yet in
`work_queue.md`, add it there (with a citation back to the source doc). If a
doc is stale/superseded, say so explicitly rather than silently ignoring it
(a future reader needs to know it was checked, not just that no action was
taken).

**Full file-modification-date listing** (today is 2026-07-23; use this to
gauge likely relevance before opening a file — but always verify, a recent
mtime doesn't guarantee correctness and an old one doesn't guarantee
staleness):

```
2026-04-23  docs/archive/full_model_workflow_notebook_post_run_guide.md
2026-05-26  docs/archive/workflow_pipeline.md
2026-06-10  docs/archive/leap_utils_leap_workflow.md
2026-06-12  docs/archive/what_this_repo_is_for - leap_utilities.md
2026-06-16  docs/archive/README.md
2026-06-16  docs/archive/other_transformation_supply_modeller_guide.md
2026-06-24  docs/archive/supply_side_modelling_overview.md
2026-07-02  docs/archive/managed_leap_initialisation_run_prompt.md
2026-07-03  docs/archive/balance_demand_conservation_check_prompt.md
2026-07-03  docs/archive/compressed_results_update_preflight_prompt.md
2026-07-03  docs/archive/managed_leap_initialisation_resume_20_usa_prompt.md
2026-07-03  docs/archive/update_resume_prompt_after_balance_demand_fixes.md
2026-07-03  docs/supply_conservation_checks.md
2026-07-04  docs/archive/demand_conservation_lineage_feasibility_prompt.md
2026-07-04  docs/archive/extend_conservation_verification_to_supply_and_transformation.md
2026-07-04  docs/archive/leap_mappings_stage3_anchor_validation_hotspots.md
2026-07-04  docs/archive/stop_balance_demand_parent_subtotal_double_count.md
2026-07-07  docs/archive/balance_demand_mapping_fixes_prompt.md
2026-07-07  docs/archive/demand_conservation_lineage_leap_mappings_planning_prompt.md
2026-07-07  docs/archive/demand_conservation_realignment_prompt.md
2026-07-07  docs/balance_demand_conservation_check.md
2026-07-08  docs/archive/OLD chat - fixing transfomaiton sectors.md
2026-07-08  docs/prompts/workflow_folder_migration_and_reconciliation_verification_prompt.md
2026-07-08  docs/workflow_inventory.md
2026-07-09  docs/archive/capacity_unmet_convergence_diagnostics_prompt.md
2026-07-09  docs/canonical_migration_diagnostics/README.md
2026-07-09  docs/prompts/supply_reconciliation_results_update_execution_prompt.md
2026-07-12  docs/archive/id_verification_consolidation/STATUS.md
2026-07-12  docs/archive/id_verification_consolidation/id_verification_consolidation_execution_prompt.md
2026-07-12  docs/archive/leap_mappings_prompt_folder_agents_review_prompt.md
2026-07-12  docs/archive/other_loss_own_use_initialisation_post_initialisation_prompt.md
2026-07-12  docs/archive/other_loss_own_use_proxy_hardening_prompt.md
2026-07-12  docs/prompts/supply_reconciliation_full_baselineseed_run_execution_prompt.md
2026-07-13  docs/archive/split_supply_reconciliation_output_by_pass_mode.md
2026-07-13  docs/leap_balance_export_centralisation_audit.md
2026-07-13  docs/prompts/centralise_leap_balance_exports_across_repos.md
2026-07-13  docs/prompts/cross_repo_dependency_documentation_prompt.md
2026-07-15  docs/archive/usa_target_results_update_failure_investigation_findings.md
2026-07-15  docs/archive/usa_target_results_update_failure_investigation_prompt.md
2026-07-16  docs/archive/export_zero_fill_consolidation_execution_prompt.md
2026-07-16  docs/baseline_seed_rule_inventory.md
2026-07-16  docs/prompts/baseline_seed_aus_things_to_check.md
2026-07-16  docs/prompts/transformation_multi_output_default_verification_prompt.md
2026-07-17  docs/archive/12_nz_baseline_seed_hardening_readiness_20260717.md
2026-07-17  docs/leap_export_readiness_plan.md
2026-07-17  docs/nz_baseline_seed_readiness_audit_20260717.md
2026-07-17  docs/prompts/final_owned_seed_completion_execution_prompt.md
2026-07-17  docs/prompts/nz_baseline_seed_hardening_readiness_prompt.md
2026-07-17  docs/prompts/patch_baseline_seeds_module_verification_prompt.md
2026-07-17  docs/prompts/review_nz_unmapped_leap_branch_fuel_combinations.md
2026-07-17  docs/prompts/transformation_final_handoff_and_verification_prompt.md
2026-07-17  docs/prompts/transformation_patch_ungate_final_verification_prompt.md
2026-07-17  docs/special_rules_and_design_decisions.md
2026-07-17  docs/system_overview_for_rewrite.md
2026-07-21  docs/check_registry.md
2026-07-21  docs/full_model_export_retirement_scope.md
2026-07-21  docs/prompts/AGENTS.md
2026-07-21  docs/prompts/aggregated_demand_scoped_review.md
2026-07-21  docs/prompts/initialisation_refactor_thread_execution_prompt.md
2026-07-21  docs/prompts/phase_2_configuration_standardisation_execution.md
2026-07-21  docs/prompts/phase_3_canonical_mapping_migration_execution.md
2026-07-21  docs/prompts/phase_4_monolith_decomposition_execution.md
2026-07-21  docs/prompts/phase_5_feature_improvements_execution.md
2026-07-21  docs/prompts/preset_forwarding_fix_execution_prompt.md
2026-07-22  docs/aggregate_preflight_source_routing_contract.md
2026-07-22  docs/leap_initialisation zip_extraction_plan.md   <- see A2, this IS the "large repo-cleanup doc"
2026-07-22  docs/prompts/advance_repo_20260722_execution_prompt.md
2026-07-22  docs/prompts/session_handoff_20260722.md
2026-07-22  docs/prompts/supply_reconciliation_runtime_profiling_execution.md
2026-07-23  docs/canonical_mapping_migration_notes.md
2026-07-23  docs/current_execution_roadmap.md
2026-07-23  docs/prompts/continuation_20260722_phase4_parallelism_and_release_readiness.md
2026-07-23  docs/prompts/continuation_20260723_next_session.md
2026-07-23  docs/prompts/initialisation_refactor_continuation.md
2026-07-23  docs/prompts/other_loss_own_use_proxy_scoped_review.md
2026-07-23  docs/prompts/refining_workflow_scoped_review.md
2026-07-23  docs/prompts/supply_reconciliation_presets_scoped_review.md
2026-07-23  docs/supply_reconciliation_workflow_guide.md
2026-07-23  docs/work_queue.md
```

**Already-done groundwork — don't redo this, build on it.** A subagent ran a
full `docs/prompts/` (not top-level `docs/`) audit earlier today, cross-checked
against real code/test state, not just self-reported status. Its findings:

| File | Classification | Recommended action |
|---|---|---|
| `advance_repo_20260722_execution_prompt.md` | DONE | Archive with note pointing to [18] and roadmap |
| `aggregated_demand_scoped_review.md` | PARTIALLY DONE | Leave; only cache-measurement item remains |
| `baseline_seed_aus_things_to_check.md` | PARTIALLY DONE | Leave; only item 2 (Bitumen display-name mapping) is open |
| `centralise_leap_balance_exports_across_repos.md` | DONE | Archive as-is |
| `continuation_20260722_phase4_parallelism_and_release_readiness.md` | PARTIALLY DONE — **needs a human decision** | Its "[18] explicit-zero-in-seed design correction" section is a real open thread that exists nowhere else. Fold into the T-register or explicitly decide to drop it before archiving. |
| `continuation_20260723_next_session.md` | SUPERSEDED | Archive, superseded by `initialisation_refactor_continuation.md` |
| `cross_repo_dependency_documentation_prompt.md` | STILL ACTIVE | Leave; never executed |
| `final_owned_seed_completion_execution_prompt.md` | STILL ACTIVE | Leave; F1 still "proposed" per `check_registry.md` |
| `initialisation_refactor_continuation.md` | STILL ACTIVE (source of truth) | Leave — this is what everything else is checked against |
| `initialisation_refactor_thread_execution_prompt.md` | STILL ACTIVE | Leave; generic companion to the register |
| `nz_baseline_seed_hardening_readiness_prompt.md` | DONE/SUPERSEDED | Archive with note crediting [7]/[9]/[10] |
| `other_loss_own_use_proxy_scoped_review.md` | DONE | Archive with note — coverage gap closed, extraction/rewrite explicitly decided against |
| `patch_baseline_seeds_module_verification_prompt.md` | DONE | Archive with note re: transformation section superseded by the ungate-verification prompt |
| `phase_2_configuration_standardisation_execution.md` | STILL ACTIVE | Leave; Commit 1/2 genuinely never started |
| `phase_3_canonical_mapping_migration_execution.md` | PARTIALLY DONE | Leave; only commit 6 / O5 evidence remain — **see A3/B1 below, this run may supply that evidence** |
| `phase_4_monolith_decomposition_execution.md` | PARTIALLY DONE | Leave; D4.3 + combined-workbook merge remain |
| `phase_5_feature_improvements_execution.md` | PARTIALLY DONE | Leave; cache-measurement + D5C.2 RSS measurement remain |
| `preset_forwarding_fix_execution_prompt.md` | DONE | Archive with note pointing at T1 in the register |
| `refining_workflow_scoped_review.md` | STILL ACTIVE | Leave; no `REFINING_NOTEBOOK_*` block built yet |
| `review_nz_unmapped_leap_branch_fuel_combinations.md` | DONE | Archive with note pointing at `outputs/mapping_gap_review/12_NZ/` |
| `session_handoff_20260722.md` | SUPERSEDED | Archive, superseded by the continuation register |
| `supply_reconciliation_full_baselineseed_run_execution_prompt.md` | STILL ACTIVE (reusable runbook) | Leave — not a one-off task |
| `supply_reconciliation_presets_scoped_review.md` | PARTIALLY DONE | Leave; recommended fix for finding 3 note: **this was actually implemented since the audit ran** (`5d20099`) — re-check before trusting "not implemented here" in that file |
| `supply_reconciliation_results_update_execution_prompt.md` | STILL ACTIVE (reusable runbook) | Leave |
| `supply_reconciliation_runtime_profiling_execution.md` | DONE | Archive with note — measurement landed, optimisation work now lives in the roadmap |
| `transformation_final_handoff_and_verification_prompt.md` | DONE | Archive with note re: a new, currently untracked follow-up task (rewire the patcher onto `save_transformation_exports_with_split_targets` if the gate is ever revisited) |
| `transformation_multi_output_default_verification_prompt.md` | PARTIALLY DONE | Leave; broad cross-economy re-verification still outstanding — **the run in flight right now may satisfy this, check after it finishes** |
| `transformation_patch_ungate_final_verification_prompt.md` | DONE | Archive together with the final-handoff prompt |
| `workflow_folder_migration_and_reconciliation_verification_prompt.md` | SUPERSEDED | Archive with note pointing at the actual approach taken (`phase_4_monolith_decomposition_execution.md`) |
| `AGENTS.md` (the guide, not a work item) | Stale | Its own inventory table still lists a file that's already gone/archived; needs a refresh pass, separate from archiving |

None of the moves above are done yet — this table is the *audit*, not the
archival itself. Actually archiving (`git mv docs/prompts/X.md
docs/archive/X.md`) is safe to do **now**, mid-run, since it's a docs-only
change — but do it as its own commit per file or small logical batch, and
write a one-line pointer at the top of the archived file crediting where its
findings now live (matches this repo's existing archive convention, see
`docs/archive/README.md`).

The 5 top-level `docs/*.md` files modified 2026-07-22 (`aggregate_preflight_source_routing_contract.md`,
`leap_initialisation zip_extraction_plan.md`, plus the three `docs/prompts/`
ones already in the table above) and everything older were **not** covered
by that subagent pass — that's the main gap in A1 still to do. Read each,
classify the same way, and fold genuinely-open items into `work_queue.md`.

### A2. `docs/leap_initialisation zip_extraction_plan.md` — the "large repo-cleanup doc"

This is almost certainly the doc the user recalled as "a large repo-cleanup
handoff doc created yesterday." It's an inter-PC sync/extraction plan
(`config.zip`/`data.zip`) with an explicit **"Instructions for whoever
reviews this on the other PC" clutter-audit section** near the top asking
for a two-pass audit (single-use/one-off files, then broader structural
clutter) to be appended as a new section at the bottom of that same file.

**Check whether that clutter audit was ever actually appended.** If not, it
is still open and duplicates real intent behind today's separate
repo-cleanliness sweep (see A2b below) — reconcile the two into one place
rather than doing the work twice. If it was appended, cross-check its
findings against A2b's before acting on either.

### A2b. Today's general repo-cleanliness sweep — already done, act on it

A separate subagent did a whole-repo (not `docs/`) cleanliness sweep today,
read-only, evidence-based. Its findings, most-confident first:

- **`Untitled-2.md`** (repo root, 45KB, tracked in git) — originated from
  commits with self-describing scratch/checkpoint messages (`"aa"`, `"codex:
  checkpoint uncommitted work"`). Content is a captured stdout log, not
  documentation. Not referenced anywhere. Recommend untracking/removing.
- **`_run_apec_preflight_after_aggregate.py`** (repo root, tracked) — a
  one-off dated Jupyter-cell script (`RUN_APEC_PREFLIGHT = False`, tied to
  `APEC_PREFLIGHT_AGGREGATE_RETRY_20260715`), not imported anywhere.
  Recommend moving to `codebase/scrapbook/` or deleting.
- **`APEC_PREFLIGHT_AGGREGATE_RETRY_LAUNCH_20260715_210958/` and
  `..._211052/`** (repo root dirs, confirmed NOT git-tracked) — pure stdout/
  stderr log clutter from a 2026-07-15 background launch. Safe to delete.
- **`codebase/analysis/`** — empty package (`__init__.py` + `__pycache__`
  only), nothing imports `codebase.analysis` anywhere. Confidently dead
  scaffold; either populate or remove.
- **`config data interm.zip`** (repo root, 7.3GB, confirmed gitignored) — no
  git-bloat risk, just flag it as local-disk housekeeping.
- **`codebase/mapping_code/`** — self-described prototype, already excluded
  from canonical-source tests alongside `archive`/`scrapbook`/
  `old_workflows`, but misnamed/mislocated relative to those conventions.
  Not dead, just inconsistent; consider renaming under `scrapbook/` or
  leave as-is if it's a working handoff artifact for `leap_dashboard`.
- **`codebase/archive/industry_workflow.py`** — correctly archived and
  excluded already; has one stale developer TODO comment worth dropping if
  this file is ever touched again.
- `outputs/` root has ~40 stray `.log`/`.err`/`.pid` files plus 207 files
  under `outputs/logs/` from past runs — all gitignored, just local-disk
  bloat if the user wants to prune manually. Not a repo-cleanliness action
  item in the git sense.
- `.gitignore` health, `codebase/scrapbook/`/`codebase/old_workflows/`/
  `*/archive/` dirs, and the two work_queue.md items ([13] full model
  export retirement, [11] fuel-catalog union design) were all checked and
  are fine / already-documented decisions, not drift. No action needed.

**None of the above have been acted on yet.** They're all cheap, low-risk,
docs/repo-hygiene-only changes (deleting/moving untracked scratch files and
one dead package) — safe to do now, mid-run, as their own small commits.
Confirm with the user before deleting anything actually tracked in git
(`Untitled-2.md`, `_run_apec_preflight_after_aggregate.py`) per this
project's standing rule on destructive actions; the untracked directories
can just be deleted directly since git has no record of them either way.

### A3. Prep (not execute) the O5 equivalence evidence for T4 commit 4

`docs/prompts/phase_3_canonical_mapping_migration_execution.md`'s O5 gate
needs a real single-economy A/B (key sets exact, totals within 1e-6
relative) comparing before/after commit `9c5f16b` (the rollup-label
exclusion). **The run in flight right now (`BASELINE_SEED_7ECON_REAL_20260723`)
is a real, multi-economy, full-horizon run that already includes commit
`9c5f16b`** — it may be usable as the "after" side of that comparison if a
comparable "before" baseline exists for any of its 7 economies. Check
`docs/current_execution_roadmap.md` and prior `SEED_*` run labels for a
pre-`9c5f16b` full-horizon baseline for `01_AUS`, `12_NZ`, or `20_USA`
specifically (those three are the most likely to have one). Do not run
anything new for this yet — just confirm whether a usable "before" baseline
already exists, so the comparison can be run the moment this real run
finishes. **This still needs the user's go-ahead before treating any
resulting diff as a verdict** - prepare, don't conclude.

---

## Section B — longer-term, after the run finishes (or safe anytime, noted per item)

### B1. Process the real run's results

Once `BASELINE_SEED_7ECON_REAL_20260723` finishes:
- Check per-economy success/failure and timing against today's estimates
  (~2-3 hours total, `05_PRC` likely slowest).
- Distinguish expected new warnings (no `CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS`
  entry for every economy except `20_USA`; possibly no fallback tier for
  `nonspecified_own_uses`/`transmission_and_distribution_losses`) from
  anything genuinely new.
- If the O5 "before" baseline from A3 exists, run the comparison (with the
  user's go-ahead) and write up the evidence per commit 6 of
  `phase_3_canonical_mapping_migration_execution.md`.
- Confirm the "Contributions" sheet appears correctly in the real
  aggregated-demand workbooks now that it's live for a real multi-economy
  run (`AGGREGATED_DEMAND_WRITE_CONTRIBUTIONS = True`).
- `transformation_multi_output_default_verification_prompt.md`'s
  outstanding "broad cross-economy re-verification" may now be satisfiable
  by this run's evidence — check.

### B2. Execute the docs archival from A1's table

Once the human has weighed in on
`continuation_20260722_phase4_parallelism_and_release_readiness.md`'s [18]
design-correction thread (the one item needing a decision, not just
archiving), execute the moves the table above already recommends.

### B3. Remaining smaller open items from today's session (not urgent, not started)

- Own-use proxy activity-source fallback-tier asymmetry (`nonspecified_own_uses`/
  `transmission_and_distribution_losses` have no fallback tier in either
  mode) — a modelling decision, not a mechanical fix; a warning was added
  today, the underlying gap is still open.
- Capacity-unmet caps (`CAPACITY_UNMET_MODULE_CAPACITY_UPPER_LIMITS`/
  `..._PRODUCTION_UPPER_LIMITS`) are configured only for `20_USA`; every
  other economy runs fully unconstrained. A warning was added today; the
  underlying authoring gap is a future task, not urgent per the user.
- `post_initialisation_anchored_intensity` own-use proxy mode is fully
  built/tested but has zero production callers — needs a decision (wire it
  in, or remove it as dead code).
- Single-file combined-workbook merge for parallel economy outputs is still
  not built (explicitly flagged as its own higher-risk task each time it
  comes up).
- D4.3 (split `supply_results_saver.py`) remains deferred per its own
  recommendation; no new information changes that.
- D5C.2 (safe worker-count default for concurrent economy runs) has real
  measured data as of today (see `outputs/concurrency_scale_tests/`) but no
  formal default decision recorded yet.

---

## What NOT to do

- Do not touch `codebase/supply_reconciliation_workflow.py` while the real
  run holds it. Confirmed safe to edit only after the process exits.
- Do not archive `docs/prompts/initialisation_refactor_continuation.md`,
  `docs/work_queue.md`, or `docs/current_execution_roadmap.md` — these are
  the living registers everything else is checked against.
- Do not treat any doc's own "DONE"/"COMPLETE" self-labeling as sufficient
  evidence — this handoff doc itself should be re-verified against reality
  before being trusted, the same as everything it describes.
- Do not delete anything tracked in git without the user's confirmation
  (per this project's standing destructive-action rule) - untracked
  scratch files/directories are the exception, since git has no record of
  them regardless.
