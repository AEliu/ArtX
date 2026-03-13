# ADR 0001: Prefer `httpx` for HTTP transport

## Status

Proposed

## Context

The downloader performs many HTTP requests and should stay on a path that supports better transport ergonomics, testing, and future concurrency evolution.

## Decision

Future HTTP work should prefer `httpx`.

The project should move toward:

- a small wrapper around `httpx.Client`
- explicit timeout and retry handling
- client or transport injection for testing

## Consequences

Positive:

- cleaner transport abstraction
- easier migration toward async if needed
- easier testing of retry and failure behavior

Negative:

- adds a dependency
- requires migration of the current HTTP layer
