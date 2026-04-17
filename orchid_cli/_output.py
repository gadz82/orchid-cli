"""Shared terminal output helpers — keeps command error formatting consistent.

Commands used to spell errors as ``[red]...[/red]`` or ``[red]Error:[/red] ...``
inconsistently; :func:`print_error`, :func:`print_warning`, and
:func:`print_success` centralise the style so every command looks the
same in the user's terminal.
"""

from __future__ import annotations

from rich.console import Console

_default_console = Console()


def print_error(message: str, *, console: Console | None = None) -> None:
    """Render an error line as ``✗ <message>`` in red.

    Used by command handlers before raising :class:`typer.Exit(1)` so
    the user sees a consistent "something went wrong" line regardless
    of which command fired.
    """
    (console or _default_console).print(f"[red]✗[/red] {message}")


def print_warning(message: str, *, console: Console | None = None) -> None:
    """Render a non-fatal warning line."""
    (console or _default_console).print(f"[yellow]![/yellow] {message}")


def print_success(message: str, *, console: Console | None = None) -> None:
    """Render a success confirmation."""
    (console or _default_console).print(f"[green]✓[/green] {message}")


def print_info(message: str, *, console: Console | None = None) -> None:
    """Render a dimmed informational note."""
    (console or _default_console).print(f"[dim]{message}[/dim]")
