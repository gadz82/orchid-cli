"""
Config command — validate YAML configuration files.

Usage:
    orchid config validate examples/basketball/orchid.yml
"""

from __future__ import annotations

import typer
from rich.console import Console

from orchid_ai.config.loader import load_config

app = typer.Typer(help="Configuration management", no_args_is_help=True)
console = Console()


@app.command()
def validate(
    config_path: str = typer.Argument(..., help="Path to agents.yaml config file"),
):
    """Validate an agents.yaml configuration file."""
    try:
        config = load_config(config_path)
        console.print(f"[green]Valid[/green] — {len(config.agents)} agent(s) configured:")
        for name, agent_cfg in config.agents.items():
            desc = agent_cfg.description[:60] if agent_cfg.description else "(no description)"
            cls = agent_cfg.class_path or "GenericAgent"
            console.print(f"  [bold]{name}[/bold] ({cls}) — {desc}")

        if config.supervisor:
            console.print(f"\n  Supervisor: assistant_name={config.supervisor.assistant_name!r}")
        if config.skills:
            console.print(f"  Orchestrator skills: {len(config.skills)}")
    except Exception as exc:
        console.print(f"[red]Invalid[/red] — {exc}")
        raise typer.Exit(code=1)
