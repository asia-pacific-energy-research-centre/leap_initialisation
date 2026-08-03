"""Entry point of the built portable release.

This module is the ``main`` of the frozen Windows application. It resolves
everything relative to the package folder it is running from — never from a
maintainer's checkout, never from the current working directory, never from an
environment variable pointing at a repository — reads the frozen release
manifest that the builder wrote beside it, and dispatches to the same command
implementations developer mode uses.

It offers a small guided flow when run with no arguments (so a colleague can
double-click the executable) and an explicit command line for automation. There
is no GUI framework: the guided flow is plain prompts on the console.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


FROZEN_MANIFEST_NAME = "release_manifest.json"


def package_root() -> Path:
    """Return the root of the running package.

    Frozen (PyInstaller ``--onedir``): the folder holding the executable.
    Unfrozen (the staged folder, used by the build's own smoke test): the folder
    two levels above this module, i.e. ``<package>/code/leap_initialisation/...``
    resolved back to ``<package>``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # <package>/code/<stage_dir>/codebase/portable_release/portable_main.py
    return Path(__file__).resolve().parents[4]


def load_frozen_manifest(root: Path) -> dict[str, Any]:
    path = root / FROZEN_MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(
            f"This package is incomplete: {FROZEN_MANIFEST_NAME} is missing from {root}.\n"
            "Re-extract the release folder, or ask for a fresh copy."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_portable_context(root: Path | None = None):
    """Build the runtime context for the package this module lives in."""
    from codebase.portable_release.runtime import portable_context

    resolved_root = Path(root) if root is not None else package_root()
    frozen = load_frozen_manifest(resolved_root)
    config_root = resolved_root / "config"
    config_assets = {
        asset["role"]: config_root / asset["dest"]
        for asset in frozen.get("config_assets", [])
    }
    context = portable_context(
        release_name=frozen["release"]["name"],
        release_version=frozen["release"]["version"],
        package_root=resolved_root,
        code_root=resolved_root / "code",
        sys_path_stage_dirs=[
            spec["stage_dir"]
            for spec in frozen.get("repositories", {}).values()
            if spec.get("on_sys_path", True)
        ],
        config_assets=config_assets,
        release_commits={
            key: spec["commit"] for key, spec in frozen.get("repositories", {}).items()
        },
    )
    context.activate_sys_path()
    return context, frozen


def _prompt(question: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip().strip('"')
    return answer or default


def _guided_flow(context, frozen: dict[str, Any]) -> int:
    """Ask for the inputs one command needs, then run it."""
    commands = frozen.get("commands", [])
    print()
    print(f"{context.release_name} {context.release_version}")
    print("=" * 72)
    print(f"Package folder : {context.package_root}")
    print(f"Put input files in: {context.input_root}")
    print(f"Results appear in : {context.output_root}")
    print()
    print("Available commands:")
    for index, spec in enumerate(commands, start=1):
        print(f"  {index}. {spec['name']} - {spec['summary']}")
    print("  q. quit")
    print()
    choice = _prompt("Choose a command by number", default="1").lower()
    if choice in {"q", "quit", "exit"}:
        return 0
    try:
        spec = commands[int(choice) - 1]
    except (ValueError, IndexError):
        print(f"'{choice}' is not one of the listed choices.")
        return 2

    print()
    print(spec["summary"])
    print(f"Input mode: {spec['input_mode']}")
    print(f"Produces  : {spec['outputs']}")
    print()
    values: dict[str, str] = {}
    for item in spec["inputs"]:
        print(f"{item['key']} - {item['description']}")
        values[item["key"]] = _prompt(f"  {item['kind']} path or value")
        print()

    if spec["name"] == "balance-review":
        return _dispatch_balance_review(context, values)
    if spec["name"] == "dashboard":
        return _dispatch_dashboard(context, values)
    print(f"Command {spec['name']!r} has no implementation in this release.")
    return 2


def _report(result) -> int:
    print()
    print("\n".join(result.summary_lines()))
    print()
    if not result.ok:
        print("The run did not complete. The validation report explains why:")
        print(f"  {result.run_directory / 'validation_report.txt'}")
        print("Send the support bundle if you need help:")
        print("  it contains the run record and logs, but no input data.")
        return 1
    print(f"Run manifest: {result.manifest_paths['text']}")
    return 0


def _dispatch_balance_review(context, values: dict[str, str]) -> int:
    from codebase.portable_release.commands import run_balance_review
    from codebase.portable_release.runtime import run_logging

    with run_logging(context, "balance-review"):
        result = run_balance_review(
            context,
            economy=values.get("economy", ""),
            scenario=values.get("scenario", ""),
            year=int(values.get("year") or 0),
            balance_export_workbook=values.get("balance_export_workbook", ""),
            diagnostics_directory=values.get("diagnostics_directory", ""),
        )
    return _report(result)


def _dispatch_dashboard(context, values: dict[str, str]) -> int:
    from codebase.portable_release.commands import run_dashboard
    from codebase.portable_release.runtime import run_logging

    with run_logging(context, "dashboard"):
        result = run_dashboard(
            context,
            economy=values.get("economy", ""),
            comparison_data_path=values.get("comparison_data_path", ""),
            common_rows_path=values.get("common_rows_path", ""),
        )
    return _report(result)


def build_parser(frozen: dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=frozen["release"]["name"],
        description=frozen["release"].get("description", ""),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{frozen['release']['name']} {frozen['release']['version']}",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("info", help="Show this release's contents, commands, and folders.")

    declared = {spec["name"] for spec in frozen.get("commands", [])}
    if "balance-review" in declared:
        review = sub.add_parser(
            "balance-review",
            help="Build a balance-review workbook from existing diagnostic artifacts.",
        )
        review.add_argument("--economy", required=True)
        review.add_argument("--scenario", required=True)
        review.add_argument("--year", required=True, type=int)
        review.add_argument("--balance-export-workbook", required=True)
        review.add_argument("--diagnostics-directory", required=True)
        review.add_argument("--run-label", default=None)
        review.add_argument("--support-bundle", action="store_true")

    if "dashboard" in declared:
        dashboard = sub.add_parser(
            "dashboard",
            help="Render the Common ESTO dashboard for one economy.",
        )
        dashboard.add_argument("--economy", required=True)
        dashboard.add_argument("--comparison-data-path", required=True)
        dashboard.add_argument("--common-rows-path", required=True)
        dashboard.add_argument("--comparison-scope", default="esto_leap_ninth")
        dashboard.add_argument("--min-year", type=int, default=2010)
        dashboard.add_argument("--max-year", type=int, default=2060)
        dashboard.add_argument("--run-label", default=None)
        dashboard.add_argument("--support-bundle", action="store_true")

    return parser


def _print_info(context, frozen: dict[str, Any]) -> int:
    print(context.describe())
    print()
    print("Commands")
    print("-" * 72)
    for spec in frozen.get("commands", []):
        print(f"  {spec['name']}")
        print(f"    {spec['summary']}")
        print(f"    input mode: {spec['input_mode']}")
        print(f"    produces  : {spec['outputs']}")
        for item in spec["inputs"]:
            flag = "required" if item.get("required", True) else "optional"
            print(f"      - {item['key']} ({item['kind']}, {flag}): {item['description']}")
    print()
    print("Runtime packages this release was built against")
    print("-" * 72)
    for package in frozen.get("runtime", {}).get("packages", []):
        print(f"  {package}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    context, frozen = build_portable_context()

    problems = context.preflight()
    if problems:
        print("This release is not usable as extracted:")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    if not args:
        try:
            return _guided_flow(context, frozen)
        except (EOFError, KeyboardInterrupt):
            print()
            return 130

    parser = build_parser(frozen)
    namespace = parser.parse_args(args)
    if namespace.command in (None, "info"):
        return _print_info(context, frozen)

    from codebase.portable_release.commands import (
        run_balance_review,
        run_dashboard,
        write_support_bundle,
    )
    from codebase.portable_release.runtime import run_logging

    with run_logging(context, namespace.command):
        if namespace.command == "balance-review":
            result = run_balance_review(
                context,
                economy=namespace.economy,
                scenario=namespace.scenario,
                year=namespace.year,
                balance_export_workbook=namespace.balance_export_workbook,
                diagnostics_directory=namespace.diagnostics_directory,
                run_label=namespace.run_label,
            )
        else:
            result = run_dashboard(
                context,
                economy=namespace.economy,
                comparison_data_path=namespace.comparison_data_path,
                common_rows_path=namespace.common_rows_path,
                comparison_scope=namespace.comparison_scope,
                min_year=namespace.min_year,
                max_year=namespace.max_year,
                run_label=namespace.run_label,
            )

    exit_code = _report(result)
    if getattr(namespace, "support_bundle", False):
        bundle = write_support_bundle(context, result)
        print(f"Support bundle: {bundle}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
