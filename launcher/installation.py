"""Installation-root ownership and lifecycle helpers."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from .config import AppConfig

INSTALL_MARKER_NAME = ".launcher-install.yml"
INSTALL_MARKER_SCHEMA_VERSION = 1
SOURCES_DIR_NAME = "sources"
WETLANDS_DIR_NAME = "wetlands"
STATE_FILE_NAME = "launcher-state.yml"


class InstallationError(Exception):
    """Raised when an installation root is unsafe or inaccessible."""


class InstallationRootKind(Enum):
    """Classification of a proposed installation root."""

    NEW = "new"
    EXISTING = "existing"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class InstallationRootInspection:
    """Result of inspecting a proposed installation root."""

    kind: InstallationRootKind
    message: str = ""


def default_installation_root(config: AppConfig) -> Path:
    """Resolve the developer-provided default installation root."""
    return config.installation_root


def inspect_installation_root(root: Path, app_name: str) -> InstallationRootInspection:
    """Classify a root without changing it."""
    root = root.expanduser().resolve()
    if not root.exists():
        return InstallationRootInspection(InstallationRootKind.NEW)
    if not root.is_dir():
        return InstallationRootInspection(
            InstallationRootKind.CONFLICT,
            f"Installation destination is not a directory: {root}",
        )

    marker_path = root / INSTALL_MARKER_NAME
    if marker_path.exists():
        try:
            marker = yaml.safe_load(marker_path.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            return InstallationRootInspection(
                InstallationRootKind.CONFLICT,
                f"Installation marker cannot be read: {exc}",
            )
        if (
            marker.get("schema_version") == INSTALL_MARKER_SCHEMA_VERSION
            and marker.get("application") == app_name
        ):
            return InstallationRootInspection(InstallationRootKind.EXISTING)
        return InstallationRootInspection(
            InstallationRootKind.CONFLICT,
            "The destination belongs to a different or unsupported Launcher installation.",
        )

    ignored_names = {STATE_FILE_NAME}
    try:
        has_unmanaged_contents = any(item.name not in ignored_names for item in root.iterdir())
    except OSError as exc:
        return InstallationRootInspection(
            InstallationRootKind.CONFLICT,
            f"Installation destination cannot be inspected: {exc}",
        )
    if has_unmanaged_contents:
        return InstallationRootInspection(
            InstallationRootKind.CONFLICT,
            "The destination is not empty and is not a Launcher-managed installation.",
        )
    return InstallationRootInspection(InstallationRootKind.NEW)


def initialize_installation_root(root: Path, app_name: str) -> None:
    """Create a launcher-owned runtime layout and marker."""
    root = root.expanduser().resolve()
    temporary = root / f"{INSTALL_MARKER_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / SOURCES_DIR_NAME).mkdir(exist_ok=True)
        (root / WETLANDS_DIR_NAME).mkdir(exist_ok=True)
        marker_path = root / INSTALL_MARKER_NAME
        temporary.write_text(
            yaml.safe_dump(
                {
                    "schema_version": INSTALL_MARKER_SCHEMA_VERSION,
                    "application": app_name,
                },
                sort_keys=False,
            )
        )
        temporary.replace(marker_path)
    except OSError as exc:
        raise InstallationError(f"Cannot initialize installation destination {root}: {exc}") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def replace_installation_root(root: Path, app_name: str) -> None:
    """Delete only launcher-owned runtime contents, then recreate the layout."""
    inspection = inspect_installation_root(root, app_name)
    if inspection.kind != InstallationRootKind.EXISTING:
        raise InstallationError(inspection.message or f"Not a Launcher installation: {root}")
    try:
        for child in (root / SOURCES_DIR_NAME, root / WETLANDS_DIR_NAME):
            if child.exists():
                shutil.rmtree(child)
        marker = root / INSTALL_MARKER_NAME
        if marker.exists():
            marker.unlink()
    except OSError as exc:
        raise InstallationError(f"Cannot replace installation at {root}: {exc}") from exc
    initialize_installation_root(root, app_name)
