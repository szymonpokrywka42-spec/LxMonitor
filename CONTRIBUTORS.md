# Contributors

## Core Contributors

- Szymon Pokrywka - Project creator, architecture, UI and engine integration
- Codex (GPT-5) - Pair programming support, refactors, diagnostics, localization and theming improvements

## How to Add Yourself

Add a new line in the same format:

- Full Name or Handle - Main contribution areas

## Community Rule

This is a friendly project: everyone who adds a meaningful contribution gets credited.
Each contributor who adds a real \"brick\" to the project is added to the creators section in the About dialog.

## Run Project

### 1. VSCode

1. Open project folder in VSCode.
2. Open terminal in project root.
3. Install dependencies:
   - `pip install PyQt6 pybind11`
4. Run:
   - `python main.py`

### 2. Linux .desktop

1. Create file `~/.local/share/applications/lxmonitor.desktop` with content:
   ```ini
   [Desktop Entry]
   Name=LxMonitor
   Comment=Linux system monitor
   Exec=python /path/to/LxMonitor/main.py
   Path=/path/to/LxMonitor
   Icon=/path/to/LxMonitor/assets/icons/icon.png
   Terminal=false
   Type=Application
   Categories=System;Monitor;
   ```
2. Make it executable:
   - `chmod +x ~/.local/share/applications/lxmonitor.desktop`
3. Launch from app menu (or desktop environment search).

## Contribution Scope (current)

- UI architecture split into mixins and widgets
- Engine discovery/loading and runtime monitoring
- Privileged metrics unlock flow
- Multi-language and theme system improvements
- Logging and diagnostics workflow
