"""Pure-Python conversion engine. Must never import Qt or any GUI/OS-shell code."""

from .base import BaseConverter, ConversionContext, ProgressCallback
from .errors import (
    BackendUnavailableError,
    ConversionCancelled,
    ConversionError,
    DuplicateToolError,
    InvalidOptionError,
    UnknownToolError,
    UnsupportedInputError,
)
from .models import (
    Availability,
    Category,
    ConversionJob,
    ConversionResult,
    ConversionSpec,
    JobStatus,
    OptionKind,
    OptionSpec,
)
from .registry import Registry, load_builtin_converters, register, registry

__all__ = [
    "Availability",
    "BackendUnavailableError",
    "BaseConverter",
    "Category",
    "ConversionCancelled",
    "ConversionContext",
    "ConversionError",
    "ConversionJob",
    "ConversionResult",
    "ConversionSpec",
    "DuplicateToolError",
    "InvalidOptionError",
    "JobStatus",
    "OptionKind",
    "OptionSpec",
    "ProgressCallback",
    "Registry",
    "UnknownToolError",
    "UnsupportedInputError",
    "load_builtin_converters",
    "register",
    "registry",
]
