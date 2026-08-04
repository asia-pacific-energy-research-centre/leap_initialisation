# Handover: portable LEAP review tools — remaining work

**Date:** 2026-08-03
**Status:** implementation, frozen verification, documentation, and release
packaging completed 2026-08-04. Both export-first paths are shipping in the
same portable folder through two isolated executables.

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

**Completed 2026-08-04.** The bullets below are retained as the execution
record for the work now reflected in section 4 and the final section 6 entry.

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
| `balance-review-from-export` (LEAP export → workbook) | **done and frozen-tested** — 20_USA Target 2022 produced 358 comparison rows and a structurally valid five-sheet workbook from `TGT 0408.xlsx` |
| `data_assets` in the manifest | **done** — four mapping-chain artifacts plus the ESTO base table and 9th-edition projection table are staged with recorded sizes and SHA-256 values |
| ESTO vocabulary check | done |
| One input folder + per-economy outputs (`workspace.py`) | done, 11 tests |
| §3.1 mapping-chain worker (`leap_mappings`) | **done** — `codebase/portable_mapping_chain.py`, verified end-to-end against the real 12_NZ export (385,035 / 48,068 / 194,694 rows, matching §2 exactly). Committed `f2b1a92`. |
| §3.2 mapping-chain client (`leap_initialisation`) | **done** — `codebase/portable_release/mapping_chain_client.py`, locates/invokes the worker, real subprocess round-trip tested. Committed `d3ca156`. |
| §3.2 `dashboard-from-export` command | **done** — `commands.run_dashboard_from_export`, with the `--comparison-data-path` escape hatch. Verified with a mocked-chain unit test plus a real dashboard render off the real 12_NZ comparison data. Committed `9748dde`. |
| §3.4 manifest entries for the mapping chain | **done** (session 3, 2026-08-04). `RepositorySpec` gained `target` ("main"/"worker") and `source_key` fields (manifest.py); `repositories.leap_mappings_worker` is a second entry for the leap_mappings checkout (`source_key = "leap_mappings"`), staged as the real `codebase` package with its ~20-module closure (computed by an ast-based walk of absolute `codebase.*` imports from parse_leap_balance_export / convert_leap_results_to_esto / apply_common_esto_structure / portable_mapping_chain). Manifest validates clean: 42 source files (up from 15). |
| §3.3 two-PyInstaller-target builder | **done and verified end-to-end** (session 3). `build_release.py` freezes both targets from isolated cwd/spec/dist/work dirs (`_freeze_target`, generalised from the old single-target `_freeze`), copies the worker build to `package/mapping-chain/`, and runs the worker's `--self-test` alongside the main exe's `info`/`selfcheck`. A real `build(freeze=True)` now succeeds: main exe passes info/selfcheck, worker passes `--self-test` (`{"ok": true, "worker": "leap_mapping_chain"}`). Package: 3141 files, ~617 MB. |
| §3.5 `portable_main.py` / `developer_launcher.py` wiring for `dashboard-from-export` | **done** (session 3). `portable_main.py` has the `dashboard-from-export` subcommand, its guided-flow dispatch, and a `list` command (reuses the already-existing `workspace.describe_workspace`, which nothing called before). `developer_launcher.py` has `run_dashboard_from_export` and `build_context()` now populates `data_assets` (was a pre-existing gap — also needed by `balance-review-from-export`, see below). |
| Dashboard from balance exports, end to end | **done and verified** (session 3, 2026-08-04). `leap-review-tools.exe dashboard-from-export --economy 20_USA` succeeds against a real, freshly staged 20_USA REF+TGT export: 286,368 raw LEAP rows -> 77,724 converted -> 351,464 comparison rows -> 648 charts, `dashboards/index.html` written. This is the whole point of §3's remaining work, now actually proven rather than unit-tested with mocks. See §6 for the four real bugs this surfaced and fixed along the way. |
| Balance review from a balance export, end to end | **done and verified** (session 4, 2026-08-04). The frozen executable generated diagnostics and `balance_review_20_USA_tgt_2022.xlsx` directly from `TGT 0408.xlsx`: 358 rows, 179 mismatches, 14 reference-unavailable rows, 165 matches, zero allocation-required rows, and no formula-error cells. |
| Documentation and distribution | **done** (session 4). Reference and walkthrough Markdown were updated, Word versions regenerated and visually checked, and the distribution ZIP rebuilt from the verified package. |

`leap_dashboard`: `common_esto_dashboard_portable.py` + tests — done.
`leap_mappings`: `codebase/portable_mapping_chain.py` added and tested (§3.1, see above).

The shipped ZIP at
`leap_initialisation/release_build/distribution/leap-review-tools-0.1.0.zip`
was rebuilt after both export-first commands passed their frozen end-to-end
checks. Its identity is recorded in the final section 6 entry.

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

#### Third channel: the previous session's transcript

Claude Code writes every session to JSONL continuously, so a previous session's
full transcript survives even if it crashed before writing anything down:

```text
C:\Users\Work\.claude\projects\<project-slug>\<session-uuid>.jsonl
```

The session that produced this handover is
`C--Users-Work-github-leap-mappings--claude-worktrees-zen-pike-39adbf\4484ea95-b3c4-4956-9f36-9fdd7c8b3a99.jsonl`.
Find later ones by modification time:

```bash
ls -t "C:/Users/Work/.claude/projects"/*/*.jsonl | head -5
```

**Never read one of these whole.** They run to several megabytes and reading one
would consume more budget than the work it was meant to inform. Treat it as a
last resort, and only ever `grep` it for something specific:

```bash
grep -o '"text":"[^"]\{0,400\}error[^"]\{0,400\}"' <transcript>.jsonl | tail -20
```

Use it to answer a precise question — "what exactly did the PyInstaller run
print?", "why was that approach abandoned?" — that §6 and the Git log cannot.
For ordinary state reconstruction, §6 and the log are sufficient and far
cheaper.

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
- **The staged/frozen package builds from the manifest's *pinned commit*, not
  your working tree.** Editing `leap_initialisation` or `leap_mappings`
  source and re-running `build()` silently builds the OLD code until you bump
  `repositories.<key>.commit` in `config/portable_release_manifest.toml` to
  your new HEAD. Session 3 lost real time to this twice: fixed a crash,
  rebuilt, got the *same* crash, because the pin was still on the pre-fix
  commit. **Bump the pin and rebuild after every source commit that touches a
  staged file, every time, immediately** — don't batch several fixes before
  re-pinning, or you can't tell which fix actually worked.
- **`validate_release_manifest` does not check that a staged file's imports
  are all themselves staged.** It checks declared command names against
  `IMPLEMENTED_COMMANDS` (the *live* checkout's `commands.py`, not the pinned
  blob) and that allowlisted paths exist at the pinned commit — it does not
  parse imports. `commands.py`'s `from codebase.portable_release import
  workspace` and `dashboard-from-export`'s need for `mapping_chain_client`
  both went unstaged for two sessions without a single validation error;
  only an actual `build(freeze=True)` + `selfcheck` (or, worse, an actual run)
  surfaces this. **Validation passing is not proof a command works** — only a
  real frozen run is.
- **A Python function's default-argument value is bound once, at import
  time — not read live from the module global it references.** Reassigning
  `some_module.SOME_CONSTANT` after import does **not** change
  `some_function()`'s behaviour if `SOME_CONSTANT` was captured as a default
  parameter value (`def f(x=SOME_CONSTANT):`), because the default is
  evaluated once and stored in `f.__defaults__`. Tried monkeypatching
  `apply_common_esto_structure.OUTLOOK_MAPPINGS_PATH` from
  `portable_mapping_chain.py` before calling
  `run_common_esto_comparison_fast_path` — silently did nothing, because the
  constant is only read live *inside a function body* (global lookup at call
  time), never as another function's *default parameter value* three call
  frames down (`build_wide_year_output`'s own default, bound at its own
  def-time). The actual fix had to be a real parameter threaded through
  (commit `a7a21ba` in `leap_mappings`).
- **A frozen PyInstaller module's `Path(__file__).resolve()` does not sit
  inside a real checkout.** Several `leap_mappings` `mapping_tools` modules
  compute `REPO_ROOT` by walking up from `__file__` looking for
  `config/outlook_mappings_master.xlsx`, or by a fixed `.parents[N]` — both
  assume a real checkout on disk and either raise or silently resolve
  somewhere wrong when frozen. The working fix in every case was a
  `sys._MEIPASS` fallback (PyInstaller sets this to the frozen bundle's own
  root at runtime) plus, for modules that read an actual file at import time
  (the `config/datasets/*.csv` registries), bundling those files into the
  frozen build via PyInstaller `datas=`. If a future module in the worker's
  closure adds its own `REPO_ROOT`/`_find_repo_root`, it needs the same
  treatment — grep for `_find_repo_root\|REPO_ROOT = Path(__file__)` in
  `leap_mappings/codebase/mapping_tools/` before assuming a frozen run is
  safe.

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

### 2026-08-04 00:15 local (session 1) — §3.1 and §3.2 completed, no blockers hit

- Items: §3.1 (mapping-chain worker), §3.2 (client + `dashboard-from-export`
  command), part of §3.4 (manifest entries for the roles §3.2 needed).
- Everything attempted this session succeeded; nothing is blocked. Full detail
  is in §4 above rather than repeated here.
- One judgement call worth recording: `run_dashboard_from_export`'s
  `_input_records` describes the whole export directory
  (`describe_directory_files(..., patterns=("*.xlsx",))`), matching how
  `run_balance_review_from_export` records its inputs — not a single file,
  since the mapping chain reads every `.xlsx` in the folder (REF and TGT).
- Another: the manifest's `DENIED_PATH_SEGMENTS` blocks any `dest` path
  containing `data/` or `results/` as a path *segment* (not just at the
  root) — the new data-asset `dest` values had to move from
  `data/mapping_chain/...` to `mapping_chain/...`. If a future session adds
  more data assets, check `path_safety_problems` in `manifest.py` before
  picking a `dest` prefix rather than re-discovering this by test failure.
- Moved on to: updating §4, then scheduling session 2 for §3.3 (the
  two-PyInstaller-target builder) and the rest of §3.4/§3.5.
- Checked `list_scheduled_tasks` before finishing: `leap-review-tools-build-2`
  (fires 2026-08-04 03:41 local), `-3` (08:41), and `-4` (13:41) were **already
  scheduled and enabled** — not created by this session. Per the governing
  instructions this session did not create another; those three will fire on
  their existing schedule. Whoever pre-created the full chain, note for
  session 4: do not schedule a session 5 unless §3 is still incomplete.

### 2026-08-04 08:45 local (session 3) — session 2 appears not to have run

- Before starting, `git log` in all three repos showed nothing past session
  1's commits (`1e49e8b` in `leap_initialisation`, `f2b1a92` in
  `leap_mappings`) despite `leap-review-tools-build-2` having been scheduled
  for 03:41 and this session (build-3) firing at its scheduled 08:41. No
  concurrency conflict (the concurrency-guard check found the last commit
  ~8.5 hours old, well past the 45-minute threshold) — session 2 simply left
  no trace in git, and no §6 entry either. Possible causes not investigated
  (out of scope for this session): the task didn't fire, or it fired and
  produced no committable output before running out of budget. Worth a
  maintainer look if this recurs.
- Proceeded as if session 2 never ran: started §3.3 (first incomplete §3
  item) directly.

### 2026-08-04 ~11:00 local (session 3) — §3.3, §3.4, §3.5 completed and verified end to end; no blockers left standing

- Items: §3.3 (two-PyInstaller-target builder), the rest of §3.4 (manifest
  `target`/`source_key` fields, `leap_mappings_worker` closure), §3.5
  (`portable_main.py`/`developer_launcher.py` wiring for `dashboard-from-export`
  and `list`, `data_assets` population in both). Then went further than the
  plan asked and actually ran `dashboard-from-export` against a real frozen
  build with a real 20_USA export, because a manifest that merely validates
  is not evidence a command works (see §5's new trap on this) — and that
  real run surfaced four bugs no test or validation pass had caught:
  1. **Missing worker closure imports crashed the frozen worker at import
     time.** `leap_mappings`' `_find_repo_root()` (four modules) walks up
     from `__file__` for a marker file that doesn't exist inside a
     PyInstaller bundle. Fixed with a `sys._MEIPASS` fallback in those four
     plus five more modules whose `REPO_ROOT` silently resolved wrong
     without raising (`dataset_registry.py` and its four dependents) —
     `leap_mappings` commit `8bd0fb6`.
  2. **Two staged-source omissions.** `commands.py` imports `workspace`;
     `dashboard-from-export` needs `mapping_chain_client` — neither was in
     `repositories.leap_initialisation.paths`, so the frozen build never had
     them despite `validate_release_manifest` passing (it doesn't parse a
     staged file's own imports). Only `selfcheck` on the real frozen build
     caught this — `leap_initialisation` commit `bc3975d`.
  3. **`data_assets` was never populated in the frozen entry point.**
     `build_portable_context()` (portable_main.py) built `config_assets` but
     not `data_assets`, so `context.require_data_asset(...)` always failed
     in a portable run. No existing test caught it because every existing
     frozen-package test exercises `balance-review` or plain `dashboard`,
     neither of which touches a data asset — `leap_initialisation` commit
     `2429da8`. (The equivalent gap in `developer_launcher.build_context()`,
     noted as a pre-existing issue in §4 since session 1, was fixed in the
     same pass, commit `bd575bc`.)
  4. **The mapping-chain fast path silently needed a file that isn't there
     when frozen.** `run_common_esto_comparison_fast_path` calls
     `build_wide_year_output()` without overriding `outlook_mappings_path`,
     so it defaulted to `OUTLOOK_MAPPINGS_PATH` — a module constant computed
     from the now-`_MEIPASS`-based `REPO_ROOT`, so a plausible-looking but
     wrong path. First tried monkeypatching the module constant from
     `portable_mapping_chain.py`, which silently did nothing (see §5's new
     trap on default-argument binding) — the real fix threads an explicit
     `outlook_mappings_path` parameter through, `leap_mappings` commit
     `a7a21ba`.
  - Every fix required committing, re-pinning the manifest to the new
    commit, and a full two-target rebuild (~4–6 minutes each) before it
    could be re-tested — staging reads the pinned Git blob, not the working
    tree (see §5). Seven rebuild cycles total this session.
  - `dashboard-from-export --economy 20_USA` now succeeds end to end against
    the frozen package: 286,368 raw LEAP rows -> 77,724 converted ->
    351,464 comparison rows -> 648 charts -> `dashboards/index.html`.
  - Not attempted this session (deliberately, to leave a clean stopping
    point rather than start a fifth unrelated sub-investigation):
    `balance-review-from-export`'s manifest entries and frozen test (§3.5's
    remaining scope) — it needs `esto_base_table`/`ninth_projection_table`
    data-asset roles declared, which needs a decision about which source
    files to pin (not obviously the same shape as the mapping-chain data
    assets); and `docs/docx/` regeneration
    (`python scripts/convert_docs.py --docs-dir docs`) and the architecture
    diagram update, both still open per the original §3.5 bullet.
  - Moved on to: updating §4 and this entry, then handing off to session 4
    for `balance-review-from-export` manifest work and the docs pass. §3's
    dashboard-from-export path (the actual point of this whole handover) is
    now done, tested, and proven against a real export — session 4 should
    treat the remaining items as cleanup, not as unblocking anything load-bearing.
  - One more thing the pin bump surfaced: five tests in
    `tests/test_portable_release_package.py` still asserted the pre-`a4dd7e0`
    flat `output/<tool>_<label>/` layout (that commit moved to
    `output/<economy>/<tool>/` with manifests under a `run_records/<label>/`
    subfolder, but only updated the golden test in the *other* file). They
    passed only because the stale pin kept old code staged; fixed all five
    plus a `balance-review`/`balance_review` (hyphen vs underscore
    `workspace.BALANCE_REVIEW_DIRNAME`) mixup in the same assertions —
    `leap_initialisation` commit `af3edd1`. Full suite for this area now
    green: `test_portable_release.py`, `test_portable_release_package.py`,
    `test_mapping_chain_client.py`, `test_portable_release_workspace.py`,
    `test_dashboard_from_export.py` all pass.

### 2026-08-04 (session 4) — balance export path frozen-tested; handover completed

- Declared and packaged the two source tables required by balance diagnostics:
  `00APEC_2024_low_with_subtotals.csv` as `esto_base_table` and
  `merged_file_energy_ALL_20251106.csv` as `ninth_projection_table`. The frozen
  release manifest records each source, byte size, and SHA-256.
- Added the remaining configuration/runtime closure and wired
  `balance-review-from-export` through both `portable_main.py` and
  `developer_launcher.py`. Two frozen-only routing defects found by the real
  run were fixed: the packaged mapping workbook is now passed into the pair
  loader, and the canonical loader temporarily uses that same packaged path.
- Verified the real developer path against 20_USA `TGT 0408.xlsx` (358 rows,
  182 mismatches) and then the rebuilt frozen executable (358 rows, 179
  mismatches, 14 reference-unavailable, 165 matches, zero allocation-required,
  no formula-error cells). The different warning totals reflect the frozen
  release's pinned canonical workbook versus the dirty live mappings checkout;
  they are QA findings, not workflow blockers.
- Verification suite: 130 passed, 5 skipped. The skips are the historical
  `TGT 0308.xlsx` golden fixture, which has moved to the archive; the current
  real checks use `TGT 0408.xlsx`.
- Relevant `leap_initialisation` commits:
  `73b9c70`, `f362da6`, `8212746`, `61af405`, `8fca627`, `293b6ff`,
  `4e49ec7`, `19a57bc`, and `1abe345`.
- Updated the reference and walkthrough, including the two-executable
  architecture and both export-first commands; regenerated and visually
  checked the Word walkthrough; rebuilt and inspected the distribution ZIP.
  The clean archive contains 3,146 files, is 309,749,572 bytes, has no CRC
  failures or private/cache/generated-run content, and has SHA-256
  `4ef2919cc798a657732ee8519c2a04d726e33a9319ff8bfbcd0a0d54b3aa262f`.
- **No implementation work remains from section 3.** Any later mapping, source
  table, command-contract, or code change requires a newly versioned and
  reverified release rather than silently replacing this `0.1.0` artifact.
