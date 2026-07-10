# LEAP Mappings Prompt Folder AGENTS Review Prompt

## Short Version

You are working in:

`C:\Users\Work\github\leap_mappings`

Review the active prompts in `docs/prompts/`, create a prompt-folder guide at
`docs/prompts/AGENTS.md`, fill it with a current prompt inventory, flag invalid
or stale prompts, recommend the best tackling order, and archive prompts whose
work is already complete.

Use the `leap_initialisation` prompt guide as the model:

`C:\Users\Work\github\leap_initialisation\docs\prompts\AGENTS.md`

## Objective

Create a maintainable `docs/prompts/AGENTS.md` for `leap_mappings` so future
agents can tell:

- which prompts are active;
- what each prompt is for;
- whether each prompt is valid, stale, complete, or invalid;
- which prompt should be tackled next;
- when completed prompts must be moved out of `docs/prompts/`;
- how to write better prompts for this repository.

## Before Starting

1. Read `C:\Users\Work\github\leap_mappings\AGENTS.md`.
2. Read `C:\Users\Work\github\leap_mappings\docs\mappings_system.md`.
3. Run `git status --short` and preserve unrelated changes.
4. List active prompt files:

   ```powershell
   Get-ChildItem -Path docs/prompts -File
   ```

5. List archived prompt files:

   ```powershell
   Get-ChildItem -Path docs/archive -File
   ```

6. Check whether `docs/archive/` is ignored by `.gitignore`. If it is ignored,
   force-add only the prompt archive files that belong to this task.

## Scope

In scope:

- Create `docs/prompts/AGENTS.md` if it does not exist.
- If it already exists, update it instead of replacing useful content.
- Review every file currently under `docs/prompts/`.
- Record each prompt's basic details, status, prerequisites, and notes before
  use.
- Identify invalid prompts, stale prompts, duplicate prompts, completed prompts,
  and prompts that should be split.
- Recommend a practical tackling order for the active prompts.
- Move completed prompts from `docs/prompts/` to `docs/archive/` when there is
  clear evidence that the work is already done.

Out of scope:

- Do not execute the implementation prompts.
- Do not fix mapping pipeline code while doing this review.
- Do not make data, workbook, or mapping changes.
- Do not rewrite prompt content unless needed to correct the prompt inventory or
  archive status.

## Required Review Method

For each active prompt:

1. Read the prompt fully.
2. Identify its task type:
   - implementation;
   - verification;
   - long-running execution;
   - investigation;
   - planning;
   - documentation;
   - cleanup/archive.
3. Check referenced files, scripts, docs, and outputs exist.
4. Search the current code/docs for the main functions, filenames, flags, or
   outputs mentioned in the prompt.
5. Classify the prompt status:
   - `Valid, active`
   - `Valid, active, high value`
   - `Partially stale, still useful`
   - `Complete; archived`
   - `Superseded`
   - `Invalid as written`
6. Record concrete evidence for stale or invalid status. Examples:
   - referenced file no longer exists;
   - prompt asks to implement behavior already present;
   - prompt mixes two unrelated objectives;
   - prompt contradicts `docs/mappings_system.md`;
   - prompt depends on old workbook names or old pipeline stage assumptions.

## AGENTS.md Content Requirements

The new or updated `docs/prompts/AGENTS.md` should include:

1. A short statement that `docs/prompts/` is for active, reusable prompts only.
2. A required lifecycle rule:
   - when a prompt's work is complete, tested, and committed, move it to
     `docs/archive/`;
   - completed prompts must not remain in `docs/prompts/`;
   - update the inventory in the same commit that adds, archives, or supersedes
     a prompt.
3. Instructions for adding new prompts.
4. Instructions for removing or archiving prompts.
5. Tips for writing good prompts in `leap_mappings`, including:
   - state the workbook, sheet, and pipeline stage precisely;
   - distinguish design decisions from implementation tasks;
   - require source workbook/schema verification before code edits;
   - require `git status --short`;
   - avoid stale line numbers where `rg` can find the function;
   - avoid prompts that combine mapping design decisions with production runs.
6. A current inventory table with columns similar to:
   - `Prompt`
   - `Type`
   - `Status`
   - `Basic Details`
   - `Notes Before Use`
7. A recommended tackling order for active prompts.
8. A list of recently archived prompts, if any were archived during the task.
9. Known folder issues, such as mojibake, stale line numbers, duplicate prompt
   names, ignored archive files, or active prompts that need splitting.

## Mapping-Specific Things To Check

Pay special attention to prompts that mention:

- `outlook_mappings_master.xlsx`
- `leap_mappings.xlsx`
- `master_config.xlsx`
- rollup rule sheets
- `leap_combined_esto`
- `leap_combined_ninth`
- `ninth_pairs_to_esto_pairs`
- Stage 0 maintenance workflow
- Stage 1 relationship building
- Stage 2 common ESTO structure
- Stage 3 comparison output
- subtotal/cardinality validation
- recursive tree validation
- dashboard comparison outputs

For any prompt that still points at legacy workbooks or old pipeline behavior,
mark it as stale unless the prompt is explicitly about legacy migration.

## Archiving Rules

Archive a prompt only when there is clear evidence that its work is complete or
superseded. Evidence can include:

- code/docs implementing the requested behavior;
- tests covering the requested behavior;
- a newer prompt that fully replaces the older one;
- prior status notes or commits showing the task was completed.

If evidence is ambiguous, leave the prompt active but mark it:

`Partially stale; review before use`

When archiving:

1. Move the file from `docs/prompts/` to `docs/archive/`.
2. Add the file to the `Recently Archived` section of
   `docs/prompts/AGENTS.md`.
3. If `docs/archive/` is ignored, force-add only those archived prompt files.
4. Do not archive unrelated prompt files.

## Recommended Output

At the end, report:

- the created or updated `docs/prompts/AGENTS.md`;
- prompts classified as valid/active;
- prompts classified as stale or invalid;
- prompts archived;
- recommended next prompt to tackle;
- any prompt that needs user review before execution;
- final `git status --short`;
- commit hash if you commit the documentation changes.

## Commit Guidance

Commit only documentation/prompt files changed for this task.

Suggested commit message:

```text
codex: add leap mappings prompt folder guide
```

Do not stage unrelated code, workbook, output, or test changes.
