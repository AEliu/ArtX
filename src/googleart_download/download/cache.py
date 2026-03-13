from __future__ import annotations

import json
import re
import shutil
from hashlib import sha1
from pathlib import Path

from ..models import PageInfo, TileInfo, TileJob

CACHE_SCHEMA_VERSION = 1


def resolve_artwork_cache_dir(output_dir: Path, page: PageInfo) -> Path:
    asset_id = page.base_url.rstrip("/").rsplit("/", 1)[-1]
    safe_asset_id = re.sub(r"[^A-Za-z0-9._-]+", "_", asset_id) or "artwork"
    identity = sha1(page.base_url.encode("utf-8")).hexdigest()[:12]
    return output_dir / ".googleart-cache" / f"{safe_asset_id}-{identity}"


def ensure_cache_layout(cache_dir: Path) -> Path:
    tiles_dir = cache_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    return tiles_dir


def tile_cache_path(tiles_dir: Path, job: TileJob) -> Path:
    return tiles_dir / f"{job.x}-{job.y}.tile"


def write_cache_state(
    cache_dir: Path,
    *,
    page: PageInfo,
    tile_info: TileInfo,
    output_path: Path,
    completed_tiles: int,
    total_tiles: int,
    stage: str,
) -> None:
    state = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "title": page.title,
        "base_url": page.base_url,
        "tile_info_url": page.tile_info_url,
        "output_path": str(output_path),
        "image_width": tile_info.image_width,
        "image_height": tile_info.image_height,
        "tile_width": tile_info.tile_width,
        "tile_height": tile_info.tile_height,
        "completed_tiles": completed_tiles,
        "total_tiles": total_tiles,
        "stage": stage,
    }
    state_path = cache_dir / "state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_cache_dir(cache_dir: Path) -> None:
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
