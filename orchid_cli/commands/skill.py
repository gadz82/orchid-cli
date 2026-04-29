"""
Skill command — generate Claude Code skills from Orchid agent configuration.

Usage:
    orchid skill generate examples/basketball/agents.yaml --output .claude/skills
    orchid skill generate examples/helpdesk/config/agents.yaml -o ./skills --include basketball,psychologist

The 630-line monolith was decomposed: ``_skill_md`` builds the SKILL.md
files, ``_skill_tools`` generates the executable tool wrappers,
``_skill_guardrails`` renders the guardrail section, and ``_skill_text``
holds tiny string helpers. This module owns the Typer surface only.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

from orchid_ai.config.loader import load_config

from ._skill_md import generate_agent_skill, generate_orchestrator_skill

app = typer.Typer(help="Generate Claude Code skills from Orchid config", no_args_is_help=True)
console = Console()


@app.command()
def generate(
    config_path: str = typer.Argument(..., help="Path to agents.yaml config file"),
    output: str = typer.Option(".claude/skills", "-o", "--output", help="Output directory for generated skills"),
    include: str | None = typer.Option(
        None, "--include", help="Comma-separated agent/skill names to include (default: all)"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing skill directories"),
    zip_archive: bool = typer.Option(False, "--zip", help="Create a zip archive of the generated skills"),
) -> None:
    """Generate Claude Code skill folders from an Orchid agents.yaml configuration."""
    try:
        config = load_config(config_path)
    except Exception as exc:
        console.print(f"[red]Error loading config:[/red] {exc}")
        raise typer.Exit(code=1)

    out_dir = Path(output)
    include_set = {n.strip() for n in include.split(",")} if include else None

    generated: list[str] = []
    skipped: list[str] = []

    for agent_name, agent_cfg in config.agents.items():
        if include_set and agent_name not in include_set:
            continue
        skill_dir = out_dir / agent_name
        if skill_dir.exists() and not overwrite:
            skipped.append(agent_name)
            continue
        generate_agent_skill(skill_dir, agent_name, agent_cfg, config)
        generated.append(agent_name)

    for skill_name, skill_cfg in config.skills.items():
        if include_set and skill_name not in include_set:
            continue
        skill_dir = out_dir / skill_name
        if skill_dir.exists() and not overwrite:
            skipped.append(skill_name)
            continue
        generate_orchestrator_skill(skill_dir, skill_name, skill_cfg, config)
        generated.append(skill_name)

    if generated:
        console.print(f"\n[green]Generated {len(generated)} skill(s):[/green]")
        for name in generated:
            console.print(f"  [bold]{out_dir / name}/SKILL.md[/bold]")
    if skipped:
        console.print(f"\n[yellow]Skipped {len(skipped)} (already exist, use --overwrite):[/yellow]")
        for name in skipped:
            console.print(f"  {name}")
    if not generated and not skipped:
        console.print("[yellow]No agents or skills matched the filter.[/yellow]")

    if zip_archive and generated:
        zip_path = Path(f"{output.rstrip('/')}.zip")
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=out_dir.parent, base_dir=out_dir.name)
        console.print(f"\n[green]Archive created:[/green] [bold]{zip_path}[/bold]")
