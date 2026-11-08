# Testing Guide

This project uses a layered test strategy. The goal is to keep the default test suite stable while still leaving room for real-world smoke checks against Google Arts & Culture.

## Test Layers

- Unit and component tests
  - Live under `tests/`
  - Cover parsing, CLI validation, batch state, tile cache, metadata output, reporters, and transport behavior
  - Do not depend on live Google Arts network access

- Integration workflow tests
  - Also live under `tests/`
  - Exercise higher-level flows such as:
    - `--resume-batch`
    - `--rerun-failed`
    - output conflict policies
    - large-image `TIFF/BigTIFF` result handling
    - sidecar and EXIF writing
  - Still avoid live network dependency

- Manual smoke workflow
  - Implemented in `.github/workflows/smoke-download.yml`
  - Uses real Google Arts inputs
  - Intended for manual GitHub Actions runs, not the default CI gate

## Local Checks

Before committing Python changes, run:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy --hide-error-context --pretty --strict src/artx
uv run python -m pytest -q
```

The imported ArtX tests use the `tests/test_artx_*.py` prefix to avoid collisions with the retained local test modules. The original `tests/test_*.py` files cover `google_art`, including shared network limits, cancellation, thread lifetime, atomic publication, and the legacy CLI. New ArtX lifecycle tests cover bounded workers and image-resource cleanup.

The default suite uses mocks and local fixtures. Passing it does not establish that a real Google Arts endpoint is reachable or that a native libvips installation works. Optional backends need separate integration checks with their dependencies installed.

## CI Coverage

The main CI workflow checks:

- formatting
- lint
- type checking
- unit and integration tests
- generated README asset freshness

The main CI workflow does not download live artwork from Google Arts.

## Manual Smoke Download

The manual smoke workflow supports:

- a built-in named smoke case
- an optional custom artwork input override
- optional real-world proxy testing by providing an artwork input that requires your network path to be reachable

Built-in real-world smoke cases are tracked in:

- `tests/fixtures/smoke_assets.json`

These cases are intentionally small and are meant for:

- bare asset id resolution
- query-string URL normalization
- `g.co` short-link handling

They are not part of the default local or CI test suite because they depend on a live external service.

## Where New Tests Should Go

- Pure parsing, formatting, path, or state logic:
  - add to the existing unit-style test files in `tests/`

- CLI, batch, retry, output-format, or persistence workflows:
  - prefer integration-style tests that still avoid live network access

- Real Google Arts download verification:
  - use the manual smoke workflow instead of the default test suite
