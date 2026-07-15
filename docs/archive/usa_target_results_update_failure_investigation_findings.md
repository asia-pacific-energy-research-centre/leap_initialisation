# USA Target results-update failure investigation

Date: 2026-07-15

## Result

The original silent termination was not reproduced. Its root cause remains
unconfirmed. The available evidence does not establish an out-of-memory or
Windows application failure.

The original run wrote the compressed projection sources and completed the
balance-demand conservation outputs, including the approximately 130 MB
lineage CSV. The last durable artifact was:

`outputs/leap_exports/supply_reconciliation/results_update/runs/UPDATE_20_USA_TGT/preflight_compressed_projection/checks/supply_reconciliation_balance_demand_conservation_lineage.csv`

modified at 14:53:42. The workflow log and launcher stdout/stderr were empty,
and no timing/state/final-results workbook was present.

## Evidence and commands

The worktree was checked first with `git status --short`; existing edits in
five unrelated code files were preserved.

The original lock contained PID `53316`, host `LAPTOP-3O0V48JB`, and
`started_at=2026-07-15T05:47:41+00:00`. The PID was not running, so the lock
was stale and was removed before the diagnostic. The retry log separately
shows the earlier retry failed in `economy_run_locks` on that stale lock with
`OSError: [WinError 87]` from the old Windows `os.kill(pid, 0)` probe.

Windows Application events were queried for 14:35–15:20 local time, filtering
Application Error, Windows Error Reporting, Python, and Application Hang.
No matching event was found.

At the initial inspection, Windows reported approximately 5.8 GiB free
physical memory, 27.4 GiB free virtual memory, and 154.2 GiB free on C:. The
completed diagnostic reached approximately 1.1-1.7 GiB private memory. These
observations do not prove that no external resource problem occurred, but
provide no direct OOM evidence.

The prescribed configuration was run with `python -u` using a temporary
notebook-style runner. Two initial launcher attempts were discarded as
non-workflow launcher quoting failures (`SyntaxError: Expected one or more
names after 'import'`) and are preserved in:

- `outputs/leap_exports/supply_reconciliation/results_update/runs/USA_TGT_DIAGNOSTIC_20260715_152604`
- `outputs/leap_exports/supply_reconciliation/results_update/runs/USA_TGT_DIAGNOSTIC_20260715_153908`

The correctly launched run used:

```python
import codebase.supply_reconciliation_workflow as workflow

workflow.ECONOMIES = ["20_USA"]
workflow.SCENARIOS = ["Target"]
workflow.RUN_MODE = "full"
workflow.RUN_OUTPUT_LABEL = "USA_TGT_DIAGNOSTIC"
workflow.__dict__.update(workflow._PRESET_RESULTS_UPDATE)
workflow.RUN_PREFLIGHT_COMPRESSED_PROJECTION = True
workflow.RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE = False
workflow.PREFLIGHT_COMPRESSED_PROJECTION_ONLY = True
workflow.PREFLIGHT_COMPRESSED_FAIL_FAST = True
workflow.run_with_config()
```

Its launcher files are under:

`outputs/leap_exports/supply_reconciliation/results_update/runs/USA_TGT_DIAGNOSTIC_20260715_155139`

The workflow outputs are under the configured `USA_TGT_DIAGNOSTIC` run tree.

## Confirmed diagnostic failure

The corrected diagnostic passed conservation and lineage generation, then
continued through transformation and transfer workbook generation. It ended
with a normal traceback:

`FileNotFoundError: Other loss/own-use proxy results-update activity needs a LEAP balance workbook for economy='00_APEC', scenario='Target'.`

The compressed projection preflight intentionally runs against `00_APEC`, but
the results-update preset activates the second own-use/loss activity source,
which requires a LEAP balance workbook. No such workbook was available. This
is a deterministic preflight setup/path failure, not evidence for the
original silent termination.

## Recommendation

Do not retry the full USA update yet. First resolve the preflight contract:
provide the required `00_APEC` LEAP balance workbook or change the preflight
configuration/design so a projection-only diagnostic does not require
results-update LEAP activity inputs. After that, rerun the prescribed
diagnostic. The original abrupt termination should still be treated as an
unconfirmed external/process/resource event unless a controlled rerun records
a traceback.

No modelling assumptions, mappings, validation rules, or workflow code were
changed. No code fix or commit was made for the pre-existing diagnostic
configuration failure.
