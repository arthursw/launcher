#!/usr/bin/env python3
"""Thin wrapper for the launcher package entry point."""

import sys
import os
from pathlib import Path
from typing import Optional

from launcher import main as _impl

CONFIG_ENV_VAR = _impl.CONFIG_ENV_VAR
DEFAULT_CONFIG_NAME = _impl.DEFAULT_CONFIG_NAME
DEFAULT_PACKAGING_CONFIG = _impl.DEFAULT_PACKAGING_CONFIG
get_gui = _impl.get_gui
init_launcher = _impl.init_launcher
run_with_delayed_gui = _impl.run_with_delayed_gui
run_launcher = _impl.run_launcher
setup_logging = _impl.setup_logging
main = _impl.main


def _unique_paths(paths: list[Path]) -> list[Path]:
    """Return paths without duplicates while preserving order."""
    return _impl._unique_paths(paths)


def _default_config_candidates() -> list[Path]:
    """Return default config locations using this wrapper's file location."""
    candidates = [Path.cwd() / DEFAULT_PACKAGING_CONFIG]

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        executable_dir = executable.parent
        bundle_dir = Path(__file__).resolve().parent
        internal_root = Path(getattr(sys, "_MEIPASS", bundle_dir.parent)).resolve()

        candidates.extend(
            [
                internal_root / DEFAULT_PACKAGING_CONFIG,
                executable_dir / DEFAULT_PACKAGING_CONFIG,
                bundle_dir / DEFAULT_PACKAGING_CONFIG,
            ]
        )
    else:
        repo_root = Path(__file__).resolve().parent
        candidates.append(repo_root / DEFAULT_PACKAGING_CONFIG)

    return _unique_paths(candidates)


def find_config_path(config_path: Optional[Path] = None) -> tuple[Path, list[Path]]:
    """Find the configuration file to use."""
    if config_path is not None:
        return config_path.expanduser().resolve(), []

    env_config = os.environ.get(CONFIG_ENV_VAR)
    if env_config:
        return Path(env_config).expanduser().resolve(), []

    candidates = _default_config_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate, candidates

    return candidates[0], candidates

__all__ = [
    "CONFIG_ENV_VAR",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_PACKAGING_CONFIG",
    "_default_config_candidates",
    "_unique_paths",
    "find_config_path",
    "get_gui",
    "init_launcher",
    "main",
    "run_launcher",
    "run_with_delayed_gui",
    "setup_logging",
]


if __name__ == "__main__":
    sys.exit(main())
