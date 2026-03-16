# Project Status

Updated: 2026-03-13

## Current state

The project currently supports:

- downloading high-resolution Google Arts & Culture artwork images by stitching tiles
- batch downloads from direct URLs or `--url-file`
- rich CLI progress output
- rich TUI dashboard via `--tui`
- download-phase observability: tile rate, ETA, retry counters, and phase display
- request-level retries with backoff
- batch-level failed task reruns via `--rerun-failures`
- batch state persistence and explicit resume via `--resume-batch`
- user-friendly size selection via `--size` and `--max-dimension`
- size inspection via `--list-sizes`
- size inspection now includes raw canvas memory estimates and auto output-format hints
- metadata-only inspection via `--metadata-only`
- default metadata-only file output for single-url runs
- official Google short links via `g.co/arts/...`
- direct artwork asset-id input such as `3QFHLJgXCmQm2Q`
- batch input deduplication across equivalent artwork forms such as canonical URLs, `?ms=...` variants, `g.co/arts/...`, and bare asset ids
- skip-existing behavior by default, with `--no-skip-existing` override
- single-artwork tile cache reuse across reruns
- conservative memory guard before stitching extremely large images
- optional `bigtiff` streaming stitch backend for very large images
- optional `pyvips` direct stitch backend for experiments and explicit use
- optional JPEG EXIF metadata writing via `--write-metadata`
- optional JSON sidecar metadata output via `--write-sidecar`
- batch task state tracking: pending, running, skipped, succeeded, failed
- atomic batch state file writes for cross-run recovery
- unit tests for batch rerun behavior, metadata output, tile cache, size selection, and output naming

## Current code structure

Application layer:

- `src/googleart_download/cli.py`
- `src/googleart_download/batch.py`
- `src/googleart_download/models.py`
- `src/googleart_download/reporters.py`
- `src/googleart_download/errors.py`
- `src/googleart_download/logging_utils.py`

Download domain:

- `src/googleart_download/download/http_client.py`
- `src/googleart_download/download/downloader.py`
- `src/googleart_download/download/tiles.py`
- `src/googleart_download/download/image_writer.py`

Metadata domain:

- `src/googleart_download/metadata/parsers.py`
- `src/googleart_download/metadata/output.py`

## Recent completed work

- replaced the old monolithic `core.py` with grouped `download/` and `metadata/` packages
- added batch queue state tracking
- added failed-task rerun rounds
- added optional EXIF writing
- added optional sidecar JSON output
- added tests and verified they pass
- pushed local commits to `origin/master`

## Verified commands

- `uv run python -m py_compile main.py src/googleart_download/*.py src/googleart_download/download/*.py src/googleart_download/metadata/*.py tests/*.py`
- `uv run python -m unittest discover -s tests -v`
- `uv run googleart-download --help`

## Next TODO

### High priority

- add targeted rerun support for previously failed tasks
- add output conflict policies beyond skip and force-redownload
- improve large-job observability:
  - ETA
  - tile rate
  - retry counters
  - phase display
- enrich `--list-sizes` output further with optional rough output-size estimates
- refine size preset thresholds if real-world usage suggests better defaults
- expand test coverage for:
  - download flow integration
  - EXIF writing
  - skip plus rerun combinations
  - CLI-level behavior

### Medium priority

- tune the `httpx` transport for better throughput without changing the sync model:
  - explicit connection-pool/session reuse settings
  - `--workers` and connection-pool sizing alignment
  - finer timeout controls
  - better transport-level observability
- unify metadata output options into a clearer mode-based CLI design
- enrich sidecar JSON with more operational metadata
- support richer batch input formats such as CSV or JSONL
- improve log and event verbosity controls
- add EXIF support for the `bigtiff` and `pyvips` stitch backends
- decide whether a separate explicit "convert TIFF to JPEG" command belongs in this project

### Low priority

- full interactive TUI
- multi-artwork parallel batch scheduling
- packaging and release polish
- consider limited support for third-party short links only when they can be resolved safely to a canonical Google Arts artwork URL

## Notes

- default metadata behavior should remain conservative:
  - EXIF is opt-in
  - sidecar is opt-in
- batch rerun semantics should stay distinct from request retry semantics
- avoid recreating a vague `core/` bucket; keep domain-based structure
- for very large artworks, recovery matters more than UI polish
