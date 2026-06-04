"""Environment management wrapper around Wetlands library."""

import hashlib
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Optional

from wetlands.environment_manager import EnvironmentManager
from wetlands.environment import Environment

if TYPE_CHECKING:
    from .config import AppConfig

logger = logging.getLogger(__name__)

LOCK_FILE_NAMES = (
    "uv.lock",
    "poetry.lock",
    "pdm.lock",
    "pixi.lock",
    "conda-lock.yml",
    "conda-lock.yaml",
    "requirements.lock",
)


class EnvironmentError(Exception):
    """Exception for environment-related errors."""
    pass


class LauncherEnvironmentManager:
    """Wrapper around Wetlands EnvironmentManager for the launcher application."""

    def __init__(
        self,
        wetlands_path: Optional[Path] = None,
        log_file_path: Optional[Path] = None,
    ) -> None:
        """Initialize the environment manager.

        Args:
            wetlands_path: Path where Wetlands stores its data (pixi installation, etc.)
                          Defaults to ~/.launcher/wetlands
            log_file_path: Path to the log file. Defaults to wetlands_path/wetlands.log
        """
        if wetlands_path is None:
            wetlands_path = Path.home() / ".launcher" / "wetlands"

        wetlands_path.mkdir(parents=True, exist_ok=True)

        if log_file_path is None:
            log_file_path = wetlands_path / "wetlands.log"

        self._manager = EnvironmentManager(
            wetlands_instance_path=wetlands_path,
            log_file_path=log_file_path,
        )

        logger.info(f"EnvironmentManager initialized at {wetlands_path}")

    @property
    def manager(self) -> EnvironmentManager:
        """Get the underlying Wetlands EnvironmentManager."""
        return self._manager

    def environment_exists(self, env_name: str) -> bool:
        """Check if an environment with the given name exists.

        Args:
            env_name: The sanitized environment name

        Returns:
            True if the environment exists
        """
        env_path = self._manager.settings_manager.get_environment_path_from_name(env_name)
        return self._manager.environment_exists(env_path)

    def get_environment_path(self, env_name: str) -> Path:
        """Get the path to an environment.

        Args:
            env_name: The sanitized environment name

        Returns:
            Path to the environment
        """
        return self._manager.settings_manager.get_environment_path_from_name(env_name)

    def get_or_create_environment(
        self,
        config: "AppConfig",
    ) -> Environment:
        """Get an existing environment or create a new one.

        Args:
            config: Application configuration

        Returns:
            The Wetlands Environment instance
        """
        env_name = config.env_name
        config_file_path = config.config_file_path
        extras = getattr(config, "extras", []) or []

        if config_file_path and config_file_path.exists():
            logger.info(f"Creating environment '{env_name}' from config: {config_file_path}")
            return self._manager.create_from_config(
                name=env_name,
                config_path=config_file_path,
                optional_dependencies=extras or None,
            )
        if extras:
            raise EnvironmentError(
                "Dependency extras require a dependency config file, but "
                f"{config.configuration!r} was not found at {config_file_path}. "
                "Update `configuration` so it points to the dependency file inside "
                "the downloaded app sources, or remove `extras`."
            )
        if config_file_path:
            raise EnvironmentError(
                "Dependency config file was not found: "
                f"{config_file_path}. Update `configuration` so it points to "
                "the dependency file inside the downloaded app sources. If this "
                "app intentionally has no dependency config file, set "
                "`configuration: null`."
            )
        else:
            logger.info(f"Creating environment '{env_name}' with no dependencies")
            return self._manager.create(name=env_name)

    def delete_environment(self, env_name: str) -> bool:
        """Delete an environment.

        Args:
            env_name: The sanitized environment name

        Returns:
            True if the environment was deleted, False if it didn't exist
        """
        env_path = self._manager.settings_manager.get_environment_path_from_name(env_name)

        if not self._manager.environment_exists(env_path):
            logger.warning(f"Environment '{env_name}' does not exist")
            return False

        # Load the environment to get access to delete method
        try:
            env = self._manager.load(env_name, env_path)
            env.delete()
            logger.info(f"Environment '{env_name}' deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete environment '{env_name}': {e}")
            raise EnvironmentError(f"Failed to delete environment: {e}") from e

    def set_proxies(
        self,
        http_proxy: Optional[str],
        https_proxy: Optional[str],
        ssl_cert_file: Optional[str] = None,
    ) -> None:
        """Set proxy settings for the environment manager.

        Args:
            http_proxy: HTTP proxy URL
            https_proxy: HTTPS proxy URL
            ssl_cert_file: Path to a custom CA certificate file
        """
        import os as _os

        proxies = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        if proxies:
            self._manager.set_proxies(proxies)
            logger.info(f"Proxies set: {proxies}")

        if ssl_cert_file:
            _os.environ["SSL_CERT_FILE"] = ssl_cert_file
            _os.environ["REQUESTS_CA_BUNDLE"] = ssl_cert_file
            logger.info(f"SSL certificate env vars set to: {ssl_cert_file}")

    def get_process_logger(self, process: subprocess.Popen):
        """Get the ProcessLogger for a running process.

        Args:
            process: The process

        Returns:
            The ProcessLogger instance, or None if not found
        """
        return self._manager.get_process_logger(process)

    def exit(self) -> None:
        """Clean up and exit all environments."""
        self._manager.exit()


def compute_dependency_hash(config: "AppConfig") -> str:
    """Hash dependency inputs that should invalidate the runtime environment."""
    digest = hashlib.sha256()
    sources_path = config.sources_path
    paths: list[Path] = []

    digest.update(b"extras\0")
    for extra in sorted(set(config.extras)):
        digest.update(extra.encode("utf-8"))
        digest.update(b"\0")

    config_path = config.config_file_path
    if config_path and config_path.exists():
        paths.append(config_path)

    for lock_name in LOCK_FILE_NAMES:
        lock_path = sources_path / lock_name
        if lock_path.exists():
            paths.append(lock_path)

    install_path = config.install_script_path
    if install_path and install_path.exists():
        paths.append(install_path)

    for path in sorted(set(paths), key=lambda item: item.relative_to(sources_path).as_posix()):
        relative = path.relative_to(sources_path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return digest.hexdigest()
