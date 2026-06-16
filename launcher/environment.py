"""Environment management wrapper around Wetlands library."""

import hashlib
import logging
from pathlib import Path
import re
import subprocess
import tomllib
from typing import TYPE_CHECKING, Optional
from urllib.parse import unquote, urlparse

from wetlands.environment_manager import EnvironmentManager
from wetlands.environment import Environment
from wetlands._internal.dependency_manager import LocalDependency

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
        local_dependency = self.project_local_dependency(config)

        if config_file_path and config_file_path.exists():
            logger.info(f"Creating environment '{env_name}' from config: {config_file_path}")
            if local_dependency:
                dependencies = self._manager._parse_dependencies_from_config(
                    config_file_path,
                    environment_name=env_name,
                    optional_dependencies=extras or None,
                )
                dependencies["local"] = [
                    *dependencies.get("local", []),
                    local_dependency,
                ]
                try:
                    return self._manager.create(name=env_name, dependencies=dependencies)
                except Exception as e:
                    raise _environment_create_error(e, env_name, config_file_path, config) from e
            try:
                return self._manager.create_from_config(
                    name=env_name,
                    config_path=config_file_path,
                    optional_dependencies=extras or None,
                )
            except Exception as e:
                raise _environment_create_error(e, env_name, config_file_path, config) from e
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
        logger.info(f"Creating environment '{env_name}' with no dependencies")
        try:
            if local_dependency:
                return self._manager.create(name=env_name, dependencies={"local": [local_dependency]})
            return self._manager.create(name=env_name)
        except Exception as e:
            raise _environment_create_error(e, env_name, config_file_path, config) from e

    def project_install_managed_by_environment(self, config: "AppConfig") -> bool:
        """Return whether Wetlands can install the project as a local dependency."""
        return self._is_project_entrypoint(config)

    def project_local_dependency(self, config: "AppConfig") -> Optional[LocalDependency]:
        """Build the Wetlands local dependency for project-mode apps when supported."""
        if not self.project_install_managed_by_environment(config):
            return None

        project_directory = config.project_directory_path
        if not project_directory.exists():
            raise EnvironmentError(
                f"Configured project directory not found: {project_directory}\n"
                "Update `entrypoint.project_directory` so it points to the Python "
                "project directory inside the downloaded app sources."
            )
        if not project_directory.is_dir():
            raise EnvironmentError(f"Configured project directory is not a directory: {project_directory}")

        package_name = _read_project_package_name(project_directory)
        if not package_name:
            raise EnvironmentError(
                "Project mode uses Wetlands local dependencies, which require the Python package name. "
                f"Add [project].name to {project_directory / 'pyproject.toml'}."
            )
        missing_paths = _missing_project_local_dependency_paths(project_directory)
        if missing_paths:
            formatted = "\n".join(f"  - {path}" for path in missing_paths)
            raise EnvironmentError(
                "Project mode cannot install this release because the project declares a missing local path dependency.\n"
                f"Project directory: {project_directory}\n"
                f"Missing path dependencies:\n{formatted}\n"
                "Fixes:\n"
                "  - Include these local package directories in the app release archive, for example with "
                "`release.archive.include`.\n"
                "  - Or change the project dependency to a published package/version that Pixi can download.\n"
                "  - Or remove stale local path dependencies from the packaged pyproject.toml."
            )
        return {
            "name": _normalize_distribution_name(package_name),
            "path": project_directory,
            "editable": True,
        }

    @staticmethod
    def _is_project_entrypoint(config: "AppConfig") -> bool:
        return getattr(getattr(config, "entrypoint", None), "mode", None) == "project"

    def uses_pixi(self) -> bool:
        """Return whether the underlying Wetlands manager is using Pixi."""
        settings = getattr(self._manager, "settings_manager", None)
        return bool(getattr(settings, "use_pixi", False))

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


def _read_project_package_name(project_directory: Path) -> Optional[str]:
    pyproject = _read_project_pyproject(project_directory)
    if not pyproject:
        return None
    _path, data = pyproject

    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            return name

    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            name = poetry.get("name")
            if isinstance(name, str) and name.strip():
                return name

    return None


def _read_project_pyproject(project_directory: Path) -> Optional[tuple[Path, dict]]:
    pyproject = project_directory / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        return pyproject, tomllib.loads(pyproject.read_text())
    except tomllib.TOMLDecodeError as e:
        raise EnvironmentError(f"Invalid project pyproject.toml: {pyproject}: {e}") from e


def _missing_project_local_dependency_paths(project_directory: Path) -> list[Path]:
    pyproject = _read_project_pyproject(project_directory)
    if not pyproject:
        return []
    _path, data = pyproject
    candidates = _project_local_dependency_paths(data, project_directory)
    return sorted({path for path in candidates if not path.exists()})


def _project_local_dependency_paths(data: dict, project_directory: Path) -> list[Path]:
    paths: list[Path] = []
    project = data.get("project")
    if isinstance(project, dict):
        paths.extend(_dependency_string_paths(project.get("dependencies"), project_directory))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for dependencies in optional.values():
                paths.extend(_dependency_string_paths(dependencies, project_directory))

    tool = data.get("tool")
    if isinstance(tool, dict):
        uv = tool.get("uv")
        if isinstance(uv, dict):
            paths.extend(_source_table_paths(uv.get("sources"), project_directory))
        pixi = tool.get("pixi")
        if isinstance(pixi, dict):
            paths.extend(_source_table_paths(pixi.get("pypi-dependencies"), project_directory))

    return paths


def _dependency_string_paths(dependencies: object, base: Path) -> list[Path]:
    if not isinstance(dependencies, list):
        return []
    paths: list[Path] = []
    for dependency in dependencies:
        if not isinstance(dependency, str) or "@" not in dependency:
            continue
        _name, target = dependency.split("@", 1)
        path = _path_from_dependency_target(target.strip(), base)
        if path:
            paths.append(path)
    return paths


def _source_table_paths(sources: object, base: Path) -> list[Path]:
    if not isinstance(sources, dict):
        return []
    paths: list[Path] = []
    for source in sources.values():
        if isinstance(source, dict):
            path_value = source.get("path")
            if isinstance(path_value, str):
                paths.append(_resolve_dependency_path(path_value, base))
        elif isinstance(source, str) and "@" in source:
            _name, target = source.split("@", 1)
            path = _path_from_dependency_target(target.strip(), base)
            if path:
                paths.append(path)
    return paths


def _path_from_dependency_target(target: str, base: Path) -> Optional[Path]:
    if target.startswith("file:"):
        parsed = urlparse(target)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).resolve()
    if target.startswith((".", "/", "~")):
        return _resolve_dependency_path(target, base)
    return None


def _resolve_dependency_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()


def _environment_create_error(
    error: Exception,
    env_name: str,
    config_file_path: Optional[Path],
    config: "AppConfig",
) -> EnvironmentError:
    message = (
        f"Wetlands failed to create environment {env_name!r}.\n"
        f"Dependency config: {config_file_path}\n"
        f"Project directory: {config.project_directory_path if config.entrypoint.mode == 'project' else 'not configured'}\n"
        "If the Wetlands output mentions `Distribution not found at: file://...`, a dependency points to a local "
        "path that is missing from the downloaded release archive. Include that directory with `release.archive.include` "
        "or depend on a published package version instead.\n"
        f"Original error: {error}"
    )
    return EnvironmentError(message)


def compute_project_install_fingerprint(config: "AppConfig", version: str) -> str:
    """Hash project-mode inputs that should trigger package reinstall."""
    digest = hashlib.sha256()
    digest.update(b"project-local-dependency\0")
    digest.update(version.encode("utf-8"))
    digest.update(b"\0")

    entrypoint = config.entrypoint
    for value in (
        entrypoint.mode,
        entrypoint.command or "",
        entrypoint.project_directory or "",
        config.configuration or "",
        str(config.project_directory_path),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")

    for arg in entrypoint.args:
        digest.update(arg.encode("utf-8"))
        digest.update(b"\0")
    for extra in sorted(set(config.extras)):
        digest.update(extra.encode("utf-8"))
        digest.update(b"\0")

    project_directory = config.project_directory_path
    for file_name in ("pyproject.toml", "setup.cfg", "setup.py"):
        path = project_directory / file_name
        if path.exists():
            digest.update(file_name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")

    return digest.hexdigest()
