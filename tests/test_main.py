"""Tests for launcher entry-point helpers."""

from pathlib import Path
import sys
import queue

import main as launcher_main
from launcher import release_cli
from launcher import main as package_main
from launcher.worker import EventType, WorkerEvent


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
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
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


def test_config_check_accepts_valid_config(tmp_path, capsys):
    """`launcher config check` should validate config without starting the app."""
    config = tmp_path / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
            ]
        )
    )

    result = launcher_main.main(["config", "check", "--config", str(config)])

    output = capsys.readouterr()
    assert result == 0
    assert "Configuration OK" in output.out
    assert str(config.resolve()) in output.out


def test_config_check_rejects_invalid_config(tmp_path, capsys):
    """Config validation errors should be available before build/run."""
    config = tmp_path / "application.yml"
    config.write_text("name: MyApp\n")

    result = launcher_main.main(["config", "check", "--config", str(config)])

    output = capsys.readouterr()
    assert result == 1
    assert "Error loading configuration" in output.err
    assert "Required field 'entrypoint'" in output.err


def test_delayed_gui_opens_for_early_error():
    """Finder-launched apps should show errors that happen before gui_timeout."""
    event_queue = queue.Queue()
    calls = []

    class FakeWorker:
        def __init__(self):
            self._running = True

        def start(self):
            event_queue.put(WorkerEvent(type=EventType.ERROR, message="No releases found"))
            self._running = False

        def is_running(self):
            return self._running

    class FakeGui:
        def run(self):
            calls.append("gui")

    package_main.run_with_delayed_gui(FakeWorker(), FakeGui(), gui_timeout=30, event_queue=event_queue)

    assert calls == ["gui"]


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
            "--script",
            "src/myapp/__main__.py",
        ]
    )

    config = tmp_path / "packaging" / "launcher" / "application.yml"
    archive_script = tmp_path / "packaging" / "launcher" / "build-release-archive.py"
    source_icon = tmp_path / "packaging" / "launcher" / "launcher.svg"
    icon = tmp_path / "packaging" / "launcher" / "icon_128x128.png"
    assert result == 0
    assert config.is_file()
    assert not archive_script.exists()
    assert source_icon.is_file()
    assert icon.is_file()
    text = config.read_text()
    assert "name: MyApp" in text
    assert "repository: https://github.com/my-org/myapp.git" in text
    assert "entrypoint:" in text
    assert "  mode: script" in text
    assert "  script: src/myapp/__main__.py" in text
    assert "\npath:" not in text
    assert "# Replace this with the public key printed by: launcher release keygen" in text
    assert "public_key: \"<base64-ed25519-public-key>\"" in text
    assert "# These default URLs match the archive, manifest, and signature produced by" in text
    assert "# launcher release archive, sign, and upload." in text
    assert "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml" in text
    assert "https://github.com/my-org/myapp/releases/download/{version}/{archive_name}" in text
    assert "# No release.archive config is needed when tracked files are enough." in text
    assert "# release:" in text
    assert "#   archive:" in text
    assert "#     build:" in text
    assert "#       - command: [\"npm\", \"ci\"]" in text
    assert "#         cwd: frontend" in text
    assert "#     include:" in text
    assert "#       - source: frontend/dist" in text
    assert "#         destination: my_app/static" in text
    assert "#     custom_script: packaging/launcher/custom_archive.py" in text


def test_launcher_init_creates_module_entrypoint(tmp_path, monkeypatch):
    """`launcher init --mode module` should generate a module entrypoint."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        ["init", "--mode", "module", "--module", "my_app", "--arg=--desktop"]
    )

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert "entrypoint:" in text
    assert "  mode: module" in text
    assert "  module: my_app" in text
    assert "  args:\n    - --desktop" in text


def test_launcher_init_creates_project_entrypoint(tmp_path, monkeypatch):
    """`launcher init --mode project` should generate a project entrypoint."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        [
            "init",
            "--mode",
            "project",
            "--command",
            "my-app-gui",
            "--project-directory",
            "backend",
        ]
    )

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert "entrypoint:" in text
    assert "  mode: project" in text
    assert "  command: my-app-gui" in text
    assert "  project_directory: backend" in text


def test_init_writes_non_default_path(tmp_path, monkeypatch):
    """The generated config omits default path but preserves explicit overrides."""
    monkeypatch.chdir(tmp_path)

    result = launcher_main.main(["init", "--path", "~/Apps/{name}"])

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert 'path: "~/Apps/MyApp"' in text


def test_launcher_init_uses_packaged_default_icon_assets(tmp_path, monkeypatch):
    """Default init should copy the checked-in SVG source and PNG build icon."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(["init"])

    source_icon = tmp_path / "packaging" / "launcher" / "launcher.svg"
    png_icon = tmp_path / "packaging" / "launcher" / "icon_128x128.png"
    assert result == 0
    assert source_icon.read_bytes() == (package_main.DEFAULT_ASSETS_DIR / "launcher.svg").read_bytes()
    assert png_icon.read_bytes() == (package_main.DEFAULT_ASSETS_DIR / "launcher.png").read_bytes()


def test_launcher_init_copies_custom_png_icon(tmp_path, monkeypatch):
    """`launcher init --icon` should copy supported custom icons."""
    monkeypatch.chdir(tmp_path)
    source_icon = tmp_path / "custom.png"
    source_icon.write_bytes(b"png")

    result = package_main.main(["init", "--icon", str(source_icon)])

    icon = tmp_path / "packaging" / "launcher" / "icon_128x128.png"
    assert result == 0
    assert icon.read_bytes() == b"png"


def test_launcher_init_rejects_unsupported_icon_format(tmp_path, monkeypatch, capsys):
    """Unsupported icon formats should fail before writing packaging files."""
    monkeypatch.chdir(tmp_path)
    source_icon = tmp_path / "custom.svg"
    source_icon.write_text("<svg />")

    result = package_main.main(["init", "--icon", str(source_icon)])

    assert result == 1
    assert not (tmp_path / "packaging").exists()
    assert "Unsupported icon format" in capsys.readouterr().err


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
    assert "https://gitlab.com/my-org/myapp/-/releases/{version}/downloads/{archive_name}" in text
    assert "https://github.com/my-org/myapp" not in text


def test_launcher_init_infers_self_hosted_gitlab_release_asset_urls(tmp_path, monkeypatch):
    """Self-hosted GitLab repositories should use their own release asset URLs."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        [
            "init",
            "--name",
            "MyApp",
            "--repository",
            "https://gitlab.example.org/my-group/myapp",
        ]
    )

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert (
        "https://gitlab.example.org/my-group/myapp/-/releases/{version}/downloads/"
        "launcher-manifest.yml"
    ) in text
    assert (
        "https://gitlab.example.org/my-group/myapp/-/releases/{version}/downloads/"
        "{archive_name}"
    ) in text
    assert "https://github.com/my-org/myapp" not in text


def test_launcher_init_infers_nested_gitlab_release_asset_urls(tmp_path, monkeypatch):
    """GitLab repositories in nested groups should keep the full project path."""
    monkeypatch.chdir(tmp_path)

    result = package_main.main(
        [
            "init",
            "--name",
            "MyApp",
            "--repository",
            "https://gitlab.example.com/group/subgroup/project.git",
        ]
    )

    text = (tmp_path / "packaging" / "launcher" / "application.yml").read_text()
    assert result == 0
    assert (
        "https://gitlab.example.com/group/subgroup/project/-/releases/{version}/downloads/"
        "launcher-manifest.yml"
    ) in text
    assert (
        "https://gitlab.example.com/group/subgroup/project/-/releases/{version}/downloads/"
        "{archive_name}"
    ) in text
    assert "https://github.com/my-org/project" not in text


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
