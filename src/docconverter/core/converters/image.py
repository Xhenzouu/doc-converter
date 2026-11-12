"""Image format converters using Pillow.

Supports conversions between common formats: .jpg, .jpeg, .jfif, .png, .webp, .bmp, .tiff.
Properly flattens transparency to white when converting transparent images (e.g. PNG)
to formats without alpha support (such as JPEG).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageColor, ImageOps

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register

log = logging.getLogger(__name__)

ALL_IMAGE_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".tiff", ".tif")

_COMMON_OPTIONS = (
    OptionSpec(
        "quality",
        "Image quality (1-100)",
        OptionKind.INT,
        90,
        help="Compression quality for lossy formats like JPEG and WebP.",
    ),
    OptionSpec(
        "background_color",
        "Background color",
        OptionKind.TEXT,
        "white",
        help="Background color used when flattening transparent images to JPEG (e.g. 'white', '#ffffff').",
    ),
)

SPEC_TO_PNG = ConversionSpec(
    id="image_to_png",
    title="Image to PNG",
    category=Category.IMAGE,
    src_exts=tuple(e for e in ALL_IMAGE_EXTS if e != ".png"),
    dst_ext=".png",
    icon="image",
    description="Convert images to lossless PNG format.",
    options=_COMMON_OPTIONS,
)

SPEC_TO_JPEG = ConversionSpec(
    id="image_to_jpeg",
    title="Image to JPEG",
    category=Category.IMAGE,
    src_exts=tuple(e for e in ALL_IMAGE_EXTS if e not in (".jpg", ".jpeg")),
    dst_ext=".jpg",
    icon="image",
    description="Convert images to JPEG format (transparency flattened to white).",
    options=_COMMON_OPTIONS,
)

SPEC_TO_WEBP = ConversionSpec(
    id="image_to_webp",
    title="Image to WEBP",
    category=Category.IMAGE,
    src_exts=tuple(e for e in ALL_IMAGE_EXTS if e != ".webp"),
    dst_ext=".webp",
    icon="image",
    description="Convert images to modern WebP format.",
    options=_COMMON_OPTIONS,
)

SPEC_TO_BMP = ConversionSpec(
    id="image_to_bmp",
    title="Image to BMP",
    category=Category.IMAGE,
    src_exts=tuple(e for e in ALL_IMAGE_EXTS if e != ".bmp"),
    dst_ext=".bmp",
    icon="image",
    description="Convert images to Windows Bitmap (BMP) format.",
    options=_COMMON_OPTIONS,
)

SPEC_TO_TIFF = ConversionSpec(
    id="image_to_tiff",
    title="Image to TIFF",
    category=Category.IMAGE,
    src_exts=tuple(e for e in ALL_IMAGE_EXTS if e not in (".tiff", ".tif")),
    dst_ext=".tiff",
    icon="image",
    description="Convert images to TIFF format.",
    options=_COMMON_OPTIONS,
)


def flatten_transparency(img: Image.Image, bg_color_name: str = "white") -> Image.Image:
    """Flatten an image with an alpha channel onto a solid background color."""
    try:
        rgb_color = ImageColor.getrgb(bg_color_name)
    except Exception:
        rgb_color = (255, 255, 255)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba_img = img.convert("RGBA")
        background = Image.new("RGB", rgba_img.size, rgb_color)
        alpha_mask = rgba_img.split()[3]
        background.paste(rgba_img, mask=alpha_mask)
        return background

    if img.mode != "RGB":
        return img.convert("RGB")

    return img


class BaseImageConverter(BaseConverter):
    """Base class for Pillow-based image conversions."""

    dst_format: str = "PNG"
    supports_alpha: bool = True

    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        quality = max(1, min(100, opts["quality"]))
        bg_color = opts["background_color"]

        ctx.progress(0.1, f"Opening image '{ctx.src.name}'")
        try:
            with Image.open(ctx.src) as img:
                # Handle EXIF orientation tag if present
                img = ImageOps.exif_transpose(img)
                img.load()
        except Exception as exc:
            raise ConversionError(f"Could not open image '{ctx.src.name}': {exc}") from exc

        ctx.check_cancelled()
        ctx.progress(0.5, f"Converting to {self.dst_format}")

        if not self.supports_alpha:
            img = flatten_transparency(img, bg_color)
        else:
            # Ensure mode is compatible with target format
            if self.dst_format == "PNG" and img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
            elif self.dst_format == "WEBP" and img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
            elif self.dst_format == "BMP" and img.mode not in ("RGB", "L", "P"):
                img = flatten_transparency(img, bg_color)

        destination = ctx.output_path()
        ctx.check_cancelled()
        ctx.progress(0.8, f"Saving {self.dst_format}")

        save_kwargs = {}
        if self.dst_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality
        if self.dst_format == "JPEG":
            save_kwargs["optimize"] = True

        try:
            img.save(destination, format=self.dst_format, **save_kwargs)
        except Exception as exc:
            raise ConversionError(f"Failed to save image '{destination.name}': {exc}") from exc

        ctx.track(destination)
        ctx.progress(1.0, "Done")
        return [destination]


@register(SPEC_TO_PNG)
class ImageToPngConverter(BaseImageConverter):
    dst_format = "PNG"
    supports_alpha = True


@register(SPEC_TO_JPEG)
class ImageToJpegConverter(BaseImageConverter):
    dst_format = "JPEG"
    supports_alpha = False


@register(SPEC_TO_WEBP)
class ImageToWebpConverter(BaseImageConverter):
    dst_format = "WEBP"
    supports_alpha = True


@register(SPEC_TO_BMP)
class ImageToBmpConverter(BaseImageConverter):
    dst_format = "BMP"
    supports_alpha = False


@register(SPEC_TO_TIFF)
class ImageToTiffConverter(BaseImageConverter):
    dst_format = "TIFF"
    supports_alpha = True
