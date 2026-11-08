"""Publish complete images without leaving partially written destinations."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .assemblers import ImageAssembler
from .models import DownloadOptions
from .planning import DownloadPlan


def check_output(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output file '{path}' already exists. Use --overwrite to replace it.")


@contextmanager
def staged_output(path: Path, overwrite: bool) -> Iterator[Path]:
    """Publish only after encoding succeeds; cancellation also removes the staging file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            # Windows rename refuses an existing target, including on exFAT/FAT.
            os.rename(temporary, path)
        else:
            # Same-directory hard link is atomic and refuses to replace an existing file.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_image(assembler: ImageAssembler, plan: DownloadPlan, options: DownloadOptions) -> Path:
    with staged_output(plan.output_path, options.overwrite) as temporary:
        assembler.finalize_save(temporary, *plan.crop_size, *plan.target_size, options.normalized_format())
    return plan.output_path
