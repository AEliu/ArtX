from __future__ import annotations

import html
import re
from typing import Pattern

from .models import PageInfo, PyramidLevel, TileInfo

_TOKEN_RE: Pattern[str] = re.compile(r"]\s*,\s*\"(//[A-Za-z0-9./_\-]+)\",(?:\"([^\"]+)\"|null)")
_NAME_RE: Pattern[str] = re.compile(r"\"name\":\"([^\"]+)\"")


def parse_page(html_text: str) -> PageInfo:
    token_match = _TOKEN_RE.search(html_text)
    if not token_match:
        raise ValueError("Unable to locate Google Arts tile base URL in page")
    base_url = f"https:{token_match.group(1)}"
    token = token_match.group(2) or ""

    name = _extract_name(html_text)
    return PageInfo(base_url=base_url, token=token, name=name)


def _extract_name(html_text: str) -> str:
    heading_re = re.compile(
        r"<h1[^>]*>(?P<title>[^<]+)</h1><h2[^>]*>.*?<a[^>]*>"
        r"(?P<artist_first>[^\s<]+) (?P<artist_last>[^\s<]+)</a>"
        r".*?<span[^>]*>(?P<year>[^<]+)</span>",
        re.DOTALL,
    )
    match = heading_re.search(html_text)
    if match:
        parts = [
            match.group("artist_last"),
            match.group("artist_first"),
            match.group("title"),
            match.group("year"),
        ]
        return html.unescape(", ".join(parts))

    if meta_match := _NAME_RE.search(html_text):
        raw = meta_match.group(1)
        cleaned = raw.replace("\\u0026", "&")
        cleaned = cleaned.replace("&quot;", '"')
        return html.unescape(cleaned)
    return "Google Arts & Culture Artwork"


def parse_tile_info(xml_text: str) -> TileInfo:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("Invalid tile info XML") from exc

    tile_width = int(root.attrib.get("tile_width", root.attrib.get("@tile_width", 512)))
    tile_height = int(root.attrib.get("tile_height", root.attrib.get("@tile_height", 512)))

    pyramid_levels = []
    for level in root.findall("pyramid_level"):
        pyramid_levels.append(
            PyramidLevel(
                num_tiles_x=int(level.attrib.get("num_tiles_x")),
                num_tiles_y=int(level.attrib.get("num_tiles_y")),
                empty_pels_x=int(level.attrib.get("empty_pels_x", 0)),
                empty_pels_y=int(level.attrib.get("empty_pels_y", 0)),
            )
        )
    if not pyramid_levels:
        raise ValueError("Tile info XML is missing pyramid levels")
    return TileInfo(tile_width=tile_width, tile_height=tile_height, pyramid_levels=pyramid_levels)
