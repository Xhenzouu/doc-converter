"""Word (.docx) to Markdown converter using Mammoth and Markdownify."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence

import mammoth
import markdownify

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register

SPEC = ConversionSpec(
    id="docx_to_markdown",
    title="Word to Markdown",
    category=Category.DOCUMENT,
    src_exts=(".docx",),
    dst_ext=".md",
    icon="word",
    description="Convert Word documents to clean Markdown using Mammoth and Markdownify.",
    options=(
        OptionSpec(
            "heading_style",
            "Heading style",
            OptionKind.CHOICE,
            "atx",
            choices=("atx", "underlined"),
            help="ATX (# Heading) or Setext (underlined) headings.",
        ),
        OptionSpec(
            "strip_empty_lines",
            "Normalize empty lines",
            OptionKind.BOOL,
            True,
            help="Collapse runs of multiple blank lines into a single blank line.",
        ),
    ),
)


@register(SPEC)
class DocxToMarkdownConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        h_style = markdownify.ATX if opts["heading_style"] == "atx" else markdownify.SETEXT
        strip_blank = opts["strip_empty_lines"]

        ctx.progress(0.1, "Reading Word document")
        try:
            with open(ctx.src, "rb") as docx_file:
                result = mammoth.convert_to_html(docx_file)
        except Exception as exc:
            raise ConversionError(f"Could not read Word document '{ctx.src.name}': {exc}") from exc

        for msg in result.messages:
            if getattr(msg, "type", "") == "warning" or "warning" in str(msg).lower():
                ctx.warn(str(getattr(msg, "message", msg)))

        ctx.check_cancelled()
        ctx.progress(0.6, "Converting HTML to Markdown")

        html_content = result.value or ""
        md_text = markdownify.markdownify(
            html_content,
            heading_style=h_style,
            bullets="-",
        )

        if strip_blank:
            md_text = re.sub(r"\n{3,}", "\n\n", md_text)
        md_text = md_text.strip()
        if md_text:
            md_text += "\n"
        else:
            ctx.warn("The Word document produced empty Markdown.")

        ctx.check_cancelled()
        ctx.progress(0.9, "Writing Markdown file")

        dest = ctx.output_path()
        ctx.write_text(dest, md_text)
        return [dest]
