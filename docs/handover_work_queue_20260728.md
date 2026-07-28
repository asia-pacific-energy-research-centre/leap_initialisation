# LEAP initialisation handover work queue

**Snapshot date:** 2026-07-28

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
  zero behind. This is the largest local-only gap in the programme. The last
  fetch was 2026-07-27.
- The main checkout is **clean** — no modified or untracked files.
- **No Python process was running** when this snapshot was taken. Note that
  `AGENTS.md` warns the supply reconciliation workflow may appear as
  `python3.13.exe`, so `Get-Process python` alone is not a reliable check; the
  `Win32_Process` query used here reads full command lines.
- There are **8 worktrees besides the main checkout** and **10 local branches**.
  Most carry no unique work; two hold real unmerged commits and one holds a
  commit that no branch points at.

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

1. **Three broken relative links**, all pointing at
   `docs/prompts/export_zero_fill_consolidation_execution_prompt.md`, which was
   moved to `docs/archive/`. Two are in `docs/check_registry.md` and one is in
   `docs/work_queue.md`. Queued as INITQ-007.
2. **`Untitled-2.md` (990 lines) sits at the repository root** with a
   placeholder name and no stated purpose, last touched 2026-07-08. It needs a
   real name and a home under `docs/`, or archival.
3. **`docs/prompts/` holds 30 prompts**, many describing work the queue records
   as settled (phase 2/3/4/5 execution prompts, preset forwarding, transformation
   ungate verification, NZ baseline seed hardening, id-verification
   consolidation). `docs/prompts/AGENTS.md` was last touched 2026-07-27 and
   should be the inventory of record. Archive completed packs together with
   their findings files, following the `docs/archive/id_verification_consolidation/`
   pattern already present here.
4. **`docs/work_queue.md` has no snapshot date** and interleaves completed and
   active items. It stays as the engineering log; this file carries the dates.

## Prioritized queue

| ID | Priority | Target | Status | Depends on | Work item | Evidence and completion test |
|---|---|---|---|---|---|---|
| INITQ-001 | P0 | 2026-07-28 to 2026-07-29 | `complete_in_worktree` | — | Protect the unreferenced detached-HEAD commit | `1fdd386` ("allocate gas processing parent residuals") is reachable only from the HEAD of `C:\Users\Work\.codex\worktrees\31a7\leap_initialisation`. Create a named branch at that commit **before** any worktree cleanup runs. Complete when `git branch --contains 1fdd386` names at least one branch. |
| INITQ-002 | P0 | 2026-07-29 to 2026-08-03 | `complete_in_worktree` | INITQ-001 | Integrate the baseline-seed export diagnostics branch | Review the 6 commits on `codex/baseline-seed-export-diagnostics`, rebase or merge onto current `master` (16 behind), and re-run the focused checks. Item `[21]` of `docs/work_queue.md` records Step 1 as real-data verified on 2026-07-27 in this worktree — that verification lives on the branch, not on `master`. Complete when the work is on `master` or a written decision records why not. |
| INITQ-003 | P0 | 2026-07-29 to 2026-08-03 | `complete_unpushed` | — | Reconcile local `master` with `origin/master` | 142 local commits are absent from `origin/master`. Re-fetch, confirm zero divergence, then review and push through the user's normal process. Complete when the intended remote contains them or the handover records why it does not. |
| INITQ-004 | P0 | 2026-08-03 to 2026-08-10 | `partial` | INITQ-002 | Close the cyclical baseline-seed diagnostics loop | Item `[21]`. A fresh LEAP cycle is required to verify the feedstock-only transformation efficiency fix and the already-landed thermal-coal producer fix. Complete when one full generate → import → recalculate → export → diagnose cycle runs and its differences are converged or classified, with the run recorded. |
| INITQ-005 | P0 | 2026-08-03 to 2026-08-10 | `human_decision` | INITQ-004 | Settle the signed adjustment strategy | The allocator can increase production/capacity but cannot yet safely perform corresponding decreases, so positive and negative import gaps need separate strategies. This is a modelling decision, not a code choice. Complete when the chosen strategy for surplus handling is written into `docs/results_update_dry_run_preview.md` with a named owner. |
| INITQ-006 | P1 | 2026-08-03 to 2026-08-10 | `paused` | Template refresh | Close the Stock Changes / Statistical Differences template exception | The supply exporter emits native `Stock Changes\...` and `Statistical Differences\...` rows, but current templates do not expose these roots, so unresolved IDs are retained and reported without failing the run. Gate: refreshed economy templates containing the branches. Complete when all generated rows receive canonical IDs and the temporary exception is removed. |
| INITQ-007 | P1 | 2026-08-04 to 2026-08-10 | `doc_stale` | — | Fix broken links and place stray documents | Repoint the three links to `docs/archive/export_zero_fill_consolidation_execution_prompt.md`. Give `Untitled-2.md` a real name under `docs/` or archive it. Complete when a link check over all 93 tracked Markdown files returns nothing and no placeholder-named document sits at the root. |
| INITQ-008 | P1 | 2026-08-04 to 2026-08-12 | `partial` | INITQ-002 | Archive completed prompt packs | Move settled prompts from `docs/prompts/` into `docs/archive/` with their findings files, and rewrite `docs/prompts/AGENTS.md` from repository evidence so it lists every active prompt exactly once. Complete when `docs/prompts/` contains only active or pending work. |
| INITQ-009 | P1 | 2026-08-05 to 2026-08-12 | `superseded_cleanup` | INITQ-001 | Reduce worktree and branch sprawl | Eight worktrees and ten branches exist; six worktrees and four branches carry no unique work. Remove them only after INITQ-001 and INITQ-002, and treat directory names as unreliable given the recorded name mismatch. Complete when every remaining worktree and branch has an explicit disposition and named owner. |
| INITQ-010 | P1 | 2026-08-10 to 2026-08-17 | `partial` | INITQ-004 | Write the initialisation handover set | A start-here guide, a supply-reconciliation runbook that carries the three launch traps from `AGENTS.md` (pin the interpreter, verify which process is running, clear stale economy locks only after confirming the pid is dead), and a stated contract for what this repo consumes from `leap_mappings`. Prefer links to `docs/supply_reconciliation_workflow_guide.md` over copying it. Complete when a colleague can launch a scoped run from a clean checkout using only tracked docs. |
| INITQ-011 | P2 | 2026-08-10 to 2026-08-17 | `partial` | — | Date and prune the engineering log | Add a snapshot date to `docs/work_queue.md` and separate its settled sections from its active ones, without deleting the trap and known-failure records. Complete when a reader can tell at a glance which items are live. |
| INITQ-012 | P2 | 2026-08-12 to 2026-08-19 | `partial` | INITQ-004 | Finish the per-economy export-template rollout | Item `[7]`. Complete when every economy in the current run scope has a verified export template or is explicitly out of scope with a reason. |
| INITQ-013 | P0 | 2026-08-18 to 2026-08-24 | `not_started` | all above | Participate in the clean-checkout handover rehearsal | Follow the runbook from a fresh checkout alongside the other two repositories. Complete when a scoped supply-reconciliation run and a results-update preview both succeed without undocumented local knowledge. |

## Four-week handover sequence

### Week 1: 2026-07-28 to 2026-08-03

- Protect the detached-HEAD commit before any cleanup (INITQ-001).
- Integrate the baseline-seed export diagnostics branch (INITQ-002).
- Re-fetch and reconcile the 142-commit remote gap (INITQ-003).

### Week 2: 2026-08-04 to 2026-08-10

- Run the baseline-seed diagnostics cycle and settle the adjustment strategy
  (INITQ-004, INITQ-005).
- Fix broken links and stray documents (INITQ-007).
- Begin prompt archival (INITQ-008).

### Week 3: 2026-08-11 to 2026-08-17

- Write the handover set (INITQ-010).
- Complete worktree and branch cleanup (INITQ-009).
- Date and prune the engineering log (INITQ-011).
- Close or explicitly defer the template rollout and template exception
  (INITQ-006, INITQ-012).

### Week 4: 2026-08-18 to 2026-08-24

- Participate in the clean-checkout rehearsal (INITQ-013).
- Fix the documentation gaps the rehearsal exposes.
- Freeze a final dated queue and known-risks list.

## Queue maintenance rules

1. Re-date the snapshot header whenever a status changes.
2. Cite the commit, worktree, run ID, or human decision supporting each status.
3. Never remove a worktree before confirming its HEAD is reachable from a branch.
4. Keep `docs/work_queue.md` as the reasoning log; keep this file as the dated
   state view. Do not duplicate content between them.
5. At the end of each week, record what moved to `complete_on_master`, what is
   blocked, and what must be descoped before handover.
