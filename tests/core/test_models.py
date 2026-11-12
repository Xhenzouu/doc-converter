from pathlib import Path

import pytest

from docconverter.core import (
    Availability,
    Category,
    ConversionJob,
    ConversionResult,
    ConversionSpec,
    InvalidOptionError,
    JobStatus,
    OptionKind,
    OptionSpec,
)
from docconverter.core.models import normalize_ext


def make_spec(**overrides):
    fields = dict(
        id="a_to_b",
        title="A to B",
        category=Category.TEXT,
        src_exts=(".a",),
        dst_ext=".b",
    )
    fields.update(overrides)
    return ConversionSpec(**fields)


@pytest.mark.parametrize(
    "raw, expected", [("md", ".md"), (".MD", ".md"), (" .Json ", ".json"), ("PDF", ".pdf")]
)
def test_normalize_ext(raw, expected):
    assert normalize_ext(raw) == expected


@pytest.mark.parametrize("raw", ["", ".", "  "])
def test_normalize_ext_rejects_empty(raw):
    with pytest.raises(ValueError):
        normalize_ext(raw)


def test_category_order_follows_definition():
    assert [c.order for c in Category] == list(range(len(Category)))
    assert Category.DOCUMENT.order < Category.TEXT.order


# --- ConversionSpec --------------------------------------------------------------


def test_spec_normalizes_extensions_and_dedupes():
    spec = make_spec(src_exts=("MD", ".md", ".Markdown"), dst_ext="HTML")
    assert spec.src_exts == (".md", ".markdown")
    assert spec.dst_ext == ".html"


def test_spec_coerces_category_from_string():
    assert make_spec(category="Text").category is Category.TEXT


@pytest.mark.parametrize("bad_id", ["", "Has Space", "1starts_with_digit", "UPPER", "a-b"])
def test_spec_rejects_bad_ids(bad_id):
    with pytest.raises(ValueError):
        make_spec(id=bad_id)


def test_spec_requires_a_source_extension():
    with pytest.raises(ValueError):
        make_spec(src_exts=())


def test_spec_rejects_duplicate_option_keys():
    opt = OptionSpec("x", "X", OptionKind.BOOL, True)
    with pytest.raises(ValueError):
        make_spec(options=(opt, opt))


def test_accepts_is_case_insensitive_and_path_or_str():
    spec = make_spec(src_exts=(".md",))
    assert spec.accepts("a/b/NOTES.MD")
    assert spec.accepts(Path("x.md"))
    assert not spec.accepts("x.txt")
    assert not spec.accepts("md")  # no extension


# --- options ---------------------------------------------------------------------


@pytest.fixture
def spec_with_options():
    return make_spec(
        options=(
            OptionSpec("flag", "Flag", OptionKind.BOOL, True),
            OptionSpec("count", "Count", OptionKind.INT, 3),
            OptionSpec("label", "Label", OptionKind.TEXT, "hi"),
            OptionSpec("mode", "Mode", OptionKind.CHOICE, "fast", choices=("fast", "slow")),
        )
    )


def test_resolve_options_defaults(spec_with_options):
    assert spec_with_options.resolve_options() == {
        "flag": True,
        "count": 3,
        "label": "hi",
        "mode": "fast",
    }
    assert spec_with_options.resolve_options(None) == spec_with_options.default_options()


def test_resolve_options_overrides_only_given(spec_with_options):
    resolved = spec_with_options.resolve_options({"count": 9, "mode": "slow"})
    assert resolved["count"] == 9 and resolved["mode"] == "slow" and resolved["flag"] is True


def test_resolve_options_rejects_unknown_keys(spec_with_options):
    with pytest.raises(InvalidOptionError, match="nope"):
        spec_with_options.resolve_options({"nope": 1})


@pytest.mark.parametrize(
    "key, value",
    [
        ("flag", "yes"),
        ("flag", 1),
        ("count", True),  # bool is not an int here
        ("count", "3"),
        ("label", 5),
        ("mode", "medium"),
    ],
)
def test_resolve_options_rejects_bad_values(spec_with_options, key, value):
    with pytest.raises(InvalidOptionError, match=key):
        spec_with_options.resolve_options({key: value})


def test_option_spec_validates_its_own_default():
    with pytest.raises(InvalidOptionError):
        OptionSpec("flag", "Flag", OptionKind.BOOL, "nope")


def test_choice_option_needs_choices():
    with pytest.raises(ValueError):
        OptionSpec("mode", "Mode", OptionKind.CHOICE, "x")


# --- jobs, results, availability -------------------------------------------------


def test_job_coerces_paths_and_copies_options():
    options = {"a": 1}
    job = ConversionJob(src="x/y.md", tool_id="t", output_dir="out", options=options)
    assert job.src == Path("x/y.md") and job.output_dir == Path("out")
    options["a"] = 2
    assert job.options == {"a": 1}


def test_job_ids_are_unique_and_job_is_hashable():
    a, b = ConversionJob(Path("a.md"), "t"), ConversionJob(Path("a.md"), "t")
    assert a.job_id != b.job_id
    assert len({a, b}) == 2


def test_job_is_frozen():
    job = ConversionJob(Path("a.md"), "t")
    with pytest.raises(Exception):
        job.tool_id = "other"


def test_result_flags():
    job = ConversionJob(Path("a.md"), "t")
    assert ConversionResult(job, JobStatus.SUCCESS).ok
    assert ConversionResult(job, JobStatus.CANCELLED).cancelled
    failed = ConversionResult(job, JobStatus.FAILED, error="boom")
    assert not failed.ok and not failed.cancelled


def test_availability_helpers():
    assert Availability.ok().available
    missing = Availability.unavailable("Requires MS Office or LibreOffice.")
    assert not missing.available and "LibreOffice" in missing.reason
