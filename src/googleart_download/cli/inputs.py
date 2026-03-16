from __future__ import annotations

import argparse
from pathlib import Path

from ..batch.state import BatchStateStore, resolve_batch_state_path, resolve_failed_rerun_state_path
from ..download.http_client import HttpClient
from ..errors import DownloadError
from ..metadata.parsers import extract_asset_id, normalize_asset_url
from ..models import RetryConfig


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = list(args.urls)

    if args.url_file:
        file_urls = [
            line.strip()
            for line in Path(args.url_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        urls.extend(file_urls)

    if not urls and not args.rerun_failed and not args.stitch_from_tiles:
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
    if args.stitch_from_tiles and urls:
        raise DownloadError("--stitch-from-tiles cannot be used together with artwork URLs or --url-file")

    if args.stitch_from_tiles and args.resume_batch:
        raise DownloadError("--stitch-from-tiles cannot be used together with --resume-batch")

    if args.stitch_from_tiles and args.rerun_failed:
        raise DownloadError("--stitch-from-tiles cannot be used together with --rerun-failed")

    if args.stitch_from_tiles and args.batch_state_file:
        raise DownloadError("--stitch-from-tiles cannot be used together with --batch-state-file")

    if args.stitch_from_tiles and args.list_sizes:
        raise DownloadError("--stitch-from-tiles cannot be used together with --list-sizes")

    if args.stitch_from_tiles and args.metadata_only:
        raise DownloadError("--stitch-from-tiles cannot be used together with --metadata-only")

    if args.stitch_from_tiles and args.tile_only:
        raise DownloadError("--stitch-from-tiles cannot be used together with --tile-only")

    if args.stitch_from_tiles and args.write_metadata:
        raise DownloadError("--stitch-from-tiles does not support --write-metadata yet")

    if args.stitch_from_tiles and args.write_sidecar:
        raise DownloadError("--stitch-from-tiles does not support --write-sidecar yet")

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
        raise DownloadError(
            "--rerun-failed loads failed URLs from the batch state file and cannot be combined with direct batch URLs"
        )

    if args.metadata_only and args.filename and len(urls) > 1:
        raise DownloadError("--filename cannot be used with multiple URLs in --metadata-only mode")

    if args.filename and len(urls) > 1:
        raise DownloadError("--filename can only be used with a single URL")

    if args.no_skip_existing and args.output_conflict != "skip":
        raise DownloadError("--no-skip-existing cannot be used together with --output-conflict")

    if args.metadata_output and not args.metadata_only:
        raise DownloadError("--metadata-output requires --metadata-only")

    if args.metadata_only and args.list_sizes:
        raise DownloadError("--metadata-only cannot be used together with --list-sizes")

    if args.tile_only and args.metadata_only:
        raise DownloadError("--tile-only cannot be used together with --metadata-only")

    if args.tile_only and args.list_sizes:
        raise DownloadError("--tile-only cannot be used together with --list-sizes")

    if args.tile_only and args.write_metadata:
        raise DownloadError("--tile-only cannot be used together with --write-metadata")

    if args.tile_only and args.write_sidecar:
        raise DownloadError("--tile-only cannot be used together with --write-sidecar")

    if args.tile_only and args.stitch_backend != "auto":
        raise DownloadError("--tile-only cannot be used together with an explicit --stitch-backend")

    if args.list_sizes and len(urls) != 1:
        raise DownloadError("--list-sizes requires exactly one artwork URL")


def _needs_url_resolution(url: str) -> bool:
    normalized = normalize_asset_url(url)
    if normalized.startswith("https://g.co/"):
        return True
    parts = [part for part in normalized.split("/") if part]
    return len(parts) >= 4 and parts[-2] == "asset"


def canonicalize_batch_urls(
    urls: list[str],
    retry_config: RetryConfig,
    *,
    proxy_url: str | None = None,
    http_client_cls: type[HttpClient] = HttpClient,
) -> tuple[list[str], list[str]]:
    unique_urls: list[str] = []
    duplicate_messages: list[str] = []
    seen_by_asset_id: dict[str, str] = {}
    seen_by_url: set[str] = set()

    with http_client_cls(retry_config=retry_config, proxy_url=proxy_url) as http_client:
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
