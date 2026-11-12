import csv
import io
import json
import threading

import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.json_to_csv import (
    SPEC,
    JsonToCsvConverter,
    flatten_json_object,
)

TOOL = "json_to_csv"


@pytest.fixture
def json_file(tmp_path):
    def make(content, name="data.json"):
        path = tmp_path / name
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content), encoding="utf-8")
        elif isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(str(content), encoding="utf-8")
        return path

    return make


def run(src, *, output_dir=None, overwrite=False, progress_cb=None, cancel_event=None, **options):
    job = ConversionJob(
        src=src, tool_id=TOOL, output_dir=output_dir, options=options, overwrite=overwrite
    )
    return JsonToCsvConverter().convert(job, progress_cb, cancel_event)


# --- Unit tests for helper functions ---


def test_flatten_json_object_nested():
    data = {
        "user": {
            "name": "Alice",
            "address": {
                "city": "Wonderland",
                "zip": "12345",
            },
        },
        "active": True,
    }
    flat = flatten_json_object(data)
    assert flat == {
        "user.name": "Alice",
        "user.address.city": "Wonderland",
        "user.address.zip": "12345",
        "active": True,
    }


def test_flatten_json_object_flat():
    data = {"a": 1, "b": "two"}
    assert flatten_json_object(data) == {"a": 1, "b": "two"}


# --- Integration tests ---


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_single_object_conversion(json_file):
    src = json_file({
        "user": {
            "address": {"city": "Paris", "country": "France"},
            "age": 30,
        },
        "id": 101,
    })
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1

    content = result.outputs[0].read_text(encoding="utf-8")
    reader = list(csv.reader(io.StringIO(content)))
    assert reader[0] == ["user.address.city", "user.address.country", "user.age", "id"]
    assert reader[1] == ["Paris", "France", "30", "101"]


def test_list_of_objects_conversion(json_file):
    src = json_file([
        {"id": 1, "user": {"name": "Alice"}},
        {"id": 2, "user": {"name": "Bob"}},
    ])
    result = run(src)
    assert result.ok, result.error

    content = result.outputs[0].read_text(encoding="utf-8")
    reader = list(csv.DictReader(io.StringIO(content)))
    assert len(reader) == 2
    assert reader[0]["user.name"] == "Alice"
    assert reader[1]["user.name"] == "Bob"
    assert reader[0]["id"] == "1"


def test_heterogeneous_keys_across_rows(json_file):
    src = json_file([
        {"a": 1, "b": 2},
        {"b": 20, "c": 30},
    ])
    result = run(src)
    assert result.ok, result.error

    content = result.outputs[0].read_text(encoding="utf-8")
    reader = list(csv.DictReader(io.StringIO(content)))
    assert reader[0]["a"] == "1" and reader[0]["b"] == "2" and reader[0]["c"] == ""
    assert reader[1]["a"] == "" and reader[1]["b"] == "20" and reader[1]["c"] == "30"


def test_nested_list_value_serialized_as_json(json_file):
    src = json_file({
        "user": {"name": "Alice", "roles": ["admin", "editor"]},
    })
    result = run(src)
    assert result.ok, result.error

    content = result.outputs[0].read_text(encoding="utf-8")
    reader = list(csv.DictReader(io.StringIO(content)))
    assert json.loads(reader[0]["user.roles"]) == ["admin", "editor"]


def test_delimiter_option(json_file):
    src = json_file([{"a": 1, "b": 2}])
    result = run(src, delimiter=";")
    assert result.ok, result.error

    content = result.outputs[0].read_text(encoding="utf-8")
    assert "a;b\n1;2" in content


def test_empty_json_file_warns(json_file):
    src = json_file("")
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_empty_json_array_warns(json_file):
    src = json_file([])
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_invalid_json_fails_with_error(json_file):
    src = json_file("{not: valid, json")
    result = run(src)
    assert not result.ok
    assert result.status is JobStatus.FAILED
    assert "Invalid JSON" in (result.error or "")


def test_primitive_root_fails(json_file):
    src = json_file('"just a plain string"')
    result = run(src)
    assert not result.ok
    assert "JSON root must be an object or a list" in (result.error or "")


def test_cancellation(json_file):
    src = json_file([{"a": 1}])
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(json_file):
    src = json_file([{"a": 1}])
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 3


def test_output_dir_and_overwrite(json_file, tmp_path):
    src = json_file({"name": "test"})
    out_dir = tmp_path / "custom_out"
    result = run(src, output_dir=out_dir)
    assert result.ok
    assert result.outputs[0].parent == out_dir
