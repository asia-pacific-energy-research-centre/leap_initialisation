#%%
"""Carry a hand-edited user guide back into the repository, ready to ship.

The guide a colleague reads is a Word document. Screenshots and wording get
added to it *in Word*, in an extracted copy of the release - not in Markdown -
so the edited .docx has to travel back into the repository before the next
build, or the build ships the older one from the pinned commit.

Usage::

    python scripts/import_user_guide.py                       # find it automatically
    python scripts/import_user_guide.py --from "C:/path/to/guide.docx"
    python scripts/import_user_guide.py --check               # report, change nothing

Nothing is committed here: the copy is staged in the working tree and the
commit is left to whoever is running the build, so an accidental import is a
`git checkout` away from undone.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the guide lives in this repository. The builder reads exactly this
#: path out of the pinned commit (build_release.USER_GUIDE_SOURCE_PATH).
REPO_GUIDE = REPO_ROOT / "docs" / "docx" / "leap_review_tools_user_guide.docx"

#: The name the guide has inside an extracted release
#: (build_release.USER_GUIDE_PACKAGE_NAME).
PACKAGE_GUIDE_NAME = "LEAP Review Tools - user guide.docx"

#: Where an extracted release is normally unpacked. Searched in order; the
#: first that holds a guide wins. A path given with --from beats all of them.
SEARCH_ROOTS = (
    REPO_ROOT.parent / "leap-review-tools-0.1.0",
    REPO_ROOT / "release_build" / "package" / "leap-review-tools-0.1.0",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_edited_guide(explicit: Path | None = None) -> Path | None:
    """Locate the guide to import."""
    if explicit is not None:
        path = Path(explicit)
        return path if path.is_file() else None
    for root in SEARCH_ROOTS:
        candidate = root / PACKAGE_GUIDE_NAME
        if candidate.is_file():
            return candidate
    return None


def import_guide(source: Path, *, check_only: bool = False) -> int:
    """Copy *source* over the repository's guide if it differs."""
    if not REPO_GUIDE.parent.is_dir():
        print(f"No docs/docx directory at {REPO_GUIDE.parent}", file=sys.stderr)
        return 2

    if REPO_GUIDE.is_file() and _digest(source) == _digest(REPO_GUIDE):
        print(f"Unchanged: {source} matches the repository copy. Nothing to do.")
        return 0

    size_before = REPO_GUIDE.stat().st_size if REPO_GUIDE.is_file() else 0
    print(f"Edited guide : {source}  ({source.stat().st_size:,} bytes)")
    print(f"Repository   : {REPO_GUIDE}  ({size_before:,} bytes)")
    if check_only:
        print("\nDiffers. Re-run without --check to import it.")
        return 1

    shutil.copy2(source, REPO_GUIDE)
    try:
        to_add = REPO_GUIDE.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # Redirected somewhere outside the repository. The copy is done; only
        # the suggested command needs the absolute path instead.
        to_add = str(REPO_GUIDE)
    print("\nImported. Now commit it and re-pin before building:")
    print(f'  git add "{to_add}"')
    print('  git commit -m "Update the user guide"')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="the edited .docx to import; searched for if omitted",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether an import is needed, changing nothing",
    )
    args = parser.parse_args(argv)

    source = find_edited_guide(args.source)
    if source is None:
        looked = args.source or "\n  ".join(str(r / PACKAGE_GUIDE_NAME) for r in SEARCH_ROOTS)
        print(f"No edited guide found. Looked in:\n  {looked}", file=sys.stderr)
        return 2
    return import_guide(source, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
