"""Output file naming. Pure ``pathlib``/``os``; no Qt."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

from .errors import ConversionError
from .models import normalize_ext

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_COLLISION_INDEX = 9999


def safe_filename_part(text: str, fallback: str = "untitled", max_len: int = 80) -> str:
    """Make ``text`` (e.g. an Excel sheet name) safe to embed in a file name."""
    cleaned = _ILLEGAL_CHARS.sub("_", text).strip(" .")
    cleaned = cleaned[:max_len].rstrip(" .")
    return cleaned or fallback


def _key(path: Path) -> str:
    """Comparison key that respects case-insensitive file systems (Windows, macOS)."""
    return os.path.normcase(os.path.abspath(path))


def resolve_output_path(
    src: Path,
    ext: str,
    *,
    output_dir: Optional[Path] = None,
    suffix: str = "",
    overwrite: bool = False,
    taken: Iterable[Path] = (),
) -> Path:
    """Choose where to write ``<src stem><suffix><ext>``.

    * The directory is ``output_dir`` (created if needed), else the source's folder.
    * Without ``overwrite``, an existing file is never replaced: ``report.pdf`` becomes
      ``report (1).pdf``, ``report (2).pdf``, ...
    * The source file itself and anything in ``taken`` (paths already handed out during
      this run but not yet written) are never returned, even with ``overwrite``.
    """
    src = Path(src)
    ext = normalize_ext(ext)
    directory = Path(output_dir) if output_dir is not None else src.parent
    directory.mkdir(parents=True, exist_ok=True)

    blocked = {_key(p) for p in taken} | {_key(src)}
    stem = f"{src.stem}{suffix}"

    def usable(candidate: Path) -> bool:
        if _key(candidate) in blocked:
            return False
        return overwrite or not candidate.exists()

    candidate = directory / f"{stem}{ext}"
    if usable(candidate):
        return candidate
    for n in range(1, _MAX_COLLISION_INDEX + 1):
        candidate = directory / f"{stem} ({n}){ext}"
        if usable(candidate):
            return candidate
    raise ConversionError(f"Could not find a free output file name for '{stem}{ext}'.")
