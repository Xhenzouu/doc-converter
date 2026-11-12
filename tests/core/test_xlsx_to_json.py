import datetime
import json
import threading

import openpyxl
import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.xlsx_to_json import (
    SPEC,
    XlsxToJsonConverter,
)

TOOL = "xlsx_to_json"


@pytest.fixture
def make_xlsx(tmp_path):
    def factory(sheets: dict[str, list[list]], name="workbook.xlsx"):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        for sheet_name, rows in sheets.items():
            ws = wb.create_sheet(title=sheet_name)
            for row in rows:
                ws.append(row)

        path = tmp_path / name
        wb.save(path)
        wb.close()
        return path

    return factory


def run(src, *, output_dir=None, overwrite=False, progress_cb=None, cancel_event=None, **options):
    job = ConversionJob(
        src=src, tool_id=TOOL, output_dir=output_dir, options=options, overwrite=overwrite
    )
    return XlsxToJsonConverter().convert(job, progress_cb, cancel_event)


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_single_sheet_with_headers_as_array(make_xlsx):
    src = make_xlsx({
        "Users": [
            ["Name", "Age"],
            ["Alice", 30],
            ["Bob", 25],
        ]
    })
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data == [
        {"Name": "Alice", "Age": 30},
        {"Name": "Bob", "Age": 25},
    ]


def test_multi_sheet_emits_dictionary(make_xlsx):
    src = make_xlsx({
        "SheetA": [["Col1"], [100]],
        "SheetB": [["Col2"], [200]],
    })
    result = run(src)
    assert result.ok, result.error

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "SheetA" in data and "SheetB" in data
    assert data["SheetA"] == [{"Col1": 100}]
    assert data["SheetB"] == [{"Col2": 200}]


def test_first_row_headers_disabled(make_xlsx):
    src = make_xlsx({
        "Data": [["ColA", "ColB"], [1, 2]],
    })
    result = run(src, first_row_headers=False)
    assert result.ok, result.error

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert data == [["ColA", "ColB"], [1, 2]]


def test_single_sheet_as_list_disabled(make_xlsx):
    src = make_xlsx({
        "OnlySheet": [["A"], [1]],
    })
    result = run(src, single_sheet_as_list=False)
    assert result.ok, result.error

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "OnlySheet" in data
    assert data["OnlySheet"] == [{"A": 1}]


def test_duplicate_headers_handled(make_xlsx):
    src = make_xlsx({
        "Scores": [
            ["Score", "Score"],
            [80, 90],
        ]
    })
    result = run(src)
    assert result.ok, result.error

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert data == [{"Score": 80, "Score_1": 90}]


def test_dates_serialization(make_xlsx):
    d = datetime.date(2025, 5, 20)
    src = make_xlsx({
        "Events": [["Date", "Title"], [d, "Launch"]],
    })
    result = run(src)
    assert result.ok, result.error

    data = json.loads(result.outputs[0].read_text(encoding="utf-8"))
    assert data[0]["Date"].startswith("2025-05-20")


def test_empty_sheet_warns(make_xlsx):
    src = make_xlsx({
        "Empty": [],
    })
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_corrupt_file_fails(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("bad data")
    result = run(bad)
    assert not result.ok
    assert "Could not read Excel file" in (result.error or "")


def test_cancellation(make_xlsx):
    src = make_xlsx({"S": [[1]]})
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(make_xlsx):
    src = make_xlsx({"S": [[1]]})
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert len(events) >= 2
