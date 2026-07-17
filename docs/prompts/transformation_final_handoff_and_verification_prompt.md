# Task: settle the handoff and finish transformation patcher verification

This prompt is the next-agent handoff for the final outstanding work in the
LEAP initialisation export-readiness track.

## Objective

Complete these steps in order:

1. Review and settle the previous agent's uncommitted changes.
2. Ensure the repository is clean.
3. Regenerate a fresh 12_NZ baseline seed using the current transformation rules.
4. Run the transformation patcher equivalence harness against that fresh seed.
5. If the harness passes, remove the transformation patch gate correctly.
6. If it finds a real defect, retain the gate and document the specific defect.
7. Refresh `docs/work_queue.md` so it reflects the final state.

Do not claim completion based on unit tests alone. The important evidence is the
real patcher compared with a fresh full-run seed using the same post-write
boundary.

## First: inspect and protect the handoff

Run:

```text
git status --short
git diff --stat
git diff -- codebase/functions/transformation_analysis_utils.py
git diff -- tests/test_hydrogen_transformation_workflow.py
git diff -- docs/prompts/patch_baseline_seeds_module_verification_prompt.md
```

At handoff, the known uncommitted files are:

- `codebase/functions/transformation_analysis_utils.py`
- `tests/test_hydrogen_transformation_workflow.py`
- `docs/prompts/patch_baseline_seeds_module_verification_prompt.md`
- `docs/prompts/transformation_patch_ungate_final_verification_prompt.md`

These belong to the previous agent until reviewed. Do not discard them, reset
them, or commit them as part of this task without understanding and explicitly
separating their scope.

The hydrogen change removes the special `17_x_green_electricity` display-name
override and deletes a related test. Verify that this is intentional and that
the remaining hydrogen tests still express the required behaviour. If it is
not safe to accept, stop and report the precise issue rather than silently
reverting it.

If the changes are valid, commit them in a focused handoff commit. If they are
not valid, preserve the evidence and make only the minimum corrective change.
Do not begin the harness while unrelated changes remain unresolved.

## Fresh NZ seed

Before running the harness, confirm that the tree is clean and inspect the
current transformation rule stamp. The old 20260715 seeds are stale and cannot
provide evidence after the transformation-rule changes.

Use the repository's established notebook-safe workflow to regenerate the NZ
seed. Do not invent a new command-line workflow. Let any long-running workflow
complete; do not interrupt it. Record:

- the commit used;
- the seed output path;
- the seed timestamp/stamp;
- the economy and scenarios processed;
- validation results and any diagnostics.

The NZ template is the accepted current reference. The known zero-valued
unresolved NZ seed rows are not part of this task and must not be converted
into new defects.

## Run the equivalence harness

Use:

```text
python codebase/scrapbook/transformation_ungate_equivalence_harness.py 12_NZ
```

The harness must run against the freshly generated seed and a clean tree. It
must compare POST-write output with POST-write output, back up and restore the
seed in a `finally`, and distinguish:

- `PASS`;
- `DEFECT`;
- `STALE-SEED`;
- `BLOCKED`.

`STALE-SEED` and `BLOCKED` are inconclusive. They are not evidence that the
patcher is correct or defective. If either occurs, diagnose and regenerate the
seed rather than changing the gate.

Record the verdict, seed stamp, rows-only-before, rows-only-after, benign value
differences, non-benign value differences, and any diagnostics.

## If the result is PASS

Ungating requires the complete implementation, not just deleting an exception:

1. Rewire the transformation patch path to the workbook-based producer
   (`save_transformation_exports_with_split_targets`) in the same way as the
   already-verified workbook-based modules.
2. Remove `auto_sector_keys` from the transformation entries in
   `MODULE_REGISTRY` only after the replacement path is in place.
3. Update the `_PRESET_PATCH_BASELINE_SEEDS` verdict comment and related tests.
4. Run focused tests, then the relevant patcher/readiness suites.

Keep measurement, implementation, and documentation in separate coherent
commits. Do not alter unrelated `_PRESET_*` blocks.

## If the result is DEFECT

Keep the transformation gate. Capture the exact offending branch paths,
variables, scenarios, and values. Update:

- `docs/check_registry.md` hotspot 4;
- the transformation section of `docs/work_queue.md` [1];
- the relevant verification prompt or audit note.

Explain whether the defect is a dropped row, invented row, or changed value,
and identify the smallest follow-up needed.

## Queue refresh

After the technical result is settled, update `docs/work_queue.md` to remove
stale wording. In particular, reflect that the following are complete:

- shared-union fuel catalog and `source_templates` provenance;
- export-readiness runner and combined-workbook readiness gate;
- per-economy ID/template routing, including aggregated demand;
- conservation migration;
- NZ readiness audit, subject to future template updates.

Leave the zero-valued NZ unresolved-ID rows described as accepted warnings,
not active defects.

Record the final transformation verdict and any remaining work. Do not mark [1]
complete unless the fresh-seed harness evidence and the resulting code path
both support that conclusion.

## Final deliverables

Report:

1. What happened to each inherited uncommitted file.
2. The fresh seed path and stamp.
3. Harness verdict and all diff counts.
4. Whether the gate was removed or retained, with rationale.
5. Tests and workflows run.
6. Updated queue location and remaining open items.
7. Final `git status --short`.

Never use destructive Git commands such as `git reset --hard` or
`git checkout --` to resolve the handoff.
