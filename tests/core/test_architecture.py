"""Guards the layering rule: ``core`` must stay free of Qt and of every other layer."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
CORE = SRC / "docconverter" / "core"

FORBIDDEN_PREFIXES = (
    "PySide6",
    "PyQt5",
    "PyQt6",
    "shiboken6",
    "docconverter.ui",
    "docconverter.services",
    "docconverter.tray",
    "docconverter.platform_integration",
    "docconverter.cli",
    "docconverter.app",
)


def _is_forbidden(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def forbidden_imports(source: str, package: str) -> list[str]:
    """Imports in ``source`` that core code must not use.

    ``package`` is the dotted package the file lives in, needed to resolve relative imports.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        else:
            continue
        found += [name for name in names if _is_forbidden(name)]
    return found


def test_detector_catches_violations():
    assert forbidden_imports("import PySide6.QtCore", "docconverter.core")
    assert forbidden_imports("from PyQt5 import QtWidgets", "docconverter.core")
    assert forbidden_imports("from docconverter.ui import main_window", "docconverter.core")
    assert forbidden_imports("from ..ui import main_window", "docconverter.core")
    assert forbidden_imports("from ... import ui", "docconverter.core.converters")
    assert not forbidden_imports("from .models import Category", "docconverter.core")
    assert not forbidden_imports("from ..registry import register", "docconverter.core.converters")


def _core_files():
    return sorted(CORE.rglob("*.py"))


def test_core_files_were_found():
    assert len(_core_files()) >= 8


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(CORE)))
def test_core_does_not_import_gui_or_other_layers(path):
    relative = path.relative_to(SRC).with_suffix("")
    package_parts = list(relative.parts[:-1]) if path.name != "__init__.py" else list(relative.parts[:-1])
    package = ".".join(package_parts)
    assert forbidden_imports(path.read_text(encoding="utf-8"), package) == []
