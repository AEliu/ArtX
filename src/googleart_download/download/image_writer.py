from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image

from ..errors import DownloadError
from ..models import ArtworkMetadata, TileInfo
from ..metadata.output import build_exif_bytes


def sanitize_filename(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] or "google-art"


def resolve_output_path(output_dir: Path, filename: str | None, title: str) -> Path:
    if filename:
        return output_dir / filename
    return output_dir / f"{sanitize_filename(title)}.jpg"


def _read_available_memory_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    if hasattr(os, "sysconf"):
        names = getattr(os, "sysconf_names", {})
        if "SC_AVPHYS_PAGES" in names and "SC_PAGE_SIZE" in names:
            return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    return None


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def ensure_stitch_memory_budget(tile_info: TileInfo) -> None:
    estimated_bytes = tile_info.image_width * tile_info.image_height * 3
    available_bytes = _read_available_memory_bytes()
    if available_bytes is None:
        return
    # Pillow also needs allocator overhead and temporary objects; keep a conservative safety margin.
    safety_budget = int(available_bytes * 0.5)
    if estimated_bytes > safety_budget:
        raise DownloadError(
            "image is too large for safe in-memory stitching: "
            f"requires about {_format_bytes(estimated_bytes)} raw canvas memory, "
            f"available memory is about {_format_bytes(available_bytes)}"
        )


def stitch_tiles(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], Path],
    output_path: Path,
    metadata: ArtworkMetadata | None = None,
    write_metadata: bool = False,
) -> None:
    ensure_stitch_memory_budget(tile_info)
    image = Image.new("RGB", (tile_info.image_width, tile_info.image_height))
    level = tile_info.highest_level

    for y in range(level.num_tiles_y):
        for x in range(level.num_tiles_x):
            tile = Image.open(tiles[(x, y)])
            tile.load()
            left = x * tile_info.tile_width
            top = y * tile_info.tile_height
            right = min(left + tile.width, tile_info.image_width)
            bottom = min(top + tile.height, tile_info.image_height)
            cropped = tile.crop((0, 0, right - left, bottom - top))
            image.paste(cropped, (left, top))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_suffix(output_path.suffix + ".part")
    try:
        if write_metadata and metadata is not None:
            exif_bytes = build_exif_bytes(metadata)
            image.save(temp_output_path, quality=95, exif=exif_bytes)
        else:
            image.save(temp_output_path, quality=95)
        temp_output_path.replace(output_path)
    except Exception:
        if temp_output_path.exists():
            temp_output_path.unlink()
        raise
