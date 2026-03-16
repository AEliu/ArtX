# Usage

## Basic Download

```bash
uv run googleart-download "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q" -o downloads
```

You can also pass:

- a full artwork URL
- an artwork URL with viewer query params such as `?ms=...`
- an official `g.co/arts/...` short link
- a bare asset id such as `3QFHLJgXCmQm2Q`

## Input Files

Read one URL per line:

```bash
uv run googleart-download --url-file urls.txt --tui
```

Equivalent artwork inputs are deduplicated before a batch starts. This applies to:

- full artwork URLs
- query-param variants
- `g.co` short links
- bare asset ids

## Batch Resume And Rerun

Resume a previously interrupted batch:

```bash
uv run googleart-download --url-file urls.txt --resume-batch
```

Rerun only failed tasks from the previous batch state:

```bash
uv run googleart-download --rerun-failed
```

Use a custom batch state file:

```bash
uv run googleart-download --url-file urls.txt --batch-state-file state/downloads.json
```

## Retry And Parallelism

Adjust request retries:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --retries 5 --retry-backoff 1.0
```

Adjust tile download concurrency:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --workers 32
```

`--workers` controls tile download concurrency inside one artwork. Higher values can help on good networks, but may also increase rate limiting or retry pressure.

Adjust JPEG quality for JPEG outputs:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-quality 85
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-preset balanced
```

`--jpeg-quality` applies to JPEG writes only. It does not force large artworks back to JPEG if the safe default path has switched them to TIFF/BigTIFF.
`--jpeg-preset` is a friendlier alias layer:

- `web` -> `75`
- `balanced` -> `85`
- `archive` -> `95`

`--jpeg-quality` and `--jpeg-preset` cannot be used together.

## Output Naming

By default:

- `--size max` keeps the base filename
- non-max preset sizes add a suffix such as `.preview`, `.medium`, `.large`
- `--max-dimension 8000` adds `.maxdim-8000`

Example:

- `The Starry Night.jpg`
- `The Starry Night.preview.jpg`
- `The Starry Night.maxdim-8000.jpg`

If you pass `--filename`, that explicit filename wins.

## Output Conflict Policies

```bash
uv run googleart-download --url-file urls.txt --output-conflict skip
uv run googleart-download --url-file urls.txt --output-conflict overwrite
uv run googleart-download --url-file urls.txt --output-conflict rename
```

Behavior:

- `skip`: default
- `overwrite`: replace existing output
- `rename`: write `.2`, `.3`, and so on

`--no-skip-existing` is kept as a compatibility flag and is equivalent to `--output-conflict overwrite`.

## Inspect Sizes Before Download

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --list-sizes
```

Size inspection reports:

- pixel dimensions
- tile count
- raw canvas memory estimate
- whether the selected backend path would remain JPEG or switch to TIFF

## TUI And Logging

```bash
uv run googleart-download --url-file urls.txt --tui --log-file logs/run.log -v
```

<a href="assets/tui-preview.svg">
  <img src="assets/tui-overview.svg" alt="TUI overview" />
</a>

The CLI can show:

- download rate
- ETA
- estimated finish time
- retry count
- current phase

## Constraints

- `--filename` is only valid for a single download target.
- `--resume-batch` and `--rerun-failed` cannot be combined.
- `--metadata-only` cannot be combined with `--list-sizes`.
