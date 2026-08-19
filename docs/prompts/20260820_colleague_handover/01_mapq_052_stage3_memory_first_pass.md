# MAPQ-052 — Stage 3 deep-validation memory first pass

> **Scheduling status, 2026-08-20:** deferred. This is a periodic mapping
> maintenance task, not part of the current three-hour readiness block. Keep
> this card intact and assign it immediately before the next intentional fresh
> mapping run; do not use its deferral as permission to run an unmeasured
> refresh.

## Objective

Make one narrow, evidence-led change to the mapping pipeline that reduces the
risk of its Stage 3 deep validation being killed by Windows, while proving it
does not alter mapping semantics or silently drop findings. The incident peak
was 17.9 GB RSS; a later run was OS-killed with about 0.4 GB free. This task is
the release gate for a new mapping output.

## Scope

Implement only MAPQ-052’s first two planned phases:

1. Add trustworthy phase-level RSS/timing/status observability to deep
   validation and capture the final state through `finally`.
2. Apply the safe narrow-read/early-filter changes already reviewed in the
   queue: manifest-validated `columns=` reads, eight-column recursive reads,
   prompt frame release after grouping, no raw diagnostic-source reads where
   there are no failures, and early scenario/year plus canonical-context
   filtering in the APEC retry.

Likely modules include the manifested-Parquet reader,
`build_dataset_tree_structure.py`, anchor validation, and child diagnostics.
Locate actual call sites before editing. Preserve the Common ESTO contract:
common rows remain a lowest-common-denominator merge/aggregation product, never
an allocation.

## Do not do

- Do not change mapping sheets, membership, rollup rules, fact values, or
  output schemas.
- Do not begin the follow-on streaming Stage 3 redesign, category experiment,
  dense-pivot rewrite, or a full mapping refresh.
- Do not claim recovery by catching `MemoryError`; a fallback is a separate,
  later design.
- Do not run this deep-validation job alongside baseline-seed work or another
  memory-heavy pipeline.

## Procedure

1. Record `git status --short` and work in an isolated worktree/branch if
   current mapping changes could overlap. The known untracked
   `.codex_tmp_rollup_fix/` is not part of this task.
2. Read the current focused tests and identify the declared keys and expected
   dtypes for every Parquet artifact used here. Add phase markers for recursive
   product/flow read-group-lookup, child diagnostics, raw evidence load, APEC
   pass, and economy retry. Include status (`completed`, `MemoryError`, or
   `process_interrupted`), duration, RSS, row/group/context counts, and a final
   sample written from `finally`.
3. Add projected Parquet reads only after manifest column validation. Restore
   dtypes by *column name*, not column position. Then make the recursive
   validator request only its documented eight columns and release its source
   frame once grouped state exists.
4. Make child diagnostics consume only needed comparison columns. With no
   failed checks, return the normal empty artifacts without opening raw source
   files. Move the APEC retry’s scenario/year and canonical-context filters
   before its expensive copies and lookup construction; do not filter its
   economies.
5. Add focused tests for projected-column/dtype validation, the no-failure
   no-raw-read path, and early retry filtering. Add an old/new equivalence
   harness comparing stable-sorted recursive detail, grouped checks, summary,
   APEC issues, and selected-economy examples under existing tolerances.
6. Run focused tests, then one bounded real-data Stage 3/deep-validation run
   alone. Compare the resulting artifacts and record peak RSS per phase plus
   elapsed time. Stop if a reported failure disappears, checks collapse to
   zero, an APEC example loses an eligible economy, or the contract/hash
   changes.

## Acceptance

- Existing focused Stage 3/anchor/typed-output tests and new tests pass.
- Fixture and bounded real-data outputs are equivalent after declared-key
  sorting, including statuses, reasons, counts, and tolerant numeric values.
- Deep-validation evidence reports phase-level RSS/timing and an honest final
  status; it does not imply a completed comparable baseline where none exists.
- One small, cohesive commit contains only this task’s implementation/tests.

## Handoff report

Return a short Markdown note with:

1. commit hash or precise stop point;
2. modules changed and test commands/results;
3. mapping run ID, phase peak RSS, elapsed time, rows/groups/contexts;
4. equivalence comparison result; and
5. a binary downstream signal: `MAPPING_OUTPUT_SAFE_TO_REFRESH` or
   `RELEASE_HOLD`, with the reason.
