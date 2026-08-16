# Parquet migration and reversible archive execution prompt

## Purpose

Execute work-queue item [44] across the connected LEAP repositories. Make
Parquet with Zstandard compression the default persistent format for tabular
data that is produced and consumed only by code. Retain formats required by
people, external systems, browsers, or published interoperability contracts.
After the migrated workflows pass end-to-end validation, identify superseded
files and place approved batches in checksummed ZIP archives that preserve
their original repository-relative paths.

This is an implementation task, not a new planning exercise. Work
autonomously through inventory, benchmarks, code changes, tests, workflow runs,
and archive-candidate preparation. Stop only at the explicit archive approval
gate or if a real semantic decision is required.

## Repositories in scope

- `C:\Users\Work\github\leap_initialisation`
- `C:\Users\Work\github\leap_mappings`
- `C:\Users\Work\github\leap_dashboard`
- `C:\Users\Work\github\leap_review_tools` — maintained web-app source
- `C:\Users\Work\github\leap_review_web_app` — regenerated deployment

Read every applicable `AGENTS.md` and the active work queue in each repository
before editing. Read `leap_mappings/docs/mappings_system.md` before changing a
mapping interface. Inspect Git status and current processes first; do not
overwrite or commit unrelated work. Commit verified changes at stable,
repository-specific checkpoints.

## Format policy

Use Parquet with Zstandard compression for an artifact when all of the
following are true:

1. it is tabular;
2. our workflows control both its producer and consumers;
3. it is not normally inspected or edited directly by a person;
4. it is not required in another format by LEAP, a browser, a colleague, or an
   external data provider; and
5. the benchmark and compatibility tests show no material regression.

Do not introduce new pickle files. Existing pickle intermediates are migration
candidates because they are Python-specific and unsafe to load when provenance
is uncertain.

Retain CSV/XLSX when it is a deliberate human deliverable, review table,
editable configuration, LEAP import/export workbook, or external interchange
file. Retain JSON/HTML where a browser consumes it. Do not rewrite externally
owned source inputs in place. A workflow may create a versioned Parquet cache
beside an immutable external input when the cache records the source hash and
can be regenerated.

Published cross-repository CSV contracts may migrate only after all producers,
consumers, packaged runtimes, tests, and manifests support the replacement.
During a bounded transition, readers may accept both formats, but new writes
must have one clearly identified authority.

## Success criteria

- Every tabular read/write site in the five repositories is inventoried and
  classified as `migrate`, `retain_human`, `retain_external`,
  `retain_browser`, `retain_contract_temporarily`, or `obsolete_candidate`.
- All machine-only artifacts that pass the benchmark use Parquet/Zstandard.
- Schemas, nulls, values, dtypes, keys, required ordering, and relevant
  floating-point tolerances are preserved.
- Unit, integration, full mapping, full initialisation, dashboard, review-tool,
  and deployed-runtime checks pass.
- Final human outputs are equivalent to the pre-migration baseline.
- Measured disk, read/write time, workflow time, and peak-memory changes are
  documented.
- Superseded originals are either retained or moved through the reversible
  archive procedure below; nothing is silently deleted.

## Phase 0 — Establish a safe baseline

1. Confirm no other agent or workflow is editing/running the relevant scope.
   Preserve unrelated dirty files and active worktrees.
2. Record the branch and commit of every repository, available disk space, the
   Python/runtime environments, and installed Parquet engine versions.
3. Run the focused existing test suites that cover current artifact contracts.
4. Select representative baseline workflows and save their manifests, row
   counts, schemas, hashes, timings, peak memory, and final human outputs.
5. Do not begin a full supply-reconciliation run casually. Follow its repository
   instructions: use the pinned Windows interpreter, an explicit unique run
   label, the supported parallel runner where appropriate, and the prescribed
   polling cadence.

## Phase 1 — Generate the format and dependency inventory

Build a machine-generated inventory for each repository. Search Python,
notebooks, JavaScript/TypeScript, configuration, tests, packaging scripts, and
documentation for CSV, CSV.gz, XLSX, pickle, Feather/Arrow, and Parquet reads or
writes. Also inventory existing artifact files without following junctions or
repository links.

For each logical artifact record:

- repository-relative path or path pattern;
- producer and all known consumers;
- source versus generated status;
- current format, compression, count, and total bytes;
- logical primary key and schema/dtype expectations;
- whether ordering is significant;
- human, browser, LEAP, external, or published-contract use;
- regeneration cost and provenance;
- proposed classification and reason;
- migration family and dependency order.

Write a concise Markdown summary for people and a machine-readable CSV or
Parquet inventory. Keep heavyweight trace details under diagnostics.

### Human-format decision register

Create `docs/parquet_human_format_decision_register.md` during the inventory
phase, with a machine-readable companion under the migration diagnostics. Use
it for every CSV/XLSX output whose human use is uncertain. Do not silently
classify an ambiguous output as machine-only merely because no current code
reference or recent modification is found.

Each register entry must contain:

- a stable decision ID and owning repository;
- exact path or path pattern and logical artifact family;
- producer, known code consumers, and how often it is produced;
- current total size and typical single-file size;
- whether the XLSX contains multiple sheets, formulas, formatting, comments,
  charts, or other semantics that Parquet cannot preserve directly;
- likely human audience and evidence for or against actual human use;
- a representative sample path or a compact preview;
- the agent's recommendation and expected storage/runtime benefit;
- the effect of conversion, including any proposed human-readable companion;
- status, user decision, decision date, and short rationale; and
- any exceptions within an otherwise similar artifact family.

Use these decision outcomes:

- `retain_csv_or_xlsx` — the human-readable file remains authoritative;
- `parquet_plus_human_summary` — detailed machine data becomes Parquet while a
  narrower CSV/XLSX summary remains for people;
- `parquet_with_on_demand_export` — Parquet is authoritative and an existing
  workflow can regenerate a human file when requested;
- `parquet_only` — confirmed machine-only;
- `retain_temporarily` — insufficient evidence; reconsider after runtime
  tracing or user review; and
- `retire_after_archive` — no continuing use, subject to the separate archive
  approval gate.

Group genuinely similar outputs into one family decision, but show exceptions
explicitly. Present the uncertain register entries to the user in small,
prioritised batches, starting with the largest potential savings and including
the recommendation rather than asking the user to investigate each file from
scratch. Pending entries default to `retain_temporarily`; they do not block
migration of clearly machine-only families and must never enter an archive
batch until decided.

## Phase 2 — Benchmark before standardising helpers

Benchmark representative small, medium, and largest candidates with their real
access patterns—not only full-table reads. Compare the current format against
Parquet/Zstandard for:

- file size;
- write time;
- cold and warm read time;
- selected-column and filtered reads;
- peak memory;
- dtype/null fidelity; and
- packaging/dependency cost in the web runtime.

Prefer Parquet when it materially improves storage or the actual processing
path without creating an unacceptable dependency or compatibility burden.
Record justified `retain` decisions where tiny CSVs, already-compressed files,
or row-streaming behavior do not benefit.

Implement the minimum shared storage helpers needed in each owning repository.
They must use explicit schemas where inference is unstable, write atomically,
record format/schema versions, and provide clear errors. Avoid a single hidden
global fallback that makes it unclear which file is authoritative.

## Phase 3 — Migrate artifact families atomically

Migrate one producer-and-consumer family at a time in this order unless the
inventory demonstrates a safer dependency order:

1. one large, internal supply-reconciliation diagnostic/cache family as the
   pilot;
2. remaining initialisation machine-only intermediates and existing pickles;
3. mapping conversion, lineage, audit-detail, and Common ESTO internals;
4. dashboard renderer-side staging data and caches;
5. review-tool server-side preparation data; and
6. the regenerated `leap_review_web_app` runtime.

For every family:

1. add equivalence tests before changing the authoritative writer;
2. update the producer and every consumer together;
3. preserve final human/browser/LEAP artifacts in their required formats;
4. update manifests, packaging, fixtures, docs, and dependency pins;
5. run focused tests and a representative workflow;
6. record measured before/after results; and
7. commit the verified family in its owning repository.

Do not mass-replace `.csv` with `.parquet`. Some code paths consume external
inputs or intentionally produce human review evidence. Classification controls
the change, not the filename alone.

## Phase 4 — Full-system validation

After all families pass focused checks:

1. run the complete mapping pipeline once, combining every outstanding
   work-queue validation that requires a full run so it is not repeated;
2. run the supported full initialisation/supply-reconciliation workflow with a
   unique output label and allow it to finish without interruption;
3. rebuild the dashboard from the migrated contracts;
4. run review-tool workbook/dashboard creation and cancellation/readiness
   checks;
5. regenerate the deployable web runtime from committed source rather than
   editing it directly; and
6. exercise the deployed runtime with its pinned Parquet dependency.

Compare pre/post final outputs using semantic checks, not raw file bytes:
keys, row counts, schemas, values within existing tolerances, mapping coverage,
conservation checks, workbook validation, dashboard chart inventories,
manifests, and browser-visible behavior. Investigate every discrepancy before
archiving anything.

## Phase 5 — Prepare the reversible archive proposal

Only after full-system validation, identify files and directories made
redundant by the migration and other clearly superseded generated runs. Do not
include tracked source code, unique source inputs, active outputs, Git metadata,
worktrees, junction targets, or evidence cited by unresolved reviews.

Prepare exact archive batches per repository. The proposed layout is:

```text
{repo}/archive/parquet_migration_YYYYMMDD/
    README.md
    manifest.csv
    manifest.sha256
    data_001.zip
    outputs_001.zip
    results_001.zip
```

ZIP members must retain their full repository-relative paths, such as:

```text
outputs/leap_exports/supply_reconciliation/.../old_file.csv
```

Use several bounded archives instead of one enormous ZIP. Split by top-level
directory and then by artifact family/run when necessary. Before creating an
archive, verify sufficient temporary disk space; ZIP creation can briefly need
both the originals and the complete archive.

The manifest must record, for every member:

- original repository and relative path;
- byte size, modification time, and SHA-256 before archiving;
- producing run/commit where available;
- reason it is superseded;
- replacement logical artifact/path;
- ZIP filename and exact member path;
- archive creation time and tool/version;
- post-extraction hash verification result; and
- restoration instructions.

Large ZIPs and archived data are local recovery assets and must be ignored by
Git. Commit only the small archive README/manifest if appropriate and if it
does not expose sensitive or machine-specific information.

### Mandatory approval gate

Present the exact batch manifest, total original size, predicted ZIP size,
available disk space, exclusions, and restoration procedure to the user.
Moving/removing originals from their live paths requires explicit approval for
the named batch. Approval for one batch does not authorize later-discovered
paths.

After approval:

1. create each ZIP from the original files without following reparse points;
2. test the ZIP and extract a sample—or all members where space allows—to a
   temporary directory;
3. verify member counts, paths, sizes, and SHA-256 hashes;
4. only then remove the approved originals from their live locations;
5. confirm active workflows resolve only the new authoritative artifacts;
6. rerun focused smoke tests; and
7. report the space recovered and exact restore command/procedure.

Never recursively delete a worktree parent or follow a junction. Git branches
and worktrees remain governed separately by P3-07 and are not data-archive
candidates.

## Required handoff

Provide:

- commits by repository;
- the inventory and benchmark report;
- the completed human-format decision register, with unresolved entries clearly
  separated from approved family decisions;
- migrated and deliberately retained artifact lists;
- focused and end-to-end validation results;
- before/after disk, runtime, and memory measurements;
- remaining compatibility readers and their removal condition;
- the exact archive batch proposal or completed archive manifests;
- unresolved semantic choices requiring human review; and
- a clean separation between this work and unrelated pre-existing changes.

Once implementation, full validation, archive disposition, and commits are
complete, move this prompt from `docs/prompts/` to `docs/archive/` and update
work-queue item [44] with final evidence.
