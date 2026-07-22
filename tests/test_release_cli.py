"""Tests for the launcher release CLI."""

import io
import os
from pathlib import Path
import stat
import subprocess
import zipfile

import yaml
import pytest

from launcher import release_cli


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _init_release_repo(tmp_path: Path, *, app_name: str = "MyApp") -> Path:
    repo = tmp_path / "myapp"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    (repo / "main.py").write_text("print('hello')\n")
    app_dir = repo / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text(
        f"name: {app_name}\nrepository: https://github.com/my-org/myapp.git\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "tag", "v1.2.3")
    return repo


def _release_zip_bytes(files: dict[str, str] | None = None, symlinks: dict[str, str] | None = None) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for name, content in (files or {"root/main.py": "print('hello')"}).items():
            zf.writestr(name, content)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return zip_buffer.getvalue()


def _prepare_signed_release(tmp_path: Path, monkeypatch, *, repository: str) -> str:
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                f"repository: {repository}",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()
    return public_key


def test_archive_release_default_git_archive_writes_dist_zip(tmp_path, monkeypatch):
    """archive should create the signed-release zip from tracked files by default."""
    repo = _init_release_repo(tmp_path)
    monkeypatch.chdir(repo)

    archive = release_cli.archive_release("v1.2.3")

    assert archive == Path("dist/myapp-v1.2.3.zip")
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert "myapp-v1.2.3/main.py" in names
        assert "myapp-v1.2.3/packaging/launcher/application.yml" in names
    release_cli.validate_release_archive(archive)


def test_archive_release_defaults_match_sign_from_app_subdirectory(tmp_path, monkeypatch):
    """archive should write dist/ beside the config when run from an app subdirectory."""
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text("{}\n")
    backend = repo / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[project]\nname = \"myapp\"\nversion = \"0.1.0\"\n")
    (backend / "src").mkdir()
    (backend / "src" / "myapp.py").write_text("print('hello')\n")
    app_dir = backend / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "tag", "v1.2.3")
    monkeypatch.chdir(backend)

    archive = release_cli.archive_release("v1.2.3")
    public_key = release_cli.keygen()
    release_cli.sign_release()
    manifest = release_cli.verify_release(public_key=public_key)

    assert archive == Path("dist/myapp-v1.2.3.zip")
    assert (backend / archive).is_file()
    assert not (repo / "dist").exists()
    assert (backend / "dist" / "launcher-manifest.yml").is_file()
    assert manifest["archive"]["name"] == "myapp-v1.2.3.zip"
    with zipfile.ZipFile(backend / archive) as zf:
        names = set(zf.namelist())
        assert "myapp-v1.2.3/frontend/package.json" in names
        assert "myapp-v1.2.3/backend/pyproject.toml" in names


def test_cli_archive_default_config_is_optional(tmp_path, monkeypatch, capsys):
    """archive should not require launcher config when tracked files are enough."""
    repo = tmp_path / "plain-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    (repo / "main.py").write_text("print('hello')\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "tag", "v1.2.3")
    monkeypatch.chdir(repo)

    result = release_cli.main(["archive", "v1.2.3"])

    assert result == 0
    assert (repo / "dist" / "plain-repo-v1.2.3.zip").is_file()
    assert "Archive written to: dist/plain-repo-v1.2.3.zip" in capsys.readouterr().out


def test_archive_release_rejects_unknown_ref(tmp_path, monkeypatch):
    """archive should fail clearly when the requested release ref does not exist."""
    repo = _init_release_repo(tmp_path)
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="Unknown git ref"):
        release_cli.archive_release("v9.9.9")


def test_archive_release_requires_version_to_match_head(tmp_path, monkeypatch):
    """archive should only package the commit currently checked out."""
    repo = _init_release_repo(tmp_path)
    (repo / "main.py").write_text("print('new')\n")
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-m", "new commit")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="does not match HEAD"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_dirty_tracked_files_before_build(tmp_path, monkeypatch):
    """tracked changes should not be packaged accidentally."""
    repo = _init_release_repo(tmp_path)
    (repo / "main.py").write_text("print('dirty')\n")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="tracked files are dirty"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_dirty_tracked_files_after_build(tmp_path, monkeypatch):
    """build commands may generate files but must not leave tracked files modified."""
    repo = _init_release_repo(tmp_path)
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    build:",
                "      - command:",
                "          - python",
                "          - -c",
                "          - \"from pathlib import Path; Path('main.py').write_text('dirty\\\\n')\"",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="tracked files are dirty"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_runs_build_commands_with_cwd_and_includes_generated_folder(tmp_path, monkeypatch):
    """structured build commands should run before generated includes are appended."""
    repo = _init_release_repo(tmp_path)
    frontend = repo / "frontend"
    frontend.mkdir()
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    build:",
                "      - command:",
                "          - python",
                "          - -c",
                "          - \"from pathlib import Path; "
                "Path('dist/app.js').parent.mkdir(exist_ok=True); Path('dist/app.js').write_text('built')\"",
                "        cwd: frontend",
                "    include:",
                "      - frontend/dist",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    archive = release_cli.archive_release("v1.2.3")

    with zipfile.ZipFile(archive) as zf:
        assert zf.read("myapp-v1.2.3/frontend/dist/app.js") == b"built"


def test_archive_release_includes_generated_folder_at_destination(tmp_path, monkeypatch):
    """object includes should copy source files under the requested destination."""
    repo = _init_release_repo(tmp_path)
    generated = repo / "frontend" / "dist"
    generated.mkdir(parents=True)
    (generated / "app.js").write_text("built")
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    include:",
                "      - source: frontend/dist",
                "        destination: my_app/static",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    archive = release_cli.archive_release("v1.2.3")

    with zipfile.ZipFile(archive) as zf:
        assert zf.read("myapp-v1.2.3/my_app/static/app.js") == b"built"


@pytest.mark.parametrize("destination", ["/abs", "../escape", "C:/escape", r"bad\\path"])
def test_archive_release_rejects_unsafe_include_destinations(tmp_path, monkeypatch, destination):
    """include destinations must stay inside the archive root."""
    repo = _init_release_repo(tmp_path)
    generated = repo / "frontend" / "dist"
    generated.mkdir(parents=True)
    (generated / "app.js").write_text("built")
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    include:",
                "      - source: frontend/dist",
                f"        destination: {destination!r}",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="Unsafe include destination"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_duplicate_archive_members(tmp_path, monkeypatch):
    """generated includes must not overwrite tracked files in the archive."""
    repo = _init_release_repo(tmp_path)
    generated = repo / "generated"
    generated.mkdir()
    (generated / "main.py").write_text("duplicate")
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    include:",
                "      - source: generated/main.py",
                "        destination: main.py",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="Duplicate archive member"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_include_source_symlink_outside_repo(tmp_path, monkeypatch):
    """generated include sources must not package files through escaping symlinks."""
    repo = _init_release_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (repo / "generated").mkdir()
    (repo / "generated" / "outside.txt").symlink_to(outside)
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    include:",
                "      - generated/outside.txt",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="Include source must stay inside the repository"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_custom_script_receives_version_and_archive_path(tmp_path, monkeypatch):
    """custom_script should be a full Python override for archive creation."""
    repo = _init_release_repo(tmp_path)
    script = repo / "packaging" / "launcher" / "custom_archive.py"
    script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "import zipfile",
                "version = sys.argv[1]",
                "archive = Path(sys.argv[2])",
                "archive.parent.mkdir(parents=True, exist_ok=True)",
                "with zipfile.ZipFile(archive, 'w') as zf:",
                "    zf.writestr(f'myapp-{version}/main.py', 'custom')",
            ]
        )
    )
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    custom_script: packaging/launcher/custom_archive.py",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "custom archive")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    archive = release_cli.archive_release("v1.2.3")

    with zipfile.ZipFile(archive) as zf:
        assert zf.read("myapp-v1.2.3/main.py") == b"custom"


def test_archive_release_rejects_missing_custom_script(tmp_path, monkeypatch):
    """custom_script should point to an existing Python file."""
    repo = _init_release_repo(tmp_path)
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    custom_script: packaging/launcher/missing.py",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "missing custom archive")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="Custom archive script not found"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_custom_script_with_structured_config(tmp_path, monkeypatch):
    """custom_script should not be mixed with built-in build/include config."""
    repo = _init_release_repo(tmp_path)
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    custom_script: packaging/launcher/custom_archive.py",
                "    include:",
                "      - frontend/dist",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "bad archive config")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="mutually exclusive"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_rejects_missing_custom_script_output(tmp_path, monkeypatch):
    """custom scripts must create the requested archive."""
    repo = _init_release_repo(tmp_path)
    script = repo / "packaging" / "launcher" / "custom_archive.py"
    script.write_text("import sys\n")
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    custom_script: packaging/launcher/custom_archive.py",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "bad custom archive")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="did not create archive"):
        release_cli.archive_release("v1.2.3")


def test_archive_release_validates_custom_script_output(tmp_path, monkeypatch):
    """custom scripts should not bypass archive extraction safety checks."""
    repo = _init_release_repo(tmp_path)
    script = repo / "packaging" / "launcher" / "custom_archive.py"
    script.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "import zipfile",
                "archive = Path(sys.argv[2])",
                "archive.parent.mkdir(parents=True, exist_ok=True)",
                "with zipfile.ZipFile(archive, 'w') as zf:",
                "    zf.writestr('../escape.py', 'bad')",
            ]
        )
    )
    config = repo / "packaging" / "launcher" / "application.yml"
    config.write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
                "release:",
                "  archive:",
                "    custom_script: packaging/launcher/custom_archive.py",
            ]
        )
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "unsafe custom archive")
    _git(repo, "tag", "-f", "v1.2.3")
    monkeypatch.chdir(repo)

    with pytest.raises(release_cli.ReleaseCliError, match="not safe for Launcher extraction"):
        release_cli.archive_release("v1.2.3")


def test_cli_archive_prints_written_archive(tmp_path, monkeypatch, capsys):
    """The release CLI should expose archive as the first release step."""
    repo = _init_release_repo(tmp_path)
    monkeypatch.chdir(repo)

    result = release_cli.main(["archive", "v1.2.3"])

    assert result == 0
    assert "Archive written to: dist/myapp-v1.2.3.zip" in capsys.readouterr().out


def test_archive_sign_verify_upload_dry_run_with_defaults(tmp_path, monkeypatch):
    """The default archive should flow through existing release commands unchanged."""
    repo = _init_release_repo(tmp_path)
    fake_bin = repo / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.chdir(repo)

    archive = release_cli.archive_release("v1.2.3")
    public_key = release_cli.keygen()
    release_cli.sign_release()
    manifest = release_cli.verify_release(public_key=public_key)
    commands = release_cli.upload_release(public_key=public_key, dry_run=True)

    assert archive == Path("dist/myapp-v1.2.3.zip")
    assert manifest["archive"]["name"] == "myapp-v1.2.3.zip"
    assert commands == [
        [
            str(gh),
            "release",
            "upload",
            "v1.2.3",
            "dist/myapp-v1.2.3.zip",
            "dist/launcher-manifest.yml",
            "dist/launcher-manifest.yml.sig",
            "--clobber",
        ]
    ]


def test_keygen_writes_key_and_gitignore_entry(tmp_path, monkeypatch):
    """keygen should create a private key and keep it out of git by default."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("dist/\n")

    public_key = release_cli.keygen()

    assert public_key
    assert (tmp_path / "launcher-signing-key.pem").is_file()
    assert "launcher-signing-key.pem" in (tmp_path / ".gitignore").read_text()


def test_cli_keygen_prints_gitignore_status(tmp_path, monkeypatch, capsys):
    """keygen output should say where the key was written and how it is protected."""
    monkeypatch.chdir(tmp_path)

    result = release_cli.main(["keygen"])

    output = capsys.readouterr()
    assert result == 0
    assert "Private key written to: launcher-signing-key.pem" in output.out
    assert "Private key ignored by git: launcher-signing-key.pem" in output.out
    assert "Add this public key to your app config:" in output.out


def test_cli_keygen_explains_private_key_outside_gitignore_scope(tmp_path, monkeypatch, capsys):
    """keygen should not claim .gitignore coverage for paths outside the current project."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    private_key = tmp_path / "outside-signing-key.pem"

    result = release_cli.main(["keygen", "--private-key", str(private_key)])

    output = capsys.readouterr()
    assert result == 0
    assert f"Private key written to: {private_key}" in output.out
    assert "Private key is outside the current directory, so .gitignore was not changed." in output.out
    assert "Keep this private key secret and out of source control." in output.out


def test_sign_infers_config_archive_and_version_from_defaults(tmp_path, monkeypatch):
    """sign should infer app name from config and version/archive from dist/."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()

    manifest_path, signature_path, returned_public_key = release_cli.sign_release()

    assert returned_public_key == public_key
    assert manifest_path.resolve() == dist_dir / "launcher-manifest.yml"
    assert signature_path.resolve() == dist_dir / "launcher-manifest.yml.sig"
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest == {
        "schema_version": 2,
        "application": "MyApp",
        "version": "v1.2.3",
        "archive": {
            "name": "myapp-v1.2.3.zip",
            "url": "https://github.com/my-org/myapp/releases/download/v1.2.3/myapp-v1.2.3.zip",
            "sha256": release_cli.sha256_file(dist_dir / "myapp-v1.2.3.zip"),
        },
    }


def test_sign_infers_packaging_launcher_config_by_default(tmp_path, monkeypatch):
    """sign should prefer the app-repo launcher config convention."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: PackagedApp\nrepository: https://gitlab.com/my-org/packaged-app.git\n"
    )
    (dist_dir / "packaged-app-v2.0.0.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    manifest_path, _, _ = release_cli.sign_release()

    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["application"] == "PackagedApp"
    assert manifest["version"] == "v2.0.0"
    assert (
        manifest["archive"]["url"]
        == "https://gitlab.com/my-org/packaged-app/-/releases/v2.0.0/downloads/packaged-app-v2.0.0.zip"
    )


def test_sign_accepts_explicit_version_for_unversioned_archive(tmp_path, monkeypatch):
    """Provider archive filenames should not need to encode the release version."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    (dist_dir / "myapp.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    manifest_path, _, _ = release_cli.sign_release(version="v1.2.3")

    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["version"] == "v1.2.3"
    assert manifest["archive"]["name"] == "myapp.zip"
    assert manifest["archive"]["url"].endswith("/v1.2.3/myapp.zip")
    assert manifest["archive"]["sha256"] == release_cli.sha256_file(dist_dir / "myapp.zip")


def test_sign_uses_trust_archive_url_template(tmp_path, monkeypatch):
    """trust.archive_url should define the archive URL when configured."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "trust:",
                "  mode: signed_manifest",
                "  public_key: placeholder",
                "  manifest_url: https://assets.example.com/{version}/launcher-manifest.yml",
                "  signature_url: https://assets.example.com/{version}/launcher-manifest.yml.sig",
                "  archive_url: https://assets.example.com/{version}/{archive_name}",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    manifest_path, _, _ = release_cli.sign_release()

    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["archive"]["url"] == "https://assets.example.com/v1.2.3/myapp-v1.2.3.zip"


def test_sign_archive_url_override_wins(tmp_path, monkeypatch):
    """--archive-url should override config and repository defaults."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    manifest_path, _, _ = release_cli.sign_release(
        archive_url="https://downloads.example.com/apps/{version}/{archive_name}"
    )

    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["archive"]["url"] == "https://downloads.example.com/apps/v1.2.3/myapp-v1.2.3.zip"


def test_sign_rejects_unresolved_archive_url_placeholder(tmp_path, monkeypatch):
    """Archive URL templates should fail clearly for unsupported placeholders."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text("name: MyApp\n")
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError, match="unsupported placeholder"):
        release_cli.sign_release(archive_url="https://example.com/{tag}/{archive_name}")


def test_sign_rejects_invalid_archive_url(tmp_path, monkeypatch):
    """Archive URLs written into signed manifests must be absolute HTTP(S) URLs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text("name: MyApp\n")
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError, match=r"absolute http\(s\) URL"):
        release_cli.sign_release(archive_url="not-a-url")


def test_sign_explains_unversioned_archive_name(tmp_path, monkeypatch):
    """Missing version errors should explain both supported fixes."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    archive = dist_dir / "myapp.zip"
    archive.write_bytes(_release_zip_bytes())
    release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.sign_release()

    message = str(exc_info.value)
    assert "Could not infer release version from archive name: dist/myapp.zip" in message
    assert "Pass --version" in message
    assert "rename the archive" in message


def test_infer_version_from_unversioned_archive_returns_none():
    """Archive filename inference should be conservative."""
    assert release_cli.infer_version_from_archive(Path("dist.zip")) is None
    assert release_cli.infer_version_from_archive(Path("myapp.zip")) is None
    assert release_cli.infer_version_from_archive(Path("myapp-v1.2.3.zip")) == "v1.2.3"


def test_infer_archive_ignores_unsupported_tar_archives(tmp_path):
    """Release commands should only accept archive formats supported at runtime."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "myapp-v1.2.3.tar.gz").write_bytes(b"tar")

    with pytest.raises(release_cli.ReleaseCliError, match="No release archive found"):
        release_cli.infer_archive(None, dist_dir, None)


def test_sign_rejects_archive_with_unsafe_symlink(tmp_path, monkeypatch):
    """sign should fail before approving archives the runtime extractor rejects."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("")
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text("name: MyApp\n")
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(
        _release_zip_bytes(symlinks={"root/.myapp": "/Users/developer/.myapp/"})
    )
    release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.sign_release()

    message = str(exc_info.value)
    assert "not safe for Launcher extraction" in message
    assert "unsafe symlink target" in message
    assert "Remove unsafe symlinks" in message


def test_verify_uses_config_public_key_and_default_dist_assets(tmp_path, monkeypatch):
    """verify should read trust.public_key from config and release assets from dist/."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    archive = dist_dir / "myapp-v1.2.3.zip"
    archive.write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "trust:",
                "  mode: signed_manifest",
                f'  public_key: "{public_key}"',
                "  manifest_url: https://example.com/{version}/launcher-manifest.yml",
                "  signature_url: https://example.com/{version}/launcher-manifest.yml.sig",
                "  archive_url: https://example.com/{version}/{archive_name}",
            ]
        )
    )
    release_cli.sign_release()

    manifest = release_cli.verify_release()

    assert manifest["application"] == "MyApp"
    assert manifest["version"] == "v1.2.3"


def test_verify_uses_packaging_launcher_config_public_key(tmp_path, monkeypatch):
    """verify should infer trust.public_key from packaging/launcher/application.yml."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    archive = dist_dir / "myapp-v1.2.3.zip"
    archive.write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "trust:",
                "  mode: signed_manifest",
                f'  public_key: "{public_key}"',
                "  manifest_url: https://example.com/{version}/launcher-manifest.yml",
                "  signature_url: https://example.com/{version}/launcher-manifest.yml.sig",
                "  archive_url: https://example.com/{version}/{archive_name}",
            ]
        )
    )
    release_cli.sign_release()

    manifest = release_cli.verify_release()

    assert manifest["application"] == "MyApp"
    assert manifest["version"] == "v1.2.3"


def test_verify_rejects_tampered_archive(tmp_path, monkeypatch):
    """verify should fail when the archive no longer matches the manifest hash."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    archive = dist_dir / "myapp-v1.2.3.zip"
    archive.write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    release_cli.sign_release()
    archive.write_bytes(b"tampered")

    with pytest.raises(release_cli.ReleaseCliError, match="SHA-256 mismatch"):
        release_cli.verify_release(public_key=public_key)


def test_verify_missing_manifest_explains_release_flow(tmp_path, monkeypatch):
    """Missing release metadata should point developers to the normal workflow."""
    monkeypatch.chdir(tmp_path)
    public_key = release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.verify_release(public_key=public_key)

    message = str(exc_info.value)
    assert "Release manifest not found" in message
    assert "launcher release sign" in message
    assert "launcher release verify" in message
    assert "launcher release upload" in message


def test_verify_missing_signature_explains_release_flow(tmp_path, monkeypatch):
    """A manifest without its signature should explain how metadata is produced."""
    monkeypatch.chdir(tmp_path)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "launcher-manifest.yml").write_text("application: MyApp\n")
    public_key = release_cli.keygen()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.verify_release(public_key=public_key)

    message = str(exc_info.value)
    assert "Release signature not found" in message
    assert "launcher release sign" in message
    assert "launcher release upload" in message


def test_verify_rejects_archive_with_unsafe_symlink(tmp_path, monkeypatch):
    """verify should fail before metadata for an unsafe archive can be uploaded."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    archive = dist_dir / "myapp-v1.2.3.zip"
    public_key = release_cli.keygen()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    archive.write_bytes(_release_zip_bytes())
    release_cli.sign_release()
    archive.write_bytes(_release_zip_bytes(symlinks={"root/.myapp": "/Users/developer/.myapp/"}))
    manifest = yaml.safe_load((dist_dir / "launcher-manifest.yml").read_text())
    manifest["archive"]["sha256"] = release_cli.sha256_file(archive)
    manifest_path = dist_dir / "launcher-manifest.yml"
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    private_key = release_cli.load_private_key(release_cli.DEFAULT_PRIVATE_KEY)
    (dist_dir / "launcher-manifest.yml.sig").write_bytes(private_key.sign(manifest_bytes))

    with pytest.raises(release_cli.ReleaseCliError, match="not safe for Launcher extraction"):
        release_cli.verify_release(public_key=public_key)


def test_cli_verify_prints_success(tmp_path, monkeypatch, capsys):
    """The installed CLI entry point should expose verify."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text(
        "name: MyApp\nrepository: https://github.com/my-org/myapp.git\n"
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    result = release_cli.main(["verify", "--public-key", public_key])

    assert result == 0
    assert "OK: MyApp v1.2.3" in capsys.readouterr().out


def test_upload_dry_run_uses_github_cli(tmp_path, monkeypatch):
    """GitHub uploads should use gh after verifying release assets."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    fake_bin = tmp_path / "bin"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    commands = release_cli.upload_release(public_key=public_key, dry_run=True)

    assert commands == [
        [
            str(gh),
            "release",
            "upload",
            "v1.2.3",
            "dist/myapp-v1.2.3.zip",
            "dist/launcher-manifest.yml",
            "dist/launcher-manifest.yml.sig",
            "--clobber",
        ]
    ]


def test_upload_dry_run_uses_gitlab_cli(tmp_path, monkeypatch):
    """GitLab uploads should use glab with the package-registry flag."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    fake_bin = tmp_path / "bin"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://gitlab.com/my-org/myapp.git",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    commands = release_cli.upload_release(public_key=public_key, dry_run=True)

    assert commands == [
        [
            str(glab),
            "release",
            "upload",
            "v1.2.3",
            "dist/myapp-v1.2.3.zip",
            "dist/launcher-manifest.yml",
            "dist/launcher-manifest.yml.sig",
            "--use-package-registry",
        ]
    ]


def test_cli_upload_dry_run_labels_command_and_assets(tmp_path, monkeypatch, capsys):
    """Dry-run upload output should be impossible to confuse with a real upload."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    public_key = _prepare_signed_release(
        tmp_path,
        monkeypatch,
        repository="https://gitlab.com/my-org/myapp.git",
    )

    result = release_cli.main(["upload", "--public-key", public_key, "--dry-run"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Dry run: verified MyApp v1.2.3 release assets." in output
    assert "No files were uploaded." in output
    assert "Would upload to GitLab: https://gitlab.com/my-org/myapp.git" in output
    assert "Assets:" in output
    assert "Archive: dist/myapp-v1.2.3.zip" in output
    assert "Manifest: dist/launcher-manifest.yml" in output
    assert "Signature: dist/launcher-manifest.yml.sig" in output
    assert "Command:" in output
    assert "glab release upload v1.2.3" in output
    assert "Upload complete" not in output


def test_cli_upload_success_prints_provider_output_and_completion(tmp_path, monkeypatch, capsys):
    """Successful upload output should say what happened and replay provider details."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text(
        "#!/bin/sh\n"
        "echo 'provider stdout: uploaded archive'\n"
        "echo 'provider stderr: linked assets' >&2\n"
        "exit 0\n"
    )
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    public_key = _prepare_signed_release(
        tmp_path,
        monkeypatch,
        repository="https://gitlab.com/my-org/myapp.git",
    )

    result = release_cli.main(["upload", "--public-key", public_key])

    output = capsys.readouterr().out
    assert result == 0
    assert "Uploading MyApp v1.2.3 release assets to GitLab." in output
    assert "Repository: https://gitlab.com/my-org/myapp.git" in output
    assert "Assets:" in output
    assert "Command:" in output
    assert "provider stdout: uploaded archive" in output
    assert "provider stderr: linked assets" in output
    assert "Upload complete: MyApp v1.2.3 release assets are published." in output


def test_cli_upload_success_prints_github_provider_name(tmp_path, monkeypatch, capsys):
    """GitHub upload output should use the same explicit success flow as GitLab."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("#!/bin/sh\necho 'provider stdout: uploaded with clobber'\nexit 0\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    public_key = _prepare_signed_release(
        tmp_path,
        monkeypatch,
        repository="https://github.com/my-org/myapp.git",
    )

    result = release_cli.main(["upload", "--public-key", public_key])

    output = capsys.readouterr().out
    assert result == 0
    assert "Uploading MyApp v1.2.3 release assets to GitHub." in output
    assert "Repository: https://github.com/my-org/myapp.git" in output
    assert "gh release upload v1.2.3" in output
    assert "--clobber" in output
    assert "provider stdout: uploaded with clobber" in output
    assert "Upload complete: MyApp v1.2.3 release assets are published." in output


def test_upload_missing_provider_cli_explains_install_and_manual_upload(tmp_path, monkeypatch):
    """Missing gh/glab should produce a helpful prerequisite-oriented error."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    with pytest.raises(release_cli.ReleaseCliError, match="github.com/cli/cli#installation"):
        release_cli.upload_release(public_key=public_key)


def test_upload_gitlab_cli_failure_explains_release_prerequisites(tmp_path, monkeypatch):
    """glab upload failures should explain likely release setup fixes."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    fake_bin = tmp_path / "bin"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("#!/bin/sh\necho '404 Not Found.' >&2\nexit 1\n")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://gitlab.com/my-org/myapp.git",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.upload_release(public_key=public_key)

    message = str(exc_info.value)
    assert "GitLab release upload failed" in message
    assert "404 Not Found" in message
    assert "glab release create v1.2.3" in message
    assert "rerun `launcher release create` before upload" in message
    assert "git push origin v1.2.3" in message
    assert "glab auth status" in message
    assert "Traceback" not in message


def test_upload_gitlab_duplicate_asset_failure_explains_previous_success(tmp_path, monkeypatch):
    """GitLab duplicate-asset errors should explain that the previous upload likely worked."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text(
        "#!/bin/sh\n"
        "echo '{message: [Url has already been taken, Name has already been taken, Filepath has already been taken]}' >&2\n"
        "exit 1\n"
    )
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    public_key = _prepare_signed_release(
        tmp_path,
        monkeypatch,
        repository="https://gitlab.com/my-org/myapp.git",
    )

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.upload_release(public_key=public_key)

    message = str(exc_info.value)
    assert "GitLab reports that one or more release assets already exist." in message
    assert "A previous upload may have succeeded." in message
    assert "Delete or replace the existing GitLab release assets before retrying the same version" in message


def test_upload_github_cli_failure_explains_release_prerequisites(tmp_path, monkeypatch):
    """gh upload failures should explain likely release setup fixes."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    fake_bin = tmp_path / "bin"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("#!/bin/sh\necho 'HTTP 404: Not Found' >&2\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    (app_dir / "application.yml").write_text(
        "\n".join(
            [
                "name: MyApp",
                "repository: https://github.com/my-org/myapp.git",
            ]
        )
    )
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(_release_zip_bytes())
    public_key = release_cli.keygen()
    release_cli.sign_release()

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.upload_release(public_key=public_key)

    message = str(exc_info.value)
    assert "GitHub release upload failed" in message
    assert "HTTP 404" in message
    assert "gh release create v1.2.3" in message
    assert "git push origin v1.2.3" in message
    assert "gh auth status" in message


def test_compose_release_notes_passes_user_notes_through_when_no_downloads(tmp_path, monkeypatch):
    """User-authored notes should be unchanged when no launcher downloads are available."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("## Changes\n\n- Fixed startup\n")

    generated = release_cli.compose_release_notes(version="v1.2.3", notes_path=notes)

    assert generated == "## Changes\n\n- Fixed startup\n"


def test_compose_release_notes_missing_file_explains_notes_path(tmp_path, monkeypatch):
    """Missing release notes files should fail without a Python traceback."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.compose_release_notes(version="v1.2.3", notes_path=Path("Release v1.2.3"))

    message = str(exc_info.value)
    assert "Release notes file not found: Release v1.2.3" in message
    assert "--notes expects a Markdown file path" in message
    assert 'launcher release create v1.2.3 --notes-text "Release v1.2.3"' in message


def test_compose_release_notes_accepts_inline_text(tmp_path, monkeypatch):
    """Inline release notes should use the same generated-notes flow as notes files."""
    monkeypatch.chdir(tmp_path)

    generated = release_cli.compose_release_notes(version="v1.2.3", notes_text="Release v1.2.3")

    assert generated == "Release v1.2.3"


def test_compose_release_notes_appends_launcher_download_block(tmp_path, monkeypatch):
    """Release notes should include a Launcher-managed download block when URLs exist."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("User notes\n")
    distribution = tmp_path / "packaging" / "launcher" / "distribution.yml"
    distribution.parent.mkdir(parents=True)
    distribution.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "launcher_downloads": {
                    "macos-arm64": {
                        "version": "v1.2.2",
                        "asset": "MyApp-launcher-v1.2.2-macos-arm64.zip",
                        "url": "https://example.com/old.zip",
                    },
                    "linux-x64": {
                        "version": "v1.2.3",
                        "asset": "MyApp-launcher-v1.2.3-linux-x64.zip",
                        "url": "https://example.com/linux.zip",
                    },
                },
            },
            sort_keys=False,
        )
    )

    generated = release_cli.compose_release_notes(version="v1.2.3", notes_path=notes)

    assert generated.startswith("User notes\n")
    assert "## Launcher Downloads" in generated
    assert "- linux-x64: [MyApp-launcher-v1.2.3-linux-x64.zip](https://example.com/linux.zip)" in generated
    assert "- macos-arm64: [MyApp-launcher-v1.2.2-macos-arm64.zip](https://example.com/old.zip)" in generated


def test_compose_release_notes_prefers_local_current_version_packages(tmp_path, monkeypatch):
    """Local packages for the release version should override stored distribution URLs."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("User notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    (app_dir / "distribution.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "launcher_downloads": {
                    "linux-x64": {
                        "version": "v1.2.2",
                        "asset": "MyApp-launcher-v1.2.2-linux-x64.zip",
                        "url": "https://example.com/old-linux.zip",
                    }
                },
            },
            sort_keys=False,
        )
    )
    local_asset = tmp_path / "dist" / "MyApp-launcher-v1.2.3-linux-x64.zip"
    local_asset.parent.mkdir()
    local_asset.write_bytes(b"zip")

    generated = release_cli.compose_release_notes(version="v1.2.3", notes_path=notes)

    assert "old-linux.zip" not in generated
    assert (
        "- linux-x64: [MyApp-launcher-v1.2.3-linux-x64.zip]"
        "(https://github.com/my-org/myapp/releases/download/v1.2.3/MyApp-launcher-v1.2.3-linux-x64.zip)"
    ) in generated


def test_compose_release_notes_escapes_local_package_asset_urls(tmp_path, monkeypatch):
    """Generated launcher download links should percent-encode asset filenames."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("User notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: My App\nrepository: https://github.com/my-org/myapp.git\n")
    local_asset = tmp_path / "dist" / "My App-launcher-v1.2.3-linux-x64.zip"
    local_asset.parent.mkdir()
    local_asset.write_bytes(b"zip")

    generated = release_cli.compose_release_notes(version="v1.2.3", notes_path=notes)

    assert "[My App-launcher-v1.2.3-linux-x64.zip]" in generated
    assert "My%20App-launcher-v1.2.3-linux-x64.zip" in generated


def test_release_create_github_uses_verify_tag_and_generated_notes(tmp_path, monkeypatch):
    """GitHub release creation should verify the existing tag and use generated notes."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")

    plan = release_cli.plan_create_release(version="v1.2.3", notes_path=notes)

    assert plan.command == [
        str(gh),
        "release",
        "create",
        "v1.2.3",
        "--verify-tag",
        "--notes-file",
        str(plan.notes_file),
    ]
    assert plan.notes_file.read_text() == "Release notes\n"


def test_release_create_accepts_inline_notes_text(tmp_path, monkeypatch):
    """Release creation should accept inline notes and still pass a notes file to the provider CLI."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")

    plan = release_cli.plan_create_release(version="v1.2.3", notes_text="Release v1.2.3")

    assert plan.command == [
        str(gh),
        "release",
        "create",
        "v1.2.3",
        "--verify-tag",
        "--notes-file",
        str(plan.notes_file),
    ]
    assert plan.notes_file.read_text() == "Release v1.2.3"


def test_release_create_gitlab_refuses_when_remote_tag_missing(tmp_path, monkeypatch):
    """GitLab release creation must preflight the remote tag instead of letting glab create it."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://gitlab.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)

    def fake_git_stdout(args, cwd=None):
        if args[:2] == ["ls-remote", "--exit-code"]:
            raise release_cli.ReleaseCliError("missing remote tag")
        return "ok"

    monkeypatch.setattr(release_cli, "git_stdout", fake_git_stdout)

    with pytest.raises(release_cli.ReleaseCliError) as exc_info:
        release_cli.plan_create_release(version="v1.2.3", notes_path=notes)

    message = str(exc_info.value)
    assert "Remote tag v1.2.3 was not found" in message
    assert "git push origin v1.2.3" in message
    assert "Plain `git push` does not usually push tags" in message


def test_release_create_gitlab_title_uses_name_flag(tmp_path, monkeypatch):
    """GitLab release titles should use the glab --name flag."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://gitlab.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    glab = fake_bin / "glab"
    glab.write_text("")
    glab.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")

    plan = release_cli.plan_create_release(version="v1.2.3", notes_path=notes, title="MyApp 1.2.3")

    assert plan.command[-2:] == ["--name", "MyApp 1.2.3"]


def test_release_create_tag_and_push_are_explicit(tmp_path, monkeypatch):
    """Local tags and remote pushes should only run when requested."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")
    calls = []
    monkeypatch.setattr(release_cli, "run_git", lambda args, cwd: calls.append(args))
    monkeypatch.setattr(release_cli, "run_release_create_command", lambda command, provider, version, repository: "")

    release_cli.create_release(version="v1.2.3", notes_path=notes, tag=False, push=False)
    assert calls == []

    release_cli.create_release(version="v1.2.3", notes_path=notes, tag=True, push=True, dry_run=False)
    assert calls == [["tag", "v1.2.3"], ["push", "origin", "v1.2.3"]]


def test_release_create_dry_run_with_push_does_not_require_remote_tag(tmp_path, monkeypatch):
    """Dry-run with --push should plan the push instead of requiring it to have happened."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)

    def fake_git_stdout(args, cwd=None):
        if args[:2] == ["ls-remote", "--exit-code"]:
            raise AssertionError("remote tag preflight should be skipped when --push is planned")
        return "ok"

    monkeypatch.setattr(release_cli, "git_stdout", fake_git_stdout)

    commands = release_cli.create_release(version="v1.2.3", notes_path=notes, tag=True, push=True, dry_run=True)

    assert commands[0] == ["git", "tag", "v1.2.3"]
    assert commands[1] == ["git", "push", "origin", "v1.2.3"]
    assert commands[2][1:4] == ["release", "create", "v1.2.3"]


def test_release_create_dry_run_prints_planned_command_without_provider_call(tmp_path, monkeypatch, capsys):
    """Dry-run release creation should show the provider command and skip release creation."""
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("Release notes\n")
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")

    def fail(*args, **kwargs):
        raise AssertionError("provider CLI should not run")

    monkeypatch.setattr(release_cli, "run_release_create_command", fail)

    result = release_cli.main(["create", "v1.2.3", "--notes", str(notes), "--dry-run"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Dry run: planned GitHub release creation for v1.2.3." in output
    assert "gh release create v1.2.3 --verify-tag --notes-file" in output


def test_release_create_cli_accepts_notes_text(tmp_path, monkeypatch, capsys):
    """The create CLI should accept inline release notes."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    app_dir.mkdir(parents=True)
    (app_dir / "application.yml").write_text("name: MyApp\nrepository: https://github.com/my-org/myapp.git\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text("")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(release_cli, "git_repo_root", lambda: tmp_path)
    monkeypatch.setattr(release_cli, "git_stdout", lambda args, cwd=None: "ok")

    result = release_cli.main(["create", "v1.2.3", "--notes-text", "Release v1.2.3", "--dry-run"])

    output = capsys.readouterr().out
    assert result == 0
    assert "Dry run: planned GitHub release creation for v1.2.3." in output
    assert "gh release create v1.2.3 --verify-tag --notes-file" in output
