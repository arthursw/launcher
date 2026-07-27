"""Cross-platform launcher icon discovery."""

from __future__ import annotations

import platform
from pathlib import Path
import sys
from typing import Iterable

ICON_FILE_NAMES = ("app.icns", "app.ico", "icon_128x128.png")
ICON_SUFFIXES = frozenset({".icns", ".ico", ".png"})


def platform_icon_names(system: str | None = None) -> tuple[str, ...]:
    """Return icon file names in native preference order."""
    system = system or platform.system()
    if system == "Darwin":
        return ("app.icns", "icon_128x128.png", "app.ico")
    if system == "Windows":
        return ("app.ico", "icon_128x128.png", "app.icns")
    return ("icon_128x128.png", "app.ico", "app.icns")


def find_icons(directories: Iterable[Path], system: str | None = None) -> tuple[Path, ...]:
    """Find supported icons in stable platform preference order."""
    result: list[Path] = []
    seen: set[Path] = set()
    names = platform_icon_names(system)

    for directory in _unique_paths(directories):
        candidates = [directory / name for name in names]
        if directory.is_dir():
            candidates.extend(
                path
                for path in sorted(directory.iterdir())
                if path.suffix.lower() in ICON_SUFFIXES and path.name not in names
            )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
    return tuple(result)


def runtime_icon_paths(config_path: Path) -> tuple[Path, ...]:
    """Return app icon candidates for source and PyInstaller runtime layouts."""
    directories = [config_path.resolve().parent]
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        internal_root = Path(getattr(sys, "_MEIPASS", executable_dir)).resolve()
        directories.extend(
            [
                internal_root / "resources",
                executable_dir / "resources",
                executable_dir / "_internal" / "resources",
            ]
        )
    return find_icons(directories)


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return tuple(result)
