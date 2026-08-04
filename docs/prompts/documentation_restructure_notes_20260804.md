# Documentation restructure — notes for review

**Date:** 2026-08-04
**Status:** review notes, nothing changed yet.
**Why now:** both user-facing documents were last edited 2026-08-03 20:00, before
the input-folder redesign and before build sessions 1–3. Two of their statements
are now the opposite of what the tool does.

---

## 1. The problem with the current set

Three documents exist, and the two user-facing ones mix audiences badly:

| File | Intended reader | Actually contains |
|---|---|---|
| `leap_review_tools.md` | reference | colleague instructions *and* manifest schema, PyInstaller isolation, namespace-collision internals |
| `leap_review_tools_walkthrough.md` → `.docx` | narrative | how to run it *and* how to build a release, validate a manifest, roll back a version |
| `leap_review_tools_handover_20260803.md` | the next build session | correct for its purpose; leave alone |

A colleague who just wants a workbook has to skip past `git cat-file`, PyInstaller
spec files, and a section on why two executables exist. Meanwhile the one thing a
maintainer most needs — the `codebase` namespace collision — is documented *only*
in the handover, which reads like a temporary file and will eventually be archived.

## 2. Proposed structure

| File | Reader | Format |
|---|---|---|
| **`leap_review_tools_user_guide.md`** *(new)* | the colleague running the release. Assume no Python, no Git, no repositories, no knowledge of ESTO pipelines. | → **`.docx`**, the primary deliverable |
| **`leap_review_tools.md`** *(rewrite)* | the maintainer | `.md` only |
| `leap_review_tools_handover_20260803.md` | next build session | unchanged |

Retire `leap_review_tools_walkthrough.md`: its user-facing half becomes the user
guide, its build/release half moves into the maintainer reference. Do not leave it
in place as a third overlapping document.

---

## 3. Corrections needed — verified 2026-08-04

### 3.1 Two statements are now actively wrong

Both are in `leap_review_tools.md` §6 and are repeated in the walkthrough's
limitations section.

**(a) "The balance-diagnostics step is developer-mode only, for size reasons."**

No longer true. `balance-review-from-export` exists, and `esto_base_table` /
`ninth_projection_table` are declared data assets. Verified: the manifest
validates with 6 data assets totalling 407 MB, and both pinned paths match the
code's own defaults —

```
DEFAULT_BASE_TABLE_PATH       → leap_initialisation\data\00APEC_2024_low_with_subtotals.csv
DEFAULT_PROJECTION_TABLE_PATH → leap_initialisation\data\merged_file_energy_ALL_20251106.csv
```

The stated reason (288 MB + 26 MB is too large to ship) was overtaken when the
package accepted those tables.

> **Hold this one** until the frozen `balance-review-from-export` run passes. If
> it fails, a *narrower* limitation may be correct — but "developer-mode only for
> size reasons" is wrong either way.

**(b) "No upstream data refresh. The portable release renders from the comparison
data it is given; it never recomputes it."**

The opposite of what session 3 proved. `dashboard-from-export` recomputes
comparison data from balance exports through the mapping chain:

```
286,368 raw LEAP rows → 77,724 converted → 351,464 comparison rows → 648 charts
```

Delete this bullet. Replace with a note that the release computes comparison data
from LEAP exports, and that a pre-built comparison CSV can still be supplied via
`--comparison-data-path`.

### 3.2 Stale facts

| Documented | Actual |
|---|---|
| 2 commands (`balance-review`, `dashboard`) | 4, plus `list` |
| One executable + `_internal/` | Two — `mapping-chain/leap-mapping-chain.exe` has its own bundle |
| No `data/` folder in the package layout | Exists; carries the 407 MB of source tables |
| `input\TGT 0308.xlsx` (flat) | `input\leap balances exports\20_USA\...` |
| "output/ — one dated folder per run" | `output/<ECONOMY>/<tool>/`, with `run_records/<label>/` beside it |
| ~110 MB zipped / 278 MB extracted | ~617 MB package before data assets; larger with them — **re-measure, do not estimate** |

### 3.3 Missing entirely

- **The two-executable architecture and why it exists.** `leap_initialisation` and
  `leap_mappings` both name their top-level package `codebase` and both use
  absolute `codebase.x.y` imports, so one executable cannot hold both. Currently
  only in the handover §1. This belongs in the maintainer reference permanently —
  it is the highest-cost thing to rediscover.
- **The four traps session 3 recorded** (handover §5/§6): frozen `REPO_ROOT`
  resolution, staged-source omissions that validation cannot catch, `data_assets`
  not populated in the frozen entry point, and default-argument binding defeating
  a monkeypatch. These are maintainer reference material, not handover trivia.
- **`list`** as a command — it exists and nothing documents it.

### 3.4 Diagrams

Two of the walkthrough's seven Mermaid diagrams are wrong:

- the **architecture diagram** shows a single program — needs the second
  executable and the JSON subprocess boundary;
- the **balance-review flow** labels step 1 "developer mode only".

---

## 4. Specification for the user guide

**Audience:** a colleague who has been sent a ZIP. They model energy systems; they
do not write software. Assume they know what a LEAP Energy Balance export is and
what an economy code means. Assume nothing else.

**Absolute rule — none of the following may appear:** manifest schema, commit
pinning, PyInstaller, staging, `git`, `sys.path`, namespace packages, module
closures, SHA-256 as a concept to reason about, repository names, Python.

Where a technical thing has a user-visible consequence, state the consequence
only. "The tools record which files a run used, so a result can always be traced
back" — not "inputs are hashed into the run manifest".

### Suggested shape

1. **What these tools do** — one page, two tools, plain language. What question
   each one answers, and what you get out.
2. **Before you start** — extract the ZIP somewhere short; SmartScreen warning and
   what to click; Excel not required to *run*, only to open the workbook.
3. **Putting your files in** — the single folder, one sub-folder per economy,
   filename rules, `archive/`. A diagram of the folder tree. State plainly that
   the newest date wins.
4. **Checking what it can see** — `list`, and how to read its output. This is the
   "am I set up correctly?" step and should come before any real run.
5. **The two workflows**, each as a numbered step-by-step with the exact command
   to type and what appears while it runs:
   - balance review → the five-sheet workbook
   - dashboard → the HTML pages
6. **Understanding the balance-review workbook** — *the most valuable section, and
   the one that does not exist anywhere today.* One sub-section per sheet, what
   the colours mean (red mismatch, blue source, purple no comparator, yellow
   unavailable, green affected supply), and how to act on each. A reader should be
   able to open the workbook and know what to fix.
7. **Understanding the dashboard** — how to navigate pages, what the series are
   (LEAP vs ESTO vs 9th), what a difference means.
8. **Where results go** — the per-economy output tree; why nothing is overwritten;
   running several economies.
9. **When something goes wrong** — the three or four real messages a user will
   actually hit, each with what to do. Then: run `selfcheck`, read
   `validation_report.txt`, send a support bundle.
10. **Updating settings without a new version** — the `config/` folder, in one
    short paragraph, framed as "your modelling team may send you a replacement
    file".

### Diagrams (Mermaid, rendered to PNG by `scripts/convert_docs.py`)

- the input folder tree, with two economies side by side;
- balance exports → the two things you can produce (no internals — no mapping
  chain, no data tables, no executables);
- what a run does, as a simple linear flow: check inputs → run → results + record;
- the five sheets of the workbook and what each answers.

### Tone

Short sentences. Second person. No hedging. Every command in its own fenced block
so it can be copied. Prefer a screenshot-shaped description of what the user sees
over a description of what the program does internally.

---

## 5. Rebuild and verification

```bash
python scripts/convert_docs.py --docs-dir docs
```

Renders Mermaid to PNG and writes `docs/docx/`. Requires Pandoc and
`@mermaid-js/mermaid-cli`, both already installed on this machine.

Before calling the documentation done:

1. Every command in the user guide has been **run against the current frozen
   package** and its output matches what the guide says. Session 3's lesson
   applies to documentation too: a command that merely validates is not evidence.
2. Package size figures are measured from the current build, not carried over.
3. No term from §4's forbidden list appears in the user guide.
4. The `.docx` opens, and every diagram is present and legible.
5. The maintainer reference covers the two-executable decision and the four traps.

---

## 6. Sequencing

Do this **after** the frozen `balance-review-from-export` test settles, not
alongside it. That test can still change what §3.1(a) should say, and both touch
`docs/`. One documentation pass against a known-final state beats two passes and a
merge conflict.
