# Doc Converter

[![CI](https://github.com/Xhenzouu/doc-converter/actions/workflows/build.yml/badge.svg)](https://github.com/Xhenzouu/doc-converter/actions/workflows/build.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-290%20passing-brightgreen?logo=pytest&logoColor=white)](#development)

A native Windows file converter with right-click context menu integration. Convert documents, images, and data files instantly, without opening an app or installing anything extra.

## Features

- **Right-click menu integration.** Convert a file straight from File Explorer. The context-menu entries install to `HKCU`, so no administrator rights are required.
- **Standalone `.exe`.** No Python installation is needed on the target machine.
- **290 passing unit tests.** The full suite runs with `pytest` and covers every conversion in the matrix.
- **Bundled Pandoc.** The executable ships with `pandoc.exe`, so users do not have to install Pandoc themselves.
- **Native Windows notifications.** Success and error popups use `MessageBoxW` through `ctypes`, with no GUI framework dependency.

## Supported Conversions

| Source | Target | Notes |
|--------|--------|-------|
| TXT | PDF | |
| DOCX | PDF | |
| DOCX | Markdown | |
| PDF | Word (`.docx`) | |
| PDF | Text (`.txt`) | |
| XLSX | CSV | One file per sheet |
| XLSX | JSON | |
| JSON | CSV | Nested keys are flattened with dotted notation (e.g. `user.address.city`) |
| YAML | JSON | |
| Markdown | HTML | |
| Images (JPG, JPEG, PNG, WebP, BMP, TIFF, JFIF) | Any image format | Convert between any of the listed formats |

## Installation

### Option A: Download the executable

1. Go to the [Releases](https://github.com/Xhenzouu/doc-converter/releases) page.
2. Download the latest `.exe`.
3. Install the right-click menu from PowerShell, in the folder where you saved the file:

   ```powershell
   .\docconverter.exe --install-menu
   ```

Python and Pandoc are not required. The context-menu entries are written to `HKCU`, so no administrator prompt appears.

### Option B: Install from source

Requires Python 3.10 or newer.

```bash
git clone https://github.com/Xhenzouu/doc-converter.git
cd doc-converter
pip install -r requirements.txt
```

When running from source, `pypandoc` uses a Pandoc installation on your `PATH`. The bundled `pandoc.exe` is only used by the frozen executable.

## Architecture

The core engine is pure Python with zero Qt dependencies, and an architecture test enforces this. The CLI and the Windows right-click integration are thin layers over the same engine, so every entry point behaves identically.

```
  Right-click menu (winreg, HKCU)          Command line
              \                               /
               \                             /
                v                           v
              +------------------------------+
              |         Core Engine          |
              |  (pure Python, no Qt)        |
              |  format detection + routing  |
              +------------------------------+
                  |        |        |
                  v        v        v
           +---------+ +---------+ +--------------+
           | Images  | | Data    | | Documents    |
           | Pillow  | | openpyxl| | pypdf, fpdf2 |
           |         | | PyYAML  | | python-docx  |
           |         | |         | | mammoth      |
           |         | |         | | markdownify  |
           |         | |         | | markdown-it  |
           |         | |         | | pypandoc     |
           +---------+ +---------+ +--------------+
                                          |
                                          v
                              pandoc.exe (bundled when frozen)

  Result / error  ->  Native Windows popup (ctypes MessageBoxW)
```

When the app runs as a frozen `.exe`, it points `pypandoc` at the bundled `pandoc.exe`, so document conversions work on a machine with no Pandoc installed.

## Development

Run the test suite:

```bash
pytest
```

GitHub Actions runs the full suite on `windows-latest` on every push.

Build the standalone executable with PyInstaller:

```bash
pip install pyinstaller
pyinstaller packaging/pyinstaller/windows.spec --noconfirm
```

The built `.exe` is written to `dist/`.

## Roadmap

- [ ] Graphical interface for drag-and-drop conversion
- [ ] Watch mode that converts files automatically as they appear in a folder
- [ ] Cloud uploads (send converted files directly to a cloud storage provider)
- [ ] PDF merge and split

## License

Released under the [MIT License](LICENSE).