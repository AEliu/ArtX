from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageFile, UnidentifiedImageError

from google_art import assemblers
from google_art.assemblers import (
    AssemblerUnavailableError,
    PillowImageAssembler,
    PyvipsImageAssembler,
    pick_assembler,
)


@pytest.mark.parametrize("fmt,expected", [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP")])
def test_pillow_crops_resizes_and_uses_requested_format(tmp_path: Path, fmt, expected):
    buffer = BytesIO()
    with Image.new("RGB", (16, 16), "red") as tile:
        tile.save(buffer, format="PNG")
    assembler = PillowImageAssembler()
    assembler.begin((32, 16))
    try:
        assembler.paste_tile(0, 0, 16, 16, b"\n\n" + buffer.getvalue())
        output = tmp_path / "nested" / "output.tmp"
        assert assembler.finalize_save(output, 16, 12, 8, 6, fmt) == output
        with Image.open(output) as image:
            assert image.size == (8, 6)
            assert image.format == expected
            assert image.getpixel((4, 3))[0] > 240
    finally:
        assembler.close()


def test_pillow_closes_old_canvas_and_close_is_repeatable():
    assembler = PillowImageAssembler()
    assembler.begin((2, 2))
    original = assembler._canvas
    assembler.begin((3, 3))
    with pytest.raises(ValueError, match="closed"):
        original.getpixel((0, 0))
    current = assembler._canvas
    assembler.close()
    assembler.close()
    with pytest.raises(ValueError, match="closed"):
        current.getpixel((0, 0))


def test_pillow_restores_decode_setting_on_failure():
    assembler = PillowImageAssembler()
    assembler.begin((2, 2))
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    try:
        with pytest.raises(UnidentifiedImageError):
            assembler.paste_tile(0, 0, 2, 2, b"invalid image")
        assert ImageFile.LOAD_TRUNCATED_IMAGES is previous
    finally:
        assembler.close()


def test_pillow_releases_temporary_images_when_save_fails(tmp_path, monkeypatch):
    assembler = PillowImageAssembler()
    assembler.begin((8, 8))
    closed = []
    original_close = Image.Image.close

    def close(image):
        closed.append(image)
        original_close(image)

    def fail_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "close", close)
    monkeypatch.setattr(Image.Image, "save", fail_save)
    try:
        with pytest.raises(OSError, match="disk full"):
            assembler.finalize_save(tmp_path / "output.png", 6, 6, 3, 3, "png")
        assert len(closed) == 2  # cropped and resized images
        assert assembler._canvas not in closed
    finally:
        assembler.close()


@pytest.mark.parametrize(
    "fmt,method,kwargs",
    [
        ("png", "pngsave", {}),
        ("jpg", "jpegsave", {"Q": 90}),
        ("jpeg", "jpegsave", {"Q": 90}),
        ("webp", "webpsave", {"Q": 90}),
    ],
)
def test_vips_resizes_by_scale_and_saves_explicit_format(tmp_path, monkeypatch, fmt, method, kwargs):
    vips = MagicMock()
    monkeypatch.setattr(assemblers, "import_module", lambda name: vips)
    assembler = PyvipsImageAssembler()
    assembler.begin((200, 100))
    cropped = vips.Image.black.return_value.crop.return_value
    resized = cropped.resize.return_value
    output = tmp_path / "output.tmp"
    assert assembler.finalize_save(output, 180, 90, 60, 29, fmt) == output
    cropped.resize.assert_called_once_with(60 / 180, vscale=29 / 90, kernel="lanczos3")
    getattr(resized, method).assert_called_once_with(str(output), **kwargs)
    resized.write_to_file.assert_not_called()
    assembler.close()
    assert assembler._img is None


@pytest.mark.parametrize("error", [ImportError("missing pyvips"), OSError("missing libvips")])
def test_vips_missing_dependency_only_falls_back_in_auto(monkeypatch, error):
    def missing(name):
        raise error

    monkeypatch.setattr(assemblers, "import_module", missing)
    assert isinstance(pick_assembler("auto", (20_000, 100), 10), PillowImageAssembler)
    with pytest.raises(AssemblerUnavailableError, match="pyvips/libvips"):
        pick_assembler("vips", (10, 10), 1)


def test_small_auto_and_explicit_pillow_do_not_load_vips(monkeypatch):
    loader = MagicMock(side_effect=AssertionError("must remain lazy"))
    monkeypatch.setattr(assemblers, "import_module", loader)
    assert isinstance(pick_assembler("auto", (100, 100), 1), PillowImageAssembler)
    assert isinstance(pick_assembler("pillow", (20_000, 20_000), 4000), PillowImageAssembler)
    loader.assert_not_called()


def test_invalid_backend_is_rejected():
    with pytest.raises(ValueError, match="assembler"):
        pick_assembler("typo", (100, 100), 1)
