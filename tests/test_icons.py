"""Tests for cross-platform runtime icon discovery."""

import sys

from launcher import icons


def test_find_icons_uses_platform_preference_and_includes_fallbacks(tmp_path):
    """Native icons should be preferred without hiding portable fallbacks."""
    ico = tmp_path / "app.ico"
    png = tmp_path / "icon_128x128.png"
    icns = tmp_path / "app.icns"
    ico.write_bytes(b"ico")
    png.write_bytes(b"png")
    icns.write_bytes(b"icns")

    assert icons.find_icons([tmp_path], system="Windows") == (
        ico.resolve(),
        png.resolve(),
        icns.resolve(),
    )
    assert icons.find_icons([tmp_path], system="Darwin") == (
        icns.resolve(),
        png.resolve(),
        ico.resolve(),
    )
    assert icons.find_icons([tmp_path], system="Linux") == (
        png.resolve(),
        ico.resolve(),
        icns.resolve(),
    )


def test_runtime_icon_paths_finds_pyinstaller_resources(tmp_path, monkeypatch):
    """Frozen launchers should find icons in PyInstaller's internal resources."""
    executable_dir = tmp_path / "dist" / "myapp"
    internal_root = executable_dir / "_internal"
    config = internal_root / "packaging" / "launcher" / "application.yml"
    icon = internal_root / "resources" / "app.ico"
    config.parent.mkdir(parents=True)
    icon.parent.mkdir(parents=True)
    config.write_text("name: MyApp\n")
    icon.write_bytes(b"ico")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable_dir / "myapp.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal_root), raising=False)
    monkeypatch.setattr(icons.platform, "system", lambda: "Windows")

    assert icons.runtime_icon_paths(config) == (icon.resolve(),)


def test_runtime_icon_paths_prefers_icons_next_to_explicit_config(tmp_path, monkeypatch):
    """An explicit app config should be able to override a bundled icon."""
    config = tmp_path / "custom" / "application.yml"
    custom_icon = config.parent / "icon_128x128.png"
    bundled_icon = tmp_path / "bundle" / "resources" / "icon_128x128.png"
    config.parent.mkdir()
    bundled_icon.parent.mkdir(parents=True)
    config.write_text("name: MyApp\n")
    custom_icon.write_bytes(b"custom")
    bundled_icon.write_bytes(b"bundled")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bundle" / "myapp"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(icons.platform, "system", lambda: "Linux")

    assert icons.runtime_icon_paths(config) == (
        custom_icon.resolve(),
        bundled_icon.resolve(),
    )
