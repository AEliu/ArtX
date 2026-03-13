# ADR 0002: Prioritize recovery for large artworks

## Status

Proposed

## Context

Some artworks require thousands of tile requests and very long end-to-end runtime.

In this situation, the main user risk is not only speed. The larger risk is losing substantial progress after interruption or failure.

## Decision

The project should treat recovery as a first-class capability for large artworks.

Preferred direction:

- cache completed tiles
- allow reruns to reuse downloaded tiles
- persist enough state to resume meaningfully
- make final output writing atomic

## Consequences

Positive:

- much lower restart cost
- better confidence for large downloads
- more useful batch behavior for long-running jobs

Negative:

- added complexity in cache lifecycle and state management
- more disk usage
- more edge cases around resume behavior
