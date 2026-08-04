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
    data_root = resolved_root / "data"
    data_assets = {
        asset["role"]: data_root / asset["dest"]
        for asset in frozen.get("data_assets", [])
    }
    # In a frozen build the program modules live inside the executable's own
    # bundle, so there is no code/ directory to put on sys.path. The staged
    # (unfrozen) package keeps one, and the build's smoke test runs that way.
    stage_dirs = (
        []
        if getattr(sys, "frozen", False)
        else [
            spec["stage_dir"]
            for spec in frozen.get("repositories", {}).values()
            if spec.get("on_sys_path", True)
        ]
    )
    context = portable_context(
        release_name=frozen["release"]["name"],
        release_version=frozen["release"]["version"],
        package_root=resolved_root,
        code_root=resolved_root / "code",
        sys_path_stage_dirs=stage_dirs,
        config_assets=config_assets,
        data_assets=data_assets,
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
    # Someone using this menu rather than a terminal is exactly who needs these
    # two, and they were the only way to reach them. The guide opens by telling
    # users to run `list` before anything else.
    print("  l. list - Show which economies and exports this release can see.")
    print("  c. check - Confirm the package is complete and working.")
    print("  q. quit")
    print()

    # Default to an export-first command: a colleague has LEAP exports and not a
    # diagnostics folder, so plain `balance-review` - which was the default
    # purely by being first - sends them to the one command they cannot run.
    default_choice = "1"
    for index, spec in enumerate(commands, start=1):
        if spec["name"].endswith("-from-export"):
            default_choice = str(index)
            break

    choice = _prompt("Choose a command by number", default=default_choice).lower()
    if choice in {"q", "quit", "exit"}:
        return 0
    if choice in {"l", "list"}:
        print()
        from codebase.portable_release import workspace

        print(
            workspace.describe_workspace(
                workspace.balance_exports_root(context.input_root)
            )
        )
        return 0
    if choice in {"c", "check", "selfcheck"}:
        print()
        return selfcheck(context, frozen)[0]
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
        label = "path" if item["kind"] in {"file", "directory"} else "value"
        values[item["key"]] = _prompt(f"  {label}")
        print()

    if spec["name"] == "balance-review":
        return _dispatch_balance_review(context, values)
    if spec["name"] == "balance-review-from-export":
        return _dispatch_balance_review_from_export(context, values)
    if spec["name"] == "dashboard":
        return _dispatch_dashboard(context, values)
    if spec["name"] == "dashboard-from-export":
        return _dispatch_dashboard_from_export(context, values)
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


def _dispatch_balance_review_from_export(
    context,
    values: dict[str, str],
) -> int:
    from codebase.portable_release.commands import run_balance_review_from_export
    from codebase.portable_release.runtime import run_logging

    with run_logging(context, "balance-review-from-export"):
        result = run_balance_review_from_export(
            context,
            economy=values.get("economy", ""),
            scenario=values.get("scenario", ""),
            year=int(values.get("year") or 0),
            balance_export_workbook=(
                values.get("balance_export_workbook") or None
            ),
            esto_table_path=values.get("esto_table_path") or None,
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


def _dispatch_dashboard_from_export(context, values: dict[str, str]) -> int:
    from codebase.portable_release.commands import run_dashboard_from_export
    from codebase.portable_release.runtime import run_logging

    with run_logging(context, "dashboard-from-export"):
        result = run_dashboard_from_export(
            context,
            economy=values.get("economy", ""),
            export_dir=values.get("export_dir") or None,
            comparison_data_path=values.get("comparison_data_path") or None,
            common_rows_path=values.get("common_rows_path") or None,
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
    sub.add_parser(
        "list",
        help="List the economies this release has balance exports for.",
    )
    sub.add_parser(
        "selfcheck",
        help="Import everything a run needs and confirm the package is intact.",
    )

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

    if "balance-review-from-export" in declared:
        review_from_export = sub.add_parser(
            "balance-review-from-export",
            help="Build a balance-review workbook directly from a LEAP balance export.",
        )
        review_from_export.add_argument("--economy", required=True)
        review_from_export.add_argument("--scenario", required=True)
        review_from_export.add_argument("--year", required=True, type=int)
        review_from_export.add_argument(
            "--balance-export-workbook",
            default=None,
            help="Defaults to input/leap balances exports/<ECONOMY>/.",
        )
        review_from_export.add_argument("--esto-table-path", default=None)
        review_from_export.add_argument("--run-label", default=None)
        review_from_export.add_argument("--support-bundle", action="store_true")

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

    if "dashboard-from-export" in declared:
        dashboard_from_export = sub.add_parser(
            "dashboard-from-export",
            help="Render the Common ESTO dashboard for one economy from a LEAP balance export.",
        )
        dashboard_from_export.add_argument("--economy", required=True)
        dashboard_from_export.add_argument(
            "--export-dir",
            default=None,
            help="Defaults to input/leap balances exports/<ECONOMY>/.",
        )
        dashboard_from_export.add_argument(
            "--comparison-data-path",
            default=None,
            help="Escape hatch: skip the mapping chain and use this file directly.",
        )
        dashboard_from_export.add_argument("--common-rows-path", default=None)
        dashboard_from_export.add_argument(
            "--esto-table-path",
            default=None,
            help=(
                "Use your own ESTO base table instead of the one supplied with "
                "this release. The comparison rows are re-derived from it, which "
                "adds a few minutes to the first run against a given table."
            ),
        )
        dashboard_from_export.add_argument("--comparison-scope", default="esto_leap_ninth")
        dashboard_from_export.add_argument("--min-year", type=int, default=2010)
        dashboard_from_export.add_argument("--max-year", type=int, default=2060)
        dashboard_from_export.add_argument("--run-label", default=None)
        dashboard_from_export.add_argument("--support-bundle", action="store_true")

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


#: Standard-library modules a run reaches for, together with an attribute that
#: only the real module has. A packaging accident that replaces one of these
#: with an empty namespace package imports cleanly and then fails deep inside a
#: run, so the attribute is checked too.
_REQUIRED_STDLIB = [
    ("csv", "reader"),
    ("json", "loads"),
    ("hashlib", "sha256"),
    ("zipfile", "ZipFile"),
    ("zoneinfo", "ZoneInfo"),
    ("re", "compile"),
    ("logging", "getLogger"),
    ("subprocess", "run"),
]

#: Third-party and packaged modules every supported command needs.
_REQUIRED_MODULES = [
    "pandas",
    "numpy",
    "openpyxl",
    "plotly.graph_objects",
    "codebase.portable_release.commands",
    "codebase.portable_release.validation",
    "codebase.portable_release.provenance",
    "codebase.portable_release.runtime",
    "codebase.portable_release.mapping_chain_client",
    "codebase.portable_release.workspace",
    "codebase.balance_update_workflow",
    "codebase.functions.balance_review_workbook_builder",
    "codebase.functions.baseline_seed_balance_diagnostics",
    "codebase.utilities.leap_balance_export_resolver",
    "common_esto_dashboard_portable",
    "mapping_tools.source_branch_preflight",
]


def selfcheck(context, frozen: dict[str, Any]) -> tuple[int, list[str]]:
    """Import everything a run needs and confirm the configuration is present.

    This is what the builder runs against a freshly frozen executable, and what
    a colleague can run when something looks wrong. It exists because a packaged
    program can start, print its own version, and still be broken: a missing
    hidden import or a shadowed standard-library module only surfaces once a
    real command reaches for it.
    """
    import importlib

    problems: list[str] = []
    for name, attribute in _REQUIRED_STDLIB:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"standard library module {name!r} does not import: {exc}")
            continue
        if not hasattr(module, attribute):
            problems.append(
                f"standard library module {name!r} is shadowed: it has no {attribute!r} "
                f"(loaded from {getattr(module, '__file__', 'an unknown location')})."
            )
    for name in _REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"module {name!r} does not import: {exc}")

    for asset in frozen.get("config_assets", []):
        path = context.config_asset(asset["role"])
        if path is None or not path.is_file():
            problems.append(f"configuration asset {asset['role']!r} is missing: {path}")

    for name in ("input", "output", "logs", "config"):
        directory = context.package_root / name
        if not directory.is_dir():
            problems.append(f"package folder {name}/ is missing.")

    print(f"{context.release_name} {context.release_version} self-check")
    print("-" * 72)
    print(f"  standard library modules : {len(_REQUIRED_STDLIB)}")
    print(f"  program modules          : {len(_REQUIRED_MODULES)}")
    print(f"  configuration assets     : {len(frozen.get('config_assets', []))}")
    if problems:
        print("  result                   : FAILED")
        for problem in problems:
            print(f"    - {problem}")
        return 2, problems
    print("  result                   : OK")
    return 0, problems


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
    if namespace.command == "selfcheck":
        return selfcheck(context, frozen)[0]
    if namespace.command == "list":
        from codebase.portable_release import workspace

        print(workspace.describe_workspace(workspace.balance_exports_root(context.input_root)))
        return 0

    from codebase.portable_release.commands import (
        run_balance_review,
        run_balance_review_from_export,
        run_dashboard,
        run_dashboard_from_export,
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
        elif namespace.command == "balance-review-from-export":
            result = run_balance_review_from_export(
                context,
                economy=namespace.economy,
                scenario=namespace.scenario,
                year=namespace.year,
                balance_export_workbook=namespace.balance_export_workbook,
                esto_table_path=namespace.esto_table_path,
                run_label=namespace.run_label,
            )
        elif namespace.command == "dashboard-from-export":
            result = run_dashboard_from_export(
                context,
                economy=namespace.economy,
                export_dir=namespace.export_dir,
                esto_table_path=namespace.esto_table_path,
                comparison_data_path=namespace.comparison_data_path,
                common_rows_path=namespace.common_rows_path,
                comparison_scope=namespace.comparison_scope,
                min_year=namespace.min_year,
                max_year=namespace.max_year,
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
