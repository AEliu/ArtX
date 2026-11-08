from google_art.parser import parse_page, parse_tile_info

SAMPLE_HTML = """
[123]\n,"//lh3.googleusercontent.com/ci/ExamplePath","SecreTT0ken"]
<script type=\"application/ld+json\">{\"name\":\"Sample \\u0026 Artwork\"}</script>
"""


def test_parse_page_extracts_base_url_and_token():
    page = parse_page(SAMPLE_HTML)
    assert page.base_url == "https://lh3.googleusercontent.com/ci/ExamplePath"
    assert page.token == "SecreTT0ken"
    assert page.name == "Sample & Artwork"


def test_parse_tile_info_round_trip():
    xml_text = """
    <TileInfo tile_width=\"256\" tile_height=\"256\">
        <pyramid_level num_tiles_x=\"1\" num_tiles_y=\"1\" empty_pels_x=\"0\" empty_pels_y=\"0\" />
        <pyramid_level num_tiles_x=\"2\" num_tiles_y=\"2\" empty_pels_x=\"10\" empty_pels_y=\"20\" />
    </TileInfo>
    """
    info = parse_tile_info(xml_text)
    assert info.tile_width == 256
    assert info.tile_height == 256
    assert len(info.pyramid_levels) == 2
    idx, level = info.choose_level(target_edge=500)
    assert idx == 1
    assert level.num_tiles_x == 2
    width, height = level.pixel_dimensions(info.tile_width, info.tile_height)
    assert width == 256 * 2 - 10
    assert height == 256 * 2 - 20
