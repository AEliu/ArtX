# Project Status

Updated: 2026-03-16

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
- targeted rerun support via `--rerun-failed`
- user-friendly size selection via `--size` and `--max-dimension`
- size inspection via `--list-sizes`
- size inspection now includes raw canvas memory estimates and auto output-format hints
- metadata-only inspection via `--metadata-only`
- default metadata-only file output for single-url runs
- official Google short links via `g.co/arts/...`
- direct artwork asset-id input such as `3QFHLJgXCmQm2Q`
- batch input deduplication across equivalent artwork forms such as canonical URLs, `?ms=...` variants, `g.co/arts/...`, and bare asset ids
- metadata-only multi-url deduplication across the same equivalent artwork forms
- explicit output conflict handling via `--output-conflict skip|overwrite|rename`
- compatibility override via `--no-skip-existing`
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

Application and shared modules:

- `src/googleart_download/cli/`
- `src/googleart_download/batch/`
- `src/googleart_download/reporting/`
- `src/googleart_download/models.py`
- `src/googleart_download/errors.py`
- `src/googleart_download/logging_utils.py`

Download domain:

- `src/googleart_download/download/constants.py`
- `src/googleart_download/download/http_client.py`
- `src/googleart_download/download/downloader.py`
- `src/googleart_download/download/tiles.py`
- `src/googleart_download/download/image_writer.py`

Metadata domain:

- `src/googleart_download/metadata/parsers.py`
- `src/googleart_download/metadata/output.py`

Repo quality and automation:

- `pyproject.toml` now configures `ruff`
- `.github/workflows/ci.yml` runs format, lint, type-check, tests, and README asset freshness checks
- `.github/workflows/smoke-download.yml` provides a manual GitHub Actions smoke download using a conservative lightweight download profile
- `tests/fixtures/smoke_assets.json` tracks a small set of real-world smoke artwork inputs for manual workflow use:
  - built-in named cases cover bare asset ids, query-string URLs, and `g.co` short links
  - the workflow still supports a manual custom artwork input override when needed
- `scripts/generate_readme_assets.py` is treated as a generated-doc asset source rather than a hand-maintained file

## Recent completed work

- replaced the old monolithic `core.py` with grouped `download/` and `metadata/` packages
- added batch queue state tracking
- added failed-task rerun rounds
- added optional EXIF writing
- added optional sidecar JSON output
- added tests and verified they pass
- added batch input deduplication, targeted rerun, explicit output conflict policies, and richer size inspection
- removed compatibility-shell leftovers after package reorganization
- moved download-specific constants into the `download/` domain
- added `ruff`, `mypy`, and GitHub Actions CI
- added CI verification that generated README assets stay up to date

## Verified commands

- `uv run ruff format .`
- `uv run ruff check .`
- `uv run python -m mypy src tests scripts/generate_readme_assets.py`
- `uv run python -m py_compile main.py src/googleart_download/*.py src/googleart_download/cli/*.py src/googleart_download/batch/*.py src/googleart_download/download/*.py src/googleart_download/metadata/*.py src/googleart_download/reporting/*.py scripts/generate_readme_assets.py tests/*.py`
- `uv run python -m unittest discover -s tests -v`
- `uv run googleart-download --help`

## Next TODO

### High priority

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
- prepare the next transport-tuning pass with clearer runtime metrics:
  - request counts by artwork
  - retry totals by artwork
  - basic phase timing breakdown for fetch / download / stitch / write
- unify metadata output options into a clearer mode-based CLI design
- enrich sidecar JSON with more operational metadata
- add an opt-in richer metadata export path without breaking the current `--write-sidecar` behavior:
  - keep the current sidecar JSON as-is for compatibility
  - evaluate a separate JSON-LD sidecar mode rather than overloading `--write-sidecar`
  - prefer stable identifiers based on asset id, for example `gac:asset:{assetId}` and `gac:asset:{assetId}:{variant}`
  - keep metadata output adjacent to the current artifact instead of forcing a new `{partner}/{object}` directory layout
  - optionally persist raw page JSON-LD snapshots for traceability
  - optionally emit checksums for the final image and metadata files
  - evaluate optional XMP writing through `exiftool`, with graceful skip when unavailable
- support richer batch input formats such as CSV or JSONL
- improve log and event verbosity controls
- add EXIF support for the `bigtiff` and `pyvips` stitch backends
- decide whether a separate explicit "convert TIFF to JPEG" command belongs in this project
- reduce developer workflow friction for formatting and checks:
  - add a single local command entry point for `fmt` and `check`
  - keep the command layered on top of `uv`, not as a separate toolchain
  - later consider pre-commit hooks only after the single-command workflow is in place
- extend GitHub Actions download workflows beyond local artifacts:
  - keep the current artifact-based workflow as the default safe path
  - evaluate optional external storage backends for downloaded outputs, such as Cloudflare R2
  - avoid committing downloaded artworks back into the main repository by default
  - keep any remote-storage integration opt-in and secret-driven
- revisit README screenshot presentation:
  - current generated TUI and large-image previews are accurate but still not readable enough in some web and mobile layouts
  - refine the documentation visual strategy later instead of continuing ad hoc tweaks now
- consider adding a minimal `SECURITY.md` if the project starts receiving broader public usage or vulnerability reports
- consider adding a short release/versioning process note once release cadence becomes more regular

### Low priority

- full interactive TUI
- multi-artwork parallel batch scheduling
- packaging and release polish
- consider limited support for third-party short links only when they can be resolved safely to a canonical Google Arts artwork URL
- explore a future service-oriented mode for research teams or lightweight web frontends:
  - keep the current CLI downloader as the stable core engine
  - treat queue lifecycle, persistent job state, and artifact storage as prerequisites before any web UI
  - prefer external object storage plus stable result links over committing downloaded artifacts into the repository

## Notes

- default metadata behavior should remain conservative:
  - EXIF is opt-in
  - sidecar is opt-in
- batch rerun semantics should stay distinct from request retry semantics
- avoid recreating a vague `core/` bucket; keep domain-based structure
- for very large artworks, recovery matters more than UI polish
