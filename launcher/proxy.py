"""Proxy detection from conda/mamba configuration files."""

import logging
import os
import platform
from pathlib import Path
from typing import Optional

import yaml

from .config import ProxySettings

logger = logging.getLogger(__name__)

_SSL_CERT_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def get_ssl_cert_from_environment() -> Optional[str]:
    """Get SSL certificate file path from environment variables.

    Checks SSL_CERT_FILE, REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE (in that order).

    Returns:
        Path to certificate file if found and exists, None otherwise
    """
    for var in _SSL_CERT_ENV_VARS:
        value = os.environ.get(var)
        if value and Path(value).is_file():
            logger.info(f"Found SSL certificate from {var}: {value}")
            return value
    return None


def _get_conda_config_paths() -> list[Path]:
    """Get all possible conda/mamba configuration file paths.

    Returns:
        List of paths to check for proxy settings
    """
    # System-wide paths
    if platform.system() == "Windows":
        system_paths = [
            Path("C:/ProgramData/conda/.condarc"),
            Path("C:/ProgramData/conda/condarc"),
            Path("C:/ProgramData/conda/condarc.d"),
            Path("C:/ProgramData/conda/.mambarc"),
        ]
    else:
        system_paths = [
            Path("/etc/conda/.condarc"),
            Path("/etc/conda/condarc"),
            Path("/etc/conda/condarc.d/"),
            Path("/etc/conda/.mambarc"),
            Path("/var/lib/conda/.condarc"),
            Path("/var/lib/conda/condarc"),
            Path("/var/lib/conda/condarc.d/"),
            Path("/var/lib/conda/.mambarc"),
        ]

    # User paths (with env var expansion)
    user_paths = []

    # CONDA_ROOT paths
    conda_root = os.environ.get("CONDA_ROOT")
    if conda_root:
        root = Path(conda_root)
        user_paths.extend([
            root / ".condarc",
            root / "condarc",
            root / "condarc.d",
        ])

    # MAMBA_ROOT_PREFIX paths
    mamba_root = os.environ.get("MAMBA_ROOT_PREFIX")
    if mamba_root:
        root = Path(mamba_root)
        user_paths.extend([
            root / ".condarc",
            root / "condarc",
            root / "condarc.d",
            root / ".mambarc",
        ])

    # XDG_CONFIG_HOME paths
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        config = Path(xdg_config)
        user_paths.extend([
            config / "conda/.condarc",
            config / "conda/condarc",
            config / "conda/condarc.d",
        ])

    # Home directory paths
    home = Path.home()
    user_paths.extend([
        home / ".config/conda/.condarc",
        home / ".config/conda/condarc",
        home / ".config/conda/condarc.d",
        home / ".conda/.condarc",
        home / ".conda/condarc",
        home / ".conda/condarc.d",
        home / ".condarc",
        home / ".mambarc",
    ])

    # CONDA_PREFIX paths
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        prefix = Path(conda_prefix)
        user_paths.extend([
            prefix / ".condarc",
            prefix / "condarc",
            prefix / "condarc.d",
        ])

    # CONDARC and MAMBARC env vars
    condarc = os.environ.get("CONDARC")
    if condarc:
        user_paths.append(Path(condarc))

    mambarc = os.environ.get("MAMBARC")
    if mambarc:
        user_paths.append(Path(mambarc))

    # Micromamba paths relative to current directory
    user_paths.extend([
        Path("micromamba/.condarc"),
        Path("micromamba/condarc"),
        Path("micromamba/condarc.d"),
        Path("micromamba/.mambarc"),
    ])

    return system_paths + user_paths


def _parse_proxy_from_yaml(path: Path) -> Optional[ProxySettings]:
    """Parse proxy settings from a YAML config file.

    Reads ``proxy_servers`` for HTTP/HTTPS proxy URLs, and ``ssl_verify``
    for a custom CA certificate path (string pointing to an existing file).

    Args:
        path: Path to the config file

    Returns:
        ProxySettings if found, None otherwise
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            return None

        http_proxy = None
        https_proxy = None
        ssl_cert_file = None

        # Check for proxy_servers section
        proxy_servers = data.get("proxy_servers", {})
        if proxy_servers:
            http_proxy = proxy_servers.get("http")
            https_proxy = proxy_servers.get("https")

        # Check ssl_verify — only use it if it's a string path to an existing file
        ssl_verify = data.get("ssl_verify")
        if isinstance(ssl_verify, str) and Path(ssl_verify).is_file():
            ssl_cert_file = ssl_verify
            logger.info(f"Found ssl_verify certificate in {path}: {ssl_verify}")

        if http_proxy or https_proxy or ssl_cert_file:
            logger.info(f"Found proxy/SSL settings in {path}")
            return ProxySettings(http=http_proxy, https=https_proxy, ssl_cert_file=ssl_cert_file)

        return None
    except Exception as e:
        logger.debug(f"Could not parse {path}: {e}")
        return None


def _parse_proxy_from_dir(dir_path: Path) -> Optional[ProxySettings]:
    """Parse proxy settings from a condarc.d directory.

    Args:
        dir_path: Path to the condarc.d directory

    Returns:
        ProxySettings if found, None otherwise
    """
    if not dir_path.is_dir():
        return None

    # Check all yaml files in the directory
    for yaml_file in sorted(dir_path.glob("*.yaml")) + sorted(dir_path.glob("*.yml")):
        result = _parse_proxy_from_yaml(yaml_file)
        if result:
            return result

    return None


def detect_proxy_settings() -> Optional[ProxySettings]:
    """Detect proxy settings from conda/mamba configuration files.

    Searches through all known conda/mamba config file locations
    and returns the first proxy settings found.

    Returns:
        ProxySettings if found, None otherwise
    """
    logger.info("Searching for proxy settings in conda/mamba configs")

    for path in _get_conda_config_paths():
        if path.suffix == ".d" or str(path).endswith(".d/"):
            # It's a directory
            result = _parse_proxy_from_dir(path)
        elif path.is_file():
            result = _parse_proxy_from_yaml(path)
        else:
            continue

        if result:
            return result

    logger.info("No proxy settings found in conda/mamba configs")
    return None


def get_proxy_from_environment() -> Optional[ProxySettings]:
    """Get proxy settings from environment variables.

    Checks HTTP_PROXY, HTTPS_PROXY, http_proxy, https_proxy for proxy URLs
    and SSL_CERT_FILE, REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE for certificate path.

    Returns:
        ProxySettings if found, None otherwise
    """
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    ssl_cert_file = get_ssl_cert_from_environment()

    if http_proxy or https_proxy or ssl_cert_file:
        logger.info("Found proxy/SSL settings in environment variables")
        return ProxySettings(http=http_proxy, https=https_proxy, ssl_cert_file=ssl_cert_file)

    return None


def discover_proxy_settings() -> Optional[ProxySettings]:
    """Discover proxy settings from all sources.

    Checks in order:
    1. Environment variables (proxy URLs + SSL cert)
    2. Conda/mamba config files

    Environment variables take priority for proxy URLs, but ``ssl_cert_file``
    from conda configs is used as a fallback if the env result is missing it.

    Returns:
        ProxySettings if found from any source, None otherwise
    """
    # Try environment variables first
    env_result = get_proxy_from_environment()
    conda_result = detect_proxy_settings()

    if env_result:
        # Fill in ssl_cert_file from conda if env doesn't have one
        if not env_result.ssl_cert_file and conda_result and conda_result.ssl_cert_file:
            env_result.ssl_cert_file = conda_result.ssl_cert_file
        return env_result

    return conda_result
