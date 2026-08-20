# LEAP GUI batch preflight

`codebase/leap_gui_batch_preflight_workflow.py` prepares a reviewed job register
for a sequential overnight GUI run. It does not open LEAP, import a seed, or
copy an area unless a later notebook cell explicitly requests staging.

The preflight discovers three separate facts per economy:

- the latest matching clean-slate `.leap` files in the protected source folder;
- matching installed LEAP-area directories in `C:\LEAP_Areas`; and
- the latest final baseline seed under the reconciliation run outputs.

It writes JSON for a GUI agent and a compact review CSV under
`outputs/leap_gui_batch/preflight_<timestamp>/`. A job remains
`REQUIRES_OPERATOR_SELECTION` until its selected source, exact expected LEAP
title, and `IMPORT_SEED`/`SKIP_SEED_ALREADY_IMPORTED` policy have been set.
This avoids choosing an area merely because its name is similar.

Use Level 2 by default. The register sets a visible-completion polling cadence
of 10 minutes at Level 2 and 60 minutes at higher detail levels. Waiting is not
treated as success: the agent must still verify that LEAP's export is complete
and inspect the destination workbook before it advances.
