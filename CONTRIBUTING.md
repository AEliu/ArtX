# Contributing

Thanks for contributing to `googleart-download`.

## Workflow

- Start new work on a branch, not directly on `master`.
- Keep each branch focused on one coherent feature, fix, refactor, or documentation task.
- Prefer small, reviewable commits with clear messages.

Typical branch names:

- `feat/...`
- `fix/...`
- `refactor/...`
- `docs/...`
- `ci/...`
- `test/...`

## Local Setup

Use `uv` for dependency management, environment sync, and commands.

```bash
uv sync --dev
uv run googleart-download --help
```

If you need optional large-image extras:

```bash
uv sync --extra large-images
```

## Required Checks Before Commit

Run the full local check chain before committing Python changes:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m mypy src tests scripts/generate_readme_assets.py
uv run python -m unittest discover -s tests -v
```

## Testing Expectations

- New features should include tests when practical.
- Changes in retry behavior, batch state, metadata output, persistence, or CLI workflow should include targeted coverage.
- Real Google Arts download checks belong in the manual smoke workflow, not the default test suite.

See also:

- `docs/testing.md`

## Documentation Expectations

- Keep user-facing documentation up to date with behavior changes.
- Record agreed TODOs and follow-up work in project documents such as `docs/project-status.md`.
- Do not put local machine paths or other environment-specific absolute paths into repository docs.

## Generated Assets

README screenshots are generated assets.

If a UI or README asset changes, regenerate and verify them as part of normal checks:

```bash
uv run python scripts/generate_readme_assets.py
```

CI will also check that generated README assets are not stale.

## Scope and Priorities

- Favor maintainable engineering choices over quick temporary implementations.
- Keep the core download path reliable before expanding UI or optional features.
- Treat transport, parsing, image writing, metadata output, and batch orchestration as separate concerns.
