"""Tiny decorator that lets Typer call ``async def`` command bodies.

Vanilla Typer (and the underlying Click) don't await coroutines — an
``async def`` command would print ``<coroutine ...>`` and exit. The
``async_command`` decorator wraps a coroutine in a sync trampoline that
Typer can register as a normal command, so command files stop carrying
the boilerplate pair of ``def cmd(...): asyncio.run(_cmd(...))`` plus
``async def _cmd(...)``.

Usage
-----

    @app.command()
    @async_command
    async def create(title: str = "") -> None:
        ...

The two decorators must be in this order: ``@app.command()`` outermost
(Typer registers the wrapper), ``@async_command`` inside (returns a
sync callable for Typer to register).
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def async_command(func: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """Wrap an ``async def`` Typer command body in :func:`asyncio.run`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(func(*args, **kwargs))

    return wrapper
