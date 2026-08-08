# LEAP initialisation handover work queue

## Documentation-audit closure update — 2026-07-28

This update supersedes the earlier status cells for the documentation-only
items without deleting their original evidence:

- **INITQ-007 — complete:** the three archived-prompt links are correct, the two
  absent README images are no longer presented as available, the two malformed
  CSV links are relative and valid, `AGENTS_DRAWIO.md` is no longer claimed to
  exist, and the raw `Untitled-2.md` log is preserved under `docs/archive/`.
- **INITQ-008 — complete:** 15 completed, superseded, or invalid prompts moved
  to `docs/archive/`; `docs/prompts/` now contains 18 active/pending prompts and
  its `AGENTS.md` inventories every one exactly once.
- **INITQ-015 — complete:** live parallelism guidance now routes through
  `supply_reconciliation/parallel_runner.py`; the duplicated/stale refactor and sibling
  backlogs are explicitly historical and route readers to their owning queues.
- **INITQ-026 — preservation review complete:** the overview is retained as an
  architecture snapshot, current template and mapping paths are corrected, and
  the pain-points section is explicitly historical. It is no longer a current
  runbook.

The exhaustive disposition for all 102 pre-existing tracked Markdown files is
[`documentation_disposition_20260728.md`](documentation_disposition_20260728.md).

**Snapshot date:** 2026-07-28

**Last verified:** 2026-07-28 — git state, worktrees, running processes, run
configuration, template inventory, and code claims all read directly. Per-item
verification dates are in the **Last verified** column.

**Later documentation validation note / INITQ-007 completion evidence:** the
handover-set path check found three pre-existing root-README references with no
current target: `codebase/industry_mapping_workflow.py`,
`codebase/balance_table_example.py`, and `data/power export.xlsx`. The README
now preserves the industry/power history while routing runnable examples to
`codebase/examples/power_mapping_example.py` and
`codebase/examples/balance_tables_example.py`. It does not invent replacement
code or data paths.

**INITQ-027 — verify remaining literal USA-template fallbacks:** the
preservation audit corrected live documentation to the resolver's flexible
filename contract and current `* clean slate 28_07.xlsx` inventory. Two code
constants still name the absent literal path
`data/leap_export_templates/leap_export_template 20_USA.xlsx`:
`codebase/utilities/fuel_catalog_preflight.py::DEFAULT_FULL_MODEL_EXPORT_PATH`
and `codebase/functions/patch_baseline_seeds.py::FULL_MODEL_EXPORT_PATH`.
Normal per-economy routes often resolve or inject a template before reaching
them, and the work queue records intentional shared/fallback semantics, so do
not mechanically rename the constants. Trace aggregate, catalog-refresh, and
patch callers; add focused tests using the current flexible resolver; then
either route these defaults through the resolver or document a proven
non-executable compatibility role.

**Planning horizon:** four weeks, through 2026-08-24

**Owner repository:** `leap_initialisation`

**Related repositories:** `leap_mappings` (canonical mapping owner),
`leap_dashboard` (presentation)

**Cross-repository index:** `leap_mappings/docs/cross_repository_handover_index.md`

## Relationship to `docs/work_queue.md`

`docs/work_queue.md` (1,911 lines) stays the **detailed engineering log**. It
holds the reasoning, settled decisions, known pre-existing failures, and the
"traps that already cost time" section, and it must not be deleted or
summarized away — several of its entries are the only record of why a gate
stays closed.

It is not, however, a handover artifact: it has no snapshot date, mixes
completed items (`[0]`, `[2]`–`[5]`, `[8]`–`[10]`, `[17]`, `[19]`) with active
ones in non-sequential order, and uses ad-hoc status markers. This file is the
**dated handover view**: git-verified state, branch and worktree disposition,
and the four-week schedule. Where the two disagree, this file's evidence column
is the one that was checked against git on 2026-07-28.

## Concurrent session (2026-07-28)

A second working session ran across all three repositories during this audit and
created `docs/documentation_audit_20260728.md` in this repository (findings
`D-01`–`D-13`). That file is the **documentation** audit; this file is the
**git-state and schedule** view. They are complementary and should both be kept:
its `D-11` (broken links), `D-08` (unexecuted archival plan), and `D-12`
(`Untitled-2.md`) correspond to INITQ-007 and INITQ-008 here.

Where they overlap, prefer that file for documentation classification and this
file for branch, worktree, and commit state — each was verified against a
different kind of evidence.

The two sessions have since been reconciled: this file now carries the full
merged queue (INITQ-001…026), with items INITQ-014 onwards contributed by the
documentation-audit session. No item was renumbered.

> **Do not mark an item complete because a document says it is complete.** The
> audit found six documents materially misreporting their own status
> (`D-01`–`D-06`), including two that contradict code in this repository.
> Completion requires the change to be committed on the intended branch,
> verified, and either reachable from `master` or explicitly recorded as a
> clean, ready-to-integrate worktree.

## Status definitions

Shared vocabulary with `leap_mappings/docs/work_queue.md` and
`leap_dashboard/docs/work_queue.md`.

| Status | Meaning |
|---|---|
| `complete_on_master` | Implemented, verified, committed, and reachable from local `master`. |
| `complete_unpushed` | Complete on local `master`, but not yet present on `origin/master`. |
| `complete_in_worktree` | Clean, committed work exists on another branch and still needs integration or an explicit decision not to integrate. |
| `partial_uncommitted` | Material work exists only as uncommitted changes or an unfinished draft. |
| `partial` | Some committed implementation exists, but the acceptance criteria are not complete. |
| `doc_stale` | Code or data is in a good state, but tracked documentation describes a superseded state. |
| `paused` | Work is intentionally preserved but should not resume until its stated gate is met. |
| `not_started` | No implementation evidence was found. |
| `human_decision` | Progress depends on a semantic or policy choice that should not be guessed. |
| `superseded_cleanup` | The work is complete or superseded; only archival or branch/worktree cleanup remains. |

## Repository state at the snapshot

- Local `master` is at `48cbf34` and is **142 commits ahead of `origin/master`**,
  zero behind. `origin/master` is at `d846955` (2026-07-22 13:37 +0900); the
  local commits span 2026-07-22 → 2026-07-28 (23 / 60 / 15 / 3 / 5 / 28 / 8 per
  day). This is the largest local-only gap in the programme. The last fetch was
  2026-07-27 17:38.
- The main checkout is **clean** — no modified or untracked files.
- **No Python process was running** when this snapshot was taken, and there are
  no stale locks under
  `outputs/leap_exports/supply_reconciliation/supporting_files/runtime/economy_locks/`.
  Note that `AGENTS.md` warns the supply reconciliation workflow may appear as
  `python3.13.exe`, so `Get-Process python` alone is not a reliable check; the
  `Win32_Process` query used here reads full command lines.
- **Run configuration is parked safely**: `RUN_OUTPUT_LABEL = "auto"`,
  `ECONOMIES = ECONOMIES_RUN_ORDER`, `ACTIVE_PRESET = _PRESET_BASELINE_SEED`,
  `TEST_HORIZON_BASE_YEAR_PLUS_ONE = True`,
  `RUN_PREFLIGHT_COMPRESSED_PROJECTION = True`. No operator's temporary label is
  stranded in the workflow file.
- There are **8 worktrees besides the main checkout** and **11 local branches**
  (10 besides `master`). Most carry no unique work; two hold real unmerged
  commits and one holds a commit that no branch points at.
- **Test collection is clean**: 1,078 tests, zero collection errors. The suite's
  *runtime* is a separate problem — see INITQ-018.
- Sibling repositories at the same snapshot: `leap_dashboard` local `master` is
  55 commits ahead of its remote with one modified file; `leap_mappings` is 4
  ahead with a dirty checkout including five uncommitted workbook deletions and
  an Excel lock file. Combined with this repository, **201 commits exist on one
  machine only.**

## Branch and worktree reconciliation

| Branch / worktree | Evidence on 2026-07-28 | Classification | Required action |
|---|---|---|---|
| `master` (main checkout) | 142 ahead of `origin/master`; clean | `complete_unpushed` | Re-fetch and reconcile with the remote through the user's normal process. Until then, 142 commits of initialisation work exist on one machine only. |
| `codex/baseline-seed-export-diagnostics` | Clean; **6 unmerged commits**, 16 behind `master` | `complete_in_worktree` | Real work: balance-shaped AUS diagnostic workbook, corrected comparators, AUS supply input trace, Windows temp-lock tolerance, and a legacy refining retirement plan. Review and integrate — see INITQ-002. |
| `C:\Users\Work\.codex\worktrees\31a7\leap_initialisation` | Clean; **detached HEAD at `1fdd386`** ("codex: allocate gas processing parent residuals"), 1 commit unmerged, 37 behind | `complete_in_worktree` (at risk) | **No branch points at `1fdd386`.** Removing this worktree would leave the commit unreachable and eligible for garbage collection. Create a branch at it before any cleanup — see INITQ-001. |
| `C:\Users\Work\.codex\worktrees\6c2b\leap_initialisation` | Merged into `master`; only untracked `.codex_spreadsheet_work/` | `superseded_cleanup` | Confirm the untracked directory holds nothing wanted, then remove the worktree. |
| `.claude/worktrees/results-update-dry-run-preview` (`codex/results-update-dry-run-preview`) | Clean; fully merged into `master`; 18 behind | `superseded_cleanup` | Remove worktree and branch. Its strategy-table and preview-enforcement work is already on `master` via merge `09b3f73`. |
| `.claude/worktrees/upbeat-elion-408d71` (`claude/leap-phase4-continuation-f01666`) | Clean; fully merged; 116 behind | `superseded_cleanup` | Remove worktree and branch. |
| `.claude/worktrees/zealous-mcnulty-f8ddad` (`claude/leap-stock-changes-discrepancies-e526a6`) | Clean; fully merged; 29 behind | `superseded_cleanup` | Remove worktree and branch. The Stock Changes / Statistical Differences export rows are on `master`. |
| `.claude/worktrees/esto-2026-nz-rows-63f3de` and `.claude/worktrees/feedstock-fuel-share-normalize-0641c7` | Clean; both sit on branches whose only commit is `04b6ec2 "Initial commit"`; 463 behind | `superseded_cleanup` | Empty scaffolding worktrees carrying no work. **Note the name mismatch:** the worktree named `esto-2026-nz-rows-63f3de` is checked out on branch `claude/electricity-interim-use-values-0979e2`, and the worktree named `feedstock-fuel-share-normalize-0641c7` is on branch `claude/esto-2026-nz-rows-63f3de`. Do not infer contents from directory names during cleanup. |
| `claude/feedstock-fuel-share-normalize-0641c7` | No worktree; only commit is `04b6ec2 "Initial commit"` | `superseded_cleanup` | Delete the empty branch. |
| `claude/holistic-mapping-stocktake-a1d2d3`, `claude/leap-init-continuation-d194c7`, `consolidate-id-verification` | No worktree; all fully merged into `master` | `superseded_cleanup` | Delete the merged branches. No content is lost. |

## Documentation findings

Full detail and evidence in
[`documentation_audit_20260728.md`](documentation_audit_20260728.md).

1. **Seven broken links or references** (`D-11`). Three point at
   `docs/prompts/export_zero_fill_consolidation_execution_prompt.md`, which was
   moved to `docs/archive/` — two in `docs/check_registry.md`, one in
   `docs/work_queue.md`; **these three are repointed in the audit's commit**.
   Two `README.md` image links target a `docs/images/` directory that does not
   exist. Two malformed absolute links sit in the all-demand-aggregated docs.
   `AGENTS.md` references `AGENTS_DRAWIO.md`, which **does not exist anywhere in
   the repository**. Queued as INITQ-007.
2. **`Untitled-2.md` (990 lines) sits at the repository root** (`D-12`). It is
   captured workflow stdout, not documentation, tracked since 2026-07-08. It
   needs a real name and a home under `docs/`, or archival.
3. **`docs/prompts/` holds 33 prompts plus its `AGENTS.md` guide** (`D-07`).
   The inventory covers only 15 of the 33, and one of its rows points at a file
   already archived to `docs/archive/id_verification_consolidation/`. Its "Known
   Folder Issues" section also claims a deleted prompt is pending in
   `git status`; the tree is clean.
4. **A complete archival plan from 2026-07-23 was never executed** (`D-08`).
   `docs/prompts/handoff_20260723_docs_audit_and_cleanup.md` § A1 classifies all
   30 then-present prompts against real code and marks 14 DONE or SUPERSEDED,
   stating the moves are safe to make immediately. Five days on, **all 14 are
   still in `docs/prompts/`**. Queued as INITQ-008.
5. **One open design thread exists in exactly one place, and that place is
   slated for archival** (`D-09`) — the `[18]` explicit-zero-in-seed correction
   inside `continuation_20260722_phase4_parallelism_and_release_readiness.md`.
   Rescue it into the queue or the T-register **before** archiving anything.
6. **`AGENTS.md` contradicts this repository's own code** (`D-02`). Both it and
   `docs/current_execution_roadmap.md` state that per-process parallelism
   overrides do not exist and that a second economy cannot be launched safely,
   while `codebase/supply_reconciliation/parallel_runner.py` and
   `_apply_worker_snapshot_overrides()` (`supply_reconciliation_workflow.py:715`,
   called at `:1122`) implement exactly that. The roadmap contradicts itself 70
   lines later at its own item 2. Queued as INITQ-015.
7. **`docs/work_queue.md` has no snapshot date** and interleaves completed and
   active items. It stays as the engineering log; this file carries the dates.

## Prioritized queue

Every item carries priority, target handover week, status, owner repository,
dependencies, evidence, next action, completion criteria, and a last-verified
date. Unless a row says otherwise, the owner repository is `leap_initialisation`.

| ID | Priority | Week | Target | Status | Owner repo | Depends on | Work item | Evidence and completion test | Last verified |
|---|---|---|---|---|---|---|---|---|---|
| INITQ-001 | P0 | 1 | 2026-07-28 to 2026-07-29 | `complete_in_worktree` | init | — | Protect the unreferenced detached-HEAD commit | `1fdd386` ("allocate gas processing parent residuals") is reachable only from the HEAD of `C:\Users\Work\.codex\worktrees\31a7\leap_initialisation`. Create a named branch at that commit **before** any worktree cleanup runs. Complete when `git branch --contains 1fdd386` names at least one branch. | 2026-07-28 |
| INITQ-002 | P0 | 1 | 2026-07-29 to 2026-08-03 | `complete_in_worktree` | init | INITQ-001 | Integrate the baseline-seed export diagnostics branch | Review the 6 commits on `codex/baseline-seed-export-diagnostics`, rebase or merge onto current `master` (16 behind), and re-run the focused checks. Item `[21]` of `docs/work_queue.md` records Step 1 as real-data verified on 2026-07-27 in this worktree — that verification lives on the branch, not on `master`. Complete when the work is on `master` or a written decision records why not. | 2026-07-28 |
| INITQ-003 | P0 | 1 | 2026-07-29 to 2026-08-03 | `complete_unpushed` | init | — | Reconcile local `master` with `origin/master` | 142 local commits are absent from `origin/master`. Re-fetch, confirm zero divergence, then review and push through the user's normal process. Complete when the intended remote contains them or the handover records why it does not. | 2026-07-28 |
| INITQ-004 | P0 | 2 | 2026-08-03 to 2026-08-10 | `partial` | init | INITQ-002 | Close the cyclical baseline-seed diagnostics loop | Item `[21]`. A fresh LEAP cycle is required to verify the feedstock-only transformation efficiency fix and the already-landed thermal-coal producer fix. Complete when one full generate → import → recalculate → export → diagnose cycle runs and its differences are converged or classified, with the run recorded. | 2026-07-28 |
| INITQ-005 | P0 | 2 | 2026-08-03 to 2026-08-10 | `human_decision` | init | INITQ-004 | Settle the signed adjustment strategy | The allocator can increase production/capacity but cannot yet safely perform corresponding decreases, so positive and negative import gaps need separate strategies. This is a modelling decision, not a code choice. Complete when the chosen strategy for surplus handling is written into `docs/results_update_dry_run_preview.md` with a named owner. | 2026-07-28 |
| INITQ-006 | P1 | 2 | 2026-08-03 to 2026-08-10 | `paused` | init | Template refresh | Close the Stock Changes / Statistical Differences template exception | The supply exporter emits native `Stock Changes\...` and `Statistical Differences\...` rows, but current templates do not expose these roots, so unresolved IDs are retained and reported without failing the run. Gate: refreshed economy templates containing the branches. Complete when all generated rows receive canonical IDs and the temporary exception is removed. | 2026-07-28 |
| INITQ-007 | P1 | 2 | 2026-08-04 to 2026-08-10 | `doc_stale` | init | — | Fix broken links and place stray documents | Repoint the three links to `docs/archive/export_zero_fill_consolidation_execution_prompt.md`. Give `Untitled-2.md` a real name under `docs/` or archive it. Complete when a link check over all 93 tracked Markdown files returns nothing and no placeholder-named document sits at the root. | 2026-07-28 |
| INITQ-008 | P1 | 2 | 2026-08-04 to 2026-08-12 | `partial` | init | INITQ-002 | Archive completed prompt packs | Move settled prompts from `docs/prompts/` into `docs/archive/` with their findings files, and rewrite `docs/prompts/AGENTS.md` from repository evidence so it lists every active prompt exactly once. Complete when `docs/prompts/` contains only active or pending work. | 2026-07-28 |
| INITQ-009 | P1 | 2 | 2026-08-05 to 2026-08-12 | `superseded_cleanup` | init | INITQ-001 | Reduce worktree and branch sprawl | Eight worktrees and ten branches exist; six worktrees and four branches carry no unique work. Remove them only after INITQ-001 and INITQ-002, and treat directory names as unreliable given the recorded name mismatch. Complete when every remaining worktree and branch has an explicit disposition and named owner. | 2026-07-28 |
| INITQ-010 | P1 | 3 | 2026-08-10 to 2026-08-17 | `partial` | init | INITQ-004 | Write the initialisation handover set | **Documentation written 2026-07-28:** `docs/handover/supply_reconciliation_guide.md` and `supply_reconciliation_agent_guide.md` now cover the repository boundary, run modes, launch traps, templates/IDs, outputs, validation, and manual LEAP loop while linking to the canonical workflow/check/rule guides. Root and docs indexes link the set. Remaining gate: prove a scoped clean-checkout launch in INITQ-013 and correct any gap it exposes. | 2026-07-28 |
| INITQ-011 | P2 | 3 | 2026-08-10 to 2026-08-17 | `partial` | init | — | Date and prune the engineering log | Add a snapshot date to `docs/work_queue.md` and separate its settled sections from its active ones, without deleting the trap and known-failure records. Complete when a reader can tell at a glance which items are live. | 2026-07-28 |
| INITQ-012 | P1 | 2 | 2026-08-04 to 2026-08-12 | `human_decision` | init | — | Re-verify the export-template rollout against the new template census | Item `[7]`, but its premise has inverted. **Evidence (`D-04`, `D-05`):** `[7]`/`[12]` reason from "3 real, 18 `_COMP_GEN`"; measured 2026-07-28 in `data/leap_export_templates/` there are **11 real and 10 `_COMP_GEN`**, eight of the real ones dated 28/07. Separately `data/full model export.xlsx` **no longer exists** and only one live code reference to it remains (`codebase/mapping_tools/update_mapping_cardinality.py`), so `[13]` is all but closed and `[7]`'s "~15 constants still pin it" list is obsolete. **Next:** re-read `[12]`'s "regeneration is NOT the answer" conclusion under the inverted ratio; run the `[7]` empirical resolver check against the eight new templates; close `[13]`. Complete when `[7]`/`[12]`/`[13]` state the measured census with a date and each new real template has an ID-routing audit or an explicit note that it lacks one. | 2026-07-28 |
| INITQ-013 | P0 | 4 | 2026-08-18 to 2026-08-24 | `not_started` | all three | all above | Participate in the clean-checkout handover rehearsal | Follow the runbook from a fresh checkout alongside the other two repositories, validating `cross_repository_handover_index.md` § 7 jointly with `leap_mappings` MAPQ-022. Complete when a scoped supply-reconciliation run and a results-update preview both succeed without undocumented local knowledge, and every gap found is fixed. | 2026-07-28 |
| INITQ-014 | P0 | 1 | 2026-07-28 to 2026-08-03 | `completed_policy_change` | init → `leap_mappings` | mapping owner | Resolve the `12_NZ` subtotal-mismatch blocker | **Completed 2026-07-29:** the two active mismatches remain review issues, but mapping-workbook subtotal mismatches now write `subtotal_flag_mismatch_warnings_<sheet>.csv` and continue rather than skipping the economy's balance-demand input. The mapping owner may still correct or explicitly approve each relationship; unresolved review metadata no longer blocks results-update. | 2026-07-29 |
| INITQ-015 | P1 | 1 | 2026-07-28 to 2026-08-03 | `doc_stale` | init | — | Correct `AGENTS.md` | **Evidence:** `D-01` (all eight LOC-table rows wrong, including the two its own staleness banner claims to have fixed — e.g. `transfers_workflow.py` claimed 1,802, measured 1,362; `aggregated_demand_workflow.py` claimed 1,212, measured 1,917), `D-02` (parallelism section contradicted by `supply_reconciliation/parallel_runner.py` and `_apply_worker_snapshot_overrides`), `D-03` (~260 lines mirroring the `leap_mappings` M1–M7 and `leap_dashboard` DB1–DB5 backlogs, both of which now have their own dated queues). **Next:** rewrite the parallelism section **first** — it misdirects operators today by telling them a working facility does not exist — then drop the LOC table, then replace the sibling backlogs with links. Complete when no claim in `AGENTS.md` is contradicted by code and no sibling backlog is duplicated in it. | 2026-07-28 |
| INITQ-016 | P1 | 2 | 2026-08-04 to 2026-08-10 | `human_decision` | init | a current consolidated rule-findings CSV | Settle the baseline-seed blocking-findings guard | **Evidence:** `docs/work_queue.md` § "Known pre-existing failures". `workflow_config.py:91` holds `BASELINE_SEED_VALIDATION_BLOCKING_FINDINGS_ARE_WARNINGS = True`, set at the user's instruction on 2026-07-10. The two strict writer-contract tests now monkeypatch the flag to `False` locally and pass without changing production policy. The obsolete cross-economy all-or-none release test was removed by user decision on 2026-08-03. **Next:** decide whether the latest real findings justify retaining the production downgrade. Complete when the flag's value is a recorded decision with evidence. | 2026-07-28 |
| INITQ-017 | P1 | 2 | 2026-08-04 to 2026-08-10 | `partial` | init | — | Clear the two non-guard pre-existing test failures | **Evidence:** `docs/work_queue.md` § "Known pre-existing failures". (1) `tests/test_supply_assets.py::test_prepare_supply_assets_maps_names_aggregates_and_builds_lookup` monkeypatches `apply_matt_subtotal_mapping`, which now exists only under `archive/`/`scrapbook/`. (2) `tests/test_supply_transformation_export_projection_cache.py::test_transformation_exports_reuse_reference_projection_for_current_accounts` has a stale `fake_apply` fixture — `apply_transformation_target_overrides_for_scenario` gained an `allocation_ledger` keyword and the fixture raises `TypeError`. **Next:** add `allocation_ledger=None` to the fixture; decide whether (1) is updated or deleted. Complete when both pass or are deleted with a recorded reason. | 2026-07-28 |
| INITQ-018 | P1 | 2 | 2026-08-04 to 2026-08-10 | `partial` | init | — | Bound the test suite's runtime and memory | **Evidence:** collection is clean and fast (1,078 tests, 6.5 s), but a full run started during this audit was **still executing 20 minutes after launch**, with rolling concurrent Python subprocesses holding **1.8–3.2 GB each** (six live at one sample). The subprocess fan-out matches `supply_reconciliation/parallel_runner.py`'s tests launching real OS processes; the memory matches `[21]`'s recorded finding that the reference loader "still prepares the full 288 MB 9th table before selecting two years". The repo already has an opt-in integration convention (the NZ run recorded "175 passed, 5 opt-in integration tests skipped"). **Next:** time the suite per module, move process-spawning and full-source-loading tests behind the opt-in marker, record expected wall-clock for the default and full runs. Complete when the default suite finishes in a documented bounded time and the runbook states what the full run costs. | 2026-07-28 (measurement incomplete — the run did not finish within the audit) |
| INITQ-019 | P1 | 2 | 2026-08-04 to 2026-08-10 | `partial` | init | — | Finish Phase 2 (`[14]`) — the tests, not the wiring | **Evidence:** `D-06`. `[14]` says only `supply_workflow.py` has landed, but **all seven** wrappers already import `workflow_config`, and `transformation_workflow.py` (13 `NOTEBOOK_*` hits), `electricity_heat_interim_workflow.py` (6) and `transfers_workflow.py` (7) carry notebook blocks — which predate Phase 2 (`0d953d1`, 2026-06-25). What is genuinely missing is `[14]`'s own completion criterion: only `tests/test_supply_workflow_config.py` exists. **Next:** add the forwarding/default tests for steps 2–4 and reconcile the pre-existing blocks with the central config; restate `[14]`. Complete when each wrapper's notebook defaults have one visible source of truth, caller arguments still win, and a focused test proves both. | 2026-07-28 |
| INITQ-020 | P1 | 2 | 2026-08-04 to 2026-08-10 | `partial` | init | — | Close the Phase 3 T4 remainder | **Evidence:** `[16]` § T4 — commit 4 landed 2026-07-23 (`9c5f16b`); `filter_leap_rollup_names()` is in `codebase/mappings/canonical_loaders.py` with 26 tests, and T10 is closed, contrary to `continuation_20260723_next_session.md`'s "blocked" framing. Remaining: D3.4 (rollup-rule reading ownership) and D3.5 (equivalence tolerance) — confirmation, not new work. Complete when both are recorded in `docs/special_rules_and_design_decisions.md` and T4 is closed in the register. | 2026-07-28 |
| INITQ-021 | P1 | 3 | 2026-08-11 to 2026-08-17 | `human_decision` | init | user scoping | Scope the single-file combined-workbook merge for parallel runs | **Evidence:** `docs/current_execution_roadmap.md` item 2 — `supply_reconciliation/parallel_merge.py` merges the consolidated findings/issue-groups CSVs across workers, but merging the single-file combined workbook is **deliberately not covered**: reconstructing its preamble/header/column layout from N independent workers is higher risk and a malformed structure is a silent defect. `continuation_20260723_next_session.md` says explicitly not to start it without discussing scope first. **Next:** agree scope and a build-and-diff verification plan before writing code. Complete when the merge exists with byte-level diff evidence against a sequential multi-economy run, or the parallel path is documented as "per-economy workbooks only". Blocks any unattended multi-economy fleet run that also wants one combined file. | 2026-07-28 |
| INITQ-022 | P2 | 3 | 2026-08-11 to 2026-08-17 | `not_started` | init | — | Extend `supply_reconciliation/parallel_merge.py` to the other diagnostic families | **Evidence:** `repo_cleanup_and_consolidation_plan_20260723.md` § 3 priority 1 — a 7-economy parallel run produces seven unmerged copies of `source_diagnostics`, `template_matching_summary`, and both F5 conservation triplets, with no cross-economy view, although every one already carries an `economy` column. **Next:** extend the merge function only; priorities 2–4 in that plan need design decisions and are out of scope here. Complete when a multi-economy parallel run produces one merged view per family with per-economy files retained. | 2026-07-28 |
| INITQ-023 | P2 | 3 | 2026-08-11 to 2026-08-17 | `human_decision` | init | user | Execute the `outputs/` cleanup plan | **Evidence:** `repo_cleanup_and_consolidation_plan_20260723.md` § 1 — 54 GB across 38+ run directories: ~4.6 GB safe to delete, ~10 GB archive candidates, ~25 GB protected reference baselines (including ~9.9 GB of deliberately retained `SEED_21ECON_*` bug evidence), ~14.4 GB needing a human call. `BASELINE_SEED_7ECON_REAL_20260723` is the failed run; `…PARALLEL3_20260723` is the successful one. **Next:** delete the safe bucket, then decide the uncertain bucket. Keep an archive log; never hard-delete a broad results path. Complete when every retained directory has a stated reason. | 2026-07-28 (plan re-read; sizes not re-measured) |
| INITQ-024 | P2 | 3 | 2026-08-11 to 2026-08-17 | `partial` | init | — | Remove the verified dead code | **Evidence:** `repo_cleanup_and_consolidation_plan_20260723.md` § 2. Items 1–2 are resolved — four modules deleted (`81119c0`) and **two false positives restored** after a full pytest run surfaced 59 collection errors. Items 3–4 remain: ~19 dead functions in `leap_results_dashboard_balance.py`, an unused transport export-logging flow in `leap_core.py`, two unused functions in `energy_use_reconciliation.py`. **Next:** remove items 3–4, running the **full suite** before committing — that is the recorded lesson from both false positives, and a grep sweep is not sufficient evidence. Complete when items 3–4 are removed with a green suite and items 5–6 are decided. | 2026-07-28 |
| INITQ-025 | P2 | 3 | 2026-08-11 to 2026-08-17 | `not_started` | init | modelling owner | Build the general `FILL_IN_MISSING_9TH_SECTORS` capability | **Evidence:** `[20]`. The narrow `09.06` gas-processing implementation landed 2026-07-27, carrying base-year ESTO values forward unchanged; `[20]` states plainly that this is a foundation, **not** a universal imputation rule. **Next:** build the candidate inventory diagnostic first; do not extend the carry-forward rule to another sector without a documented owner and tests. Complete when ownership routing is defined for supply, transformation, transfers, demand and losses/own-use, every fill is opt-in and recorded, and per-family conservation and continuity tests exist. | 2026-07-28 |
| INITQ-026 | P2 | 3 | 2026-08-11 to 2026-08-17 | `paused` | init | INITQ-015 | Re-verify `system_overview_for_rewrite.md` | **Evidence:** `D-13`. 1,042 lines, unverified since 2026-07-17; predates the Phase 4 split evidence, the parallelism work, and the template rollout, yet `README.md` points new readers straight at it. **Next:** audit § 5 (Current Code Areas), § 9 (Output Structure) and § 11 (Current Pain Points) against current code, after `AGENTS.md` is corrected. Complete when every § 11 pain point is still true, marked resolved with a commit, or removed. | not verified — flagged only |

## Four-week handover sequence

Dates match `leap_mappings/docs/work_queue.md` so the two programmes stay in step.

### Week 1: 2026-07-28 to 2026-08-03

Stabilise git state and stop the bleeding.

- Protect the detached-HEAD commit before any cleanup (INITQ-001) — minutes of
  work, and the only item where delay can destroy work outright.
- Integrate the baseline-seed export diagnostics branch (INITQ-002).
- Re-fetch and reconcile the 142-commit remote gap (INITQ-003).
- Put the two `12_NZ` mapping rows in front of the modeller (INITQ-014).
- Correct `AGENTS.md`'s parallelism section (INITQ-015) — it actively misleads
  operators about a facility that exists and works.
- Begin prompt archival, orphan thread rescued first (INITQ-008).

### Week 2: 2026-08-04 to 2026-08-10

Run the cycle, settle the long-open decisions, make the suite trustworthy.

- Run the baseline-seed diagnostics cycle and settle the adjustment strategy
  (INITQ-004, INITQ-005).
- The two judgement calls open longest (INITQ-016, INITQ-012).
- Tests and phase closure (INITQ-017, INITQ-018, INITQ-019, INITQ-020).
- Fix broken links and stray documents (INITQ-007).

### Week 3: 2026-08-11 to 2026-08-17

Write the handover material and clear the low-risk backlog.

- Write the handover set (INITQ-010) and reconcile the cross-repository contract
  with `leap_mappings` MAPQ-015.
- Complete worktree and branch cleanup (INITQ-009).
- Date and prune the engineering log (INITQ-011).
- Scope the combined-workbook merge with the user (INITQ-021).
- Cleanup and consolidation (INITQ-022, INITQ-023, INITQ-024).
- Close or explicitly defer INITQ-006, INITQ-025, INITQ-026.
- Confirm which sibling-repository work is local-only versus remotely
  recoverable.

### Week 4: 2026-08-18 to 2026-08-24

Rehearse and freeze.

- Participate in the clean-checkout rehearsal (INITQ-013), jointly with
  `leap_mappings` MAPQ-022, validating
  `cross_repository_handover_index.md` § 7.
- Fix the documentation gaps the rehearsal exposes.
- Freeze a final dated queue and known-risks list.
- Ensure every unmerged branch, worktree and unpushed commit has an explicit
  disposition and a named owner.

## Queue maintenance rules

1. Re-date the snapshot header and the row's **Last verified** value whenever a
   status changes.
2. Cite the commit, worktree, run ID, or human decision supporting each status.
3. Never remove a worktree before confirming its HEAD is reachable from a branch.
4. Never roll an old document's counts forward to a new baseline. Re-measure —
   `D-01` and `D-05` are both cases where that was not done, and both produced
   confidently-stated numbers that were wrong.
5. Keep `docs/work_queue.md` as the reasoning log; keep this file as the dated
   state view. Do not duplicate content between them.
6. Move a completed prompt to `docs/archive/` in the same commit that updates
   `docs/prompts/AGENTS.md`.
7. At the end of each week, record what moved to `complete_on_master`, what is
   blocked, and what must be descoped before handover.
