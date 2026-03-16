from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

from ..logging_utils import get_logger
from ..metadata.output import metadata_to_dict, write_metadata_sidecar
from ..metadata.parsers import normalize_asset_url, parse_page_info, parse_tile_info
from ..models import (
    ArtworkContext,
    DownloadResult,
    DownloadSize,
    JsonObject,
    OutputConflictPolicy,
    PageInfo,
    PyramidLevel,
    RetryConfig,
    SizeOption,
    StitchBackend,
    TileInfo,
    TileJob,
)
from ..reporting import Reporter
from .cache import (
    cache_has_complete_tiles,
    clear_cache_dir,
    ensure_cache_layout,
    resolve_artwork_cache_dir,
    restore_cache_from_visible_output,
    tile_cache_path,
    write_cache_state,
    write_visible_tile_output,
)
from .http_client import AsyncHttpClient, HttpClient
from .image_writer import (
    choose_stitch_backend,
    cleanup_stale_partial_outputs,
    resolve_backend_output_path,
    resolve_non_conflicting_output_path,
    resolve_output_path,
    resolve_tile_output_path,
    stitch_tiles,
)
from .size_selection import list_size_options, select_download_level
from .tiles import build_jobs, download_tiles_async


@dataclass(frozen=True)
class _ArtworkDownloadData:
    asset_url: str
    canonical_asset_url: str
    page: PageInfo
    tile_info: TileInfo
    selected_level: PyramidLevel
    selected_tile_info: TileInfo
    selected_backend: StitchBackend
    original_output_path: Path
    jobs: list[TileJob]


@dataclass(frozen=True)
class _DownloadWorkspace:
    requested_output_path: Path
    output_path: Path
    cache_dir: Path
    tiles_dir: Path
    removed_partials: list[Path]


def inspect_artwork_sizes(
    url: str, retry_config: RetryConfig, *, proxy_url: str | None = None
) -> tuple[str, list[SizeOption]]:
    with HttpClient(retry_config=retry_config, proxy_url=proxy_url) as http_client:
        asset_url = normalize_asset_url(url)
        html, fetched_url = http_client.fetch_text_with_url(asset_url, description="artwork page")
        page = parse_page_info(html, fetched_url=fetched_url)
        tile_info = parse_tile_info(http_client.fetch_bytes(page.tile_info_url, description="tile metadata"))
        return page.title, list_size_options(tile_info)


def inspect_artwork_metadata(url: str, retry_config: RetryConfig, *, proxy_url: str | None = None) -> JsonObject:
    with HttpClient(retry_config=retry_config, proxy_url=proxy_url) as http_client:
        asset_url = normalize_asset_url(url)
        html, fetched_url = http_client.fetch_text_with_url(asset_url, description="artwork page")
        page = parse_page_info(html, fetched_url=fetched_url)
        canonical_asset_url = page.asset_url or normalize_asset_url(fetched_url)
        payload: JsonObject = {}
        if page.metadata is not None:
            payload.update(metadata_to_dict(page.metadata))
        payload["asset_url"] = canonical_asset_url
        payload.setdefault("title", page.title)
        return payload


def _resolve_artwork_download_data(
    *,
    url: str,
    output_dir: Path,
    filename: str | None,
    download_size: DownloadSize,
    max_dimension: int | None,
    stitch_backend: StitchBackend,
    http_client: HttpClient,
    reporter: Reporter,
    logger: Logger,
) -> _ArtworkDownloadData:
    asset_url = normalize_asset_url(url)
    logger.info("Fetching artwork page: %s", asset_url)
    reporter.phase_changed("fetching")
    reporter.log(f"Fetching artwork page: {asset_url}")
    html, fetched_url = http_client.fetch_text_with_url(asset_url, description="artwork page")
    page = parse_page_info(html, fetched_url=fetched_url)
    canonical_asset_url = page.asset_url or normalize_asset_url(fetched_url)
    if canonical_asset_url != asset_url:
        reporter.log(f"Canonical artwork URL: {canonical_asset_url}")

    original_output_path = resolve_output_path(
        output_dir,
        filename,
        page.title,
        download_size=download_size,
        max_dimension=max_dimension,
    )
    tile_info = parse_tile_info(http_client.fetch_bytes(page.tile_info_url, description="tile metadata"))
    selected_level = select_download_level(tile_info, size=download_size, max_dimension=max_dimension)
    selected_tile_info = TileInfo(
        tile_width=tile_info.tile_width,
        tile_height=tile_info.tile_height,
        levels=[selected_level],
    )
    selected_backend = choose_stitch_backend(selected_tile_info, stitch_backend)
    jobs = build_jobs(page, tile_info, selected_level)
    return _ArtworkDownloadData(
        asset_url=asset_url,
        canonical_asset_url=canonical_asset_url,
        page=page,
        tile_info=tile_info,
        selected_level=selected_level,
        selected_tile_info=selected_tile_info,
        selected_backend=selected_backend,
        original_output_path=original_output_path,
        jobs=jobs,
    )


def _resolve_output_path_for_artwork(data: _ArtworkDownloadData, *, tile_only: bool) -> Path:
    if tile_only:
        return resolve_tile_output_path(data.original_output_path)
    return resolve_backend_output_path(data.original_output_path, data.selected_backend)


def _prepare_download_workspace(
    *,
    data: _ArtworkDownloadData,
    output_dir: Path,
    output_conflict_policy: OutputConflictPolicy,
    tile_only: bool,
    reporter: Reporter,
) -> _DownloadWorkspace:
    requested_output_path = _resolve_output_path_for_artwork(data, tile_only=tile_only)
    output_path = requested_output_path
    if output_conflict_policy is OutputConflictPolicy.RENAME and requested_output_path.exists():
        renamed_output_path = resolve_non_conflicting_output_path(requested_output_path)
        reporter.log(f"Output already exists, renaming to: {renamed_output_path}")
        output_path = renamed_output_path

    cache_dir = resolve_artwork_cache_dir(output_dir, data.canonical_asset_url, data.original_output_path)
    if tile_only:
        restore_cache_from_visible_output(cache_dir, requested_output_path, data.canonical_asset_url)

    removed_partials = (
        []
        if tile_only
        else cleanup_stale_partial_outputs(data.original_output_path, output_path, data.selected_backend)
    )
    tiles_dir = ensure_cache_layout(cache_dir)
    return _DownloadWorkspace(
        requested_output_path=requested_output_path,
        output_path=output_path,
        cache_dir=cache_dir,
        tiles_dir=tiles_dir,
        removed_partials=removed_partials,
    )


def _existing_output_result(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    write_sidecar: bool,
    tile_only: bool,
) -> DownloadResult:
    sidecar_path = None
    if not tile_only and write_sidecar:
        candidate = workspace.output_path.with_suffix(workspace.output_path.suffix + ".json")
        sidecar_path = candidate if candidate.exists() else None
    return DownloadResult(
        url=data.canonical_asset_url,
        output_path=workspace.output_path,
        title=data.page.title,
        size=None,
        tile_count=None,
        skipped=True,
        tile_only=tile_only,
        sidecar_path=sidecar_path,
        backend_used=None if tile_only else data.selected_backend,
    )


def _handle_existing_output(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    output_conflict_policy: OutputConflictPolicy,
    write_sidecar: bool,
    tile_only: bool,
    reporter: Reporter,
) -> DownloadResult | None:
    if output_conflict_policy is OutputConflictPolicy.SKIP and workspace.output_path.exists():
        if not tile_only:
            return _existing_output_result(
                data=data,
                workspace=workspace,
                write_sidecar=write_sidecar,
                tile_only=False,
            )
        if cache_has_complete_tiles(workspace.output_path, data.canonical_asset_url, data.jobs):
            return _existing_output_result(
                data=data,
                workspace=workspace,
                write_sidecar=False,
                tile_only=True,
            )

    if output_conflict_policy is OutputConflictPolicy.OVERWRITE:
        if workspace.output_path.exists():
            reporter.log(f"Overwriting existing output: {workspace.output_path}")
            if workspace.output_path.is_dir():
                shutil.rmtree(workspace.output_path)
            else:
                workspace.output_path.unlink()
        if tile_only and workspace.cache_dir.exists():
            clear_cache_dir(workspace.cache_dir)
            ensure_cache_layout(workspace.cache_dir)
    return None


def _report_artwork_ready(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    index: int,
    total: int,
    reporter: Reporter,
    logger: Logger,
) -> None:
    context = ArtworkContext(
        index=index,
        total=total,
        url=data.canonical_asset_url,
        page=data.page,
        tile_info=data.tile_info,
        selected_level=data.selected_level,
        output_path=workspace.output_path,
    )
    reporter.artwork_started(context)

    cached_tiles = sum(1 for job in data.jobs if tile_cache_path(workspace.tiles_dir, job).exists())
    if cached_tiles:
        reporter.log(f"Cache directory: {workspace.cache_dir}")
        reporter.log(f"Cached tiles available: {cached_tiles}/{len(data.jobs)}")
    logger.info(
        "Artwork metadata: title=%s size=%sx%s tiles=%s level=%s",
        data.page.title,
        data.tile_info.image_width_for(data.selected_level),
        data.tile_info.image_height_for(data.selected_level),
        len(data.jobs),
        data.selected_level.z,
    )
    selected_width = data.tile_info.image_width_for(data.selected_level)
    selected_height = data.tile_info.image_height_for(data.selected_level)
    reporter.log(
        "Metadata ready: "
        f"{data.page.title} | "
        f"{selected_width}x{selected_height} | "
        f"{len(data.jobs)} tiles | level {data.selected_level.z}"
    )
    reporter.log(
        "Output format: TILES"
        if workspace.output_path.suffix == ".tiles"
        else f"Output format: {workspace.output_path.suffix.lower().lstrip('.').upper()}"
    )
    if data.selected_backend is StitchBackend.BIGTIFF:
        reporter.log(f"Large artwork output adjusted to TIFF for streaming stitch safety: {workspace.output_path}")
    for stale_partial in workspace.removed_partials:
        reporter.log(f"Removed stale partial output from older JPEG attempt: {stale_partial}")


def _download_tile_phase(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    workers: int,
    retry_config: RetryConfig,
    timeout: int,
    proxy_url: str | None,
    reporter: Reporter,
) -> dict[tuple[int, int], Path]:
    cached_tiles = sum(1 for job in data.jobs if tile_cache_path(workspace.tiles_dir, job).exists())
    write_cache_state(
        workspace.cache_dir,
        asset_url=data.canonical_asset_url,
        page=data.page,
        tile_info=data.selected_tile_info,
        output_path=workspace.output_path,
        completed_tiles=cached_tiles,
        total_tiles=len(data.jobs),
        stage="downloading",
    )
    return await_download_tiles(
        data.jobs,
        workers=workers,
        reporter=reporter,
        retry_config=retry_config,
        timeout=timeout,
        proxy_url=proxy_url,
        tiles_dir=workspace.tiles_dir,
    )


def _finalize_tile_only_output(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    reporter: Reporter,
) -> DownloadResult:
    write_visible_tile_output(workspace.cache_dir, workspace.output_path)
    reporter.log(f"Tiles saved: {workspace.output_path}")
    return DownloadResult(
        url=data.canonical_asset_url,
        output_path=workspace.output_path,
        title=data.page.title,
        size=(
            data.tile_info.image_width_for(data.selected_level),
            data.tile_info.image_height_for(data.selected_level),
        ),
        tile_count=len(data.jobs),
        tile_only=True,
    )


def _finalize_stitched_output(
    *,
    data: _ArtworkDownloadData,
    workspace: _DownloadWorkspace,
    tiles: dict[tuple[int, int], Path],
    jpeg_quality: int,
    write_metadata: bool,
    write_sidecar: bool,
    stitch_backend: StitchBackend,
    reporter: Reporter,
) -> DownloadResult:
    reporter.log(f"Stitch backend selected: {data.selected_backend.value}")
    reporter.stitching_started()
    selected_backend = stitch_tiles(
        data.selected_tile_info,
        tiles,
        workspace.output_path,
        metadata=data.page.metadata,
        write_metadata=write_metadata,
        jpeg_quality=jpeg_quality,
        backend=stitch_backend,
    )
    reporter.log(f"Stitch backend: {selected_backend.value}")
    sidecar_path = None
    if write_sidecar and data.page.metadata is not None:
        sidecar_path = write_metadata_sidecar(workspace.output_path, data.page.metadata)
    clear_cache_dir(workspace.cache_dir)
    return DownloadResult(
        url=data.canonical_asset_url,
        output_path=workspace.output_path,
        title=data.page.title,
        size=(
            data.tile_info.image_width_for(data.selected_level),
            data.tile_info.image_height_for(data.selected_level),
        ),
        tile_count=len(data.jobs),
        sidecar_path=sidecar_path,
        backend_used=selected_backend,
    )


def download_artwork(
    url: str,
    output_dir: Path,
    filename: str | None,
    workers: int,
    jpeg_quality: int,
    retry_config: RetryConfig,
    download_size: DownloadSize,
    max_dimension: int | None,
    output_conflict_policy: OutputConflictPolicy,
    write_metadata: bool,
    write_sidecar: bool,
    stitch_backend: StitchBackend,
    reporter: Reporter,
    index: int,
    total: int,
    proxy_url: str | None = None,
    tile_only: bool = False,
) -> DownloadResult:
    logger = get_logger()
    with HttpClient(
        retry_config=retry_config,
        proxy_url=proxy_url,
        on_retry=reporter.retry_recorded,
    ) as http_client:
        data = _resolve_artwork_download_data(
            url=url,
            output_dir=output_dir,
            filename=filename,
            download_size=download_size,
            max_dimension=max_dimension,
            stitch_backend=stitch_backend,
            http_client=http_client,
            reporter=reporter,
            logger=logger,
        )
        workspace = _prepare_download_workspace(
            data=data,
            output_dir=output_dir,
            output_conflict_policy=output_conflict_policy,
            tile_only=tile_only,
            reporter=reporter,
        )
        existing_result = _handle_existing_output(
            data=data,
            workspace=workspace,
            output_conflict_policy=output_conflict_policy,
            write_sidecar=write_sidecar,
            tile_only=tile_only,
            reporter=reporter,
        )
        if existing_result is not None:
            return existing_result

        _report_artwork_ready(
            data=data,
            workspace=workspace,
            index=index,
            total=total,
            reporter=reporter,
            logger=logger,
        )
        tiles = _download_tile_phase(
            data=data,
            workspace=workspace,
            workers=workers,
            retry_config=retry_config,
            timeout=http_client.timeout,
            proxy_url=proxy_url,
            reporter=reporter,
        )
        write_cache_state(
            workspace.cache_dir,
            asset_url=data.canonical_asset_url,
            page=data.page,
            tile_info=data.selected_tile_info,
            output_path=workspace.output_path,
            completed_tiles=len(tiles),
            total_tiles=len(data.jobs),
            stage="downloaded" if tile_only else "stitching",
        )
        if tile_only:
            return _finalize_tile_only_output(
                data=data,
                workspace=workspace,
                reporter=reporter,
            )
        return _finalize_stitched_output(
            data=data,
            workspace=workspace,
            tiles=tiles,
            jpeg_quality=jpeg_quality,
            write_metadata=write_metadata,
            write_sidecar=write_sidecar,
            stitch_backend=stitch_backend,
            reporter=reporter,
        )


def await_download_tiles(
    jobs: list[TileJob],
    *,
    workers: int,
    reporter: Reporter,
    retry_config: RetryConfig,
    timeout: int,
    proxy_url: str | None,
    tiles_dir: Path,
) -> dict[tuple[int, int], Path]:
    async def _run() -> dict[tuple[int, int], Path]:
        async with AsyncHttpClient(
            retry_config=retry_config,
            timeout=timeout,
            proxy_url=proxy_url,
            on_retry=reporter.retry_recorded,
        ) as http_client:
            return await download_tiles_async(
                jobs,
                workers=workers,
                reporter=reporter,
                http_client=http_client,
                tiles_dir=tiles_dir,
            )

    return asyncio.run(_run())
