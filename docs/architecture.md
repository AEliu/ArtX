# Architecture Notes

Updated: 2026-11-08. Working version: `0.4.2.dev0` (unreleased).

## Package boundaries

ArtX is the primary application. This integration preserves two distinct compatibility surfaces:

| Package | Responsibility |
| --- | --- |
| `src/artx/` | Primary CLI, metadata, cache recovery, batch state, and image output |
| `src/googleart_download/` | Historical upstream imports forwarded to ArtX with deprecation warnings |
| `src/google_art/` | Retained local downloader API and `google-art` CLI with their original semantics |

`main.py`, `python -m artx`, and the `artx` entry point all start the primary application. The legacy `google-art` entry point continues to call `google_art.cli:app`. The old implementations are not aliases: their data models, size options, default formats, and batching behavior differ. See [migration.md](migration.md).

## Primary ArtX structure

```text
artx.cli
  ├─ inputs / args / output
  ├─ metadata inspection
  └─ batch.manager + batch.state
       └─ download.downloader
            ├─ metadata.parsers + models
            ├─ http_client + transport
            ├─ size_selection
            ├─ cache + tiles + concurrency
            ├─ image_writer
            └─ metadata.output

reporting: CLI / TUI / telemetry events
```

| Domain | Main modules |
| --- | --- |
| Application | `cli/`, `batch/`, `models.py`, `errors.py` |
| Network and tiles | `download/http_client.py`, `transport.py`, `tiles.py`, `concurrency.py` |
| Recovery | `download/cache.py`, `batch/state.py`, `download/stitch_from_tiles.py` |
| Image output | `download/image_writer.py`, `download/size_selection.py` |
| Metadata | `metadata/parsers.py`, `metadata/output.py` |
| Presentation | `reporting/`, `logging_utils.py` |

## Single-artwork flow

1. Normalize a URL, supported short link, or bare asset ID and resolve the artwork page.
2. Fetch and parse artwork metadata and the tile pyramid.
3. Select a pyramid level using a size preset or maximum dimension. ArtX selects an existing level; it does not resize to an exact requested pixel edge.
4. Choose the stitch backend and resolve the image path or visible `.tiles` directory.
5. Check the output conflict policy and prepare the stable hidden cache.
6. Reuse cached tiles and download missing tiles with bounded workers.
7. In tile-only mode, export a visible tile directory and retain the hidden cache.
8. Otherwise, stitch and encode the final image through a temporary file, then publish it.
9. Optionally write metadata and clear the successful stitched artwork's cache.

## Concurrency and resource lifetime

ArtX is mixed-mode. Page fetches, metadata parsing, image writing, and batch-state persistence use synchronous APIs. The network-heavy tile stage uses `httpx.AsyncClient`.

`--workers` bounds the number of tile workers. Each worker holds one slot while downloading, decrypting, and writing a tile to cache; a slow disk therefore cannot accumulate one response body per tile in memory. The job list and tile-path map still scale with artwork tile count, but the number of tasks and in-flight payloads does not. The synchronous tile API likewise submits only a bounded number of futures.

Async workers live in a `TaskGroup`. On failure or cancellation, peers are cancelled and awaited. Blocking cache writes run in threads; `download/concurrency.py` shields and waits for already-started writes even under repeated cancellation before their owners return. Completed cached tiles remain available for recovery; failed tile publications remove their temporary files.

Injected HTTP clients belong to callers. Internally created clients are closed by their owning context managers. Pillow canvases, cropped images, and RGB tile conversions are explicitly closed on both success and failure.

## Batch flow

The batch manager collects and deduplicates equivalent inputs, persists task states, and reports pending/running/skipped/succeeded/failed outcomes. It supports explicit batch resume, targeted reruns, and configured retry rounds.

The default batch runs artworks sequentially. `--pipeline-artworks` may overlap one artwork's download with the previous artwork's stitching. It is not general multi-artwork parallelism. The pipeline's fail-fast path stops launching new downloads and drains already queued finalization. This differs from the retained local `google_art.service.download_many`, which offers fully concurrent artwork jobs and a shared network budget.

## Cache and output publication

Hidden tile caches live beneath `<output-dir>/.googleart-cache/` and are keyed by artwork identity. Visible `.tiles/` directories are portable user-facing artifacts containing `state.json` and `tiles/*.tile`. Successful tile-only output intentionally duplicates tiles into the visible directory while retaining the hidden cache.

- Tile data is written to `.part` files before replacement.
- Batch state is published through a temporary file.
- Final image writers encode to temporary paths and publish only after successful encoding.
- Image overwrite keeps the prior image until the replacement is ready, including offline stitching from tiles.
- Directory paths are rejected as image overwrite targets.

These are per-file guarantees, not a transaction for all artifacts. Metadata sidecars can fail after the image is published. Tile-only directory overwrite retains the upstream remove-and-copy behavior. Concurrent processes sharing an output directory are not coordinated by a filesystem lock; `skip` and `rename` checks are not cross-process reservations.

## Stitch backends

| Backend | Behavior |
| --- | --- |
| Pillow | In-memory RGB canvas with a conservative memory check; supports JPEG EXIF |
| BigTIFF | Disk-backed TIFF assembly for large outputs; requires numpy and tifffile |
| pyvips | Optional explicit alternative; requires both the Python binding and native libvips |

`auto` chooses Pillow when the memory estimate is safe and BigTIFF otherwise. BigTIFF output is a normal success path; automatic conversion of that large result back to JPEG is not part of the default workflow. EXIF remains unsupported for BigTIFF and pyvips; sidecars can be used instead. Missing optional backend dependencies produce actionable errors.

## Retained local implementation

`google_art` continues to use the shared `DownloadPlan`, transport response/retry helpers, assembler interfaces, and staged output from the local refactor. Its async service uses fixed workers, bounded queues, shared network concurrency, cancellation-safe image threads, and batch output reservations. It supports exact longest-edge shrinking without upscaling and explicit PNG/JPEG/WebP output.

This package is retained for compatibility, not folded into ArtX's cache or batch-state schema. New feature work should normally target `artx`; changes to shared behavior need tests against both interfaces. Keep the compatibility implementation independent until an intentional, tested API migration is designed.

## Validation and next decisions

The default pytest suite covers both implementations without live Google access. Formatting and lint apply to the whole repository; strict mypy checks target `src/artx`. Packaging includes all three namespaces and both CLI entry points. See [testing.md](testing.md) and [development.md](development.md).

Further work can focus on cache-schema migration, retained-cache disk budgets, cross-process output coordination, and richer metadata transactions. Such changes should preserve recovery behavior and distinguish network throughput, image memory, and encoding cost. See [project-status.md](project-status.md) for the roadmap.
