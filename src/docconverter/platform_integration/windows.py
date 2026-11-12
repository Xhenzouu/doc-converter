"""Windows Explorer context menu integration using winreg.

Creates a nested 'Convert to ▸' cascading sub-menu under:
HKCU\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell\\DocConverter
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence
import winreg

from ..core.models import ConversionSpec
from ..core.registry import load_builtin_converters, registry
from .base import BasePlatformIntegration

log = logging.getLogger(__name__)

ROOT_HKEY = winreg.HKEY_CURRENT_USER
ASSOC_BASE_PATH = r"Software\Classes\SystemFileAssociations"
MENU_KEY_NAME = "DocConverter"
MENU_LABEL = "Convert"

# Shell Change Notification Constants
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


def get_pythonw_path() -> str:
    """Return the path to pythonw.exe or the current frozen executable."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())

    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        return str(pythonw)
    return str(exe)


def refresh_explorer() -> None:
    """Notify the Windows Shell that file associations have changed."""
    try:
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception as exc:
        log.warning("SHChangeNotify failed: %s", exc)


def delete_registry_tree(root_key: int, sub_key_path: str) -> bool:
    """Recursively delete a Windows Registry key and all of its subkeys."""
    try:
        with winreg.OpenKey(root_key, sub_key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child_name = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_registry_tree(key, child_name)
        winreg.DeleteKey(root_key, sub_key_path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("Error deleting key %s: %s", sub_key_path, exc)
        return False


def show_toast_notification(title: str, message: str) -> None:
    """Display a silent native Windows toast notification to the user."""
    # 1. PowerShell WinRT Toast Notification (standard and reliable on Windows 10 & 11)
    try:
        escaped_title = title.replace("'", "''").replace('"', '`"')
        escaped_msg = message.replace("'", "''").replace('"', '`"')
        ps_cmd = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$nodes = $template.GetElementsByTagName('text'); "
            f"$nodes.Item(0).AppendChild($template.CreateTextNode('{escaped_title}')) | Out-Null; "
            f"$nodes.Item(1).AppendChild($template.CreateTextNode('{escaped_msg}')) | Out-Null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('DocConverter').Show($toast);"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=5,
        )
        return
    except Exception:
        pass

    # 2. Fallback to Windows MessageBox if WinRT is unavailable
    try:
        MB_ICONWARNING = 0x30
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONWARNING)
    except Exception:
        pass


class WindowsPlatformIntegration(BasePlatformIntegration):
    """Windows Explorer shell integration managing the right-click sub-menu."""

    def __init__(self) -> None:
        load_builtin_converters()

    def _get_supported_extensions(self) -> dict[str, list[ConversionSpec]]:
        """Map each supported file extension to its available conversion specs."""
        mapping: dict[str, list[ConversionSpec]] = {}
        for spec in registry.all_specs():
            for ext in spec.src_exts:
                ext_clean = ext.lower()
                mapping.setdefault(ext_clean, []).append(spec)
        return mapping

    def install_context_menu(self) -> bool:
        """Register cascading context menus for all supported file types."""
        pythonw = get_pythonw_path()
        mapping = self._get_supported_extensions()
        success_count = 0

        for ext, specs in mapping.items():
            try:
                # Key path: HKCU\Software\Classes\SystemFileAssociations\<.ext>\shell\DocConverter
                parent_path = f"{ASSOC_BASE_PATH}\\{ext}\\shell\\{MENU_KEY_NAME}"
                with winreg.CreateKey(ROOT_HKEY, parent_path) as parent_key:
                    winreg.SetValueEx(parent_key, "MUIVerb", 0, winreg.REG_SZ, MENU_LABEL)
                    winreg.SetValueEx(parent_key, "SubCommands", 0, winreg.REG_SZ, "")

                # Create sub-commands inside shell\
                shell_path = f"{parent_path}\\shell"
                for spec in specs:
                    format_slug = spec.dst_ext.lstrip(".").lower()
                    verb_name = f"Convert_{format_slug}"
                    item_path = f"{shell_path}\\{verb_name}"

                    # e.g., "Convert to PDF" or "Convert to Markdown"
                    target_name = spec.dst_ext.lstrip(".").upper()
                    if spec.title and " to " in spec.title:
                        target_name = spec.title.split(" to ")[-1].strip()
                    item_label = f"Convert to {target_name}"

                    with winreg.CreateKey(ROOT_HKEY, item_path) as item_key:
                        winreg.SetValueEx(item_key, "MUIVerb", 0, winreg.REG_SZ, item_label)

                    cmd_path = f"{item_path}\\command"
                    if getattr(sys, "frozen", False):
                        cmd_line = f'"{pythonw}" "%1" --to {format_slug}'
                    else:
                        cmd_line = f'"{pythonw}" -m docconverter.cli "%1" --to {format_slug}'
                    with winreg.CreateKey(ROOT_HKEY, cmd_path) as cmd_key:
                        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_line)

                success_count += 1
            except OSError as exc:
                log.warning("Failed to register context menu for '%s': %s", ext, exc)

        refresh_explorer()
        return success_count > 0

    def uninstall_context_menu(self) -> bool:
        """Remove the DocConverter context menu from all registered extensions."""
        mapping = self._get_supported_extensions()
        removed_count = 0

        for ext in mapping:
            parent_path = f"{ASSOC_BASE_PATH}\\{ext}\\shell\\{MENU_KEY_NAME}"
            if delete_registry_tree(ROOT_HKEY, parent_path):
                removed_count += 1

        refresh_explorer()
        return removed_count > 0

    def is_menu_installed(self) -> bool:
        """Check if at least one extension currently has the DocConverter menu registered."""
        mapping = self._get_supported_extensions()
        for ext in mapping:
            parent_path = f"{ASSOC_BASE_PATH}\\{ext}\\shell\\{MENU_KEY_NAME}"
            try:
                with winreg.OpenKey(ROOT_HKEY, parent_path, 0, winreg.KEY_READ):
                    return True
            except FileNotFoundError:
                continue
            except OSError:
                continue
        return False
