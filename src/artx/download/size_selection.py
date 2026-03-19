from __future__ import annotations

from ..errors import DownloadError
from ..models import DownloadSize, PyramidLevel, SizeOption, StitchBackend, TileInfo
from .image_writer import choose_stitch_backend, estimate_stitch_memory_bytes

SIZE_TARGET_LONGEST_EDGE: dict[DownloadSize, int | None] = {
    DownloadSize.PREVIEW: 2_000,
    DownloadSize.MEDIUM: 5_000,
    DownloadSize.LARGE: 12_000,
    DownloadSize.MAX: None,
}


def list_size_options(tile_info: TileInfo) -> list[SizeOption]:
    return [_build_size_option(tile_info, level) for level in tile_info.levels]


def _build_size_option(tile_info: TileInfo, level: PyramidLevel) -> SizeOption:
    selected_tile_info = TileInfo(tile_width=tile_info.tile_width, tile_height=tile_info.tile_height, levels=[level])
    return SizeOption(
        label=f"level-{level.z}",
        level=level,
        width=tile_info.image_width_for(level),
        height=tile_info.image_height_for(level),
        tile_count=level.tile_count,
        raw_memory_bytes=estimate_stitch_memory_bytes(selected_tile_info),
        default_backend=choose_stitch_backend(selected_tile_info, StitchBackend.AUTO),
    )


def _select_by_max_dimension(tile_info: TileInfo, max_dimension: int) -> PyramidLevel:
    if max_dimension < 1:
        raise DownloadError("--max-dimension must be at least 1")

    eligible = [
        level
        for level in tile_info.levels
        if max(tile_info.image_width_for(level), tile_info.image_height_for(level)) <= max_dimension
    ]
    if eligible:
        return eligible[-1]
    return tile_info.levels[0]


def select_download_level(
    tile_info: TileInfo,
    *,
    size: DownloadSize,
    max_dimension: int | None,
) -> PyramidLevel:
    if max_dimension is not None:
        return _select_by_max_dimension(tile_info, max_dimension)

    target = SIZE_TARGET_LONGEST_EDGE[size]
    if target is None:
        return tile_info.highest_level
    return _select_by_max_dimension(tile_info, target)
