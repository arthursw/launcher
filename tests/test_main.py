"""Tests for launcher entry-point helpers."""

from pathlib import Path
import sys

import main as launcher_main
from launcher import release_cli
from launcher import main as package_main


def test_find_config_path_uses_explicit_path(tmp_path, monkeypatch):
    """An explicit config path should bypass default lookup."""
    monkeypatch.chdir(tmp_path)
    default_config = tmp_path / "packaging" / "launcher" / "application.yml"
    explicit_config = tmp_path / "custom" / "launcher.yml"
    default_config.parent.mkdir(parents=True)
    default_config.write_text("name: Default\n")
    explicit_config.parent.mkdir()
    explicit_config.write_text("name: Custom\n")

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


def test_find_config_path_prefers_packaging_launcher_default(tmp_path, monkeypatch):
    """Source-mode lookup should find the app-repo launcher config by default."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text("name: Packaged\n")

    config_path, candidates = launcher_main.find_config_path()

    assert config_path == config.resolve()
    assert config.resolve() in candidates


def test_find_config_path_finds_pyinstaller_bundled_config(tmp_path, monkeypatch):
    """Frozen apps can locate the bundled packaging/launcher config."""
    cwd = tmp_path / "cwd"
    executable_dir = tmp_path / "dist" / "myapp"
    internal_root = executable_dir / "_internal"
    bundle_dir = internal_root
    config = internal_root / "packaging" / "launcher" / "application.yml"
    cwd.mkdir()
    config.parent.mkdir(parents=True)
    config.write_text("name: MyApp\n")

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable_dir / "myapp"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal_root), raising=False)
    monkeypatch.setattr(launcher_main, "__file__", str(bundle_dir / "main.py"))

    config_path, candidates = launcher_main.find_config_path()

    assert config_path == config.resolve()
    assert config.resolve() in candidates


def test_package_main_frozen_lookup_checks_pyinstaller_internal_root(tmp_path, monkeypatch):
    """Generated PyInstaller builds should find bundled packaging/launcher config."""
    cwd = tmp_path / "cwd"
    executable_dir = tmp_path / "dist" / "myapp"
    internal_root = executable_dir / "_internal"
    package_dir = internal_root / "launcher"
    config = internal_root / "packaging" / "launcher" / "application.yml"
    cwd.mkdir()
    package_dir.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    config.write_text("name: MyApp\n")

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable_dir / "myapp"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal_root), raising=False)
    monkeypatch.setattr(package_main, "__file__", str(package_dir / "main.py"))

    config_path, candidates = package_main.find_config_path()

    assert config_path == config.resolve()
    assert config.resolve() in candidates


def test_default_config_candidates_are_unique(tmp_path, monkeypatch):
    """Source-mode lookup should not repeat the same path."""
    monkeypatch.chdir(Path(launcher_main.__file__).resolve().parent)
    monkeypatch.delattr(sys, "frozen", raising=False)

    candidates = launcher_main._default_config_candidates()

    assert len(candidates) == len(set(candidates))


def test_launcher_release_subcommand_delegates_to_release_cli(monkeypatch):
    """`launcher release ...` should reuse the release command implementation."""
    calls = []

    def fake_release_main(argv, prog="launcher release"):
        calls.append((argv, prog))
        return 0

    monkeypatch.setattr(release_cli, "main", fake_release_main)

    result = package_main.main(["release", "verify", "--public-key", "abc"])

    assert result == 0
    assert calls == [(["verify", "--public-key", "abc"], "launcher release")]


def test_launcher_run_subcommand_uses_runtime_launcher(monkeypatch, tmp_path):
    """`launcher run` should invoke the existing runtime path explicitly."""
    config = tmp_path / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: TestApp",
                "repository: https://github.com/org/test-app.git",
                "main: main.py",
                "path: .",
            ]
        )
    )
    calls = []

    class FakeWorker:
        failed = False

        def __init__(self, config_path, event_queue, response_queue):
            calls.append(("worker", config_path))

        def start(self):
            calls.append(("start", None))

        def stop(self):
            calls.append(("stop", None))

    class FakeGui:
        error_message = None

        def run(self):
            calls.append(("gui", None))

        def destroy(self):
            calls.append(("destroy", None))

    monkeypatch.setattr(package_main, "LauncherWorker", FakeWorker)
    monkeypatch.setattr(package_main, "get_gui", lambda *args: FakeGui())

    result = package_main.main(["run", "--no-gui", "--config", str(config)])

    assert result == 0
    assert ("worker", config.resolve()) in calls


def test_launcher_init_creates_default_packaging_files(tmp_path, monkeypatch):
    """`launcher init` should create app-owned launcher packaging files."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        [
            "init",
            "--name",
            "MyApp",
            "--repository",
            "https://github.com/my-org/myapp.git",
            "--main",
            "src/myapp/__main__.py",
        ]
    )

    config = tmp_path / "packaging" / "launcher" / "application.yml"
    icon = tmp_path / "packaging" / "launcher" / "icon_128x128.png"
    assert result == 0
    assert config.is_file()
    assert icon.is_file()
    text = config.read_text()
    assert "name: MyApp" in text
    assert "repository: https://github.com/my-org/myapp.git" in text
    assert "main: src/myapp/__main__.py" in text
    assert "public_key: \"<base64-ed25519-public-key>\"" in text
    assert "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml" in text


def test_launcher_init_infers_gitlab_release_asset_urls(tmp_path, monkeypatch):
    """GitLab repositories should not receive GitHub manifest URL placeholders."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        [
            "init",
            "--name",
            "MyApp",
            "--repository",
            "https://gitlab.com/my-org/myapp.git",
        ]
    )

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert "https://gitlab.com/my-org/myapp/-/releases/{version}/downloads/launcher-manifest.yml" in text
    assert "https://github.com/my-org/myapp" not in text


def test_launcher_init_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    """Existing generated files should be protected unless --force is used."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text("name: Existing\n")

    result = package_main.main(["init", "--name", "NewName"])

    assert result == 1
    assert config.read_text() == "name: Existing\n"
    assert "already exists" in capsys.readouterr().err
