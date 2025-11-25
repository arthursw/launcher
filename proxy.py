"""Proxy configuration and management."""

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProxySettings:
    """Proxy server settings."""

    http: Optional[str] = None
    https: Optional[str] = None


def get_proxy_settings(config_path: str) -> ProxySettings:
    """Get proxy settings from various sources.

    Attempts to get proxy settings from:
    1. application.yml file
    2. Conda configuration files
    3. Returns empty ProxySettings if none found

    Args:
        config_path: Path to application.yml

    Returns:
        ProxySettings object with http and https settings
    """
    # Try to load from application.yml
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            if config and "proxy_servers" in config and config["proxy_servers"] is not None:
                proxy_servers = config["proxy_servers"]
                return ProxySettings(
                    http=proxy_servers.get("http"),
                    https=proxy_servers.get("https"),
                )
    except Exception as e:
        print(f"Failed to read proxy settings from config: {e}")

    # Try conda configuration files
    conda_rc_paths = _get_conda_rc_paths()
    for rc_path in conda_rc_paths:
        settings = _load_proxy_from_conda_rc(rc_path)
        if settings.http or settings.https:
            return settings

    return ProxySettings()


def _get_conda_rc_paths() -> list[str]:
    """Get list of conda configuration file paths to check.

    Returns:
        List of paths to check for conda configuration
    """
    paths = []

    if platform.system() != "Windows":
        paths.extend([
            "/etc/conda/.condarc",
            "/etc/conda/condarc",
            "/etc/conda/condarc.d/",
            "/etc/conda/.mambarc",
            "/var/lib/conda/.condarc",
            "/var/lib/conda/condarc",
            "/var/lib/conda/condarc.d/",
            "/var/lib/conda/.mambarc",
        ])
    else:
        paths.extend([
            "C:\\ProgramData\\conda\\.condarc",
            "C:\\ProgramData\\conda\\condarc",
            "C:\\ProgramData\\conda\\condarc.d",
            "C:\\ProgramData\\conda\\.mambarc",
        ])

    # User-specific paths
    home = Path.home()
    paths.extend([
        str(home / ".condarc"),
        str(home / ".mambarc"),
        str(home / ".conda" / ".condarc"),
        str(home / ".config" / "conda" / ".condarc"),
    ])

    # Environment-specific paths
    conda_root = os.environ.get("CONDA_ROOT")
    if conda_root:
        paths.extend([
            str(Path(conda_root) / ".condarc"),
            str(Path(conda_root) / ".mambarc"),
        ])

    mamba_root = os.environ.get("MAMBA_ROOT_PREFIX")
    if mamba_root:
        paths.extend([
            str(Path(mamba_root) / ".condarc"),
            str(Path(mamba_root) / ".mambarc"),
        ])

    # Local micromamba
    paths.append("micromamba/.condarc")
    paths.append("micromamba/.mambarc")

    return paths


def _load_proxy_from_conda_rc(rc_path: str) -> ProxySettings:
    """Load proxy settings from a conda rc file.

    Args:
        rc_path: Path to conda rc file

    Returns:
        ProxySettings with http and https settings, or empty if file not found
    """
    rc_file = Path(rc_path).expanduser()

    if not rc_file.exists():
        return ProxySettings()

    try:
        with open(rc_file, "r") as f:
            config = yaml.safe_load(f)
            if config and "proxy_servers" in config:
                proxy_servers = config["proxy_servers"]
                return ProxySettings(
                    http=proxy_servers.get("http"),
                    https=proxy_servers.get("https"),
                )
    except Exception:
        # Silently ignore errors reading conda rc files
        pass

    return ProxySettings()


def update_proxy_in_config(config_path: str, settings: ProxySettings) -> None:
    """Update proxy settings in application.yml.

    Args:
        config_path: Path to application.yml
        settings: ProxySettings to save
    """
    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    config["proxy_servers"] = {
        "http": settings.http,
        "https": settings.https,
    }

    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)


def apply_proxy_to_requests(settings: ProxySettings) -> dict:
    """Convert ProxySettings to requests library format.

    Args:
        settings: ProxySettings object

    Returns:
        Dictionary suitable for requests proxies parameter
    """
    proxies = {}
    if settings.http:
        proxies["http"] = settings.http
    if settings.https:
        proxies["https"] = settings.https
    return proxies
