"""Version checking and source downloading."""

import io
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests

from .config import AppConfig, ProxySettings
from .repository import get_api_endpoints

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

        buffer.seek(0)

    except requests.exceptions.ConnectionError as e:
        raise NetworkError(f"Failed to download sources: {e}") from e
    except requests.exceptions.Timeout as e:
        raise NetworkError(f"Download timed out") from e
    except requests.exceptions.HTTPError as e:
        raise NetworkError(f"HTTP error downloading sources: {e}") from e

    # Extract the archive
    try:
        logger.info(f"Extracting sources to {target_path}")
        if progress_callback:
            progress_callback(0, 0, f"Extracting {target_path.name}...")

        with zipfile.ZipFile(buffer, "r") as zf:
            # GitHub/GitLab archives have a root folder, we need to extract contents
            # Get the root folder name (usually owner-repo-hash or similar)
            root_folders = set()
            for name in zf.namelist():
                parts = name.split("/")
                if parts[0]:
                    root_folders.add(parts[0])

            # Create temporary extraction path
            temp_path = target_path.with_suffix(".tmp")
            if temp_path.exists():
                shutil.rmtree(temp_path)

            zf.extractall(temp_path)

            # If there's a single root folder, move its contents up
            if len(root_folders) == 1:
                root_folder = temp_path / list(root_folders)[0]
                if root_folder.is_dir():
                    shutil.move(str(root_folder), str(target_path))
                    temp_path.rmdir()
                else:
                    shutil.move(str(temp_path), str(target_path))
            else:
                shutil.move(str(temp_path), str(target_path))

        logger.info(f"Sources extracted to {target_path}")
        return target_path

    except zipfile.BadZipFile as e:
        raise DownloadError(f"Invalid zip archive: {e}") from e
    except OSError as e:
        raise DownloadError(f"Failed to extract sources: {e}") from e


def update_sources(
    config: AppConfig,
    proxy_settings: Optional[ProxySettings] = None,
    progress_callback: Optional[ProgressCallback] = None,
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

        # Check if sources exist
        sources_path = config.get_sources_path(latest_tag)
        if sources_path.is_dir():
            if config.version == latest_tag:
                logger.info(f"Already up to date: {latest_tag}")
                return False, latest_tag
            else:
                logger.info(f"Sources already exist: {sources_path}")
                # Update config version
                config.version = latest_tag
                config.save()
                return False, latest_tag

        # Download new sources
        logger.info(f"Sources not found, downloading: {sources_path.name}")
        download_and_extract_sources(
            config, latest_tag, proxy_settings, progress_callback
        )

        # Update config version
        config.version = latest_tag
        config.save()

        return True, latest_tag
    else:
        # No auto-update, use existing version
        if not config.version:
            raise UpdaterError("auto_update is false but no version is specified")

        tag_name = config.version

        # Check if sources exist, download if not
        sources_path = config.get_sources_path(tag_name)
        if not sources_path.is_dir():
            logger.info(f"Sources not found, downloading: {sources_path.name}")
            download_and_extract_sources(
                config, tag_name, proxy_settings, progress_callback
            )
            return True, tag_name

        return False, tag_name
