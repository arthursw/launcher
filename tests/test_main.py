"""Tests for launcher entry-point helpers."""

from pathlib import Path
import sys

import main as launcher_main


def test_find_config_path_uses_explicit_path(tmp_path, monkeypatch):
    """An explicit config path should bypass default lookup."""
    monkeypatch.chdir(tmp_path)
    default_config = tmp_path / "application.yml"
    explicit_config = tmp_path / "galaxy" / "galaxy.yml"
    default_config.write_text("name: Default\n")
    explicit_config.parent.mkdir()
    explicit_config.write_text("name: Galaxy\n")

    config_path, candidates = launcher_main.find_config_path(explicit_config)

    assert config_path == explicit_config.resolve()
    assert candidates == []


def test_find_config_path_uses_env_override(tmp_path, monkeypatch):
    """LAUNCHER_CONFIG should override default config discovery."""
    env_config = tmp_path / "env.yml"
    env_config.write_text("name: FromEnv\n")
    monkeypatch.setenv(launcher_main.CONFIG_ENV_VAR, str(env_config))

    config_path, candidates = launcher_main.find_config_path()

    assert config_path == env_config.resolve()
    assert candidates == []


def test_find_config_path_finds_packaged_app_config(tmp_path, monkeypatch):
    """Frozen apps can locate a bundled config named after the executable."""
    cwd = tmp_path / "cwd"
    executable_dir = tmp_path / "dist" / "galaxy"
    bundle_dir = executable_dir / "_internal"
    config = bundle_dir / "galaxy" / "galaxy.yml"
    cwd.mkdir()
    config.parent.mkdir(parents=True)
    config.write_text("name: Galaxy\n")

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable_dir / "galaxy"))
    monkeypatch.setattr(launcher_main, "__file__", str(bundle_dir / "main.py"))

    config_path, candidates = launcher_main.find_config_path()

    assert config_path == config.resolve()
    assert config.resolve() in candidates


def test_default_config_candidates_are_unique(tmp_path, monkeypatch):
    """Source-mode lookup should not repeat the same path."""
    monkeypatch.chdir(Path(launcher_main.__file__).resolve().parent)
    monkeypatch.delattr(sys, "frozen", raising=False)

    candidates = launcher_main._default_config_candidates()

    assert len(candidates) == len(set(candidates))
