"""Version checking and source downloading."""

import base64
import hashlib
import io
import logging
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable, Optional

import requests
import yaml

from .config import AppConfig, ProxySettings
from .repository import get_api_endpoints
from .state import LauncherState

logger = logging.getLogger(__name__)

# Type alias for progress callback: (current_bytes, total_bytes, message)
ProgressCallback = Callable[[int, int, str], None]


class UpdaterError(Exception):
    """Base exception for updater errors."""

    pass


class NetworkError(UpdaterError):
    """Network-related errors (connection, proxy, etc.)."""

    pass


class DownloadError(UpdaterError):
    """Download or extraction errors."""

    pass


@dataclass(frozen=True)
class LauncherManifest:
    """Verified signed release manifest."""

    schema_version: int
    application: str
    version: str
    archive_sha256: str


def fetch_latest_release(
    config: AppConfig,
    proxy_settings: Optional[ProxySettings] = None,
    timeout: int = 30,
) -> str:
    """Fetch the latest release from the repository.

    Args:
        config: Application configuration
        proxy_settings: Optional proxy settings to use
        timeout: Request timeout in seconds

    Returns:
        The tag name corresponding to the latest release (e.g., "v1.2.3")

    Raises:
        NetworkError: If unable to connect to the API
        UpdaterError: If no release is found or response is invalid
    """
    api_base, releases_endpoint, _ = get_api_endpoints(config)
    url = f"{api_base}{releases_endpoint}"

    proxies = proxy_settings.to_dict() if proxy_settings else None
    verify = proxy_settings.verify if proxy_settings else True

    try:
        logger.info(f"Fetching latest release from {url}")
        response = requests.get(url, proxies=proxies, timeout=timeout, verify=verify)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise NetworkError(f"Failed to connect to {url}: {e}") from e
    except requests.exceptions.Timeout as e:
        raise NetworkError(f"Request timed out: {url}") from e
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response else 'unknown'
        raise NetworkError(f"HTTP error {status_code}: {e}") from e

    data = response.json()

    # GitHub /repos/{owner}/{repo}/releases/latest returns a single object with 'tag_name' field
    if isinstance(data, dict) and "tag_name" in data:
        return data["tag_name"]

    # GitLab /projects/{id}/releases returns a list of releases sorted by released_at
    # Each release has a 'tag_name' field
    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict) and "tag_name" in data[0]:
            return data[0]["tag_name"]

    raise UpdaterError(f"Unexpected release response format: {type(data)}")


def fetch_signed_manifest(
    config: AppConfig,
    version: str,
    proxy_settings: Optional[ProxySettings] = None,
    timeout: int = 30,
) -> LauncherManifest:
    """Download, verify, and parse the signed release manifest."""
    if not config.trust:
        raise UpdaterError("Signed manifest trust configuration is required for updates")

    manifest_url = config.trust.manifest_url.format(version=version)
    signature_url = config.trust.signature_url.format(version=version)
    manifest_bytes = _download_bytes(manifest_url, proxy_settings, timeout)
    signature_bytes = _download_bytes(signature_url, proxy_settings, timeout)
    _verify_ed25519_signature(config.trust.public_key, signature_bytes, manifest_bytes)
    return parse_manifest(manifest_bytes, config.name, version)


def parse_manifest(manifest_bytes: bytes, app_name: str, version: str) -> LauncherManifest:
    """Parse a manifest after its detached signature has been verified."""
    try:
        data = yaml.safe_load(manifest_bytes) or {}
    except yaml.YAMLError as e:
        raise UpdaterError(f"Invalid manifest YAML: {e}") from e

    archive = data.get("archive") or {}
    sha256 = archive.get("sha256")
    if data.get("schema_version") != 1:
        raise UpdaterError("Manifest schema_version must be 1")
    if data.get("application") != app_name:
        raise UpdaterError("Manifest application does not match configuration")
    if data.get("version") != version:
        raise UpdaterError("Manifest version does not match requested version")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise UpdaterError("Manifest archive.sha256 must be a SHA-256 hex digest")
    try:
        int(sha256, 16)
    except ValueError as e:
        raise UpdaterError("Manifest archive.sha256 must be a SHA-256 hex digest") from e

    return LauncherManifest(
        schema_version=1,
        application=app_name,
        version=version,
        archive_sha256=sha256.lower(),
    )


def _download_bytes(
    url: str,
    proxy_settings: Optional[ProxySettings],
    timeout: int,
) -> bytes:
    proxies = proxy_settings.to_dict() if proxy_settings else None
    verify = proxy_settings.verify if proxy_settings else True
    try:
        response = requests.get(url, proxies=proxies, timeout=timeout, verify=verify)
        response.raise_for_status()
        return response.content
    except requests.exceptions.ConnectionError as e:
        raise NetworkError(f"Failed to connect to {url}: {e}") from e
    except requests.exceptions.Timeout as e:
        raise NetworkError(f"Request timed out: {url}") from e
    except requests.exceptions.HTTPError as e:
        raise NetworkError(f"HTTP error downloading {url}: {e}") from e


def _verify_ed25519_signature(public_key_b64: str, signature: bytes, payload: bytes) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:
        raise UpdaterError("cryptography is required for signed manifest verification") from e

    try:
        public_key_bytes = base64.b64decode(public_key_b64, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature, payload)
    except InvalidSignature as e:
        raise UpdaterError("Manifest signature verification failed") from e
    except ValueError as e:
        raise UpdaterError(f"Invalid Ed25519 public key: {e}") from e


def check_sources_exist(config: AppConfig) -> bool:
    """Check if sources for the current version already exist.

    Args:
        config: Application configuration with version set

    Returns:
        True if sources directory exists
    """
    if not config.version:
        return False

    return config.sources_path.is_dir()


def download_and_extract_sources(
    config: AppConfig,
    tag_name: str,
    proxy_settings: Optional[ProxySettings] = None,
    progress_callback: Optional[ProgressCallback] = None,
    expected_sha256: Optional[str] = None,
    timeout: int = 300,
) -> Path:
    """Download and extract source archive for a given tag.

    Args:
        config: Application configuration
        tag_name: Tag to download
        proxy_settings: Optional proxy settings
        progress_callback: Optional callback for progress updates
        timeout: Request timeout in seconds

    Returns:
        Path to extracted sources

    Raises:
        NetworkError: If unable to download
        DownloadError: If extraction fails
    """
    api_base, _, archive_endpoint = get_api_endpoints(config)

    # Replace {ref} placeholder in archive endpoint
    endpoint = archive_endpoint.replace("{ref}", tag_name)
    url = f"{api_base}{endpoint}"

    proxies = proxy_settings.to_dict() if proxy_settings else None
    verify = proxy_settings.verify if proxy_settings else True

    # Prepare target directory
    target_path = config.get_sources_path(tag_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"Downloading sources from {url}")
        if progress_callback:
            progress_callback(0, 0, f"Downloading {target_path.name}...")

        response = requests.get(url, proxies=proxies, timeout=timeout, stream=True, verify=verify)
        response.raise_for_status()

        # Get total size if available
        total_size = int(response.headers.get("content-length", 0))

        # Download to memory
        buffer = io.BytesIO()
        downloaded = 0

        for chunk in response.iter_content(chunk_size=8192):
            buffer.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                progress_callback(downloaded, total_size, f"Downloading {target_path.name}...")

        archive_bytes = buffer.getvalue()

    except requests.exceptions.ConnectionError as e:
        raise NetworkError(f"Failed to download sources: {e}") from e
    except requests.exceptions.Timeout as e:
        raise NetworkError("Download timed out") from e
    except requests.exceptions.HTTPError as e:
        raise NetworkError(f"HTTP error downloading sources: {e}") from e

    if expected_sha256:
        actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            raise DownloadError("Archive SHA-256 does not match signed manifest")

    buffer = io.BytesIO(archive_bytes)

    # Extract the archive
    temp_path = target_path.parent / f".{target_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        logger.info(f"Extracting sources to {target_path}")
        if progress_callback:
            progress_callback(0, 0, f"Extracting {target_path.name}...")

        if target_path.exists():
            raise DownloadError(f"Target sources already exist: {target_path}")

        with zipfile.ZipFile(buffer, "r") as zf:
            infos = zf.infolist()
            _validate_zip_members(infos)
            root_folder = _single_archive_root(infos)
            _extract_zip_members(zf, infos, temp_path, root_folder)

        temp_path.replace(target_path)

        logger.info(f"Sources extracted to {target_path}")
        return target_path

    except zipfile.BadZipFile as e:
        raise DownloadError(f"Invalid zip archive: {e}") from e
    except OSError as e:
        raise DownloadError(f"Failed to extract sources: {e}") from e
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)


def _validate_zip_members(infos: list[zipfile.ZipInfo]) -> None:
    """Reject archive members that could write outside the extraction tree."""
    for info in infos:
        name = info.filename
        if not name:
            raise DownloadError("Archive contains an empty path")
        if "\\" in name:
            raise DownloadError(f"Archive contains unsafe path: {name}")

        path = PurePosixPath(name)
        windows_path = PureWindowsPath(name)
        if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
            raise DownloadError(f"Archive contains absolute path: {name}")
        if any(part == ".." for part in path.parts):
            raise DownloadError(f"Archive contains parent path segment: {name}")

        file_type = (info.external_attr >> 16) & 0o170000
        if file_type:
            if stat.S_ISLNK(file_type):
                raise DownloadError(f"Archive contains symlink: {name}")
            if not (stat.S_ISDIR(file_type) or stat.S_ISREG(file_type)):
                raise DownloadError(f"Archive contains special file: {name}")


def _single_archive_root(infos: list[zipfile.ZipInfo]) -> Optional[str]:
    roots = {
        PurePosixPath(info.filename).parts[0]
        for info in infos
        if PurePosixPath(info.filename).parts
    }
    return next(iter(roots)) if len(roots) == 1 else None


def _extract_zip_members(
    zf: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    destination: Path,
    root_folder: Optional[str],
) -> None:
    for info in infos:
        parts = list(PurePosixPath(info.filename).parts)
        if root_folder and parts and parts[0] == root_folder:
            parts = parts[1:]
        if not parts:
            continue

        target = destination.joinpath(*parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)


def update_sources(
    config: AppConfig,
    proxy_settings: Optional[ProxySettings] = None,
    progress_callback: Optional[ProgressCallback] = None,
    state: Optional[LauncherState] = None,
) -> tuple[bool, str]:
    """Check for updates and download new sources if available.

    Args:
        config: Application configuration
        proxy_settings: Optional proxy settings
        progress_callback: Optional progress callback

    Returns:
        Tuple of (updated: bool, version: str)
        - updated: True if new sources were downloaded
        - version: The current version string

    Raises:
        NetworkError: If unable to check for updates
        DownloadError: If download fails
    """
    if config.auto_update:
        # Fetch latest release
        if progress_callback:
            progress_callback(0, 0, "Checking for updates...")

        latest_tag = fetch_latest_release(config, proxy_settings)

        manifest = fetch_signed_manifest(config, latest_tag, proxy_settings)

        # Check if sources exist
        sources_path = config.get_sources_path(latest_tag)
        if sources_path.is_dir():
            if config.version == latest_tag:
                logger.info(f"Already up to date: {latest_tag}")
                return False, latest_tag
            else:
                logger.info(f"Sources already exist: {sources_path}")
                # Update runtime version only; packaged config remains immutable.
                config.version = latest_tag
                if state:
                    state.version = latest_tag
                    state.save()
                return False, latest_tag

        # Download new sources
        logger.info(f"Sources not found, downloading: {sources_path.name}")
        download_and_extract_sources(
            config,
            latest_tag,
            proxy_settings,
            progress_callback,
            expected_sha256=manifest.archive_sha256,
        )

        # Update runtime version only; packaged config remains immutable.
        config.version = latest_tag
        if state:
            state.version = latest_tag
            state.save()

        return True, latest_tag
    else:
        # No auto-update, use existing version
        if not config.version:
            raise UpdaterError("auto_update is false but no version is specified")

        tag_name = config.version

        # Check if sources exist, download if not
        sources_path = config.get_sources_path(tag_name)
        if not sources_path.is_dir():
            manifest = fetch_signed_manifest(config, tag_name, proxy_settings)
            logger.info(f"Sources not found, downloading: {sources_path.name}")
            download_and_extract_sources(
                config,
                tag_name,
                proxy_settings,
                progress_callback,
                expected_sha256=manifest.archive_sha256,
            )
            if state:
                state.version = tag_name
                state.save()
            return True, tag_name

        return False, tag_name
