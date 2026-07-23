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

# data/leap_export_templates/leap_export_template 20_USA.xlsx (example only -
# 2026-07-23: matching no longer requires this exact filename shape; see
# _filename_tokens/_economy_letter_code below).
LEAP_EXPORT_TEMPLATE_FILENAME_TEMPLATE = "leap_export_template {economy}.xlsx"

# A `COMP_GEN` marker (in any separator form - "_COMP_GEN", "COMP GEN",
# "COMPGEN", ...) flags a computer-generated template: it was derived from
# another economy's area rather than exported from its own, so its BranchID /
# VariableID / ScenarioID / RegionID values are not known to be that economy's.
# Usable, but every use must say so.
PROVISIONAL_TEMPLATE_MARKER = "COMP_GEN"

# Aggregate runs span economies and therefore span LEAP areas; no single export
# template can carry their IDs.
AGGREGATE_ECONOMY_SENTINELS = frozenset({"00_APEC", "ALL_ECONOMIES", "ALL"})

# The 21 APEC member economies this pipeline models, in canonical "NN_XXX"
# form. Hardcoded here deliberately - this is a leaf module with no other
# codebase imports (see resolve_leap_export_template_or_fallback's docstring)
# - purely so a template file can be found by its economy's letter code alone
# ("MAS") without the numeric prefix appearing in the filename at all.
KNOWN_ECONOMIES: tuple[str, ...] = (
    "01_AUS", "02_BD", "03_CDA", "04_CHL", "05_PRC", "06_HKC", "07_INA",
    "08_JPN", "09_ROK", "10_MAS", "11_MEX", "12_NZ", "13_PNG", "14_PE",
    "15_PHL", "16_RUS", "17_SGP", "18_CT", "19_THA", "20_USA", "21_VN",
)

# The Export-sheet columns every real LEAP export carries. Checked whenever a
# template is resolved (2026-07-23) so a file that merely matches an economy's
# letter code by name, but is not actually a real LEAP export (wrong file,
# corrupted save, etc.), is caught here rather than failing confusingly deep
# inside a consumer.
REQUIRED_TEMPLATE_COLUMNS: tuple[str, ...] = (
    "BranchID", "VariableID", "ScenarioID", "RegionID",
    "Branch Path", "Variable", "Scenario", "Region",
)

# One warning per economy per process; these resolve inside per-economy loops.
_PROVISIONAL_USE_WARNED: set[str] = set()

_FILENAME_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


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


def _economy_letter_code(economy: object) -> str:
    """Return the letter-code portion of a canonical economy string.

    "10_MAS" -> "MAS"; "01_AUS" -> "AUS". A bare letter code passed directly
    (no underscore) is returned unchanged, so callers already using just the
    letter code still work.
    """
    text = normalize_template_economy(economy)
    return text.split("_", 1)[1] if "_" in text else text


def _filename_tokens(name: str) -> list[str]:
    """Uppercase alphanumeric tokens from a filename, ignoring its extension.

    The whole point: the filename may otherwise be written any way (dates,
    extra description text, no numeric economy prefix, ...) - only the
    presence of the right tokens is checked, not any fixed shape.
    """
    return [tok.upper() for tok in _FILENAME_TOKEN_PATTERN.findall(Path(name).stem)]


def _filename_is_provisional(tokens: list[str]) -> bool:
    """True when a COMP_GEN marker appears in the tokens, in any separator form."""
    if "COMPGEN" in tokens:
        return True
    return any(tokens[i] == "COMP" and tokens[i + 1] == "GEN" for i in range(len(tokens) - 1))


def _filename_matches_economy(tokens: list[str], letter_code: str) -> bool:
    """True when ``letter_code`` appears as its own token in the filename.

    An exact-token match, not a raw substring search, so a short 2-letter
    code ("CT", "PE", "BD", "NZ", "VN") cannot false-match inside an
    unrelated word or a date fragment.
    """
    return letter_code in tokens


def iter_leap_export_templates(
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> list[LeapExportTemplate]:
    """Return every export template present under templates_root.

    Matched against ``KNOWN_ECONOMIES`` by letter code (see
    ``_filename_matches_economy``) - the numeric prefix, dates, and any other
    filename text are not required to follow any fixed pattern.
    """
    root = _resolve_path(templates_root)
    if not root.exists():
        return []
    found: list[LeapExportTemplate] = []
    for path in sorted(root.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        tokens = _filename_tokens(path.name)
        if not tokens:
            continue
        is_provisional = _filename_is_provisional(tokens)
        for economy in KNOWN_ECONOMIES:
            if _filename_matches_economy(tokens, _economy_letter_code(economy)):
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


def _validate_template_columns(
    path: Path,
    *,
    sheet_name: str = LEAP_EXPORT_TEMPLATE_SHEET,
) -> None:
    """Raise if the template's Export sheet is missing a required ID/key column.

    A filename match only proves the file's *name* mentions the right
    economy - not that its contents are a real LEAP export. This is the
    check that catches the rest: wrong file, corrupted save, wrong sheet
    layout, etc.
    """
    try:
        header = pd.read_excel(path, sheet_name=sheet_name, header=2, nrows=0)
    except Exception as exc:
        raise ValueError(
            f"Could not read the '{sheet_name}' sheet (header row 3) from LEAP export "
            f"template {path}: {exc}"
        ) from exc
    missing = [column for column in REQUIRED_TEMPLATE_COLUMNS if column not in header.columns]
    if missing:
        raise ValueError(
            f"LEAP export template {path} is missing required column(s) {missing} in its "
            f"'{sheet_name}' sheet (header row 3). Its filename matched the requested "
            "economy, but its contents do not look like a real LEAP export - check it "
            "was saved correctly (Area view export, not some other sheet or file)."
        )


def find_leap_export_template(
    economy: object,
    *,
    templates_root: Path | str = DEFAULT_LEAP_EXPORT_TEMPLATES_ROOT,
) -> LeapExportTemplate:
    """Return the export template for one economy, preferring a final over a provisional one.

    Matches by the economy's letter code (e.g. "MAS" for "10_MAS") appearing
    as its own token anywhere in the filename - the rest of the filename
    (numeric prefix, dates, description text, ...) may be written any way. A
    `COMP_GEN` token (any separator form) marks a provisional template. The
    Export sheet of the chosen file is validated against
    `REQUIRED_TEMPLATE_COLUMNS` before it is returned.
    """
    economy_text = normalize_template_economy(economy)
    root = _resolve_path(templates_root)

    if economy_text in AGGREGATE_ECONOMY_SENTINELS:
        raise ValueError(
            f"Economy {economy_text!r} is an aggregate sentinel spanning multiple LEAP "
            "areas, so it has no single export template. Resolve the template per "
            "member economy instead."
        )

    letter_code = _economy_letter_code(economy_text)
    final_matches: list[Path] = []
    provisional_matches: list[Path] = []
    for path in sorted(root.glob("*.xlsx")) if root.exists() else []:
        if path.name.startswith("~$"):
            continue
        tokens = _filename_tokens(path.name)
        if not _filename_matches_economy(tokens, letter_code):
            continue
        (provisional_matches if _filename_is_provisional(tokens) else final_matches).append(path)

    if len(final_matches) > 1:
        raise ValueError(
            f"Multiple final (non-provisional) LEAP export templates match economy "
            f"{economy_text!r}: {[p.name for p in final_matches]}. Remove or rename all "
            "but the correct one - refusing to guess which is authoritative."
        )
    if final_matches:
        chosen, is_provisional = final_matches[0], False
    elif provisional_matches:
        # Multiple provisional candidates are lower-stakes than multiple final
        # ones (neither is authoritative anyway); take the most recently
        # modified rather than refuse, since a provisional file is expected
        # to get superseded/regenerated over time.
        chosen = max(provisional_matches, key=lambda p: p.stat().st_mtime)
        is_provisional = True
    else:
        available = available_template_economies(root)
        available_text = ", ".join(available) if available else "(none)"
        raise FileNotFoundError(
            f"No LEAP export template for economy {economy_text!r}.\n"
            f"  Looked for: any .xlsx file under {root} whose name contains the token "
            f"{letter_code!r}.\n"
            f"  Available: {available_text}\n"
            f"  Fix: export the Analysis view for {economy_text} from its LEAP area and "
            f"save it under {root}, with {letter_code!r} somewhere in the filename. Do "
            f"not copy another economy's template — its BranchIDs belong to a different "
            f"area."
        )

    _validate_template_columns(chosen)
    return LeapExportTemplate(path=chosen, economy=economy_text, is_provisional=is_provisional)


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
    return _filename_is_provisional(_filename_tokens(Path(path).name))


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
