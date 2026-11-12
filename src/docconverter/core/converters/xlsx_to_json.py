"""Excel (.xlsx) to JSON converter."""

from __future__ import annotations

import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Sequence

import openpyxl

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register

SPEC = ConversionSpec(
    id="xlsx_to_json",
    title="Excel to JSON",
    category=Category.SPREADSHEET,
    src_exts=(".xlsx", ".xlsm", ".xltx", ".xltm"),
    dst_ext=".json",
    icon="spreadsheet",
    description="Convert Excel workbook sheets to structured JSON.",
    options=(
        OptionSpec(
            "first_row_headers",
            "Use first row as headers",
            OptionKind.BOOL,
            True,
            help="If true, each row is an object keyed by column names from row 1.",
        ),
        OptionSpec(
            "single_sheet_as_list",
            "Single sheet as root array",
            OptionKind.BOOL,
            True,
            help="If workbook has only one sheet, emit an array directly instead of a sheet dictionary.",
        ),
        OptionSpec(
            "indent",
            "Indentation spaces",
            OptionKind.INT,
            2,
            help="Number of spaces for indentation (0 for compact single-line JSON).",
        ),
    ),
)


def _json_serial(obj: Any) -> Any:
    """Serialize dates, times, decimals, etc. to JSON-compatible values."""
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _make_unique_headers(raw_headers: Sequence[Any]) -> list[str]:
    """Ensure header names are non-empty and unique."""
    counts: dict[str, int] = {}
    result: list[str] = []
    for idx, h in enumerate(raw_headers, 1):
        name = str(h).strip() if h is not None else ""
        if not name:
            name = f"col_{idx}"
        base = name
        if base in counts:
            counts[base] += 1
            name = f"{base}_{counts[base]}"
        else:
            counts[base] = 0
        result.append(name)
    return result


@register(SPEC)
class XlsxToJsonConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        use_headers = opts["first_row_headers"]
        single_as_list = opts["single_sheet_as_list"]
        indent = opts["indent"]

        ctx.progress(0.05, "Opening Excel workbook")
        try:
            wb = openpyxl.load_workbook(ctx.src, data_only=True, read_only=True)
        except Exception as exc:
            raise ConversionError(f"Could not read Excel file '{ctx.src.name}': {exc}") from exc

        try:
            sheet_names = wb.sheetnames
            if not sheet_names:
                raise ConversionError(f"Excel workbook '{ctx.src.name}' contains no sheets.")

            data_by_sheet: dict[str, list[Any]] = {}
            total = len(sheet_names)

            for idx, name in enumerate(sheet_names, 1):
                ctx.check_cancelled()
                ctx.progress(idx / (total + 1), f"Reading sheet '{name}' ({idx}/{total})")

                ws = wb[name]
                rows = list(ws.iter_rows(values_only=True))

                # Filter out completely empty trailing rows
                while rows and all(c is None or str(c).strip() == "" for c in rows[-1]):
                    rows.pop()

                if not rows:
                    ctx.warn(f"Sheet '{name}' is empty.")
                    data_by_sheet[name] = []
                    continue

                if use_headers:
                    raw_headers = rows[0]
                    # Trim trailing None headers
                    headers_list = list(raw_headers)
                    while headers_list and headers_list[-1] is None:
                        headers_list.pop()

                    if not headers_list:
                        data_by_sheet[name] = []
                        continue

                    headers = _make_unique_headers(headers_list)
                    num_cols = len(headers)
                    sheet_rows: list[dict[str, Any]] = []

                    for row in rows[1:]:
                        if all(c is None or str(c).strip() == "" for c in row):
                            continue
                        row_dict: dict[str, Any] = {}
                        for c_idx in range(num_cols):
                            val = row[c_idx] if c_idx < len(row) else None
                            row_dict[headers[c_idx]] = val
                        sheet_rows.append(row_dict)
                    data_by_sheet[name] = sheet_rows
                else:
                    sheet_rows_list: list[list[Any]] = []
                    for row in rows:
                        if all(c is None or str(c).strip() == "" for c in row):
                            continue
                        sheet_rows_list.append(list(row))
                    data_by_sheet[name] = sheet_rows_list

            ctx.check_cancelled()
            ctx.progress(0.85, "Formatting JSON")

            if single_as_list and len(sheet_names) == 1:
                final_data: Any = data_by_sheet[sheet_names[0]]
            else:
                final_data = data_by_sheet

            indent_val = indent if indent > 0 else None
            output_json = json.dumps(
                final_data,
                indent=indent_val,
                ensure_ascii=False,
                default=_json_serial,
            )
            if not output_json.endswith("\n"):
                output_json += "\n"

            dest = ctx.output_path()
            ctx.write_text(dest, output_json)
            ctx.progress(1.0, "Done")
            return [dest]
        finally:
            wb.close()
