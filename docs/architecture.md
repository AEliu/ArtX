# Architecture Notes

## Purpose

This document records the current architecture, major risks, and near-term design direction for `googleart-download`.

Use this file for system design context.
Do not use it as a replacement for `AGENTS.md`.

- `AGENTS.md` holds stable local engineering rules.
- This document explains structure, bottlenecks, and preferred evolution paths.

## Current architecture

The package uses a `src/` layout and is grouped by domain.

Application layer:

- `src/googleart_download/cli.py`
- `src/googleart_download/batch.py`
- `src/googleart_download/reporters.py`
- `src/googleart_download/models.py`
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

## Current single-artwork flow

1. Normalize the artwork URL.
2. Fetch the artwork page.
3. Parse artwork metadata and tile metadata URL.
4. Fetch tile metadata.
5. Build tile jobs for the highest zoom level.
6. Download tiles concurrently.
7. Decrypt tiles when required.
8. Stitch the full image.
9. Write the final image file.
10. Optionally write EXIF and JSON sidecar metadata.

## Current batch flow

1. Collect URLs from CLI input and `--url-file`.
2. Build batch tasks.
3. Run artworks one by one at the batch level.
4. Track task state:
   - `pending`
   - `running`
   - `skipped`
   - `succeeded`
   - `failed`
5. Optionally rerun failed artworks in later batch rounds.

## Current strengths

- The codebase is separated by domain instead of one large core module.
- Batch state and request retry behavior are explicit.
- Metadata output is opt-in.
- The CLI already supports both one-off and batch usage.
- Tests exist for batch reruns and metadata output.

## Known constraints

### HTTP layer

The current transport works, but it should move toward a more maintainable `httpx`-based abstraction.

Why:

- better connection reuse support
- cleaner API surface
- easier injection for testing
- smoother path toward async if needed later

### Large artwork behavior

Very large artworks create a different risk profile from normal images.

Main issues:

- thousands of tile requests
- long-running download windows
- costly restarts after interruption
- high memory pressure during stitching
- long final JPEG encoding and disk write time

### Progress visibility

Current progress is informative but not yet predictive enough for large jobs.

Still missing:

- tile throughput
- ETA
- retry-rate visibility
- explicit phase display:
  - metadata
  - tile download
  - stitching
  - final write

## Design priorities

### 1. Recovery before richer UI

For large artworks, the most valuable improvement is not a more advanced interface.
It is reliable recovery.

Preferred order:

1. tile cache and resume
2. persisted task state
3. atomic final output
4. better observability
5. richer TUI work

### 2. Explicit side effects

Anything that changes outputs or preserves local state should stay explicit.

Examples:

- metadata writing remains opt-in
- cache retention should be controlled by flags
- overwrite behavior should be explicit

### 3. Separate bottlenecks

Large-artwork performance must be treated as three different concerns:

1. HTTP request throughput
2. image assembly and memory cost
3. final file encoding and disk output

Improving one of these does not automatically solve the others.

## Important next design direction

### Tile cache and resume

This is the highest-value missing reliability feature.

Desired behavior:

- keep a per-artwork work directory
- store tile metadata and download state there
- reuse finished tiles after interruption
- stitch from cached tiles once the set is complete

Suggested high-level layout:

```text
<output-dir>/
  .googleart-cache/
    <stable-artwork-id>/
      page.json
      tile-info.json
      state.json
      tiles/
        <z>-<x>-<y>.tile
```

Important design constraints:

- the cache key must use a stable artwork identity
- do not rely only on title or output filename
- failed jobs should keep cache by default
- successful jobs can clean cache by default, with an opt-in keep-cache mode
- cache schema versioning should be considered early

### Atomic output writes

Final file output should become atomic:

- write to a temporary file first
- rename only after the write succeeds

This avoids corrupted or partial final outputs.

### Better observability

For large jobs, the user should be able to see:

- tiles completed / total
- current tile rate
- rolling ETA for the download phase
- retry counters
- current phase

### HTTP evolution

Preferred path:

1. replace `urllib` transport usage with a small `httpx.Client` wrapper
2. keep the sync interface stable first
3. improve transport testability
4. only then evaluate async migration

## Design questions that still need deliberate answers

### Cache identity

- Which exact value should identify a stable artwork cache key?
- How should different slugs for the same artwork map to one cache?

### Resume semantics

- What happens if the output filename changes between runs?
- What happens if metadata flags change between runs?
- What happens if the cache format changes in a newer version?

### Disk usage

- How much cache should be retained?
- Should the tool estimate required disk space for very large works?
- When should stale cache be cleaned?

### Memory usage

- Is in-memory stitching still acceptable for extreme image sizes?
- Should the project eventually support lower-memory stitching strategies?

## Recommended documentation split

- `AGENTS.md`
  - stable local rules and engineering preferences
- `docs/architecture.md`
  - architecture, bottlenecks, design direction
- `docs/project-status.md`
  - current implemented state and next roadmap
- `docs/adr/`
  - short records for important decisions
