# ADR 0003: Keep UI work behind core reliability work

## Status

Accepted

## Context

The project already has a usable CLI and a `rich`-based live terminal dashboard.

The current major gaps are in reliability and recovery, not presentation.

## Decision

Core reliability and maintainability work should stay ahead of advanced UI work.

This means prioritizing:

- retry quality
- resume and cache support
- atomic writes
- better observability for long-running downloads

before building a full interactive TUI.

## Consequences

Positive:

- engineering effort goes to the highest-risk areas first
- less chance of building a polished UI over a fragile core

Negative:

- the UI will remain intentionally modest in the near term
