# LxBinMan

`LxBinMan` manages binary engines with a fast hybrid strategy:

1. prebuilt binaries (optional),
2. ABI-specific cache,
3. local fallback build from `*.cpp` (pybind11 + g++).
4. automatic prebuilt backup after successful build/cache hit.

It also provides a unified feedback/logging bus and script-duty runner.

## Quick Start

```python
from lxbinman import feedback, builder

feedback.enable_console(True)
feedback.set_file_sink("./logs/lxbinman.log")

engines = builder.build_all(source_dir="core/engines")
# engines["cpu"].get_usage()
```

## Fast Boot (recommended for apps)

```python
from lxbinman import builder

# Fast startup path for desktop apps:
# - prefers cache
# - compile-only for engine prep
# - auto-saves prebuilt backup by ABI key
builder.fast_boot_build_all(
    source_dir="core/engines",
    output_dir="core/engines",
)
```

## Toolchain Snapshot

```python
from lxbinman import builder

snap = builder.snapshot_toolchain(source_dir="core/engines")
print(snap["changed"])  # True if Python/compiler/runtime changed
```

## Heavy vs Script Duties

```python
from lxbinman import feedback, builder

result = builder.run_duties(
    heavy_source_dir="core/engines",   # C++ heavy duties
    script_source_dir="core/scripts",  # .py/.js script duties
    policy="prefer_prebuilt",
)
```

## Load Policies

- `prefer_prebuilt` (default): prebuilt -> cache -> build
- `prefer_cache`: cache -> prebuilt -> build
- `build_only`: always build
- `prebuilt_only`: never build

## Engine Config (`engines.json`)

Optional per-engine overrides in `source_dir/engines.json`:

```json
{
  "gpu_nvidia": {
    "extra_link_args": ["-lnvidia-ml"],
    "policy": "prefer_prebuilt"
  },
  "cpu": {
    "extra_compile_args": ["-O3"]
  }
}
```

## Healthcheck

```python
from lxbinman import healthcheck

report = healthcheck(source_dir="core/engines")
print(report["ok"])
```

## Cache Maintenance

```python
from lxbinman import builder

builder.prune_cache(source_dir="core/engines", max_versions=3, max_age_days=30)
report = builder.clean_binaries(
    source_dir="core/engines",
    profile="release",               # dev | ci | release
    mode="deep",                    # light | standard | deep
    remove_orphans=True,
    exclude=["core/engines/keep.so"],
    dry_run=False,
)
print(report["bytes_freed"])
```

Cleaner report includes:
- removed/missing/skipped paths
- estimated reclaimed bytes (`bytes_freed`)
- mode and dry-run state

## Prebuilt Manifest with SHA256 (optional)

`assets/binaries/<cache-key>/manifest.json`:

```json
{
  "python_version": "3.13",
  "python_soabi": "cpython-313-x86_64-linux-gnu",
  "system": "linux",
  "machine": "x86_64",
  "hashes": {
    "cpu.cpython-313-x86_64-linux-gnu.so": "<sha256>",
    "ram.cpython-313-x86_64-linux-gnu.so": "<sha256>"
  }
}
```

If hash data exists, prebuilt files are verified before use.

## CLI

```bash
python -m lxbinman healthcheck --source-dir core/engines
python -m lxbinman build --source-dir core/engines --policy prefer_prebuilt
python -m lxbinman fast-build --source-dir core/engines --output-dir core/engines
python -m lxbinman toolchain --source-dir core/engines
python -m lxbinman prune --source-dir core/engines
python -m lxbinman clean --source-dir core/engines --dry-run
python -m lxbinman clean --source-dir core/engines --profile release
python -m lxbinman clean --source-dir core/engines --mode deep --pycache --build-artifacts
```
