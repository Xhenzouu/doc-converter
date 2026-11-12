import threading

import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.txt_to_pdf import (
    SPEC,
    TxtToPdfConverter,
)

TOOL = "txt_to_pdf"


@pytest.fixture
def txt_file(tmp_path):
    def make(content="Line 1\nLine 2\nLine 3\n", name="sample.txt"):
        path = tmp_path / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    return make


def run(src, *, output_dir=None, overwrite=False, progress_cb=None, cancel_event=None, **options):
    job = ConversionJob(
        src=src, tool_id=TOOL, output_dir=output_dir, options=options, overwrite=overwrite
    )
    return TxtToPdfConverter().convert(job, progress_cb, cancel_event)


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_basic_txt_to_pdf(txt_file):
    src = txt_file("Hello, World!\nThis is a test document.\n")
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1

    pdf_bytes = result.outputs[0].read_bytes()
    # Check PDF header
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500


def test_unicode_and_special_characters(txt_file):
    # Tests accents, math symbols, and Cyrillic with DejaVu font
    text = "Unicode test:\nAccents: à é î ö ú\nGreek: α β γ\nCyrillic: Привет\nSymbols: → ± ≠\n"
    src = txt_file(text)
    result = run(src)
    assert result.ok, result.error
    pdf_bytes = result.outputs[0].read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")


def test_line_numbers_option(txt_file):
    text = "Alpha\nBeta\nGamma\nDelta\n"
    src = txt_file(text)
    result = run(src, line_numbers=True)
    assert result.ok, result.error
    assert result.outputs[0].exists()


def test_page_size_and_orientation_options(txt_file):
    src = txt_file("Testing letter landscape layout")
    result = run(src, page_size="Letter", orientation="landscape", font_size=12)
    assert result.ok, result.error
    assert result.outputs[0].exists()


def test_empty_text_file_warns(txt_file):
    src = txt_file("")
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)
    # Still produces a valid PDF file
    assert result.outputs[0].read_bytes().startswith(b"%PDF-")


def test_cancellation(txt_file):
    src = txt_file("Some content\n" * 100)
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(txt_file):
    src = txt_file("Line\n" * 250)
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 2


def test_output_dir(txt_file, tmp_path):
    src = txt_file("Simple line")
    out = tmp_path / "pdf_folder"
    result = run(src, output_dir=out)
    assert result.ok
    assert result.outputs[0].parent == out
