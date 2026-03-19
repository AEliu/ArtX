from __future__ import annotations

import json
import re
import shutil
from hashlib import sha1
from pathlib import Path

from ..models import PageInfo, TileInfo, TileJob

CACHE_SCHEMA_VERSION = 1


def _stable_cache_dir(output_dir: Path, asset_url: str) -> Path:
    asset_id = asset_url.rstrip("/").rsplit("/", 1)[-1]
    safe_asset_id = re.sub(r"[^A-Za-z0-9._-]+", "_", asset_id) or "artwork"
    identity = sha1(asset_url.encode("utf-8")).hexdigest()[:12]
    return output_dir / ".googleart-cache" / f"{safe_asset_id}-{identity}"


def _read_cache_state(cache_dir: Path) -> dict[str, object] | None:
    state_path = cache_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def cache_matches_asset(cache_dir: Path, asset_url: str) -> bool:
    state = _read_cache_state(cache_dir)
    return state is not None and state.get("asset_url") == asset_url


def cache_has_complete_tiles(cache_dir: Path, asset_url: str, jobs: list[TileJob]) -> bool:
    state = _read_cache_state(cache_dir)
    if state is None or state.get("asset_url") != asset_url:
        return False
    if state.get("completed_tiles") != len(jobs):
        return False
    if state.get("total_tiles") != len(jobs):
        return False
    if state.get("stage") != "downloaded":
        return False

    tiles_dir = cache_dir / "tiles"
    return all(tile_cache_path(tiles_dir, job).exists() for job in jobs)


def restore_cache_from_visible_output(cache_dir: Path, visible_output_dir: Path, asset_url: str) -> bool:
    if cache_dir.exists() or not visible_output_dir.exists():
        return False
    if not cache_matches_asset(visible_output_dir, asset_url):
        return False

    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(visible_output_dir, cache_dir)
    except OSError:
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        return False
    return True


def write_visible_tile_output(cache_dir: Path, visible_output_dir: Path) -> None:
    if visible_output_dir.exists():
        shutil.rmtree(visible_output_dir)
    visible_output_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cache_dir, visible_output_dir)


def _find_legacy_cache_dir(output_dir: Path, output_path: Path) -> Path | None:
    cache_root = output_dir / ".googleart-cache"
    if not cache_root.exists():
        return None

    best_match: tuple[int, Path] | None = None
    for candidate in cache_root.iterdir():
        if not candidate.is_dir():
            continue
        state = _read_cache_state(candidate)
        if state is None:
            continue
        if state.get("output_path") != str(output_path):
            continue
        completed_tiles = state.get("completed_tiles")
        completed = completed_tiles if isinstance(completed_tiles, int) else -1
        if best_match is None or completed > best_match[0]:
            best_match = (completed, candidate)

    return best_match[1] if best_match is not None else None


def resolve_artwork_cache_dir(output_dir: Path, asset_url: str, output_path: Path) -> Path:
    stable_dir = _stable_cache_dir(output_dir, asset_url)
    if stable_dir.exists():
        return stable_dir

    legacy_dir = _find_legacy_cache_dir(output_dir, output_path)
    if legacy_dir is None:
        return stable_dir

    stable_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy_dir.replace(stable_dir)
        return stable_dir
    except OSError:
        return legacy_dir


def ensure_cache_layout(cache_dir: Path) -> Path:
    tiles_dir = cache_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    return tiles_dir


def tile_cache_path(tiles_dir: Path, job: TileJob) -> Path:
    return tiles_dir / f"{job.z}-{job.x}-{job.y}.tile"


def write_cache_state(
    cache_dir: Path,
    *,
    asset_url: str,
    page: PageInfo,
    tile_info: TileInfo,
    output_path: Path,
    completed_tiles: int,
    total_tiles: int,
    stage: str,
) -> None:
    state = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "asset_url": asset_url,
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
