"""Excel (.xlsx) to CSV converter.

Iterates over all sheets in the workbook and outputs one CSV file per sheet,
naming each output with a sheet suffix: e.g. <stem>_Sheet1.csv.
"""

from __future__ import annotations

import csv
import datetime
import io
from pathlib import Path
from typing import Any, Sequence

import openpyxl

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..paths import safe_filename_part
from ..registry import register

SPEC = ConversionSpec(
    id="xlsx_to_csv",
    title="Excel to CSV",
    category=Category.SPREADSHEET,
    src_exts=(".xlsx", ".xlsm", ".xltx", ".xltm"),
    dst_ext=".csv",
    icon="spreadsheet",
    description="Export each sheet in an Excel workbook to a separate CSV file.",
    options=(
        OptionSpec(
            "delimiter",
            "Delimiter",
            OptionKind.CHOICE,
            ",",
            choices=(",", ";", "\t"),
            help="Delimiter character separating CSV columns.",
        ),
        OptionSpec(
            "skip_empty_rows",
            "Skip empty rows",
            OptionKind.BOOL,
            True,
            help="Do not write rows that contain only empty cells.",
        ),
    ),
)


def _format_cell_value(val: Any) -> str:
    """Format cell value for CSV output."""
    if val is None:
        return ""
    if isinstance(val, (datetime.date, datetime.datetime, datetime.time)):
        return val.isoformat()
    return str(val)


@register(SPEC)
class XlsxToCsvConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        delimiter = opts["delimiter"]
        skip_empty_rows = opts["skip_empty_rows"]

        ctx.progress(0.05, "Opening Excel workbook")
        try:
            wb = openpyxl.load_workbook(ctx.src, data_only=True, read_only=True)
        except Exception as exc:
            raise ConversionError(f"Could not read Excel file '{ctx.src.name}': {exc}") from exc

        try:
            sheet_names = wb.sheetnames
            if not sheet_names:
                raise ConversionError(f"Excel workbook '{ctx.src.name}' contains no sheets.")

            outputs: list[Path] = []
            total = len(sheet_names)

            for idx, name in enumerate(sheet_names, 1):
                ctx.check_cancelled()
                ctx.progress(idx / (total + 1), f"Exporting sheet '{name}' ({idx}/{total})")

                ws = wb[name]
                buf = io.StringIO()
                writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")

                row_count = 0
                has_content = False

                for row in ws.iter_rows(values_only=True):
                    is_empty = all(c is None or str(c).strip() == "" for c in row)
                    if is_empty and skip_empty_rows:
                        continue
                    writer.writerow([_format_cell_value(c) for c in row])
                    row_count += 1
                    has_content = True

                if not has_content:
                    ctx.warn(f"Sheet '{name}' is empty.")

                suffix = f"_{safe_filename_part(name)}"
                path = ctx.output_path(suffix=suffix, ext=".csv")
                ctx.write_text(path, buf.getvalue())
                outputs.append(path)

            ctx.progress(1.0, "Done")
            return outputs
        finally:
            wb.close()
