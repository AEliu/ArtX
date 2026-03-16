# googleart-download

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-3776AB.svg)](#install)
[![Version 0.2.0](https://img.shields.io/badge/version-0.2.0-0f766e.svg)](pyproject.toml)

[中文说明](README.zh-CN.md)

Download high-resolution images from Google Arts & Culture artwork pages.

`googleart-download` resolves the artwork page, downloads the tiled image pyramid, and stitches the final image locally. It is built for reliability first: batch runs, retry handling, tile-cache reuse, interrupted-run recovery, and safe handling for very large artworks.

## Highlights

- Downloads a single artwork, a URL list, or a batch file.
- Supports multiple input forms for the same artwork:
  - full artwork URL
  - artwork URL with viewer query params
  - official `g.co/arts/...` short links
  - bare asset id such as `3QFHLJgXCmQm2Q`
- Reuses cached tiles after interruption instead of starting over.
- Supports batch resume and rerun of only failed tasks.
- Lets you inspect available download sizes before downloading.
- Automatically switches very large artworks to TIFF/BigTIFF output for safer streaming stitch.
- Supports metadata-only export and optional sidecar / EXIF metadata output.

## Why This Project

Google Arts & Culture artwork pages use image tiles. A simple “save image” workflow does not recover the full artwork.

This project focuses on the practical problems that appear once you try to download real artwork pages at scale:

- broken or retried tile requests
- interrupted downloads
- very large artworks that should not be stitched fully in memory
- batch runs that need to be resumed instead of restarted

## Install

```bash
uv sync
```

Run the CLI:

```bash
uv run googleart-download --help
```

If you want optional large-image extras:

```bash
uv sync --extra large-images
```

## Quick Start

Download one artwork:

```bash
uv run googleart-download "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q" -o downloads
```

Use a short asset id instead of a long URL:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --size preview
```

Inspect sizes before downloading:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --list-sizes
```

Export artwork metadata only:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --metadata-only
```

<a href="docs/assets/tui-preview.svg">
  <img src="docs/assets/tui-overview.svg" alt="Terminal preview" />
</a>

_Screenshot generated from the current TUI output._

## Common Tasks

Choose a user-friendly download size:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --size preview
uv run googleart-download "3QFHLJgXCmQm2Q" --size medium
uv run googleart-download "3QFHLJgXCmQm2Q" --size large
uv run googleart-download "3QFHLJgXCmQm2Q" --size max
```

Resume an interrupted batch:

```bash
uv run googleart-download --url-file urls.txt --resume-batch
```

Rerun only failed tasks from the previous batch:

```bash
uv run googleart-download --rerun-failed
```

Write metadata sidecars or EXIF:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --write-sidecar
uv run googleart-download "3QFHLJgXCmQm2Q" --write-metadata
```

Adjust JPEG quality for JPEG outputs:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-quality 85
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-preset balanced
```

## Output Format Behavior

Normal-sized artworks default to JPEG output.

Very large artworks automatically switch to TIFF/BigTIFF output. This is intentional. The project uses a safer streaming stitch path for large outputs instead of trying to build the full image in memory and then write a JPEG.

Large-image JPEG conversion is not part of the default path. If you need a JPEG from a very large TIFF result, convert it yourself as a separate post-process step.

<a href="docs/assets/large-image-tiff.svg">
  <img src="docs/assets/large-image-overview.svg" alt="Large artwork TIFF path" />
</a>

_Screenshot generated from the current TUI output._

## More Documentation

- [Usage Guide](docs/usage.md): CLI usage, batch workflows, resume, rerun, conflict handling
- [Large Images](docs/large-images.md): large artwork behavior, TIFF/BigTIFF path, cache reuse, size inspection
- [Metadata Guide](docs/metadata.md): metadata-only export, sidecars, EXIF behavior
- [Architecture Notes](docs/architecture.md): internal architecture and implementation notes
- [Project Status](docs/project-status.md): current status and planned work

## Current Scope

- Works on artwork pages, not full collections or story pages.
- Large-image TIFF output is supported; automatic TIFF-to-JPEG conversion is intentionally not in the default flow.
- Some richer metadata export ideas are planned, but the current metadata features remain intentionally conservative.
