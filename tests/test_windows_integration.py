import winreg

import pytest

from docconverter.platform_integration.windows import (
    ASSOC_BASE_PATH,
    MENU_KEY_NAME,
    ROOT_HKEY,
    WindowsPlatformIntegration,
    get_pythonw_path,
    refresh_explorer,
    show_toast_notification,
)


def test_get_pythonw_path():
    path = get_pythonw_path()
    assert isinstance(path, str)
    assert len(path) > 0


def test_supported_extensions():
    win = WindowsPlatformIntegration()
    exts = win._get_supported_extensions()
    assert ".docx" in exts
    assert ".xlsx" in exts
    assert ".md" in exts
    assert ".json" in exts
    assert ".txt" in exts


def test_refresh_explorer_runs():
    # Should run without error
    refresh_explorer()


def test_show_toast_notification_safe():
    # Should execute gracefully without throwing unhandled exceptions
    show_toast_notification("Test Title", "Test Message")


def test_install_and_uninstall_lifecycle():
    win = WindowsPlatformIntegration()

    # Install context menu
    installed = win.install_context_menu()
    assert installed is True
    assert win.is_menu_installed() is True

    # Verify registry structure for .json
    json_key_path = f"{ASSOC_BASE_PATH}\\.json\\shell\\{MENU_KEY_NAME}"
    with winreg.OpenKey(ROOT_HKEY, json_key_path, 0, winreg.KEY_READ) as key:
        val, _ = winreg.QueryValueEx(key, "MUIVerb")
        assert val == "Convert"
        subcommands, _ = winreg.QueryValueEx(key, "SubCommands")
        assert subcommands == ""

    # Verify command subkey exists
    cmd_key_path = f"{json_key_path}\\shell\\Convert_csv\\command"
    with winreg.OpenKey(ROOT_HKEY, cmd_key_path, 0, winreg.KEY_READ) as key:
        cmd, _ = winreg.QueryValueEx(key, "")
        assert "--to csv" in cmd
        assert "%1" in cmd

    # Uninstall
    uninstalled = win.uninstall_context_menu()
    assert uninstalled is True
    assert win.is_menu_installed() is False

    # Verify key is gone
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(ROOT_HKEY, json_key_path, 0, winreg.KEY_READ)


def test_frozen_exe_command_line():
    import sys
    from unittest.mock import patch

    win = WindowsPlatformIntegration()
    fake_exe = r"C:\Program Files\DocConverter\docconverter.exe"
    with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", fake_exe):
        assert win.install_context_menu() is True
        json_key = f"{ASSOC_BASE_PATH}\\.json\\shell\\{MENU_KEY_NAME}\\shell\\Convert_csv\\command"
        with winreg.OpenKey(ROOT_HKEY, json_key, 0, winreg.KEY_READ) as k:
            cmd, _ = winreg.QueryValueEx(k, "")
            assert cmd == f'"{fake_exe}" "%1" --to csv'
        win.uninstall_context_menu()
