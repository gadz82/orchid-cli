"""
Orchid CLI — command-line interface for the Orchid agent framework.

Usage:
    orchid chat "What are LeBron's stats?" --config examples/basketball/orchid.yml
    orchid chat --interactive --config examples/basketball/orchid.yml
    orchid config validate examples/basketball/orchid.yml
    orchid index --config examples/basketball/orchid.yml
"""

from __future__ import annotations

import typer

from .commands import chat, config, index, skill

app = typer.Typer(
    name="orchid",
    help="Orchid — multi-agent AI framework CLI",
    no_args_is_help=True,
)

app.add_typer(chat.app, name="chat")
app.add_typer(config.app, name="config")
app.add_typer(index.app, name="index")
app.add_typer(skill.app, name="skill")


if __name__ == "__main__":
    app()
