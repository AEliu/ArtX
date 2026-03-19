class DownloadError(RuntimeError):
    pass


def build_error_guidance(message: str) -> list[str]:
    lowered = message.lower()
    guidance: list[str] = []

    if "tile x=" in lowered and any(token in lowered for token in ("ssl", "eof", "timed out", "connection reset")):
        guidance.extend(
            [
                "This usually indicates a transient network failure while downloading one tile.",
                "Already downloaded tiles stay in the cache and will be reused on the next run.",
                "Try rerunning with higher request retries, for example `--retries 5 --retry-backoff 1.0`.",
                "If the failure repeats, lower tile concurrency, for example `--workers 16` instead of a higher value.",
            ]
        )

    if "image is too large for safe in-memory stitching" in lowered:
        guidance.extend(
            [
                "This is a memory safety guard, not an out-of-memory crash.",
                "Try a smaller size such as `--size large` or use `--max-dimension ...`.",
                ("For very large artworks, the `bigtiff` TIFF/BigTIFF path is the intended safe output path."),
                "If you still need JPEG later, convert the TIFF result as a separate post-process step.",
            ]
        )

    return guidance
