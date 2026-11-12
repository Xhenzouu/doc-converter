"""Reading and writing text files robustly. Shared by the text-based converters."""

from __future__ import annotations

import codecs
import contextlib
import os
import uuid
from pathlib import Path
from typing import NamedTuple

from .errors import ConversionError

_BINARY_SNIFF_BYTES = 8192


class DecodedText(NamedTuple):
    text: str
    encoding: str
    guessed: bool  # True when the encoding was a fallback guess rather than certain


def decode_bytes(data: bytes) -> DecodedText:
    """Decode a text file of unknown encoding.

    Order: UTF-32/UTF-16 by BOM, then UTF-8 (with or without BOM), then cp1252 and
    finally latin-1 (which cannot fail). Data that looks binary is rejected.
    """
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return DecodedText(data.decode("utf-32"), "utf-32", False)
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return DecodedText(data.decode("utf-16"), "utf-16", False)
    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        raise ConversionError("This file does not look like a text file.")
    try:
        return DecodedText(data.decode("utf-8-sig"), "utf-8", False)
    except UnicodeDecodeError:
        pass
    try:
        return DecodedText(data.decode("cp1252"), "cp1252", True)
    except UnicodeDecodeError:
        return DecodedText(data.decode("latin-1"), "latin-1", True)


def read_text_file(path: Path | str) -> DecodedText:
    return decode_bytes(Path(path).read_bytes())


def atomic_write_bytes(path: Path | str, data: bytes) -> Path:
    """Write ``data`` to ``path`` so readers never see a half-written file.

    Writes to a sibling temp file, then renames it over the target. The temp file is
    removed if anything fails. It is created with the process umask, so permissions
    match what a normal save would give.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with open(tmp, "xb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return path


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> Path:
    """Like :func:`atomic_write_bytes`; ``\\n`` is written as-is on every OS."""
    return atomic_write_bytes(path, text.encode(encoding))
