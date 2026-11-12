"""YAML to JSON converter using PyYAML's safe_load."""

from __future__ import annotations

import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Sequence

import yaml

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register
from ..textio import read_text_file

SPEC = ConversionSpec(
    id="yaml_to_json",
    title="YAML to JSON",
    category=Category.TEXT,
    src_exts=(".yaml", ".yml"),
    dst_ext=".json",
    icon="yaml",
    description="Convert YAML documents to formatted JSON using safe_load.",
    options=(
        OptionSpec(
            "indent",
            "Indentation spaces",
            OptionKind.INT,
            2,
            help="Number of spaces for indentation (0 for compact single-line JSON).",
        ),
        OptionSpec(
            "sort_keys",
            "Sort keys",
            OptionKind.BOOL,
            False,
            help="Sort dictionary keys alphabetically in the output.",
        ),
    ),
)


def _json_serial(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return str(obj)


@register(SPEC)
class YamlToJsonConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        indent = opts["indent"]
        sort_keys = opts["sort_keys"]

        ctx.progress(0.05, "Reading YAML file")
        decoded = read_text_file(ctx.src)
        if decoded.guessed:
            ctx.warn(
                f"The file is not valid UTF-8, so it was read as {decoded.encoding}. "
                "Check accented characters in the result."
            )

        raw_text = decoded.text.strip()
        if not raw_text:
            ctx.warn("The YAML file is empty.")
            dest = ctx.output_path()
            ctx.write_text(dest, "{}\n")
            return [dest]

        ctx.check_cancelled()
        ctx.progress(0.3, "Parsing YAML")

        try:
            data = yaml.safe_load(decoded.text)
        except yaml.YAMLError as exc:
            raise ConversionError(f"Invalid YAML in '{ctx.src.name}': {exc}") from exc

        if data is None:
            ctx.warn("The YAML file contains no data.")
            data = {}

        ctx.check_cancelled()
        ctx.progress(0.7, "Formatting JSON")

        indent_val = indent if indent > 0 else None
        output_json = json.dumps(
            data,
            indent=indent_val,
            ensure_ascii=False,
            sort_keys=sort_keys,
            default=_json_serial,
        )
        if not output_json.endswith("\n"):
            output_json += "\n"

        ctx.progress(0.9, "Writing JSON file")
        dest = ctx.output_path()
        ctx.write_text(dest, output_json)
        return [dest]
