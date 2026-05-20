from __future__ import annotations

import zipfile
from pathlib import Path

from rich.console import Console
from rich.tree import Tree


def create_zip(file_tree: dict[str, str], output_path: Path) -> Path:
    zip_path = output_path.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filepath, content in file_tree.items():
            zf.writestr(filepath, content)
    return zip_path


def write_to_directory(file_tree: dict[str, str], output_dir: Path) -> None:
    for filepath, content in file_tree.items():
        full_path = output_dir / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)


def display_file_tree(file_tree: dict[str, str], console: Console | None = None) -> None:
    con = console or Console()
    tree = Tree("📁 Generated project")
    file_map: dict[str, Tree] = {}

    for filepath in sorted(file_tree.keys()):
        parts = filepath.split("/")
        current = tree
        for i, part in enumerate(parts):
            key = "/".join(parts[: i + 1])
            if key not in file_map:
                is_file = i == len(parts) - 1
                label = f"📄 {part}" if is_file else f"📁 {part}"
                file_map[key] = current.add(label)
            current = file_map[key]

    con.print(tree)


def print_success_summary(output_path: Path, file_count: int, console: Console | None = None) -> None:
    con = console or Console()
    con.print()
    con.print(f"[bold green]✓[/bold green] Generated {file_count} files")
    con.print(f"[bold green]✓[/bold green] Output: {output_path}")
    con.print()
    con.print("[dim]Next steps:[/dim]")
    con.print("  1. Review orchid.yml and agents.yaml")
    con.print("  2. Implement custom agent/tool handlers")
    con.print("  3. Run: ORCHID_CONFIG=orchid.yml uvicorn orchid_api.main:app")
