"""Main application entry point.

Handles menu installation from the CLI, or launches the GUI application
when invoked with no arguments.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .platform_integration.windows import WindowsPlatformIntegration


def launch_gui() -> int:
    """Launch the PySide6 desktop GUI."""
    print("Starting Doc Converter desktop GUI...")
    # Full PySide6 GUI to be initialized in Batch 4/5.
    try:
        from .ui.main_window import MainWindow  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        print(
            "Notice: Full GUI will be integrated in Batch 4/5.\n"
            "Use '--install-menu' to register the Windows Explorer context sub-menu,\n"
            "or use 'python -m docconverter.cli <file> --to <format>' for conversions."
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Application entry point."""
    parser = argparse.ArgumentParser(
        prog="docconverter-app",
        description="Doc Converter: Desktop Application & Shell Integration",
    )
    parser.add_argument(
        "--install-menu",
        action="store_true",
        help="Register the Windows Explorer right-click 'Convert to' sub-menu and exit.",
    )
    parser.add_argument(
        "--uninstall-menu",
        action="store_true",
        help="Remove the Windows Explorer right-click sub-menu and exit.",
    )

    args, unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.install_menu:
        win = WindowsPlatformIntegration()
        if win.install_context_menu():
            print("Windows right-click 'Convert to' sub-menu successfully registered.")
            return 0
        else:
            print("Failed to register Windows context menu.", file=sys.stderr)
            return 1

    if args.uninstall_menu:
        win = WindowsPlatformIntegration()
        if win.uninstall_context_menu():
            print("Windows right-click sub-menu successfully removed.")
            return 0
        else:
            print("Failed to remove Windows context menu.", file=sys.stderr)
            return 1

    return launch_gui()


if __name__ == "__main__":
    sys.exit(main())
