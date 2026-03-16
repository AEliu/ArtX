from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ..errors import DownloadError
from ..metadata.parsers import normalize_asset_url
from ..models import BatchStateLoadResult, BatchTask, DownloadResult, JsonObject, JsonValue, StitchBackend, TaskState

DEFAULT_BATCH_STATE_FILENAME = ".googleart-batch-state.json"
FAILED_RERUN_BATCH_STATE_FILENAME = ".googleart-batch-rerun-state.json"
STATE_VERSION = 1


def resolve_batch_state_path(output_dir: Path, batch_state_file: str | None) -> Path:
    if batch_state_file is not None:
        return Path(batch_state_file)
    return output_dir / DEFAULT_BATCH_STATE_FILENAME


def resolve_failed_rerun_state_path(output_dir: Path, batch_state_file: str | None) -> Path:
    if batch_state_file is not None:
        source_path = Path(batch_state_file)
        return source_path.with_name(f"{source_path.stem}.rerun{source_path.suffix}")
    return output_dir / FAILED_RERUN_BATCH_STATE_FILENAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_result(result: DownloadResult) -> JsonObject:
    payload: JsonObject = {
        "url": result.url,
        "output_path": str(result.output_path),
        "title": result.title,
        "skipped": result.skipped,
    }
    if result.size is not None:
        payload["size"] = [result.size[0], result.size[1]]
    if result.tile_count is not None:
        payload["tile_count"] = result.tile_count
    if result.sidecar_path is not None:
        payload["sidecar_path"] = str(result.sidecar_path)
    if result.backend_used is not None:
        payload["backend_used"] = result.backend_used.value
    return payload


def _serialize_task(task: BatchTask) -> JsonObject:
    payload: JsonObject = {
        "index": task.index,
        "url": task.url,
        "state": task.state.value,
        "attempts": task.attempts,
    }
    if task.error is not None:
        payload["error"] = task.error
    if task.result is not None:
        payload["result"] = _serialize_result(task.result)
    return payload


def _parse_result(raw: object) -> DownloadResult | None:
    if not isinstance(raw, dict):
        return None

    output_path = raw.get("output_path")
    title = raw.get("title")
    url = raw.get("url")
    if not isinstance(output_path, str) or not isinstance(title, str) or not isinstance(url, str):
        return None

    size: tuple[int, int] | None = None
    raw_size = raw.get("size")
    if isinstance(raw_size, list) and len(raw_size) == 2 and all(isinstance(item, int) for item in raw_size):
        size = (raw_size[0], raw_size[1])

    tile_count = raw.get("tile_count")
    sidecar_path = raw.get("sidecar_path")
    skipped = raw.get("skipped", False)
    backend_used = raw.get("backend_used")
    parsed_backend: StitchBackend | None = None
    if isinstance(backend_used, str):
        try:
            parsed_backend = StitchBackend(backend_used)
        except ValueError:
            parsed_backend = None

    return DownloadResult(
        url=url,
        output_path=Path(output_path),
        title=title,
        size=size,
        tile_count=tile_count if isinstance(tile_count, int) else None,
        skipped=bool(skipped),
        sidecar_path=Path(sidecar_path) if isinstance(sidecar_path, str) else None,
        backend_used=parsed_backend,
    )


def _parse_task(raw: object) -> BatchTask:
    if not isinstance(raw, dict):
        raise DownloadError("batch state file is invalid: task entry is not an object")

    index = raw.get("index")
    url = raw.get("url")
    state = raw.get("state")
    attempts = raw.get("attempts", 0)
    error = raw.get("error")
    if (
        not isinstance(index, int)
        or not isinstance(url, str)
        or not isinstance(state, str)
        or not isinstance(attempts, int)
    ):
        raise DownloadError("batch state file is invalid: task entry is missing required fields")
    if error is not None and not isinstance(error, str):
        raise DownloadError("batch state file is invalid: task error must be a string")

    try:
        task_state = TaskState(state)
    except ValueError as exc:
        raise DownloadError(f"batch state file is invalid: unknown task state '{state}'") from exc

    return BatchTask(
        index=index,
        url=url,
        state=task_state,
        result=_parse_result(raw.get("result")),
        error=error,
        attempts=attempts,
    )


class BatchStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, *, urls: list[str], tasks: list[BatchTask]) -> None:
        normalized_urls = [normalize_asset_url(url) for url in urls]
        created_at = _utc_now()
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if isinstance(existing, dict):
                raw_created_at = existing.get("created_at")
                if isinstance(raw_created_at, str):
                    created_at = raw_created_at

        payload: JsonObject = {
            "version": STATE_VERSION,
            "created_at": created_at,
            "updated_at": _utc_now(),
        }
        payload["urls"] = cast("JsonValue", normalized_urls)
        payload["tasks"] = cast("JsonValue", [_serialize_task(task) for task in tasks])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.path)

    def load(self, *, urls: list[str]) -> BatchStateLoadResult:
        payload, raw_urls, raw_tasks = self._load_payload()

        normalized_urls = [normalize_asset_url(url) for url in urls]
        if normalized_urls != raw_urls:
            raise DownloadError("batch state file URLs do not match the current batch input")

        tasks = [_parse_task(task) for task in raw_tasks]
        if len(tasks) != len(urls):
            raise DownloadError("batch state file task count does not match the current batch input")

        reset_running = False
        normalized_tasks: list[BatchTask] = []
        for index, (task, expected_url) in enumerate(zip(tasks, normalized_urls, strict=True), start=1):
            if normalize_asset_url(task.url) != expected_url:
                raise DownloadError("batch state file task URLs do not match the current batch input")
            normalized_task = replace(task, index=index, url=expected_url)
            if normalized_task.state == TaskState.RUNNING:
                normalized_task = replace(normalized_task, state=TaskState.PENDING)
                reset_running = True
            normalized_tasks.append(normalized_task)

        return BatchStateLoadResult(tasks=normalized_tasks, reset_running_tasks=reset_running)

    def load_failed_urls(self) -> list[str]:
        _, _, raw_tasks = self._load_payload()
        tasks = [_parse_task(task) for task in raw_tasks]
        return [normalize_asset_url(task.url) for task in tasks if task.state == TaskState.FAILED]

    def _load_payload(self) -> tuple[dict[str, object], list[str], list[object]]:
        if not self.path.exists():
            raise DownloadError(f"batch state file does not exist: {self.path}")

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DownloadError(f"batch state file is invalid JSON: {self.path}") from exc
        except OSError as exc:
            raise DownloadError(f"failed to read batch state file: {self.path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise DownloadError(f"batch state file is invalid: {self.path}")

        version = payload.get("version")
        if version != STATE_VERSION:
            raise DownloadError(f"unsupported batch state file version in {self.path}: {version}")

        raw_urls = payload.get("urls")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_urls, list) or not all(isinstance(item, str) for item in raw_urls):
            raise DownloadError("batch state file is invalid: urls must be a string list")
        if not isinstance(raw_tasks, list):
            raise DownloadError("batch state file is invalid: tasks must be a list")

        return payload, raw_urls, raw_tasks
