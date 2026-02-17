# LxMonitor

LxMonitor is a desktop system monitor for Linux built with PyQt6 (UI) and C++ engines (via pybind11) for fast metrics collection.

## Features

- Live metrics for CPU, RAM, disks, network, and GPU
- Dynamic cards/tabs for multiple devices (disks, interfaces, GPUs)
- Optional protected metrics unlock flow (system password)
- Python fallback collectors for core metrics when C++ engines are unavailable
- Multi-language UI (15+ languages + system language)
- Theme support: `dark`, `light`, `system`
- Developer console with log streaming and diagnostics copy
- Daily log files in `assets/logs/`

## Tech Stack

- Python 3
- PyQt6
- C++17 engines compiled to `.so` with `pybind11`
- Linux system sources (`/proc`, `/sys`, DRM/hwmon, etc.)

## Project Structure

```text
LxMonitor/
  main.py
  config.json
  assets/
    languages/
    styles/
    icons/
    logs/
  core/
    builder.py
    handlers/
    engines/
    language_handler.py
    themes_handler.py
    console_logic.py
  ui/
    main_window.py
    about.py
    settings.py
    console.py
    toolbar.py
    widgets/
    window/mixins/
```

## Requirements

Install system dependencies (example for Fedora):

```bash
sudo dnf install -y python3 python3-pip gcc-c++
```

Install Python dependencies:

```bash
pip install PyQt6 pybind11
```

Optional tools used for better hardware naming/detection:

```bash
sudo dnf install -y pciutils mesa-demos vulkan-tools
```

## Build C++ Engines

The app auto-builds engines on startup, but you can also build manually:

```bash
python -m lxbinman build --source-dir core/engines --policy prefer_cache
```

Compiled modules are stored in `core/engines/*.so`.

## Run

```bash
python main.py
```

## Configuration

`config.json` supports:

```json
{
  "language": "system",
  "theme": "system"
}
```

Values:

- `language`: `system` or language code from `assets/languages/*.json`
- `theme`: `system`, `dark`, `light`

## Notes on Permissions

Some metrics can require elevated access depending on distro/hardware.
Unlock is available in **Settings** and uses the internal privilege engine.

## Linux Compatibility

LxMonitor targets modern Linux distributions and different desktop environments.

- Preferred path: C++ engines (`core/engines/*.so`) via `pybind11`
- Fallback path: built-in Python collectors for `cpu`, `ram`, `disc`, `net`
- Advanced sensors (GPU power/temps, board rails, etc.) depend on kernel + driver exposure in `/sys`

If ABI mismatch or build issues occur, the app can still run using fallback collectors for the base dashboard.

## Troubleshooting

- Missing engine binary:
  - run `python -m lxbinman build --source-dir core/engines --policy prefer_cache`
- Missing compiler/headers:
  - install `gcc-c++` and `pybind11`
- No GPU metrics:
  - verify `/sys/class/drm/card*` availability and required permissions
- Logs:
  - check `assets/logs/monitor_YYYY-MM-DD.log`

## Status

Beta 1.0.
