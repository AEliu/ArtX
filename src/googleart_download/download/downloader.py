from __future__ import annotations

from pathlib import Path

from ..logging_utils import get_logger
from ..metadata.output import write_metadata_sidecar
from ..metadata.parsers import normalize_asset_url, parse_page_info, parse_tile_info
from ..models import ArtworkContext, DownloadResult, DownloadSize, RetryConfig, SizeOption, StitchBackend, TileInfo
from ..reporters import Reporter
from .cache import clear_cache_dir, ensure_cache_layout, resolve_artwork_cache_dir, tile_cache_path, write_cache_state
from .http_client import HttpClient
from .image_writer import choose_stitch_backend, resolve_output_path, stitch_tiles
from .size_selection import list_size_options, select_download_level
from .tiles import build_jobs, download_tiles


def inspect_artwork_sizes(url: str, retry_config: RetryConfig) -> tuple[str, list[SizeOption]]:
    http_client = HttpClient(retry_config=retry_config)
    asset_url = normalize_asset_url(url)
    html = http_client.fetch_text(asset_url, description="artwork page")
    page = parse_page_info(html)
    tile_info = parse_tile_info(http_client.fetch_bytes(page.tile_info_url, description="tile metadata"))
    return page.title, list_size_options(tile_info)


def download_artwork(
    url: str,
    output_dir: Path,
    filename: str | None,
    workers: int,
    retry_config: RetryConfig,
    download_size: DownloadSize,
    max_dimension: int | None,
    skip_existing: bool,
    write_metadata: bool,
    write_sidecar: bool,
    stitch_backend: StitchBackend,
    reporter: Reporter,
    index: int,
    total: int,
) -> DownloadResult:
    logger = get_logger()
    http_client = HttpClient(retry_config=retry_config)
    asset_url = normalize_asset_url(url)
    logger.info("Fetching artwork page: %s", asset_url)
    reporter.log(f"Fetching artwork page: {asset_url}")
    html = http_client.fetch_text(asset_url, description="artwork page")
    page = parse_page_info(html)
    output_path = resolve_output_path(
        output_dir,
        filename,
        page.title,
        download_size=download_size,
        max_dimension=max_dimension,
    )

    if skip_existing and output_path.exists():
        sidecar_path = output_path.with_suffix(output_path.suffix + ".json") if write_sidecar else None
        return DownloadResult(
            url=asset_url,
            output_path=output_path,
            title=page.title,
            size=None,
            tile_count=None,
            skipped=True,
            sidecar_path=sidecar_path if sidecar_path and sidecar_path.exists() else None,
        )

    tile_info = parse_tile_info(http_client.fetch_bytes(page.tile_info_url, description="tile metadata"))
    selected_level = select_download_level(tile_info, size=download_size, max_dimension=max_dimension)
    selected_tile_info = TileInfo(tile_width=tile_info.tile_width, tile_height=tile_info.tile_height, levels=[selected_level])
    cache_dir = resolve_artwork_cache_dir(output_dir, page)
    tiles_dir = ensure_cache_layout(cache_dir)

    context = ArtworkContext(
        index=index,
        total=total,
        url=asset_url,
        page=page,
        tile_info=tile_info,
        selected_level=selected_level,
        output_path=output_path,
    )
    reporter.artwork_started(context)

    jobs = build_jobs(page, tile_info, selected_level)
    cached_tiles = sum(1 for job in jobs if tile_cache_path(tiles_dir, job).exists())
    logger.info(
        "Artwork metadata: title=%s size=%sx%s tiles=%s level=%s",
        page.title,
        tile_info.image_width_for(selected_level),
        tile_info.image_height_for(selected_level),
        len(jobs),
        selected_level.z,
    )
    reporter.log(
        "Metadata ready: "
        f"{page.title} | {tile_info.image_width_for(selected_level)}x{tile_info.image_height_for(selected_level)} | "
        f"{len(jobs)} tiles | level {selected_level.z}"
    )
    write_cache_state(
        cache_dir,
        page=page,
        tile_info=selected_tile_info,
        output_path=output_path,
        completed_tiles=cached_tiles,
        total_tiles=len(jobs),
        stage="downloading",
    )
    tiles = download_tiles(jobs, workers=workers, reporter=reporter, http_client=http_client, tiles_dir=tiles_dir)
    write_cache_state(
        cache_dir,
        page=page,
        tile_info=selected_tile_info,
        output_path=output_path,
        completed_tiles=len(tiles),
        total_tiles=len(jobs),
        stage="stitching",
    )
    selected_backend = choose_stitch_backend(selected_tile_info, stitch_backend)
    reporter.log(f"Stitch backend selected: {selected_backend.value}")
    reporter.stitching_started()
    selected_backend = stitch_tiles(
        selected_tile_info,
        tiles,
        output_path,
        metadata=page.metadata,
        write_metadata=write_metadata,
        backend=stitch_backend,
    )
    reporter.log(f"Stitch backend: {selected_backend.value}")
    sidecar_path = None
    if write_sidecar and page.metadata is not None:
        sidecar_path = write_metadata_sidecar(output_path, page.metadata)
    clear_cache_dir(cache_dir)

    return DownloadResult(
        url=asset_url,
        output_path=output_path,
        title=page.title,
        size=(tile_info.image_width_for(selected_level), tile_info.image_height_for(selected_level)),
        tile_count=len(jobs),
        sidecar_path=sidecar_path,
    )
