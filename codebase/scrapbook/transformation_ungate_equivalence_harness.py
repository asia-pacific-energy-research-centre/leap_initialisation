#%%
"""[1] transformation ungate — the definitive equivalence harness.

WHAT THIS SETTLES
-----------------
`patch_baseline_seeds.run_patch` raises NotImplementedError for any module with
`auto_sector_keys` (every transformation module). The gate's evidence was
"20_USA: 7 process-efficiency / auxiliary-fuel expression diffs" — but that was
almost certainly measured on the RAW output of
`save_transformation_exports_with_split_targets`, which skips
`prepare_seed_rows_for_write`, the seed writer the real patcher applies.

**Never diff raw export output against a finished seed.** The seed writer does
canonical share completion and cross-scenario borrowing, so a pre-boundary vs
post-boundary comparison manufactures differences that were never real. That trap
already cost one retracted conclusion, and it is the gate's likely origin.

This harness runs the REAL patcher (bypassing only the gate) and diffs
POST-write vs POST-write, so both sides have crossed the same boundary.

PRECONDITIONS (both now met, 2026-07-17)
----------------------------------------
1. Per-economy template routing — every producer resolves
   `_template_for_economy(econ)`; no pinned `full model export.xlsx`.
   Landed across 39f82df / 12e1482 / e799029 / ee4e5d1 / 6714db0.
2. Clean HEAD transformation code — 8c32504 (multi_output default). Run this
   against a clean tree; a dirty tree makes the result unreadable.

KNOWN BLOCKER, READ THIS BEFORE INTERPRETING A FAILURE
------------------------------------------------------
The patcher refuses to write when the seed itself fails validation against its
own economy's template. Measured 2026-07-17: `run_patch("aggregated_demand",
["12_NZ"])` raised on SEED-003/008/011 because the 20260715 seed was built with
USA IDs. **That is not a patch defect — it is a stale seed**, and this harness
reports it separately so nobody records it as one.

Practical consequence: `20_USA` is the only economy whose 20260715 seed is
internally consistent (it *is* the pinned area). `01_AUS` and `12_NZ` need a
regenerated seed before their result means anything.

USAGE
-----
    python codebase/scrapbook/transformation_ungate_equivalence_harness.py
    python codebase/scrapbook/transformation_ungate_equivalence_harness.py 20_USA

Read-only with respect to the repo: seeds are backed up and restored in a
`finally`. It does NOT remove the gate — it produces the evidence for that
decision. Ungating is also not just deleting the gate: the patcher's
transformation path uses `_collect_auto_regen` (the simplified path), not
`save_transformation_exports_with_split_targets`. See work_queue [1].
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codebase.functions import patch_baseline_seeds as patcher

MODULE = "transformation"
DEFAULT_ECONOMIES = ["20_USA", "01_AUS"]

# The Verification Recipe's precondition is an economy "whose config for M has
# not changed since the last full run". For transformation that is a hard
# requirement, not a nicety: 8c32504 (2026-07-16) flipped the multi_output
# default, which moves capacity, historical production, efficiency, output shares
# and aux-fuel ratios by one exact ratio (USA coke ovens x1.16676). A seed built
# before it disagrees with today's code *by design* -- work_queue [0] records
# "where fresh and a 20260715 seed disagree on these sectors, the seed is out of
# date -- fresh is right."
#
# This harness reads "before" straight off the seed on disk. Against a stale seed
# the patch regenerates with current code, so that intended correction surfaces as
# differences and would be reported as a patcher DEFECT -- blaming the patcher for
# a modelling change already signed off. That is the same class of error as the
# gate's original evidence: comparing two things built under different rules.
# Refuse rather than mislead.
#
# Bump this when transformation output rules change again.
TRANSFORMATION_RULES_CHANGED = "20260716"  # 8c32504

_SEED_DATE_RE = re.compile(r"_(\d{8})$")

# Key on Branch Path/Variable/Scenario, NOT Region: the patcher may legitimately
# rewrite Region (it resolves per economy), and keying on it would report every
# corrected row as a defect.
KEY = ["Branch Path", "Variable", "Scenario"]

_DATA_RE = re.compile(r"^(Data|Interp)\s*\((.*)\)\s*$", re.I)
VALUE_TOLERANCE = 1e-6


def _parse_expression(expression: object) -> dict[int, float] | str:
    """Return {year: value} for a series, else the normalized scalar/text.

    Values are parsed numerically before comparison so that 1 vs 1.0 vs 1.000000
    is not reported as a difference (recipe step 5).
    """
    text = str(expression).strip()
    match = _DATA_RE.match(text)
    if not match:
        try:
            return {0: float(text)}
        except ValueError:
            return text.lower()
    tokens = [token.strip() for token in match.group(2).split(",")]
    series: dict[int, float] = {}
    for index in range(0, len(tokens) - 1, 2):
        try:
            series[int(float(tokens[index]))] = float(tokens[index + 1])
        except ValueError:
            return text.lower()
    return series


def _classify(before: object, after: object) -> tuple[str, str]:
    """Return (verdict, detail). verdict is 'same' | 'benign' | 'DEFECT'."""
    left, right = _parse_expression(before), _parse_expression(after)
    if isinstance(left, str) or isinstance(right, str):
        return ("same", "") if left == right else ("DEFECT", f"{left!r} -> {right!r}")

    shared = set(left) & set(right)
    for year in sorted(shared):
        if abs(left[year] - right[year]) > VALUE_TOLERANCE:
            return ("DEFECT", f"{year}: {left[year]} -> {right[year]}")

    only_before, only_after = set(left) - shared, set(right) - shared
    if only_before or only_after:
        # Scenario-year trimming is benign ONLY when the dropped/added years are
        # themselves zero; a dropped nonzero year is real data loss.
        for year in only_before:
            if abs(left[year]) > VALUE_TOLERANCE:
                return ("DEFECT", f"nonzero year {year}={left[year]} present before, gone after")
        for year in only_after:
            if abs(right[year]) > VALUE_TOLERANCE:
                return ("DEFECT", f"nonzero year {year}={right[year]} added by patch")
        return ("benign", f"zero-valued year-window change ({len(only_before)}/{len(only_after)})")
    return ("same", "")


def _read_seed(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name="LEAP", header=2)
    return frame[frame["Branch Path"].notna()].copy()


def _module_rows(frame: pd.DataFrame, prefixes: list[str]) -> pd.DataFrame:
    mask = False
    for prefix in prefixes:
        mask = mask | frame["Branch Path"].astype(str).str.startswith(prefix)
    return frame[mask].copy()


def _seed_path_for(economy: str) -> Path | None:
    matches = sorted(patcher.BASELINE_SEED_DIR.glob(f"leap_import_baseline_seed_{economy}_*.xlsx"))
    return matches[-1] if matches else None


def seed_is_too_old_to_compare(seed_path: Path) -> str | None:
    """Return why this seed cannot answer the question, or None if it can.

    A seed predating the current transformation rules disagrees with today's code
    by design, so the diff would measure that intended change and not the patcher.
    """
    match = _SEED_DATE_RE.search(seed_path.stem)
    if match is None:
        return (
            f"cannot read a date from {seed_path.name}; refusing rather than "
            "assuming it was built with current transformation rules"
        )
    stamp = match.group(1)
    if stamp < TRANSFORMATION_RULES_CHANGED:
        return (
            f"seed is stamped {stamp}, but transformation output rules changed in "
            f"{TRANSFORMATION_RULES_CHANGED} (8c32504, the multi_output default). "
            "A seed built before that disagrees with current code BY DESIGN -- "
            "capacity, historical production, efficiency, output shares and "
            "aux-fuel ratios all move by one exact ratio. Diffing it would report "
            "that intended correction as a patcher defect. Regenerate this "
            "economy's seed with a full run first, then re-run this harness."
        )
    return None


def run_for_economy(economy: str) -> str:
    """Return 'PASS' | 'DEFECT' | 'BLOCKED' | 'SKIPPED'."""
    seed_path = _seed_path_for(economy)
    if seed_path is None:
        print(f"[{economy}] SKIPPED — no seed in {patcher.BASELINE_SEED_DIR}")
        return "SKIPPED"

    stale_reason = seed_is_too_old_to_compare(seed_path)
    if stale_reason is not None:
        print(f"[{economy}] STALE-SEED — refusing to run, this cannot answer the question:")
        print(f"    {stale_reason}")
        return "STALE-SEED"

    cfg = patcher.MODULE_REGISTRY[MODULE]
    prefixes = cfg.resolve_strip_prefixes()
    before = _module_rows(_read_seed(seed_path), prefixes)
    print(f"[{economy}] seed={seed_path.name}  transformation rows before={len(before)}")

    backup_dir = Path(tempfile.mkdtemp(prefix=f"ungate_{economy}_"))
    backup = backup_dir / seed_path.name
    shutil.copy2(seed_path, backup)
    print(f"[{economy}] backup -> {backup}")

    try:
        # Bypass ONLY the gate: _run_patch_locked is what run_patch calls after
        # the auto_sector_keys check. Everything else is the real patcher.
        patcher._TEMPLATE_ID_LOOKUP_CACHE.clear()
        patcher._run_patch_locked(MODULE, [economy], True, cfg)
    except NotImplementedError:
        print(f"[{economy}] BLOCKED — gate still fired; _run_patch_locked is the wrong bypass")
        return "BLOCKED"
    except Exception as exc:
        message = str(exc)
        if "blocking validation findings remain" in message:
            print(
                f"[{economy}] BLOCKED — the SEED fails validation against its own "
                f"template, so the patcher correctly refused to write. This is a "
                f"stale/contaminated seed, NOT a patch defect. Regenerate the seed "
                f"and re-run.\n    {message[:300]}"
            )
            return "BLOCKED"
        print(f"[{economy}] BLOCKED — patcher raised: {type(exc).__name__}: {message[:300]}")
        return "BLOCKED"
    finally:
        after_frame = _read_seed(seed_path) if seed_path.exists() else None
        shutil.copy2(backup, seed_path)
        print(f"[{economy}] seed restored from backup")

    if after_frame is None:
        print(f"[{economy}] BLOCKED — seed vanished")
        return "BLOCKED"

    after = _module_rows(after_frame, prefixes)
    print(f"[{economy}] transformation rows after={len(after)}")

    left = before.set_index(KEY, drop=False)
    right = after.set_index(KEY, drop=False)
    left = left[~left.index.duplicated(keep="last")]
    right = right[~right.index.duplicated(keep="last")]

    only_before = left.index.difference(right.index)
    only_after = right.index.difference(left.index)
    shared = left.index.intersection(right.index)

    defects: list[str] = []
    benign = 0
    for key in shared:
        verdict, detail = _classify(left.loc[key, "Expression"], right.loc[key, "Expression"])
        if verdict == "DEFECT":
            defects.append(f"{key} :: {detail}")
        elif verdict == "benign":
            benign += 1

    print(f"\n[{economy}] === RESULT ===")
    print(f"  rows only BEFORE (patch dropped) : {len(only_before)}")
    print(f"  rows only AFTER  (patch invented): {len(only_after)}")
    print(f"  benign value differences         : {benign}")
    print(f"  NON-BENIGN value differences     : {len(defects)}")
    for line in defects[:15]:
        print(f"      {line}")
    for key in list(only_before)[:8]:
        print(f"      only-before: {key}")
    for key in list(only_after)[:8]:
        print(f"      only-after : {key}")

    passed = not len(only_before) and not len(only_after) and not defects
    print(f"  -> {'PASS' if passed else 'DEFECT'}")
    return "PASS" if passed else "DEFECT"


def main(economies: list[str] | None = None) -> None:
    targets = economies or DEFAULT_ECONOMIES
    print(f"[1] transformation ungate equivalence — economies={targets}")
    print("Compares POST-write vs POST-write. Never raw-vs-seed.\n")
    results = {economy: run_for_economy(economy) for economy in targets}

    print("\n" + "=" * 70)
    for economy, verdict in results.items():
        print(f"  {economy:8s} {verdict}")
    if all(v == "PASS" for v in results.values()):
        print(
            "\nAll PASS -> the gate's premise does not hold. Ungating is still NOT "
            "just deleting the gate: rewire the patcher's transformation path to be "
            "workbook-based via save_transformation_exports_with_split_targets (the "
            "transfers model) first, then drop auto_sector_keys. See work_queue [1]."
        )
    elif any(v == "STALE-SEED" for v in results.values()):
        print(
            "\nSTALE-SEED -> inconclusive, and NOT evidence either way. The seed on "
            "disk predates the current transformation rules, so a diff would measure "
            "that intended change rather than the patcher. Regenerate the economy's "
            "seed with a full run, then re-run this harness."
        )
    elif any(v == "BLOCKED" for v in results.values()):
        print(
            "\nBLOCKED -> inconclusive, and NOT evidence for the gate. A seed that "
            "fails its own template's validation blocks the write before any patch "
            "comparison happens. Regenerate that economy's seed first."
        )
    else:
        print("\nDEFECT -> the gate's premise holds for at least one economy. Keep it.")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
#%%
