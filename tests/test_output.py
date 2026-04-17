"""Tests for the shared terminal output helpers."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from orchid_cli._output import print_error, print_info, print_success, print_warning


def _capture(fn, message: str) -> str:
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120)
    fn(message, console=console)
    return buf.getvalue()


class TestOutputHelpers:
    def test_error_has_cross_glyph(self):
        output = _capture(print_error, "something went wrong")
        assert "✗" in output
        assert "something went wrong" in output

    def test_warning_has_exclamation_glyph(self):
        output = _capture(print_warning, "careful")
        assert "!" in output
        assert "careful" in output

    def test_success_has_check_glyph(self):
        output = _capture(print_success, "all good")
        assert "✓" in output
        assert "all good" in output

    def test_info_has_no_glyph(self):
        output = _capture(print_info, "fyi")
        assert "fyi" in output
