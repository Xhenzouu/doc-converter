"""JSON to CSV converter.

Flattens nested JSON structures using dotted notation (e.g. user.address.city)
and produces tabular CSV output.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register
from ..textio import read_text_file

SPEC = ConversionSpec(
    id="json_to_csv",
    title="JSON to CSV",
    category=Category.TEXT,
    src_exts=(".json",),
    dst_ext=".csv",
    icon="json",
    description="Flatten nested JSON keys into CSV columns.",
    options=(
        OptionSpec(
            "delimiter",
            "Delimiter",
            OptionKind.CHOICE,
            ",",
            choices=(",", ";", "\t"),
            help="Delimiter character separating CSV columns.",
        ),
    ),
)


def flatten_json_object(
    obj: Mapping[str, Any],
    prefix: str = "",
    sep: str = ".",
) -> dict[str, Any]:
    """Recursively flatten nested dictionary keys using dotted notation."""
    items: list[tuple[str, Any]] = []
    for key, value in obj.items():
        new_key = f"{prefix}{sep}{key}" if prefix else str(key)
        if isinstance(value, dict) and value:  # Non-empty sub-dict
            items.extend(flatten_json_object(value, prefix=new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)


def json_to_rows(data: Any) -> list[dict[str, Any]]:
    """Convert parsed JSON data (dict or list) into a list of flat dictionaries."""
    if isinstance(data, dict):
        return [flatten_json_object(data)]
    if isinstance(data, list):
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(flatten_json_object(item))
            else:
                rows.append({"value": item})
        return rows
    raise ConversionError(
        f"JSON root must be an object or a list of objects (got {type(data).__name__})."
    )


def format_csv_cell(value: Any) -> str:
    """Format a value for CSV output."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@register(SPEC)
class JsonToCsvConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        delimiter = opts["delimiter"]

        ctx.progress(0.05, "Reading JSON file")
        decoded = read_text_file(ctx.src)
        if decoded.guessed:
            ctx.warn(
                f"The file is not valid UTF-8, so it was read as {decoded.encoding}. "
                "Check accented characters in the result."
            )

        raw_text = decoded.text.strip()
        if not raw_text:
            ctx.warn("The JSON file is empty.")
            dest = ctx.output_path()
            ctx.write_text(dest, "")
            return [dest]

        ctx.check_cancelled()
        ctx.progress(0.2, "Parsing JSON data")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid JSON in '{ctx.src.name}': {exc.msg} (line {exc.lineno}, col {exc.colno})") from exc

        ctx.check_cancelled()
        ctx.progress(0.5, "Flattening nested objects")

        rows = json_to_rows(parsed)
        if not rows:
            ctx.warn("The JSON array is empty.")
            dest = ctx.output_path()
            ctx.write_text(dest, "")
            return [dest]

        # Collect unique fieldnames in order of appearance
        fieldnames: list[str] = []
        for row in rows:
            for k in row:
                if k not in fieldnames:
                    fieldnames.append(k)

        if not fieldnames:
            ctx.warn("No fields found to write to CSV.")
            dest = ctx.output_path()
            ctx.write_text(dest, "")
            return [dest]

        ctx.check_cancelled()
        ctx.progress(0.8, "Writing CSV")

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
        writer.writerow(fieldnames)

        for row in rows:
            writer.writerow([format_csv_cell(row.get(k)) for k in fieldnames])

        destination = ctx.output_path()
        ctx.write_text(destination, buf.getvalue())
        return [destination]
