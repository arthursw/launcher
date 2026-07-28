"""Configuration management for the launcher application."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Optional, Union

import yaml

from .paths import get_default_install_dir
from .repository import default_release_asset_url_templates
from .release_version import ReleaseVersionError, validate_release_config

VALID_CERT_EXTENSIONS = (".pem", ".crt", ".cer")
ENTRYPOINT_MODES = {"script", "module", "project"}


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
    manifest_url: Optional[str] = None
    signature_url: Optional[str] = None
    archive_url: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate trust configuration."""
        if self.mode != "signed_manifest":
            raise ValueError("trust.mode must be 'signed_manifest'")
        if not self.public_key:
            raise ValueError("trust.public_key is required")


@dataclass
class EntryPointConfig:
    """Application launch entrypoint."""

    mode: str
    script: Optional[str] = None
    module: Optional[str] = None
    command: Optional[str] = None
    project_directory: Optional[str] = None
    args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate entrypoint configuration."""
        if self.mode not in ENTRYPOINT_MODES:
            expected = ", ".join(sorted(ENTRYPOINT_MODES))
            raise ValueError(f"entrypoint.mode must be one of: {expected}")
        if not isinstance(self.args, list) or not all(
            isinstance(item, str) for item in self.args
        ):
            raise ValueError("entrypoint.args must be a list of strings")

        if self.mode == "script":
            if not self.script:
                raise ValueError("entrypoint.script is required when entrypoint.mode is 'script'")
            if self.module or self.command or self.project_directory:
                raise ValueError(
                    "script entrypoints can only define entrypoint.script and entrypoint.args"
                )
        elif self.mode == "module":
            if not self.module:
                raise ValueError("entrypoint.module is required when entrypoint.mode is 'module'")
            if self.script or self.command or self.project_directory:
                raise ValueError(
                    "module entrypoints can only define entrypoint.module and entrypoint.args"
                )
        elif self.mode == "project":
            if not self.command:
                raise ValueError("entrypoint.command is required when entrypoint.mode is 'project'")
            if self.script or self.module:
                raise ValueError(
                    "project entrypoints can only define entrypoint.command, "
                    "entrypoint.project_directory, and entrypoint.args"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to YAML data."""
        data: dict[str, Any] = {"mode": self.mode}
        if self.script:
            data["script"] = self.script
        if self.module:
            data["module"] = self.module
        if self.command:
            data["command"] = self.command
        if self.project_directory:
            data["project_directory"] = self.project_directory
        if self.args:
            data["args"] = self.args
        return data


@dataclass
class AppConfig:
    """Application configuration from application.yml."""

    name: str
    entrypoint: EntryPointConfig
    path: str = "."
    ask_install_location: bool = True
    repository: Optional[str] = None
    gitlab_project_id: Optional[str] = None
    api: Optional[str] = None
    releases_endpoint: Optional[str] = None
    archive_endpoint: Optional[str] = None
    version: Optional[str] = None
    auto_update: bool = True
    configuration: Optional[str] = "pyproject.toml"
    extras: list[str] = field(default_factory=list)
    working_directory: Optional[str] = None
    pythonpath: Optional[list[str]] = None
    install: Optional[str] = None
    reinstall_on_update: bool = False
    gui_timeout: int = 3
    init_message: Optional[str] = None
    init_timeout: int = 30
    proxy_servers: ProxySettings = field(default_factory=ProxySettings)
    trust: Optional[TrustConfig] = None

    # Internal: path to the config file for saving updates
    _config_path: Optional[Path] = field(default=None, repr=False)
    _installation_root: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not isinstance(self.entrypoint, EntryPointConfig):
            raise ValueError("'entrypoint' must be an EntryPointConfig")
        if not self.repository and not (self.api and self.releases_endpoint):
            raise ValueError(
                "Either 'repository' or both 'api' and 'releases_endpoint' must be provided"
            )
        if not isinstance(self.extras, list) or not all(
            isinstance(item, str) for item in self.extras
        ):
            raise ValueError("'extras' must be a list of strings")
        if not isinstance(self.path, str):
            raise ValueError("'path' must be a string")
        if not isinstance(self.ask_install_location, bool):
            raise ValueError("'ask_install_location' must be a boolean")
        if self.working_directory is not None and not isinstance(self.working_directory, str):
            raise ValueError("'working_directory' must be a string")
        if self.pythonpath is not None and (
            not isinstance(self.pythonpath, list)
            or not all(isinstance(item, str) for item in self.pythonpath)
        ):
            raise ValueError("'pythonpath' must be a list of strings")

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
        return self.installation_root / "sources"

    @property
    def installation_root(self) -> Path:
        """Return the selected or configured unified runtime root."""
        if self._installation_root is not None:
            return self._installation_root
        root = Path(self.path).expanduser()
        if root.is_absolute():
            return root.resolve()
        return (get_default_install_dir(self.name) / root).resolve()

    def use_installation_root(self, root: Path) -> None:
        """Use a resolved runtime installation root for source paths."""
        self._installation_root = root.expanduser().resolve()

    @property
    def sources_path(self) -> Path:
        """Get the path where sources should be extracted."""
        return self.get_sources_path()

    @property
    def script_path(self) -> Optional[Path]:
        """Get the full path to the configured script entrypoint."""
        if self.entrypoint.mode != "script" or not self.entrypoint.script:
            return None
        return self.sources_path / self.entrypoint.script

    @property
    def config_file_path(self) -> Optional[Path]:
        """Get the full path to the configuration file (pyproject.toml, etc.)."""
        if self.configuration is None:
            return None
        return self.sources_path / self.configuration

    @property
    def working_directory_path(self) -> Path:
        """Get the directory where the app process should start."""
        if self.working_directory is not None:
            return self._source_relative_path(self.working_directory)

        if self.configuration is not None:
            config_parent = Path(self.configuration).parent
            if config_parent != Path("."):
                return self.sources_path / config_parent

        return self.sources_path

    @property
    def project_directory_path(self) -> Path:
        """Get the project directory for project entrypoints."""
        if self.entrypoint.project_directory is not None:
            return self._source_relative_path(self.entrypoint.project_directory)

        if self.configuration is not None:
            config_parent = Path(self.configuration).parent
            if config_parent != Path("."):
                return self.sources_path / config_parent

        if self.working_directory is not None:
            return self.working_directory_path

        return self.sources_path

    @property
    def pythonpath_paths(self) -> list[Path]:
        """Get paths that should be added to the app's Python import path."""
        if self.pythonpath is not None:
            return [self._source_relative_path(path) for path in self.pythonpath]

        working_directory = self.working_directory_path
        paths: list[Path] = []
        src_dir = working_directory / "src"
        if src_dir.is_dir():
            paths.append(src_dir)
        paths.append(working_directory)
        return paths

    def _source_relative_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return self.sources_path / path

    @property
    def install_script_path(self) -> Optional[Path]:
        """Get the full path to the install script if defined."""
        if self.install:
            return self.sources_path / self.install
        return None

    @property
    def entrypoint_label(self) -> str:
        """Return a concise entrypoint description for logs and errors."""
        if self.entrypoint.mode == "script":
            return f"entrypoint.script: {self.entrypoint.script}"
        if self.entrypoint.mode == "module":
            return f"entrypoint.module: {self.entrypoint.module}"
        return f"entrypoint.command: {self.entrypoint.command}"

    def save(self) -> None:
        """Save the current configuration back to the YAML file."""
        if not self._config_path:
            raise ValueError("Cannot save: config file path not set")

        data: dict[str, Any] = {
            "name": self.name,
            "entrypoint": self.entrypoint.to_dict(),
        }
        if self.path != ".":
            data["path"] = self.path
        data["ask_install_location"] = self.ask_install_location

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
        if self.working_directory is not None:
            data["working_directory"] = self.working_directory
        if self.pythonpath is not None:
            data["pythonpath"] = self.pythonpath

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
                "archive_url": self.trust.archive_url,
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


def _config_type_error(section: str, error: TypeError) -> ValueError:
    message = str(error)
    missing_fields = re.findall(r"'([^']+)'", message)
    if "missing" in message and "required positional argument" in message and missing_fields:
        if len(missing_fields) == 1:
            return ValueError(f"{section}.{missing_fields[0]} is required")
        fields = ", ".join(f"{section}.{field}" for field in missing_fields)
        return ValueError(f"Required fields are missing from {section}: {fields}")

    unexpected = re.search(r"unexpected keyword argument '([^']+)'", message)
    if unexpected:
        return ValueError(f"Unknown field in {section}: {unexpected.group(1)}")

    return ValueError(f"Invalid {section} configuration: {message}")


def _load_entrypoint_config(data: dict[str, Any]) -> EntryPointConfig:
    try:
        return EntryPointConfig(**data)
    except TypeError as e:
        raise _config_type_error("entrypoint", e) from e


def _load_trust_config(data: Any) -> TrustConfig:
    if not isinstance(data, dict):
        raise ValueError("'trust' must be a mapping")
    try:
        return TrustConfig(**data)
    except TypeError as e:
        raise _config_type_error("trust", e) from e


def _resolve_trust_urls(config: AppConfig) -> None:
    if not config.trust:
        return

    missing = [
        field_name
        for field_name in ("manifest_url", "signature_url", "archive_url")
        if not getattr(config.trust, field_name)
    ]
    if not missing:
        return

    if not config.repository:
        formatted = ", ".join(f"trust.{field_name}" for field_name in missing)
        raise ValueError(
            f"{formatted} required when trust is configured without repository inference. "
            "Set repository to a GitHub/GitLab URL, or configure explicit trust.manifest_url, "
            "trust.signature_url, and trust.archive_url for custom hosting."
        )

    try:
        defaults = default_release_asset_url_templates(config.repository)
    except ValueError as e:
        formatted = ", ".join(f"trust.{field_name}" for field_name in missing)
        raise ValueError(
            f"{formatted} could not be inferred from repository {config.repository!r}. "
            "Configure explicit trust.manifest_url, trust.signature_url, and trust.archive_url."
        ) from e

    for field_name in missing:
        setattr(config.trust, field_name, getattr(defaults, field_name))


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
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a mapping")
    try:
        validate_release_config(data)
    except ReleaseVersionError as exc:
        raise ValueError(str(exc)) from exc

    # Check required fields
    required_fields = ["name", "entrypoint"]
    for field_name in required_fields:
        if field_name not in data:
            raise ValueError(f"Required field '{field_name}' is missing from configuration")
    if not isinstance(data["entrypoint"], dict):
        raise ValueError("'entrypoint' must be a mapping")

    # Parse proxy settings
    proxy_data = data.pop("proxy_servers", {}) or {}
    proxy_settings = ProxySettings(
        http=proxy_data.get("http"),
        https=proxy_data.get("https"),
        ssl_cert_file=proxy_data.get("ssl_cert_file"),
    )

    trust_data = data.pop("trust", None)
    trust = _load_trust_config(trust_data) if trust_data else None

    # Create config instance
    config = AppConfig(
        name=data["name"],
        entrypoint=_load_entrypoint_config(data["entrypoint"]),
        path=data.get("path") or ".",
        ask_install_location=data.get("ask_install_location", True),
        repository=data.get("repository"),
        gitlab_project_id=data.get("gitlab_project_id"),
        api=data.get("api"),
        releases_endpoint=data.get("releases_endpoint"),
        archive_endpoint=data.get("archive_endpoint"),
        version=data.get("version"),
        auto_update=data.get("auto_update", True),
        configuration=data.get("configuration", "pyproject.toml"),
        extras=data.get("extras", []),
        working_directory=data.get("working_directory"),
        pythonpath=data.get("pythonpath"),
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
    _resolve_trust_urls(config)

    return config
