from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .._output import print_error, print_success

app = typer.Typer(
    help="Interactive wizard to scaffold a complete Orchid project",
    no_args_is_help=True,
    invoke_without_command=True,
)
console = Console()


@app.callback()
def generate_flower(
    output: str = typer.Option(".", "--output", "-o", help="Output directory for the generated project"),
    no_zip: bool = typer.Option(False, "--no-zip", help="Write files directly instead of creating a zip"),
    ai: bool = typer.Option(False, "--ai", help="Enable AI-assisted question answering"),
    ai_model: str = typer.Option("ollama/llama3.2", "--ai-model", help="LLM model for AI assistance"),
    from_seed: str = typer.Option("", "--from-seed", help="Load answers from a JSON seed file"),
    verbose: bool = typer.Option(False, "--verbose", help="Show all questions, even with defaults"),
) -> None:
    """Interactive wizard to create a complete Orchid project skeleton.

    Guides you through infrastructure, agents, tools, skills, and more,
    then generates orchid.yml, agents.yaml, and Python scaffold files.
    """
    from ._flower.scaffolding import ScaffoldGenerator
    from ._flower.output import create_zip, display_file_tree, print_success_summary, write_to_directory
    from ._flower.wizard import Wizard

    wizard = Wizard(console=console)

    if from_seed:
        import json

        seed_path = Path(from_seed).expanduser()
        if not seed_path.exists():
            print_error(f"Seed file not found: {seed_path}")
            raise typer.Exit(code=1)
        with open(seed_path) as f:
            wizard.answers = json.load(f)
        print_success(f"Loaded answers from {seed_path}")

    success = wizard.run_all_phases()
    if not success:
        console.print("[yellow]Wizard cancelled.[/yellow]")
        raise typer.Exit(code=0)

    project_name = wizard.get_nested("project.name") or "my_orchid_project"
    output_dir = Path(output).expanduser()

    scaffold = ScaffoldGenerator(wizard.answers, project_name)
    file_tree = scaffold.generate()

    display_file_tree(file_tree, console=console)

    if no_zip:
        write_to_directory(file_tree, output_dir)
        print_success_summary(output_dir, len(file_tree), console=console)
    else:
        zip_path = create_zip(file_tree, output_dir / project_name)
        print_success_summary(zip_path, len(file_tree), console=console)
