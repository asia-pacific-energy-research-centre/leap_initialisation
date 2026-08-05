# LEAP Review Tools: Hugging Face Space guide

This guide is for developers who need to initialise, test, publish, and later
update the LEAP balance-review web app as a Hugging Face (HF) Gradio Space.

The app can run in two modes:

1. **Sibling-repository development mode** uses `leap_initialisation`,
   `leap_mappings`, and `leap_dashboard` beside one another on a developer's
   machine.
2. **HF bundle mode** uses a prepared, self-contained `hf_bundle/` directory.
   This is the deployment mode. It copies the exact runtime files and data
   assets required from the three repositories and records their commits in
   `hf_bundle/source_manifest.json`. The Space does not need GitHub access at
   runtime.

The bundle is a snapshot. Updating one of the source repositories does not
automatically update the Space; the bundle preparation step must be run again
and the refreshed Space files must be uploaded.

## Current readiness

The local app is ready for an initial private Space deployment. The remaining
deployment work is operational rather than a second application build:

- create a private HF Space;
- prepare and upload the bundle;
- verify one real export end-to-end in the hosted container;
- review licensing and publication safety before changing the Space to public.

The current app includes internal diagnostics, the four-sheet balance-review
workbook, dashboard generation and in-app dashboard viewing. It accepts a LEAP
balance export workbook, one or more review years, and an optional ESTO CSV
override. Dashboard scenario and economy selectors are intentionally hidden;
they are taken from the submitted inputs. The optional ESTO override changes
the comparison dataset used by both the review workbook and dashboard, and the
latest year in that dataset becomes the dashboard base year.

The removed fifth “missing combinations” workbook sheet does not mean those
diagnostics were removed. Missing/unavailable rows remain available through
the diagnostic outputs and run summary.

## 1. Prerequisites and local layout

Use a parent directory containing the three source repositories:

```text
C:\Users\Work\github\
  leap_initialisation\
  leap_mappings\
  leap_dashboard\
  leap_review_web_app\       # created by the preparation step
```

The source repositories must be available locally because bundle preparation
copies files from them. They do not need to be installed as Python packages.

Before preparing a release, confirm that the code, configuration, and source
data assets intended for publication may be redistributed. A public Space
publishes the prepared bundle to the Space repository. Do not include raw
user-uploaded exports, local output folders, logs, notebooks, credentials, or
the full source repositories.

Install the web-app requirements in the development environment:

```powershell
C:\Users\Work\miniconda3\python.exe -m pip install -r web_app\requirements.txt
```

## 2. Test the existing local app first

From `leap_initialisation`:

```powershell
C:\Users\Work\miniconda3\python.exe app.py
```

Open `http://127.0.0.1:7860`. Upload a representative LEAP balance export and
check the following before creating the Space:

1. the economy, scenario, and `Balance table review year(s)` inputs;
2. the optional ESTO override;
3. the generated workbook download;
4. the dashboard pages in the app;
5. the full dashboard/workbook/diagnostics ZIP download;
6. saving and reopening a dashboard from the browser-local archive list;
7. clearing the browser-local archive list.

The app processes the uploaded workbook on the Space server while the run is
active. Browser-local storage only controls the user's saved dashboard page
snapshots; it is not a claim that uploaded files never reach the server.

## 3. Prepare the self-contained bundle

The preparation script reads the source-of-truth
`config/portable_release_manifest.toml`. It validates the three sibling Git
repositories, copies the allow-listed runtime files and required configuration
and data assets, and writes source commit provenance.

Run a dry run first. This inspects the source state without writing the
bundle:

```powershell
Set-Location C:\Users\Work\github\leap_initialisation
C:\Users\Work\miniconda3\python.exe -c "from web_app.prepare_hf_bundle import prepare_hf_bundle; r=prepare_hf_bundle(dry_run=True); print(r['bundle_root']); print(r['manifest'])"
```

The preparation function normally refuses dirty source repositories. That is
intentional: a public deployment should identify exact committed source
versions. Finish or commit unrelated work in the three source repositories,
then repeat the dry run. Do not use `allow_dirty_sources=True` for a published
bundle; it is only useful for a local inspection build.

After reviewing the commits and file counts, write the bundle:

```powershell
C:\Users\Work\miniconda3\python.exe -c "from web_app.prepare_hf_bundle import prepare_hf_bundle; r=prepare_hf_bundle(); print(r['bundle_root']); print(r['manifest'])"
```

This creates or refreshes:

```text
C:\Users\Work\github\leap_review_web_app\
  hf_bundle\
    leap_initialisation\
    leap_mappings\
    leap_dashboard\
    source_manifest.json
```

The current dry-run bundle is approximately 392 MB and is much smaller than
the complete source repositories. The exact size can change when the manifest
or source data changes. The manifest is the record of what was copied and from
which source commits.

## 4. Assemble the Space repository

The output repository is deliberately separate from
`leap_initialisation`. Copy the web-app entry point and runtime files into the
new repository, keeping the bundle at its root:

```text
leap_review_web_app\
  app.py
  requirements.txt
  README.md
  web_app\
    app.py
  hf_bundle\
    leap_initialisation\
    leap_mappings\
    leap_dashboard\
    source_manifest.json
```

`app.py` should be the root entry point from this repository. `requirements.txt`
must be at the Space root because HF installs dependencies from a root-level
requirements file. When copying into a separate Space repo, either preserve
the current relative include or put the package lines directly in the root
requirements file.

Create a root `README.md` with HF Space metadata. A minimal example is:

```yaml
---
title: LEAP Balance Review
emoji: 📊
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.44.1
app_file: app.py
pinned: false
---
```

Keep the README description clear about inputs, processing, outputs, and any
license or data restrictions. HF reads this metadata to determine the Space
SDK and application file. Check the current HF configuration reference before
changing these fields.

Do not copy the nested `.git` directories from the three source repositories.
The Space repository should have one Git history of its own.

## 5. Test bundle mode locally

Before uploading, run the new Space directory as it will run on HF. From the
root of `leap_review_web_app`:

```powershell
$env:HF_BUNDLE_ROOT = (Resolve-Path .\hf_bundle).Path
$env:GRADIO_SERVER_NAME = "127.0.0.1"
$env:GRADIO_SERVER_PORT = "7860"
C:\Users\Work\miniconda3\python.exe .\app.py
```

The app should find the bundled `leap_initialisation`, `leap_mappings`, and
`leap_dashboard` trees without `LEAP_MAPPINGS_ROOT` or
`LEAP_DASHBOARD_ROOT`. This is the important pre-upload proof that the Space
does not accidentally depend on sibling folders or GitHub at runtime.

Repeat the end-to-end checks from section 2 in this bundle-mode process. Also
run the focused regression tests from the source repository when source code
has changed:

```powershell
C:\Users\Work\miniconda3\python.exe -m pytest tests/test_balance_review_workbooks.py tests/test_portable_release.py -q
```

## 6. Create the Hugging Face Space

Create the Space privately first. In the HF web UI, choose **New Space**, set
the owner and repository name, select **Gradio**, choose CPU hardware for the
first smoke test, and leave storage at its default unless a later feature
explicitly requires server-side persistence.

The same operation can be performed with the HF Python client:

```python
from huggingface_hub import HfApi

api = HfApi()
api.create_repo(
    repo_id="YOUR_ACCOUNT/leap-review-web-app",
    repo_type="space",
    space_sdk="gradio",
    private=True,
)
```

Then upload the assembled Space directory. For example, after cloning the
new Space repository:

```powershell
git clone https://huggingface.co/spaces/YOUR_ACCOUNT/leap-review-web-app
Set-Location .\leap-review-web-app
# Copy app.py, requirements.txt, README.md, web_app/, and hf_bundle/ here.
git add app.py requirements.txt README.md web_app hf_bundle
git commit -m "Initialise LEAP balance review Space"
git push
```

Alternatively, `HfApi.upload_folder(..., repo_type="space")` can upload the
assembled directory. Use an HF token with write access, and never place that
token in the repository or in application source.

HF installs the root requirements and builds the Gradio Space. Monitor the
build and runtime logs in the Space page. The root `app.py` launches Gradio on
the host and port supplied by the environment, which is the expected Space
runtime behavior.

## 7. First hosted smoke test

Keep the Space private until this checklist passes:

- the build completes without missing-package errors;
- the app opens and shows the expected input controls;
- a small representative export produces the balance-review workbook;
- the workbook has the expected four sheets;
- diagnostics and the dashboard are produced from the upload;
- the dashboard opens inside the app with the submitted economy/scenario;
- the full ZIP contains the dashboard subfolders, workbook, diagnostics, and
  logs;
- browser-local dashboard snapshots can be saved, restored, and cleared;
- a second browser profile cannot see the first profile's saved snapshots;
- no user input or generated output has been committed back to the Space repo.

The current Space does not need persistent HF storage for saved dashboards.
The app stores up to three compressed dashboard page snapshots in the user's
browser using Gradio browser state. The current run's full ZIP is generated in
temporary server storage for download. Browser snapshots disappear if the
user clears site data or changes browser/device, which is expected. They are
not a cross-device archive and are not a substitute for downloading the ZIP.

HF's default Space disk is ephemeral, so the deployment should not rely on
server files surviving restarts. If a future feature requires shared or
long-lived server-side data, design authentication and access controls first,
then explicitly add an appropriate HF volume or external storage service.

## 8. Public-release review

Only change the Space visibility to public after checking:

- source-repository licenses permit redistribution;
- all copied data tables may be published;
- the Space README describes the data and processing accurately;
- no secrets, tokens, raw test exports, or local paths are present;
- the app does not write user exports or dashboards into the Git checkout;
- the browser-local archive behavior is explained to users;
- resource and file-size limits are acceptable for the selected HF hardware.

Making dashboard archives browser-local prevents one anonymous visitor from
seeing another visitor's saved archive through shared server state. It does
not make uploaded exports anonymous from the server's point of view, and it
does not provide authentication. Use a private Space or add authentication if
the inputs themselves are sensitive.

## 9. Updating the Space from the source repositories

When `leap_initialisation`, `leap_mappings`, or `leap_dashboard` changes:

1. pull or otherwise select the intended commits in all three sibling repos;
2. run the bundle preparation dry run and inspect source commits, file counts,
   and missing assets;
3. ensure the source repos are clean and prepare the bundle without
   `allow_dirty_sources=True`;
4. run the bundle-mode local smoke test;
5. replace `hf_bundle/` in the Space checkout and inspect the diff;
6. commit and push the Space update;
7. repeat the hosted smoke test and record the new
   `source_manifest.json` commit IDs.

There is no automatic runtime link to the other GitHub repositories. This is
intentional: it makes the deployment reproducible and prevents a source-repo
change from silently changing a public application. The preparation step is
the controlled update boundary.

## 10. Troubleshooting

**The app says a bundled source asset is missing.** Confirm that the Space has
`hf_bundle/` at its repository root, that the preparation step was run from a
parent containing all three sibling repositories, and that no large required
asset was accidentally excluded from the manifest.

**The app tries to use sibling repositories.** The Space is not seeing a valid
bundle. Check the `HF_BUNDLE_ROOT` path and the presence of
`hf_bundle/leap_initialisation`, `hf_bundle/leap_mappings`, and
`hf_bundle/leap_dashboard`.

**The build cannot install dependencies.** Confirm that `requirements.txt` is
at the Space root and that its relative include still points to an existing
file. Check the HF build log for the first package error.

**A saved dashboard is missing.** Browser-local archives are intentionally
limited to the last three snapshots and are tied to the same browser profile.
Use the full ZIP download for durable sharing or comparison outside that
browser.

**A later source change does not appear online.** The Space only contains the
last prepared snapshot. Re-run bundle preparation, upload the refreshed
`hf_bundle/`, and confirm the new source commit IDs in
`source_manifest.json`.

## Official HF references

- [Space overview and supported SDKs](https://huggingface.co/docs/hub/main/spaces)
- [Gradio Space dependencies](https://huggingface.co/docs/hub/spaces-dependencies)
- [Spaces configuration reference](https://huggingface.co/docs/hub/main/spaces-config-reference)
- [Managing Spaces with `huggingface_hub`](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces)
- [Space disk usage and storage](https://huggingface.co/docs/hub/main/spaces-storage)

For the repository-specific release contract and bundle contents, also see
[`docs/balance_review_web_app.md`](balance_review_web_app.md) and
[`web_app/README.md`](../web_app/README.md).
