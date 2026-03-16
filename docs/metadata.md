# Metadata

## Metadata-Only Export

Export artwork metadata without downloading image tiles:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --metadata-only
```

Single URL behavior:

- if `--metadata-output` is not provided, the CLI writes a default `.metadata.json` file
- if no usable title is available, it falls back to `google-art.metadata.json`

Multiple URL behavior:

- if `--metadata-output` is not provided, the CLI writes a JSON array to stdout
- if you want a file, pass `--metadata-output path/to/file.json`

Example:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --metadata-only --metadata-output metadata.json
```

## Metadata Deduplication

`--metadata-only` uses the same canonicalization and deduplication rules as batch downloads.

That means equivalent inputs for the same artwork are merged before metadata export:

- full artwork URL
- query-param variant
- `g.co` short link
- bare asset id

## Sidecar Output

Write a simple JSON sidecar next to the downloaded image:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --write-sidecar
```

This does not replace the image output. It adds a structured metadata file for the downloaded artwork.

## EXIF Output

Write artwork metadata into JPEG EXIF:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --write-metadata
```

This is opt-in and only applies where the current output path supports it well.

## Large-Image Note

Large-image TIFF/BigTIFF paths do not use the normal JPEG EXIF flow. For large outputs, prefer `--write-sidecar` if you want metadata captured alongside the image.
