"""Tests for unified runtime installation roots."""

import pytest
import yaml

from launcher.config import AppConfig, EntryPointConfig
from launcher.installation import (
    INSTALL_MARKER_NAME,
    InstallationError,
    InstallationRootKind,
    default_installation_root,
    initialize_installation_root,
    inspect_installation_root,
    replace_installation_root,
)
from launcher.paths import get_default_install_dir


def _config(path: str = ".") -> AppConfig:
    return AppConfig(
        name="My App",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        repository="https://github.com/example/app.git",
        path=path,
    )


def test_default_install_directories_follow_platform_data_conventions(monkeypatch, tmp_path):
    monkeypatch.setattr("launcher.paths.Path.home", lambda: tmp_path)

    monkeypatch.setattr("launcher.paths.platform.system", lambda: "Darwin")
    assert get_default_install_dir("My App") == tmp_path / "Library" / "Application Support" / "My_App"

    monkeypatch.setattr("launcher.paths.platform.system", lambda: "Windows")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert get_default_install_dir("My App") == tmp_path / "AppData" / "Local" / "My_App"

    monkeypatch.setattr("launcher.paths.platform.system", lambda: "Linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert get_default_install_dir("My App") == tmp_path / ".local" / "share" / "My_App"


def test_configured_installation_default_resolves_relative_to_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr("launcher.config.get_default_install_dir", lambda _name: tmp_path / "app-data")

    assert default_installation_root(_config()) == (tmp_path / "app-data").resolve()
    assert default_installation_root(_config("custom")) == (tmp_path / "app-data" / "custom").resolve()
    assert default_installation_root(_config(str(tmp_path / "absolute"))) == (tmp_path / "absolute").resolve()


def test_installation_marker_distinguishes_owned_and_unmanaged_roots(tmp_path):
    root = tmp_path / "app"
    assert inspect_installation_root(root, "My App").kind == InstallationRootKind.NEW

    initialize_installation_root(root, "My App")
    assert inspect_installation_root(root, "My App").kind == InstallationRootKind.EXISTING
    assert yaml.safe_load((root / INSTALL_MARKER_NAME).read_text())["application"] == "My App"

    assert inspect_installation_root(root, "Other App").kind == InstallationRootKind.CONFLICT

    unmanaged = tmp_path / "unmanaged"
    unmanaged.mkdir()
    (unmanaged / "notes.txt").write_text("keep")
    assert inspect_installation_root(unmanaged, "My App").kind == InstallationRootKind.CONFLICT


def test_replace_removes_only_launcher_owned_runtime_contents(tmp_path):
    root = tmp_path / "app"
    initialize_installation_root(root, "My App")
    (root / "sources" / "old.py").write_text("old")
    (root / "wetlands" / "environment").mkdir()
    (root / "launcher-state.yml").write_text("installation_root: app")
    (root / "keep.txt").write_text("keep")

    replace_installation_root(root, "My App")

    assert list((root / "sources").iterdir()) == []
    assert list((root / "wetlands").iterdir()) == []
    assert (root / INSTALL_MARKER_NAME).is_file()
    assert (root / "launcher-state.yml").is_file()
    assert (root / "keep.txt").read_text() == "keep"


def test_replace_rejects_unmanaged_directory(tmp_path):
    root = tmp_path / "unmanaged"
    root.mkdir()
    (root / "file.txt").write_text("do not delete")

    with pytest.raises(InstallationError):
        replace_installation_root(root, "My App")

    assert (root / "file.txt").is_file()
