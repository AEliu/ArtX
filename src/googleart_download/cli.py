from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.table import Table

from .batch import BatchDownloadManager
from .download.downloader import inspect_artwork_metadata, inspect_artwork_sizes
from .download.image_writer import resolve_output_path
from .errors import DownloadError, build_error_guidance
from .logging_utils import configure_logging
from .models import BatchRunResult, DownloadSize, RetryConfig, SizeOption, StitchBackend
from .reporters import build_reporter


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download high-resolution Google Arts & Culture images by stitching tiles.",
    )
    parser.add_argument("urls", nargs="*", help="one or more Google Arts & Culture asset URLs")
    parser.add_argument("--url-file", help="text file with one asset URL per line")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="destination directory (default: downloads)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="output filename, only valid when downloading a single URL",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=min(16, (os.cpu_count() or 4) * 2),
        help="concurrent tile downloads (default: auto)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="request retry attempts for pages, metadata, and tiles (default: 3)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=0.75,
        help="base backoff in seconds before retrying failed requests (default: 0.75)",
    )
    parser.add_argument(
        "--rerun-failures",
        type=int,
        default=0,
        help="how many extra batch rounds to rerun artworks that still failed after request-level retries",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the batch immediately after the first failed artwork",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="download again even if the target file already exists",
    )
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument(
        "--size",
        choices=[size.value for size in DownloadSize],
        default=DownloadSize.MAX.value,
        help="download size preset: preview, medium, large, or max (default: max)",
    )
    size_group.add_argument(
        "--max-dimension",
        type=int,
        help="choose the largest available level whose longest edge does not exceed this size",
    )
    parser.add_argument(
        "--write-metadata",
        action="store_true",
        help="write artwork metadata into the output JPEG EXIF",
    )
    parser.add_argument(
        "--write-sidecar",
        action="store_true",
        help="write artwork metadata to a JSON sidecar next to the image",
    )
    parser.add_argument(
        "--stitch-backend",
        choices=[backend.value for backend in StitchBackend],
        default=StitchBackend.AUTO.value,
        help="image stitch backend: auto, pillow, or pyvips (default: auto)",
    )
    parser.add_argument(
        "--list-sizes",
        action="store_true",
        help="inspect available download sizes for a single artwork URL and exit",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="fetch artwork metadata only and output JSON without downloading image tiles",
    )
    parser.add_argument(
        "--metadata-output",
        help="write metadata-only JSON output to a file instead of stdout",
    )
    parser.add_argument("--tui", action="store_true", help="show a richer live terminal dashboard")
    parser.add_argument("--log-file", help="write logs to a file")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args(argv)


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = list(args.urls)

    if args.url_file:
        file_urls = [
            line.strip()
            for line in Path(args.url_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        urls.extend(file_urls)

    if not urls:
        raise DownloadError("provide at least one URL or use --url-file")

    if args.filename and len(urls) > 1:
        raise DownloadError("--filename can only be used with a single URL")

    if args.retries < 1:
        raise DownloadError("--retries must be at least 1")

    if args.retry_backoff < 0:
        raise DownloadError("--retry-backoff must be >= 0")

    if args.rerun_failures < 0:
        raise DownloadError("--rerun-failures must be >= 0")

    if args.max_dimension is not None and args.max_dimension < 1:
        raise DownloadError("--max-dimension must be at least 1")

    return urls


def validate_cli_args(args: argparse.Namespace, urls: list[str]) -> None:
    if args.metadata_output and not args.metadata_only:
        raise DownloadError("--metadata-output requires --metadata-only")

    if args.metadata_only and args.list_sizes:
        raise DownloadError("--metadata-only cannot be used together with --list-sizes")

    if args.list_sizes and len(urls) != 1:
        raise DownloadError("--list-sizes requires exactly one artwork URL")


def render_size_options(title: str, options: list[SizeOption]) -> None:
    console = Console()
    table = Table(title=f"Available Sizes: {title}", header_style="bold cyan")
    table.add_column("Level")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Longest Edge", justify="right")

    for option in options:
        table.add_row(
            str(option.level.z),
            f"{option.width}x{option.height}",
            str(option.tile_count),
            str(max(option.width, option.height)),
        )

    console.print(table)


def write_metadata_output_file(output_path: Path, payload: str) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise DownloadError(f"failed to write metadata output file: {output_path}: {exc}") from exc


def render_metadata_output(results: list[dict[str, object]], output_path: str | None) -> None:
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


def run_metadata_only(args: argparse.Namespace, urls: list[str], retry_config: RetryConfig) -> int:
    results = [inspect_artwork_metadata(url, retry_config) for url in urls]
    metadata_output = args.metadata_output

    if metadata_output is None and len(urls) == 1:
        title = results[0].get("title")
        resolved_title = title if isinstance(title, str) and title else "google-art"
        metadata_output = str(
            resolve_default_metadata_output_path(
                output_dir=args.output_dir,
                filename=args.filename,
                title=resolved_title,
                download_size=DownloadSize(args.size),
                max_dimension=args.max_dimension,
            )
        )
    elif metadata_output is None and len(urls) > 1:
        Console(stderr=True).print(
            "[cyan]•[/cyan] Multiple URLs with --metadata-only default to a JSON array on stdout. "
            "Use --metadata-output to save to a file."
        )

    render_metadata_output(results, metadata_output)
    return 0


def render_summary(run_result: BatchRunResult) -> None:
    console = Console()
    table = Table(title="Download Summary", header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Title / URL")
    table.add_column("Size", justify="right")
    table.add_column("Tiles", justify="right")
    table.add_column("Attempts", justify="right")
    table.add_column("Path / Error")
    table.add_column("Sidecar")

    for result in run_result.succeeded:
        status = "skipped" if result.skipped else "ok"
        size = "-" if result.size is None else f"{result.size[0]}x{result.size[1]}"
        tiles = "-" if result.tile_count is None else str(result.tile_count)
        attempts = next((str(task.attempts) for task in run_result.snapshot.tasks if task.result == result), "-")
        table.add_row(
            status,
            result.title,
            size,
            tiles,
            attempts,
            str(result.output_path),
            str(result.sidecar_path) if result.sidecar_path else "-",
        )
    for task in run_result.failed:
        table.add_row("failed", task.url, "-", "-", str(task.attempts), task.error or "unknown error", "-")
    console.print(table)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(verbose=args.verbose, log_file=args.log_file)

    reporter = build_reporter(args.tui)
    retry_config = RetryConfig(
        attempts=args.retries,
        backoff_base_seconds=args.retry_backoff,
    )
    run_result: BatchRunResult | None = None

    try:
        urls = collect_urls(args)
        validate_cli_args(args, urls)
        if args.list_sizes:
            title, options = inspect_artwork_sizes(urls[0], retry_config)
            render_size_options(title, options)
            return 0
        if args.metadata_only:
            return run_metadata_only(args, urls, retry_config)
        manager = BatchDownloadManager(
            urls=urls,
            output_dir=Path(args.output_dir),
            filename=args.filename,
            workers=max(1, args.workers),
            retry_config=retry_config,
            reporter=reporter,
            fail_fast=args.fail_fast,
            download_size=DownloadSize(args.size),
            max_dimension=args.max_dimension,
            skip_existing=not args.no_skip_existing,
            write_metadata=args.write_metadata,
            write_sidecar=args.write_sidecar,
            stitch_backend=StitchBackend(args.stitch_backend),
            rerun_failures=args.rerun_failures,
        )
        run_result = manager.run()
    except DownloadError as exc:
        console = Console(stderr=True)
        console.print(f"[bold red]Error:[/bold red] {exc}")
        for line in build_error_guidance(str(exc)):
            console.print(f"[yellow]Hint:[/yellow] {line}")
        return 1
    finally:
        reporter.close()

    assert run_result is not None
    render_summary(run_result)
    return 0 if run_result.snapshot.failed == 0 else 1
