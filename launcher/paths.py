"""Shared filesystem locations for launcher runtime data."""

from __future__ import annotations

import os
import platform
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
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / safe_name
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / safe_name


def sanitize_state_name(app_name: str) -> str:
    """Sanitize application names before using them in runtime paths."""
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in app_name).strip("._-")
    return safe_name or "launcher"
