from __future__ import annotations

import os
import re
from pathlib import Path
from types import ModuleType

from PIL import Image

from ..errors import DownloadError
from ..metadata.output import build_exif_bytes
from ..models import ArtworkMetadata, DownloadSize, StitchBackend, TileInfo


def sanitize_filename(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] or "google-art"


def build_output_suffix(download_size: DownloadSize, max_dimension: int | None) -> str:
    if max_dimension is not None:
        return f".maxdim-{max_dimension}"
    if download_size is DownloadSize.MAX:
        return ""
    return f".{download_size.value}"


def build_temp_output_path(output_path: Path) -> Path:
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.part{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.part")


def build_bigtiff_temp_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.part.bigtiff.tif")


def resolve_backend_output_path(output_path: Path, backend: StitchBackend) -> Path:
    if backend is not StitchBackend.BIGTIFF:
        return output_path
    if output_path.suffix.lower() in {".tif", ".tiff"}:
        return output_path
    return output_path.with_suffix(".tif")


def cleanup_stale_partial_outputs(
    original_output_path: Path, final_output_path: Path, backend: StitchBackend
) -> list[Path]:
    stale_paths: list[Path] = []
    if backend is StitchBackend.BIGTIFF and original_output_path != final_output_path:
        stale_paths.append(build_temp_output_path(original_output_path))

    removed: list[Path] = []
    for stale_path in stale_paths:
        if stale_path.exists():
            stale_path.unlink()
            removed.append(stale_path)
    return removed


def resolve_output_path(
    output_dir: Path,
    filename: str | None,
    title: str,
    *,
    download_size: DownloadSize,
    max_dimension: int | None,
) -> Path:
    if filename:
        return output_dir / filename
    suffix = build_output_suffix(download_size, max_dimension)
    return output_dir / f"{sanitize_filename(title)}{suffix}.jpg"


def resolve_non_conflicting_output_path(output_path: Path) -> Path:
    if not output_path.exists():
        return output_path

    parent = output_path.parent
    suffix = output_path.suffix
    stem = output_path.stem
    index = 2
    while True:
        candidate = parent / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


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


def estimate_stitch_memory_bytes(tile_info: TileInfo) -> int:
    return tile_info.image_width * tile_info.image_height * 3


def has_safe_pillow_memory_budget(tile_info: TileInfo) -> bool:
    available_bytes = _read_available_memory_bytes()
    if available_bytes is None:
        return True
    safety_budget = int(available_bytes * 0.5)
    return estimate_stitch_memory_bytes(tile_info) <= safety_budget


def ensure_stitch_memory_budget(tile_info: TileInfo) -> None:
    estimated_bytes = estimate_stitch_memory_bytes(tile_info)
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


def _load_pyvips() -> ModuleType:
    try:
        import pyvips  # type: ignore[import-not-found, import-untyped]
    except Exception as exc:
        raise DownloadError(
            "pyvips backend is not available. Install the optional dependency with "
            "`uv sync --extra large-images` and ensure libvips is installed on the system."
        ) from exc
    return pyvips


def choose_stitch_backend(tile_info: TileInfo, requested_backend: StitchBackend) -> StitchBackend:
    if requested_backend is StitchBackend.AUTO:
        return StitchBackend.PILLOW if has_safe_pillow_memory_budget(tile_info) else StitchBackend.BIGTIFF
    return requested_backend


def _load_streaming_tiff_modules() -> tuple[ModuleType, ModuleType]:
    try:
        import numpy  # type: ignore[import-not-found]
        import tifffile  # type: ignore[import-not-found]
    except Exception as exc:
        raise DownloadError(
            "bigtiff backend is not available. Install the optional dependency set with `uv sync --extra large-images`."
        ) from exc
    return numpy, tifffile


def _save_with_pillow(
    image: Image.Image,
    output_path: Path,
    metadata: ArtworkMetadata | None,
    write_metadata: bool,
    jpeg_quality: int,
) -> None:
    temp_output_path = build_temp_output_path(output_path)
    try:
        if write_metadata and metadata is not None:
            exif_bytes = build_exif_bytes(metadata)
            image.save(temp_output_path, quality=jpeg_quality, exif=exif_bytes)
        else:
            image.save(temp_output_path, quality=jpeg_quality)
        temp_output_path.replace(output_path)
    except Exception:
        if temp_output_path.exists():
            temp_output_path.unlink()
        raise


def _stitch_with_pillow(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], Path],
    output_path: Path,
    metadata: ArtworkMetadata | None,
    write_metadata: bool,
    jpeg_quality: int,
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
    _save_with_pillow(image, output_path, metadata, write_metadata, jpeg_quality)


def _stitch_with_bigtiff(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], Path],
    output_path: Path,
    metadata: ArtworkMetadata | None,
    write_metadata: bool,
) -> None:
    if write_metadata and metadata is not None:
        raise DownloadError(
            "EXIF writing is not supported with the bigtiff stitch backend yet. "
            "Use `--write-sidecar`, disable `--write-metadata`, or force `--stitch-backend pillow` for smaller images."
        )

    numpy, tifffile = _load_streaming_tiff_modules()
    level = tile_info.highest_level
    output_path.parent.mkdir(parents=True, exist_ok=True)
    intermediate_path = build_bigtiff_temp_path(output_path)
    canvas = None

    try:
        canvas = tifffile.memmap(
            str(intermediate_path),
            shape=(tile_info.image_height, tile_info.image_width, 3),
            dtype=numpy.uint8,
            bigtiff=True,
            photometric="rgb",
        )
        for y in range(level.num_tiles_y):
            top = y * tile_info.tile_height
            for x in range(level.num_tiles_x):
                left = x * tile_info.tile_width
                with Image.open(tiles[(x, y)]) as tile:
                    rgb_tile = tile.convert("RGB")
                    width = min(rgb_tile.width, tile_info.image_width - left)
                    height = min(rgb_tile.height, tile_info.image_height - top)
                    if width != rgb_tile.width or height != rgb_tile.height:
                        rgb_tile = rgb_tile.crop((0, 0, width, height))
                    canvas[top : top + height, left : left + width, :] = numpy.asarray(rgb_tile, dtype=numpy.uint8)
            canvas.flush()
    except Exception:
        if canvas is not None:
            del canvas
        if intermediate_path.exists():
            intermediate_path.unlink()
        raise

    assert canvas is not None
    del canvas
    intermediate_path.replace(output_path)


def _stitch_with_pyvips(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], Path],
    output_path: Path,
    metadata: ArtworkMetadata | None,
    write_metadata: bool,
    jpeg_quality: int,
) -> None:
    if write_metadata and metadata is not None:
        raise DownloadError(
            "EXIF writing is not supported with the pyvips stitch backend yet. "
            "Use `--write-sidecar`, disable `--write-metadata`, or force `--stitch-backend pillow` for smaller images."
        )

    pyvips = _load_pyvips()
    level = tile_info.highest_level
    rows: list[object] = []
    temp_output_path = build_temp_output_path(output_path)

    for y in range(level.num_tiles_y):
        row_images: list[object] = []
        for x in range(level.num_tiles_x):
            left = x * tile_info.tile_width
            top = y * tile_info.tile_height
            tile = pyvips.Image.new_from_file(str(tiles[(x, y)]), access="sequential")
            width = min(tile.width, tile_info.image_width - left)
            height = min(tile.height, tile_info.image_height - top)
            if width != tile.width or height != tile.height:
                tile = tile.crop(0, 0, width, height)
            row_images.append(tile)
        rows.append(pyvips.Image.arrayjoin(row_images, across=len(row_images), shim=0))

    final_image = pyvips.Image.arrayjoin(rows, across=1, shim=0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        final_image.write_to_file(str(temp_output_path), Q=jpeg_quality, optimize_coding=True, strip=False)
        temp_output_path.replace(output_path)
    except Exception:
        if temp_output_path.exists():
            temp_output_path.unlink()
        raise


def stitch_tiles(
    tile_info: TileInfo,
    tiles: dict[tuple[int, int], Path],
    output_path: Path,
    metadata: ArtworkMetadata | None = None,
    write_metadata: bool = False,
    jpeg_quality: int = 95,
    backend: StitchBackend = StitchBackend.AUTO,
) -> StitchBackend:
    selected_backend = choose_stitch_backend(tile_info, backend)
    if selected_backend is StitchBackend.PILLOW:
        _stitch_with_pillow(tile_info, tiles, output_path, metadata, write_metadata, jpeg_quality)
    elif selected_backend is StitchBackend.BIGTIFF:
        _stitch_with_bigtiff(tile_info, tiles, output_path, metadata, write_metadata)
    else:
        _stitch_with_pyvips(tile_info, tiles, output_path, metadata, write_metadata, jpeg_quality)
    return selected_backend
