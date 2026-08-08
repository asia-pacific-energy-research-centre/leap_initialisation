"""Regression tests for optional console output in hosted workers."""

from __future__ import annotations

import sys

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "codebase.functions.transformation_analysis_utils",
        "codebase.functions.transformation_record_builder",
    ],
)
def test_safe_print_line_survives_missing_stdout(module_name, monkeypatch) -> None:
    module = __import__(module_name, fromlist=["_safe_print_line"])
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "__stdout__", None)

    # Hosted Gradio/ZeroGPU workers can expose no usable console stream. Debug
    # output must remain optional and must not abort the actual workflow.
    module._safe_print_line("non-ascii label — optional debug text")
