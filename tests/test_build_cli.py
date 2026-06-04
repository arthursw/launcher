"""Tests for launcher build planning."""

from pathlib import Path

from launcher import build_cli


def write_config(root: Path) -> Path:
    config = root / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "main: main.py",
                'path: "."',
                "auto_update: true",
                "configuration: pyproject.toml",
            ]
        )
    )
    return config


def test_build_plan_uses_default_app_repo_config(tmp_path, monkeypatch):
    """Build planning should use packaging/launcher/application.yml by default."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Linux")
    config = write_config(tmp_path)
    icon = config.parent / "icon_128x128.png"
    icon.write_bytes(b"png")

    plan = build_cli.create_build_plan()

    assert plan.config_path == config.resolve()
    assert plan.output_dir == tmp_path / "dist" / "launcher"
    assert plan.spec_path == tmp_path / "dist" / "launcher" / "build" / "launcher.spec"
    assert plan.entry_path == tmp_path / "dist" / "launcher" / "build" / "launcher_build_entry.py"
    assert (str(config), "packaging/launcher") in plan.datas
    assert (str(icon), "resources") in plan.datas
    assert plan.app_name == "MyApp"


def test_build_spec_only_writes_generated_spec(tmp_path, monkeypatch):
    """Spec-only mode should write a PyInstaller spec without running PyInstaller."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Linux")
    config = write_config(tmp_path)
    icon = config.parent / "icon_128x128.png"
    icon.write_bytes(b"png")

    result = build_cli.main(["--spec-only"])

    spec = tmp_path / "dist" / "launcher" / "build" / "launcher.spec"
    entry = tmp_path / "dist" / "launcher" / "build" / "launcher_build_entry.py"
    assert result == 0
    assert spec.is_file()
    assert entry.is_file()
    assert not (tmp_path / "dist" / "launcher" / "launcher.spec").exists()
    assert not (tmp_path / "dist" / "launcher" / "launcher_build_entry.py").exists()
    text = spec.read_text()
    assert "launcher_build_entry.py" in text
    assert "packaging/launcher/application.yml" in text
    assert str(config.resolve()) in text
    assert str(icon.resolve()) in text
    assert f"icon={str(icon.resolve())!r}" in text
    assert "dist/launcher" in text


def test_build_plan_allows_explicit_config_and_spec(tmp_path):
    """Advanced callers should be able to point at custom config/spec files."""
    config = write_config(tmp_path)
    spec = tmp_path / "custom.spec"
    spec.write_text("# custom")

    plan = build_cli.create_build_plan(config_path=config, spec_path=spec)

    assert plan.config_path == config.resolve()
    assert plan.spec_path == spec
    assert plan.uses_custom_spec is True
    assert (str(config), "packaging/launcher") in plan.datas


def test_build_plan_on_macos_auto_uses_png_and_prefers_icns(tmp_path, monkeypatch):
    """macOS should use the default PNG icon, preferring native ICNS when present."""
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Darwin")
    config = write_config(tmp_path)
    png_icon = config.parent / "icon_128x128.png"
    png_icon.write_bytes(b"png")

    plan = build_cli.create_build_plan(config_path=config)

    assert plan.icon_path == png_icon.resolve()
    assert (str(png_icon.resolve()), "resources") in plan.datas

    icns_icon = config.parent / "app.icns"
    icns_icon.write_bytes(b"icns")
    plan = build_cli.create_build_plan(config_path=config)

    assert plan.icon_path == icns_icon.resolve()
    assert (str(icns_icon.resolve()), "resources") in plan.datas


def test_build_plan_on_windows_prefers_ico(tmp_path, monkeypatch):
    """Windows should prefer the native ICO build icon."""
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Windows")
    config = write_config(tmp_path)
    png_icon = config.parent / "icon_128x128.png"
    ico_icon = config.parent / "app.ico"
    png_icon.write_bytes(b"png")
    ico_icon.write_bytes(b"ico")

    plan = build_cli.create_build_plan(config_path=config)

    assert plan.icon_path == ico_icon.resolve()


def test_build_spec_only_allows_explicit_icon(tmp_path, monkeypatch):
    """Build callers should be able to override the packaging icon for one build."""
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    icon = tmp_path / "custom.icns"
    icon.write_bytes(b"icns")

    result = build_cli.main(["--spec-only", "--icon", str(icon)])

    spec = tmp_path / "dist" / "launcher" / "build" / "launcher.spec"
    assert result == 0
    assert f"icon={str(icon.resolve())!r}" in spec.read_text()


def test_build_rejects_icon_with_custom_spec(tmp_path, capsys):
    """Explicit icons are encoded in generated specs, not custom specs."""
    config = write_config(tmp_path)
    icon = tmp_path / "custom.icns"
    icon.write_bytes(b"icns")
    spec = tmp_path / "custom.spec"
    spec.write_text("# custom")

    result = build_cli.main(["--config", str(config), "--icon", str(icon), "--spec", str(spec)])

    assert result == 1
    assert "--icon cannot be used with --spec" in capsys.readouterr().err


def test_run_pyinstaller_uses_clean_noninteractive_build(tmp_path, monkeypatch):
    """Launcher builds should not reuse stale PyInstaller analysis artifacts."""
    config = write_config(tmp_path)
    plan = build_cli.create_build_plan(config_path=config)
    calls = []
    monkeypatch.setattr(build_cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(build_cli.subprocess, "run", lambda command, check: calls.append((command, check)))

    build_cli.run_pyinstaller(plan)

    command, check = calls[0]
    assert check is True
    assert command[:3] == ["/bin/pyinstaller", "--clean", "--noconfirm"]
    assert "--distpath" in command
    assert "--workpath" in command
    assert command[-1] == plan.spec_path.as_posix()
