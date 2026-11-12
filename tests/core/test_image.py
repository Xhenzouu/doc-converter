import threading

from PIL import Image
import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.image import (
    SPEC_TO_BMP,
    SPEC_TO_JPEG,
    SPEC_TO_PNG,
    SPEC_TO_TIFF,
    SPEC_TO_WEBP,
    ImageToBmpConverter,
    ImageToJpegConverter,
    ImageToPngConverter,
    ImageToTiffConverter,
    ImageToWebpConverter,
)


@pytest.fixture
def make_image(tmp_path):
    def factory(size=(20, 20), mode="RGB", color=(255, 0, 0), ext=".png", name=None):
        filename = name or f"image{ext}"
        path = tmp_path / filename
        im = Image.new(mode, size, color)
        im.save(path)
        return path

    return factory


def test_registered():
    load_builtin_converters()
    assert "image_to_png" in registry
    assert "image_to_jpeg" in registry
    assert "image_to_webp" in registry
    assert "image_to_bmp" in registry
    assert "image_to_tiff" in registry


def test_png_to_jpeg_conversion(make_image):
    src = make_image(mode="RGB", color=(100, 150, 200), ext=".png")
    job = ConversionJob(src=src, tool_id="image_to_jpeg")
    result = ImageToJpegConverter().convert(job)

    assert result.ok, result.error
    assert len(result.outputs) == 1
    assert result.outputs[0].suffix.lower() == ".jpg"

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        assert out_img.size == (20, 20)


def test_transparency_flattened_to_white_for_jpeg(tmp_path):
    # Create an RGBA image with fully transparent pixels
    path = tmp_path / "transparent.png"
    im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))  # Completely transparent
    im.save(path)

    job = ConversionJob(src=path, tool_id="image_to_jpeg")
    result = ImageToJpegConverter().convert(job)
    assert result.ok, result.error

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"
        # Transparent areas must be flattened to pure white (255, 255, 255)
        pixel = out_img.getpixel((0, 0))
        assert pixel == (255, 255, 255)


def test_transparency_custom_background_color(tmp_path):
    # Flatten transparent image to black background
    path = tmp_path / "transparent_black.png"
    im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    im.save(path)

    job = ConversionJob(
        src=path,
        tool_id="image_to_jpeg",
        options={"background_color": "black"},
    )
    result = ImageToJpegConverter().convert(job)
    assert result.ok, result.error

    with Image.open(result.outputs[0]) as out_img:
        pixel = out_img.getpixel((0, 0))
        assert pixel == (0, 0, 0)


def test_jpeg_to_png_conversion(make_image):
    src = make_image(mode="RGB", color=(50, 60, 70), ext=".jpg")
    job = ConversionJob(src=src, tool_id="image_to_png")
    result = ImageToPngConverter().convert(job)

    assert result.ok, result.error
    assert result.outputs[0].suffix.lower() == ".png"

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "PNG"


def test_png_to_webp_conversion(make_image):
    src = make_image(mode="RGBA", color=(10, 20, 30, 128), ext=".png")
    job = ConversionJob(src=src, tool_id="image_to_webp")
    result = ImageToWebpConverter().convert(job)

    assert result.ok, result.error
    assert result.outputs[0].suffix.lower() == ".webp"

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "WEBP"


def test_jpeg_to_bmp_conversion(make_image):
    src = make_image(mode="RGB", color=(80, 90, 100), ext=".jpg")
    job = ConversionJob(src=src, tool_id="image_to_bmp")
    result = ImageToBmpConverter().convert(job)

    assert result.ok, result.error
    assert result.outputs[0].suffix.lower() == ".bmp"

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "BMP"


def test_png_to_tiff_conversion(make_image):
    src = make_image(mode="RGB", color=(12, 34, 56), ext=".png")
    job = ConversionJob(src=src, tool_id="image_to_tiff")
    result = ImageToTiffConverter().convert(job)

    assert result.ok, result.error
    assert result.outputs[0].suffix.lower() == ".tiff"

    with Image.open(result.outputs[0]) as out_img:
        assert out_img.format == "TIFF"


def test_jfif_conversion(tmp_path):
    path = tmp_path / "sample.jfif"
    im = Image.new("RGB", (15, 15), (200, 100, 50))
    im.save(path, format="JPEG")

    job = ConversionJob(src=path, tool_id="image_to_png")
    result = ImageToPngConverter().convert(job)
    assert result.ok, result.error
    assert result.outputs[0].suffix.lower() == ".png"


def test_corrupt_image_fails(tmp_path):
    bad = tmp_path / "corrupt.png"
    bad.write_text("this is not image data")

    job = ConversionJob(src=bad, tool_id="image_to_jpeg")
    result = ImageToJpegConverter().convert(job)
    assert not result.ok
    assert result.status is JobStatus.FAILED
    assert "Could not open image" in (result.error or "")


def test_cancellation(make_image):
    src = make_image(ext=".png")
    job = ConversionJob(src=src, tool_id="image_to_jpeg")
    cancel = threading.Event()
    cancel.set()

    result = ImageToJpegConverter().convert(job, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(make_image):
    src = make_image(ext=".png")
    job = ConversionJob(src=src, tool_id="image_to_jpeg")
    events = []

    result = ImageToJpegConverter().convert(job, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 3
