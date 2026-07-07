"""Regression tests for long-running workflow output logging."""

from io import StringIO

from codebase.supply_reconciliation_workflow import _TeeWriter


class _BrokenConsole:
    """Represent a detached Windows console whose handle is no longer valid."""

    def write(self, _data):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


def test_tee_writer_continues_file_logging_after_console_write_failure():
    log_file = StringIO()
    writer = _TeeWriter(log_file, _BrokenConsole())

    assert writer.write("workflow output") == len("workflow output")
    writer.write(" after failure")
    writer.flush()

    logged = log_file.getvalue()
    assert "workflow output" in logged
    assert "continuing with file logging only" in logged
    assert logged.endswith(" after failure")


def test_tee_writer_mirrors_output_while_console_is_available():
    log_file = StringIO()
    console = StringIO()
    writer = _TeeWriter(log_file, console)

    writer.write("workflow output")
    writer.flush()

    assert log_file.getvalue() == "workflow output"
    assert console.getvalue() == "workflow output"
