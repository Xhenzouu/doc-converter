"""Command-line interface (CLI) for Doc Converter.

Runs completely headless for batch conversions, shell script automation,
and Windows Explorer context menu invocations.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence

from .core.errors import ConversionError
from .core.models import ConversionJob, ConversionSpec
from .core.registry import load_builtin_converters, registry
from .platform_integration.windows import (
    WindowsPlatformIntegration,
    show_toast_notification,
)


def resolve_converter(src_path: Path, target_format: str) -> Optional[ConversionSpec]:
    """Find the registered converter matching the input file and target format."""
    load_builtin_converters()
    target = target_format.strip().lower()
    target_ext = target if target.startswith(".") else f".{target}"

    # Format aliases
    alias_map = {
        "markdown": ".md",
        "excel": ".xlsx",
        "word": ".docx",
        "jpeg": ".jpg",
        "jpg": ".jpg",
        "tif": ".tiff",
        "text": ".txt",
    }
    if target in alias_map:
        target_ext = alias_map[target]

    specs = registry.specs_for_path(src_path)

    # 1. Match by dst_ext
    for spec in specs:
        if spec.dst_ext.lower() == target_ext:
            return spec

    # 2. Match by tool id suffix (e.g. xlsx_to_csv matching "csv")
    for spec in specs:
        clean_target = target.lstrip(".")
        if spec.id.lower().endswith(f"_to_{clean_target}"):
            return spec

    return None


def handle_conversion(
    file_path: Path,
    target_format: str,
    output_dir: Optional[Path] = None,
    overwrite: bool = False,
) -> int:
    """Execute a single headless conversion job."""
    if not file_path.exists():
        err_msg = f"Source file not found: '{file_path}'"
        print(err_msg, file=sys.stderr)
        show_toast_notification("Doc Converter Error", err_msg)
        return 1

    spec = resolve_converter(file_path, target_format)
    if not spec:
        err_msg = (
            f"No converter found from '{file_path.suffix}' to '{target_format}'. "
            f"Supported extensions for this file: "
            f"{[s.dst_ext for s in registry.specs_for_path(file_path)]}"
        )
        print(err_msg, file=sys.stderr)
        show_toast_notification("Doc Converter Error", err_msg)
        return 1

    job = ConversionJob(
        src=file_path,
        tool_id=spec.id,
        output_dir=output_dir,
        overwrite=overwrite,
    )

    result = registry.run(job)

    if not result.ok:
        err_msg = result.error or "Conversion failed unexpectedly."
        print(f"Error converting '{file_path.name}': {err_msg}", file=sys.stderr)
        show_toast_notification("Conversion Failed", f"{file_path.name}: {err_msg}")
        return 1

    # Print output paths to stdout
    for output in result.outputs:
        print(str(output))

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="docconverter",
        description="Doc Converter: headless document and text conversion engine.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Path to the source file to convert.",
    )
    parser.add_argument(
        "-t",
        "--to",
        dest="target_format",
        help="Target format (e.g. pdf, csv, json, md, html).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save converted files (default: beside source file).",
    )
    parser.add_argument(
        "-f",
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files instead of generating unique names.",
    )
    parser.add_argument(
        "--install-menu",
        action="store_true",
        help="Register the Windows Explorer right-click 'Convert to' sub-menu.",
    )
    parser.add_argument(
        "--uninstall-menu",
        action="store_true",
        help="Remove the Windows Explorer right-click sub-menu.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    load_builtin_converters()
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.install_menu:
        win = WindowsPlatformIntegration()
        if win.install_context_menu():
            print("Windows right-click 'Convert to' sub-menu successfully installed.")
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
            print("Failed to remove Windows context menu or none was found.", file=sys.stderr)
            return 1

    if args.file and args.target_format:
        return handle_conversion(
            file_path=args.file,
            target_format=args.target_format,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
        )

    if args.file and not args.target_format:
        available = [s.dst_ext.lstrip(".") for s in registry.specs_for_path(args.file)]
        if available:
            print(f"Please specify a target format with --to. Available for {args.file.name}: {', '.join(available)}", file=sys.stderr)
        else:
            print(f"No converters available for '{args.file.name}'.", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
