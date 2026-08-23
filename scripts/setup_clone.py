#%%
"""Install a downloaded data bundle and verify a new clone before a long run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.extract_data_bundle import extract_data_bundle

REQUIRED_MODULES = ("numpy", "pandas", "openpyxl", "pyarrow", "plotly")
REQUIRED_COMPATIBILITY_FILES = (
    Path("config/LEAP_API_helpers.py"),
    Path("config/LEAP_API_utilities.py"),
)


def verify_clone_setup(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Return missing clone prerequisites without installing into another Python."""
    repo_root = Path(repo_root).resolve()
    for required_path in (repo_root, repo_root / "config"):
        if str(required_path) not in sys.path:
            sys.path.insert(0, str(required_path))
    missing_modules = [
        module_name
        for module_name in REQUIRED_MODULES
        if importlib.util.find_spec(module_name) is None
    ]
    missing_files = [
        relative_path.as_posix()
        for relative_path in REQUIRED_COMPATIBILITY_FILES
        if not (repo_root / relative_path).is_file()
    ]
    required_paths = (repo_root, repo_root / "config")
    missing_sys_paths = [
        str(path)
        for path in required_paths
        if str(path) not in sys.path
    ]
    return {
        "missing_modules": missing_modules,
        "missing_files": missing_files,
        "missing_sys_paths": missing_sys_paths,
    }


def install_bundle_and_verify(
    downloaded_zip_path: Path,
    repo_root: Path = REPO_ROOT,
    allow_overwrite: bool = False,
) -> list[Path]:
    """Install a regular or Google Drive wrapper ZIP, then fail clearly if unready."""
    installed = extract_data_bundle(
        bundle_path=downloaded_zip_path,
        repo_root=repo_root,
        allow_overwrite=allow_overwrite,
    )
    findings = verify_clone_setup(repo_root)
    problems = [
        f"missing Python packages: {', '.join(findings['missing_modules'])}",
        f"missing tracked compatibility files: {', '.join(findings['missing_files'])}",
    ]
    problems = [problem for problem in problems if not problem.endswith(": ")]
    if problems:
        raise RuntimeError(
            "Clone data was installed, but the selected interpreter is not ready.\n"
            + "\n".join(problems)
            + "\nRun this notebook-style script with the intended Windows conda interpreter, "
            "then install any reported packages into that same interpreter."
        )
    print(f"Clone setup passed with interpreter: {sys.executable}")
    return installed


#%%
# --- Frequently changed run settings ---

INSTALL_DOWNLOADED_BUNDLE = False
DOWNLOADED_ZIP_PATH: Path | None = None
ALLOW_OVERWRITE = False

if __name__ == "__main__":
    if INSTALL_DOWNLOADED_BUNDLE:
        if DOWNLOADED_ZIP_PATH is None:
            raise ValueError("Set DOWNLOADED_ZIP_PATH before installing a data bundle.")
        install_bundle_and_verify(
            downloaded_zip_path=DOWNLOADED_ZIP_PATH,
            repo_root=REPO_ROOT,
            allow_overwrite=ALLOW_OVERWRITE,
        )
    else:
        print(verify_clone_setup(REPO_ROOT))

#%%
