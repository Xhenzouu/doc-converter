import threading

import docx
import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.docx_to_markdown import (
    SPEC,
    DocxToMarkdownConverter,
)

TOOL = "docx_to_markdown"


@pytest.fixture
def make_docx(tmp_path):
    def factory(content_fn=None, name="document.docx"):
        doc = docx.Document()
        if content_fn:
            content_fn(doc)
        path = tmp_path / name
        doc.save(path)
        return path

    return factory


def run(src, *, output_dir=None, overwrite=False, progress_cb=None, cancel_event=None, **options):
    job = ConversionJob(
        src=src, tool_id=TOOL, output_dir=output_dir, options=options, overwrite=overwrite
    )
    return DocxToMarkdownConverter().convert(job, progress_cb, cancel_event)


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_basic_docx_conversion(make_docx):
    def populate(doc):
        doc.add_heading("Document Title", level=1)
        p = doc.add_paragraph("This is ")
        p.add_run("bold").bold = True
        p.add_run(" and ")
        p.add_run("italic").italic = True

    src = make_docx(populate)
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1

    md_text = result.outputs[0].read_text(encoding="utf-8")
    assert "# Document Title" in md_text
    assert "**bold**" in md_text
    assert "*italic*" in md_text or "_italic_" in md_text


def test_lists_and_tables(make_docx):
    def populate(doc):
        doc.add_paragraph("First item", style="List Bullet")
        doc.add_paragraph("Second item", style="List Bullet")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Header A"
        table.cell(0, 1).text = "Header B"
        table.cell(1, 0).text = "Cell 1"
        table.cell(1, 1).text = "Cell 2"

    src = make_docx(populate)
    result = run(src)
    assert result.ok, result.error

    md_text = result.outputs[0].read_text(encoding="utf-8")
    assert "First item" in md_text
    assert "Second item" in md_text
    assert "Header A" in md_text


def test_heading_style_option(make_docx):
    def populate(doc):
        doc.add_heading("Main Header", level=1)

    src = make_docx(populate)
    result_atx = run(src, heading_style="atx")
    assert result_atx.ok
    assert "# Main Header" in result_atx.outputs[0].read_text(encoding="utf-8")

    result_setext = run(src, heading_style="underlined")
    assert result_setext.ok
    md_setext = result_setext.outputs[0].read_text(encoding="utf-8")
    assert "===" in md_setext or "---" in md_setext


def test_empty_docx_warns(make_docx):
    src = make_docx()  # No paragraphs or headings
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_corrupt_file_fails(tmp_path):
    bad = tmp_path / "broken.docx"
    bad.write_text("not a real docx zip archive")
    result = run(bad)
    assert not result.ok
    assert result.status is JobStatus.FAILED
    assert "Could not read Word document" in (result.error or "")


def test_cancellation(make_docx):
    src = make_docx(lambda doc: doc.add_paragraph("Text"))
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(make_docx):
    src = make_docx(lambda doc: doc.add_paragraph("Text"))
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 2


def test_output_dir(make_docx, tmp_path):
    src = make_docx(lambda doc: doc.add_paragraph("Text"))
    out = tmp_path / "custom_markdown"
    result = run(src, output_dir=out)
    assert result.ok
    assert result.outputs[0].parent == out
