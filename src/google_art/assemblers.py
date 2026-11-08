from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import closing
from importlib import import_module
from io import BytesIO
from pathlib import Path
from threading import RLock

from PIL import Image, ImageFile

_pillow_decode_lock = RLock()


class AssemblerUnavailableError(RuntimeError):
    """An optional image backend could not be loaded."""


class ImageAssembler(ABC):
    @abstractmethod
    def begin(self, canvas_size: tuple[int, int]) -> None:  # (width, height)
        ...

    @abstractmethod
    def paste_tile(self, x: int, y: int, tile_w: int, tile_h: int, raw_bytes: bytes) -> None: ...

    @abstractmethod
    def finalize_save(self, out_path: Path, crop_w: int, crop_h: int, target_w: int, target_h: int, fmt: str) -> Path:
        """Crop to (crop_w,crop_h), then resize to (target_w,target_h) if different, and save."""
        ...

    @abstractmethod
    def close(self) -> None: ...


class PillowImageAssembler(ImageAssembler):
    def __init__(self) -> None:
        self._canvas: Image.Image | None = None

    def begin(self, canvas_size: tuple[int, int]) -> None:
        self.close()
        self._canvas = Image.new("RGB", canvas_size, "white")

    def paste_tile(self, x: int, y: int, tile_w: int, tile_h: int, raw_bytes: bytes) -> None:
        assert self._canvas is not None
        # Google 有时会在 JPEG 前面加空白且末尾不完整
        normalized = raw_bytes.lstrip(b"\r\n\t ")
        # Pillow exposes this setting globally; serialize our decoders while it
        # is temporarily enabled, including when callers use worker threads.
        with _pillow_decode_lock:
            previous = ImageFile.LOAD_TRUNCATED_IMAGES
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            try:
                with closing(Image.open(BytesIO(normalized))) as tile_img:
                    with closing(tile_img.convert("RGB")) as tile_rgb:
                        self._canvas.paste(tile_rgb, (x * tile_w, y * tile_h))
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = previous

    def finalize_save(self, out_path: Path, crop_w: int, crop_h: int, target_w: int, target_h: int, fmt: str) -> Path:
        assert self._canvas is not None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        output_format = "JPEG" if fmt.lower() == "jpg" else fmt.upper()
        with closing(self._canvas.crop((0, 0, crop_w, crop_h))) as cropped:
            if (target_w, target_h) != (crop_w, crop_h):
                with closing(cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)) as resized:
                    resized.save(out_path, format=output_format)
            else:
                cropped.save(out_path, format=output_format)
        return out_path

    def close(self) -> None:
        if self._canvas is not None:
            self._canvas.close()
        self._canvas = None


class PyvipsImageAssembler(ImageAssembler):
    def __init__(self) -> None:
        try:
            self._vips = import_module("pyvips")
        except (ImportError, OSError) as exc:
            raise AssemblerUnavailableError(
                "pyvips/libvips is unavailable. Install both or use --assembler pillow/auto."
            ) from exc
        # 尽量限制 vips 缓存，避免内存激增
        try:
            self._vips.cache_set_max_mem(800 * 1024 * 1024)
            self._vips.cache_set_max(0)
        except Exception:
            pass
        self._img = None

    def begin(self, canvas_size: tuple[int, int]) -> None:
        w, h = canvas_size
        self._img = self._vips.Image.black(w, h, bands=3)

    def paste_tile(self, x: int, y: int, tile_w: int, tile_h: int, raw_bytes: bytes) -> None:
        assert self._img is not None
        normalized = raw_bytes.lstrip(b"\r\n\t ")
        tile = self._vips.Image.new_from_buffer(normalized, "", access="sequential")
        # 统一到 3 通道 sRGB
        try:
            if tile.interpretation != "srgb":
                tile = tile.colourspace("srgb")
        except Exception:
            pass
        if tile.bands > 3:
            tile = tile[:3]
        if tile.bands < 3:
            tile = tile.bandjoin([tile] * (3 - tile.bands))
        self._img = self._img.insert(tile, x * tile_w, y * tile_h)

    def finalize_save(self, out_path: Path, crop_w: int, crop_h: int, target_w: int, target_h: int, fmt: str) -> Path:
        assert self._img is not None
        img = self._img.crop(0, 0, crop_w, crop_h)
        if (target_w, target_h) != (crop_w, crop_h):
            img = img.resize(target_w / crop_w, vscale=target_h / crop_h, kernel="lanczos3")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ext = fmt.lower()
        p = str(out_path)
        if ext in ("jpg", "jpeg"):
            img.jpegsave(p, Q=90)
        elif ext == "webp":
            img.webpsave(p, Q=90)
        elif ext == "png":
            img.pngsave(p)
        else:
            raise ValueError(f"Unsupported image format: {fmt}")
        return out_path

    def close(self) -> None:
        self._img = None


def pick_assembler(name: str, canvas_size: tuple[int, int], tile_count: int) -> ImageAssembler:
    """Choose a backend; only automatic selection may fall back to Pillow."""
    if name not in {"auto", "pillow", "vips"}:
        raise ValueError("assembler must be one of auto, pillow, vips")
    width, height = canvas_size
    want_vips = name == "vips" or (
        name == "auto" and (width * height >= 150_000_000 or tile_count >= 3000 or max(canvas_size) >= 20_000)
    )
    if want_vips:
        try:
            return PyvipsImageAssembler()
        except AssemblerUnavailableError:
            if name == "vips":
                raise
    return PillowImageAssembler()
