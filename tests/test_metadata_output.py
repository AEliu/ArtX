from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from googleart_download.cli import resolve_default_metadata_output_path
from googleart_download.metadata import metadata_to_dict, write_metadata_sidecar
from googleart_download.metadata.parsers import normalize_asset_url, parse_artwork_metadata, parse_page_info
from googleart_download.models import ArtworkMetadata, DownloadSize


class MetadataOutputTests(unittest.TestCase):
    def test_parse_artwork_metadata_extracts_core_fields(self) -> None:
        html = """
        <script type="application/ld+json">
        [{"@type":"CreativeWork","name":"Artwork Title","author":"Artist Name","description":"Long description","url":"https://example.com/art"}]
        </script>
        ["Date Created",[["1890"]],0]
        ["Rights",[["Museum Rights"]],0]
        ["External Link",[["Museum page","https://museum.example"]],0]
        """

        metadata = parse_artwork_metadata(html, fallback_url="https://fallback", fallback_title="Fallback")

        self.assertEqual(metadata.title, "Artwork Title")
        self.assertEqual(metadata.creator, "Artist Name")
        self.assertEqual(metadata.description, "Long description")
        self.assertEqual(metadata.source_url, "https://example.com/art")
        self.assertEqual(metadata.date_created, "1890")
        self.assertEqual(metadata.rights, "Museum Rights")
        self.assertEqual(metadata.external_link, "Museum page")

    def test_write_metadata_sidecar_outputs_json(self) -> None:
        metadata = ArtworkMetadata(
            title="Artwork Title",
            creator="Artist Name",
            description="Description",
            source_url="https://example.com/art",
        )

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "artwork.jpg"
            output_path.write_bytes(b"fake")
            sidecar = write_metadata_sidecar(output_path, metadata)
            payload = json.loads(sidecar.read_text(encoding="utf-8"))

        self.assertEqual(payload["title"], "Artwork Title")
        self.assertEqual(payload["creator"], "Artist Name")
        self.assertEqual(payload["description"], "Description")
        self.assertEqual(payload["source_url"], "https://example.com/art")
        self.assertEqual(sidecar.name, "artwork.jpg.json")

    def test_metadata_to_dict_omits_empty_values(self) -> None:
        payload = metadata_to_dict(ArtworkMetadata(title="Title", creator=None, description=""))
        self.assertEqual(payload, {"title": "Title"})

    def test_normalize_asset_url_strips_terminal_wrapped_whitespace(self) -> None:
        raw = (
            "https://artsandculture.google.com/asset/%E6%98%9F%E5%A4\n"
            "%9C-%E6%96%87%E6%A3%AE%E7%89%B9%C2%B7%E6%A2%B5%C2%B7%E9%AB%98/bgEuwDxel93-Pg"
        )
        normalized = normalize_asset_url(raw)
        self.assertNotIn("\n", normalized)
        self.assertEqual(
            normalized,
            "https://artsandculture.google.com/asset/%E6%98%9F%E5%A4%9C-"
            "%E6%96%87%E6%A3%AE%E7%89%B9%C2%B7%E6%A2%B5%C2%B7%E9%AB%98/bgEuwDxel93-Pg",
        )

    def test_normalize_asset_url_strips_query_and_fragment(self) -> None:
        normalized = normalize_asset_url("https://artsandculture.google.com/asset/example/id?ms=%7B%7D#details")
        self.assertEqual(normalized, "https://artsandculture.google.com/asset/example/id")

    def test_normalize_asset_url_accepts_bare_asset_id(self) -> None:
        normalized = normalize_asset_url("3QFHLJgXCmQm2Q")
        self.assertEqual(normalized, "https://artsandculture.google.com/asset/3QFHLJgXCmQm2Q")

    def test_parse_page_info_uses_canonical_asset_url_from_og_url(self) -> None:
        html = """
        <html>
          <head>
            <title>Artwork — Google Arts &amp; Culture</title>
            <meta property="og:url" content="https://artsandculture.google.com/asset/example/id?ms=%7B%7D">
          </head>
          <body>
            ]\n,"//lh3.googleusercontent.com/ci/example",null
          </body>
        </html>
        """

        page = parse_page_info(html, fetched_url="https://g.co/arts/example")

        self.assertEqual(page.title, "Artwork")
        self.assertEqual(page.asset_url, "https://artsandculture.google.com/asset/example/id")

    def test_metadata_to_dict_can_be_used_for_metadata_only_payload(self) -> None:
        metadata = ArtworkMetadata(title="Artwork Title", creator="Artist Name", source_url="https://example.com/art")
        payload = metadata_to_dict(metadata)
        payload["asset_url"] = "https://example.com/art"
        self.assertEqual(
            payload,
            {
                "title": "Artwork Title",
                "creator": "Artist Name",
                "source_url": "https://example.com/art",
                "asset_url": "https://example.com/art",
            },
        )

    def test_default_metadata_output_path_matches_image_naming_rules(self) -> None:
        path = resolve_default_metadata_output_path(
            output_dir="downloads",
            filename=None,
            title="Artwork Title",
            download_size=DownloadSize.MEDIUM,
            max_dimension=None,
        )
        self.assertEqual(path.name, "Artwork Title.medium.metadata.json")

    def test_default_metadata_output_path_respects_explicit_filename(self) -> None:
        path = resolve_default_metadata_output_path(
            output_dir="downloads",
            filename="custom-name.jpg",
            title="Artwork Title",
            download_size=DownloadSize.MAX,
            max_dimension=None,
        )
        self.assertEqual(path.name, "custom-name.metadata.json")

    def test_default_metadata_output_path_uses_google_art_fallback_title(self) -> None:
        path = resolve_default_metadata_output_path(
            output_dir="downloads",
            filename=None,
            title="google-art",
            download_size=DownloadSize.MAX,
            max_dimension=None,
        )
        self.assertEqual(path.name, "google-art.metadata.json")


if __name__ == "__main__":
    unittest.main()
