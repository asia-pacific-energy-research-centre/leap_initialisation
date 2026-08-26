# Implement the Oil Refining net-output and own-use boundary

Type: focused implementation prompt. Status: active. Created 2026-08-26.

## Objective

Correct the baseline-seed representation of Oil Refining so its fuel-level
LEAP results use the Ninth inclusive boundary (`09.07 Oil refineries` plus
`10.01.11 Oil refineries` own use).

This task is only for the remaining refinery fuel-level/own-use issue. The
separate 90% output issue is caused by Target `Maximum Availability = 90%` and
is not part of this code change.

## Read first

Follow the repository instructions in `AGENTS.md` and read:

- `docs/prc_gasworks_refining_dispatch_and_own_use_findings.md`
- work-queue item `[59]` in `docs/work_queue.md`
- `codebase/functions/transformation_record_builder.py`
- the Oil Refining capacity exception in
  `codebase/supply_reconciliation/leap_io.py`
- `tests/test_transformation_efficiency_feedstock_only.py`

Before editing, run `git status --short`. Preserve all unrelated changes,
especially any existing change to
`config/baseline_seed_validation_exception_sets.xlsx`.

## Confirmed problem

The current record builder calculates Oil Refining on a mixed boundary:

- Exogenous Capacity uses net deliverable refinery output;
- Output Shares still use gross `09.07` product output;
- Auxiliary Fuel Use ratios still use gross output as their denominator; and
- Process Efficiency correctly uses gross `09.07` output divided by direct
  refinery feedstock.

At 100% Maximum Availability, total positive output is correct, but individual
product outputs and external auxiliary fuels remain different from the Ninth
inclusive values. Merely changing LEAP units did not correct this: it changed
crude-oil consumption but left output and auxiliary-fuel results unchanged.

The existing helper `_normalize_process_boundary_for_leap()` already supports
the required net representation when
`preserve_gross_output_basis=False`. However, `build_process_record()`
currently always passes `preserve_gross_output_basis=True`.

## Required implementation

Make the smallest process-specific change:

1. In `build_process_record()`, use the net-deliverable boundary only when
   `sector_title` identifies `Oil Refining` (case-insensitive and whitespace
   tolerant).
2. Continue preserving the gross-output boundary for all other transformation
   modules. Do not change Gas works, Coke ovens, Blast furnaces, LNG, Transfers,
   or generic transformation behaviour.
3. For Oil Refining, the returned record must contain:
   - `gross_output_values`: unchanged gross `09.07` output by fuel;
   - `output_values`: gross output minus same-fuel `10.01.11` own use, by fuel;
   - `deliverable_output_values`: the same net values used for capacity;
   - `auxiliary_ratios`: all `10.01.11` own-use energy divided by total net
     deliverable output; and
   - `efficiency`: unchanged gross `09.07` output divided by direct feedstock.
4. Retain the existing Oil Refining capacity rule in
   `codebase/supply_reconciliation/leap_io.py`: capacity must continue to use
   `deliverable_output_values`. Do not inflate capacity to compensate for
   Maximum Availability.
5. Preserve the helper's existing zero-net-output safeguard. Do not invent a
   new fallback for a fully self-consuming refinery.

A likely minimal implementation is to make the
`preserve_gross_output_basis` argument passed by `build_process_record()`
conditional on whether `sector_title` is Oil Refining. Inspect the existing
helper before editing and avoid duplicating its netting or rebasing logic.

## Required regression tests

Update or replace the outdated refinery gross-boundary assertions in
`tests/test_transformation_efficiency_feedstock_only.py`. Do not weaken or
delete the tests for other transformation modules.

Add focused assertions proving that a synthetic refinery with:

- 100 PJ gross output;
- 80 PJ Motor gasoline and 20 PJ Refinery gas output;
- 20 PJ Refinery gas own use;
- 5 PJ Natural gas external own use; and
- 110 PJ direct crude feedstock

produces a record with:

- 80 PJ net deliverable output;
- Motor gasoline output of 80 PJ and Refinery gas output of 0 PJ;
- Exogenous Capacity of 80 PJ before any separately supplied runtime addition;
- Refinery gas auxiliary ratio `20 / 80`;
- Natural gas auxiliary ratio `5 / 80`;
- Process Efficiency `100 / 110`; and
- a net-boundary status rather than
  `gross_output_with_separate_auxiliary_use`.

Also retain or add a multi-output refinery case where some output remains after
same-product own use. Prove fuel by fuel that:

```text
net refinery output = gross 09.07 output - same-fuel 10.01.11 own use
auxiliary energy     = rebased ratio * total net deliverable output
```

Keep the parametrized non-refinery overlap test passing unchanged so Coke
ovens, Blast furnaces, and LNG continue using their existing gross boundary.

## Verification

Run at least:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests/test_transformation_efficiency_feedstock_only.py -q
```

Then run the nearest baseline-seed writer/output-share tests affected by the
change. If practical, generate a controlled PRC seed and compare only the Oil
Refining rows against the previous seed. Do not launch a full all-economy run.

If a fresh LEAP import/export is available, verify it using Target Maximum
Availability already set to 100%. Require the 2060 result to reproduce:

- total net deliverable output;
- individual net product outputs;
- natural-gas and electricity auxiliary use;
- crude-oil input; and
- the signed `09.07 + 10.01.11` fuel-level comparison.

Do not claim the LEAP-side issue is fully closed without this fresh export. A
workbook-only result may be reported as code/tests complete and awaiting LEAP
verification.

## Non-goals and safeguards

- Do not change the Gas works implementation.
- Do not modify dashboard mappings to hide the difference.
- Do not add own use to Exogenous Capacity.
- Do not change refinery efficiency to a net-output denominator.
- Do not alter Maximum Availability in this task.
- Do not perform a broad transformation refactor.
- Do not update unrelated documentation or formatting.

## Completion criteria

The task is complete when:

1. Oil Refining alone uses net per-fuel outputs and net-denominator auxiliary
   ratios while retaining gross-output/direct-feedstock efficiency.
2. Oil Refining capacity remains net deliverable output.
3. Focused tests prove the numerical identities above.
4. Non-refinery transformation tests remain unchanged and pass.
5. The agent reports exactly which tests and controlled artifacts were used,
   and clearly separates workbook verification from fresh LEAP verification.
6. The implementation and tests are committed in one focused commit, without
   including pre-existing unrelated changes.
