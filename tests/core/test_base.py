"""Tests for the BaseConverter template method, using throwaway converters."""

import logging
import threading

import pytest

from docconverter.core import (
    Availability,
    BaseConverter,
    Category,
    ConversionError,
    ConversionJob,
    ConversionSpec,
    JobStatus,
    Registry,
)


def make_spec(tool_id="dummy", **overrides):
    fields = dict(
        id=tool_id, title="Dummy", category=Category.TEXT, src_exts=(".dummy",), dst_ext=".out"
    )
    fields.update(overrides)
    return ConversionSpec(**fields)


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "data.dummy"
    path.write_text("input")
    return path


def job_for(src, tool_id="dummy", **kwargs):
    return ConversionJob(src=src, tool_id=tool_id, **kwargs)


def build(behaviour, spec=None, availability=None):
    """Register a converter whose _convert is ``behaviour(ctx)`` on a private registry."""
    reg = Registry()
    spec = spec or make_spec()

    attrs = {"_convert": lambda self, ctx: behaviour(ctx)}
    if availability is not None:
        attrs["availability"] = classmethod(lambda cls: availability)
    cls = type("DummyConverter", (BaseConverter,), attrs)
    reg.register(spec)(cls)
    return reg, cls()


def test_success_returns_outputs_warnings_and_duration(src):
    def behaviour(ctx):
        ctx.warn("heads up")
        out = ctx.output_path()
        ctx.write_text(out, "converted")
        return [out]

    _, converter = build(behaviour)
    result = converter.convert(job_for(src))
    assert result.status is JobStatus.SUCCESS
    assert [p.name for p in result.outputs] == ["data.out"]
    assert result.outputs[0].read_text() == "converted"
    assert result.warnings == ("heads up",)
    assert result.error is None and result.duration_s >= 0


def test_options_are_resolved_and_passed_to_converter(src):
    from docconverter.core import OptionKind, OptionSpec

    seen = {}
    spec = make_spec(options=(OptionSpec("n", "N", OptionKind.INT, 5),))

    def behaviour(ctx):
        seen.update(ctx.options)
        return []

    _, converter = build(behaviour, spec)
    converter.convert(job_for(src, options={"n": 7}))
    assert seen == {"n": 7}
    converter.convert(job_for(src))
    assert seen == {"n": 5}


def test_conversion_error_becomes_failed_result_and_cleans_up(src, tmp_path):
    def behaviour(ctx):
        ctx.write_text(ctx.output_path(suffix="_1"), "partial")
        raise ConversionError("Sheet 2 is corrupt.")

    _, converter = build(behaviour)
    result = converter.convert(job_for(src))
    assert result.status is JobStatus.FAILED
    assert result.error == "Sheet 2 is corrupt."
    assert not list(tmp_path.glob("*.out"))


def test_unexpected_exception_is_contained_and_logged(src, tmp_path, caplog):
    def behaviour(ctx):
        ctx.write_text(ctx.output_path(), "partial")
        raise RuntimeError("bug")

    _, converter = build(behaviour)
    with caplog.at_level(logging.ERROR):
        result = converter.convert(job_for(src))
    assert result.status is JobStatus.FAILED
    assert "Unexpected error (RuntimeError): bug" in result.error
    assert "Traceback" in caplog.text
    assert not list(tmp_path.glob("*.out"))


def test_os_error_gets_friendly_prefix(src):
    def behaviour(ctx):
        raise PermissionError(13, "Permission denied", "/locked/file")

    _, converter = build(behaviour)
    result = converter.convert(job_for(src))
    assert result.status is JobStatus.FAILED
    assert result.error.startswith("File system error:") and "Permission denied" in result.error


def test_keyboard_interrupt_is_not_swallowed(src):
    def behaviour(ctx):
        raise KeyboardInterrupt

    _, converter = build(behaviour)
    with pytest.raises(KeyboardInterrupt):
        converter.convert(job_for(src))


def test_cancel_mid_run_cleans_up_partial_output(src, tmp_path):
    event = threading.Event()

    def behaviour(ctx):
        ctx.write_text(ctx.output_path(suffix="_1"), "first sheet")
        event.set()  # the user clicks Cancel
        ctx.check_cancelled()
        ctx.write_text(ctx.output_path(suffix="_2"), "never written")
        return []

    _, converter = build(behaviour)
    result = converter.convert(job_for(src), cancel_event=event)
    assert result.cancelled and result.outputs == () and result.error is None
    assert not list(tmp_path.glob("*.out"))


def test_cancel_before_start_never_calls_converter(src):
    called = []
    event = threading.Event()
    event.set()
    _, converter = build(lambda ctx: called.append(1) or [])
    assert converter.convert(job_for(src), cancel_event=event).cancelled
    assert called == []


def test_unavailable_backend_fails_without_running(src):
    called = []
    reason = "Requires MS Office or LibreOffice."
    _, converter = build(
        lambda ctx: called.append(1) or [], availability=Availability.unavailable(reason)
    )
    result = converter.convert(job_for(src))
    assert result.status is JobStatus.FAILED and result.error == reason
    assert called == []


def test_unavailable_backend_without_reason_still_explains(src):
    _, converter = build(lambda ctx: [], availability=Availability(False))
    assert "not available" in converter.convert(job_for(src)).error


def test_job_for_wrong_tool_is_rejected(src):
    _, converter = build(lambda ctx: [])
    result = converter.convert(job_for(src, tool_id="something_else"))
    assert result.status is JobStatus.FAILED and "something_else" in result.error


def test_missing_source_and_wrong_extension(tmp_path):
    _, converter = build(lambda ctx: [])
    missing = converter.convert(job_for(tmp_path / "nope.dummy"))
    assert missing.status is JobStatus.FAILED and "not found" in missing.error

    folder = tmp_path / "folder.dummy"
    folder.mkdir()
    assert "not found" in converter.convert(job_for(folder)).error  # a directory is not a file

    wrong = tmp_path / "data.txt"
    wrong.write_text("x")
    assert "not a supported input" in converter.convert(job_for(wrong)).error


def test_progress_is_clamped_and_reported(src):
    events = []

    def behaviour(ctx):
        ctx.progress(-1, "low")
        ctx.progress(5, "high")
        ctx.progress(None, "busy")
        return []

    _, converter = build(behaviour)
    converter.convert(job_for(src), progress_cb=lambda f, m: events.append((f, m)))
    assert events == [(0.0, "low"), (1.0, "high"), (None, "busy"), (1.0, "Done")]


def test_multiple_outputs_and_reserved_names(src, tmp_path):
    """Models the xlsx case: one file per sheet, even when sheet names collide."""

    def behaviour(ctx):
        outputs = []
        for sheet in ("Sheet1", "Sheet2", "Sheet2"):  # duplicate name after sanitizing
            path = ctx.output_path(suffix=f"_{sheet}", ext=".csv")
            outputs.append(ctx.write_text(path, sheet))
        return outputs

    _, converter = build(behaviour)
    result = converter.convert(job_for(src))
    assert [p.name for p in result.outputs] == [
        "data_Sheet1.csv",
        "data_Sheet2.csv",
        "data_Sheet2 (1).csv",
    ]


def test_reserved_names_apply_before_anything_is_written(src):
    def behaviour(ctx):
        return [ctx.output_path(), ctx.output_path()]  # asked twice, nothing written yet

    _, converter = build(behaviour)
    first, second = converter.convert(job_for(src)).outputs
    assert first != second


def test_output_dir_and_overwrite_are_honoured(src, tmp_path):
    def behaviour(ctx):
        return [ctx.write_text(ctx.output_path(), "x")]

    _, converter = build(behaviour)
    out_dir = tmp_path / "elsewhere"
    first = converter.convert(job_for(src, output_dir=out_dir)).outputs[0]
    second = converter.convert(job_for(src, output_dir=out_dir, overwrite=True)).outputs[0]
    third = converter.convert(job_for(src, output_dir=out_dir)).outputs[0]
    assert first.parent == out_dir and first == second and third.name == "data (1).out"


def test_track_removes_files_written_by_other_means(src, tmp_path):
    def behaviour(ctx):
        path = ctx.output_path()
        path.write_text("written by a subprocess")
        ctx.track(path)
        raise ConversionError("later step failed")

    _, converter = build(behaviour)
    assert converter.convert(job_for(src)).status is JobStatus.FAILED
    assert not list(tmp_path.glob("*.out"))
