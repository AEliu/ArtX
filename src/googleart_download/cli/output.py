from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..download.image_writer import resolve_output_path
from ..errors import DownloadError
from ..models import BatchRunResult, DownloadSize, JsonObject, SizeOption, StitchBackend


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def render_size_options(title: str, options: list[SizeOption]) -> None:
    console = Console()
    table = Table(title=f"Available Sizes: {title}", header_style="bold cyan")
    table.add_column("Level")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Raw Canvas", justify="right")
    table.add_column("Auto Output", justify="right")

    for option in options:
        table.add_row(
            str(option.level.z),
            f"{option.width}x{option.height}",
            str(option.tile_count),
            _format_bytes(option.raw_memory_bytes),
            "TIFF" if option.default_backend is StitchBackend.BIGTIFF else "JPG",
        )

    console.print(table)
    if any(option.default_backend is StitchBackend.BIGTIFF for option in options):
        console.print(
            "[cyan]Note:[/cyan] Rows marked TIFF will default to the streaming BigTIFF path in "
            "`--stitch-backend auto` for large-image safety."
        )


def write_metadata_output_file(output_path: Path, payload: str) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise DownloadError(f"failed to write metadata output file: {output_path}: {exc}") from exc


def emit_metadata_output(results: list[JsonObject], output_path: str | None) -> None:
    payload = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    if output_path:
        output_file = Path(output_path)
        write_metadata_output_file(output_file, payload)
        Console(stderr=True).print(f"[cyan]•[/cyan] Metadata saved: {output_file}")
    else:
        Console().print_json(payload)


def resolve_default_metadata_output_path(
    *,
    output_dir: str,
    filename: str | None,
    title: str,
    download_size: DownloadSize,
    max_dimension: int | None,
) -> Path:
    image_path = resolve_output_path(
        Path(output_dir),
        filename,
        title,
        download_size=download_size,
        max_dimension=max_dimension,
    )
    return image_path.with_suffix(".metadata.json")


def render_summary(run_result: BatchRunResult) -> None:
    console = Console()
    table = Table(title="Download Summary", header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Artwork")
    table.add_column("Format", justify="right")
    table.add_column("Backend", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Attempts", justify="right")
    table.add_column("Path / Error")
    table.add_column("Sidecar")

    for result in run_result.succeeded:
        status = "skipped" if result.skipped else "ok"
        image_format = result.output_path.suffix.lower().lstrip(".").upper() or "-"
        backend = result.backend_used.value if result.backend_used is not None else "-"
        size = "-" if result.size is None else f"{result.size[0]}x{result.size[1]}"
        tiles = "-" if result.tile_count is None else str(result.tile_count)
        attempts = next((str(task.attempts) for task in run_result.snapshot.tasks if task.result == result), "-")
        table.add_row(
            status,
            result.title,
            image_format,
            backend,
            size,
            tiles,
            attempts,
            str(result.output_path),
            str(result.sidecar_path) if result.sidecar_path else "-",
        )
    for task in run_result.failed:
        table.add_row("failed", task.url, "-", "-", "-", "-", str(task.attempts), task.error or "unknown error", "-")
    console.print(table)
