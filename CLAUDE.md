# CLAUDE.md

Project working agreements for Claude Code and contributors.

## Quality gates (run after meaningful Python changes)
- Formatting: `uv run ruff format .`
- Linting: `uv run ruff check .`
- Type checking: `uv run mypy --hide-error-context --pretty --strict src/artx`
- Tests: `uv run python -m pytest -q`

Notes:
- Keep editor/static warnings clean. Fix E/F/I classes from ruff; do not ignore obvious issues.
- Type hints: avoid returning `Any` from typed functions; prefer narrow casts when needed.
- Optional deps: missing stubs for `psutil`/`pyvips` are handled via module-specific mypy config (no global `ignore_missing_imports`).

## Tooling
- Python: 3.12+
- Packaging: hatchling; wheel includes `src/artx` and deprecation shims in `src/googleart_download`.
- CLI entry point: `artx = artx.cli:main`

## Deprecation policy
- Import path `googleart_download` remains as a shim for 2 minor versions, emits `DeprecationWarning`, and forwards to `artx`.

## Git & PR conventions
- Conventional commits (type: scope): use `feat`, `fix`, `docs`, `chore`, `refactor`, etc.
- Prefer squash merge for PRs.
- Automated pushes should use GitHub noreply email for author/committer.

## Quick commands
```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run mypy --hide-error-context --pretty --strict src/artx
uv run python -m pytest -q
```
