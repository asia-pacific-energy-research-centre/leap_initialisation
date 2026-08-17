# Supply reconciliation agent guide

**Verified:** 2026-08-17

> **Operating status:** `baseline_seed` is the normal path. The implemented
> `results_update` path is optional, under review, and may be deactivated. Do
> not run it unless the active run plan explicitly requests it.

Read `AGENTS.md`, `docs/work_queue.md`, the
[reader guide](supply_reconciliation_guide.md), and
[`../check_registry.md`](../check_registry.md) first.

## Operational inventory

| Workflow | Entry | Inputs | Outputs | Canonical mutation | Downstream |
|---|---|---|---|---|---|
| baseline seed / optional update | `codebase/supply_reconciliation_workflow.py` | source tables, mappings, templates; LEAP results only for an explicit optional update | run-labelled workbooks/tables/diagnostics | generated files; live LEAP only if enabled | LEAP |
| patch | orchestrator `RUN_MODE="patch_baseline_seeds"` | existing seed and selected module | patched seed and validation | generated seed | LEAP |
| supply producer | `codebase/supply_workflow.py` | ESTO/9th/mappings | resource/trade rows | generated | orchestrator |
| transformation | `codebase/transformation_workflow.py` | signed transformation sources/mappings | capacity/efficiency/input/output rows | generated | orchestrator |
| transfers | `codebase/transfers_workflow.py` | reviewed transfer config/source | transfer rows | generated | orchestrator |
| loss/own use | `codebase/other_loss_own_use_proxy_workflow.py` | source or LEAP activity | proxy workbook/diagnostics | generated | orchestrator |

## Required environment

- Windows;
- `C:\Users\Work\miniconda3\python.exe`;
- Excel-compatible libraries;
- LEAP and `pywin32` only for live COM/API operations;
- Jupyter/`#%%` execution with editable constants.

Do not use the repository `.venv` from PowerShell or a bare `python` alias.

## Before editing or running

1. Run `git status --short --branch`.
2. Read `docs/work_queue.md` known failures and active processes.
3. Inspect worktrees and exact Python command lines.
4. Verify no same-economy reconciliation process is active.
5. Inspect locks and confirm PIDs before considering stale-lock removal.
6. Close relevant Excel workbooks.
7. Verify templates, source vintages, and the canonical mapping path. Verify
   balance exports only for diagnostics or an explicitly selected optional
   `results_update` run.
8. Set a unique dated output label for a retained repeated scope.
9. Record commit, dirty state, economy/scenario/year scope, mode, and template.

## Important constants/toggles

| Setting | Meaning/risk |
|---|---|
| `ECONOMIES` | economy run order/scope |
| `SCENARIOS` | normally Target, Reference, Current Accounts |
| `RUN_MODE` | full or patch orchestration |
| `RUN_OUTPUT_LABEL` | run-root identity; identical `auto` scope can collide |
| `CAPACITY_UNMET_PASS_MODE` | use `baseline_seed` normally; `results_update` is optional and under review |
| `RUN_PREFLIGHT_COMPRESSED_PROJECTION` | isolated projection preflight |
| `RUN_PREFLIGHT_COMPRESSED_RESULTS_UPDATE` | isolated update preflight |
| `TEST_HORIZON_BASE_YEAR_PLUS_ONE` | normal two-year development/production-check horizon when true |
| `RUN_RESET_SUPPLY_AND_TRANSFORMATION_IMPORT_EXPORT` | reset behavior, preset-controlled |
| `RUN_ELECTRICITY_HEAT_INTERIM` | placeholder power modules |
| `RUN_OTHER_LOSS_OWN_USE_PROXY` / stage | proxy activity source |
| live LEAP import/scrape toggles | external mutation; review explicitly |
| `PARALLEL_ECONOMY_WORKERS` | process-based economy parallelism; use carefully |

Module-level values are mirrored into consumer modules. Read the workflow’s
printed “effective setting” block; the wrapper copy is not proof of what ran.

## Jupyter execution

Review the editable constants in `supply_reconciliation_workflow.py`, then:

```python
#%%
from pathlib import Path
import os
import runpy

REPO_ROOT = Path(r"C:\Users\Work\github\leap_initialisation")
os.chdir(REPO_ROOT)

WORKFLOW_PATH = REPO_ROOT / "codebase" / "supply_reconciliation_workflow.py"
RESULTS = runpy.run_path(str(WORKFLOW_PATH), run_name="__main__")

#%%
```

Do not edit the shared workflow file to launch another economy scope while a
process is in its late preflight import window. Run sequentially unless using a
proven per-process configuration boundary.

## Process monitoring

Verify the interpreter and actual command:

```powershell
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
  Select-Object ProcessId, Name, CommandLine
```

Let the workflow run to completion. Poll at most every 10 minutes. Do not kill
it merely to check status.

Each lock is JSON and contains its owner PID. Never clear a lock while that PID
is alive. A killed process can leave stale locks; validate the exact PID first.

## Expected runtime

Default repository verification is deliberately bounded:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest -q
```

`pytest.ini` excludes tests marked `integration` from that command. On
2026-08-13 it collected 1,471 default tests in 5.38 seconds and completed in
10m51s while a full mapping conversion was also active; only one pytest process
was observed (about 1.2 GB working set), rather than the prior multi-process
1.8-3.2 GB fan-out. Run an expensive case explicitly with, for example,
`pytest -o addopts="" -m integration tests/test_dashboard_from_export.py`.
The complete integration set stages large packages and reads production data;
the previous unbounded run was still active after 20 minutes with several
multi-GB workers, so run the required module(s), not the entire integration set,
unless that cost is intentional.

Observed real three-economy baseline run, 2026-07-28:

```text
01_AUS + 20_USA + 05_PRC, three scenarios: 1h 26m 50.9s
```

Per-economy transformation generation was roughly 6–7 minutes in that run.
These are planning observations, not timeouts. LEAP Energy Balance export is a
separate 3–4 hour operation for a full area.

## Run roots and overwrite behavior

Normal outputs:

```text
outputs/leap_exports/supply_reconciliation/<pass>/runs/<label>/
```

The workflow isolates labelled runs and locks economies. Reusing the same
resolved label can interleave/overwrite files. Keep production and compressed
preflight roots separate. Do not manually merge artifacts between runs.

Patch mode strips the configured module slice and inserts regenerated rows. It
uses the common emit boundary, but module equivalence must be documented before
treating the patch as safe.

## Validation sequence

1. preflight results and deferred errors;
2. workflow timing/status rows;
3. source and balance-matching diagnostics;
4. conservation and source-preservation checks;
5. baseline rule findings/issue groups;
6. per-economy export-readiness JSON and findings;
7. duplicate four-part keys;
8. unresolved IDs and branch/template coverage;
9. representative expressions and Level columns;
10. convergence state/manifest for iterative updates.

Import gate:

```text
blocking_failures == 0
```

plus reviewed warnings/conservation evidence. The latest 20_USA real seed does
not meet this gate.

## LEAP workbook contract

- read/write header at row 2;
- preserve preamble rows 0–1;
- preserve ID and metadata fields from the economy template;
- unique key is Branch Path + Variable + Scenario + Region;
- expression must be valid LEAP syntax;
- Level columns match Branch Path;
- `-1` is unresolved.

Do not fabricate a missing branch, copy another economy’s IDs, or waive a
non-zero unresolved ID.

For aggregated demand, verify the values before diagnosing an absent generated
branch: the workflow intentionally omits branches whose selected modelled
values are all zero (`5544853`).

## Optional results-update loop — under review

Do not treat this as a required continuation of baseline seed. Use it only
when the active run plan explicitly selects `results_update`.

1. Review/import seed.
2. Recalculate correct LEAP area.
3. Export Energy Balance in PJ at Level 2+.
4. Verify file placement, economy, scenarios, years, and detail.
5. Run results-update.
6. Inspect product/year gaps and allocation ledger.
7. Check caps, production-only products, transformation order, import fallback,
   exports, conservation, and convergence.
8. Repeat only while that explicit optional update plan remains active.

## Symptom routing

| Symptom | First evidence | Likely owner | Unsafe shortcut |
|---|---|---|---|
| unknown branch or `-1` ID | readiness findings and economy template | initialisation/model structure | copy IDs |
| high positive import gap | production/capacity headroom and shortfall rules | initialisation/model policy | hard-code import |
| high negative gap/export drift | export pinning and surplus policy | initialisation/model policy | flip sign blindly |
| transformation imbalance | signed source rows and conservation breakdown | initialisation; mappings if category wrong | disable check |
| wrong source category | canonical mapping and source lineage | mappings | local duplicate mapping |
| repeated pass has same gap | convergence manifest and actual LEAP export freshness | initialisation/operator | reuse old export |
| run folder mixed | label and timestamps | operator/config | keep writing |
| missing check file | log and output resolver | owning producer | call it zero findings |

## Human-stop conditions

Stop before:

- changing allocation/cap/surplus/import policy;
- accepting an economy-specific exception;
- waiving unresolved IDs, duplicate keys, or blocking readiness;
- using an unverified patch module;
- changing mapping semantics locally;
- importing/publishing without explicit scope;
- clearing locks whose process state is uncertain.

## Handoff evidence

Record interpreter, process ID/command, commit, dirty state, source/template
paths, run mode/label/scope, start/end time, timing CSV, check counts, readiness
summary, and every import/recalculate/export iteration.
