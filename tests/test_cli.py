from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docconverter.cli import handle_conversion, main, resolve_converter


@pytest.fixture
def json_sample(tmp_path):
    p = tmp_path / "sample.json"
    p.write_text('{"user": {"name": "Test"}}', encoding="utf-8")
    return p


def test_resolve_converter(json_sample):
    spec = resolve_converter(json_sample, "csv")
    assert spec is not None
    assert spec.id == "json_to_csv"

    # Also resolve with dot
    spec_dot = resolve_converter(json_sample, ".csv")
    assert spec_dot is not None
    assert spec_dot.id == "json_to_csv"


def test_resolve_converter_unknown(json_sample):
    assert resolve_converter(json_sample, "mp4") is None


def test_cli_successful_conversion(json_sample, capsys):
    code = main([str(json_sample), "--to", "csv"])
    assert code == 0
    captured = capsys.readouterr()
    assert "sample.csv" in captured.out
    assert Path(captured.out.strip()).exists()


def test_cli_missing_source_file(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.json"
    with patch("docconverter.cli.show_toast_notification") as mock_toast:
        code = main([str(missing), "--to", "csv"])
        assert code == 1
        mock_toast.assert_called_once()
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()


def test_cli_unsupported_format(json_sample, capsys):
    with patch("docconverter.cli.show_toast_notification") as mock_toast:
        code = main([str(json_sample), "--to", "mp3"])
        assert code == 1
        mock_toast.assert_called_once()
        captured = capsys.readouterr()
        assert "no converter found" in captured.err.lower()


def test_cli_missing_to_flag(json_sample, capsys):
    code = main([str(json_sample)])
    assert code == 1
    captured = capsys.readouterr()
    assert "please specify a target format" in captured.err.lower()


def test_cli_install_menu_flag():
    with patch("docconverter.cli.WindowsPlatformIntegration.install_context_menu", return_value=True) as mock_install:
        code = main(["--install-menu"])
        assert code == 0
        mock_install.assert_called_once()


def test_cli_uninstall_menu_flag():
    with patch("docconverter.cli.WindowsPlatformIntegration.uninstall_context_menu", return_value=True) as mock_uninstall:
        code = main(["--uninstall-menu"])
        assert code == 0
        mock_uninstall.assert_called_once()


def test_cli_conversion_failure_notifies(tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{bad json")
    with patch("docconverter.cli.show_toast_notification") as mock_toast:
        code = main([str(bad_json), "--to", "csv"])
        assert code == 1
        mock_toast.assert_called_once()


def test_app_install_and_uninstall_flags():
    from docconverter.app import main as app_main

    with patch("docconverter.platform_integration.windows.WindowsPlatformIntegration.install_context_menu", return_value=True) as mock_inst:
        assert app_main(["--install-menu"]) == 0
        mock_inst.assert_called_once()

    with patch("docconverter.platform_integration.windows.WindowsPlatformIntegration.uninstall_context_menu", return_value=True) as mock_uninst:
        assert app_main(["--uninstall-menu"]) == 0
        mock_uninst.assert_called_once()


def test_app_launch_gui_stub(capsys):
    from docconverter.app import main as app_main

    code = app_main([])
    assert code == 0
    captured = capsys.readouterr()
    assert "Doc Converter" in captured.out
