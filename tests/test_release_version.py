"""Tests for shared release-tag inference and artifact parsing."""

from pathlib import Path
import subprocess

import pytest

from launcher import release_version


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _write_project(
    tmp_path: Path,
    *,
    version: str = "1.2.3",
    tag_template: str | None = None,
    project_body: str | None = None,
) -> Path:
    _git(tmp_path, "init")
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text(
        project_body or f'[project]\nname = "myapp"\nversion = "{version}"\n'
    )
    config = backend / "packaging" / "launcher" / "application.yml"
    config.parent.mkdir(parents=True)
    lines = [
        "name: My-App",
        "repository: https://github.com/my-org/myapp.git",
        "configuration: backend/pyproject.toml",
    ]
    if tag_template is not None:
        lines.extend(["release:", f'  tag_template: "{tag_template}"'])
    config.write_text("\n".join(lines) + "\n")
    return config


def test_resolves_raw_project_version_from_nested_config(tmp_path, monkeypatch):
    config = _write_project(tmp_path)
    monkeypatch.chdir(tmp_path / "backend")

    assert release_version.resolve_release_tag(config_path=config) == "1.2.3"


def test_applies_explicit_tag_template(tmp_path):
    config = _write_project(tmp_path, tag_template="v{version}")

    assert release_version.resolve_release_tag(config_path=config) == "v1.2.3"


def test_rejects_explicit_project_tag_mismatch(tmp_path):
    config = _write_project(tmp_path)

    with pytest.raises(release_version.ReleaseVersionError, match="Release tag mismatch"):
        release_version.resolve_release_tag(config_path=config, explicit_tag="v1.2.3")


def test_dynamic_version_allows_explicit_fallback(tmp_path):
    config = _write_project(
        tmp_path,
        project_body='[project]\nname = "myapp"\ndynamic = ["version"]\n',
    )

    assert (
        release_version.resolve_release_tag(
            config_path=config,
            explicit_tag="release-1",
        )
        == "release-1"
    )


def test_missing_explicit_project_toml_is_not_bypassed(tmp_path):
    config = _write_project(tmp_path)
    (tmp_path / "backend" / "pyproject.toml").unlink()

    with pytest.raises(release_version.ReleaseVersionError, match="not found"):
        release_version.resolve_release_tag(config_path=config, explicit_tag="1.2.3")


@pytest.mark.parametrize(
    "template",
    ["prefix", "{version}-{version}", "{version!r}", "{other}"],
)
def test_rejects_invalid_tag_templates(tmp_path, template):
    config = _write_project(tmp_path, tag_template=template)

    with pytest.raises(release_version.ReleaseVersionError, match="tag_template"):
        release_version.resolve_release_tag(config_path=config)


def test_rejects_filename_unsafe_rendered_tag(tmp_path):
    config = _write_project(tmp_path, tag_template="release/{version}")

    with pytest.raises(release_version.ReleaseVersionError, match="filename-safe"):
        release_version.resolve_release_tag(config_path=config)


def test_parses_hyphenated_launcher_tag_from_platform_suffix():
    parsed = release_version.parse_launcher_package_name(
        "My-App-launcher-1.2.3-rc-1-macos-arm64.zip",
        application="My-App",
    )

    assert parsed.tag == "1.2.3-rc-1"
    assert parsed.platform_id == "macos-arm64"


def test_rejects_launcher_platform_mismatch():
    with pytest.raises(release_version.ReleaseVersionError, match="does not match"):
        release_version.parse_launcher_package_name(
            "My-App-launcher-1.2.3-windows-x64.zip",
            application="My-App",
            known_tag="1.2.3",
            platform_id="macos-arm64",
        )
