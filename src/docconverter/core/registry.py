"""Converter registry: the single source of truth the UI grid is built from.

``@register(spec)`` adds a converter class. The UI iterates ``all_specs()`` (or
``specs_by_category()``) to draw cards, ``specs_for_path()`` to offer the right tools for
a file that arrived from the right-click menu, and ``run()`` to execute a job.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional, TypeVar

from .base import BaseConverter, ProgressCallback
from .errors import DuplicateToolError, UnknownToolError
from .models import (
    Availability,
    Category,
    ConversionJob,
    ConversionResult,
    ConversionSpec,
    normalize_ext,
)

C = TypeVar("C", bound=type)


class Registry:
    def __init__(self) -> None:
        self._classes: dict[str, type[BaseConverter]] = {}

    def register(self, spec: ConversionSpec) -> Callable[[C], C]:
        """Class decorator: ``@register(SPEC)``. Sets ``cls.spec`` and records the class."""

        def decorator(cls: C) -> C:
            if not (isinstance(cls, type) and issubclass(cls, BaseConverter)):
                raise TypeError(f"{cls!r} must subclass BaseConverter to be registered")
            if spec.id in self._classes:
                raise DuplicateToolError(f"A converter with id '{spec.id}' is already registered")
            cls.spec = spec
            self._classes[spec.id] = cls
            return cls

        return decorator

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self._classes

    def __len__(self) -> int:
        return len(self._classes)

    def _class_for(self, tool_id: str) -> type[BaseConverter]:
        try:
            return self._classes[tool_id]
        except KeyError:
            raise UnknownToolError(f"Unknown conversion tool: '{tool_id}'.") from None

    def get_spec(self, tool_id: str) -> ConversionSpec:
        return self._class_for(tool_id).spec

    def get_converter(self, tool_id: str) -> BaseConverter:
        """Return a fresh converter instance (converters hold no state between jobs)."""
        return self._class_for(tool_id)()

    def availability(self, tool_id: str) -> Availability:
        return self._class_for(tool_id).availability()

    @staticmethod
    def _sorted(specs: list[ConversionSpec]) -> list[ConversionSpec]:
        return sorted(specs, key=lambda s: (s.category.order, s.title.lower()))

    def all_specs(self) -> list[ConversionSpec]:
        """Every tool, ordered by category and then title (stable order for the UI)."""
        return self._sorted([cls.spec for cls in self._classes.values()])

    def specs_by_category(self) -> dict[Category, list[ConversionSpec]]:
        """Non-empty categories in display order, each with its tools."""
        grouped: dict[Category, list[ConversionSpec]] = {}
        for spec in self.all_specs():
            grouped.setdefault(spec.category, []).append(spec)
        return grouped

    def specs_for_extension(self, ext: str) -> list[ConversionSpec]:
        ext = normalize_ext(ext)
        return self._sorted([s for s in self.all_specs() if ext in s.src_exts])

    def specs_for_path(self, path: Path | str) -> list[ConversionSpec]:
        """Tools that can read ``path``. Empty if the file type is unsupported."""
        suffix = Path(path).suffix
        return self.specs_for_extension(suffix) if suffix else []

    def run(
        self,
        job: ConversionJob,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ConversionResult:
        """Run ``job`` with the converter registered for ``job.tool_id``."""
        return self.get_converter(job.tool_id).convert(job, progress_cb, cancel_event)


registry = Registry()
register = registry.register


def load_builtin_converters() -> Registry:
    """Import the built-in converters so they register themselves (idempotent)."""
    from . import converters  # noqa: F401

    return registry
