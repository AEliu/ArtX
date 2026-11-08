"""Pure download planning shared by the synchronous and asynchronous APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import DownloadOptions, PageInfo, PyramidLevel, TileInfo, clamp_dimensions

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def normalize_asset(asset: str) -> str:
    asset = asset.strip()
    if asset.startswith(("http://", "https://")):
        return asset
    return f"https://artsandculture.google.com/asset/{asset.strip('/')}"


def is_directory_output(path: Path) -> bool:
    return path.is_dir() or path.suffix.lower() not in IMAGE_SUFFIXES


def resolve_output_path(options: DownloadOptions, page: PageInfo) -> Path:
    filename = f"{options.sanitized_filename(page.name)}.{options.normalized_format()}"
    if options.out_path is None:
        return Path.cwd() / filename
    path = Path(options.out_path)
    return path / filename if is_directory_output(path) else path


@dataclass(frozen=True)
class DownloadPlan:
    page_url: str
    page: PageInfo
    tiles: TileInfo
    level_index: int
    level: PyramidLevel
    output_path: Path
    target_size: tuple[int, int]

    @classmethod
    def build(cls, options: DownloadOptions, page: PageInfo, tiles: TileInfo) -> DownloadPlan:
        index, level = tiles.choose_level(options.max_edge)
        size = level.pixel_dimensions(tiles.tile_width, tiles.tile_height)
        return cls(
            normalize_asset(options.asset),
            page,
            tiles,
            index,
            level,
            resolve_output_path(options, page),
            clamp_dimensions(*size, options.max_edge),
        )

    @property
    def canvas_size(self) -> tuple[int, int]:
        return (self.tiles.tile_width * self.level.num_tiles_x, self.tiles.tile_height * self.level.num_tiles_y)

    @property
    def crop_size(self) -> tuple[int, int]:
        return self.level.pixel_dimensions(self.tiles.tile_width, self.tiles.tile_height)

    @property
    def tile_count(self) -> int:
        return self.level.num_tiles_x * self.level.num_tiles_y

    def coordinates(self) -> Iterator[tuple[int, int]]:
        return ((x, y) for y in range(self.level.num_tiles_y) for x in range(self.level.num_tiles_x))
