"""
External-agents command — list configured external-agent CLI delegation tools.

Usage:
    orchid external-agents list agents.yaml
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from orchid_ai.config.loader import load_config
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="External-agent CLI delegation tools", no_args_is_help=True)
console = Console()


@app.command(name="list")
def list_cmd(
    config_path: str = typer.Argument(..., help="Path to agents.yaml config file"),
):
    try:
        path = Path(config_path)
        if not path.exists():
            console.print(f"[red]File not found:[/red] {config_path}")
            raise typer.Exit(code=1)

        config = load_config(str(path))
        agents = config.external_agents

        if not agents:
            console.print("[dim]No external agents configured.[/dim]")
            return

        table = Table(title="External Agent CLI Tools")
        table.add_column("Name", style="bold")
        table.add_column("Command")
        table.add_column("Timeout (s)")
        table.add_column("Approval")
        table.add_column("Normalizer")
        table.add_column("Found")

        for name, cfg in agents.items():
            cmd_str = " ".join(cfg.command + cfg.args)
            found = shutil.which(cfg.command[0]) if cfg.command else None
            found_str = "[green]✓[/green]" if found else "[red]✗[/red]"
            approval_str = "[yellow]Yes[/yellow]" if cfg.requires_approval else "[dim]No[/dim]"
            timeout_str = f"{cfg.timeout:.0f}"
            normalizer_str = cfg.normalizer
            table.add_row(name, cmd_str, timeout_str, approval_str, normalizer_str, found_str)

        console.print(table)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Failed to load config:[/red] {exc}")
        raise typer.Exit(code=1)
