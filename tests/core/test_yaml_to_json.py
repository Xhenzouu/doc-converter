import json
import threading

import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.yaml_to_json import (
    SPEC,
    YamlToJsonConverter,
)

TOOL = "yaml_to_json"


@pytest.fixture
def yaml_file(tmp_path):
    def make(content="title: Test\ncount: 5\n", name="data.yaml"):
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
    return YamlToJsonConverter().convert(job, progress_cb, cancel_event)


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_basic_yaml_to_json(yaml_file):
    src = yaml_file("name: Alice\nage: 28\nskills:\n  - python\n  - rust\n")
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1

    parsed = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert parsed == {
        "name": "Alice",
        "age": 28,
        "skills": ["python", "rust"],
    }


def test_indent_option(yaml_file):
    src = yaml_file("a: 1\nb: 2\n")
    result_compact = run(src, indent=0)
    assert result_compact.ok
    text_compact = result_compact.outputs[0].read_text(encoding="utf-8")
    assert "\n " not in text_compact  # No multi-space indentation

    result_indented = run(src, indent=4)
    assert result_indented.ok
    text_indented = result_indented.outputs[0].read_text(encoding="utf-8")
    assert "    " in text_indented


def test_sort_keys_option(yaml_file):
    src = yaml_file("z: 1\na: 2\nm: 3\n")
    result = run(src, sort_keys=True)
    assert result.ok
    text = result.outputs[0].read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"m"') < text.index('"z"')


def test_dates_and_special_types(yaml_file):
    src = yaml_file("created: 2024-03-15\nprice: 19.99\n")
    result = run(src)
    assert result.ok, result.error
    parsed = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert parsed["created"] == "2024-03-15"
    assert parsed["price"] == 19.99


def test_empty_yaml_warns(yaml_file):
    src = yaml_file("")
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)
    parsed = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert parsed == {}


def test_comment_only_yaml_warns(yaml_file):
    src = yaml_file("# just a comment\n")
    result = run(src)
    assert result.ok
    assert any("no data" in w.lower() or "empty" in w.lower() for w in result.warnings)
    parsed = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert parsed == {}


def test_invalid_yaml_fails(yaml_file):
    src = yaml_file("key: [unclosed list\n")
    result = run(src)
    assert not result.ok
    assert result.status is JobStatus.FAILED
    assert "Invalid YAML" in (result.error or "")


def test_cancellation(yaml_file):
    src = yaml_file("a: 1\n")
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(yaml_file):
    src = yaml_file("a: 1\n")
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 3


def test_output_dir(yaml_file, tmp_path):
    src = yaml_file("a: 1\n")
    out = tmp_path / "custom"
    result = run(src, output_dir=out)
    assert result.ok
    assert result.outputs[0].parent == out
