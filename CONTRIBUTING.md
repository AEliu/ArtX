# Contributing

Thanks for contributing to `ArtX`.

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
uv run artx --help
```

If you need optional large-image extras:

```bash
uv sync --extra large-images
```

## Branch protection and required checks

To keep `master` green and avoid accidental merges before CI finishes:
- Enable branch protection on `master` and require status checks to pass before merging (Settings → Branches → Branch protection rules)
- Required checks (CI job):
  - Ruff format check
  - Ruff lint
  - Mypy strict on `src/artx`
  - Pytest
- Optional but recommended:
  - Require branches to be up to date before merging
  - Dismiss stale approvals when new commits are pushed

## Pull request rules
- Do not enable auto-merge before CI is green.
- Prefer squash merges.

## Required Checks Before Commit

Run the full local check chain before committing Python changes:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy --hide-error-context --pretty --strict src/artx
uv run python -m pytest -q
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
