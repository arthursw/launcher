"""Tests for the launcher release CLI."""

import io
from pathlib import Path
import stat
import zipfile

import yaml
import pytest

from launcher import release_cli


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


def test_keygen_writes_key_and_gitignore_entry(tmp_path, monkeypatch):
    """keygen should create a private key and keep it out of git by default."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("dist/\n")

    public_key = release_cli.keygen()

    assert public_key
    assert (tmp_path / "launcher-signing-key.pem").is_file()
    assert "launcher-signing-key.pem" in (tmp_path / ".gitignore").read_text()


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
