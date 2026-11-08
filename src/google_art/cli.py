from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .models import AsyncOptions
from .planning import is_directory_output
from .service import download_many

app = typer.Typer(help="Download artworks from Google Arts & Culture in custom formats and sizes.")
console = Console()


def error_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        return [message for child in exc.exceptions for message in error_messages(child)]
    return [str(exc)]


@app.command()
def download(
    assets: Annotated[list[str] | None, typer.Argument(help="Artwork URLs or asset slugs/IDs.")] = None,
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file or directory."),
    fmt: str = typer.Option("png", "--format", "-f", help="Image format (png, jpg, webp)."),
    size: int | None = typer.Option(None, "--size", "-s", min=1, help="Maximum image edge in pixels."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files."),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable progress bar."),
    assembler: str = typer.Option("auto", "--assembler", help="Image assembler: auto|pillow|vips"),
    net_concurrency: int = typer.Option(32, "--net-concurrency", min=1, help="Global network concurrency"),
    per_asset_concurrency: int = typer.Option(
        8, "--per-asset-concurrency", min=1, help="Per-asset network concurrency"
    ),
    queue_size: int = typer.Option(256, "--queue-size", min=1, help="Buffered tiles per asset"),
    jobs: int = typer.Option(3, "--jobs", min=1, help="How many assets to download in parallel"),
    from_file: Path | None = typer.Option(None, "--from-file", help="Read assets from a newline-delimited file"),
) -> None:
    asset_list = list(assets or [])
    if from_file:
        try:
            asset_list.extend(
                line.strip() for line in from_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()
            )
        except (OSError, UnicodeError) as exc:
            raise typer.BadParameter(f"Failed to read --from-file: {exc}") from exc
    if not asset_list:
        raise typer.BadParameter("Provide at least one asset or use --from-file")
    if len(asset_list) > 1 and output is not None and not is_directory_output(output):
        raise typer.BadParameter("Multiple assets require an output directory")
    try:
        requests = [
            AsyncOptions(
                asset=asset,
                out_path=str(output) if output is not None else None,
                max_edge=size,
                fmt=fmt,
                overwrite=overwrite,
                assembler=assembler,
                net_concurrency=net_concurrency,
                per_asset_concurrency=per_asset_concurrency,
                queue_size=queue_size,
            )
            for asset in asset_list
        ]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        paths = asyncio.run(download_many(requests, jobs=jobs, show_progress=not no_progress))
    except Exception as exc:
        # Structured concurrency may report nested failures; show their useful causes.
        for message in dict.fromkeys(error_messages(exc)):
            console.print(f"Download failed: {message}", style="red", markup=False)
        raise typer.Exit(code=1) from exc
    if len(paths) == 1:
        console.print(f"Saved artwork to {paths[0]}", style="green", markup=False)
    else:
        console.print(f"Saved {len(paths)} artworks:", style="green")
        for path in paths:
            console.print(f"  - {path}", markup=False)


if __name__ == "__main__":
    app()
