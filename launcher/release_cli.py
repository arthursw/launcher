"""Developer CLI for launcher signing keys and release manifests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

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

    path: Path
    application: str | None = None
    public_key: str | None = None
    repository: str | None = None
    archive_url: str | None = None


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
        return ReleaseConfig(path=Path(""))

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
