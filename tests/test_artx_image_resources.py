from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from artx.download import image_writer
from artx.models import PyramidLevel, TileInfo


@pytest.fixture
def artwork(tmp_path):
    tile_path = tmp_path / "tile.png"
    with closing(Image.new("RGB", (8, 8), (12, 34, 56))) as image:
        image.save(tile_path)
    info = TileInfo(8, 8, [PyramidLevel(0, 1, 1, 0, 2)])
    return info, {(0, 0): tile_path}


def track_images(monkeypatch):
    # Load Pillow's plugins before spying: plugin initialization can create
    # internal images that are not owned by the stitcher under test.
    Image.init()
    opened = []
    closed = []
    real_close = Image.Image.close

    def close(image):
        closed.append(image)
        real_close(image)

    def track(owner, name):
        original = getattr(owner, name)

        def wrapped(*args, **kwargs):
            image = original(*args, **kwargs)
            opened.append(image)
            return image

        monkeypatch.setattr(owner, name, wrapped)

    monkeypatch.setattr(Image.Image, "close", close)
    track(Image, "new")
    track(Image, "open")
    track(Image.Image, "crop")
    track(Image.Image, "convert")
    return opened, closed


@pytest.mark.parametrize("failure", [None, "decode", "paste", "save"])
def test_pillow_closes_canvas_and_tiles_including_failure_paths(tmp_path, monkeypatch, artwork, failure):
    info, tiles = artwork
    output = tmp_path / "art.png"
    output.write_bytes(b"original result")
    if failure == "decode":
        tiles[(0, 0)].write_bytes(b"corrupt tile")
    elif failure == "paste":

        def fail_paste(*args, **kwargs):
            raise RuntimeError("paste failed")

        monkeypatch.setattr(Image.Image, "paste", fail_paste)
    elif failure == "save":

        def fail_save(image, path, **kwargs):
            Path(path).write_bytes(b"partial result")
            raise RuntimeError("save failed")

        monkeypatch.setattr(Image.Image, "save", fail_save)
    opened, closed = track_images(monkeypatch)
    if failure:
        with pytest.raises((RuntimeError, OSError)):
            image_writer._stitch_with_pillow(info, tiles, output, None, False, 90)
        assert output.read_bytes() == b"original result"
    else:
        image_writer._stitch_with_pillow(info, tiles, output, None, False, 90)
    assert opened
    assert {id(image) for image in opened} <= {id(image) for image in closed}
    assert not image_writer.build_temp_output_path(output).exists()
    if not failure:
        with closing(Image.open(output)) as result:
            assert result.size == (8, 6)
            assert result.getpixel((2, 2)) == (12, 34, 56)


@pytest.mark.parametrize("fail_flush", [False, True])
def test_bigtiff_closes_rgb_and_cropped_tiles(tmp_path, monkeypatch, artwork, fail_flush):
    info, tiles = artwork
    output = tmp_path / "art.tif"
    output.write_bytes(b"original result")

    class Canvas:
        def __setitem__(self, key, value):
            assert value == (8, 6)

        def flush(self):
            if fail_flush:
                raise OSError("disk full")

    def memmap(path, **kwargs):
        Path(path).write_bytes(b"complete tiff")
        return Canvas()

    numpy = SimpleNamespace(uint8="uint8", asarray=lambda image, **kwargs: image.size)
    tifffile = SimpleNamespace(memmap=memmap)
    monkeypatch.setattr(image_writer, "_load_streaming_tiff_modules", lambda: (numpy, tifffile))
    opened, closed = track_images(monkeypatch)
    if fail_flush:
        with pytest.raises(OSError, match="disk full"):
            image_writer._stitch_with_bigtiff(info, tiles, output, None, False)
        assert output.read_bytes() == b"original result"
    else:
        image_writer._stitch_with_bigtiff(info, tiles, output, None, False)
        assert output.read_bytes() == b"complete tiff"
    assert len(opened) >= 3  # file image, RGB conversion, cropped boundary tile
    assert {id(image) for image in opened} <= {id(image) for image in closed}
    assert not image_writer.build_bigtiff_temp_path(output).exists()


@pytest.mark.parametrize(
    "suffix,expected_options",
    [
        (".jpg", {"Q": 85, "optimize_coding": True, "strip": False}),
        (".jpeg", {"Q": 85, "optimize_coding": True, "strip": False}),
        (".webp", {"Q": 85}),
        (".png", {}),
        (".tif", {}),
    ],
)
def test_pyvips_only_passes_options_supported_by_output_format(
    tmp_path, monkeypatch, artwork, suffix, expected_options
):
    info, tiles = artwork
    output = tmp_path / f"art{suffix}"

    class VipsImage:
        width = height = 8

        def crop(self, *args):
            return self

        def write_to_file(self, path, **options):
            assert options == expected_options
            Path(path).write_bytes(b"image")

    vips = SimpleNamespace(
        Image=SimpleNamespace(
            new_from_file=lambda *args, **kwargs: VipsImage(),
            arrayjoin=lambda *args, **kwargs: VipsImage(),
        )
    )
    monkeypatch.setattr(image_writer, "_load_pyvips", lambda: vips)
    image_writer._stitch_with_pyvips(info, tiles, output, None, False, 85)
    assert output.read_bytes() == b"image"
    assert not image_writer.build_temp_output_path(output).exists()
