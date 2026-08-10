"""Environment management wrapper around Wetlands library."""

import hashlib
import logging
import os
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Optional
from urllib.parse import unquote, urlparse

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
import yaml
from wetlands import (
    EnvironmentManager,
    EnvironmentSpec,
    LocalPackage,
    ManagedEnvironment,
    local_package_content_identity,
)

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
    ) -> None:
        """Initialize the environment manager.

        Args:
            wetlands_path: Path where Wetlands stores its data (pixi installation, etc.)
                          Defaults to ~/.launcher/wetlands
        """
        if wetlands_path is None:
            wetlands_path = Path.home() / ".launcher" / "wetlands"

        wetlands_path.mkdir(parents=True, exist_ok=True)

        self._wetlands_path = wetlands_path
        self._manager = EnvironmentManager(root=wetlands_path)

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
        return any(info.name == env_name and info.ready for info in self._manager.managed_environments())

    def get_environment_path(self, env_name: str) -> Path:
        """Get the path to an environment.

        Args:
            env_name: The sanitized environment name

        Returns:
            Path to the environment
        """
        return self._manager.environments_root / env_name

    def get_or_create_environment(
        self,
        config: "AppConfig",
    ) -> ManagedEnvironment:
        """Get an existing environment or create a new one.

        Args:
            config: Application configuration

        Returns:
            The Wetlands Environment instance
        """
        env_name = config.env_name
        config_file_path = config.config_file_path
        extras = getattr(config, "extras", []) or []
        local_package = self.project_local_dependency(config)

        if config_file_path and config_file_path.exists():
            logger.info(f"Provisioning environment '{env_name}' from config: {config_file_path}")
            try:
                spec = _environment_spec_from_config(
                    config_file_path,
                    environment_name=env_name,
                    optional_dependencies=extras,
                    local_packages=(local_package,) if local_package else (),
                )
                return self._manager.provision(env_name, spec, replace_existing=True).wait_for()
            except Exception as e:
                raise _environment_create_error(e, env_name, config_file_path, config) from e
        elif extras:
            raise EnvironmentError(
                "Dependency extras require a dependency config file, but "
                f"{config.configuration!r} was not found at {config_file_path}. "
                "Update `configuration` so it points to the dependency file inside "
                "the downloaded app sources, or remove `extras`."
            )
        elif config_file_path:
            raise EnvironmentError(
                "Dependency config file was not found: "
                f"{config_file_path}. Update `configuration` so it points to "
                "the dependency file inside the downloaded app sources. If this "
                "app intentionally has no dependency config file, set "
                "`configuration: null`."
            )
        logger.info(f"Provisioning environment '{env_name}' with no configured dependencies")
        try:
            spec = EnvironmentSpec(local=(local_package,) if local_package else ())
            return self._manager.provision(env_name, spec, replace_existing=True).wait_for()
        except Exception as e:
            raise _environment_create_error(e, env_name, config_file_path, config) from e

    def project_install_managed_by_environment(self, config: "AppConfig") -> bool:
        """Return whether Wetlands can install the project as a local dependency."""
        return self._is_project_entrypoint(config)

    def project_local_dependency(self, config: "AppConfig") -> Optional[LocalPackage]:
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
        return LocalPackage(
            source=project_directory,
            extras=tuple(config.extras),
            content_identity=local_package_content_identity(project_directory),
        )

    @staticmethod
    def _is_project_entrypoint(config: "AppConfig") -> bool:
        return getattr(getattr(config, "entrypoint", None), "mode", None) == "project"

    def uses_pixi(self) -> bool:
        """Return whether the underlying Wetlands manager is using Pixi."""
        return True

    def delete_environment(self, env_name: str) -> bool:
        """Delete an environment.

        Args:
            env_name: The sanitized environment name

        Returns:
            True if the environment was deleted, False if it didn't exist
        """
        if not any(info.name == env_name for info in self._manager.managed_environments()):
            logger.warning(f"Environment '{env_name}' does not exist")
            return False

        try:
            self._manager.remove(env_name).wait_for()
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
        proxies = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        if dict(self._manager.network or {}) != proxies:
            self._manager.close()
            self._manager = EnvironmentManager(root=self._wetlands_path, network=proxies or None)
            logger.info("Proxy settings updated for: %s", ", ".join(sorted(proxies)) or "none")

        if ssl_cert_file:
            os.environ["SSL_CERT_FILE"] = ssl_cert_file
            os.environ["REQUESTS_CA_BUNDLE"] = ssl_cert_file
            logger.info(f"SSL certificate env vars set to: {ssl_cert_file}")

    def exit(self) -> None:
        """Clean up and exit all environments."""
        self._manager.close()


def _environment_spec_from_config(
    config_path: Path,
    *,
    environment_name: str,
    optional_dependencies: list[str],
    local_packages: tuple[LocalPackage, ...],
) -> EnvironmentSpec:
    """Translate supported app dependency files into a Wetlands 2 recipe."""
    name = config_path.name.lower()
    if name in {"pyproject.toml", "pixi.toml"}:
        try:
            document = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise EnvironmentError(f"Invalid TOML dependency config {config_path}: {error}") from error
        pixi = document.get("tool", {}).get("pixi", {}) if name == "pyproject.toml" else document
        if pixi:
            python, conda, pypi, channels, config_local = _pixi_dependencies(
                pixi,
                config_path.parent,
                environment_name,
                optional_dependencies,
            )
        elif name == "pyproject.toml":
            python, conda, pypi, channels, config_local = _pep621_dependencies(
                document,
                optional_dependencies,
                config_path.parent,
            )
        else:
            raise EnvironmentError(f"No Pixi dependency tables were found in {config_path}")
    elif name in {"environment.yml", "environment.yaml"}:
        python, conda, pypi, channels, config_local = _environment_yml_dependencies(config_path)
        if optional_dependencies:
            raise EnvironmentError("Dependency extras are only supported for pyproject.toml and Pixi features")
    elif name == "requirements.txt":
        python, conda, pypi, channels, config_local = (
            ">=3.9",
            (),
            _requirements_dependencies(config_path),
            ("conda-forge",),
            (),
        )
        if optional_dependencies:
            raise EnvironmentError("Dependency extras are not supported for requirements.txt")
    else:
        raise EnvironmentError(
            f"Unsupported dependency config {config_path.name!r}; expected pyproject.toml, pixi.toml, "
            "environment.yml, environment.yaml, or requirements.txt"
        )

    all_local = _deduplicate_local_packages((*config_local, *local_packages))
    local_names = {package.distribution_name for package in all_local}
    filtered_pypi = tuple(
        dependency
        for dependency in pypi
        if canonicalize_name(Requirement(dependency).name) not in local_names
    )
    return EnvironmentSpec(
        python=python,
        conda=conda,
        pypi=filtered_pypi,
        channels=channels,
        local=all_local,
    )


def _pep621_dependencies(
    document: dict,
    optional_dependencies: list[str],
    base: Path,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[LocalPackage, ...]]:
    project = document.get("project")
    if not isinstance(project, dict):
        return ">=3.9", (), (), ("conda-forge",), ()

    dependency_groups = [project.get("dependencies", [])]
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        optional = {}
    for group in optional_dependencies:
        if group not in optional:
            raise EnvironmentError(
                f"Optional dependency group {group!r} was not found; available groups: {sorted(optional)}"
            )
        dependency_groups.append(optional[group])

    uv = document.get("tool", {}).get("uv", {})
    uv_sources = uv.get("sources", {}) if isinstance(uv, dict) else {}
    if not isinstance(uv_sources, dict):
        uv_sources = {}
    dependencies: list[str] = []
    local: list[LocalPackage] = []
    for group in dependency_groups:
        group_dependencies, group_local = _requirements_and_local_packages(group, base, uv_sources)
        dependencies.extend(group_dependencies)
        local.extend(group_local)

    requires_python = project.get("requires-python", ">=3.9")
    return (
        str(requires_python),
        (),
        tuple(dict.fromkeys(dependencies)),
        ("conda-forge",),
        _deduplicate_local_packages(tuple(local)),
    )


def _pixi_dependencies(
    pixi: dict,
    base: Path,
    environment_name: str,
    optional_dependencies: list[str],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[LocalPackage, ...]]:
    if not isinstance(pixi, dict):
        raise EnvironmentError("Pixi configuration must be a TOML table")

    environments = pixi.get("environments", {})
    selected_features: list[str] = []
    if isinstance(environments, dict) and environments:
        selected = environments.get(environment_name, environments.get("default", {}))
        if not isinstance(selected, dict):
            raise EnvironmentError(f"Pixi environment {environment_name!r} must be a TOML table")
        selected_features.extend(str(feature) for feature in selected.get("features", []))
    selected_features.extend(optional_dependencies)
    selected_features = list(dict.fromkeys(selected_features))

    conda_tables = [pixi.get("dependencies", {})]
    pypi_tables = [pixi.get("pypi-dependencies", {})]
    features = pixi.get("feature", {})
    if not isinstance(features, dict):
        features = {}
    for feature_name in selected_features:
        feature = features.get(feature_name)
        if not isinstance(feature, dict):
            raise EnvironmentError(f"Pixi feature {feature_name!r} was not found; available features: {sorted(features)}")
        conda_tables.append(feature.get("dependencies", {}))
        pypi_tables.append(feature.get("pypi-dependencies", {}))

    python = ">=3.9"
    conda: list[str] = []
    pypi: list[str] = []
    local: list[LocalPackage] = []
    for table in conda_tables:
        if not isinstance(table, dict):
            raise EnvironmentError("Pixi dependencies must be a TOML table")
        for package, constraint in table.items():
            rendered = _render_conda_requirement(str(package), constraint)
            if canonicalize_name(str(package)) == "python":
                python = rendered.removeprefix(str(package)) or ">=3.9"
            else:
                conda.append(rendered)
    for table in pypi_tables:
        if not isinstance(table, dict):
            raise EnvironmentError("Pixi pypi-dependencies must be a TOML table")
        for package, constraint in table.items():
            dependency, local_package = _render_pixi_pypi_requirement(str(package), constraint, base)
            if dependency:
                pypi.append(dependency)
            if local_package:
                local.append(local_package)

    workspace = pixi.get("workspace", pixi.get("project", {}))
    raw_channels = workspace.get("channels", ["conda-forge"]) if isinstance(workspace, dict) else ["conda-forge"]
    channels = tuple(str(channel) for channel in raw_channels) if raw_channels else ("conda-forge",)
    return (
        python,
        tuple(dict.fromkeys(conda)),
        tuple(dict.fromkeys(pypi)),
        channels,
        tuple(local),
    )


def _render_conda_requirement(package: str, constraint: object) -> str:
    if isinstance(constraint, dict):
        constraint = constraint.get("version", "*")
    version = str(constraint).strip()
    return package if version in {"", "*"} else f"{package}{version}"


def _render_pixi_pypi_requirement(
    package: str,
    constraint: object,
    base: Path,
) -> tuple[Optional[str], Optional[LocalPackage]]:
    if isinstance(constraint, str):
        version = constraint.strip()
        return (package if version in {"", "*"} else f"{package}{version}"), None
    if not isinstance(constraint, dict):
        raise EnvironmentError(f"Invalid Pixi PyPI dependency for {package!r}")

    extras = tuple(str(extra) for extra in constraint.get("extras", []))
    extras_text = f"[{','.join(extras)}]" if extras else ""
    if "path" in constraint:
        source = _resolve_dependency_path(str(constraint["path"]), base)
        return None, LocalPackage(
            source=source,
            extras=extras,
            content_identity=local_package_content_identity(source),
        )
    if "git" in constraint:
        revision = constraint.get("rev") or constraint.get("revision")
        if not revision:
            raise EnvironmentError(f"Pixi Git dependency {package!r} must be pinned with rev")
        return f"{package}{extras_text} @ git+{constraint['git']}@{revision}", None
    if "url" in constraint:
        return f"{package}{extras_text} @ {constraint['url']}", None
    version = str(constraint.get("version", "*")).strip()
    return (f"{package}{extras_text}" if version in {"", "*"} else f"{package}{extras_text}{version}"), None


def _environment_yml_dependencies(
    config_path: Path,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[LocalPackage, ...]]:
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise EnvironmentError(f"Invalid YAML dependency config {config_path}: {error}") from error
    if not isinstance(document, dict):
        raise EnvironmentError(f"Dependency config {config_path} must contain a YAML mapping")

    python = ">=3.9"
    conda: list[str] = []
    pypi: list[str] = []
    for dependency in document.get("dependencies", []):
        if isinstance(dependency, str):
            if canonicalize_name(dependency.split("=", 1)[0]) == "python":
                python = dependency.removeprefix(dependency.split("=", 1)[0]).replace("=", "", 1) or ">=3.9"
            elif dependency != "pip":
                conda.append(dependency)
        elif isinstance(dependency, dict) and isinstance(dependency.get("pip"), list):
            pypi.extend(_requirement_strings(dependency["pip"]))
    raw_channels = document.get("channels", ["conda-forge"])
    channels = tuple(str(channel) for channel in raw_channels) if raw_channels else ("conda-forge",)
    return python, tuple(conda), tuple(pypi), channels, ()


def _requirements_dependencies(config_path: Path) -> tuple[str, ...]:
    dependencies = []
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            dependencies.extend(_requirement_strings([line]))
    return tuple(dependencies)


def _requirements_and_local_packages(
    values: object,
    base: Path,
    source_table: dict,
) -> tuple[list[str], list[LocalPackage]]:
    if not isinstance(values, list):
        raise EnvironmentError("Python dependencies must be a list of requirement strings")
    dependencies: list[str] = []
    local: list[LocalPackage] = []
    for value in values:
        if not isinstance(value, str):
            raise EnvironmentError("Python dependencies must be requirement strings")
        try:
            requirement = Requirement(value)
        except InvalidRequirement as error:
            raise EnvironmentError(f"Invalid Python dependency {value!r}: {error}") from error
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue

        source: Optional[Path] = None
        configured_source = source_table.get(requirement.name, source_table.get(canonicalize_name(requirement.name)))
        if isinstance(configured_source, dict) and isinstance(configured_source.get("path"), str):
            source = _resolve_dependency_path(configured_source["path"], base)
        elif isinstance(configured_source, str):
            source = _path_from_dependency_target(configured_source, base)
        elif requirement.url:
            source = _path_from_dependency_target(requirement.url, base)

        if source is not None:
            local.append(
                LocalPackage(
                    source=source,
                    extras=tuple(sorted(requirement.extras)),
                    content_identity=local_package_content_identity(source),
                )
            )
        else:
            dependencies.extend(_requirement_strings([value]))
    return dependencies, local


def _requirement_strings(values: object) -> list[str]:
    if not isinstance(values, list):
        raise EnvironmentError("Python dependencies must be a list of requirement strings")
    dependencies: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise EnvironmentError("Python dependencies must be requirement strings")
        try:
            requirement = Requirement(value)
        except InvalidRequirement as error:
            raise EnvironmentError(f"Invalid Python dependency {value!r}: {error}") from error
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
        target = f" @ {requirement.url}" if requirement.url else str(requirement.specifier)
        dependencies.append(f"{requirement.name}{extras}{target}")
    return dependencies


def _deduplicate_local_packages(packages: tuple[LocalPackage, ...]) -> tuple[LocalPackage, ...]:
    by_name: dict[str, LocalPackage] = {}
    for package in packages:
        existing = by_name.get(package.distribution_name)
        if existing is not None and existing != package:
            raise EnvironmentError(f"Multiple local packages declare distribution {package.distribution_name!r}")
        by_name[package.distribution_name] = package
    return tuple(by_name.values())


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
            return _resolve_dependency_path(unquote(parsed.path), base)
    if target.startswith((".", "/", "~")):
        return _resolve_dependency_path(target, base)
    return None


def _resolve_dependency_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


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
