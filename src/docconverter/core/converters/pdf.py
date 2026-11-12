"""PDF converters.

PDF → Word (.docx)
    Pipeline: pypdf text extraction → lightweight Markdown heuristics → Pandoc → .docx
    pypandoc_binary bundles Pandoc so no manual install is required.

PDF → Text (.txt)
    Plain page-by-page extraction via pypdf.

Honest limitations
------------------
PDF stores positioned glyphs, not semantic structure.  pypdf returns a *flat
text stream* – there is no reliable way to auto-detect headings, bullets, or
tables from arbitrary PDFs.  The Markdown heuristics below work well for PDFs
originally exported from word-processors (clear heading lines, indented lists)
and produce clean paragraph breaks in the resulting .docx.  Scanned PDFs or
complex multi-column layouts will still produce mostly flat output; that is a
fundamental limitation of text-based PDF extraction, not a bug.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Sequence

from ..base import BaseConverter, ConversionContext
from ..errors import ConversionError
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register


# ---------------------------------------------------------------------------
# Heuristic: flat text → Markdown
# ---------------------------------------------------------------------------

# Lines shorter than this that end without punctuation are treated as headings.
_HEADING_MAX_LEN = 80
# Bullet prefixes pypdf commonly extracts from PDF list items.
_BULLET_RE = re.compile(r"^[\s]*([•\-\*·▪▸➤◆○●►]|\d+[.)]\s)\s*")
# A "likely heading" line: short, not ending in mid-sentence punctuation,
# not a bullet, and either Title-Cased, ALL CAPS, or bold-prefixed.
_HEADING_RE = re.compile(
    r"^(?![\s]*[•\-\*·▪▸➤◆○●►])(.{4," + str(_HEADING_MAX_LEN) + r"})$"
)


def _looks_like_heading(line: str, next_line: str) -> bool:
    """Heuristic: is this line a standalone heading?"""
    stripped = line.strip()
    if not stripped or len(stripped) > _HEADING_MAX_LEN:
        return False
    # Must not end in a sentence-continuing character
    if stripped[-1] in ",:;":
        return False
    # Next line must be blank or another heading (not a continuation)
    if next_line.strip():
        return False
    # Favour lines that are title-cased or ALL CAPS
    words = stripped.split()
    if len(words) > 10:
        return False
    all_caps = stripped == stripped.upper() and any(c.isalpha() for c in stripped)
    title_case = sum(1 for w in words if w and w[0].isupper()) >= max(1, len(words) // 2)
    return all_caps or title_case


def _text_to_markdown(raw_pages: list[str]) -> str:
    """Convert a list of per-page plain-text strings into a Markdown document.

    Strategy (in priority order):
    1. Blank lines → paragraph breaks (kept as-is).
    2. Lines that match bullet prefixes → Markdown list items.
    3. Short, title-cased or ALL-CAPS lines followed by a blank → ## heading.
    4. Everything else → plain paragraph text.
    """
    md_lines: list[str] = []

    for page_num, page_text in enumerate(raw_pages):
        if page_num > 0:
            md_lines.append("\n---\n")  # horizontal rule between pages

        # Normalise line endings and collapse 3+ blank lines to 2
        page_text = re.sub(r"\r\n?", "\n", page_text)
        page_text = re.sub(r"\n{3,}", "\n\n", page_text)
        lines = page_text.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            next_line = lines[i + 1] if i + 1 < len(lines) else ""

            if not line.strip():
                md_lines.append("")
                i += 1
                continue

            # Bullet detection
            m = _BULLET_RE.match(line)
            if m:
                content = line[m.end():].strip()
                md_lines.append(f"- {content}")
                i += 1
                continue

            # Heading detection
            if _looks_like_heading(line.strip(), next_line):
                md_lines.append(f"## {line.strip()}")
                i += 1
                continue

            # Plain text — wrap in a paragraph (just append the line)
            md_lines.append(line.rstrip())
            i += 1

    # Final cleanup: no more than 2 consecutive blank lines
    result = "\n".join(md_lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result + "\n" if result else "\n"


# ---------------------------------------------------------------------------
# Shared pypdf helper
# ---------------------------------------------------------------------------

def _extract_pages(src: Path, ctx: ConversionContext) -> list[str]:
    """Open the PDF and return a list of per-page text strings."""
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover
        raise ConversionError("pypdf is not installed. Run: pip install pypdf") from exc

    ctx.progress(0.1, "Opening PDF")
    try:
        reader = pypdf.PdfReader(str(src))
    except Exception as exc:
        raise ConversionError(f"Could not open PDF '{src.name}': {exc}") from exc

    total = len(reader.pages)
    if total == 0:
        raise ConversionError(f"'{src.name}' has no pages.")

    ctx.progress(0.2, f"Extracting text from {total} page(s)")
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        ctx.check_cancelled()
        ctx.progress(0.2 + 0.5 * (i / total), f"Page {i + 1}/{total}")
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")  # gracefully skip unreadable pages

    return pages


# ---------------------------------------------------------------------------
# PDF → Word  (pypdf → Markdown heuristics → Pandoc → .docx)
# ---------------------------------------------------------------------------

SPEC_PDF_TO_DOCX = ConversionSpec(
    id="pdf_to_docx",
    title="PDF to Word",
    category=Category.DOCUMENT,
    src_exts=(".pdf",),
    dst_ext=".docx",
    icon="pdf",
    description=(
        "Convert PDF to Word via text extraction + Pandoc. "
        "Works best on text-based PDFs (e.g. exported from Word). "
        "Scanned or image-only PDFs will produce flat text output."
    ),
    options=(
        OptionSpec(
            "detect_structure",
            "Detect headings & bullets",
            OptionKind.BOOL,
            True,
            help=(
                "Apply heuristics to convert short title-cased lines to headings "
                "and bullet-prefixed lines to lists before passing to Pandoc."
            ),
        ),
    ),
)


def _get_pandoc_path() -> str | None:
    """Return the path to the Pandoc executable, handling frozen exe layout."""
    # 1. When frozen by PyInstaller, check sys._MEIPASS first (one-file mode)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            for name in (
                "pandoc.exe",
                "pandoc",
                "pypandoc/files/pandoc.exe",
                "pypandoc/files/pandoc",
            ):
                candidate = Path(meipass) / name
                if candidate.exists():
                    return str(candidate)
        # Check next to executable (one-dir mode)
        exe_dir = Path(sys.executable).parent
        for name in ("pandoc.exe", "pandoc"):
            candidate = exe_dir / name
            if candidate.exists():
                return str(candidate)

    # 2. Check PYPANDOC_PANDOC environment variable
    env_pandoc = os.environ.get("PYPANDOC_PANDOC")
    if env_pandoc:
        p = Path(env_pandoc)
        if p.exists():
            return str(p)

    # 3. Fall back to pypandoc's default resolution
    try:
        import pypandoc
        path = pypandoc.get_pandoc_path()
        # On Windows pypandoc omits the .exe suffix in the returned path
        if sys.platform == "win32" and not path.endswith(".exe"):
            candidate = path + ".exe"
            if Path(candidate).exists():
                return candidate
        if Path(path).exists():
            return path
    except Exception:
        pass

    return None


@register(SPEC_PDF_TO_DOCX)
class PdfToDocxConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        try:
            import pypandoc
        except ImportError as exc:  # pragma: no cover
            raise ConversionError(
                "pypandoc is not installed. Run: pip install pypandoc_binary"
            ) from exc

        pages = _extract_pages(ctx.src, ctx)
        detect = ctx.options["detect_structure"]

        ctx.progress(0.75, "Building Markdown intermediate")
        if detect:
            md_text = _text_to_markdown(pages)
        else:
            # Simple join with page separators, no heuristics
            separator = "\n\n---\n\n"
            md_text = separator.join(
                re.sub(r"\n{3,}", "\n\n", p).strip() for p in pages
            ).strip() + "\n"

        ctx.check_cancelled()
        ctx.progress(0.85, "Converting Markdown → Word via Pandoc")

        pandoc_path = _get_pandoc_path()
        dest = ctx.output_path()

        extra_args = ["--standalone"]
        pandoc_kwargs: dict = {
            "format": "markdown",
            "outputfile": str(dest),
            "extra_args": extra_args,
        }
        if pandoc_path:
            pandoc_kwargs["sandbox"] = False  # allow subprocess

        old_path = os.environ.get("PATH", "")
        old_pypandoc_env = os.environ.get("PYPANDOC_PANDOC")

        try:
            if pandoc_path:
                os.environ["PYPANDOC_PANDOC"] = pandoc_path
                pandoc_dir = str(Path(pandoc_path).parent)
                os.environ["PATH"] = pandoc_dir + os.pathsep + old_path
                try:
                    pypandoc.clean_pandocpath_cache()
                except Exception:
                    pass

            pypandoc.convert_text(md_text, "docx", **pandoc_kwargs)
        except Exception as exc:
            raise ConversionError(
                f"Pandoc failed to convert '{ctx.src.name}' to Word: {exc}"
            ) from exc
        finally:
            os.environ["PATH"] = old_path
            if old_pypandoc_env is not None:
                os.environ["PYPANDOC_PANDOC"] = old_pypandoc_env
            else:
                os.environ.pop("PYPANDOC_PANDOC", None)
            try:
                pypandoc.clean_pandocpath_cache()
            except Exception:
                pass

        ctx.progress(1.0, "Done")
        return [dest]


# ---------------------------------------------------------------------------
# PDF → Text
# ---------------------------------------------------------------------------

SPEC_PDF_TO_TXT = ConversionSpec(
    id="pdf_to_txt",
    title="PDF to Text",
    category=Category.TEXT,
    src_exts=(".pdf",),
    dst_ext=".txt",
    icon="pdf",
    description="Extract plain text from PDF pages using pypdf.",
    options=(
        OptionSpec(
            "page_separator",
            "Page separator",
            OptionKind.TEXT,
            "\n\n--- Page {n} ---\n\n",
            help=(
                "Template inserted between pages. "
                "Use '{n}' for the 1-based page number. "
                "Set to empty string to join pages without a separator."
            ),
        ),
        OptionSpec(
            "strip_whitespace",
            "Strip extra whitespace",
            OptionKind.BOOL,
            True,
            help="Collapse multiple blank lines and strip leading/trailing whitespace per page.",
        ),
    ),
)


@register(SPEC_PDF_TO_TXT)
class PdfToTxtConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options
        separator_template: str = opts["page_separator"]
        strip_ws: bool = opts["strip_whitespace"]

        pages = _extract_pages(ctx.src, ctx)

        ctx.progress(0.75, "Formatting output")
        parts: list[str] = []
        for i, text in enumerate(pages):
            if strip_ws:
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if i > 0 and separator_template:
                parts.append(separator_template.format(n=i + 1))
            parts.append(text)

        full_text = "".join(parts).rstrip() + "\n"

        ctx.progress(0.95, "Writing text file")
        dest = ctx.output_path()
        ctx.write_text(dest, full_text)

        ctx.progress(1.0, "Done")
        return [dest]