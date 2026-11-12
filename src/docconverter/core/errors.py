"""Exception types for the conversion engine.

``ConversionError`` and its subclasses are *expected* failures whose message is safe
to show to the user as-is. ``ConversionCancelled`` is control flow, not an error.
"""

from __future__ import annotations


class ConversionError(Exception):
    """A conversion failed for a reason the user can understand and act on."""


class UnsupportedInputError(ConversionError):
    """The source file's extension is not accepted by the chosen tool."""


class InvalidOptionError(ConversionError):
    """An option is unknown or has a value of the wrong type."""


class BackendUnavailableError(ConversionError):
    """A required external backend (MS Office, LibreOffice, ...) is not installed."""


class UnknownToolError(ConversionError):
    """No converter is registered under the requested tool id."""


class DuplicateToolError(ValueError):
    """Programming error: two converters tried to register the same tool id."""


class ConversionCancelled(Exception):
    """Raised inside a converter when the user cancelled the job."""
