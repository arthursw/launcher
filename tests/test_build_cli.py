"""Tests for launcher build planning."""

from pathlib import Path
import subprocess
import stat
import zipfile

import pytest
import yaml

from launcher import build_cli


def write_config(root: Path) -> Path:
    config = root / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
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


def test_build_plan_validates_full_launcher_config(tmp_path):
    """Build planning should fail before packaging invalid runtime config."""
    config = tmp_path / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                # missing entrypoint
            ]
        )
    )

    try:
        build_cli.create_build_plan(config_path=config)
    except build_cli.BuildCliError as exc:
        message = str(exc)
    else:
        raise AssertionError("BuildCliError was not raised")

    assert "Invalid config" in message
    assert "Required field 'entrypoint'" in message


def test_build_reports_missing_custom_trust_urls_without_traceback(tmp_path, capsys):
    """Build should explain endpoint-only trust config instead of leaking TypeError."""
    config = tmp_path / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "api: https://updates.example.com",
                "releases_endpoint: /releases/latest",
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
                "trust:",
                "  mode: signed_manifest",
                "  public_key: abc",
            ]
        )
    )

    result = build_cli.main(["--config", str(config), "--spec-only"])

    output = capsys.readouterr()
    assert result == 1
    assert "Invalid config" in output.err
    assert "trust.manifest_url, trust.signature_url, trust.archive_url" in output.err
    assert "Set repository to a GitHub/GitLab URL" in output.err
    assert "Traceback" not in output.err
    assert "TypeError" not in output.err


def test_build_plan_allows_omitted_path(tmp_path):
    """path is optional and defaults to portable per-app runtime data."""
    config = write_config(tmp_path)

    plan = build_cli.create_build_plan(config_path=config)

    assert plan.app_name == "MyApp"


def test_build_spec_only_writes_generated_spec(tmp_path, monkeypatch, capsys):
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
    assert "collect_data_files" not in text
    assert "wetlands_datas" not in text
    output = capsys.readouterr()
    assert "Spec-only mode: generated build files without running PyInstaller." in output.out
    assert "Launcher build spec:" in output.out
    assert "Launcher build output:" in output.out


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
    assert (str(png_icon.resolve()), "resources") in plan.datas


def test_build_plan_on_windows_prefers_ico(tmp_path, monkeypatch):
    """Windows should prefer ICO for the executable and bundle the PNG GUI fallback."""
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Windows")
    config = write_config(tmp_path)
    png_icon = config.parent / "icon_128x128.png"
    ico_icon = config.parent / "app.ico"
    png_icon.write_bytes(b"png")
    ico_icon.write_bytes(b"ico")

    plan = build_cli.create_build_plan(config_path=config)

    assert plan.icon_path == ico_icon.resolve()
    assert (str(ico_icon.resolve()), "resources") in plan.datas
    assert (str(png_icon.resolve()), "resources") in plan.datas


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


def test_explicit_build_icon_excludes_default_runtime_icons(tmp_path):
    """An explicit icon override should also be the only bundled runtime icon."""
    config = write_config(tmp_path)
    default_icon = config.parent / "icon_128x128.png"
    explicit_icon = tmp_path / "custom.ico"
    default_icon.write_bytes(b"default")
    explicit_icon.write_bytes(b"explicit")

    plan = build_cli.create_build_plan(config_path=config, icon_path=explicit_icon)

    assert plan.icon_path == explicit_icon.resolve()
    assert (str(explicit_icon.resolve()), "resources") in plan.datas
    assert (str(default_icon.resolve()), "resources") not in plan.datas


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


def test_run_pyinstaller_uses_current_interpreter_for_clean_noninteractive_build(tmp_path, monkeypatch):
    """Launcher builds should use PyInstaller from the active Python environment."""
    config = write_config(tmp_path)
    plan = build_cli.create_build_plan(config_path=config)
    calls = []
    monkeypatch.setattr(build_cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(build_cli.subprocess, "run", lambda command, check: calls.append((command, check)))

    build_cli.run_pyinstaller(plan)

    command, check = calls[0]
    assert check is True
    assert command[:5] == [build_cli.sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm"]
    assert "--distpath" in command
    assert "--workpath" in command
    assert command[-1] == plan.spec_path.as_posix()


def test_run_pyinstaller_rejects_path_only_install(tmp_path, monkeypatch):
    """A global PyInstaller executable must not build against another Python environment."""
    config = write_config(tmp_path)
    plan = build_cli.create_build_plan(config_path=config)
    monkeypatch.setattr(build_cli.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(build_cli.shutil, "which", lambda name: f"/global/bin/{name}")

    with pytest.raises(build_cli.BuildCliError, match="uv run --with pyinstaller"):
        build_cli.run_pyinstaller(plan)


def test_build_prints_running_and_complete_messages(tmp_path, monkeypatch, capsys):
    """Real builds should clearly say that PyInstaller ran and where output lives."""
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)
    monkeypatch.setattr(build_cli, "run_pyinstaller", lambda plan: None)

    result = build_cli.main([])

    output = capsys.readouterr()
    assert result == 0
    assert "Running PyInstaller..." in output.out
    assert "Build complete: packaged launcher files are in" in output.out
    assert "Launcher build spec:" in output.out
    assert "Launcher build output:" in output.out


def test_build_reports_pyinstaller_failure_with_command(tmp_path, monkeypatch, capsys):
    """PyInstaller failures should include the failing command without a traceback."""
    config = write_config(tmp_path)
    plan = build_cli.create_build_plan(config_path=config)

    def fail(command, check):
        raise build_cli.subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(build_cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(build_cli.subprocess, "run", fail)

    result = build_cli.main(["--config", str(config)])

    output = capsys.readouterr()
    assert result == 1
    assert "PyInstaller failed with exit code 7." in output.err
    assert "Command:" in output.err
    assert str(plan.spec_path) in output.err
    assert "Traceback" not in output.err


def test_build_package_macos_app_uses_ditto(tmp_path, monkeypatch):
    """macOS app bundles should be packaged with ditto after external signing/notarization."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(build_cli.platform, "machine", lambda: "arm64")
    write_config(tmp_path)
    app = tmp_path / "dist" / "launcher" / "MyApp.app"
    app.mkdir(parents=True)
    calls = []

    def fake_run(command, check):
        calls.append((command, check))
        Path(command[-1]).write_bytes(b"zip")

    monkeypatch.setattr(build_cli.subprocess, "run", fake_run)

    artifact = build_cli.package_launcher(version="v1.2.3")

    assert artifact == Path("dist/MyApp-launcher-v1.2.3-macos-arm64.zip")
    assert calls == [
        (
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(app),
                str(tmp_path / artifact),
            ],
            True,
        )
    ]


def test_build_package_directory_build_uses_python_zip(tmp_path, monkeypatch):
    """Non-macOS directory-style builds should package with Python zip tooling."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_cli.platform, "machine", lambda: "x86_64")
    write_config(tmp_path)
    build_dir = tmp_path / "dist" / "launcher" / "myapp"
    build_dir.mkdir(parents=True)
    (build_dir / "myapp").write_text("exe")

    artifact = build_cli.package_launcher(version="v1.2.3")

    assert artifact == Path("dist/MyApp-launcher-v1.2.3-linux-x64.zip")
    with zipfile.ZipFile(tmp_path / artifact) as zf:
        assert zf.read("myapp/myapp") == b"exe"


def test_build_package_directory_build_preserves_symlinks(tmp_path, monkeypatch):
    """Directory-style build packaging should preserve POSIX symlink entries."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build_cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_cli.platform, "machine", lambda: "x86_64")
    write_config(tmp_path)
    build_dir = tmp_path / "dist" / "launcher" / "myapp"
    build_dir.mkdir(parents=True)
    (build_dir / "target.txt").write_text("target")
    (build_dir / "lib").mkdir()
    try:
        (build_dir / "link.txt").symlink_to("target.txt")
        (build_dir / "lib-link").symlink_to("lib", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks are not available on this filesystem: {exc}")

    artifact = build_cli.package_launcher(version="v1.2.3")

    with zipfile.ZipFile(tmp_path / artifact) as zf:
        file_link = zf.getinfo("myapp/link.txt")
        dir_link = zf.getinfo("myapp/lib-link")
        assert stat.S_ISLNK(file_link.external_attr >> 16)
        assert stat.S_ISLNK(dir_link.external_attr >> 16)
        assert zf.read("myapp/link.txt") == b"target.txt"
        assert zf.read("myapp/lib-link") == b"lib"


def test_build_package_reports_missing_build_output(tmp_path, monkeypatch):
    """Packaging should fail clearly when PyInstaller output has not been produced."""
    monkeypatch.chdir(tmp_path)
    write_config(tmp_path)

    with pytest.raises(build_cli.BuildCliError) as exc_info:
        build_cli.package_launcher(version="v1.2.3")

    message = str(exc_info.value)
    assert "No launcher build output found" in message
    assert "launcher build" in message
    assert "sign and notarize" in message


def test_build_upload_github_dry_run_does_not_update_distribution(tmp_path, monkeypatch):
    """Dry-run launcher uploads should print the provider command without touching metadata."""
    monkeypatch.chdir(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    write_config(tmp_path)
    asset = tmp_path / "dist" / "MyApp-launcher-v1.2.3-linux-x64.zip"
    asset.parent.mkdir()
    asset.write_bytes(b"zip")

    commands = build_cli.upload_launcher_package(version="v1.2.3", dry_run=True)

    assert commands == [
        [
            str(gh),
            "release",
            "upload",
            "v1.2.3",
            "dist/MyApp-launcher-v1.2.3-linux-x64.zip",
            "--clobber",
        ]
    ]
    assert not (tmp_path / "packaging" / "launcher" / "distribution.yml").exists()


def test_build_upload_gitlab_success_updates_distribution(tmp_path, monkeypatch):
    """Successful GitLab launcher uploads should persist latest download metadata."""
    monkeypatch.chdir(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    write_config(tmp_path).write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://gitlab.com/my-org/myapp.git",
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
                "auto_update: true",
                "configuration: pyproject.toml",
            ]
        )
    )
    asset = tmp_path / "dist" / "MyApp-launcher-v1.2.3-linux-x64.zip"
    asset.parent.mkdir()
    asset.write_bytes(b"zip")
    calls = []

    def fake_run(command, check, text, stdout, stderr):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(build_cli.subprocess, "run", fake_run)

    commands = build_cli.upload_launcher_package(version="v1.2.3")

    assert commands[0][:4] == [str(glab), "release", "upload", "v1.2.3"]
    assert "--use-package-registry" in commands[0]
    assert calls == [commands[0]]
    distribution = yaml.safe_load((tmp_path / "packaging" / "launcher" / "distribution.yml").read_text())
    assert distribution == {
        "schema_version": 1,
        "launcher_downloads": {
            "linux-x64": {
                "version": "v1.2.3",
                "asset": "MyApp-launcher-v1.2.3-linux-x64.zip",
                "url": "https://gitlab.com/my-org/myapp/-/releases/v1.2.3/downloads/MyApp-launcher-v1.2.3-linux-x64.zip",
            }
        },
    }


def test_build_upload_escapes_asset_names_in_distribution_urls(tmp_path, monkeypatch):
    """Distribution URLs should percent-encode asset names while preserving filenames."""
    monkeypatch.chdir(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    write_config(tmp_path).write_text(
        "\n".join(
            [
                "name: My App",
                "repository: https://github.com/my-org/myapp.git",
                "entrypoint:",
                "  mode: script",
                "  script: main.py",
                "auto_update: true",
                "configuration: pyproject.toml",
            ]
        )
    )
    asset = tmp_path / "dist" / "My App-launcher-v1.2.3-linux-x64.zip"
    asset.parent.mkdir()
    asset.write_bytes(b"zip")
    monkeypatch.setattr(
        build_cli.subprocess,
        "run",
        lambda command, check, text, stdout, stderr: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )

    build_cli.upload_launcher_package(version="v1.2.3")

    distribution = yaml.safe_load((tmp_path / "packaging" / "launcher" / "distribution.yml").read_text())
    download = distribution["launcher_downloads"]["linux-x64"]
    assert download["asset"] == "My App-launcher-v1.2.3-linux-x64.zip"
    assert download["url"].endswith("/My%20App-launcher-v1.2.3-linux-x64.zip")


def test_build_upload_failure_leaves_distribution_unchanged(tmp_path, monkeypatch):
    """Failed launcher uploads should not publish stale metadata."""
    monkeypatch.chdir(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    write_config(tmp_path)
    distribution = tmp_path / "packaging" / "launcher" / "distribution.yml"
    distribution.write_text("schema_version: 1\nlauncher_downloads: {}\n")
    asset = tmp_path / "dist" / "MyApp-launcher-v1.2.3-linux-x64.zip"
    asset.parent.mkdir()
    asset.write_bytes(b"zip")

    def fail(command, check, text, stdout, stderr):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(build_cli.subprocess, "run", fail)

    with pytest.raises(build_cli.BuildCliError):
        build_cli.upload_launcher_package(version="v1.2.3")

    assert yaml.safe_load(distribution.read_text()) == {"schema_version": 1, "launcher_downloads": {}}
