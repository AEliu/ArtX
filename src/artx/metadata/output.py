from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from PIL import Image

from ..models import ArtworkMetadata
from .parsers import clean_text


def build_exif_bytes(metadata: ArtworkMetadata) -> bytes:
    exif = Image.Exif()

    def utf16le_bytes(value: str) -> bytes:
        return value.encode("utf-16le") + b"\x00\x00"

    def set_exif_value(tag: int, value: str | bytes) -> None:
        cast(Any, exif)[tag] = value

    title = clean_text(metadata.title)
    creator = clean_text(metadata.creator)
    description = clean_text(metadata.description)
    rights = clean_text(metadata.rights)

    comment_parts = []
    if metadata.source_url:
        comment_parts.append(f"Source URL: {metadata.source_url}")
    if metadata.date_created:
        comment_parts.append(f"Date Created: {metadata.date_created}")
    if metadata.external_link:
        comment_parts.append(f"External Link: {metadata.external_link}")
    if metadata.partner:
        comment_parts.append(f"Partner: {metadata.partner}")
    if rights and rights not in comment_parts:
        comment_parts.append(f"Rights: {rights}")
    comment = clean_text(" | ".join(comment_parts))

    if description:
        set_exif_value(270, description[:2000])
    if creator:
        set_exif_value(315, creator[:512])
        set_exif_value(40093, utf16le_bytes(creator[:512]))
    if rights:
        set_exif_value(33432, rights[:2000])
    if title:
        set_exif_value(40091, utf16le_bytes(title[:512]))
    if comment:
        set_exif_value(40092, utf16le_bytes(comment[:1500]))
        set_exif_value(37510, b"ASCII\x00\x00\x00" + comment[:1500].encode("ascii", errors="replace"))

    return exif.tobytes()


def metadata_to_dict(metadata: ArtworkMetadata) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in metadata.__dict__.items():
        cleaned = clean_text(value)
        if cleaned:
            result[key] = cleaned
    return result


def write_metadata_sidecar(output_path: Path, metadata: ArtworkMetadata) -> Path:
    sidecar_path = output_path.with_suffix(output_path.suffix + ".json")
    payload = metadata_to_dict(metadata)
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sidecar_path
