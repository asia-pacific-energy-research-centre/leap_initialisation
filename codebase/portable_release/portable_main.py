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


def _pause_before_closing() -> None:
    """Keep a double-clicked console window open until the user is done reading."""
    try:
        print()
        input("Press Enter to close this window. ")
    except (EOFError, KeyboardInterrupt):
        pass


def _build_stamp(frozen: dict[str, Any]) -> str:
    """Return ' (built 2026-08-05)', or nothing if the date is unavailable.

    A version number alone cannot tell two copies apart, and in practice it
    did not: several builds went out as 0.1.0 with materially different
    behaviour, and nobody holding one could say which they had. The build date
    settles it in the first line a user sees, and it is the first thing to ask
    for when someone reports a problem.
    """
    built = str(frozen.get("built_utc", ""))[:10]
    return f"  (built {built})" if len(built) == 10 else ""


def _guided_flow(context, frozen: dict[str, Any]) -> int:
    """Ask for an economy, scenario and year, then produce both outputs.

    Deliberately not a menu of the four commands. Those exist because the
    underlying tools take different inputs, which is a distinction about how the
    code is organised and not one a user should have to make: told "1. balance-
    review / 2. balance-review-from-export", there is no way to know which one
    fits without knowing what a diagnostics folder is. Someone here has LEAP
    exports and wants to see what is wrong with their model.

    So this asks the three things only they can answer, and runs both tools.
    Every path is still available on the command line for anyone who wants one
    of them on its own.
    """
    from codebase.portable_release import workspace

    exports_root = workspace.balance_exports_root(context.input_root)
    print()
    print(f"{context.release_name} {context.release_version}{_build_stamp(frozen)}")
    print("=" * 72)
    # Say what the program does before asking anything. Someone opening this for
    # the first time was previously shown two folder paths and a numbered list,
    # with nothing explaining what was about to happen to them.
    print("This reads the energy balances you exported from LEAP and produces")
    print("two things for one economy:")
    print()
    print("  * a balance-review workbook - where LEAP disagrees with ESTO, by")
    print("    flow and product, for the year(s) you choose;")
    print("  * a dashboard - LEAP against ESTO and the 9th, as charts you open")
    print("    in a browser.")
    print()
    print(f"  Reading exports from : {exports_root}")
    print(f"  Writing results to   : {context.output_root}")
    print("=" * 72)
    print()

    found = [item for item in workspace.discover_economies(exports_root) if item.workbooks]
    if not found:
        print("No LEAP balance exports found yet.")
        print()
        print(workspace.describe_workspace(exports_root))
        return 1

    print("Economies I can see exports for:")
    print()
    for index, item in enumerate(found, start=1):
        scenarios = ", ".join(w.scenario for w in item.workbooks)
        years = f"{min(item.years)}-{max(item.years)}" if item.years else "years unknown"
        print(f"  {index}. {item.economy}  ({scenarios};  {years})")
    print()
    print("  c. check that this copy is working")
    print("  q. quit")
    print()
    # Spell out the interaction. "[1]" is obvious only to someone who already
    # knows the convention; a new user cannot tell whether it is a label, a
    # count, or something they are meant to type.
    print(f"Type a number from the list above (1 to {len(found)}) and press Enter.")
    print("Press Enter on its own to accept the [default] shown in brackets.")
    print()

    choice = _prompt("Economy number", default="1").strip().lower()
    if choice in {"q", "quit", "exit"}:
        return 0
    if choice in {"c", "check", "selfcheck"}:
        print()
        return selfcheck(context, frozen)[0]
    chosen = None
    for index, item in enumerate(found, start=1):
        if choice in {str(index), item.economy.lower()}:
            chosen = item
            break
    if chosen is None:
        print(f"'{choice}' is not one of the economies listed above.")
        print(f"Type a number from 1 to {len(found)}, or q to quit.")
        return 2

    print()
    scenarios = [w.scenario for w in chosen.workbooks]
    if len(scenarios) == 1:
        scenario = scenarios[0]
        print(f"Scenario: {scenario} - the only one exported for {chosen.economy}.")
    else:
        print(f"{chosen.economy} has both scenarios exported.")
        print(f"Type {' or '.join(scenarios)} and press Enter.")
        scenario = _prompt("Scenario", default=scenarios[-1])

    print()
    suggested = workspace._suggested_review_year(chosen.years)
    span = (
        f"{min(chosen.years)} to {max(chosen.years)}"
        if chosen.years
        else "the years in your export"
    )
    print("Which year should the balance review compare?")
    print(f"  The workbook checks LEAP against ESTO for the year(s) you name.")
    print(f"  Your export covers {span}. {suggested} is the base year LEAP is")
    print("  calibrated on, which is usually the one worth checking first.")
    print("  For more than one year, separate them with commas: 2022,2030,2040")
    print("  (each year adds a few minutes, and produces its own workbook).")
    years_text = _prompt("Year(s)", default=str(suggested))
    print()

    print(f"Running both tools for {chosen.economy} {scenario} {years_text}.")
    print("This takes several minutes; each step is printed as it starts.")
    print()

    values = {"economy": chosen.economy, "scenario": scenario, "year": years_text}
    review_status = _dispatch_balance_review_from_export(context, values)
    print()
    print("-" * 72)
    print()
    dashboard_status = _dispatch_dashboard_from_export(context, {"economy": chosen.economy})

    print()
    print("=" * 72)
    economy_output = workspace.economy_output_root(context.output_root, chosen.economy)
    print(f"Balance review : {'done' if review_status == 0 else 'FAILED'}")
    print(f"Dashboard      : {'done' if dashboard_status == 0 else 'FAILED'}")
    print(f"Both are under : {economy_output}")
    # Neither failure should hide the other: the review can succeed while the
    # dashboard fails, and a user needs to know they still have a workbook.
    return 0 if review_status == 0 and dashboard_status == 0 else 1


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
        # Double-clicking opens a console that closes the moment this returns,
        # taking the output with it. Anything printed here - a listing, a
        # self-check, an error - is unreadable unless we wait first. This must
        # cover the failure paths too, since those are the ones worth reading.
        try:
            return _guided_flow(context, frozen)
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        except Exception as exc:  # noqa: BLE001 - shown, then paused on
            print()
            print(f"Something went wrong: {type(exc).__name__}: {exc}")
            print("Send the logs folder to whoever gave you these tools.")
            return 2
        finally:
            _pause_before_closing()

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
