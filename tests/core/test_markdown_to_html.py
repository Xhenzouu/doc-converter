import threading

import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.markdown_to_html import (
    SPEC,
    MarkdownToHtmlConverter,
    build_page,
    render_markdown,
)

TOOL = "markdown_to_html"


@pytest.fixture
def md_file(tmp_path):
    def make(content="# Title\n\nHello", name="note.md"):
        path = tmp_path / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
        return path

    return make


def run(src, *, output_dir=None, overwrite=False, progress_cb=None, cancel_event=None, **options):
    job = ConversionJob(
        src=src, tool_id=TOOL, output_dir=output_dir, options=options, overwrite=overwrite
    )
    return MarkdownToHtmlConverter().convert(job, progress_cb, cancel_event)


@pytest.fixture
def render(md_file):
    """Convert Markdown text and return the output HTML (fragment unless told otherwise)."""

    def go(text, **options):
        options.setdefault("full_document", False)
        result = run(md_file(text), **options)
        assert result.ok, result.error
        return result.outputs[0].read_text(encoding="utf-8")

    return go


# --- rendering -------------------------------------------------------------------


def test_basic_blocks_and_inline(render):
    out = render("# Hi\n\nSome **bold** and *em* text.\n\n- one\n- two\n")
    assert "<h1>Hi</h1>" in out
    assert "<strong>bold</strong>" in out
    assert "<em>em</em>" in out
    assert "<ul>" in out and "<li>one</li>" in out


def test_tables(render):
    out = render("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in out and "<th>a</th>" in out and "<td>2</td>" in out


def test_strikethrough(render):
    assert "<s>gone</s>" in render("~~gone~~")


def test_fenced_code_is_escaped_and_labelled(render):
    out = render("```python\nprint('<hi>')\n```\n")
    assert 'class="language-python"' in out
    assert "&lt;hi&gt;" in out


def test_task_list_renders_checkboxes(render):
    out = render("- [x] done\n- [ ] todo\n")
    assert out.count('type="checkbox"') == 2
    assert "checked" in out


def test_footnotes(render):
    out = render("Text[^1]\n\n[^1]: The note.\n")
    assert "footnote" in out and "The note." in out


def test_front_matter_is_not_rendered(render):
    out = render("---\nauthor: someone\n---\n\n# Real\n")
    assert "author: someone" not in out
    assert "<h1>Real</h1>" in out


def test_crlf_line_endings(render):
    assert "<h1>Hi</h1>" in render("# Hi\r\n\r\ntext\r\n")


def test_unicode_round_trip(render):
    assert "Café ☕ 日本語" in render("# Café ☕ 日本語\n")


# --- security --------------------------------------------------------------------


def test_raw_html_is_escaped_by_default(render):
    out = render("<script>alert(1)</script>\n")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_raw_html_allowed_when_opted_in(render):
    assert "<script>alert(1)</script>" in render("<script>alert(1)</script>\n", allow_html=True)


def test_javascript_links_are_not_linked(render):
    assert 'href="javascript' not in render("[x](javascript:alert(1))\n")


# --- full page -------------------------------------------------------------------


def test_full_document_structure(md_file):
    result = run(md_file("# Hello World\n\ntext"))
    out = result.outputs[0].read_text(encoding="utf-8")
    assert out.startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in out
    assert "<title>Hello World</title>" in out
    assert "<style>" in out
    assert "<h1>Hello World</h1>" in out


def test_title_falls_back_to_file_name(md_file):
    out = run(md_file("no heading here", name="my notes.md")).outputs[0].read_text("utf-8")
    assert "<title>my notes</title>" in out


def test_title_uses_first_h1_not_h2(md_file):
    out = run(md_file("## Sub\n\n# Main\n")).outputs[0].read_text("utf-8")
    assert "<title>Main</title>" in out


def test_title_is_html_escaped(md_file):
    out = run(md_file("# A & B <b>\n")).outputs[0].read_text("utf-8")
    assert "<title>A &amp; B &lt;b&gt;</title>" in out


def test_include_styles_off(md_file):
    out = run(md_file(), include_styles=False).outputs[0].read_text("utf-8")
    assert "<style>" not in out and out.startswith("<!DOCTYPE html>")


def test_fragment_has_no_page_wrapper(render):
    out = render("# Hi\n")
    assert "<!DOCTYPE" not in out and "<html" not in out
    assert "<h1>Hi</h1>" in out


def test_render_markdown_and_build_page_are_usable_directly():
    rendered = render_markdown("# T\n\nbody")
    assert rendered.title == "T"
    page = build_page(rendered.body, "T", include_styles=False)
    assert "<style>" not in page and "<p>body</p>" in page


# --- encodings and bad input -----------------------------------------------------


def test_utf8_bom_is_stripped(md_file, render):
    path = md_file(b"\xef\xbb\xbf# Hi\n")
    out = run(path, full_document=False).outputs[0].read_text("utf-8")
    assert out.startswith("<h1>Hi</h1>")


def test_utf16_with_bom(md_file):
    path = md_file("# Hi ☕\n".encode("utf-16"))
    result = run(path, full_document=False)
    assert result.ok and "Hi ☕" in result.outputs[0].read_text("utf-8")
    assert result.warnings == ()


def test_cp1252_fallback_warns(md_file):
    result = run(md_file(b"# caf\xe9\n"), full_document=False)
    assert result.ok
    assert "café" in result.outputs[0].read_text("utf-8")
    assert any("cp1252" in w for w in result.warnings)


def test_empty_file_succeeds_with_warning(md_file):
    result = run(md_file(""))
    assert result.ok and result.outputs[0].exists()
    assert any("empty" in w.lower() for w in result.warnings)


def test_binary_file_is_rejected(md_file, tmp_path):
    result = run(md_file(b"\x00\x01\x02binary\x00"))
    assert result.status is JobStatus.FAILED
    assert "text file" in result.error
    assert not list(tmp_path.glob("*.html"))


# --- files, naming, validation ---------------------------------------------------


def test_output_goes_next_to_source(md_file, tmp_path):
    result = run(md_file())
    assert result.outputs == (tmp_path / "note.html",)


def test_output_dir_is_created(md_file, tmp_path):
    target = tmp_path / "out" / "nested"
    result = run(md_file(), output_dir=target)
    assert result.outputs == (target / "note.html",)
    assert result.outputs[0].exists()


def test_existing_output_is_not_replaced(md_file, tmp_path):
    src = md_file()
    first, second = run(src).outputs[0], run(src).outputs[0]
    assert first.name == "note.html" and second.name == "note (1).html"


def test_overwrite_replaces_existing_output(md_file):
    src = md_file("# One\n")
    first = run(src, full_document=False).outputs[0]
    src.write_text("# Two\n", encoding="utf-8")
    second = run(src, overwrite=True, full_document=False).outputs[0]
    assert first == second
    assert "Two" in second.read_text("utf-8")


def test_no_temp_files_left_behind(md_file, tmp_path):
    run(md_file())
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".part"]


@pytest.mark.parametrize("name", ["note.markdown", "NOTE.MD", "x.mdown"])
def test_accepted_extensions_case_insensitive(md_file, name):
    assert run(md_file(name=name)).ok


def test_uppercase_extension_output_name(md_file, tmp_path):
    assert run(md_file(name="NOTE.MD")).outputs == (tmp_path / "NOTE.html",)


def test_unsupported_extension(md_file):
    result = run(md_file(name="note.txt"))
    assert result.status is JobStatus.FAILED and "supported" in result.error


def test_missing_source(tmp_path):
    result = run(tmp_path / "ghost.md")
    assert result.status is JobStatus.FAILED and "not found" in result.error


def test_unknown_option(md_file):
    result = run(md_file(), bogus=True)
    assert result.status is JobStatus.FAILED and "bogus" in result.error


def test_option_type_is_checked(md_file):
    result = run(md_file(), full_document="yes")
    assert result.status is JobStatus.FAILED and "full_document" in result.error


# --- progress and cancellation ---------------------------------------------------


def test_progress_is_monotonic_and_finishes_at_one(md_file):
    events = []
    run(md_file(), progress_cb=lambda f, m: events.append((f, m)))
    fractions = [f for f, _ in events if f is not None]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert all(m for _, m in events)


def test_failing_progress_callback_does_not_break_conversion(md_file):
    def boom(fraction, message):
        raise RuntimeError("UI exploded")

    assert run(md_file(), progress_cb=boom).ok


def test_cancel_before_start_writes_nothing(md_file, tmp_path):
    event = threading.Event()
    event.set()
    result = run(md_file(), cancel_event=event)
    assert result.cancelled and result.outputs == ()
    assert not list(tmp_path.glob("*.html"))


def test_cancel_after_reading_writes_nothing(md_file, tmp_path):
    event = threading.Event()

    def cancel_while_converting(fraction, message):
        if message == "Converting Markdown":
            event.set()  # the converter checks for cancellation right after this step

    result = run(md_file(), progress_cb=cancel_while_converting, cancel_event=event)
    assert result.cancelled and result.outputs == ()
    assert not list(tmp_path.glob("*.html"))


# --- registry integration --------------------------------------------------------


def test_registered_with_expected_spec():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL) is SPEC
    assert SPEC in registry.specs_for_path("README.md")


def test_run_through_registry(md_file):
    load_builtin_converters()
    job = ConversionJob(src=md_file(), tool_id=TOOL)
    result = registry.run(job)
    assert result.ok and result.outputs[0].suffix == ".html"
