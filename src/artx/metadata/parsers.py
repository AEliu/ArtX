from __future__ import annotations

import json
import re
import urllib.parse
from xml.etree import ElementTree

from ..errors import DownloadError
from ..models import ArtworkMetadata, PageInfo, PyramidLevel, TileInfo

ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def normalize_asset_url(url: str) -> str:
    url = re.sub(r"\s+", "", url)
    if ASSET_ID_PATTERN.fullmatch(url):
        return f"https://artsandculture.google.com/asset/{url}"

    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        url = f"https://{url.lstrip('/')}"
        parsed = urllib.parse.urlparse(url)

    if parsed.netloc not in {"artsandculture.google.com", "g.co"}:
        raise DownloadError("only Google Arts & Culture asset URLs are supported")

    cleaned = parsed._replace(params="", query="", fragment="")
    return urllib.parse.urlunparse(cleaned)


def extract_asset_id(url: str) -> str | None:
    normalized = normalize_asset_url(url)
    parsed = urllib.parse.urlparse(normalized)
    if parsed.netloc != "artsandculture.google.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "asset":
        return parts[-1] or None
    return None


def html_unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", html_unescape(value)).strip()
    return value or None


def decode_js_escapes(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def extract_json_ld_metadata(html: str) -> dict[str, object] | None:
    matches = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I)
    for raw in matches:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "CreativeWork":
                return item
    return None


def get_str_value(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def extract_named_field(html: str, name: str) -> str | None:
    pattern = rf'\["{re.escape(name)}",\[\["(.*?)"'
    match = re.search(pattern, html)
    if not match:
        return None
    return clean_text(decode_js_escapes(match.group(1)))


def parse_artwork_metadata(html: str, fallback_url: str, fallback_title: str) -> ArtworkMetadata:
    payload = extract_json_ld_metadata(html) or {}
    title = clean_text(get_str_value(payload, "name") or fallback_title)
    creator = clean_text(get_str_value(payload, "author"))
    description = clean_text(get_str_value(payload, "description"))
    source_url = clean_text(get_str_value(payload, "url") or fallback_url)

    return ArtworkMetadata(
        title=title,
        creator=creator,
        description=description,
        source_url=source_url,
        date_created=extract_named_field(html, "Date Created"),
        rights=extract_named_field(html, "Rights"),
        external_link=extract_named_field(html, "External Link"),
        partner=extract_named_field(html, "Provider"),
    )


def parse_page_info(html: str, fetched_url: str | None = None) -> PageInfo:
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = title_match.group(1).replace("— Google Arts &amp; Culture", "").strip() if title_match else "google-art"
    title = html_unescape(title)

    match = re.search(r']\r?\n?,"(//[a-zA-Z0-9./_\-]+)",(?:"([^"]+)"|null)', html)
    if not match:
        raise DownloadError("could not find tile base URL in page HTML")

    page_url_match = re.search(r'<meta property="og:url" content="([^"]+)"', html)
    page_url = page_url_match.group(1) if page_url_match else (fetched_url or "")
    normalized_page_url = normalize_asset_url(page_url) if page_url else None
    metadata = parse_artwork_metadata(html, fallback_url=page_url, fallback_title=title)

    return PageInfo(
        title=title,
        base_url=f"https:{match.group(1)}",
        token=match.group(2) or "",
        asset_url=normalized_page_url,
        metadata=metadata,
    )


def parse_tile_info(xml_data: bytes) -> TileInfo:
    root = ElementTree.fromstring(xml_data)
    levels = [
        PyramidLevel(
            z=index,
            num_tiles_x=int(level.attrib["num_tiles_x"]),
            num_tiles_y=int(level.attrib["num_tiles_y"]),
            empty_pels_x=int(level.attrib["empty_pels_x"]),
            empty_pels_y=int(level.attrib["empty_pels_y"]),
        )
        for index, level in enumerate(root.findall("pyramid_level"))
    ]
    if not levels:
        raise DownloadError("tile metadata is missing pyramid levels")

    return TileInfo(
        tile_width=int(root.attrib["tile_width"]),
        tile_height=int(root.attrib["tile_height"]),
        levels=levels,
    )
