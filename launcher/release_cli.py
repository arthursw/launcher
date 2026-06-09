"""Developer CLI for launcher signing keys and release manifests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Sequence
from urllib.parse import urlparse
import zipfile

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .archive_validation import ArchiveValidationError, validate_source_archive
from .repository import parse_repository_url

DEFAULT_DIST_DIR = Path("dist")
DEFAULT_CONFIG_PATH = Path("packaging/launcher/application.yml")
DEFAULT_PRIVATE_KEY = Path("launcher-signing-key.pem")
DEFAULT_MANIFEST_NAME = "launcher-manifest.yml"
DEFAULT_SIGNATURE_NAME = "launcher-manifest.yml.sig"
ARCHIVE_SUFFIXES = (".zip",)


class ReleaseCliError(Exception):
    """Raised when a release CLI command cannot complete."""


@dataclass(frozen=True)
class ReleaseConfig:
    """Small subset of app configuration needed by release signing commands."""

    path: Path | None = None
    application: str | None = None
    public_key: str | None = None
    repository: str | None = None
    archive_url: str | None = None


@dataclass(frozen=True)
class ArchiveBuildCommand:
    """Structured command run before a release archive is created."""

    command: list[str]
    cwd: Path | None = None


@dataclass(frozen=True)
class ArchiveInclude:
    """Generated source path to append to the release archive."""

    source: Path
    destination: PurePosixPath | None = None


@dataclass(frozen=True)
class ReleaseArchiveConfig:
    """Packaging-only config for creating a release archive."""

    build: tuple[ArchiveBuildCommand, ...] = ()
    include: tuple[ArchiveInclude, ...] = ()
    custom_script: Path | None = None


def keygen(private_key_path: Path = DEFAULT_PRIVATE_KEY, force: bool = False) -> str:
    """Generate an Ed25519 private key and return the base64 public key."""
    private_key_path = private_key_path.expanduser()
    if private_key_path.exists() and not force:
        raise ReleaseCliError(f"Private key already exists: {private_key_path}")

    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _add_to_gitignore(private_key_path)
    return public_key_to_base64(private_key.public_key())


def archive_release(
    version: str,
    *,
    config_path: Path | None = None,
    out_dir: Path = DEFAULT_DIST_DIR,
    archive: Path | None = None,
) -> Path:
    """Build the app archive consumed by release sign, verify, and upload."""
    repo_root = git_repo_root()
    release_config = load_release_config_for_archive(config_path, repo_root)
    archive_config = load_release_archive_config(release_config.path, repo_root)

    ref_commit = git_commit_for_ref(version, repo_root)
    head_commit = git_stdout(["rev-parse", "HEAD"], cwd=repo_root)
    if ref_commit != head_commit:
        raise ReleaseCliError(
            f"Release ref {version} ({ref_commit}) does not match HEAD ({head_commit}). "
            "Check out the release commit before building the archive."
        )

    require_clean_tracked_tree(repo_root)
    archive_path = resolve_release_archive_path(
        archive=archive,
        out_dir=out_dir,
        version=version,
        release_config=release_config,
        repo_root=repo_root,
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()

    root = f"{archive_path.stem}/"
    if archive_config.custom_script:
        run_custom_archive_script(archive_config.custom_script, version, archive_path, repo_root)
    else:
        for build_command in archive_config.build:
            run_archive_build_command(build_command, repo_root)

        require_clean_tracked_tree(repo_root)
        run_git(
            [
                "archive",
                "--format=zip",
                f"--prefix={root}",
                f"--output={archive_path}",
                version,
            ],
            cwd=repo_root,
        )
        if archive_config.include:
            append_archive_includes(archive_path, root, archive_config.include, repo_root)

    require_clean_tracked_tree(repo_root)
    if not archive_path.is_file():
        raise ReleaseCliError(f"Archive command did not create archive: {archive_path}")
    validate_release_archive(archive_path)
    return display_path(archive_path)


def load_release_config_for_archive(config_path: Path | None, repo_root: Path) -> ReleaseConfig:
    """Load release config using archive command path rules."""
    resolved = resolve_archive_config_path(config_path, repo_root)
    if not resolved:
        return ReleaseConfig()

    data = yaml.safe_load(resolved.read_text()) or {}
    return ReleaseConfig(
        path=resolved,
        application=data.get("name"),
        repository=data.get("repository"),
    )


def load_release_archive_config(config_path: Path | None, repo_root: Path) -> ReleaseArchiveConfig:
    """Load and validate release.archive packaging config."""
    if not config_path:
        return ReleaseArchiveConfig()

    data = yaml.safe_load(config_path.read_text()) or {}
    release = data.get("release") or {}
    archive_config = release.get("archive") or {}
    if not isinstance(archive_config, dict):
        raise ReleaseCliError("release.archive must be a mapping")

    build = parse_archive_build(archive_config.get("build"), repo_root)
    include = parse_archive_include(archive_config.get("include"), repo_root)
    custom_script = archive_config.get("custom_script")
    if custom_script in ("", None):
        custom_script_path = None
    elif not isinstance(custom_script, str):
        raise ReleaseCliError("release.archive.custom_script must be a path string")
    else:
        custom_script_path = resolve_repo_relative_path(custom_script, repo_root, field="custom_script")

    if custom_script_path and (build or include):
        raise ReleaseCliError("release.archive.custom_script is mutually exclusive with build and include")

    return ReleaseArchiveConfig(build=build, include=include, custom_script=custom_script_path)


def parse_archive_build(value: object, repo_root: Path) -> tuple[ArchiveBuildCommand, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise ReleaseCliError("release.archive.build must be a list")

    commands = []
    for item in value:
        if not isinstance(item, dict):
            raise ReleaseCliError("release.archive.build entries must be mappings")
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
            raise ReleaseCliError("release.archive.build[].command must be a non-empty list of strings")
        cwd_value = item.get("cwd")
        cwd = None
        if cwd_value is not None:
            if not isinstance(cwd_value, str):
                raise ReleaseCliError("release.archive.build[].cwd must be a path string")
            cwd = resolve_repo_relative_path(cwd_value, repo_root, field="cwd")
        commands.append(ArchiveBuildCommand(command=command, cwd=cwd))
    return tuple(commands)


def parse_archive_include(value: object, repo_root: Path) -> tuple[ArchiveInclude, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise ReleaseCliError("release.archive.include must be a list")

    includes = []
    for item in value:
        if isinstance(item, str):
            includes.append(
                ArchiveInclude(
                    source=resolve_repo_relative_path(item, repo_root, field="include source"),
                    destination=None,
                )
            )
        elif isinstance(item, dict):
            source = item.get("source")
            destination = item.get("destination")
            if not isinstance(source, str) or not source:
                raise ReleaseCliError("release.archive.include[].source must be a path string")
            if not isinstance(destination, str) or not destination:
                raise ReleaseCliError("release.archive.include[].destination must be a path string")
            includes.append(
                ArchiveInclude(
                    source=resolve_repo_relative_path(source, repo_root, field="include source"),
                    destination=validate_archive_destination(destination),
                )
            )
        else:
            raise ReleaseCliError("release.archive.include entries must be path strings or mappings")
    return tuple(includes)


def sign_release(
    *,
    application: str | None = None,
    version: str | None = None,
    archive: Path | None = None,
    archive_url: str | None = None,
    private_key_path: Path = DEFAULT_PRIVATE_KEY,
    out_dir: Path = DEFAULT_DIST_DIR,
    config_path: Path | None = None,
) -> tuple[Path, Path, str]:
    """Create and sign a release manifest.

    Returns:
        Tuple of manifest path, signature path, and public key.
    """
    release_config = load_release_config(config_path)
    application = application or release_config.application
    if not application:
        raise ReleaseCliError("Application name is required. Pass --application or provide a config file.")

    archive = infer_archive(archive, out_dir, version)
    version = version or infer_version_from_archive(archive)
    if not version:
        raise ReleaseCliError(
            f"Could not infer release version from archive name: {archive}. "
            "Pass --version, or rename the archive so its filename contains the release version "
            "(for example: myapp-v1.2.3.zip)."
        )
    validate_release_archive(archive)

    private_key = load_private_key(private_key_path)
    archive_sha256 = sha256_file(archive)
    resolved_archive_url = resolve_archive_url(
        explicit_archive_url=archive_url,
        config_archive_url=release_config.archive_url,
        repository=release_config.repository,
        version=version,
        archive_name=archive.name,
    )
    manifest = {
        "schema_version": 2,
        "application": application,
        "version": version,
        "archive": {
            "name": archive.name,
            "url": resolved_archive_url,
            "sha256": archive_sha256,
        },
    }
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False).encode("utf-8")
    signature = private_key.sign(manifest_bytes)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / DEFAULT_MANIFEST_NAME
    signature_path = out_dir / DEFAULT_SIGNATURE_NAME
    manifest_path.write_bytes(manifest_bytes)
    signature_path.write_bytes(signature)
    return manifest_path, signature_path, public_key_to_base64(private_key.public_key())


def verify_release(
    *,
    manifest_path: Path | None = None,
    signature_path: Path | None = None,
    archive: Path | None = None,
    public_key: str | None = None,
    out_dir: Path = DEFAULT_DIST_DIR,
    config_path: Path | None = None,
) -> dict:
    """Verify a release manifest, detached signature, and archive hash."""
    manifest_path = manifest_path or out_dir / DEFAULT_MANIFEST_NAME
    signature_path = signature_path or out_dir / DEFAULT_SIGNATURE_NAME
    if not manifest_path.is_file():
        raise ReleaseCliError(_missing_release_asset_message("manifest", manifest_path))
    if not signature_path.is_file():
        raise ReleaseCliError(_missing_release_asset_message("signature", signature_path))

    release_config = load_release_config(config_path)
    public_key = public_key or release_config.public_key
    if not public_key:
        raise ReleaseCliError("Public key is required. Pass --public-key or provide a config with trust.public_key.")

    manifest_bytes = manifest_path.read_bytes()
    signature = signature_path.read_bytes()
    verify_signature(public_key, signature, manifest_bytes)

    manifest = yaml.safe_load(manifest_bytes) or {}
    validate_release_manifest(manifest)
    archive = infer_archive(archive, out_dir, manifest.get("version"))
    manifest_archive = manifest["archive"]
    if archive.name != manifest_archive["name"]:
        raise ReleaseCliError(
            f"Archive name mismatch: manifest names {manifest_archive['name']}, "
            f"but local archive is {archive.name}"
        )
    expected_sha256 = manifest_archive["sha256"].lower()
    actual_sha256 = sha256_file(archive)
    if actual_sha256 != expected_sha256:
        raise ReleaseCliError(
            f"Archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    validate_release_archive(archive)
    return manifest


def _missing_release_asset_message(kind: str, path: Path) -> str:
    display_kind = "manifest" if kind == "manifest" else "signature"
    return (
        f"Release {display_kind} not found: {path}\n"
        "Create and publish Launcher release metadata with:\n"
        "  launcher release archive VERSION\n"
        "  launcher release sign\n"
        "  launcher release verify\n"
        "  launcher release upload\n"
        "If your archive or output directory is not the default `dist/`, pass "
        "`--archive` and `--out` to the release commands."
    )


def validate_release_archive(archive: Path) -> None:
    """Validate that the release archive can be safely extracted at runtime."""
    try:
        validate_source_archive(archive)
    except ArchiveValidationError as e:
        raise ReleaseCliError(
            f"Archive is not safe for Launcher extraction: {e}\n"
            "Remove unsafe symlinks or special files from the release archive. "
            "Absolute symlinks are rejected because they can point outside the downloaded app sources."
        ) from e


def upload_release(
    *,
    manifest_path: Path | None = None,
    signature_path: Path | None = None,
    archive: Path | None = None,
    public_key: str | None = None,
    out_dir: Path = DEFAULT_DIST_DIR,
    config_path: Path | None = None,
    repository: str | None = None,
    dry_run: bool = False,
) -> list[list[str]]:
    """Verify release assets and upload them using gh or glab.

    Returns:
        Commands that were run, or would be run in dry-run mode.
    """
    manifest = verify_release(
        manifest_path=manifest_path,
        signature_path=signature_path,
        archive=archive,
        public_key=public_key,
        out_dir=out_dir,
        config_path=config_path,
    )
    manifest_path = manifest_path or out_dir / DEFAULT_MANIFEST_NAME
    signature_path = signature_path or out_dir / DEFAULT_SIGNATURE_NAME

    release_config = load_release_config(config_path)
    repository = repository or release_config.repository
    provider = detect_repository_provider(repository)
    if not provider:
        raise ReleaseCliError("Cannot detect GitHub or GitLab repository. Pass --repository or configure repository.")

    version = manifest["version"]
    archive = infer_archive(archive, out_dir, version)
    if archive.name != manifest["archive"]["name"]:
        raise ReleaseCliError(
            f"Archive name mismatch: manifest names {manifest['archive']['name']}, "
            f"but local archive is {archive.name}"
        )
    if provider == "github":
        github_message = (
            "GitHub upload requires the GitHub CLI (`gh`). Install it from "
            "https://github.com/cli/cli#installation or upload the files manually "
            "from the GitHub release page."
        )
        command = [
            require_executable("gh", github_message),
            "release",
            "upload",
            version,
            str(archive),
            str(manifest_path),
            str(signature_path),
            "--clobber",
        ]
    else:
        gitlab_message = (
            "GitLab upload requires the GitLab CLI (`glab`). Install it from "
            "https://gitlab.com/gitlab-org/cli/#installation or upload the files "
            "manually from the GitLab release page."
        )
        command = [
            require_executable("glab", gitlab_message),
            "release",
            "upload",
            version,
            str(archive),
            str(manifest_path),
            str(signature_path),
            "--use-package-registry",
        ]

    if dry_run:
        return [command]

    subprocess.run(command, check=True)
    return [command]


def load_release_config(config_path: Path | None) -> ReleaseConfig:
    """Load the small config subset used by signing commands."""
    resolved = resolve_config_path(config_path)
    if not resolved:
        return ReleaseConfig()

    data = yaml.safe_load(resolved.read_text()) or {}
    trust = data.get("trust") or {}
    public_key = trust.get("public_key")
    if public_key and public_key.startswith("<"):
        public_key = None
    return ReleaseConfig(
        path=resolved,
        application=data.get("name"),
        public_key=public_key,
        repository=data.get("repository"),
        archive_url=trust.get("archive_url"),
    )


def resolve_config_path(config_path: Path | None) -> Path | None:
    """Resolve an explicit config, or infer one from the current directory."""
    if config_path:
        path = config_path.expanduser()
        if not path.exists():
            raise ReleaseCliError(f"Config file not found: {path}")
        return path

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    return None


def resolve_archive_config_path(config_path: Path | None, repo_root: Path) -> Path | None:
    """Resolve config paths for archive creation relative to the git root."""
    if config_path:
        path = config_path.expanduser()
        if not path.is_absolute():
            path = repo_root / path
        if not path.exists():
            raise ReleaseCliError(f"Config file not found: {display_path(path)}")
        return path

    path = repo_root / DEFAULT_CONFIG_PATH
    return path if path.exists() else None


def git_repo_root() -> Path:
    """Return the repository root for the current working directory."""
    try:
        return Path(git_stdout(["rev-parse", "--show-toplevel"])).resolve()
    except ReleaseCliError as e:
        raise ReleaseCliError("launcher release archive must be run inside a git repository") from e


def git_commit_for_ref(ref: str, repo_root: Path) -> str:
    try:
        return git_stdout(["rev-parse", f"{ref}^{{commit}}"], cwd=repo_root)
    except ReleaseCliError as e:
        raise ReleaseCliError(f"Unknown git ref: {ref}") from e


def require_clean_tracked_tree(repo_root: Path) -> None:
    """Require tracked files and the index to be clean, allowing untracked files."""
    status = git_stdout(["status", "--porcelain", "--untracked-files=no"], cwd=repo_root)
    if status:
        raise ReleaseCliError(
            "Git tracked files are dirty. Commit or revert tracked changes before building a release archive."
        )


def run_git(args: list[str], *, cwd: Path) -> None:
    command = ["git", *args]
    try:
        subprocess.run(command, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise ReleaseCliError("git is required to build release archives") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        message = f"git {' '.join(args)} failed"
        if detail:
            message = f"{message}: {detail}"
        raise ReleaseCliError(message) from e


def git_stdout(args: list[str], *, cwd: Path | None = None) -> str:
    command = ["git", *args]
    try:
        result = subprocess.run(command, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise ReleaseCliError("git is required to build release archives") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        message = f"git {' '.join(args)} failed"
        if detail:
            message = f"{message}: {detail}"
        raise ReleaseCliError(message) from e
    return result.stdout.strip()


def resolve_release_archive_path(
    *,
    archive: Path | None,
    out_dir: Path,
    version: str,
    release_config: ReleaseConfig,
    repo_root: Path,
) -> Path:
    if archive:
        archive_path = archive.expanduser()
        if not archive_path.is_absolute():
            archive_path = repo_root / archive_path
        return archive_path

    out_path = out_dir.expanduser()
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    return out_path / f"{release_archive_basename(release_config, repo_root)}-{version}.zip"


def release_archive_basename(release_config: ReleaseConfig, repo_root: Path) -> str:
    if release_config.repository:
        try:
            return sanitize_archive_name(parse_repository_url(release_config.repository.rstrip("/").removesuffix(".git")).repo)
        except ValueError:
            pass
        repo_name = fallback_repository_name(release_config.repository)
        if repo_name:
            return sanitize_archive_name(repo_name)

    repo_name = repo_root.name
    if repo_name:
        return sanitize_archive_name(repo_name)
    if release_config.application:
        return sanitize_archive_name(release_config.application)
    return "app"


def sanitize_archive_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_")
    return sanitized or "app"


def fallback_repository_name(repository: str) -> str:
    cleaned = repository.rstrip("/").removesuffix(".git")
    if ":" in cleaned and "/" not in cleaned.rsplit(":", 1)[0]:
        cleaned = cleaned.rsplit(":", 1)[1]
    return cleaned.rsplit("/", 1)[-1]


def resolve_repo_relative_path(value: str, repo_root: Path, *, field: str) -> Path:
    if "\\" in value:
        raise ReleaseCliError(f"Unsafe {field} path: {value}")
    path = Path(value).expanduser()
    windows_path = PureWindowsPath(value)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ReleaseCliError(f"Unsafe {field} path: {value}")
    if any(part == ".." for part in PurePosixPath(value).parts):
        raise ReleaseCliError(f"Unsafe {field} path: {value}")
    return repo_root / path


def validate_archive_destination(value: str) -> PurePosixPath:
    if "\\" in value:
        raise ReleaseCliError(f"Unsafe include destination: {value}")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ReleaseCliError(f"Unsafe include destination: {value}")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ReleaseCliError(f"Unsafe include destination: {value}")
    return path


def run_archive_build_command(build_command: ArchiveBuildCommand, repo_root: Path) -> None:
    cwd = build_command.cwd or repo_root
    try:
        subprocess.run(build_command.command, cwd=cwd, shell=False, check=True)
    except FileNotFoundError as e:
        raise ReleaseCliError(f"Build command not found: {build_command.command[0]}") from e
    except subprocess.CalledProcessError as e:
        raise ReleaseCliError(f"Build command failed with exit code {e.returncode}: {build_command.command}") from e


def run_custom_archive_script(script: Path, version: str, archive_path: Path, repo_root: Path) -> None:
    if not script.is_file():
        raise ReleaseCliError(f"Custom archive script not found: {display_path(script)}")
    try:
        subprocess.run([sys.executable, str(script), version, str(archive_path)], cwd=repo_root, shell=False, check=True)
    except subprocess.CalledProcessError as e:
        raise ReleaseCliError(f"Custom archive script failed with exit code {e.returncode}: {display_path(script)}") from e


def append_archive_includes(
    archive_path: Path,
    root: str,
    includes: tuple[ArchiveInclude, ...],
    repo_root: Path,
) -> None:
    with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        existing = set(zf.namelist())
        for include in includes:
            if not include.source.exists():
                raise ReleaseCliError(f"Include source not found: {display_path(include.source)}")
            require_include_source_within_repo(include.source, repo_root)
            for source_path, destination in iter_include_files(include, repo_root):
                require_include_source_within_repo(source_path, repo_root)
                member = f"{root}{destination.as_posix()}"
                if member in existing:
                    raise ReleaseCliError(f"Duplicate archive member: {member}")
                zf.write(source_path, member)
                existing.add(member)


def iter_include_files(include: ArchiveInclude, repo_root: Path) -> list[tuple[Path, PurePosixPath]]:
    source = include.source
    if source.is_file():
        destination = include.destination or PurePosixPath(source.relative_to(repo_root).as_posix())
        return [(source, destination)]

    if not source.is_dir():
        raise ReleaseCliError(f"Include source is not a file or directory: {display_path(source)}")

    files = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if include.destination:
            destination = include.destination / path.relative_to(source).as_posix()
        else:
            destination = PurePosixPath(path.relative_to(repo_root).as_posix())
        files.append((path, destination))
    return files


def require_include_source_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve(strict=True).relative_to(repo_root.resolve())
    except (FileNotFoundError, ValueError) as e:
        raise ReleaseCliError(f"Include source must stay inside the repository: {display_path(path)}") from e


def display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def infer_archive(archive: Path | None, dist_dir: Path, version: str | None) -> Path:
    """Resolve an archive path, using dist/ by default."""
    if archive:
        archive = archive.expanduser()
        if not archive.is_file():
            raise ReleaseCliError(f"Archive not found: {archive}")
        return archive

    dist_dir = dist_dir.expanduser()
    archives = [path for path in sorted(dist_dir.iterdir()) if _is_archive(path)] if dist_dir.exists() else []
    if version:
        matching = [path for path in archives if version in path.name]
        if len(matching) == 1:
            return matching[0]
        if len(matching) > 1:
            names = ", ".join(str(path) for path in matching)
            raise ReleaseCliError(f"Multiple archives match version {version}: {names}")

    if len(archives) == 1:
        return archives[0]
    if not archives:
        raise ReleaseCliError(f"No release archive found in {dist_dir}. Pass --archive.")

    names = ", ".join(str(path) for path in archives)
    raise ReleaseCliError(f"Multiple archives found. Pass --archive. Candidates: {names}")


def infer_version_from_archive(archive: Path) -> str | None:
    """Infer a version such as v1.2.3 or 1.2.3 from an archive filename."""
    name = archive.name
    for suffix in ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    matches = re.findall(r"v?\d+(?:\.\d+)+(?:[A-Za-z0-9._-]*)?", name)
    return matches[-1].strip("._-") if matches else None


def resolve_archive_url(
    *,
    explicit_archive_url: str | None,
    config_archive_url: str | None,
    repository: str | None,
    version: str,
    archive_name: str,
) -> str:
    """Resolve the release archive URL written into the signed manifest."""
    if explicit_archive_url:
        return _format_archive_url(explicit_archive_url, version, archive_name)
    if config_archive_url:
        return _format_archive_url(config_archive_url, version, archive_name)
    if repository:
        return _default_archive_url(repository, version, archive_name)
    raise ReleaseCliError(
        "Archive URL is required. Pass --archive-url, configure trust.archive_url, "
        "or configure repository so Launcher can infer the release asset URL."
    )


def _format_archive_url(template: str, version: str, archive_name: str) -> str:
    try:
        url = template.format(version=version, archive_name=archive_name)
    except KeyError as e:
        raise ReleaseCliError(
            f"Archive URL contains unsupported placeholder {{{e.args[0]}}}. "
            "Supported placeholders are {version} and {archive_name}."
        ) from e
    except ValueError as e:
        raise ReleaseCliError(f"Archive URL template is invalid: {e}") from e

    if "{" in url or "}" in url:
        raise ReleaseCliError(
            "Archive URL still contains unresolved placeholders after formatting. "
            "Supported placeholders are {version} and {archive_name}."
        )
    _validate_archive_url(url)
    return url


def _default_archive_url(repository: str, version: str, archive_name: str) -> str:
    try:
        repo = parse_repository_url(repository.rstrip("/").removesuffix(".git"))
    except ValueError as e:
        raise ReleaseCliError(
            "Cannot infer archive URL from repository. Pass --archive-url or configure trust.archive_url."
        ) from e

    owner_repo = f"{repo.owner}/{repo.repo}"
    if "gitlab" in repo.host.lower():
        base = f"https://{repo.host}/{owner_repo}/-/releases/{version}/downloads"
    else:
        base = f"https://{repo.host}/{owner_repo}/releases/download/{version}"
    return f"{base}/{archive_name}"


def _validate_archive_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReleaseCliError("Archive URL must be an absolute http(s) URL")


def validate_release_manifest(manifest: dict) -> None:
    """Validate the local release manifest schema before upload."""
    if not isinstance(manifest, dict):
        raise ReleaseCliError("Release manifest must be a mapping")
    if manifest.get("schema_version") != 2:
        raise ReleaseCliError("Release manifest schema_version must be 2")
    if not isinstance(manifest.get("application"), str) or not manifest["application"]:
        raise ReleaseCliError("Release manifest application is required")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ReleaseCliError("Release manifest version is required")

    archive = manifest.get("archive")
    if not isinstance(archive, dict):
        raise ReleaseCliError("Release manifest archive must be a mapping")
    for field in ("name", "url", "sha256"):
        if not isinstance(archive.get(field), str) or not archive[field]:
            raise ReleaseCliError(f"Release manifest archive.{field} is required")
    if len(archive["sha256"]) != 64:
        raise ReleaseCliError("Release manifest archive.sha256 must be a SHA-256 hex digest")
    try:
        int(archive["sha256"], 16)
    except ValueError as e:
        raise ReleaseCliError("Release manifest archive.sha256 must be a SHA-256 hex digest") from e


def load_private_key(private_key_path: Path) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from PEM."""
    try:
        private_key = serialization.load_pem_private_key(
            private_key_path.expanduser().read_bytes(),
            password=None,
        )
    except FileNotFoundError as e:
        raise ReleaseCliError(
            f"Private key not found: {private_key_path}. Run `launcher release keygen` first."
        ) from e
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ReleaseCliError("Private key must be an Ed25519 PEM key")
    return private_key


def verify_signature(public_key_b64: str, signature: bytes, payload: bytes) -> None:
    """Verify an Ed25519 detached signature."""
    try:
        public_key_bytes = base64.b64decode(public_key_b64, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, payload)
    except InvalidSignature as e:
        raise ReleaseCliError("Manifest signature verification failed") from e
    except ValueError as e:
        raise ReleaseCliError(f"Invalid public key: {e}") from e


def public_key_to_base64(public_key: Ed25519PublicKey) -> str:
    """Return the raw Ed25519 public key as base64 text."""
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(public_key_bytes).decode("ascii")


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_repository_provider(repository: str | None) -> str | None:
    """Return github, gitlab, or None for a repository URL."""
    if not repository:
        return None
    if repository.startswith("git@"):
        host = repository.split("@", 1)[1].split(":", 1)[0].lower()
    else:
        host = urlparse(repository).hostname or ""
        host = host.lower()

    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"
    return None


def require_executable(name: str, message: str) -> str:
    """Return executable path or raise a helpful error."""
    executable = shutil.which(name)
    if executable:
        return executable
    raise ReleaseCliError(
        f"{message}\n\n"
        f"Manual upload: upload the app archive, {DEFAULT_MANIFEST_NAME}, and "
        f"{DEFAULT_SIGNATURE_NAME} as release assets. See docs/security.md for details."
    )


def _is_archive(path: Path) -> bool:
    return path.is_file() and any(path.name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _add_to_gitignore(path: Path) -> None:
    """Add the generated private-key path to .gitignore when possible."""
    gitignore = Path(".gitignore")
    try:
        relative_path = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return

    entry = relative_path.as_posix()
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    if entry in existing:
        return

    prefix = "\n" if existing and existing[-1] else ""
    with gitignore.open("a") as f:
        f.write(f"{prefix}\n# Launcher signing keys\n{entry}\n")


def build_parser(prog: str = "launcher release") -> argparse.ArgumentParser:
    """Build the release CLI parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Prepare, verify, and upload launcher release assets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen_parser = subparsers.add_parser("keygen", help="Generate an Ed25519 signing key")
    keygen_parser.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    keygen_parser.add_argument("--force", action="store_true", help="Overwrite an existing private key")

    archive_parser = subparsers.add_parser("archive", help="Build the app archive for release signing")
    archive_parser.add_argument("version", help="Release version or git ref, for example v1.2.3")
    archive_parser.add_argument("--config", type=Path, help=f"Launcher app config (default: {DEFAULT_CONFIG_PATH})")
    archive_parser.add_argument("--out", type=Path, default=DEFAULT_DIST_DIR, help="Output directory")
    archive_parser.add_argument("--archive", type=Path, help="Exact output archive path")

    sign_parser = subparsers.add_parser("sign", help="Create launcher-manifest.yml and signature")
    sign_parser.add_argument("--config", type=Path, help="App config to infer the application name from")
    sign_parser.add_argument("--application", help="Application name written to the manifest")
    sign_parser.add_argument("--version", help="Release version; inferred from archive filename by default")
    sign_parser.add_argument("--archive", type=Path, help="Release app archive; inferred from dist/ by default")
    sign_parser.add_argument("--archive-url", help="Archive URL written to the signed manifest")
    sign_parser.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    sign_parser.add_argument("--out", type=Path, default=DEFAULT_DIST_DIR, help="Output directory")

    verify_parser = subparsers.add_parser("verify", help="Verify manifest signature and archive hash")
    verify_parser.add_argument("--config", type=Path, help="App config to infer trust.public_key from")
    verify_parser.add_argument("--public-key", help="Base64 Ed25519 public key")
    verify_parser.add_argument("--manifest", type=Path, help="Manifest path; defaults to dist/launcher-manifest.yml")
    verify_parser.add_argument("--signature", type=Path, help="Signature path; defaults to dist/launcher-manifest.yml.sig")
    verify_parser.add_argument("--archive", type=Path, help="Release app archive; inferred from dist/ by default")
    verify_parser.add_argument("--out", type=Path, default=DEFAULT_DIST_DIR, help="Directory containing default release assets")

    upload_parser = subparsers.add_parser("upload", help="Verify and upload manifest assets with gh or glab")
    upload_parser.add_argument("--config", type=Path, help="App config to infer repository and trust.public_key from")
    upload_parser.add_argument("--repository", help="Repository URL used to detect GitHub or GitLab")
    upload_parser.add_argument("--public-key", help="Base64 Ed25519 public key")
    upload_parser.add_argument("--manifest", type=Path, help="Manifest path; defaults to dist/launcher-manifest.yml")
    upload_parser.add_argument("--signature", type=Path, help="Signature path; defaults to dist/launcher-manifest.yml.sig")
    upload_parser.add_argument("--archive", type=Path, help="Release app archive; inferred from dist/ by default")
    upload_parser.add_argument("--out", type=Path, default=DEFAULT_DIST_DIR, help="Directory containing default release assets")
    upload_parser.add_argument("--dry-run", action="store_true", help="Print the upload command without running it")

    return parser


def main(argv: Sequence[str] | None = None, prog: str = "launcher release") -> int:
    """Run the release CLI."""
    parser = build_parser(prog)
    args = parser.parse_args(argv)

    try:
        if args.command == "keygen":
            public_key = keygen(args.private_key, force=args.force)
            print(f"Private key written to: {args.private_key}")
            print("The private key path was added to .gitignore.")
            print()
            print("Add this public key to your app config:")
            print("trust:")
            print("  mode: signed_manifest")
            print(f'  public_key: "{public_key}"')
            return 0

        if args.command == "archive":
            archive_path = archive_release(
                args.version,
                config_path=args.config,
                out_dir=args.out,
                archive=args.archive,
            )
            print(f"Archive written to: {archive_path}")
            return 0

        if args.command == "sign":
            manifest_path, signature_path, public_key = sign_release(
                application=args.application,
                version=args.version,
                archive=args.archive,
                archive_url=args.archive_url,
                private_key_path=args.private_key,
                out_dir=args.out,
                config_path=args.config,
            )
            print(f"Manifest written to: {manifest_path}")
            print(f"Signature written to: {signature_path}")
            print(f"Public key: {public_key}")
            return 0

        if args.command == "verify":
            manifest = verify_release(
                manifest_path=args.manifest,
                signature_path=args.signature,
                archive=args.archive,
                public_key=args.public_key,
                out_dir=args.out,
                config_path=args.config,
            )
            print(f"OK: {manifest['application']} {manifest['version']}")
            return 0

        if args.command == "upload":
            commands = upload_release(
                manifest_path=args.manifest,
                signature_path=args.signature,
                archive=args.archive,
                public_key=args.public_key,
                out_dir=args.out,
                config_path=args.config,
                repository=args.repository,
                dry_run=args.dry_run,
            )
            for command in commands:
                print(" ".join(command))
            return 0
    except ReleaseCliError as e:
        parser.exit(1, f"Error: {e}\n")

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
