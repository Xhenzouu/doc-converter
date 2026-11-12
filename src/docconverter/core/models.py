"""Plain data types that cross layer boundaries.

Nothing here imports Qt or touches the OS. Every type is picklable, so a job can be
handed to a worker process later without changes.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from .errors import InvalidOptionError

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def normalize_ext(ext: str) -> str:
    """Return ``ext`` lower-cased with a leading dot: ``'MD'`` -> ``'.md'``."""
    ext = ext.strip().lower()
    if not ext.lstrip("."):
        raise ValueError("Empty file extension")
    return ext if ext.startswith(".") else f".{ext}"


class Category(str, Enum):
    """Tool categories. Definition order is the order the UI shows them in."""

    DOCUMENT = "Document"
    SPREADSHEET = "Spreadsheet"
    PRESENTATION = "Presentation"
    TEXT = "Text"
    IMAGE = "Image"

    @property
    def order(self) -> int:
        return list(Category).index(self)


class OptionKind(str, Enum):
    BOOL = "bool"
    CHOICE = "choice"
    TEXT = "text"
    INT = "int"


@dataclass(frozen=True)
class OptionSpec:
    """Describes one user-facing option; the UI can build a form from these."""

    key: str
    label: str
    kind: OptionKind
    default: Any
    choices: tuple[str, ...] = ()
    help: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "choices", tuple(self.choices))
        if self.kind is OptionKind.CHOICE and not self.choices:
            raise ValueError(f"Option '{self.key}' is a choice but has no choices")
        self.validate(self.default)

    def validate(self, value: Any) -> Any:
        """Return ``value`` if acceptable, else raise ``InvalidOptionError``. No coercion."""
        kind = self.kind
        if kind is OptionKind.BOOL and not isinstance(value, bool):
            self._reject(value, "true or false")
        elif kind is OptionKind.INT and (isinstance(value, bool) or not isinstance(value, int)):
            self._reject(value, "a whole number")
        elif kind is OptionKind.TEXT and not isinstance(value, str):
            self._reject(value, "text")
        elif kind is OptionKind.CHOICE and value not in self.choices:
            self._reject(value, "one of: " + ", ".join(self.choices))
        return value

    def _reject(self, value: Any, expected: str) -> None:
        raise InvalidOptionError(f"Option '{self.key}' must be {expected} (got {value!r}).")


@dataclass(frozen=True)
class ConversionSpec:
    """Describes one tool, i.e. one card in the UI grid."""

    id: str
    title: str
    category: Category
    src_exts: tuple[str, ...]
    dst_ext: str
    description: str = ""
    icon: str = ""
    options: tuple[OptionSpec, ...] = ()

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError(f"Invalid tool id {self.id!r}: use lower_snake_case")
        exts = tuple(dict.fromkeys(normalize_ext(e) for e in self.src_exts))
        if not exts:
            raise ValueError(f"Tool '{self.id}' must accept at least one source extension")
        object.__setattr__(self, "src_exts", exts)
        object.__setattr__(self, "dst_ext", normalize_ext(self.dst_ext))
        object.__setattr__(self, "category", Category(self.category))
        object.__setattr__(self, "options", tuple(self.options))
        keys = [o.key for o in self.options]
        if len(set(keys)) != len(keys):
            raise ValueError(f"Tool '{self.id}' has duplicate option keys")

    def accepts(self, path: Path | str) -> bool:
        """True if ``path`` has an extension this tool can read (case-insensitive)."""
        return Path(path).suffix.lower() in self.src_exts

    def default_options(self) -> dict[str, Any]:
        return {o.key: o.default for o in self.options}

    def resolve_options(self, given: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Merge ``given`` over the defaults, rejecting unknown keys and bad values."""
        given = dict(given or {})
        by_key = {o.key: o for o in self.options}
        unknown = sorted(set(given) - set(by_key))
        if unknown:
            raise InvalidOptionError(
                f"Unknown option(s) for '{self.title}': {', '.join(unknown)}."
            )
        resolved = self.default_options()
        for key, value in given.items():
            resolved[key] = by_key[key].validate(value)
        return resolved


@dataclass(frozen=True)
class Availability:
    """Whether a tool can run on this machine (e.g. Office/LibreOffice is installed)."""

    available: bool = True
    reason: str = ""

    @classmethod
    def ok(cls) -> "Availability":
        return cls(True)

    @classmethod
    def unavailable(cls, reason: str) -> "Availability":
        return cls(False, reason)


@dataclass(frozen=True)
class ConversionJob:
    """One source file to convert with one tool."""

    src: Path
    tool_id: str
    output_dir: Optional[Path] = None  # None -> next to the source file
    options: Mapping[str, Any] = field(default_factory=dict, compare=False)
    overwrite: bool = False  # False -> pick "name (1).ext" instead of replacing
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        object.__setattr__(self, "src", Path(self.src))
        if self.output_dir is not None:
            object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "options", dict(self.options))


class JobStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConversionResult:
    """Outcome of one job. ``convert()`` always returns one; it does not raise."""

    job: ConversionJob
    status: JobStatus
    outputs: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    error: Optional[str] = None
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is JobStatus.SUCCESS

    @property
    def cancelled(self) -> bool:
        return self.status is JobStatus.CANCELLED
