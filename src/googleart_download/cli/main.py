from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from rich.console import Console

from ..download.http_client import HttpClient
from ..download.stitch_from_tiles import stitch_from_tile_directory
from ..errors import DownloadError, build_error_guidance
from ..logging_utils import configure_logging
from ..models import (
    BatchRunResult,
    BatchSnapshot,
    BatchTask,
    DownloadSize,
    JsonObject,
    OutputConflictPolicy,
    RetryConfig,
    SizeOption,
    StitchBackend,
    TaskState,
)
from ..reporting import Reporter
from .args import (
    BARE_ASSET_ID_PATTERN,
    JPEG_PRESET_QUALITIES,
    _preprocess_argv,
    parse_args,
    parse_jpeg_quality,
    resolve_jpeg_quality,
)
from .inputs import (
    _needs_url_resolution,
    canonicalize_batch_urls,
    collect_urls,
    load_failed_batch_urls,
    validate_cli_args,
)
from .output import (
    emit_metadata_output,
    render_size_options,
    render_summary,
    resolve_default_metadata_output_path,
    write_metadata_output_file,
)

__all__ = [
    "BARE_ASSET_ID_PATTERN",
    "JPEG_PRESET_QUALITIES",
    "_needs_url_resolution",
    "_preprocess_argv",
    "canonicalize_batch_urls",
    "collect_urls",
    "emit_metadata_output",
    "load_failed_batch_urls",
    "main",
    "parse_args",
    "parse_jpeg_quality",
    "render_size_options",
    "render_summary",
    "resolve_default_metadata_output_path",
    "resolve_jpeg_quality",
    "run_metadata_only",
    "validate_cli_args",
    "write_metadata_output_file",
    "BatchRunResult",
    "DownloadSize",
    "JsonObject",
    "OutputConflictPolicy",
    "RetryConfig",
    "SizeOption",
    "StitchBackend",
    "HttpClient",
]


def run_metadata_only(
    args: argparse.Namespace,
    urls: list[str],
    retry_config: RetryConfig,
    *,
    reporter: Reporter | None = None,
) -> int:
    canonical_urls = urls
    if len(urls) > 1:
        from . import canonicalize_batch_urls, inspect_artwork_metadata

        canonical_urls, duplicate_messages = canonicalize_batch_urls(urls, retry_config, proxy_url=args.proxy)
        for message in duplicate_messages:
            if reporter is not None:
                reporter.log(message)
        if len(canonical_urls) != len(urls) and reporter is not None:
            reporter.log(
                f"Metadata-only input normalized from {len(urls)} URL(s) to {len(canonical_urls)} unique artwork(s)"
            )

    from . import inspect_artwork_metadata

    results = [inspect_artwork_metadata(url, retry_config, proxy_url=args.proxy) for url in canonical_urls]
    metadata_output = args.metadata_output

    if metadata_output is None and len(canonical_urls) == 1:
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
    elif metadata_output is None and len(canonical_urls) > 1:
        Console(stderr=True).print(
            "[cyan]•[/cyan] Multiple URLs with --metadata-only default to a JSON array on stdout. "
            "Use --metadata-output to save to a file."
        )

    emit_metadata_output(results, metadata_output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    reporter = None
    run_result: BatchRunResult | None = None

    try:
        urls = collect_urls(args)
        validate_cli_args(args, urls)
        configure_logging(verbose=args.verbose, log_file=args.log_file)
        from . import build_reporter, canonicalize_batch_urls, inspect_artwork_sizes, load_failed_batch_urls

        reporter = build_reporter(args.tui)
        retry_config = RetryConfig(
            attempts=args.retries,
            backoff_base_seconds=args.retry_backoff,
        )
        batch_state_file = args.batch_state_file
        if args.list_sizes:
            title, options = inspect_artwork_sizes(urls[0], retry_config, proxy_url=args.proxy)
            render_size_options(title, options)
            return 0
        if args.metadata_only:
            return run_metadata_only(args, urls, retry_config, reporter=reporter)
        if args.stitch_from_tiles:
            result = stitch_from_tile_directory(
                tile_dir=Path(args.stitch_from_tiles),
                output_dir=Path(args.output_dir),
                filename=args.filename,
                jpeg_quality=resolve_jpeg_quality(args),
                output_conflict_policy=(
                    OutputConflictPolicy.OVERWRITE
                    if args.no_skip_existing
                    else OutputConflictPolicy(args.output_conflict)
                ),
                stitch_backend=StitchBackend(args.stitch_backend),
                reporter=reporter,
            )
            task_state = TaskState.SKIPPED if result.skipped else TaskState.SUCCEEDED
            task = BatchTask(index=1, url=result.url, state=task_state, result=result, attempts=1)
            run_result = BatchRunResult(
                snapshot=BatchSnapshot(tasks=[task]),
                succeeded=[result],
                failed=[],
            )
            if result.skipped:
                reporter.task_skipped(task)
            else:
                reporter.artwork_finished(result)
            render_summary(run_result)
            return 0
        if args.rerun_failed:
            failed_urls, source_state_path, rerun_state_path = load_failed_batch_urls(
                Path(args.output_dir), args.batch_state_file
            )
            if not failed_urls:
                reporter.log(f"No failed tasks found in batch state file: {source_state_path}")
                return 0
            reporter.log(f"Loaded {len(failed_urls)} failed artwork(s) from {source_state_path}")
            reporter.log(f"Targeted rerun state file: {rerun_state_path}")
            urls = failed_urls
            batch_state_file = str(rerun_state_path)
        canonical_urls = urls
        if len(urls) > 1:
            canonical_urls, duplicate_messages = canonicalize_batch_urls(urls, retry_config, proxy_url=args.proxy)
            for message in duplicate_messages:
                reporter.log(message)
            if len(canonical_urls) != len(urls):
                reporter.log(
                    f"Batch input normalized from {len(urls)} URL(s) to {len(canonical_urls)} unique artwork(s)"
                )
        if args.pipeline_artworks and len(canonical_urls) < 2:
            raise DownloadError("--pipeline-artworks requires at least two artwork URLs in the batch")
        from . import BatchDownloadManager

        manager = BatchDownloadManager(
            urls=canonical_urls,
            output_dir=Path(args.output_dir),
            filename=args.filename,
            workers=max(1, args.workers),
            jpeg_quality=resolve_jpeg_quality(args),
            retry_config=retry_config,
            proxy_url=args.proxy,
            reporter=reporter,
            fail_fast=args.fail_fast,
            download_size=DownloadSize(args.size),
            max_dimension=args.max_dimension,
            output_conflict_policy=(
                OutputConflictPolicy.OVERWRITE if args.no_skip_existing else OutputConflictPolicy(args.output_conflict)
            ),
            write_metadata=args.write_metadata,
            write_sidecar=args.write_sidecar,
            tile_only=args.tile_only,
            stitch_backend=StitchBackend(args.stitch_backend),
            rerun_failures=args.rerun_failures,
            resume_batch=args.resume_batch,
            pipeline_artworks=args.pipeline_artworks,
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
