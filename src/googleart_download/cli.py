from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.table import Table

from .batch import BatchDownloadManager
from .batch_state import BatchStateStore, resolve_batch_state_path, resolve_failed_rerun_state_path
from .download.http_client import HttpClient
from .download.downloader import inspect_artwork_metadata, inspect_artwork_sizes
from .download.image_writer import resolve_output_path
from .errors import DownloadError, build_error_guidance
from .logging_utils import configure_logging
from .metadata.parsers import extract_asset_id, normalize_asset_url
from .models import BatchRunResult, DownloadSize, JsonObject, OutputConflictPolicy, RetryConfig, SizeOption, StitchBackend
from .reporters import build_reporter


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


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
        "--resume-batch",
        action="store_true",
        help="resume batch task state from the state file instead of starting a fresh batch",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="start a new batch using only the failed tasks recorded in the batch state file",
    )
    parser.add_argument(
        "--batch-state-file",
        help="custom path for the batch state JSON file (default: <output-dir>/.googleart-batch-state.json)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="compatibility alias for --output-conflict overwrite",
    )
    parser.add_argument(
        "--output-conflict",
        choices=[policy.value for policy in OutputConflictPolicy],
        default=OutputConflictPolicy.SKIP.value,
        help="what to do when the target output already exists: skip, overwrite, or rename (default: skip)",
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
        help="image stitch backend: auto, pillow, bigtiff, or pyvips (default: auto)",
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

    if not urls and not args.rerun_failed:
        raise DownloadError("provide at least one URL or use --url-file")

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
    if args.resume_batch and args.rerun_failed:
        raise DownloadError("--resume-batch cannot be used together with --rerun-failed")

    if args.resume_batch and args.metadata_only:
        raise DownloadError("--resume-batch cannot be used together with --metadata-only")

    if args.resume_batch and args.list_sizes:
        raise DownloadError("--resume-batch cannot be used together with --list-sizes")

    if args.batch_state_file and args.metadata_only:
        raise DownloadError("--batch-state-file cannot be used together with --metadata-only")

    if args.batch_state_file and args.list_sizes:
        raise DownloadError("--batch-state-file cannot be used together with --list-sizes")

    if args.rerun_failed and args.metadata_only:
        raise DownloadError("--rerun-failed cannot be used together with --metadata-only")

    if args.rerun_failed and args.list_sizes:
        raise DownloadError("--rerun-failed cannot be used together with --list-sizes")

    if args.rerun_failed and urls:
        raise DownloadError("--rerun-failed loads failed URLs from the batch state file and cannot be combined with direct batch URLs")

    if args.metadata_only and args.filename and len(urls) > 1:
        raise DownloadError("--filename cannot be used with multiple URLs in --metadata-only mode")

    if args.filename and len(urls) > 1:
        raise DownloadError("--filename can only be used with a single URL")

    if args.no_skip_existing and args.output_conflict != OutputConflictPolicy.SKIP.value:
        raise DownloadError("--no-skip-existing cannot be used together with --output-conflict")

    if args.metadata_output and not args.metadata_only:
        raise DownloadError("--metadata-output requires --metadata-only")

    if args.metadata_only and args.list_sizes:
        raise DownloadError("--metadata-only cannot be used together with --list-sizes")

    if args.list_sizes and len(urls) != 1:
        raise DownloadError("--list-sizes requires exactly one artwork URL")


def _needs_url_resolution(url: str) -> bool:
    normalized = normalize_asset_url(url)
    if normalized.startswith("https://g.co/"):
        return True
    parts = [part for part in normalized.split("/") if part]
    return len(parts) >= 4 and parts[-2] == "asset"


def canonicalize_batch_urls(urls: list[str], retry_config: RetryConfig) -> tuple[list[str], list[str]]:
    unique_urls: list[str] = []
    duplicate_messages: list[str] = []
    seen_by_asset_id: dict[str, str] = {}
    seen_by_url: set[str] = set()

    with HttpClient(retry_config=retry_config) as http_client:
        for raw_url in urls:
            normalized_url = normalize_asset_url(raw_url)
            canonical_url = normalized_url
            if _needs_url_resolution(normalized_url):
                canonical_url = normalize_asset_url(
                    http_client.resolve_url(normalized_url, description="artwork URL resolution")
                )

            asset_id = extract_asset_id(canonical_url)
            identity_key = asset_id or canonical_url
            if identity_key in seen_by_asset_id or canonical_url in seen_by_url:
                original = seen_by_asset_id.get(identity_key) or canonical_url
                duplicate_messages.append(
                    f"Duplicate artwork input skipped: {raw_url} -> {canonical_url} (same artwork as {original})"
                )
                continue

            unique_urls.append(canonical_url)
            seen_by_asset_id[identity_key] = canonical_url
            seen_by_url.add(canonical_url)

    return unique_urls, duplicate_messages


def load_failed_batch_urls(output_dir: Path, batch_state_file: str | None) -> tuple[list[str], Path, Path]:
    source_state_path = resolve_batch_state_path(output_dir, batch_state_file)
    failed_urls = BatchStateStore(source_state_path).load_failed_urls()
    rerun_state_path = resolve_failed_rerun_state_path(output_dir, batch_state_file)
    return failed_urls, source_state_path, rerun_state_path


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

    emit_metadata_output(results, metadata_output)
    return 0


def render_summary(run_result: BatchRunResult) -> None:
    console = Console()
    table = Table(title="Download Summary", header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Title / URL")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    reporter = None
    run_result: BatchRunResult | None = None

    try:
        urls = collect_urls(args)
        validate_cli_args(args, urls)
        configure_logging(verbose=args.verbose, log_file=args.log_file)
        reporter = build_reporter(args.tui)
        retry_config = RetryConfig(
            attempts=args.retries,
            backoff_base_seconds=args.retry_backoff,
        )
        batch_state_file = args.batch_state_file
        if args.list_sizes:
            title, options = inspect_artwork_sizes(urls[0], retry_config)
            render_size_options(title, options)
            return 0
        if args.metadata_only:
            return run_metadata_only(args, urls, retry_config)
        if args.rerun_failed:
            failed_urls, source_state_path, rerun_state_path = load_failed_batch_urls(Path(args.output_dir), args.batch_state_file)
            if not failed_urls:
                reporter.log(f"No failed tasks found in batch state file: {source_state_path}")
                return 0
            reporter.log(f"Loaded {len(failed_urls)} failed artwork(s) from {source_state_path}")
            reporter.log(f"Targeted rerun state file: {rerun_state_path}")
            urls = failed_urls
            batch_state_file = str(rerun_state_path)
        canonical_urls = urls
        if len(urls) > 1:
            canonical_urls, duplicate_messages = canonicalize_batch_urls(urls, retry_config)
            for message in duplicate_messages:
                reporter.log(message)
            if len(canonical_urls) != len(urls):
                reporter.log(f"Batch input normalized from {len(urls)} URL(s) to {len(canonical_urls)} unique artwork(s)")
        manager = BatchDownloadManager(
            urls=canonical_urls,
            output_dir=Path(args.output_dir),
            filename=args.filename,
            workers=max(1, args.workers),
            retry_config=retry_config,
            reporter=reporter,
            fail_fast=args.fail_fast,
            download_size=DownloadSize(args.size),
            max_dimension=args.max_dimension,
            output_conflict_policy=(
                OutputConflictPolicy.OVERWRITE if args.no_skip_existing else OutputConflictPolicy(args.output_conflict)
            ),
            write_metadata=args.write_metadata,
            write_sidecar=args.write_sidecar,
            stitch_backend=StitchBackend(args.stitch_backend),
            rerun_failures=args.rerun_failures,
            resume_batch=args.resume_batch,
            batch_state_file=batch_state_file,
        )
        run_result = manager.run()
    except DownloadError as exc:
        console = Console(stderr=True)
        console.print(f"[bold red]Error:[/bold red] {exc}")
        for line in build_error_guidance(str(exc)):
            console.print(f"[yellow]Hint:[/yellow] {line}")
        return 1
    finally:
        if reporter is not None:
            reporter.close()

    assert run_result is not None
    render_summary(run_result)
    return 0 if run_result.snapshot.failed == 0 else 1
