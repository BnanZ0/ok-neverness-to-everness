# Installation

## System requirements

- Operating system: Windows.
- Game resolution: 1920×1080 or higher; 16:9 aspect ratio only.
- Game language: Simplified Chinese or English.

## Use the installer

The installer is recommended for most users. It is simple to use and supports automatic updates.

1. Open [GitHub Releases](https://github.com/BnanZ0/ok-nte/releases).
2. Download the latest `ok-nte-win32-Global-setup.exe` file.
3. Double-click the installer and follow the prompts.

## Run from source

Running from source is intended for contributors, modifications, and debugging.

```bash
git clone https://github.com/BnanZ0/ok-nte.git
cd ok-nte
uv sync
python main.py
```

After updating the repository, run `uv sync` again to keep dependencies current. See [Running from source](../../development/running-from-source.md) for development verification commands.
