# Development Guide

This document describes the day-to-day development workflow for `googleart-download`.

## Tooling

The repository uses:

- `uv` for dependency management and command execution
- `ruff` for formatting and linting
- `mypy` for static type checking
- `unittest` for the default test suite

## Common Commands

Sync the environment:

```bash
uv sync --dev
```

Run the full local check chain:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m mypy src tests scripts/generate_readme_assets.py
uv run python -m unittest discover -s tests -v
```

Show CLI help:

```bash
uv run googleart-download --help
```

## Branching

- Do not start new work on `master`.
- Create a focused branch first.
- Merge back to `master` only after the branch is checked and coherent.

## Test Layers

- Unit and component tests in `tests/`
- Integration workflow tests in `tests/`
- Manual GitHub Actions smoke workflow for real external downloads

See:

- `docs/testing.md`

## Generated README Assets

README screenshots are generated from the current TUI output.

Regenerate them with:

```bash
uv run python scripts/generate_readme_assets.py
```

The main CI workflow checks for stale generated assets.

## CI

The main CI workflow validates:

- formatting
- lint
- type checking
- tests
- README asset freshness

The manual smoke workflow is separate and uses real Google Arts inputs.

## Download Architecture Notes

The current downloader is intentionally mixed-mode rather than fully async:

- artwork page fetch and metadata fetch remain synchronous
- tile downloads now use an internal async `httpx.AsyncClient` path
- stitching, image writing, sidecar writing, and batch-state persistence remain synchronous

This keeps async work focused on the most network-heavy stage without forcing a full rewrite of the rest of the pipeline.

At the moment there is no separate user-facing switch for sync versus async tile download.
The existing `--workers` flag still controls tile-download concurrency, but it now maps to the async download semaphore rather than a thread-pool size.

## Release Notes

Release notes live under:

- `docs/releases/`

Current released examples:

- `docs/releases/v0.1.0.md`
- `docs/releases/v0.2.0.md`
