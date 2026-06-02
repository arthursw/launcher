"""Tests for the launcher release CLI."""

import yaml
import pytest

from launcher import release_cli


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
    (app_dir / "application.yml").write_text("name: MyApp\n")
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(b"archive-content")
    public_key = release_cli.keygen()

    manifest_path, signature_path, returned_public_key = release_cli.sign_release()

    assert returned_public_key == public_key
    assert manifest_path.resolve() == dist_dir / "launcher-manifest.yml"
    assert signature_path.resolve() == dist_dir / "launcher-manifest.yml.sig"
    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest == {
        "schema_version": 1,
        "application": "MyApp",
        "version": "v1.2.3",
        "archive": {
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
    (app_dir / "application.yml").write_text("name: PackagedApp\n")
    (dist_dir / "packaged-app-v2.0.0.zip").write_bytes(b"archive-content")
    release_cli.keygen()

    manifest_path, _, _ = release_cli.sign_release()

    manifest = yaml.safe_load(manifest_path.read_text())
    assert manifest["application"] == "PackagedApp"
    assert manifest["version"] == "v2.0.0"


def test_verify_uses_config_public_key_and_default_dist_assets(tmp_path, monkeypatch):
    """verify should read trust.public_key from config and release assets from dist/."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    archive = dist_dir / "myapp-v1.2.3.zip"
    archive.write_bytes(b"archive-content")
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
    archive.write_bytes(b"archive-content")
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
    archive.write_bytes(b"archive-content")
    public_key = release_cli.keygen()
    (app_dir / "application.yml").write_text("name: MyApp\n")
    release_cli.sign_release()
    archive.write_bytes(b"tampered")

    with pytest.raises(release_cli.ReleaseCliError, match="SHA-256 mismatch"):
        release_cli.verify_release(public_key=public_key)


def test_cli_verify_prints_success(tmp_path, monkeypatch, capsys):
    """The installed CLI entry point should expose verify."""
    monkeypatch.chdir(tmp_path)
    app_dir = tmp_path / "packaging" / "launcher"
    dist_dir = tmp_path / "dist"
    app_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (app_dir / "application.yml").write_text("name: MyApp\n")
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(b"archive-content")
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
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(b"archive-content")
    public_key = release_cli.keygen()
    release_cli.sign_release()

    commands = release_cli.upload_release(public_key=public_key, dry_run=True)

    assert commands == [
        [
            str(gh),
            "release",
            "upload",
            "v1.2.3",
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
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(b"archive-content")
    public_key = release_cli.keygen()
    release_cli.sign_release()

    commands = release_cli.upload_release(public_key=public_key, dry_run=True)

    assert commands == [
        [
            str(glab),
            "release",
            "upload",
            "v1.2.3",
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
    (dist_dir / "myapp-v1.2.3.zip").write_bytes(b"archive-content")
    public_key = release_cli.keygen()
    release_cli.sign_release()

    with pytest.raises(release_cli.ReleaseCliError, match="github.com/cli/cli#installation"):
        release_cli.upload_release(public_key=public_key)
