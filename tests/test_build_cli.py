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
    config = write_config(tmp_path)
    icon = config.parent / "icon_128x128.png"
    icon.write_bytes(b"png")

    plan = build_cli.create_build_plan()

    assert plan.config_path == config.resolve()
    assert plan.output_dir == tmp_path / "dist" / "launcher"
    assert (str(config), "packaging/launcher") in plan.datas
    assert (str(icon), "resources") in plan.datas
    assert plan.app_name == "MyApp"


def test_build_spec_only_writes_generated_spec(tmp_path, monkeypatch):
    """Spec-only mode should write a PyInstaller spec without running PyInstaller."""
    monkeypatch.chdir(tmp_path)
    config = write_config(tmp_path)
    icon = config.parent / "icon_128x128.png"
    icon.write_bytes(b"png")

    result = build_cli.main(["--spec-only"])

    spec = tmp_path / "dist" / "launcher" / "launcher.spec"
    assert result == 0
    assert spec.is_file()
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
