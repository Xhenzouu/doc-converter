"""The converter interface.

Subclasses implement only ``_convert``. The public ``convert`` is a template method that
validates the job, runs the conversion, and turns every outcome (success, expected
error, unexpected bug, cancellation) into a ``ConversionResult``. It never raises, so a
batch loop or worker thread can treat each file independently.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar, Mapping, Optional, Sequence

from .errors import (
    BackendUnavailableError,
    ConversionCancelled,
    ConversionError,
    UnsupportedInputError,
)
from .models import (
    Availability,
    ConversionJob,
    ConversionResult,
    ConversionSpec,
    JobStatus,
)
from .paths import resolve_output_path
from .textio import atomic_write_bytes, atomic_write_text

log = logging.getLogger(__name__)

# progress_cb(fraction, message): fraction is 0.0-1.0, or None when progress is unknown
# (the UI shows a busy indicator).
ProgressCallback = Callable[[Optional[float], str], None]


class ConversionContext:
    """What a converter gets to work with: the job, resolved options, and helpers.

    Files written through ``write_text``/``write_bytes`` are tracked, so they are removed
    again if the conversion later fails or is cancelled.
    """

    def __init__(
        self,
        job: ConversionJob,
        spec: ConversionSpec,
        options: Mapping[str, Any],
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self.job = job
        self.spec = spec
        self.options = options
        self.warnings: list[str] = []
        self._progress_cb = progress_cb
        self._cancel_event = cancel_event
        self._reserved: list[Path] = []
        self._written: list[Path] = []

    @property
    def src(self) -> Path:
        return self.job.src

    def progress(self, fraction: Optional[float], message: str = "") -> None:
        """Report progress. A failing callback never breaks the conversion."""
        if self._progress_cb is None:
            return
        if fraction is not None:
            fraction = min(1.0, max(0.0, fraction))
        try:
            self._progress_cb(fraction, message)
        except Exception:
            log.exception("Progress callback raised; ignoring")

    def check_cancelled(self) -> None:
        """Call between steps; raises ``ConversionCancelled`` if the user cancelled."""
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise ConversionCancelled()

    def warn(self, message: str) -> None:
        """Record a non-fatal problem to show next to the (successful) result."""
        self.warnings.append(message)

    def output_path(self, suffix: str = "", ext: Optional[str] = None) -> Path:
        """Choose an output path (see ``resolve_output_path``).

        Paths handed out here are reserved, so asking twice for the same name within one
        run (e.g. two sheets named alike) yields distinct files.
        """
        path = resolve_output_path(
            self.job.src,
            ext or self.spec.dst_ext,
            output_dir=self.job.output_dir,
            suffix=suffix,
            overwrite=self.job.overwrite,
            taken=self._reserved,
        )
        self._reserved.append(path)
        return path

    def write_text(self, path: Path, text: str, encoding: str = "utf-8") -> Path:
        atomic_write_text(path, text, encoding)
        self._written.append(path)
        return path

    def write_bytes(self, path: Path, data: bytes) -> Path:
        atomic_write_bytes(path, data)
        self._written.append(path)
        return path

    def track(self, path: Path) -> None:
        """Mark a file written by other means (a subprocess, a library) for cleanup."""
        self._written.append(path)

    def cleanup(self) -> None:
        """Remove everything this run wrote. Called automatically on failure/cancel."""
        for path in reversed(self._written):
            with contextlib.suppress(OSError):
                path.unlink()
        self._written.clear()


class BaseConverter(ABC):
    """One conversion tool. Registered with ``@register(spec)``, which sets ``spec``."""

    spec: ClassVar[ConversionSpec]

    @classmethod
    def availability(cls) -> Availability:
        """Override when the tool needs an external backend; the UI greys the card out."""
        return Availability.ok()

    @abstractmethod
    def _convert(self, ctx: ConversionContext) -> Sequence[Path]:
        """Do the work and return the output files.

        Raise ``ConversionError`` with a user-readable message for expected failures.
        Call ``ctx.check_cancelled()`` between steps and ``ctx.progress()`` as you go.
        """

    def convert(
        self,
        job: ConversionJob,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ConversionResult:
        started = time.perf_counter()
        ctx: Optional[ConversionContext] = None

        def result(
            status: JobStatus, outputs: Sequence[Path] = (), error: Optional[str] = None
        ) -> ConversionResult:
            return ConversionResult(
                job=job,
                status=status,
                outputs=tuple(outputs),
                warnings=tuple(ctx.warnings) if ctx else (),
                error=error,
                duration_s=time.perf_counter() - started,
            )

        def fail(message: str) -> ConversionResult:
            if ctx:
                ctx.cleanup()
            return result(JobStatus.FAILED, error=message)

        try:
            options = self.spec.resolve_options(job.options)
            self._preflight(job)
            ctx = ConversionContext(job, self.spec, options, progress_cb, cancel_event)
            ctx.check_cancelled()
            outputs = list(self._convert(ctx))
            ctx.progress(1.0, "Done")
            return result(JobStatus.SUCCESS, outputs)
        except ConversionCancelled:
            if ctx:
                ctx.cleanup()
            return result(JobStatus.CANCELLED)
        except ConversionError as exc:
            return fail(str(exc))
        except OSError as exc:
            return fail(f"File system error: {exc}")
        except Exception as exc:  # a bug in a converter must not take down the batch
            log.exception("Unexpected error converting %s with %s", job.src, self.spec.id)
            return fail(f"Unexpected error ({type(exc).__name__}): {exc}")

    def _preflight(self, job: ConversionJob) -> None:
        if job.tool_id != self.spec.id:
            raise ConversionError(
                f"Job is for tool '{job.tool_id}' but was given to '{self.spec.id}'."
            )
        if not job.src.is_file():
            raise ConversionError(f"Source file not found: {job.src}")
        if not self.spec.accepts(job.src):
            accepted = ", ".join(self.spec.src_exts)
            raise UnsupportedInputError(
                f"'{job.src.name}' is not a supported input for {self.spec.title} "
                f"(expected {accepted})."
            )
        availability = self.availability()
        if not availability.available:
            raise BackendUnavailableError(
                availability.reason or f"{self.spec.title} is not available on this computer."
            )
