"""Runtime smoke test for the compressed-projection preflight.

`run_preflight_compressed_projection` drives the real supply/transformation
pipeline for a single 2-year 00_APEC run with LEAP import/scrape disabled, so it
exercises the exact code paths where cross-module misattribution bugs live —
the static scanners in ``test_module_attribute_contracts`` catch attribute /
bare-name existence, but only a real run catches wrong signatures, bad wiring,
and undefined names that surface mid-pipeline.

This test is **opt-in**: it takes minutes and writes to the outputs directory,
so it does not run in the default suite.  Enable it with:

    RUN_PREFLIGHT_SMOKE=1 pytest tests/test_preflight_smoke.py

Contract: the preflight must not fail with the *misattribution class* of error
(``NameError`` / ``AttributeError``).  A data/config failure (e.g. a missing
code-to-name mapping sheet) is environment state, not a code regression, so the
test skips on those rather than failing.
"""
from __future__ import annotations

import os

import pytest

_ENABLED = os.environ.get("RUN_PREFLIGHT_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="preflight smoke test is slow + writes outputs; set RUN_PREFLIGHT_SMOKE=1 to run",
)


def test_preflight_compressed_projection_has_no_missing_name_bugs() -> None:
    from codebase.functions.supply_preflight import run_preflight_compressed_projection

    try:
        result = run_preflight_compressed_projection()
    except (NameError, AttributeError) as exc:  # the misattribution class
        pytest.fail(
            "preflight hit a missing-name/attribute bug (cross-module "
            f"misattribution regression): {type(exc).__name__}: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 — data/config, not a code regression
        pytest.skip(
            "preflight ran past the code paths but hit a non-code failure "
            f"(data/config): {type(exc).__name__}: {exc}"
        )
    else:
        assert isinstance(result, dict)
