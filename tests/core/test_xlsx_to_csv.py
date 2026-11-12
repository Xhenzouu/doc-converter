import csv
import io
import threading

import openpyxl
import pytest

from docconverter.core import (
    ConversionJob,
    JobStatus,
    load_builtin_converters,
    registry,
)
from docconverter.core.converters.xlsx_to_csv import (
    SPEC,
    XlsxToCsvConverter,
)

TOOL = "xlsx_to_csv"


@pytest.fixture
def make_xlsx(tmp_path):
    def factory(sheets: dict[str, list[list]], name="workbook.xlsx"):
        wb = openpyxl.Workbook()
        # Remove default sheet
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
    return XlsxToCsvConverter().convert(job, progress_cb, cancel_event)


def test_registered():
    load_builtin_converters()
    assert TOOL in registry
    assert registry.get_spec(TOOL).id == TOOL


def test_multiple_sheets_output(make_xlsx):
    src = make_xlsx({
        "Sheet1": [["Name", "Score"], ["Alice", 95]],
        "Sheet2": [["Product", "Price"], ["Widget", 19.99]],
    })
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 2

    names = [p.name for p in result.outputs]
    assert "workbook_Sheet1.csv" in names
    assert "workbook_Sheet2.csv" in names

    sheet1_out = next(p for p in result.outputs if "Sheet1" in p.name)
    rows1 = list(csv.reader(io.StringIO(sheet1_out.read_text(encoding="utf-8"))))
    assert rows1 == [["Name", "Score"], ["Alice", "95"]]

    sheet2_out = next(p for p in result.outputs if "Sheet2" in p.name)
    rows2 = list(csv.reader(io.StringIO(sheet2_out.read_text(encoding="utf-8"))))
    assert rows2 == [["Product", "Price"], ["Widget", "19.99"]]


def test_special_characters_in_sheet_name(make_xlsx):
    src = make_xlsx({
        "Q1 Sales & Profit": [["Total", 5000]],
    })
    result = run(src)
    assert result.ok, result.error
    assert len(result.outputs) == 1
    assert "Q1 Sales & Profit" in result.outputs[0].name


def test_delimiter_option(make_xlsx):
    src = make_xlsx({
        "Data": [["Col1", "Col2"], [1, 2]],
    })
    result = run(src, delimiter=";")
    assert result.ok, result.error
    content = result.outputs[0].read_text(encoding="utf-8")
    assert "Col1;Col2\n1;2" in content


def test_skip_empty_rows_option(make_xlsx):
    src = make_xlsx({
        "Data": [["A", "B"], [None, None], ["C", "D"]],
    })
    result_skip = run(src, skip_empty_rows=True)
    assert result_skip.ok
    rows_skip = list(csv.reader(io.StringIO(result_skip.outputs[0].read_text(encoding="utf-8"))))
    assert len(rows_skip) == 2

    result_keep = run(src, skip_empty_rows=False)
    assert result_keep.ok
    rows_keep = list(csv.reader(io.StringIO(result_keep.outputs[0].read_text(encoding="utf-8"))))
    assert len(rows_keep) == 3


def test_empty_sheet_warns(make_xlsx):
    src = make_xlsx({
        "EmptySheet": [],
    })
    result = run(src)
    assert result.ok
    assert any("empty" in w.lower() for w in result.warnings)


def test_corrupt_file_fails(tmp_path):
    corrupt = tmp_path / "broken.xlsx"
    corrupt.write_text("this is not a zip or excel file")
    result = run(corrupt)
    assert not result.ok
    assert result.status is JobStatus.FAILED
    assert "Could not read Excel file" in (result.error or "")


def test_cancellation(make_xlsx):
    src = make_xlsx({"S1": [[1]]})
    cancel = threading.Event()
    cancel.set()
    result = run(src, cancel_event=cancel)
    assert result.cancelled


def test_progress_callback(make_xlsx):
    src = make_xlsx({
        "S1": [[1]],
        "S2": [[2]],
    })
    events = []
    result = run(src, progress_cb=lambda f, m: events.append((f, m)))
    assert result.ok
    assert any("Exporting sheet" in m for f, m in events)
