"""Resolve per-economy LEAP Analysis-view export templates.

Each economy is a separate LEAP area, so its internal BranchID/VariableID/
ScenarioID/RegionID values are its own and must not be borrowed from another
economy's export. This module resolves the template workbook for one economy
and refuses to guess when it is absent.

Mirrors the conventions in `leap_balance_export_resolver.py`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT = REPO_ROOT / "data" / "leap_export_templates"

LEAP_EXPORT_TEMPLATE_SHEET = "Export"

# data/leap_export_templates/leap_export_template 20_USA.xlsx
LEAP_EXPORT_TEMPLATE_FILENAME_TEMPLATE = "leap_export_template {economy}.xlsx"
LEAP_EXPORT_TEMPLATE_FILENAME_PATTERN = re.compile(
    r"^leap_export_template (?P<economy>[^.]+)\.xlsx$",
    re.IGNORECASE,
)

# A `_COMP_GEN` suffix marks a computer-generated template: it was derived from
# another economy's area rather than exported from its own, so its BranchID /
# VariableID / ScenarioID / RegionID values are not known to be that economy's.
# Usable, but every use must say so.
PROVISIONAL_TEMPLATE_MARKER = "COMP_GEN"

# Aggregate runs span economies and therefore span LEAP areas; no single export
# template can carry their IDs.
AGGREGATE_ECONOMY_SENTINELS = frozenset({"00_APEC", "ALL_ECONOMIES", "ALL"})

# One warning per economy per process; these resolve inside per-economy loops.
_PROVISIONAL_USE_WARNED: set[str] = set()


@dataclass(frozen=True)
class LeapExportTemplate:
    path: Path
    economy: str
    is_provisional: bool = False


def _resolve_path(path: Path | str) -> Path:
    """Resolve repo-relative paths while leaving absolute paths unchanged."""
    raw = str(path).replace("\\", "/")
    drive_match = re.match(r"^([a-zA-Z]):/(.*)$", raw)
    if drive_match:
        drive = drive_match.group(1).lower()
        rest = drive_match.group(2)
        if os.name == "nt":
            return Path(f"{drive.upper()}:/{rest}")
        return Path(f"/mnt/{drive}/{rest}")
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def normalize_template_economy(economy: object) -> str:
    """Return the economy label used in export-template filenames."""
    text = str(economy or "").strip()
    if not text:
        raise ValueError("LEAP export template economy cannot be blank.")
    return text.upper()


def is_aggregate_economy(economy: object) -> bool:
    """Return True for aggregate sentinels that have no single LEAP area."""
    try:
        return normalize_template_economy(economy) in AGGREGATE_ECONOMY_SENTINELS
    except ValueError:
        return False


def _split_provisional_marker(economy_token: str) -> tuple[str, bool]:
    """Split a filename economy token into its economy and provisional flag."""
    token = normalize_template_economy(economy_token)
    suffix = f"_{PROVISIONAL_TEMPLATE_MARKER}"
    if token.endswith(suffix):
        return token[: -len(suffix)], True
    return token, False


def iter_leap_export_templates(
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> list[LeapExportTemplate]:
    """Return every export template present under templates_root."""
    root = _resolve_path(templates_root)
    if not root.exists():
        return []
    found: list[LeapExportTemplate] = []
    for path in sorted(root.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        match = LEAP_EXPORT_TEMPLATE_FILENAME_PATTERN.match(path.name)
        if not match:
            continue
        economy, is_provisional = _split_provisional_marker(match.group("economy"))
        if not economy:
            continue
        found.append(
            LeapExportTemplate(
                path=path,
                economy=economy,
                is_provisional=is_provisional,
            )
        )
    return found


def available_template_economies(
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
    *,
    include_provisional: bool = True,
) -> list[str]:
    """Return the economies that currently have an export template."""
    return sorted(
        {
            template.economy
            for template in iter_leap_export_templates(templates_root)
            if include_provisional or not template.is_provisional
        }
    )


def find_leap_export_template(
    economy: object,
    *,
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> LeapExportTemplate:
    """Return the export template for one economy, preferring a final over a provisional one."""
    economy_text = normalize_template_economy(economy)
    root = _resolve_path(templates_root)

    if economy_text in AGGREGATE_ECONOMY_SENTINELS:
        raise ValueError(
            f"Economy {economy_text!r} is an aggregate sentinel spanning multiple LEAP "
            "areas, so it has no single export template. Resolve the template per "
            "member economy instead."
        )

    matches = [
        template
        for template in iter_leap_export_templates(root)
        if template.economy == economy_text
    ]
    # A finalized export supersedes the generated placeholder it replaces.
    for template in matches:
        if not template.is_provisional:
            return template
    if matches:
        return matches[0]

    available = available_template_economies(root)
    available_text = ", ".join(available) if available else "(none)"
    expected = root / LEAP_EXPORT_TEMPLATE_FILENAME_TEMPLATE.format(economy=economy_text)
    raise FileNotFoundError(
        f"No LEAP export template for economy {economy_text!r}.\n"
        f"  Expected: {expected}\n"
        f"  Available: {available_text}\n"
        f"  Fix: export the Analysis view for {economy_text} from its LEAP area and save it "
        f"at the expected path. Do not copy another economy's template — its BranchIDs "
        f"belong to a different area."
    )


def resolve_leap_export_template(
    economy: object,
    *,
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
    warn_on_provisional: bool = True,
) -> Path:
    """Return the LEAP export template workbook path for one economy.

    Raises rather than falling back to another economy's template: the IDs in a
    borrowed template route values into the wrong branches, and the resulting
    workbook still looks importable.
    """
    template = find_leap_export_template(economy, templates_root=templates_root)
    if template.is_provisional and warn_on_provisional:
        if template.economy not in _PROVISIONAL_USE_WARNED:
            _PROVISIONAL_USE_WARNED.add(template.economy)
            print(
                f"[WARN] Using provisional ({PROVISIONAL_TEMPLATE_MARKER}) LEAP export template "
                f"for {template.economy}: {template.path.name}. It was generated from another "
                f"economy's area, so its BranchID/VariableID/ScenarioID/RegionID values may be "
                f"wrong for {template.economy} and anything derived from it may import into the "
                f"wrong branches. Replace it with a real export from the {template.economy} area."
            )
    return template.path


def resolve_leap_export_template_or_fallback(
    economy: object,
    *,
    fallback: Path | str,
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
    warn_on_provisional: bool = True,
) -> Path:
    """Return the economy's template, or ``fallback`` where none can apply.

    Two cases legitimately have no single per-economy template: aggregate
    sentinels (``00_APEC``, ``ALL_ECONOMIES``), which span areas, and an economy
    with no template yet. Everything else resolves to its own area's template —
    `resolve_leap_export_template` raises rather than borrow another area's IDs,
    and this wrapper turns that refusal into an explicit, warned fallback.

    ``fallback`` is **injected, not imported**: this module is a leaf utility
    with no codebase imports, and importing the config that owns the legacy
    single export would create a cycle. Each caller passes its own legacy
    constant, so there is one wrapper rather than one per module.

    Do not use this to paper over a missing template for a real economy — the
    warning it emits is the signal that a template needs exporting.
    """
    if is_aggregate_economy(economy):
        return _resolve_path(fallback)
    try:
        return resolve_leap_export_template(
            economy,
            templates_root=templates_root,
            warn_on_provisional=warn_on_provisional,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[WARN] {exc}")
        return _resolve_path(fallback)


def reset_provisional_template_warnings() -> None:
    """Clear the once-per-economy provisional-template warning state."""
    _PROVISIONAL_USE_WARNED.clear()


def is_provisional_template(path: Path | str) -> bool:
    """Return True when a template path is a provisional (COMP_GEN) workbook."""
    match = LEAP_EXPORT_TEMPLATE_FILENAME_PATTERN.match(Path(path).name)
    if not match:
        return False
    _, is_provisional = _split_provisional_marker(match.group("economy"))
    return is_provisional


def provisional_template_economies(
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> list[str]:
    """Return economies whose resolved template is still provisional."""
    provisional: list[str] = []
    for economy in available_template_economies(templates_root):
        template = find_leap_export_template(economy, templates_root=templates_root)
        if template.is_provisional:
            provisional.append(economy)
    return sorted(provisional)


def read_leap_export_template_area(
    path: Path | str,
    *,
    sheet_name: str = LEAP_EXPORT_TEMPLATE_SHEET,
) -> str:
    """Return the LEAP area name recorded in the template preamble.

    LEAP writes `Area:` and the area name into the first preamble row. The name
    is free-form, so it is reported rather than validated against the economy.
    """
    resolved = _resolve_path(path)
    preamble = pd.read_excel(resolved, sheet_name=sheet_name, header=None, nrows=2)
    for _, row in preamble.iterrows():
        values = list(row)
        for idx, cell in enumerate(values):
            if str(cell or "").strip().rstrip(":").lower() != "area":
                continue
            for candidate in values[idx + 1 :]:
                text = str(candidate or "").strip()
                if text and text.lower() != "nan":
                    return text
    return ""


def find_shared_template_areas(
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> dict[str, list[str]]:
    """Return area names claimed by more than one economy's final template.

    Two final templates sharing an area name means one was copied between
    economies rather than exported from its own LEAP area, so its IDs are
    another area's. Provisional templates are excluded because sharing the
    source area is what being provisional means.
    """
    by_area: dict[str, list[str]] = {}
    for template in iter_leap_export_templates(templates_root):
        if template.is_provisional:
            continue
        area = read_leap_export_template_area(template.path)
        if not area:
            continue
        by_area.setdefault(area, []).append(template.economy)
    return {
        area: sorted(economies)
        for area, economies in by_area.items()
        if len(economies) > 1
    }
