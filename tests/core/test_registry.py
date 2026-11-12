import threading

import pytest

from docconverter.core import (
    Availability,
    BaseConverter,
    Category,
    ConversionJob,
    ConversionSpec,
    DuplicateToolError,
    JobStatus,
    Registry,
    UnknownToolError,
    load_builtin_converters,
    registry,
)


def make_spec(tool_id, title=None, category=Category.TEXT, src_exts=(".x",), dst_ext=".y"):
    return ConversionSpec(
        id=tool_id,
        title=title or tool_id.replace("_", " ").title(),
        category=category,
        src_exts=src_exts,
        dst_ext=dst_ext,
    )


def add(reg, spec, availability=None, convert=None):
    attrs = {"_convert": convert or (lambda self, ctx: [])}
    if availability is not None:
        attrs["availability"] = classmethod(lambda cls: availability)
    cls = type(f"Conv_{spec.id}", (BaseConverter,), attrs)
    return reg.register(spec)(cls)


@pytest.fixture
def reg():
    return Registry()


def test_register_sets_spec_and_returns_class(reg):
    spec = make_spec("one")
    cls = add(reg, spec)
    assert cls.spec is spec and "one" in reg and len(reg) == 1


def test_duplicate_id_is_rejected(reg):
    add(reg, make_spec("dup"))
    with pytest.raises(DuplicateToolError):
        add(reg, make_spec("dup"))


def test_only_converters_can_be_registered(reg):
    with pytest.raises(TypeError):
        reg.register(make_spec("bad"))(object)
    with pytest.raises(TypeError):
        reg.register(make_spec("bad"))(lambda: None)


def test_unknown_tool_raises_clear_error(reg):
    for call in (reg.get_spec, reg.get_converter, reg.availability):
        with pytest.raises(UnknownToolError, match="nope"):
            call("nope")


def test_get_converter_returns_fresh_instances(reg):
    add(reg, make_spec("one"))
    assert reg.get_converter("one") is not reg.get_converter("one")


def test_all_specs_sorted_by_category_then_title(reg):
    add(reg, make_spec("t_b", "Beta", Category.TEXT))
    add(reg, make_spec("t_a", "alpha", Category.TEXT))  # case-insensitive title sort
    add(reg, make_spec("s_1", "Sheet", Category.SPREADSHEET))
    add(reg, make_spec("d_1", "Doc", Category.DOCUMENT))
    assert [s.id for s in reg.all_specs()] == ["d_1", "s_1", "t_a", "t_b"]


def test_specs_by_category_skips_empty_categories_and_keeps_order(reg):
    add(reg, make_spec("t_1", category=Category.TEXT))
    add(reg, make_spec("d_1", category=Category.DOCUMENT))
    grouped = reg.specs_by_category()
    assert list(grouped) == [Category.DOCUMENT, Category.TEXT]
    assert [s.id for s in grouped[Category.TEXT]] == ["t_1"]


def test_specs_for_path_matches_extension_case_insensitively(reg):
    add(reg, make_spec("docx_to_pdf", "Word to PDF", Category.DOCUMENT, (".docx",), ".pdf"))
    add(reg, make_spec("docx_to_md", "Word to Markdown", Category.DOCUMENT, (".docx",), ".md"))
    add(reg, make_spec("json_to_csv", "JSON to CSV", Category.TEXT, (".json",), ".csv"))
    ids = [s.id for s in reg.specs_for_path("C:/Users/me/Report.DOCX")]
    assert ids == ["docx_to_md", "docx_to_pdf"]  # sorted by title
    assert [s.id for s in reg.specs_for_extension("json")] == ["json_to_csv"]


def test_specs_for_path_without_match_or_extension(reg):
    add(reg, make_spec("one", src_exts=(".x",)))
    assert reg.specs_for_path("file.unknown") == []
    assert reg.specs_for_path("no_extension") == []


def test_availability_is_reported_per_tool(reg):
    add(reg, make_spec("ok_tool"))
    reason = "Requires MS Office or LibreOffice."
    add(reg, make_spec("office_tool"), availability=Availability.unavailable(reason))
    assert reg.availability("ok_tool").available
    missing = reg.availability("office_tool")
    assert not missing.available and missing.reason == reason


def test_run_dispatches_by_tool_id_and_forwards_arguments(reg, tmp_path):
    src = tmp_path / "f.x"
    src.write_text("hi")
    seen = {}

    def convert(self, ctx):
        seen["tool"] = ctx.spec.id
        ctx.progress(0.5, "halfway")
        return []

    add(reg, make_spec("one"), convert=convert)
    add(reg, make_spec("two"))
    events = []
    result = reg.run(
        ConversionJob(src=src, tool_id="one"),
        progress_cb=lambda f, m: events.append(m),
        cancel_event=threading.Event(),
    )
    assert result.status is JobStatus.SUCCESS and seen["tool"] == "one"
    assert "halfway" in events


def test_run_with_unknown_tool_raises(reg, tmp_path):
    with pytest.raises(UnknownToolError):
        reg.run(ConversionJob(src=tmp_path / "f.x", tool_id="ghost"))


def test_private_registries_do_not_leak_into_the_global_one(reg):
    add(reg, make_spec("only_here"))
    assert "only_here" not in registry


def test_load_builtin_converters_is_idempotent():
    first = load_builtin_converters()
    count = len(first)
    assert load_builtin_converters() is registry and len(registry) == count
    assert "markdown_to_html" in registry
