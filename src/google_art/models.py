from __future__ import annotations

from dataclasses import dataclass
from typing import List


def clamp_dimensions(width: int, height: int, max_edge: int | None) -> tuple[int, int]:
    """Compute resized dimensions preserving aspect ratio."""
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive")
    if max_edge is None:
        return width, height
    if max_edge <= 0:
        raise ValueError("max_edge must be positive")
    longest = max(width, height)
    if longest <= max_edge:
        return width, height
    scale = max_edge / longest
    return max(1, int(width * scale)), max(1, int(height * scale))


@dataclass(frozen=True)
class PyramidLevel:
    num_tiles_x: int
    num_tiles_y: int
    empty_pels_x: int
    empty_pels_y: int

    def pixel_dimensions(self, tile_width: int, tile_height: int) -> tuple[int, int]:
        width = tile_width * self.num_tiles_x - self.empty_pels_x
        height = tile_height * self.num_tiles_y - self.empty_pels_y
        return width, height


@dataclass(frozen=True)
class TileInfo:
    tile_width: int
    tile_height: int
    pyramid_levels: List[PyramidLevel]

    def __post_init__(self) -> None:
        if self.tile_width <= 0 or self.tile_height <= 0:
            raise ValueError("Tile dimensions must be positive")
        if not self.pyramid_levels:
            raise ValueError("Tile info does not contain pyramid levels")
        for level in self.pyramid_levels:
            if level.num_tiles_x <= 0 or level.num_tiles_y <= 0:
                raise ValueError("Tile counts must be positive")
            if not (0 <= level.empty_pels_x < self.tile_width and 0 <= level.empty_pels_y < self.tile_height):
                raise ValueError("Empty pixels must fit within the last tile")

    def choose_level(self, target_edge: int | None) -> tuple[int, PyramidLevel]:
        """Pick best zoom level index and metadata for requested max edge."""
        if not self.pyramid_levels:
            raise ValueError("Tile info does not contain pyramid levels")
        if target_edge is None:
            return len(self.pyramid_levels) - 1, self.pyramid_levels[-1]

        best_index = len(self.pyramid_levels) - 1
        best_level = self.pyramid_levels[best_index]
        for idx, level in enumerate(self.pyramid_levels):
            width, height = level.pixel_dimensions(self.tile_width, self.tile_height)
            if max(width, height) >= target_edge:
                best_index = idx
                best_level = level
                break
        return best_index, best_level


@dataclass(frozen=True)
class PageInfo:
    base_url: str
    token: str
    name: str

    def tile_info_url(self) -> str:
        return f"{self.base_url}=g"

    def path(self) -> str:
        return self.base_url.split("//", 1)[-1].split("/", 1)[-1]


@dataclass(frozen=True)
class DownloadOptions:
    asset: str
    out_path: str | None = None
    max_edge: int | None = None
    fmt: str = "png"
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not self.asset.strip():
            raise ValueError("asset must not be empty")
        if self.max_edge is not None and self.max_edge <= 0:
            raise ValueError("max_edge must be positive")
        if self.normalized_format() not in {"png", "jpeg", "webp"}:
            raise ValueError("format must be one of png, jpg, jpeg, webp")

    def normalized_format(self) -> str:
        fmt = self.fmt.lower()
        if fmt == "jpg":
            return "jpeg"
        return fmt

    def sanitized_filename(self, fallback: str) -> str:
        import re

        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._") or "artwork"
        return stem


@dataclass(frozen=True)
class AsyncOptions(DownloadOptions):
    net_concurrency: int = 32
    per_asset_concurrency: int = 8
    queue_size: int = 256
    assembler: str = "auto"

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("net_concurrency", "per_asset_concurrency", "queue_size"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.assembler not in {"auto", "pillow", "vips"}:
            raise ValueError("assembler must be one of auto, pillow, vips")
