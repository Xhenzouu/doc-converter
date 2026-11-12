"""Built-in converters. Importing this package registers all of them.

The imports are listed explicitly rather than discovered with ``pkgutil``: PyInstaller
only bundles modules it can see statically, so dynamic discovery would silently drop
converters from the packaged app.
"""

from . import (
    docx_to_markdown,  # noqa: F401
    image,  # noqa: F401
    json_to_csv,  # noqa: F401
    markdown_to_html,  # noqa: F401
    pdf,  # noqa: F401
    txt_to_pdf,  # noqa: F401
    xlsx_to_csv,  # noqa: F401
    xlsx_to_json,  # noqa: F401
    yaml_to_json,  # noqa: F401
)

__all__ = [
    "docx_to_markdown",
    "image",
    "json_to_csv",
    "markdown_to_html",
    "pdf",
    "txt_to_pdf",
    "xlsx_to_csv",
    "xlsx_to_json",
    "yaml_to_json",
]
