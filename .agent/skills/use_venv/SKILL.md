---
name: use-venv
description: Prefer the repository .venv Python interpreter for Python commands, tests, scripts, package tooling, and AI coding workflows when .venv exists.
---

# Use Repository Virtual Environment

When running Python commands in this repository, use the local virtual environment if it exists.

## PowerShell

Before Python commands, resolve the interpreter:

```powershell
$py = if (Test-Path .\.venv\Scripts\python.exe) { ".\.venv\Scripts\python.exe" } else { "python" }
```

Then run commands through that interpreter:

```powershell
& $py -m py_compile ok\util\logger.py
& $py -m pytest tests
& $py .\.agents\skills\compile_i18n\add_translation.py --help
& $py -m pip install -r requirements.txt
```

Do not call global `python`, `pip`, or `pytest` directly when `.venv` exists. Use `& $py`, `& $py -m pip`, and `& $py -m pytest` instead.
