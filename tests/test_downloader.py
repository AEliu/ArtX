from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from Crypto.Cipher import AES
from PIL import Image

from google_art.constants import AES_IV, AES_KEY, ENCRYPTION_MARKER
from google_art.downloader import GoogleArtDownloader
from google_art.models import DownloadOptions

ASSET_HTML = """
[123]\n,"//lh3.googleusercontent.com/ci/TileBase","SecretToken"]
<script type=\"application/ld+json\">{\"name\":\"Test Artwork\"}</script>
"""

TILE_INFO_XML = """
<TileInfo tile_width=\"32\" tile_height=\"32\">
    <pyramid_level num_tiles_x=\"2\" num_tiles_y=\"2\" empty_pels_x=\"0\" empty_pels_y=\"0\" />
</TileInfo>
"""


@pytest.fixture()
def tile_assets():
    colors = {
        (0, 0): (255, 0, 0),
        (1, 0): (0, 255, 0),
        (0, 1): (0, 0, 255),
        (1, 1): (255, 255, 0),
    }
    data: dict[tuple[int, int], bytes] = {}
    for coords, color in colors.items():
        img = Image.new("RGB", (32, 32), color)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        data[coords] = buffer.getvalue()
    return data


def test_downloader_reconstructs_image(tmp_path: Path, httpx_mock, tile_assets):
    asset_url = "https://artsandculture.google.com/asset/sample-id"
    httpx_mock.add_response(url=asset_url, text=ASSET_HTML)
    httpx_mock.add_response(url="https://lh3.googleusercontent.com/ci/TileBase=g", text=TILE_INFO_XML)

    tile_pattern = re.compile(
        r"https://lh3\.googleusercontent\.com/ci/TileBase=x(?P<x>\d+)-y(?P<y>\d+)-z(?P<z>\d+)-t[0-9A-Za-z_]+"
    )

    def tile_callback(request: httpx.Request) -> httpx.Response:  # pragma: no cover - callback logic
        match = tile_pattern.search(str(request.url))
        assert match is not None
        coords = (int(match.group("x")), int(match.group("y")))
        payload = tile_assets[coords]
        return httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})

    httpx_mock.add_callback(tile_callback, url=tile_pattern, is_reusable=True)

    downloader = GoogleArtDownloader(show_progress=False)
    opts = DownloadOptions(asset="sample-id", out_path=str(tmp_path / "output.png"), fmt="png", overwrite=True)
    result_path = downloader.download(opts)
    downloader.close()

    assert result_path.exists()
    with Image.open(result_path) as image:
        assert image.size == (64, 64)
        assert image.getpixel((10, 10))[0] > 200  # red tile present
        assert image.getpixel((40, 10))[1] > 200  # green tile
        assert image.getpixel((10, 40))[2] > 200  # blue tile


def test_downloader_accepts_prefixed_truncated_jpeg(tmp_path: Path, httpx_mock):
    asset_url = "https://artsandculture.google.com/asset/sample-id"
    httpx_mock.add_response(url=asset_url, text=ASSET_HTML)
    httpx_mock.add_response(url="https://lh3.googleusercontent.com/ci/TileBase=g", text=TILE_INFO_XML)

    tile_pattern = re.compile(
        r"https://lh3\.googleusercontent\.com/ci/TileBase=x(?P<x>\d+)-y(?P<y>\d+)-z(?P<z>\d+)-t[0-9A-Za-z_]+"
    )

    buffer = BytesIO()
    Image.new("RGB", (32, 32), (128, 64, 32)).save(buffer, format="JPEG")
    jpeg_payload = b"\n\n\n\n" + buffer.getvalue() + b"\r\x01\x00\x00"

    def tile_callback(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg_payload, headers={"Content-Type": "image/jpeg"})

    httpx_mock.add_callback(tile_callback, url=tile_pattern, is_reusable=True)

    downloader = GoogleArtDownloader(show_progress=False)
    opts = DownloadOptions(asset="sample-id", out_path=str(tmp_path / "output.jpg"), fmt="jpg", overwrite=True)
    result_path = downloader.download(opts)
    downloader.close()

    with Image.open(result_path) as image:
        assert image.size == (64, 64)


def test_downloader_decrypts_encrypted_tile_payload(tmp_path: Path, httpx_mock):
    asset_url = "https://artsandculture.google.com/asset/sample-id"
    httpx_mock.add_response(url=asset_url, text=ASSET_HTML)
    httpx_mock.add_response(url="https://lh3.googleusercontent.com/ci/TileBase=g", text=TILE_INFO_XML)

    tile_pattern = re.compile(
        r"https://lh3\.googleusercontent\.com/ci/TileBase=x(?P<x>\d+)-y(?P<y>\d+)-z(?P<z>\d+)-t[0-9A-Za-z_]+"
    )

    buffer = BytesIO()
    Image.new("RGB", (32, 32), (12, 34, 56)).save(buffer, format="JPEG")
    jpeg_bytes = buffer.getvalue()
    header = jpeg_bytes[:64]
    body = jpeg_bytes[64:]
    pad = (-len(body)) % 16
    encrypted_body = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV).encrypt(body + (b"\x00" * pad))
    encrypted_payload = (
        ENCRYPTION_MARKER
        + header
        + len(encrypted_body).to_bytes(4, "little")
        + encrypted_body
        + b""
        + len(header).to_bytes(4, "little")
    )

    def tile_callback(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=encrypted_payload, headers={"Content-Type": "image/jpeg"})

    httpx_mock.add_callback(tile_callback, url=tile_pattern, is_reusable=True)

    downloader = GoogleArtDownloader(show_progress=False)
    opts = DownloadOptions(asset="sample-id", out_path=str(tmp_path / "output.jpg"), fmt="jpg", overwrite=True)
    result_path = downloader.download(opts)
    downloader.close()

    with Image.open(result_path) as image:
        assert image.size == (64, 64)
