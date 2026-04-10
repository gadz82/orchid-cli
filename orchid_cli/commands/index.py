"""
Index command — seed the vector store with data.

Usage:
    orchid index seed --config examples/basketball/orchid.yml --tenant default
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from orchid.core.repository import VectorWriter
from orchid.rag.indexer import StaticIndexer


app = typer.Typer(help="Vector store indexing", no_args_is_help=True)
console = Console()


@app.command()
def seed(
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant ID for indexing"),
):
    """Seed the vector store with static data."""
    asyncio.run(_seed(config, tenant))


async def _seed(config_path: str, tenant: str) -> None:
    from ..bootstrap import cli_context

    async with cli_context(config_path) as ctx:
        if not isinstance(ctx.reader, VectorWriter):
            console.print("[red]Error:[/red] Vector store does not support writing (backend may be 'null')")
            raise typer.Exit(code=1)

        indexer = StaticIndexer(writer=ctx.reader)
        counts = await indexer.index_all(tenant_key=tenant)

        console.print(f"[green]Indexed[/green] for tenant={tenant}:")
        for namespace, count in counts.items():
            console.print(f"  {namespace}: {count} document(s)")
