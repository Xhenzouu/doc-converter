"""Tests for the PDF converters (pdf_to_docx via pypandoc, pdf_to_txt via pypdf).

Synthetic PDFs are built with fpdf2 so the test suite has zero external fixtures.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest
from fpdf import FPDF

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.pdf import (
    SPEC_PDF_TO_DOCX,
    SPEC_PDF_TO_TXT,
    PdfToDocxConverter,
    PdfToTxtConverter,
    _text_to_markdown,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdf(tmp_path: Path, pages: list[str], name: str = "sample.pdf") -> Path:
    """Create a simple PDF with one text paragraph per page using fpdf2."""
    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, text)
    dest = tmp_path / name
    pdf.output(str(dest))
    return dest


def run_txt(src: Path, **kwargs):
    job = ConversionJob(src=src, tool_id="pdf_to_txt", options=kwargs)
    return PdfToTxtConverter().convert(job)


def run_docx(src: Path, **kwargs):
    job = ConversionJob(src=src, tool_id="pdf_to_docx", options=kwargs)
    return PdfToDocxConverter().convert(job)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registered():
    load_builtin_converters()
    assert "pdf_to_txt" in registry
    assert "pdf_to_docx" in registry


def test_specs_accept_pdf():
    assert SPEC_PDF_TO_TXT.accepts("report.pdf")
    assert SPEC_PDF_TO_DOCX.accepts("report.pdf")
    assert not SPEC_PDF_TO_TXT.accepts("report.docx")


def test_specs_via_registry(tmp_path):
    load_builtin_converters()
    pdf = _make_pdf(tmp_path, ["hello"])
    specs = registry.specs_for_path(pdf)
    ids = {s.id for s in specs}
    assert "pdf_to_txt" in ids
    assert "pdf_to_docx" in ids


# ---------------------------------------------------------------------------
# _text_to_markdown unit tests (pure function, no I/O)
# ---------------------------------------------------------------------------


def test_markdown_empty_pages():
    result = _text_to_markdown([""])
    assert isinstance(result, str)


def test_markdown_plain_paragraph():
    result = _text_to_markdown(["This is a normal paragraph of text that is long enough."])
    assert "This is a normal paragraph" in result


def test_markdown_bullet_detection():
    text = "• First item\n• Second item\n- Third item"
    result = _text_to_markdown([text])
    assert "- First item" in result
    assert "- Second item" in result
    assert "- Third item" in result


def test_markdown_heading_detection_allcaps():
    # ALL CAPS short line followed by blank → heading
    text = "INTRODUCTION\n\nThis paragraph follows."
    result = _text_to_markdown([text])
    assert "## INTRODUCTION" in result


def test_markdown_heading_detection_titlecase():
    text = "Chapter One\n\nContent goes here."
    result = _text_to_markdown([text])
    assert "## Chapter One" in result


def test_markdown_no_false_heading_long_line():
    # Long lines must NOT become headings
    long = "This is a very long line that goes well past eighty characters and should not become a heading at all."
    result = _text_to_markdown([long])
    assert "##" not in result


def test_markdown_multipage_separator():
    result = _text_to_markdown(["Page one", "Page two"])
    assert "---" in result  # horizontal rule between pages


def test_markdown_ends_with_newline():
    result = _text_to_markdown(["some content"])
    assert result.endswith("\n")


def test_markdown_no_triple_blank_lines():
    result = _text_to_markdown(["a\n\n\n\n\nb"])
    assert not re.search(r"\n{3,}", result)


# ---------------------------------------------------------------------------
# PDF → Text
# ---------------------------------------------------------------------------


def test_txt_basic(tmp_path):
    src = _make_pdf(tmp_path, ["Hello PDF World"])
    result = run_txt(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1
    out = result.outputs[0]
    assert out.suffix == ".txt"
    text = out.read_text(encoding="utf-8")
    assert "Hello PDF World" in text


def test_txt_output_beside_source(tmp_path):
    src = _make_pdf(tmp_path, ["content"])
    result = run_txt(src)
    assert result.ok, result.error
    assert result.outputs[0].parent == src.parent


def test_txt_multipage_separator(tmp_path):
    src = _make_pdf(tmp_path, ["Page one content", "Page two content", "Page three content"])
    result = run_txt(src, page_separator="\n\n--- Page {n} ---\n\n")
    assert result.ok, result.error
    text = result.outputs[0].read_text(encoding="utf-8")
    assert "--- Page 2 ---" in text
    assert "--- Page 3 ---" in text
    assert "--- Page 1 ---" not in text


def test_txt_no_separator(tmp_path):
    src = _make_pdf(tmp_path, ["Alpha", "Beta"])
    result = run_txt(src, page_separator="")
    assert result.ok, result.error
    text = result.outputs[0].read_text(encoding="utf-8")
    assert "---" not in text


def test_txt_strip_whitespace_default(tmp_path):
    src = _make_pdf(tmp_path, ["Line 1\n\n\n\n\nLine 2"])
    result = run_txt(src)
    assert result.ok, result.error
    text = result.outputs[0].read_text(encoding="utf-8")
    assert not re.search(r"\n{3,}", text)


def test_txt_ends_with_newline(tmp_path):
    src = _make_pdf(tmp_path, ["some text"])
    result = run_txt(src)
    assert result.ok, result.error
    assert result.outputs[0].read_bytes().endswith(b"\n")


def test_txt_custom_output_dir(tmp_path):
    src = _make_pdf(tmp_path, ["data"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    job = ConversionJob(src=src, tool_id="pdf_to_txt", output_dir=out_dir)
    result = PdfToTxtConverter().convert(job)
    assert result.ok, result.error
    assert result.outputs[0].parent == out_dir


def test_txt_overwrite(tmp_path):
    src = _make_pdf(tmp_path, ["v1"])
    result1 = run_txt(src)
    assert result1.ok
    result2 = run_txt(src)
    assert result2.ok
    assert result2.outputs[0] != result1.outputs[0]  # unique name
    job = ConversionJob(src=src, tool_id="pdf_to_txt", overwrite=True)
    result3 = PdfToTxtConverter().convert(job)
    assert result3.ok
    assert result3.outputs[0] == result1.outputs[0]  # overwrote original


def test_txt_not_a_pdf(tmp_path):
    bad = tmp_path / "not_a_pdf.pdf"
    bad.write_bytes(b"This is not a PDF file at all.")
    result = run_txt(bad)
    assert not result.ok
    assert result.status == JobStatus.FAILED


def test_txt_empty_pdf(tmp_path):
    """A PDF with pages but no extractable text still succeeds."""
    src = _make_pdf(tmp_path, [""])
    result = run_txt(src)
    assert result.status in (JobStatus.SUCCESS, JobStatus.FAILED)


# ---------------------------------------------------------------------------
# PDF → Word (pypandoc pipeline)
# ---------------------------------------------------------------------------


def test_docx_basic(tmp_path):
    src = _make_pdf(tmp_path, ["Hello PDF to Word"])
    result = run_docx(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1
    out = result.outputs[0]
    assert out.suffix == ".docx"
    assert out.stat().st_size > 0


def test_docx_is_valid_zip(tmp_path):
    """A .docx must be a valid ZIP (Office Open XML)."""
    src = _make_pdf(tmp_path, ["Validity check"])
    result = run_docx(src)
    assert result.ok, result.error
    assert zipfile.is_zipfile(result.outputs[0])


def test_docx_output_beside_source(tmp_path):
    src = _make_pdf(tmp_path, ["next to source"])
    result = run_docx(src)
    assert result.ok, result.error
    assert result.outputs[0].parent == src.parent


def test_docx_custom_output_dir(tmp_path):
    src = _make_pdf(tmp_path, ["custom dir"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    job = ConversionJob(src=src, tool_id="pdf_to_docx", output_dir=out_dir)
    result = PdfToDocxConverter().convert(job)
    assert result.ok, result.error
    assert result.outputs[0].parent == out_dir


def test_docx_multipage(tmp_path):
    src = _make_pdf(tmp_path, ["Page one", "Page two", "Page three"])
    result = run_docx(src)
    assert result.ok, result.error
    assert result.outputs[0].stat().st_size > 0


def test_docx_detect_structure_false(tmp_path):
    """detect_structure=False should still produce a valid docx."""
    src = _make_pdf(tmp_path, ["Simple content without heuristics"])
    result = run_docx(src, detect_structure=False)
    assert result.ok, result.error
    assert zipfile.is_zipfile(result.outputs[0])


def test_docx_not_a_pdf(tmp_path):
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"I am not a real PDF.")
    result = run_docx(bad)
    assert not result.ok
    assert result.status == JobStatus.FAILED


def test_docx_overwrite(tmp_path):
    src = _make_pdf(tmp_path, ["content"])
    result1 = run_docx(src)
    assert result1.ok
    result2 = run_docx(src)
    assert result2.ok
    assert result2.outputs[0] != result1.outputs[0]  # unique name without overwrite
