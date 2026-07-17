# Task: the last step to proving the patcher works — ungate transformation

Supersedes the transformation section of
[patch_baseline_seeds_module_verification_prompt.md](patch_baseline_seeds_module_verification_prompt.md),
which remains the reference for every **other** module (transfers, power_interim,
aggregated_demand, losses_own_use, supply — all already verified) and for the
general Verification Recipe.

## The one open question

`patch_baseline_seeds.run_patch()` raises `NotImplementedError` for every module
with `auto_sector_keys` — i.e. all transformation sectors. Every other module is
patchable and verified. **Transformation is the last one, and this is the last
step.**

The gate exists on evidence that is probably an artefact:

> "20_USA: 7 process-efficiency / auxiliary-fuel expression diffs"

That was almost certainly measured on the **raw** output of
`save_transformation_exports_with_split_targets`, which skips
`prepare_seed_rows_for_write` — the seed writer the real patcher applies
(`patch_baseline_seeds.py:928-946`). The writer does canonical share completion
and cross-scenario borrowing, so **comparing raw output to a finished seed
manufactures differences that were never real.**

A read-only reassessment (2026-07-16) already showed process-efficiency and
aux-fuel expressions **match** through the real write path, and that 20_USA's one
apparent conflict is the Reference→Target output-share fallback that
`complete_canonical_share_groups` applies. So the gate may be guarding nothing.

**Settle it with evidence, then act. Do not delete the gate on argument alone.**

## The instrument (already built)

`codebase/scrapbook/transformation_ungate_equivalence_harness.py`

It runs the **real** patcher, bypassing only the gate via `_run_patch_locked`,
and diffs **POST-write vs POST-write** so both sides have crossed the same
boundary. It implements the Verification Recipe: backup outside the seed dir and
restore in a `finally`; filter module-owned rows by `strip_prefixes`; key on
`(Branch Path, Variable, Scenario)` and **not** `Region`; parse `Data(...)`
numerically; pass only on zero-rows-only-before, zero-rows-only-after, zero
non-benign value differences.

```bash
python codebase/scrapbook/transformation_ungate_equivalence_harness.py 20_USA
python codebase/scrapbook/transformation_ungate_equivalence_harness.py 20_USA 01_AUS
```

Guarded by `tests/test_transformation_ungate_harness.py` (17 tests). The
classifier is load-bearing: if it called a real change "benign" it would
greenlight ungating on top of a defect.

## Preconditions — all three, or the result is worthless

1. **Clean tree.** `git status --short` must be empty. The patcher imports
   `supply_leap_io.py` and `transformation_analysis_utils.py`; verifying against
   a dirty tree is what invalidated the previous attempt.
2. **A seed built with current transformation rules.** The harness refuses
   otherwise (`STALE-SEED`) — see below. Every seed stamped `20260715` predates
   `8c32504` (2026-07-16, the `multi_output` default) and cannot answer this.
3. **Per-economy template routing.** ✅ Done (`39f82df`, `12e1482`, `e799029`,
   `ee4e5d1`, `6714db0`). Never pin `full model export.xlsx`.

Precondition 2 is the live one. Regenerate the economy's seed with a full run
first, and place it in `outputs/.../baseline_seed/`.

## Reading the verdict

| Verdict | Meaning | Action |
| --- | --- | --- |
| `PASS` | Patch reproduces the full-run seed | The gate's premise is false → proceed to ungate (**read the next section**) |
| `DEFECT` | Real rows dropped/invented/changed | The gate is right. Keep it, now with real evidence. Record the rows. |
| `STALE-SEED` | Seed predates current transformation rules | **Inconclusive, NOT evidence either way.** Regenerate and re-run. |
| `BLOCKED` | Seed fails validation against its own template | **Inconclusive, NOT evidence for the gate.** A contaminated seed blocks the write before any comparison. Regenerate. |

The bottom two rows exist because both were hit for real on 2026-07-17. Neither
is a patcher defect, and neither may be recorded as one.

## If it PASSES, ungating is not just deleting the gate

The patcher's transformation path uses `_collect_auto_regen` (the simplified
path), **not** `save_transformation_exports_with_split_targets`. Ungating means:

1. Rewire transformation to be workbook-based via
   `save_transformation_exports_with_split_targets` — the model `transfers`
   already follows.
2. Then drop `auto_sector_keys` from the transformation entries in
   `MODULE_REGISTRY`.
3. Update the verdict comment above `_PRESET_PATCH_BASELINE_SEEDS`.

If revisiting the raw layers, the patch path must reproduce **before** the seed
writer: Exogenous Capacity / Historical Production seeding, output-fuel
Import/Export Target resets, and full catalog zero-fill from the same catalog
source as the full run.

## Hard constraints

- **Never diff raw export output against a finished seed.** This is the trap that
  produced the gate and cost a retracted conclusion. Always compare post-boundary.
- Back up and restore seeds in a `finally`. The harness does; keep it that way.
- Preserve unrelated working-tree changes; do not touch other `_PRESET_*` blocks.
- Do not broaden scope beyond transformation.
- If equivalence genuinely requires full reconciliation state, **keep the gate**
  rather than approximating.
- Bump `TRANSFORMATION_RULES_CHANGED` in the harness when transformation output
  rules change again — otherwise it will happily compare across a rules change.

## Deliverables

1. The verdict per economy, and the seed stamp each ran against.
2. Diff numbers: rows-only-before, rows-only-after, benign vs non-benign values.
3. Diagnostics separated from patch failures.
4. On `PASS`: the rewiring above, the gate removal, and the updated verdict
   comment — as separate commits from the measurement.
5. On `DEFECT`: the offending rows, and `docs/check_registry.md` hotspot 4 plus
   `docs/work_queue.md` [1] updated with the confirmed rationale.
6. Final `git status --short`.

Related: `docs/check_registry.md` hotspot 4, `docs/work_queue.md` [1], and the
`transformation-patch-gate-reassessment` memory.
