"""Report whether preset overrides reach the modules that read them.

Import-only diagnostic for docs/work_queue.md [17]. It never calls
``run_with_config()`` or any other entry point, so it acquires no economy run
locks and writes nothing to ``outputs/`` - safe to run alongside a live run.

For every key any ``_PRESET_*`` dict can set, it compares the wrapper's value
against every loaded ``codebase`` module that defines that name, and splits the
disagreements by whether the module actually *reads* the name as a module
global (AST: loaded, never stored or bound, i.e. it arrived via
``from ... import *``) or merely holds an unread stale copy.

Exit code 0 when no module that reads a preset key disagrees with the wrapper,
except for names deliberately withheld in ``_PRESET_BROADCAST_PINS``.

    python scripts/check_preset_forwarding.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codebase.supply_reconciliation_workflow as wrapper  # noqa: E402

_READS_CACHE: dict[str, frozenset[str]] = {}


def _module_globals_read_by(module) -> frozenset[str]:
    """Names the module loads but never binds - its ``import *`` config copies.

    Source is read as utf-8-sig: several codebase modules carry a UTF-8 BOM
    that makes naive ``ast.parse`` tooling fail on them.
    """
    cached = _READS_CACHE.get(module.__name__)
    if cached is not None:
        return cached
    path = getattr(module, "__file__", None)
    if not path or not str(path).endswith(".py"):
        _READS_CACHE[module.__name__] = frozenset()
        return frozenset()
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"), filename=str(path))
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    stored = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                bound |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(
            node.target, ast.Name
        ):
            bound.add(node.target.id)
    result = frozenset(loaded - stored - bound)
    _READS_CACHE[module.__name__] = result
    return result


def _loaded_codebase_modules():
    return [
        (name, module)
        for name, module in sorted(sys.modules.items())
        if module is not None
        and (name == "codebase" or name.startswith("codebase."))
        and name != wrapper.__name__
    ]


def main() -> int:
    # Mirror what a run does before the saver executes, so the comparison is
    # against run-time state rather than bare import state.
    wrapper._sync_results_saver_overrides()

    pins = set(wrapper._PRESET_BROADCAST_PINS)
    preset_keys = sorted(set(wrapper._preset_override_names()) | pins)
    modules = _loaded_codebase_modules()

    print(f"loaded codebase modules: {len(modules)}")
    print(f"preset keys: {len(preset_keys)}  (withheld pins: {sorted(pins) or 'none'})\n")

    read_disagreements: list[tuple[str, str, object, object]] = []
    stale_copies: list[tuple[str, str, object, object]] = []
    checked = 0

    for key in preset_keys:
        if not hasattr(wrapper, key):
            continue
        want = getattr(wrapper, key)
        for module_name, module in modules:
            module_dict = getattr(module, "__dict__", None)
            if module_dict is None or key not in module_dict:
                continue
            reads = key in _module_globals_read_by(module)
            if reads:
                checked += 1
            if module_dict[key] == want:
                continue
            entry = (key, module_name, module_dict[key], want)
            (read_disagreements if reads else stale_copies).append(entry)

    print(f"(name, module) pairs where the module reads the key: {checked}\n")

    print("Modules that READ a preset key and disagree with the wrapper")
    print("-" * 74)
    unexpected = []
    for key, module_name, have, want in read_disagreements:
        tag = "pinned " if key in pins else "DEFECT "
        if key not in pins:
            unexpected.append((key, module_name))
        print(f"  {tag}{key}\n          {module_name}: holds {have!r}, wrapper has {want!r}")
    if not read_disagreements:
        print("  (none)")

    print()
    print("Unread stale copies (no behaviour attached)")
    print("-" * 74)
    for key, module_name, have, want in stale_copies:
        print(f"  {key}\n          {module_name}: holds {have!r}, wrapper has {want!r}")
    if not stale_copies:
        print("  (none)")

    print()
    for key in sorted(pins):
        effective = None
        for _module_name, module in modules:
            if key in getattr(module, "__dict__", {}) and key in _module_globals_read_by(module):
                effective = getattr(module, key)
                break
        print(f"pinned {key}: wrapper={getattr(wrapper, key)!r}, effective={effective!r}")

    if unexpected:
        print(f"\nFAIL: {len(unexpected)} unpinned preset key(s) do not reach a reader.")
        return 1
    print("\nOK: every preset key reaches every module that reads it, except the pins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
