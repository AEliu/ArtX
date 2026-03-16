from .args import BARE_ASSET_ID_PATTERN, JPEG_PRESET_QUALITIES, _preprocess_argv, parse_args, parse_jpeg_quality, resolve_jpeg_quality
from .inputs import _needs_url_resolution, collect_urls, load_failed_batch_urls, validate_cli_args
from .main import main, run_metadata_only
from .output import emit_metadata_output, render_size_options, render_summary, resolve_default_metadata_output_path, write_metadata_output_file
from ..batch import BatchDownloadManager
from ..download.downloader import inspect_artwork_metadata, inspect_artwork_sizes
from ..download.http_client import HttpClient
from ..models import BatchRunResult, DownloadSize, JsonObject, OutputConflictPolicy, RetryConfig, SizeOption, StitchBackend
from ..reporting import build_reporter


def canonicalize_batch_urls(urls: list[str], retry_config: RetryConfig) -> tuple[list[str], list[str]]:
    from .inputs import canonicalize_batch_urls as _canonicalize_batch_urls

    return _canonicalize_batch_urls(urls, retry_config, http_client_cls=HttpClient)

__all__ = [
    "BARE_ASSET_ID_PATTERN",
    "BatchDownloadManager",
    "JPEG_PRESET_QUALITIES",
    "_needs_url_resolution",
    "_preprocess_argv",
    "canonicalize_batch_urls",
    "collect_urls",
    "emit_metadata_output",
    "build_reporter",
    "inspect_artwork_metadata",
    "inspect_artwork_sizes",
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
