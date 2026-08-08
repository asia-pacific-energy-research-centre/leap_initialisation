#%%
"""Raise the release version and start its changelog entry.

Several builds went out as 0.1.0 with materially different behaviour, and
nobody holding one could say which they had. Bumping is cheap; the reason it
did not happen is that it was two edits in two files with nothing to prompt
either. This does both, and refuses to bump without an entry to write in.

Usage::

    python scripts/bump_release_version.py minor      # 0.1.0 -> 0.2.0
    python scripts/bump_release_version.py patch      # 0.2.0 -> 0.2.1
    python scripts/bump_release_version.py major      # 0.2.0 -> 1.0.0
    python scripts/bump_release_version.py 1.4.2      # exactly this
    python scripts/bump_release_version.py minor --dry-run

Which part to raise is a judgement about the person receiving it:

* **patch** — same behaviour, something that was broken now works;
* **minor** — new or changed behaviour they will notice and should read about;
* **major** — they have to do something differently, or results change.

Nothing is committed. Write the entry, then commit both files together.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "config" / "portable_release_manifest.toml"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"

VERSION_LINE = re.compile(r'^(version = ")(\d+)\.(\d+)\.(\d+)(")$', re.M)

#: Written under the new heading. Deliberately not empty: a blank entry is easy
#: to leave blank, and a prompt naming the reader is harder to answer badly.
ENTRY_TEMPLATE = """## {version}

<!-- What is different for someone USING the tools? Delete this comment.
     Not "refactored the runner" - say what they will see, and what to do
     about it. Internal work belongs in the commit history, not here. -->

"""


def read_current_version(text: str) -> tuple[int, int, int]:
    match = VERSION_LINE.search(text)
    if match is None:
        raise SystemExit(f"No 'version = \"X.Y.Z\"' line found in {MANIFEST}")
    return int(match.group(2)), int(match.group(3)), int(match.group(4))


def next_version(current: tuple[int, int, int], part: str) -> str:
    major, minor, patch = current
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if re.fullmatch(r"\d+\.\d+\.\d+", part):
        return part
    raise SystemExit(f"Expected major, minor, patch, or an X.Y.Z version - got {part!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", help="major, minor, patch, or an explicit X.Y.Z")
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would change, change nothing"
    )
    args = parser.parse_args(argv)

    manifest_text = MANIFEST.read_text(encoding="utf-8")
    current = read_current_version(manifest_text)
    new = next_version(current, args.part)
    current_text = ".".join(str(n) for n in current)

    if new == current_text:
        print(f"Already at {new}. Nothing to do.")
        return 0

    changelog_text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.is_file() else ""
    if f"## {new}" in changelog_text:
        print(f"{CHANGELOG.name} already has a '## {new}' entry; leaving it alone.")

    print(f"{current_text}  ->  {new}")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    MANIFEST.write_text(
        VERSION_LINE.sub(rf'\g<1>{new}\g<5>', manifest_text, count=1), encoding="utf-8"
    )

    if f"## {new}" not in changelog_text:
        # Insert above the newest existing entry so the file reads newest-first.
        entry = ENTRY_TEMPLATE.format(version=new)
        marker = "\n## "
        index = changelog_text.find(marker)
        if index == -1:
            changelog_text = (changelog_text.rstrip() + "\n\n" + entry) if changelog_text else entry
        else:
            changelog_text = (
                changelog_text[: index + 1] + entry + "---\n\n" + changelog_text[index + 1 :]
            )
        CHANGELOG.write_text(changelog_text, encoding="utf-8")

    print(f"\nWritten:\n  {MANIFEST}\n  {CHANGELOG}")
    print("\nNow write the entry, then commit both and re-pin:")
    print("  git add config/portable_release_manifest.toml docs/CHANGELOG.md")
    print(f'  git commit -m "Release {new}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
