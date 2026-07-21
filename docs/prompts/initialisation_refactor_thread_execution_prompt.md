# Initialisation refactor - thread execution prompt

Type: implementation prompt, multi-session, thread-at-a-time.
Status: active, opened 2026-07-21.
Register: [`initialisation_refactor_continuation.md`](initialisation_refactor_continuation.md)

## Short version

Pick **one** thread from the register, confirm it is not blocked, do it as one
or a few small commits with focused tests, update the register, stop and report.
Do not attempt several threads in one session, and do not treat the register as
a to-do list to burn down.

## Context you need before starting - read this, it changes what you should do

### Where the repository actually is

The initialisation refactor was planned as five phases (`AGENTS.md`, "Planned
workflow improvements"). **That section is materially stale and must not be used
for scoping** - see thread T9. The measured position as of 2026-07-21:

| Phase | Real status |
|---|---|
| Phase 1 - shared utilities and cache hardening | **Done** (`56f951a`, `3116741`, `eca34af`). Do not reopen. |
| Phase 2 - configuration standardisation | **The current phase.** `supply_workflow.py` done (`70613de`); `transformation_workflow.py` and `electricity_heat_interim_workflow.py` remain. See `work_queue.md` [14] and `phase_2_configuration_standardisation_execution.md`. |
| [15] scoped modelling reviews | Pending, sequenced after/alongside Phase 2. Review documents, not implementations. |
| Phases 3, 4, 5 | **Future work.** Planned in detail (three briefs) but not started. |

So most threads in the register belong to **future phases**. The register exists
because those phases were planned in one session and the planning would
otherwise be lost - not because all of it is due now.

### Why some future-phase items are being brought forward

Three findings from the planning session are **urgent enough to jump the phase
order**, and are deliberately being done during the current phase:

1. **T1 - `work_queue.md` [17], the preset-forwarding defect.** Two preset
   overrides never reach the module that reads them, so the supply/transformation
   zero-reset and the demand-zeroing workbooks have been silently switched off
   across **every recent baseline seed**, while the run log reported them on.
   This is an active production defect, not a refactor. It has its own prompt:
   `preset_forwarding_fix_execution_prompt.md`. **It is the current priority and
   nothing else in the register should start ahead of it.**
2. **T7's guard on `PARALLEL_ECONOMY_WORKERS`.** A `ThreadPoolExecutor` over
   economies already exists and shares the mirrored module globals; it is safe
   only because the default is `0`. Raising that dial today would corrupt
   results with no error. The guard is a small commit that removes a live
   foot-gun years before the rest of Phase 5C is due.
3. **T6 G2 - the demand-zeroing/active-sector gap.** Dormant only because no
   demand sector has been handed over yet. The first handover arms it, and it
   fails as silent energy loss. Blocked on T1, but must not be left unscheduled.

Everything else in the register is genuine future-phase work. **Bringing more of
it forward needs a reason, not enthusiasm.** If a thread looks tempting but is
not urgent, leave it; the phases exist to keep blast radius small.

### The distinction to hold on to

- **Urgent** = it is wrong *now*, in production output, or it can silently
  become wrong without anyone noticing. Bring forward.
- **Planned** = it makes the code better, faster, or easier to change. Wait for
  its phase.

If you cannot state which of those a thread is, you have not understood it well
enough to start.

## Standing safety rules

These apply to every thread and are not negotiable:

1. **While a long workflow run is in flight, commit documentation and new test
   files only.** A code commit landing mid-run can kill it through mixed module
   versions - this destroyed the 2026-07-21 fleet run 78 minutes in, with no
   seeds produced. See the trap entry in `work_queue.md`. A clean
   `git status` at launch does **not** protect you.
2. Check `git status --short` first. Preserve unrelated working-tree changes -
   in particular a temporary `RUN_OUTPUT_LABEL` in
   `supply_reconciliation_workflow.py`, which belongs to the operator, and
   `node_modules/`, which is not ours.
3. One coherent change per commit, `codex:` message convention, focused tests in
   the same commit.
4. Never diff raw export output against a finished seed. Compare post-boundary
   on both sides (`prepare_seed_rows_for_write` does canonical share completion,
   so a pre/post comparison manufactures differences).
5. Never reintroduce a pinned `id_lookup_path` or template default
   (`work_queue.md` [7]).
6. Do not chase the known pre-existing test failures listed in `work_queue.md`
   ("Known pre-existing failures"). They are intentional or stale, not
   regressions.
7. Python is `/c/Users/Work/miniconda3/python.exe` via the Bash tool. Do not use
   PowerShell's `python`/`py`, and do not activate `.venv` (it is a WSL venv).
   Several `codebase/*.py` files carry a UTF-8 BOM - read as `utf-8-sig` for any
   AST or text tooling or they will be silently skipped.
8. Do not modify `C:\Users\Work\github\leap_mappings`. It is read-only from
   here. If a thread implies an obligation there, report it (see T10).

## Procedure for one thread

1. **Open the register** and re-read the thread. Re-verify its blockers against
   the tree - the register is a snapshot and blockers move.
2. **Confirm scope.** State in your first message: which thread, whether it is
   *urgent* or *planned*, what you will commit, and what you will not touch.
3. **Check for decisions.** If the thread depends on an open decision in the
   register's decision table, **stop and ask** rather than picking a default.
   Ten decisions are listed with recommendations; a recommendation is not an
   approval.
4. **Characterization before change.** If the thread moves or replaces existing
   behaviour, land the tests that pin current behaviour *first*, in their own
   commit. This is repo-standard practice, not optional
   (`phase_4_monolith_decomposition_execution.md` makes it explicit).
5. **Implement** as small commits. Anything output-affecting goes in a commit of
   its own, never bundled - so it can be reverted alone when a seed diff appears.
6. **Test.** Run the focused tests plus a collection check:
   `python -m pytest tests/ -q --collect-only | tail -5`. If a thread's change
   is output-affecting, unit tests are not sufficient evidence - see below.
7. **Update the register** in the same commit: thread status, decisions taken,
   anything the work proved wrong about the plan. **Recording what the plan got
   wrong is a required deliverable, not a courtesy** - two briefs have already
   been corrected this way.
8. **Stop and report.** One thread per session.

## Evidence standards

- **Test-only threads** (T2, parts of T4, T8): focused tests passing, plus
  collection clean, is sufficient.
- **Behaviour-affecting threads** (T4 commit 4, T6, and T1's step 4): require a
  **single-economy before/after comparison, post-boundary on both sides**, with
  branch-path key sets, row counts, and per economy/scenario/fuel totals. State
  the tolerance used. A green test suite is not evidence that a seed is
  unchanged.
- **Never** run a full fleet run to prove a refactor. If a thread seems to need
  one, stop and ask - the answer is usually a smaller check.

## Stop and ask the user when

- a thread depends on an open decision, or on a modelling judgement of any kind;
- the change would alter seed contents and the thread did not already say so;
- a blocker you expected to be cleared is not;
- you find a defect outside the thread's scope (record it in `work_queue.md`
  and report it - do not fix it inside an unrelated commit);
- a long run appears to be in flight and your thread needs a code commit;
- the work turns out to be larger than "one or a few small commits".

## Suggested order

From the register, subject to T1 completing first:

1. **T1** ([17]) - separate prompt, current priority.
2. **T7's guard** on `PARALLEL_ECONOMY_WORKERS` - small, urgent, independent.
3. **T2** remaining characterization tests - safe, unblocks T3.
4. **T6 G1**, then **T6 G2** once T1 has landed.
5. **T4** commits 1-3 and 5 - safe at any time, can interleave.
6. **T3** state injection, then re-decide D4.3 with fresh measurements.
7. **T5** - fully self-contained, whenever convenient.
8. **T8** fixtures; **T9** documentation corrections incrementally as phases
   complete; **T10** when the mapping owner is available; **T11** after T1.

## Deliverables per session

- The commits, with hashes.
- Updated register entry.
- Any correction to a brief that the work proved wrong.
- A clear statement of what is now unblocked, and what the next thread should be.
