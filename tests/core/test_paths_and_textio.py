import os
import stat
import sys

import pytest

from docconverter.core.errors import ConversionError
from docconverter.core.paths import resolve_output_path, safe_filename_part
from docconverter.core.textio import (
    atomic_write_bytes,
    atomic_write_text,
    decode_bytes,
    read_text_file,
)

# --- safe_filename_part ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Sheet1", "Sheet1"),
        ("Q1/Q2", "Q1_Q2"),
        ('a<b>c:d"e|f?g*h', "a_b_c_d_e_f_g_h"),
        ("back\\slash", "back_slash"),
        ("  padded.  ", "padded"),
        ("tab\tinside", "tab_inside"),
        ("", "untitled"),
        ("...", "untitled"),
        ("日本語 シート", "日本語 シート"),
    ],
)
def test_safe_filename_part(raw, expected):
    assert safe_filename_part(raw) == expected


def test_safe_filename_part_truncates():
    assert len(safe_filename_part("x" * 500)) == 80


def test_safe_filename_part_custom_fallback():
    assert safe_filename_part("  ", fallback="sheet") == "sheet"
    assert safe_filename_part("...", fallback="sheet") == "sheet"


# --- resolve_output_path ---------------------------------------------------------


def test_defaults_to_source_folder(tmp_path):
    src = tmp_path / "report.docx"
    assert resolve_output_path(src, ".pdf") == tmp_path / "report.pdf"


def test_extension_is_normalized(tmp_path):
    assert resolve_output_path(tmp_path / "a.md", "HTML").name == "a.html"


def test_suffix_is_inserted_before_extension(tmp_path):
    assert resolve_output_path(tmp_path / "data.xlsx", ".csv", suffix="_Sheet1").name == (
        "data_Sheet1.csv"
    )


def test_output_dir_is_created(tmp_path):
    target = tmp_path / "a" / "b"
    path = resolve_output_path(tmp_path / "x.md", ".html", output_dir=target)
    assert path == target / "x.html" and target.is_dir()


def test_collisions_are_numbered(tmp_path):
    (tmp_path / "r.pdf").touch()
    assert resolve_output_path(tmp_path / "r.docx", ".pdf").name == "r (1).pdf"
    (tmp_path / "r (1).pdf").touch()
    assert resolve_output_path(tmp_path / "r.docx", ".pdf").name == "r (2).pdf"


def test_overwrite_reuses_existing_name(tmp_path):
    (tmp_path / "r.pdf").touch()
    assert resolve_output_path(tmp_path / "r.docx", ".pdf", overwrite=True).name == "r.pdf"


def test_never_returns_the_source_file_even_with_overwrite(tmp_path):
    src = tmp_path / "data.json"
    src.touch()
    assert resolve_output_path(src, ".json", overwrite=True).name == "data (1).json"


def test_taken_paths_are_skipped_even_with_overwrite(tmp_path):
    first = resolve_output_path(tmp_path / "d.xlsx", ".csv", suffix="_S")
    second = resolve_output_path(tmp_path / "d.xlsx", ".csv", suffix="_S", taken=[first])
    third = resolve_output_path(
        tmp_path / "d.xlsx", ".csv", suffix="_S", taken=[first, second], overwrite=True
    )
    assert [p.name for p in (first, second, third)] == ["d_S.csv", "d_S (1).csv", "d_S (2).csv"]


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive file systems only")
def test_taken_comparison_ignores_case_on_windows(tmp_path):
    taken = [tmp_path / "A_S.csv"]
    assert resolve_output_path(tmp_path / "a.xlsx", ".csv", suffix="_S", taken=taken).name == (
        "a_S (1).csv"
    )


def test_gives_up_with_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr("docconverter.core.paths._MAX_COLLISION_INDEX", 2)
    for name in ("r.pdf", "r (1).pdf", "r (2).pdf"):
        (tmp_path / name).touch()
    with pytest.raises(ConversionError, match="free output file name"):
        resolve_output_path(tmp_path / "r.docx", ".pdf")


# --- decode_bytes / read_text_file -----------------------------------------------


def test_decode_utf8():
    decoded = decode_bytes("héllo ☕".encode("utf-8"))
    assert (decoded.text, decoded.encoding, decoded.guessed) == ("héllo ☕", "utf-8", False)


def test_decode_utf8_bom_is_removed():
    assert decode_bytes(b"\xef\xbb\xbfhi").text == "hi"


@pytest.mark.parametrize(
    "data",
    [
        b"\xff\xfe" + "hi ☕".encode("utf-16-le"),  # little-endian BOM
        b"\xfe\xff" + "hi ☕".encode("utf-16-be"),  # big-endian BOM
    ],
    ids=["little-endian", "big-endian"],
)
def test_decode_utf16_with_bom(data):
    decoded = decode_bytes(data)
    assert decoded.text == "hi ☕" and decoded.encoding == "utf-16" and not decoded.guessed


def test_decode_utf32_is_not_mistaken_for_utf16():
    decoded = decode_bytes("hi".encode("utf-32"))
    assert decoded.text == "hi" and decoded.encoding == "utf-32"


def test_decode_falls_back_to_cp1252_and_flags_guess():
    decoded = decode_bytes(b"caf\xe9 \x93quoted\x94")
    assert decoded.text == "café “quoted”"
    assert decoded.encoding == "cp1252" and decoded.guessed


def test_decode_last_resort_latin1():
    decoded = decode_bytes(b"x\x81y")  # 0x81 is undefined in cp1252
    assert decoded.encoding == "latin-1" and decoded.guessed and decoded.text == "x\x81y"


def test_decode_rejects_binary():
    with pytest.raises(ConversionError, match="text file"):
        decode_bytes(b"PK\x03\x04\x00\x00binary")


def test_nul_after_sniff_window_is_not_flagged():
    assert decode_bytes(b"a" * 9000 + b"\x00").text.startswith("a")


def test_read_text_file(tmp_path):
    path = tmp_path / "t.txt"
    path.write_bytes("ok ☕".encode("utf-8"))
    assert read_text_file(path).text == "ok ☕"


# --- atomic writes ---------------------------------------------------------------


def test_atomic_write_creates_and_replaces(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "one")
    atomic_write_text(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]  # no temp leftovers


def test_atomic_write_preserves_newlines_exactly(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"  # no \r\n translation on Windows


def test_atomic_write_encoding(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "é", encoding="utf-16")
    assert target.read_bytes().decode("utf-16") == "é"


def test_atomic_write_failure_leaves_original_and_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    target.write_text("original")

    def boom(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk on fire"):
        atomic_write_bytes(target, b"new")
    assert target.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_atomic_write_respects_umask(tmp_path):
    old = os.umask(0o022)
    try:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "x")
    finally:
        os.umask(old)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
