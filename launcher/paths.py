"""Shared filesystem locations for launcher runtime data."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

RUNTIME_DATA_DIR_ENV_VAR = "LAUNCHER_STATE_DIR"


def get_runtime_data_dir(app_name: str) -> Path:
    """Return the per-app runtime data directory, honoring test/user overrides."""
    override = os.environ.get(RUNTIME_DATA_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser() / sanitize_state_name(app_name)
    return get_default_state_dir(app_name)


def get_default_state_dir(app_name: str) -> Path:
    """Return the OS-specific runtime data directory for an application."""
    safe_name = sanitize_state_name(app_name)
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / safe_name
    if system == "Windows":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        return base / safe_name
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / safe_name


def get_default_install_dir(app_name: str) -> Path:
    """Return the OS-specific root for mutable application runtime data."""
    safe_name = sanitize_state_name(app_name)
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / safe_name
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / safe_name
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / safe_name


def get_portable_state_dir(app_name: str) -> Path:
    """Return the state sidecar path beside the executable or macOS app bundle."""
    executable = Path(sys.executable).resolve()
    container = executable.parent
    if platform.system() == "Darwin":
        for parent in executable.parents:
            if parent.suffix.lower() == ".app":
                container = parent.parent
                break
    return container / f"{sanitize_state_name(app_name)}-launcher-data"


def sanitize_state_name(app_name: str) -> str:
    """Sanitize application names before using them in runtime paths."""
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in app_name).strip("._-")
    return safe_name or "launcher"
