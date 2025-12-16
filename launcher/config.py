"""Configuration management for the launcher application."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ProxySettings:
    """Proxy server configuration."""

    http: Optional[str] = None
    https: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for requests library."""
        result = {}
        if self.http:
            result["http"] = self.http
        if self.https:
            result["https"] = self.https
        return result


@dataclass
class AppConfig:
    """Application configuration from application.yml."""

    name: str
    main: str
    path: str
    repository: Optional[str] = None
    api: Optional[str] = None
    tags_endpoint: Optional[str] = None
    archive_endpoint: Optional[str] = None
    version: Optional[str] = None
    auto_update: bool = True
    configuration: str = "pyproject.toml"
    install: Optional[str] = None
    gui_timeout: int = 3
    init_message: Optional[str] = None
    init_timeout: int = 30
    proxy_servers: ProxySettings = field(default_factory=ProxySettings)

    # Internal: path to the config file for saving updates
    _config_path: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.repository and not (self.api and self.tags_endpoint and self.archive_endpoint):
            raise ValueError(
                "Either 'repository' or all of 'api', 'tags_endpoint', and 'archive_endpoint' must be provided"
            )

    @property
    def env_name(self) -> str:
        """Get sanitized environment name."""
        # Remove special characters to make a valid env name
        return "".join(c if c.isalnum() or c == "_" else "_" for c in self.name)

    @property
    def sources_path(self) -> Path:
        """Get the path where sources should be extracted."""
        if self.version:
            return Path(self.path).expanduser() / self.version
        return Path(self.path).expanduser()

    @property
    def main_script_path(self) -> Path:
        """Get the full path to the main script."""
        return self.sources_path / self.main

    @property
    def config_file_path(self) -> Optional[Path]:
        """Get the full path to the configuration file (pyproject.toml, etc.)."""
        return self.sources_path / self.configuration

    @property
    def install_script_path(self) -> Optional[Path]:
        """Get the full path to the install script if defined."""
        if self.install:
            return self.sources_path / self.install
        return None

    def save(self) -> None:
        """Save the current configuration back to the YAML file."""
        if not self._config_path:
            raise ValueError("Cannot save: config file path not set")

        data = {
            "name": self.name,
            "main": self.main,
            "path": self.path,
        }

        # Add optional fields if set
        if self.repository:
            data["repository"] = self.repository
        if self.api:
            data["api"] = self.api
        if self.tags_endpoint:
            data["tags_endpoint"] = self.tags_endpoint
        if self.archive_endpoint:
            data["archive_endpoint"] = self.archive_endpoint
        if self.version:
            data["version"] = self.version

        data["auto_update"] = self.auto_update
        data["configuration"] = self.configuration

        if self.install:
            data["install"] = self.install

        data["gui_timeout"] = self.gui_timeout

        if self.init_message:
            data["init_message"] = self.init_message

        data["init_timeout"] = self.init_timeout

        # Add proxy settings if any are set
        proxy_dict = self.proxy_servers.to_dict()
        if proxy_dict:
            data["proxy_servers"] = proxy_dict

        with open(self._config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_config(config_path: Path) -> AppConfig:
    """Load application configuration from a YAML file.

    Args:
        config_path: Path to the application.yml file

    Returns:
        AppConfig instance with loaded configuration

    Raises:
        FileNotFoundError: If the config file doesn't exist
        ValueError: If required fields are missing or invalid
    """
    config_path = Path(config_path).expanduser().resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError("Configuration file is empty")

    # Check required fields
    required_fields = ["name", "main", "path"]
    for field_name in required_fields:
        if field_name not in data:
            raise ValueError(f"Required field '{field_name}' is missing from configuration")

    # Parse proxy settings
    proxy_data = data.pop("proxy_servers", {}) or {}
    proxy_settings = ProxySettings(
        http=proxy_data.get("http"),
        https=proxy_data.get("https"),
    )

    # Create config instance
    config = AppConfig(
        name=data["name"],
        main=data["main"],
        path=data["path"],
        repository=data.get("repository"),
        api=data.get("api"),
        tags_endpoint=data.get("tags_endpoint"),
        archive_endpoint=data.get("archive_endpoint"),
        version=data.get("version"),
        auto_update=data.get("auto_update", True),
        configuration=data.get("configuration", "pyproject.toml"),
        install=data.get("install"),
        gui_timeout=data.get("gui_timeout", 3),
        init_message=data.get("init_message"),
        init_timeout=data.get("init_timeout", 30),
        proxy_servers=proxy_settings,
    )

    # Store the config path for saving
    config._config_path = config_path

    return config
