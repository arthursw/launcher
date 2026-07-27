"""Shared release-tag resolution and artifact-name parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Iterable

import toml
import yaml


DEFAULT_CONFIG_PATH = Path("packaging/launcher/application.yml")
KNOWN_PLATFORM_IDS = ("macos-arm64", "macos-x64", "windows-x64", "linux-x64")


class ReleaseVersionError(ValueError):
    """Raised when a release tag cannot be resolved safely."""


@dataclass(frozen=True)
class ProjectReleaseTag:
    """Project-derived release-tag details."""

    tag: str | None
    config_path: Path | None
    application: str | None


@dataclass(frozen=True)
class LauncherPackageName:
    """Release tag and platform parsed from a launcher package."""

    tag: str
    platform_id: str


def resolve_release_tag(
    *,
    config_path: Path | None = None,
    explicit_tag: str | None = None,
    artifact_tag: str | None = None,
    required: bool = True,
) -> str | None:
    """Resolve and reconcile a release tag from project, CLI, and artifact inputs."""
    project = project_release_tag(config_path)
    candidates = [
        ("project metadata", project.tag),
        ("explicit release tag", explicit_tag),
        ("artifact filename", artifact_tag),
    ]
    present = [(source, validate_release_tag(tag)) for source, tag in candidates if tag is not None]
    if not present:
        if required:
            raise ReleaseVersionError(
                "Could not infer a release tag. Configure a static [project].version in the app's TOML "
                "configuration file or pass the command's explicit version/tag argument."
            )
        return None

    source, resolved = present[0]
    for other_source, other in present[1:]:
        if other != resolved:
            raise ReleaseVersionError(
                f"Release tag mismatch: {source} resolves to {resolved!r}, "
                f"but {other_source} resolves to {other!r}."
            )
    return resolved


def project_release_tag(config_path: Path | None = None) -> ProjectReleaseTag:
    """Read the configured static project version and render its release tag."""
    resolved_config = _resolve_config_path(config_path)
    if resolved_config is None:
        return ProjectReleaseTag(tag=None, config_path=None, application=None)

    try:
        data = yaml.safe_load(resolved_config.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ReleaseVersionError(f"Invalid launcher config {resolved_config}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseVersionError(f"Launcher config must be a mapping: {resolved_config}")

    application = data.get("name")
    if application is not None and not isinstance(application, str):
        raise ReleaseVersionError("Launcher config name must be a string")

    template = _tag_template(data)
    if "configuration" not in data:
        return ProjectReleaseTag(tag=None, config_path=resolved_config, application=application)
    configuration = data.get("configuration")
    if configuration is None:
        return ProjectReleaseTag(tag=None, config_path=resolved_config, application=application)
    if not isinstance(configuration, str) or not configuration:
        raise ReleaseVersionError("Launcher config configuration must be a non-empty path string or null")
    if Path(configuration).suffix.lower() != ".toml":
        return ProjectReleaseTag(tag=None, config_path=resolved_config, application=application)

    repo_root = _git_repo_root(resolved_config.parent)
    project_path = Path(configuration)
    if project_path.is_absolute():
        raise ReleaseVersionError("Project configuration path must be relative to the Git repository root")
    project_path = (repo_root / project_path).resolve()
    try:
        project_path.relative_to(repo_root)
    except ValueError as exc:
        raise ReleaseVersionError("Project configuration path must stay inside the Git repository") from exc
    if not project_path.is_file():
        raise ReleaseVersionError(f"Configured project TOML file not found: {project_path}")

    try:
        project_data = toml.loads(project_path.read_text())
    except (OSError, toml.TomlDecodeError) as exc:
        raise ReleaseVersionError(f"Invalid project TOML {project_path}: {exc}") from exc
    project = project_data.get("project")
    if project is None:
        return ProjectReleaseTag(tag=None, config_path=resolved_config, application=application)
    if not isinstance(project, dict):
        raise ReleaseVersionError(f"[project] must be a table in {project_path}")

    dynamic = project.get("dynamic", [])
    if dynamic is None:
        dynamic = []
    if not isinstance(dynamic, list) or not all(isinstance(item, str) for item in dynamic):
        raise ReleaseVersionError(f"project.dynamic must be a list of strings in {project_path}")
    version = project.get("version")
    if version is not None and "version" in dynamic:
        raise ReleaseVersionError(f"Project version cannot be both static and dynamic in {project_path}")
    if version is None or "version" in dynamic:
        return ProjectReleaseTag(tag=None, config_path=resolved_config, application=application)
    if not isinstance(version, str) or not version:
        raise ReleaseVersionError(f"project.version must be a non-empty string in {project_path}")

    tag = template.replace("{version}", version)
    return ProjectReleaseTag(
        tag=validate_release_tag(tag),
        config_path=resolved_config,
        application=application,
    )


def validate_release_tag(tag: str) -> str:
    """Require a tag that is valid for Git and safe inside artifact filenames."""
    if not isinstance(tag, str) or not tag:
        raise ReleaseVersionError("Release tag must be a non-empty string")
    if "/" in tag or "\\" in tag:
        raise ReleaseVersionError("Release tag must be a single filename-safe component without '/' or '\\'")
    invalid_characters = {"~", "^", ":", "?", "*", "["}
    if (
        tag == "@"
        or tag.startswith(".")
        or tag.endswith(".")
        or tag.endswith(".lock")
        or ".." in tag
        or "@{" in tag
        or any(ord(character) < 32 or ord(character) == 127 for character in tag)
        or any(character.isspace() or character in invalid_characters for character in tag)
    ):
        raise ReleaseVersionError(f"Invalid Git release tag: {tag!r}")
    return tag


def validate_release_config(data: dict) -> None:
    """Validate release-tag configuration without resolving project metadata."""
    _tag_template(data)


def parse_launcher_package_name(
    filename: str,
    *,
    application: str,
    known_tag: str | None = None,
    platform_id: str | None = None,
    known_platform_ids: Iterable[str] = KNOWN_PLATFORM_IDS,
    allow_custom: bool = False,
) -> LauncherPackageName:
    """Parse a standard launcher package without splitting hyphenated tags."""
    prefix = f"{application}-launcher-"
    if not filename.startswith(prefix):
        if allow_custom and known_tag and platform_id:
            return LauncherPackageName(validate_release_tag(known_tag), platform_id)
        raise ReleaseVersionError(f"Launcher package must start with {prefix!r}: {filename}")
    if not filename.endswith(".zip"):
        raise ReleaseVersionError(f"Launcher package must be a ZIP file: {filename}")

    body = filename[len(prefix) : -4]
    if known_tag is not None:
        known_tag = validate_release_tag(known_tag)
        tag_prefix = f"{known_tag}-"
        if not body.startswith(tag_prefix):
            raise ReleaseVersionError(
                f"Launcher package tag does not match resolved release tag {known_tag!r}: {filename}"
            )
        parsed_platform = body[len(tag_prefix) :]
        if not parsed_platform:
            raise ReleaseVersionError(f"Launcher package platform is missing: {filename}")
        if platform_id and parsed_platform != platform_id:
            raise ReleaseVersionError(
                f"Launcher package platform {parsed_platform!r} does not match --platform {platform_id!r}"
            )
        return LauncherPackageName(known_tag, parsed_platform)

    platform_candidates = (platform_id,) if platform_id else tuple(known_platform_ids)
    for candidate in sorted((item for item in platform_candidates if item), key=len, reverse=True):
        suffix = f"-{candidate}"
        if body.endswith(suffix):
            tag = body[: -len(suffix)]
            if not tag:
                raise ReleaseVersionError(f"Launcher package release tag is missing: {filename}")
            return LauncherPackageName(validate_release_tag(tag), candidate)
    raise ReleaseVersionError(
        f"Cannot infer the launcher package tag and platform from {filename}. "
        "Pass --version and --platform for a custom package name."
    )


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path is not None:
        resolved = config_path.expanduser()
        if not resolved.is_file():
            raise ReleaseVersionError(f"Launcher config file not found: {resolved}")
        return resolved.resolve()
    if DEFAULT_CONFIG_PATH.is_file():
        return DEFAULT_CONFIG_PATH.resolve()
    return None


def _tag_template(data: dict) -> str:
    release = data.get("release") or {}
    if not isinstance(release, dict):
        raise ReleaseVersionError("release must be a mapping")
    template = release.get("tag_template", "{version}")
    if not isinstance(template, str):
        raise ReleaseVersionError("release.tag_template must be a string")
    if template.count("{version}") != 1:
        raise ReleaseVersionError("release.tag_template must contain exactly one {version} placeholder")
    remainder = template.replace("{version}", "")
    if "{" in remainder or "}" in remainder:
        raise ReleaseVersionError("release.tag_template supports only the {version} placeholder")
    return template


def _git_repo_root(start: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ReleaseVersionError("git is required to resolve the configured project version") from exc
    except subprocess.CalledProcessError as exc:
        raise ReleaseVersionError(
            f"Launcher config is not inside a Git repository: {start}"
        ) from exc
    return Path(result.stdout.strip()).resolve()
