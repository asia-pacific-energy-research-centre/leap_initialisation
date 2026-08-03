# Handover: portable LEAP review tools — remaining work

**Date:** 2026-08-03
**Status:** balance-review path complete and shipping; dashboard-from-exports
path designed, proven, and not yet built.

Read `docs/leap_review_tools.md` for the reference and
`docs/leap_review_tools_walkthrough.md` for the narrative. This file only covers
what is *left*, and the one architectural decision that governs it.

---

## 1. The decision that governs everything left

**`leap_initialisation` and `leap_mappings` both name their top-level package
`codebase`, and both use absolute `codebase.x.y` imports.**

- balance-review needs `leap_initialisation.codebase` (38-module closure)
- the dashboard chain needs `leap_mappings.codebase` (20-module closure)

They cannot share one `sys.path`, and PyInstaller flattens modules into a single
namespace, so **one executable cannot contain both**.

### Agreed approach: two executables in one package

```text
leap-review-tools-0.1.0/
  leap-review-tools.exe          main CLI; bundles leap_initialisation.codebase
                                 + the three flat leap_dashboard modules
  _internal/                     its runtime
  mapping-chain/
    leap-mapping-chain.exe       bundles leap_mappings.codebase only
    _internal/                   its runtime
  config/  data/  input/  output/  logs/  licenses/
```

The main executable invokes `mapping-chain/leap-mapping-chain.exe` as a
subprocess, passing a JSON job on stdin and reading a JSON result from stdout.
Isolation is then guaranteed by construction rather than by discipline.

Rejected alternatives, with reasons, so this is not relitigated:

- **Rename one repo's package** (`leap_mappings.codebase` → something else).
  One clean executable, but it rewrites the import line of every module in that
  repository — production code well outside a productisation task.
- **`sys.modules` swapping / custom import finders.** Fragile, and it defeats
  PyInstaller's static analysis, so the modules would not be bundled at all.
- **Keep the dashboard on comparison-data input.** No packaging change, but the
  colleague still needs a ~1 GB CSV from the maintainer, which is the problem
  this work exists to remove.

---

## 2. The dashboard chain is proven — do not re-derive it

Run on 2026-08-03 against `12_NZ`, in a process with only `leap_mappings` on
`sys.path`. Every number below is measured, not estimated.

```text
1. parse_leap_balance_dir           385,035 raw LEAP rows
2. run_conversion                    48,068 converted ESTO rows (3.5 MB)
3. run_common_esto_comparison_fast_path
                                    194,694 comparison rows
                                    common_esto_comparison_data.csv, 46 MB
```

The exact call sequence, with the arguments that worked:

```python
from codebase.mapping_tools.parse_leap_balance_export import parse_leap_balance_dir
from codebase.mapping_tools.convert_leap_results_to_esto import run_conversion
from codebase.mapping_tools.apply_common_esto_structure import (
    NINTH_PROJECTION_START_YEAR, run_common_esto_comparison_fast_path)

df = parse_leap_balance_dir(export_dir, raw_leap_path, economy_code="12_NZ")

run_conversion(
    leap_results_path=raw_leap_path,
    relationships_path=REL / "energy_balance_relationships.csv",
    output_path=converted_path,
    mapping_workbook_path=CONFIG / "outlook_mappings_master.xlsx",
    rollup_audit_path=work / "leap_source_rollup_audit.csv",
    target_values_path=REL / "esto_results_exact_rows.csv.gz",
    lineage_output_path=work / "lineage.csv.gz",
    source_branch_fallback_rules_path=CONFIG / "source_branch_fallback_rules.csv",
    all_demand_components_path=CONFIG / "all_demand_aggregated_components.json",
    preflight_audit_dir=work,
)

run_common_esto_comparison_fast_path(
    source_paths={
        "LEAP":  converted_path,
        "NINTH": REL / "ninth_results_converted_to_esto.csv.gz",
        "ESTO":  REL / "esto_results_exact_rows.csv.gz",
    },
    common_rows_path=CE / "common_esto_rows.csv",
    output_dir=work,
    default_economy="12_NZ",
    active_component_abs_tolerance=0.0,
    ninth_projection_start_year=NINTH_PROJECTION_START_YEAR,
    economies=["12_NZ"],
    run_id=..., run_timestamp_utc=...,
)
```

Then feed `work / "common_esto_comparison_data.csv"` and
`common_esto_rows.csv` to
`leap_dashboard.codebase.common_esto_dashboard_portable.render_common_esto_dashboard`,
which already exists and is tested.

### Why only part of the mapping pipeline is needed

Stage 1 (relationships), Stage 2 (structure), the ESTO exact-row extraction and
the 9th-edition conversion are all functions of the mapping workbook and the
source tables — **not** of any model run. Their outputs are therefore bundled as
pre-built artifacts, and only the export-dependent tail runs at run time.

| Pre-built artifact | Size | From |
|---|---|---|
| `energy_balance_relationships.csv` | 8.3 MB | `leap_mappings/results/mapping_relationships/` |
| `common_esto_rows.csv` | 5.0 MB | `leap_mappings/results/common_esto/` |
| `esto_results_exact_rows.csv.gz` | 24.5 MB | `leap_mappings/results/mapping_relationships/` |
| `ninth_results_converted_to_esto.csv.gz` | 55.2 MB | same |

Plus config: `outlook_mappings_master.xlsx`,
`all_demand_aggregated_components.json`, `source_branch_fallback_rules.csv`.

**These are regenerated outputs.** Pin them in the manifest as `data_assets`
with `allow_untracked = true` (they are gitignored) and rely on the recorded
SHA-256 for identity. A release must be rebuilt when the mapping workbook
changes, because these go stale — say so in the release notes.

---

## 3. Work remaining, in order

### 3.1 `leap_mappings`: add the chain worker *(owner repo)*

New `codebase/portable_mapping_chain.py` — a small module with a `__main__`
entry that reads a JSON job (`{economy, export_dir, artifacts{}, config{},
work_dir}`), runs the three steps above, and prints a JSON result
(`{comparison_data_path, common_rows_path, raw_leap_rows, converted_rows,
comparison_rows, scenarios[], years[], notes[]}`). Errors become
`{"error": "..."}` with a non-zero exit.

Keep it thin: sequencing and I/O only, no mapping logic. Test it in
`leap_mappings/tests/` against `12_NZ` using the numbers in §2.

A module deleted during this session,
`leap_initialisation/codebase/portable_release/dashboard_pipeline.py`, was an
earlier attempt at this that assumed flat imports would work. It will not —
`convert_leap_results_to_esto` imports `codebase.mapping_tools.source_branch_preflight`
absolutely. Recover it from Git history for the docstrings only if useful; the
import strategy in it is wrong.

### 3.2 `leap_initialisation`: the caller side

New `codebase/portable_release/mapping_chain_client.py`:

- locate the worker (`mapping-chain/leap-mapping-chain.exe` beside the main exe
  in portable mode; `sys.executable -m codebase.portable_mapping_chain` with
  `cwd=leap_mappings` in developer mode);
- invoke it, stream its output into the run log, parse the JSON result;
- surface a failed chain as a plain-language error, not a traceback.

Then a `dashboard` command that: resolves the economy's export folder →
mapping chain → `render_common_esto_dashboard` → `output/<ECONOMY>/dashboard/`.
Give it a `--comparison-data-path` escape hatch so a supplied CSV still works.

### 3.3 Builder: two PyInstaller targets

`build_release.py` currently freezes one spec. It needs to freeze the worker
too, into `mapping-chain/`, and verify both (`info`, `selfcheck`, and a
worker `--self-test`). Keep both builds in isolated subprocesses run from a
directory containing none of the repositories — that isolation is why the
current build is clean, and the reason is recorded in the module docstring.

### 3.4 Manifest

Still to declare: the 38-module diagnostics closure and the 20-module mapping
closure (per executable — the manifest needs a `target` or `executable` field on
each source entry), the four pre-built artifacts, the ESTO/9th source tables,
the new commands, and the `list` command.

### 3.5 Wiring, tests, rebuild, docs

- `portable_main.py`: `list`, `dashboard`, `balance-review-from-export`, and the
  guided flow for each.
- `developer_launcher.py`: same commands, plus `data_assets` wiring (it does not
  populate them yet).
- Tests: mapping-chain client (mocked worker + one real run), dashboard command,
  per-economy layout for the dashboard, and package hygiene for two executables.
- Rebuild, re-verify, re-zip; expect roughly 133 MB + ~90 MB artifacts + ~25 MB
  second runtime ≈ **250 MB zipped**.
- Regenerate `docs/docx/` — `python scripts/convert_docs.py --docs-dir docs`.
  The walkthrough's balance-review diagram is current; its architecture diagram
  needs the second executable adding.

---

## 4. State of the tree

Committed and verified in `leap_initialisation` (all on `master`):

| Area | State |
|---|---|
| Release manifest + validator, builder, developer launcher, runtime, validation, provenance, support bundle | done |
| `balance-review` (diagnostics folder → workbook) | done, frozen, golden-tested |
| `balance-review-from-export` (LEAP export → workbook) | code done; needs manifest entries, wiring, and a frozen test |
| `data_assets` in the manifest | done |
| ESTO vocabulary check | done |
| One input folder + per-economy outputs (`workspace.py`) | done, 11 tests |
| Dashboard from balance exports | **not built** — this document |

`leap_dashboard`: `common_esto_dashboard_portable.py` + tests — done.
`leap_mappings`: nothing changed yet; §3.1 is the first change it needs.

The shipped ZIP at
`leap_initialisation/release_build/distribution/leap-review-tools-0.1.0.zip`
predates the input-folder redesign. It still works, but its `input/` layout is
the old one; rebuild before distributing.

---

## 4a. START HERE — unattended build plan

The maintainer is asleep. Work through §3 autonomously across four scheduled
sessions, using whatever budget each usage window allows.

Local time is **UTC+0900**. This plan was written at 2026-08-03 23:35 local.

| Session | Fires (local) | Budget |
|---|---|---|
| 0 | 23:35, 3 Aug (already run) | remainder of the current window (~50%) |
| 1 | 03:40, 4 Aug | full window |
| 2 | ~08:40, 4 Aug | full window |
| 3 | ~13:40, 4 Aug | full window |
| 4 | ~18:40, 4 Aug | full window |

### Sessions schedule their own successor

Only session 1 is pre-created. **Each session creates the next one itself**,
because only the running session knows when it actually finished and how much
budget it consumed — a fixed timetable set in advance drifts as soon as one
session runs long or short.

At the **start** of each session, note the session number from the scheduled
task's prompt. Before finishing, if that number is **less than 4**:

1. create a one-time scheduled task named `leap-review-tools-build-<n+1>`,
   firing **5 hours from now**, with the same prompt but the session number
   incremented;
2. record in §6 that you scheduled it, with the fire time.

If the number is 4, do not schedule another; instead append a short summary to
§6 saying the unattended run is finished and what remains.

If a session finds §3 fully complete, do not schedule a successor — record that
in §6 and stop.

### The rule that matters most

**Never stop at a blocker. Record it and move to the next item.**

If a step cannot be completed — a build fails, a dependency will not resolve, a
test cannot be made to pass, a decision needs the maintainer — then:

1. append an entry to §6 (Blockers for review) saying what was attempted, the
   exact error, and what you think it needs;
2. commit that;
3. **go to the next item in §3** and keep working.

A session that halts on the first obstacle wastes an entire window. Partial
progress plus a clear note is far more useful than a clean stop. Only stop early
if continuing would damage the repositories (see §5 traps) or if every remaining
item is blocked.

### Sessions cannot see each other

Each scheduled run starts fresh, with **no memory of any previous run and no
access to its chat log**. This document and the Git history are the only
channels between sessions. Anything a session learns and does not write down is
lost.

So every session must, before doing anything else, reconstruct state from both:

```bash
git -C C:\Users\Work\github\leap_initialisation log --oneline -30
git -C C:\Users\Work\github\leap_mappings       log --oneline -15
git -C C:\Users\Work\github\leap_dashboard      log --oneline -10
```

Read §6 **and** that log. They are deliberately redundant: §6 is richer but
depends on a previous session having had the budget to write it, whereas the log
records what actually landed even if a session died mid-item. Where the two
disagree, believe the log and correct §6.

### Each session

1. Read this document, then §3 for the ordered work list, then §6 for what
   previous sessions already found blocked — do not re-attempt a known blocker
   unless a later change plausibly unblocks it.
2. Work down §3 from the first incomplete item.
3. Commit in small, verified steps. Stage **only** files you authored; other
   agents work in these checkouts (§5).
4. Keep §4 (state of the tree) and §6 current as you go, so the next session
   starts accurate. Do this *as you finish each item*, not at the end — a
   session that runs out of budget mid-item must still leave a truthful record.
5. When the budget runs low, stop cleanly: commit, update §4 and §6, and let the
   next scheduled session continue.

### Keeping each session cheap

Every turn re-sends the whole conversation, so a long session costs far more per
turn than a short one. That is why this is four separate sessions rather than
one: each starts from this document at a fraction of the per-turn cost.

Within a session: targeted `Grep` and ranged `Read` rather than whole modules;
pipe long command output through `tail`; run one test module at a time rather
than re-running suites to double-check; batch independent tool calls into one
turn; do not spawn subagents for work you already have context for.

### Why a fresh session is the main lever

Every turn re-sends the whole conversation. In a long session that is by far the
dominant cost — far more than any single file read or test run. A fresh session
carrying only this handover starts at a fraction of the cost per turn and stays
cheap for much longer.

That is the main reason this document exists in the detail it does: it is the
mechanism for ending a session cheaply and restarting at full speed, rather than
keeping an expensive one alive.

### Why a fresh session is the main lever

Every turn re-sends the whole conversation. In a long session that is by far the
dominant cost — far more than any single file read or test run. A fresh session
carrying only this handover starts at a fraction of the cost per turn and stays
cheap for much longer.

That is the main reason this document exists in the detail it does: it is the
mechanism for ending a session cheaply and restarting at full speed, rather than
keeping an expensive one alive.

Ranked levers, most effective first:

1. **End a long session; restart from a handover.** Removes the re-sent context.
2. **Match the model to the task.** Use the cheaper model for scaffolding,
   mechanical edits, and test loops; reserve the strongest one for the
   architecture-sensitive work (§1 and §3.3 here).
3. **Do not spawn subagents or workflows for this work.** Each one starts cold
   and re-derives context that is already in hand.
4. **Read narrowly.** Targeted `Grep` and ranged `Read` rather than whole large
   modules; pipe long command output through `tail`/`head`.
5. **Run focused tests.** One test module at a time; do not re-run a suite to
   confirm something the tool already confirmed.
6. **Batch independent tool calls** into a single turn.

---

## 5. Traps worth keeping

- **Two `codebase` packages.** §1. The single most expensive thing to rediscover.
- **PyInstaller must run in a subprocess from a neutral directory.** Run
  in-process from a checkout it silently baked the live `codebase` into the
  executable, which then failed on a machine with no LEAP COM API. `selfcheck`
  exists to catch a recurrence.
- **Relative input paths.** The repositories resolve them against their own
  repository root, which inside a package is `_internal`. `commands._resolve_user_path`
  pins them to the working directory first; do not bypass it.
- **`ESTO unique flows and products` is stale.** It says `16.01.02` where the
  live mapping uses `16.01.99`, has a double-space `Paraffin  waxes`, and omits
  the LNG and `09.13*` hydrogen flows. Read `leap_combined_esto` instead.
- **Combined categories are not source rows.** Hyphen ranges
  (`04-05 ...`), comma lists (`09.01.01,09.02.01 ...`) and `(including own use)`
  rollups are mapping-layer constructs. Excluding them is what took the ESTO
  vocabulary check from six false positives to zero.
- **A results update is not required for a review workbook.** The diagnostics
  step reads a LEAP export directly. Documented wrongly once already.
- **Concurrent Codex activity in these checkouts.** A cherry-pick was mid-conflict
  during this session. Stage only your own files; check `git status` first.

---

## 6. Blockers for review

Append here whenever something cannot be completed. Do not stop working — record
and move on (§4a). Newest last.

Format:

```text
### <date time local> — <short title>
- Item: <which §3 step>
- Attempted: <what was tried>
- Error: <exact message, trimmed>
- Needs: <what would unblock it — a decision, a dependency, a rebuild>
- Moved on to: <next item>
```

_(no blockers recorded yet)_
