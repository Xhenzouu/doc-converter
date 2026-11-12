"""Plain text to PDF converter using fpdf2 with embedded DejaVu Sans Mono font."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from fpdf import FPDF

from ..base import BaseConverter, ConversionContext
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register
from ..textio import read_text_file

_FONTS_DIR = Path(__file__).parent / "fonts"
_REGULAR_FONT = _FONTS_DIR / "DejaVuSansMono.ttf"
_BOLD_FONT = _FONTS_DIR / "DejaVuSansMono-Bold.ttf"
_OBLIQUE_FONT = _FONTS_DIR / "DejaVuSansMono-Oblique.ttf"
_BOLD_OBLIQUE_FONT = _FONTS_DIR / "DejaVuSansMono-BoldOblique.ttf"

SPEC = ConversionSpec(
    id="txt_to_pdf",
    title="Text to PDF",
    category=Category.TEXT,
    src_exts=(".txt", ".text", ".log"),
    dst_ext=".pdf",
    icon="file-text",
    description="Convert plain text files to PDF documents with a monospaced Unicode font.",
    options=(
        OptionSpec(
            "page_size",
            "Page size",
            OptionKind.CHOICE,
            "A4",
            choices=("A4", "Letter"),
            help="Page paper size.",
        ),
        OptionSpec(
            "orientation",
            "Orientation",
            OptionKind.CHOICE,
            "portrait",
            choices=("portrait", "landscape"),
            help="Page orientation.",
        ),
        OptionSpec(
            "font_size",
            "Font size",
            OptionKind.INT,
            10,
            help="Font size in points.",
        ),
        OptionSpec(
            "line_numbers",
            "Show line numbers",
            OptionKind.BOOL,
            False,
            help="Prefix each line with its line number.",
        ),
    ),
)


@register(SPEC)
class TxtToPdfConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        page_size = opts["page_size"]
        orientation = "P" if opts["orientation"] == "portrait" else "L"
        font_size = max(4, min(72, opts["font_size"]))
        show_line_numbers = opts["line_numbers"]

        ctx.progress(0.05, "Reading text file")
        decoded = read_text_file(ctx.src)
        if decoded.guessed:
            ctx.warn(
                f"The file is not valid UTF-8, so it was read as {decoded.encoding}. "
                "Check accented characters in the result."
            )

        if not decoded.text.strip():
            ctx.warn("The text file is empty.")

        ctx.check_cancelled()
        ctx.progress(0.2, "Initializing PDF document")

        pdf = FPDF(orientation=orientation, unit="pt", format=page_size)
        pdf.set_auto_page_break(auto=True, margin=36)
        pdf.set_margins(left=36, top=36, right=36)

        # Register embedded DejaVu Sans Mono font family
        font_family = "DejaVuSansMono"
        if _REGULAR_FONT.exists():
            pdf.add_font(font_family, style="", fname=_REGULAR_FONT)
            if _BOLD_FONT.exists():
                pdf.add_font(font_family, style="B", fname=_BOLD_FONT)
            if _OBLIQUE_FONT.exists():
                pdf.add_font(font_family, style="I", fname=_OBLIQUE_FONT)
            if _BOLD_OBLIQUE_FONT.exists():
                pdf.add_font(font_family, style="BI", fname=_BOLD_OBLIQUE_FONT)
        else:
            font_family = "Courier"

        pdf.add_page()
        pdf.set_font(font_family, size=font_size)

        line_height = round(font_size * 1.35, 1)
        raw_lines = decoded.text.splitlines()
        total_lines = len(raw_lines)
        num_width = len(str(max(1, total_lines)))

        if not raw_lines:
            # Empty file produces a blank single page
            raw_lines = [""]

        ctx.check_cancelled()
        for idx, line in enumerate(raw_lines, 1):
            if idx % 100 == 0:
                ctx.check_cancelled()
                ctx.progress(0.2 + 0.7 * (idx / total_lines), f"Formatting line {idx}/{total_lines}")

            # Expand tabs for uniform monospaced indentation
            expanded = line.expandtabs(4)
            if show_line_numbers and total_lines > 1:
                prefix = f"{idx:>{num_width}} | "
                content = prefix + expanded
            else:
                content = expanded

            pdf.multi_cell(
                w=0,
                h=line_height,
                text=content,
                new_x="LMARGIN",
                new_y="NEXT",
            )

        ctx.check_cancelled()
        ctx.progress(0.95, "Generating PDF")

        dest = ctx.output_path()
        pdf_bytes = bytes(pdf.output())
        ctx.write_bytes(dest, pdf_bytes)
        return [dest]
