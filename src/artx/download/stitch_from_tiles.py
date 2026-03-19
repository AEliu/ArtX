from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import cast

from ..errors import DownloadError
from ..models import (
    ArtworkContext,
    DownloadResult,
    OutputConflictPolicy,
    PageInfo,
    PyramidLevel,
    StitchBackend,
    TileInfo,
)
from ..reporting import Reporter
from .image_writer import (
    choose_stitch_backend,
    cleanup_stale_partial_outputs,
    resolve_backend_output_path,
    resolve_non_conflicting_output_path,
    stitch_tiles,
)

_TILE_FILENAME_PATTERN = re.compile(r"^(?P<z>\d+)-(?P<x>\d+)-(?P<y>\d+)\.tile$")


def _load_tile_state(tile_dir: Path) -> dict[str, object]:
    state_path = tile_dir / "state.json"
    if not tile_dir.exists():
        raise DownloadError(f"tile directory does not exist: {tile_dir}")
    if not tile_dir.is_dir():
        raise DownloadError(f"tile directory is not a directory: {tile_dir}")
    if not state_path.exists():
        raise DownloadError(f"tile directory is missing state.json: {tile_dir}")

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DownloadError(f"tile directory state.json is invalid JSON: {state_path}") from exc
    except OSError as exc:
        raise DownloadError(f"failed to read tile directory state: {state_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise DownloadError(f"tile directory state.json is invalid: {state_path}")
    return payload


def _required_int(state: dict[str, object], key: str, state_path: Path) -> int:
    value = state.get(key)
    if not isinstance(value, int) or value < 0:
        raise DownloadError(f"tile directory state.json is missing valid '{key}': {state_path}")
    return value


def _build_tile_info_from_state(state: dict[str, object], state_path: Path) -> tuple[TileInfo, int]:
    image_width = _required_int(state, "image_width", state_path)
    image_height = _required_int(state, "image_height", state_path)
    tile_width = _required_int(state, "tile_width", state_path)
    tile_height = _required_int(state, "tile_height", state_path)
    total_tiles = _required_int(state, "total_tiles", state_path)
    completed_tiles = _required_int(state, "completed_tiles", state_path)
    stage = state.get("stage")

    if stage != "downloaded":
        raise DownloadError(f"tile directory is not fully downloaded yet: {state_path.parent}")
    if completed_tiles != total_tiles:
        raise DownloadError(f"tile directory is incomplete: {state_path.parent}")
    if tile_width < 1 or tile_height < 1 or image_width < 1 or image_height < 1:
        raise DownloadError(f"tile directory state.json has invalid image dimensions: {state_path}")

    num_tiles_x = (image_width + tile_width - 1) // tile_width
    num_tiles_y = (image_height + tile_height - 1) // tile_height
    empty_pels_x = num_tiles_x * tile_width - image_width
    empty_pels_y = num_tiles_y * tile_height - image_height
    level = PyramidLevel(
        z=0,
        num_tiles_x=num_tiles_x,
        num_tiles_y=num_tiles_y,
        empty_pels_x=empty_pels_x,
        empty_pels_y=empty_pels_y,
    )
    return TileInfo(tile_width=tile_width, tile_height=tile_height, levels=[level]), total_tiles


def _load_tiles(
    tile_dir: Path, tile_info: TileInfo, expected_total_tiles: int
) -> tuple[dict[tuple[int, int], Path], int]:
    tiles_dir = tile_dir / "tiles"
    if not tiles_dir.exists() or not tiles_dir.is_dir():
        raise DownloadError(f"tile directory is missing tiles/: {tile_dir}")

    tiles: dict[tuple[int, int], Path] = {}
    z_value: int | None = None
    for tile_path in tiles_dir.iterdir():
        if not tile_path.is_file():
            continue
        match = _TILE_FILENAME_PATTERN.fullmatch(tile_path.name)
        if match is None:
            continue
        z = int(match.group("z"))
        x = int(match.group("x"))
        y = int(match.group("y"))
        if z_value is None:
            z_value = z
        elif z != z_value:
            raise DownloadError(f"tile directory mixes multiple zoom levels: {tile_dir}")
        tiles[(x, y)] = tile_path

    if z_value is None:
        raise DownloadError(f"tile directory does not contain any tile files: {tile_dir}")

    level = tile_info.highest_level
    for y in range(level.num_tiles_y):
        for x in range(level.num_tiles_x):
            if (x, y) not in tiles:
                raise DownloadError(f"tile directory is missing tile z={z_value} x={x} y={y}: {tile_dir}")

    if len(tiles) != expected_total_tiles:
        raise DownloadError(f"tile directory tile count does not match state.json: {tile_dir}")

    return tiles, z_value


def _resolve_default_output_path(tile_dir: Path, state: dict[str, object]) -> Path:
    raw_output_path = state.get("output_path")
    if isinstance(raw_output_path, str):
        state_output_path = Path(raw_output_path)
        if state_output_path.suffix == ".tiles":
            return state_output_path.with_suffix(".jpg")
    if tile_dir.suffix == ".tiles":
        return tile_dir.with_suffix(".jpg")
    return tile_dir / "stitched.jpg"


def stitch_from_tile_directory(
    *,
    tile_dir: Path,
    output_dir: Path,
    filename: str | None,
    jpeg_quality: int,
    output_conflict_policy: OutputConflictPolicy,
    stitch_backend: StitchBackend,
    reporter: Reporter,
) -> DownloadResult:
    tile_dir = tile_dir.expanduser()
    state_path = tile_dir / "state.json"
    state = _load_tile_state(tile_dir)
    tile_info, expected_total_tiles = _build_tile_info_from_state(state, state_path)
    tiles, z_value = _load_tiles(tile_dir, tile_info, expected_total_tiles)
    level = tile_info.highest_level
    selected_tile_info = TileInfo(
        tile_width=tile_info.tile_width,
        tile_height=tile_info.tile_height,
        levels=[
            PyramidLevel(
                z=z_value,
                num_tiles_x=level.num_tiles_x,
                num_tiles_y=level.num_tiles_y,
                empty_pels_x=level.empty_pels_x,
                empty_pels_y=level.empty_pels_y,
            )
        ],
    )

    title = cast("str", state.get("title")) if isinstance(state.get("title"), str) else tile_dir.stem
    asset_url = cast("str", state.get("asset_url")) if isinstance(state.get("asset_url"), str) else str(tile_dir)
    default_output_path = _resolve_default_output_path(tile_dir, state)
    base_output_path = (output_dir / filename) if filename is not None else output_dir / default_output_path.name
    selected_backend = choose_stitch_backend(selected_tile_info, stitch_backend)
    output_path = resolve_backend_output_path(base_output_path, selected_backend)

    if output_conflict_policy is OutputConflictPolicy.RENAME and output_path.exists():
        renamed_output_path = resolve_non_conflicting_output_path(output_path)
        reporter.log(f"Output already exists, renaming to: {renamed_output_path}")
        output_path = renamed_output_path

    removed_partials = cleanup_stale_partial_outputs(base_output_path, output_path, selected_backend)

    if output_conflict_policy is OutputConflictPolicy.SKIP and output_path.exists():
        return DownloadResult(
            url=asset_url,
            output_path=output_path,
            title=title,
            size=None,
            tile_count=None,
            skipped=True,
            backend_used=selected_backend,
        )
    if output_conflict_policy is OutputConflictPolicy.OVERWRITE and output_path.exists():
        reporter.log(f"Overwriting existing output: {output_path}")
        if output_path.is_dir():
            shutil.rmtree(output_path)
        else:
            output_path.unlink()

    context = ArtworkContext(
        index=1,
        total=1,
        url=asset_url,
        page=PageInfo(title=title, base_url="https://example.invalid/tiles", token="", asset_url=asset_url),
        tile_info=selected_tile_info,
        selected_level=selected_tile_info.highest_level,
        output_path=output_path,
    )
    reporter.artwork_started(context)
    reporter.log(f"Stitching from tile directory: {tile_dir}")
    reporter.log(f"Found complete tile set: {len(tiles)} tile(s)")
    for stale_partial in removed_partials:
        reporter.log(f"Removed stale partial output from older JPEG attempt: {stale_partial}")
    reporter.log(f"Stitch backend selected: {selected_backend.value}")
    reporter.stitching_started()
    selected_backend = stitch_tiles(
        selected_tile_info,
        tiles,
        output_path,
        metadata=None,
        write_metadata=False,
        jpeg_quality=jpeg_quality,
        backend=stitch_backend,
    )
    reporter.log(f"Stitch backend: {selected_backend.value}")
    return DownloadResult(
        url=asset_url,
        output_path=output_path,
        title=title,
        size=(selected_tile_info.image_width, selected_tile_info.image_height),
        tile_count=len(tiles),
        backend_used=selected_backend,
    )
