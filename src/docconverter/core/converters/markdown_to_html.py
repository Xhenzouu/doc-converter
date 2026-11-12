"""Markdown to HTML using markdown-it-py (CommonMark) plus tables, strikethrough,
footnotes, task lists and YAML front matter (which is consumed, not rendered)."""

from __future__ import annotations

import html
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from ..base import BaseConverter, ConversionContext
from ..models import Category, ConversionSpec, OptionKind, OptionSpec
from ..registry import register
from ..textio import read_text_file

SPEC = ConversionSpec(
    id="markdown_to_html",
    title="Markdown to HTML",
    category=Category.TEXT,
    src_exts=(".md", ".markdown", ".mdown"),
    dst_ext=".html",
    icon="markdown",
    description="Turn a Markdown file into a web page.",
    options=(
        OptionSpec(
            "full_document",
            "Create a complete HTML page",
            OptionKind.BOOL,
            True,
            help="Turn off to get just the HTML fragment, e.g. to paste into a CMS.",
        ),
        OptionSpec(
            "include_styles",
            "Include default styling",
            OptionKind.BOOL,
            True,
            help="Adds a small built-in stylesheet. Only applies to complete pages.",
        ),
        OptionSpec(
            "allow_html",
            "Allow raw HTML in the Markdown",
            OptionKind.BOOL,
            False,
            help="Off by default: raw tags are shown as text so a file cannot inject scripts.",
        ),
    ),
)

_STYLE = """\
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
  h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 1.6em 0 .6em; }
  h1, h2 { border-bottom: 1px solid #8884; padding-bottom: .3em; }
  h1 { font-size: 2em; }
  h2 { font-size: 1.5em; }
  code, pre { font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: .9em; }
  code { background: #8882; padding: .15em .35em; border-radius: 4px; }
  pre { background: #8881; border: 1px solid #8883; padding: 1rem; overflow-x: auto; border-radius: 6px; }
  pre code { background: none; padding: 0; }
  blockquote { margin: 1em 0; padding: 0 1em; border-left: 4px solid #8885; opacity: .85; }
  table { border-collapse: collapse; display: block; overflow-x: auto; }
  th, td { border: 1px solid #8884; padding: .4em .8em; }
  th { background: #8881; }
  img { max-width: 100%; }
  hr { border: 0; border-top: 1px solid #8884; }
  .footnotes { font-size: .9em; }
</style>
"""

_PAGE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{style}</head>
<body>
<main>
{body}</main>
</body>
</html>
"""


class RenderedMarkdown(NamedTuple):
    body: str  # HTML fragment
    title: Optional[str]  # text of the first level-1 heading, if any


def _build_parser(allow_html: bool) -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": allow_html})
    md.enable(["table", "strikethrough"])
    md.use(front_matter_plugin)
    md.use(footnote_plugin)
    md.use(tasklists_plugin)  # read-only (disabled) checkboxes
    return md


def _first_h1_text(tokens: Sequence[Token]) -> Optional[str]:
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1" and i + 1 < len(tokens):
            inline = tokens[i + 1]
            parts: list[str] = []
            for child in inline.children or []:
                if child.type in ("text", "text_special", "code_inline"):
                    parts.append(child.content)
                elif child.type in ("softbreak", "hardbreak"):
                    parts.append(" ")
            text = " ".join("".join(parts).split())
            if text:
                return text
    return None


def render_markdown(text: str, *, allow_html: bool = False) -> RenderedMarkdown:
    """Render Markdown source to an HTML fragment. Pure function; easy to unit-test."""
    md = _build_parser(allow_html)
    env: dict = {}
    tokens = md.parse(text, env)
    return RenderedMarkdown(md.renderer.render(tokens, md.options, env), _first_h1_text(tokens))


def build_page(body: str, title: str, *, include_styles: bool = True) -> str:
    """Wrap an HTML fragment in a complete, self-contained HTML document."""
    return _PAGE.format(
        title=html.escape(title, quote=False),
        style=_STYLE if include_styles else "",
        body=body,
    )


@register(SPEC)
class MarkdownToHtmlConverter(BaseConverter):
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        opts = ctx.options

        ctx.progress(0.05, "Reading file")
        decoded = read_text_file(ctx.src)
        if decoded.guessed:
            ctx.warn(
                f"The file is not valid UTF-8, so it was read as {decoded.encoding}. "
                "Check accented characters in the result."
            )
        if not decoded.text.strip():
            ctx.warn("The Markdown file is empty.")
        ctx.check_cancelled()

        ctx.progress(0.3, "Converting Markdown")
        rendered = render_markdown(decoded.text, allow_html=opts["allow_html"])
        ctx.check_cancelled()

        if opts["full_document"]:
            output = build_page(
                rendered.body,
                rendered.title or ctx.src.stem,
                include_styles=opts["include_styles"],
            )
        else:
            output = rendered.body

        ctx.progress(0.8, "Writing HTML")
        destination = ctx.output_path()
        ctx.write_text(destination, output)
        return [destination]
