"""The input and output layout a user actually works with.

There is one folder a user touches: ``input/leap balances exports``. It mirrors
``leap_initialisation/data/leap balances exports`` exactly — one sub-folder per
economy code, LEAP Energy Balance workbooks inside it, superseded files moved to
``archive/`` — so the same folder can be copied between a release and the
maintainer's checkout without rearranging anything, and the naming rules only
have to be documented once.

Discovery reuses :mod:`codebase.utilities.leap_balance_export_resolver` rather
than re-deriving the conventions. That module already knows the filename
patterns, the compact date-id forms, the latest-file rule, and that ``archive/``
is ignored. Reimplementing any of that here would be a second source of truth
that drifts.

Outputs are grouped by economy so that runs accumulate instead of overwriting::

    output/
      20_USA/
        balance_review/balance_review_20_USA_tgt_2022.xlsx
        dashboard/dashboards/index.html
      01_AUS/
        ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


#: The input sub-folder, named to match the maintainer's data directory.
BALANCE_EXPORTS_DIRNAME = "leap balances exports"

#: Output sub-folder per tool, inside each economy's folder.
BALANCE_REVIEW_DIRNAME = "balance_review"
DASHBOARD_DIRNAME = "dashboard"

#: Economy folder names look like ``20_USA`` / ``02_BD``. Anything else in the
#: exports root (README, stray files) is ignored rather than treated as an
#: economy, so a user cannot accidentally create one by dropping a file there.
ECONOMY_DIR_PATTERN = re.compile(r"^\d{2}_[A-Z]{2,4}$")

SCENARIO_CODES = ("REF", "TGT")
SCENARIO_NAMES = {"REF": "Reference", "TGT": "Target"}


@dataclass(frozen=True)
class DiscoveredWorkbook:
    """One balance-export workbook found for an economy and scenario."""

    economy: str
    scenario_code: str
    scenario: str
    path: Path
    date_id: str
    years: tuple[int, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.scenario} ({self.scenario_code}) - {self.path.name}"


@dataclass
class DiscoveredEconomy:
    """Everything a release can see for one economy."""

    economy: str
    directory: Path
    workbooks: list[DiscoveredWorkbook] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def scenario_codes(self) -> list[str]:
        return sorted({item.scenario_code for item in self.workbooks})

    @property
    def years(self) -> list[int]:
        years: set[int] = set()
        for item in self.workbooks:
            years.update(item.years)
        return sorted(years)

    def workbook_for(self, scenario_code: str) -> DiscoveredWorkbook | None:
        for item in self.workbooks:
            if item.scenario_code == scenario_code:
                return item
        return None


def balance_exports_root(input_root: Path | str) -> Path:
    """Return the balance-exports folder inside an ``input`` directory."""
    return Path(input_root) / BALANCE_EXPORTS_DIRNAME


def economy_output_root(output_root: Path | str, economy: str) -> Path:
    """Return the per-economy output folder, creating nothing."""
    return Path(output_root) / normalize_economy_folder(economy)


def normalize_economy_folder(economy: str) -> str:
    """Return the folder form of an economy code (``20_USA``)."""
    text = str(economy).strip().upper().replace("-", "_")
    if "_" not in text and len(text) > 2 and text[:2].isdigit():
        # Accept the compact dashboard form (20USA) and restore the underscore.
        text = f"{text[:2]}_{text[2:]}"
    return text


def discover_economies(
    exports_root: Path | str,
    *,
    read_years: bool = True,
) -> list[DiscoveredEconomy]:
    """List every economy folder under *exports_root* and what it contains.

    ``read_years`` opens each workbook to read the scenario/year sheets it
    declares. That is the slow part (a second or so per workbook), so callers
    that only need the economy list can switch it off.
    """
    root = Path(exports_root)
    if not root.is_dir():
        return []

    from codebase.utilities.leap_balance_export_resolver import (
        list_balance_export_sheets,
        resolve_balance_export_workbook,
    )

    found: list[DiscoveredEconomy] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if not ECONOMY_DIR_PATTERN.match(directory.name):
            continue
        economy = DiscoveredEconomy(economy=directory.name, directory=directory)
        loose = [
            p
            for p in directory.glob("*.xlsx")
            if not p.name.startswith("~$")
        ]
        for scenario_code in SCENARIO_CODES:
            try:
                path = resolve_balance_export_workbook(
                    economy=directory.name,
                    scenario=scenario_code,
                    exports_root=root,
                )
            except (FileNotFoundError, ValueError):
                continue
            years: tuple[int, ...] = ()
            if read_years:
                try:
                    sheets = list_balance_export_sheets(path)
                    years = tuple(sorted({sheet.year for sheet in sheets}))
                except Exception as exc:  # noqa: BLE001 - reported, not fatal
                    economy.problems.append(
                        f"{path.name}: could not read its scenario/year sheets ({exc})."
                    )
            economy.workbooks.append(
                DiscoveredWorkbook(
                    economy=directory.name,
                    scenario_code=scenario_code,
                    scenario=SCENARIO_NAMES[scenario_code],
                    path=path,
                    date_id=_date_id_of(path),
                    years=years,
                )
            )
        if loose and not economy.workbooks:
            economy.problems.append(
                f"{len(loose)} workbook(s) are present but none could be matched to a "
                "scenario. Rename them like 'full model output all years 03082026 TGT.xlsx'."
            )
        found.append(economy)
    return found


def _date_id_of(path: Path) -> str:
    from codebase.utilities.leap_balance_export_resolver import (
        _balance_export_filename_parts,
    )

    parts = _balance_export_filename_parts(path)
    return parts[0] if parts else ""


def describe_workspace(
    exports_root: Path | str,
    economies: Sequence[DiscoveredEconomy] | None = None,
) -> str:
    """Render the human-facing 'what can I run?' listing."""
    root = Path(exports_root)
    found = list(economies) if economies is not None else discover_economies(root)
    lines = [f"LEAP balance exports in: {root}", ""]
    if not root.is_dir():
        lines.append("  That folder does not exist yet.")
        lines.append("")
        lines.append(_getting_started_text(root))
        return "\n".join(lines)
    if not found:
        lines.append("  No economy folders found.")
        lines.append("")
        lines.append(_getting_started_text(root))
        return "\n".join(lines)

    for economy in found:
        lines.append(f"  {economy.economy}")
        if not economy.workbooks:
            lines.append("      (no usable workbook found)")
        for workbook in economy.workbooks:
            years = (
                f"{min(workbook.years)}-{max(workbook.years)}"
                if len(workbook.years) > 1
                else (str(workbook.years[0]) if workbook.years else "years unknown")
            )
            lines.append(
                f"      {workbook.scenario:<10} {workbook.path.name}  [{years}]"
            )
        for problem in economy.problems:
            lines.append(f"      ! {problem}")
    lines.append("")
    runnable = [item for item in found if item.workbooks]
    if runnable:
        example = runnable[0]
        # Suggest the base year rather than the horizon end: a balance review is
        # normally run against the year the model was calibrated on.
        example_year = _suggested_review_year(example.years)
        lines += [
            "Run a balance review:",
            f"  leap-review-tools.exe balance-review --economy {example.economy} "
            f"--year {example_year}",
            "",
            "Render a dashboard from every export for one economy:",
            f"  leap-review-tools.exe dashboard --economy {example.economy}",
        ]
    return "\n".join(lines)


#: The LEAP base year these workflows calibrate on.
DEFAULT_REVIEW_YEAR = 2022


def _suggested_review_year(years: Sequence[int]) -> int:
    """Return the year to offer as an example or default for a review."""
    if not years:
        return DEFAULT_REVIEW_YEAR
    if DEFAULT_REVIEW_YEAR in years:
        return DEFAULT_REVIEW_YEAR
    return min(years)


def _getting_started_text(root: Path) -> str:
    return "\n".join(
        [
            "To add data, create one folder per economy and put the LEAP Energy",
            "Balance exports inside it:",
            "",
            f"  {root / '20_USA' / 'full model output all years 03082026 TGT.xlsx'}",
            f"  {root / '20_USA' / 'full model output all years 03082026 REF.xlsx'}",
            "",
            "Export from LEAP with at least Level 2 detail. The date is DDMMYYYY;",
            "when several files exist for one scenario the newest is used, and",
            "anything inside an 'archive' sub-folder is ignored.",
        ]
    )


#: Dropped into the exports folder so the rules are next to the data.
INPUT_README = """# LEAP balance exports — put your files here

One folder per economy, named with the economy code:

```text
leap balances exports/
  20_USA/
    full model output all years 03082026 REF.xlsx
    full model output all years 03082026 TGT.xlsx
    archive/
  01_AUS/
    full model output all years 04082026 TGT.xlsx
```

This is the same layout as `leap_initialisation/data/leap balances exports`, so
a folder can be copied straight between the two.

## Filename

```text
full model output all years <date> <scenario>.xlsx
```

* `<date>` is `DDMMYYYY` (`03082026` is 3 August 2026). `382026` also works.
* `<scenario>` is `REF` or `TGT`. `Reference` and `Target` are accepted too.
* `REF 03082026.xlsx` (scenario first) is accepted as well.

When more than one file matches an economy and scenario, **the newest date is
used**. Move superseded workbooks into `archive/` — anything in there is ignored.

## Export settings

Export the LEAP **Energy Balance** view to Excel with **at least Level 2
detail**, with a sheet per year you care about. A Level 1 export collapses every
module to one flat row; the tools detect this and refuse it, because the
comparison would have no sector detail to work with.

## What reads this folder

Both tools:

* `balance-review` picks the one workbook matching the economy, scenario, and
  year you ask for.
* `dashboard` reads **every** workbook available for the economy you ask for.

## Where results go

Per economy, so nothing is overwritten:

```text
output/
  20_USA/
    balance_review/
    dashboard/
  01_AUS/
    ...
```

Run `leap-review-tools.exe list` to see exactly what the tools can find.
"""
