# Large Images

## Why Large Artworks Are Different

Some Google Arts & Culture artworks are extremely large. A direct in-memory stitch to JPEG is not a safe default for outputs at that scale.

This project separates large-image handling from normal-sized handling on purpose.

## Default Behavior

For normal-sized outputs:

- the final output stays JPEG

For very large outputs:

- the project automatically switches to TIFF/BigTIFF
- stitching is done through a safer streaming path
- the default flow does not automatically convert the result back to JPEG

This is intentional product behavior, not a fallback accident.

<a href="assets/large-image-tiff.svg">
  <img src="assets/large-image-overview.svg" alt="Large artwork TIFF path" />
</a>

## Tile Cache Reuse

Artwork tiles are cached per artwork identity. If a download is interrupted, already downloaded tiles are reused on the next run.

You should see logs such as:

- cache directory
- cached tiles available
- reusing cached tiles

This is especially important for large artworks where downloading thousands of tiles twice would be wasteful.

## Choosing A Smaller Size

You do not have to download the largest available output.

Use:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --list-sizes
```

Then choose:

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --size large
uv run googleart-download "3QFHLJgXCmQm2Q" --max-dimension 8000
```

The size inspection output is intended to help you avoid:

- unnecessary tile counts
- excessive raw canvas memory
- large-image TIFF output when you do not need it

## TIFF Output

When a very large artwork switches to TIFF/BigTIFF:

- this is the safer and expected output path
- the summary reports the output format and stitch backend
- the result is ready for later conversion if you want another format

The project does not automatically convert large TIFF results to JPEG in the default download path.

## Optional Extras

The repository can install optional large-image extras with:

```bash
uv sync --extra large-images
```

Some optional backends may also need system libraries. See the main README for the current install note.
