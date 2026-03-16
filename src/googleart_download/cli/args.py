from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Sequence

from ..models import DownloadSize, OutputConflictPolicy, StitchBackend

BARE_ASSET_ID_PATTERN = re.compile(r"^-?[A-Za-z0-9_][A-Za-z0-9_-]{9,}$")
JPEG_PRESET_QUALITIES = {
    "web": 75,
    "balanced": 85,
    "archive": 95,
}


def parse_jpeg_quality(value: str) -> int:
    try:
        quality = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("jpeg quality must be an integer between 1 and 100") from exc
    if not 1 <= quality <= 100:
        raise argparse.ArgumentTypeError("jpeg quality must be between 1 and 100")
    return quality


def _preprocess_argv(argv: Sequence[str] | None) -> list[str]:
    from ..metadata.parsers import normalize_asset_url

    raw_args = list(sys.argv[1:] if argv is None else argv)
    processed: list[str] = []
    for token in raw_args:
        if token.startswith("-") and not token.startswith("--") and BARE_ASSET_ID_PATTERN.fullmatch(token):
            if token.startswith("-w") and len(token) > 2:
                try:
                    int(token[2:])
                except ValueError:
                    processed.append(normalize_asset_url(token))
                    continue
            elif not token.startswith(("-o", "-f")):
                processed.append(normalize_asset_url(token))
                continue
        processed.append(token)
    return processed


def resolve_jpeg_quality(args: argparse.Namespace) -> int:
    if args.jpeg_preset is not None:
        return JPEG_PRESET_QUALITIES[args.jpeg_preset]
    if args.jpeg_quality is not None:
        return args.jpeg_quality
    return 95


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    argv = _preprocess_argv(argv)
    parser = argparse.ArgumentParser(
        description="Download high-resolution Google Arts & Culture images by stitching tiles.",
    )
    parser.add_argument("urls", nargs="*", help="one or more Google Arts & Culture asset URLs")
    parser.add_argument("--url-file", help="text file with one asset URL per line")
    parser.add_argument(
        "--stitch-from-tiles",
        help="stitch a final image from an existing .tiles directory instead of downloading artwork URLs",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="destination directory (default: downloads)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="output filename, only valid when downloading a single URL",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=min(16, (os.cpu_count() or 4) * 2),
        help="concurrent tile downloads (default: auto)",
    )
    jpeg_group = parser.add_mutually_exclusive_group()
    jpeg_group.add_argument(
        "--jpeg-quality",
        type=parse_jpeg_quality,
        default=None,
        help="jpeg output quality for jpeg writes (1-100, default: 95)",
    )
    jpeg_group.add_argument(
        "--jpeg-preset",
        choices=sorted(JPEG_PRESET_QUALITIES),
        help="human-readable jpeg quality preset: web, balanced, or archive",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="request retry attempts for pages, metadata, and tiles (default: 3)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=0.75,
        help="base backoff in seconds before retrying failed requests (default: 0.75)",
    )
    parser.add_argument(
        "--proxy",
        help="proxy URL for artwork page, metadata, and tile requests (for example http://127.0.0.1:7890 or socks5://127.0.0.1:7890)",
    )
    parser.add_argument(
        "--rerun-failures",
        type=int,
        default=0,
        help="how many extra batch rounds to rerun artworks that still failed after request-level retries",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop the batch immediately after the first failed artwork",
    )
    parser.add_argument(
        "--resume-batch",
        action="store_true",
        help="resume an interrupted batch from the state file; succeeded and skipped tasks are not rerun",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="start a new batch using only the failed tasks recorded in the state file",
    )
    parser.add_argument(
        "--batch-state-file",
        help="custom path for the batch state JSON file used by --resume-batch or --rerun-failed",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="compatibility alias for --output-conflict overwrite",
    )
    parser.add_argument(
        "--output-conflict",
        choices=[policy.value for policy in OutputConflictPolicy],
        default=OutputConflictPolicy.SKIP.value,
        help="when output already exists: skip it, overwrite it, or save as a renamed file (default: skip)",
    )
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument(
        "--size",
        choices=[size.value for size in DownloadSize],
        default=DownloadSize.MAX.value,
        help="download size preset: preview, medium, large, or max (default: max)",
    )
    size_group.add_argument(
        "--max-dimension",
        type=int,
        help="choose the largest available level whose longest edge does not exceed this size",
    )
    parser.add_argument(
        "--write-metadata",
        action="store_true",
        help="write artwork metadata into the output JPEG EXIF",
    )
    parser.add_argument(
        "--write-sidecar",
        action="store_true",
        help="write artwork metadata to a JSON sidecar next to the image",
    )
    parser.add_argument(
        "--tile-only",
        action="store_true",
        help="download artwork tiles into a local .tiles directory without stitching a final image",
    )
    parser.add_argument(
        "--stitch-backend",
        choices=[backend.value for backend in StitchBackend],
        default=StitchBackend.AUTO.value,
        help="image stitch backend: auto, pillow, bigtiff, or pyvips (default: auto)",
    )
    parser.add_argument(
        "--list-sizes",
        action="store_true",
        help="inspect available download sizes for a single artwork URL and exit",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="fetch artwork metadata only and output JSON without downloading image tiles",
    )
    parser.add_argument(
        "--metadata-output",
        help="write metadata-only JSON output to a file instead of stdout",
    )
    parser.add_argument("--tui", action="store_true", help="show a richer live terminal dashboard")
    parser.add_argument("--log-file", help="write logs to a file")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser.parse_args(argv)
