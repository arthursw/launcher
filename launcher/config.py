"""Configuration management for the launcher application."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from .paths import get_runtime_data_dir

VALID_CERT_EXTENSIONS = (".pem", ".crt", ".cer")


@dataclass
class ProxySettings:
    """Proxy server configuration."""

    http: Optional[str] = None
    https: Optional[str] = None
    ssl_cert_file: Optional[str] = None

    @property
    def verify(self) -> Union[str, bool]:
        """Return the value for requests' ``verify`` parameter.

        Returns the certificate path when set, otherwise ``True``
        (default SSL verification).
        """
        if self.ssl_cert_file:
            return self.ssl_cert_file
        return True

    def validate_ssl_cert_file(self) -> bool:
        """Check that ``ssl_cert_file`` points to an existing file with a recognised extension.

        Returns:
            True if the file is valid.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the extension is not recognised.
        """
        if not self.ssl_cert_file:
            return True
        path = Path(self.ssl_cert_file)
        if not path.is_file():
            raise FileNotFoundError(f"SSL certificate file not found: {self.ssl_cert_file}")
        if path.suffix.lower() not in VALID_CERT_EXTENSIONS:
            raise ValueError(
                f"Unrecognised certificate extension '{path.suffix}'. "
                f"Expected one of: {', '.join(VALID_CERT_EXTENSIONS)}"
            )
        return True

    def to_dict(self) -> dict:
        """Convert to dictionary for requests library."""
        result = {}
        if self.http:
            result["http"] = self.http
        if self.https:
            result["https"] = self.https
        return result


@dataclass
class TrustConfig:
    """Update trust configuration."""

    mode: str
    public_key: str
    manifest_url: str
    signature_url: str

    def __post_init__(self) -> None:
        """Validate trust configuration."""
        if self.mode != "signed_manifest":
            raise ValueError("trust.mode must be 'signed_manifest'")
        if not self.public_key:
            raise ValueError("trust.public_key is required")
        if not self.manifest_url:
            raise ValueError("trust.manifest_url is required")
        if not self.signature_url:
            raise ValueError("trust.signature_url is required")


@dataclass
class AppConfig:
    """Application configuration from application.yml."""

    name: str
    main: str
    path: str
    repository: Optional[str] = None
    gitlab_project_id: Optional[str] = None
    api: Optional[str] = None
    releases_endpoint: Optional[str] = None
    archive_endpoint: Optional[str] = None
    version: Optional[str] = None
    auto_update: bool = True
    configuration: Optional[str] = "pyproject.toml"
    extras: list[str] = field(default_factory=list)
    install: Optional[str] = None
    reinstall_on_update: bool = False
    gui_timeout: int = 3
    init_message: Optional[str] = None
    init_timeout: int = 30
    proxy_servers: ProxySettings = field(default_factory=ProxySettings)
    trust: Optional[TrustConfig] = None

    # Internal: path to the config file for saving updates
    _config_path: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.repository and not (self.api and self.releases_endpoint and self.archive_endpoint):
            raise ValueError(
                "Either 'repository' or all of 'api', 'releases_endpoint', and 'archive_endpoint' must be provided"
            )
        if not isinstance(self.extras, list) or not all(
            isinstance(item, str) for item in self.extras
        ):
            raise ValueError("'extras' must be a list of strings")

    @property
    def env_name(self) -> str:
        """Get sanitized environment name."""
        # Remove special characters to make a valid env name
        return "".join(c if c.isalnum() or c == "_" else "_" for c in self.name)

    def get_sources_path(self, version: Optional[str] = None) -> Path:
        """Get the path where sources should be extracted for a given version.

        Args:
            version: Version tag (e.g., "v1.2.3"). Defaults to self.version.

        Returns:
            Path to sources directory (e.g., ~/apps/myapp-v1.2.3)
        """
        root = self._sources_root()
        ver = version or self.version
        if ver:
            # Sanitize app name (lowercase, no special chars except dash/underscore)
            sanitized_name = "".join(
                c if c.isalnum() or c in "-_" else "" for c in self.name.lower()
            )
            sanitized_version = sanitize_version_for_path(ver)
            folder_name = f"{sanitized_name}-{sanitized_version}"
            return root / folder_name
        return root

    def _sources_root(self) -> Path:
        root = Path(self.path).expanduser()
        if root.is_absolute():
            return root
        return get_runtime_data_dir(self.name) / root

    @property
    def sources_path(self) -> Path:
        """Get the path where sources should be extracted."""
        return self.get_sources_path()

    @property
    def main_script_path(self) -> Path:
        """Get the full path to the main script."""
        return self.sources_path / self.main

    @property
    def config_file_path(self) -> Optional[Path]:
        """Get the full path to the configuration file (pyproject.toml, etc.)."""
        if self.configuration is None:
            return None
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

        data: dict[str, Any] = {
            "name": self.name,
            "main": self.main,
            "path": self.path,
        }

        # Add optional fields if set
        if self.repository:
            data["repository"] = self.repository
        if self.gitlab_project_id:
            data["gitlab_project_id"] = self.gitlab_project_id
        if self.api:
            data["api"] = self.api
        if self.releases_endpoint:
            data["releases_endpoint"] = self.releases_endpoint
        if self.archive_endpoint:
            data["archive_endpoint"] = self.archive_endpoint
        if self.version:
            data["version"] = self.version

        data["auto_update"] = self.auto_update
        data["configuration"] = self.configuration
        if self.extras:
            data["extras"] = self.extras

        if self.install:
            data["install"] = self.install

        data["reinstall_on_update"] = self.reinstall_on_update

        data["gui_timeout"] = self.gui_timeout

        if self.init_message:
            data["init_message"] = self.init_message

        data["init_timeout"] = self.init_timeout

        # Add proxy settings if any are set
        proxy_dict = self.proxy_servers.to_dict()
        if self.proxy_servers.ssl_cert_file:
            proxy_dict["ssl_cert_file"] = self.proxy_servers.ssl_cert_file
        if proxy_dict:
            data["proxy_servers"] = proxy_dict

        if self.trust:
            data["trust"] = {
                "mode": self.trust.mode,
                "public_key": self.trust.public_key,
                "manifest_url": self.trust.manifest_url,
                "signature_url": self.trust.signature_url,
            }

        with open(self._config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def sanitize_version_for_path(version: str) -> str:
    """Sanitize a release tag before using it in a directory name."""
    sanitized = "".join(c if c.isalnum() or c in "._-" else "_" for c in version)
    sanitized = sanitized.strip("._-")
    if not sanitized:
        raise ValueError(f"Version cannot be used as a directory name: {version!r}")
    return sanitized


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
        ssl_cert_file=proxy_data.get("ssl_cert_file"),
    )

    trust_data = data.pop("trust", None)
    trust = TrustConfig(**trust_data) if trust_data else None

    # Create config instance
    config = AppConfig(
        name=data["name"],
        main=data["main"],
        path=data["path"],
        repository=data.get("repository"),
        gitlab_project_id=data.get("gitlab_project_id"),
        api=data.get("api"),
        releases_endpoint=data.get("releases_endpoint"),
        archive_endpoint=data.get("archive_endpoint"),
        version=data.get("version"),
        auto_update=data.get("auto_update", True),
        configuration=data.get("configuration", "pyproject.toml"),
        extras=data.get("extras", []),
        install=data.get("install"),
        reinstall_on_update=data.get("reinstall_on_update", False),
        gui_timeout=data.get("gui_timeout", 3),
        init_message=data.get("init_message"),
        init_timeout=data.get("init_timeout", 30),
        proxy_servers=proxy_settings,
        trust=trust,
    )

    # Store the config path for saving
    config._config_path = config_path

    return config
