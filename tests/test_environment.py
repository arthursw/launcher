"""Tests for the environment module."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from launcher.config import AppConfig, EntryPointConfig
from launcher.environment import (
    EnvironmentError as LauncherEnvironmentError,
    LauncherEnvironmentManager,
    _environment_spec_from_config,
    compute_dependency_hash,
    compute_project_install_fingerprint,
)


class TestLauncherEnvironmentManager:
    """Tests for LauncherEnvironmentManager class."""

    @patch('launcher.environment.EnvironmentManager')
    def test_initialization_default_path(self, mock_env_manager_class):
        """Test initialization with default path."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        LauncherEnvironmentManager()

        # Should use default path
        mock_env_manager_class.assert_called_once()
        call_kwargs = mock_env_manager_class.call_args[1]
        assert '.launcher/wetlands' in str(call_kwargs['root'])

    @patch('launcher.environment.EnvironmentManager')
    def test_initialization_custom_path(self, mock_env_manager_class, tmp_path):
        """Test initialization with custom path."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        custom_path = tmp_path / "custom_wetlands"
        LauncherEnvironmentManager(wetlands_path=custom_path)

        call_kwargs = mock_env_manager_class.call_args[1]
        assert call_kwargs['root'] == custom_path

    @patch('launcher.environment.EnvironmentManager')
    def test_environment_exists(self, mock_env_manager_class):
        """Test checking if environment exists."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_instance.managed_environments.return_value = (
            SimpleNamespace(name="test_env", ready=True),
        )

        manager = LauncherEnvironmentManager()
        result = manager.environment_exists("test_env")

        assert result is True
        mock_instance.managed_environments.assert_called_once_with()

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_from_config(self, mock_env_manager_class, tmp_path):
        """Test getting or creating environment from config file."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.provision.return_value.wait_for.return_value = mock_env

        # Create a mock config
        config = MagicMock()
        config.env_name = "test_env"
        config.extras = []
        config.config_file_path = tmp_path / "pyproject.toml"
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        name, spec = mock_instance.provision.call_args.args
        assert name == "test_env"
        assert spec.pypi == ()
        assert mock_instance.provision.call_args.kwargs == {"replace_existing": True}

    @patch('launcher.environment.EnvironmentManager')
    def test_project_mode_adds_wetlands_local_dependency_from_config(self, mock_env_manager_class, tmp_path):
        """Project mode should let Wetlands install the local package with backend-specific commands."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance
        mock_env = MagicMock()
        mock_instance.provision.return_value.wait_for.return_value = mock_env

        sources = tmp_path / "apps" / "sources" / "myapp-v1.2.3"
        project = sources / "backend"
        project.mkdir(parents=True)
        pyproject = project / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'my-app'\ndependencies = ['requests']\n")
        config = AppConfig(
            name="MyApp",
            entrypoint=EntryPointConfig(mode="project", command="my-app-gui", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="https://github.com/my-org/myapp.git",
            version="v1.2.3",
            configuration="backend/pyproject.toml",
        )

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        name, spec = mock_instance.provision.call_args.args
        assert name == "MyApp"
        assert spec.pypi == ("requests",)
        assert len(spec.local) == 1
        assert spec.local[0].distribution_name == "my-app"
        assert spec.local[0].source == project
        assert spec.local[0].editable is False
        assert spec.local[0].content_identity is not None
        assert mock_instance.provision.call_args.kwargs == {"replace_existing": True}

    @patch('launcher.environment.EnvironmentManager')
    def test_project_mode_requires_package_name_for_wetlands_local_dependency(
        self,
        mock_env_manager_class,
        tmp_path,
    ):
        """Wetlands local dependencies need the Python distribution name."""
        mock_env_manager_class.return_value = MagicMock()
        sources = tmp_path / "apps" / "sources" / "myapp-v1.2.3"
        project = sources / "backend"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[tool.pixi.project]\nname = 'pixi-env'\n")
        config = AppConfig(
            name="MyApp",
            entrypoint=EntryPointConfig(mode="project", command="my-app-gui", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="https://github.com/my-org/myapp.git",
            version="v1.2.3",
            configuration="backend/pyproject.toml",
        )

        manager = LauncherEnvironmentManager()

        with pytest.raises(LauncherEnvironmentError, match=r"\[project\]\.name"):
            manager.get_or_create_environment(config)

    @patch('launcher.environment.EnvironmentManager')
    def test_project_mode_rejects_missing_project_local_dependency_path(
        self,
        mock_env_manager_class,
        tmp_path,
    ):
        """Missing local path dependencies should fail before Pixi reports a solver error."""
        mock_env_manager_class.return_value = MagicMock()
        sources = tmp_path / "apps" / "sources" / "myapp-v1.2.3"
        project = sources / "backend"
        project.mkdir(parents=True)
        missing = sources / "packages" / "my-core"
        (project / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    "name = 'my-app'",
                    "dependencies = ['my-core @ ../packages/my-core']",
                ]
            )
        )
        config = AppConfig(
            name="MyApp",
            entrypoint=EntryPointConfig(mode="project", command="my-app-gui", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="https://github.com/my-org/myapp.git",
            version="v1.2.3",
            configuration="backend/pyproject.toml",
        )

        manager = LauncherEnvironmentManager()

        with pytest.raises(LauncherEnvironmentError) as exc_info:
            manager.get_or_create_environment(config)

        message = str(exc_info.value)
        assert "missing local path dependency" in message
        assert str(missing) in message
        assert "release archive" in message
        assert "release.archive.include" in message

    @patch('launcher.environment.EnvironmentManager')
    def test_project_mode_rejects_missing_uv_source_path(
        self,
        mock_env_manager_class,
        tmp_path,
    ):
        """tool.uv.sources local paths should also be validated before environment creation."""
        mock_env_manager_class.return_value = MagicMock()
        sources = tmp_path / "apps" / "sources" / "myapp-v1.2.3"
        project = sources / "backend"
        project.mkdir(parents=True)
        missing = sources / "packages" / "my-core"
        (project / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    "name = 'my-app'",
                    "dependencies = ['my-core']",
                    "[tool.uv.sources]",
                    "my-core = { path = '../packages/my-core', editable = true }",
                ]
            )
        )
        config = AppConfig(
            name="MyApp",
            entrypoint=EntryPointConfig(mode="project", command="my-app-gui", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="https://github.com/my-org/myapp.git",
            version="v1.2.3",
            configuration="backend/pyproject.toml",
        )

        manager = LauncherEnvironmentManager()

        with pytest.raises(LauncherEnvironmentError) as exc_info:
            manager.get_or_create_environment(config)

        assert str(missing) in str(exc_info.value)

    @patch('launcher.environment.EnvironmentManager')
    def test_environment_create_failure_is_wrapped_with_project_context(
        self,
        mock_env_manager_class,
        tmp_path,
    ):
        """Wetlands command failures should surface as actionable environment errors."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance
        mock_instance.provision.return_value.wait_for.side_effect = Exception("failed to solve the pypi requirements")
        sources = tmp_path / "apps" / "sources" / "myapp-v1.2.3"
        project = sources / "backend"
        project.mkdir(parents=True)
        pyproject = project / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'my-app'\n")
        config = AppConfig(
            name="MyApp",
            entrypoint=EntryPointConfig(mode="project", command="my-app-gui", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="https://github.com/my-org/myapp.git",
            version="v1.2.3",
            configuration="backend/pyproject.toml",
        )

        manager = LauncherEnvironmentManager()

        with pytest.raises(LauncherEnvironmentError) as exc_info:
            manager.get_or_create_environment(config)

        message = str(exc_info.value)
        assert "Wetlands failed to create environment" in message
        assert str(pyproject) in message
        assert str(project) in message
        assert "release.archive.include" in message

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_from_config_with_extras(self, mock_env_manager_class, tmp_path):
        """Python optional dependency groups are passed to Wetlands."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.provision.return_value.wait_for.return_value = mock_env

        config = MagicMock()
        config.env_name = "test_env"
        config.extras = ["desktop", "server"]
        config.config_file_path = tmp_path / "pyproject.toml"
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname='test'\n"
            "[project.optional-dependencies]\n"
            "desktop = ['pyside6']\n"
            "server = ['requests']\n"
        )

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        name, spec = mock_instance.provision.call_args.args
        assert name == "test_env"
        assert spec.pypi == ("pyside6", "requests")

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_configuration_disabled(self, mock_env_manager_class):
        """configuration: null creates an environment without dependency config."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.provision.return_value.wait_for.return_value = mock_env

        config = MagicMock()
        config.env_name = "test_env"
        config.configuration = None
        config.extras = []
        config.config_file_path = None

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        name, spec = mock_instance.provision.call_args.args
        assert name == "test_env"
        assert spec.pypi == ()
        assert spec.conda == ()

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_requires_configured_file(self, mock_env_manager_class):
        """A configured dependency file must exist."""
        mock_env_manager_class.return_value = MagicMock()

        config = MagicMock()
        config.env_name = "test_env"
        config.configuration = "backend/pyproject.toml"
        config.extras = []
        config.config_file_path = Path("/nonexistent/backend/pyproject.toml")

        manager = LauncherEnvironmentManager()

        try:
            manager.get_or_create_environment(config)
        except Exception as exc:
            assert "Dependency config file was not found" in str(exc)
            assert "backend/pyproject.toml" in str(exc)
            assert "configuration: null" in str(exc)
        else:
            raise AssertionError("Expected missing configured dependency file to fail")

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_requires_config_for_extras(self, mock_env_manager_class):
        """Extras cannot be installed if dependency config loading is disabled."""
        mock_env_manager_class.return_value = MagicMock()

        config = MagicMock()
        config.env_name = "test_env"
        config.configuration = None
        config.extras = ["desktop"]
        config.config_file_path = None

        manager = LauncherEnvironmentManager()

        try:
            manager.get_or_create_environment(config)
        except Exception as exc:
            assert "Dependency extras require a dependency config file" in str(exc)
        else:
            raise AssertionError("Expected missing config with extras to fail")

    @patch('launcher.environment.EnvironmentManager')
    def test_set_proxies(self, mock_env_manager_class):
        """Test setting proxy settings."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        manager = LauncherEnvironmentManager()
        manager.set_proxies("http://proxy:8080", "https://proxy:8080")

        mock_instance.close.assert_called_once_with()
        assert mock_env_manager_class.call_args.kwargs == {
            "root": manager._wetlands_path,
            "network": {
                "http": "http://proxy:8080",
                "https": "https://proxy:8080",
            },
        }

    @patch('launcher.environment.EnvironmentManager')
    def test_set_proxies_http_only(self, mock_env_manager_class):
        """Test setting HTTP-only proxy."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        manager = LauncherEnvironmentManager()
        manager.set_proxies("http://proxy:8080", None)

        mock_instance.close.assert_called_once_with()
        assert mock_env_manager_class.call_args.kwargs == {
            "root": manager._wetlands_path,
            "network": {"http": "http://proxy:8080"},
        }

    @patch('launcher.environment.EnvironmentManager')
    def test_set_proxies_with_ssl_cert_file(self, mock_env_manager_class, monkeypatch):
        """Test that set_proxies with ssl_cert_file sets environment variables."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        # Clear existing env vars
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        manager = LauncherEnvironmentManager()
        manager.set_proxies("http://proxy:8080", None, ssl_cert_file="/path/to/cert.pem")

        import os
        assert os.environ.get("SSL_CERT_FILE") == "/path/to/cert.pem"
        assert os.environ.get("REQUESTS_CA_BUNDLE") == "/path/to/cert.pem"

        # Clean up
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    @patch('launcher.environment.EnvironmentManager')
    def test_exit(self, mock_env_manager_class):
        """Test exiting the environment manager."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        manager = LauncherEnvironmentManager()
        manager.exit()

        mock_instance.close.assert_called_once()

    @patch('launcher.environment.EnvironmentManager')
    def test_delete_environment_success(self, mock_env_manager_class):
        """Test deleting an environment."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_instance.managed_environments.return_value = (
            SimpleNamespace(name="test_env", ready=True),
        )
        removal = mock_instance.remove.return_value

        manager = LauncherEnvironmentManager()
        result = manager.delete_environment("test_env")

        assert result is True
        mock_instance.remove.assert_called_once_with("test_env")
        removal.wait_for.assert_called_once_with()

    @patch('launcher.environment.EnvironmentManager')
    def test_delete_environment_not_exists(self, mock_env_manager_class):
        """Test deleting non-existent environment."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_instance.managed_environments.return_value = ()

        manager = LauncherEnvironmentManager()
        result = manager.delete_environment("test_env")

        assert result is False

    @patch('launcher.environment.subprocess.Popen')
    @patch('launcher.environment.EnvironmentManager')
    def test_execute_command_uses_managed_pixi_project(
        self,
        mock_env_manager_class,
        mock_popen,
        tmp_path,
    ):
        """Application commands should run through the public Wetlands Pixi paths."""
        mock_instance = MagicMock()
        mock_instance.state_root = tmp_path / "state"
        mock_instance.network = {"https": "https://proxy:8080"}
        mock_env_manager_class.return_value = mock_instance
        environment = SimpleNamespace(
            pixi_executable_path=tmp_path / "pixi",
            pixi_manifest_path=tmp_path / "environment" / "pixi.toml",
        )
        manager = LauncherEnvironmentManager(wetlands_path=tmp_path / "wetlands")

        manager.execute_command(environment, ["python", "app.py"], cwd=tmp_path)

        argv = mock_popen.call_args.args[0]
        assert argv == [
            str(tmp_path / "pixi"),
            "run",
            "--manifest-path",
            str(tmp_path / "environment" / "pixi.toml"),
            "python",
            "app.py",
        ]
        assert mock_popen.call_args.kwargs["cwd"] == tmp_path
        assert mock_popen.call_args.kwargs["env"]["HTTPS_PROXY"] == "https://proxy:8080"


def test_pixi_config_is_translated_to_environment_spec(tmp_path):
    """Pixi base dependencies and selected features should survive the Wetlands 2 migration."""
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text(
        "[project]\nname = 'demo'\n"
        "[tool.pixi.workspace]\nchannels = ['conda-forge', 'pytorch']\n"
        "[tool.pixi.dependencies]\npython = '3.12.*'\nnumpy = '>=2'\n"
        "[tool.pixi.pypi-dependencies]\nrequests = '>=2.32'\n"
        "[tool.pixi.feature.desktop.pypi-dependencies]\npyside6 = '>=6.8'\n"
    )

    spec = _environment_spec_from_config(
        config_path,
        environment_name="demo",
        optional_dependencies=["desktop"],
        local_packages=(),
    )

    assert spec.python == "3.12.*"
    assert spec.conda == ("numpy>=2",)
    assert spec.pypi == ("requests>=2.32", "pyside6>=6.8")
    assert spec.channels == ("conda-forge", "pytorch")


def test_uv_local_sources_become_immutable_local_packages(tmp_path):
    """Local uv sources should keep working after Wetlands removed dependency dictionaries."""
    local_package = tmp_path / "packages" / "my-core"
    local_package.mkdir(parents=True)
    (local_package / "pyproject.toml").write_text("[project]\nname = 'my-core'\nversion = '1.0.0'\n")
    project = tmp_path / "backend"
    project.mkdir()
    config_path = project / "pyproject.toml"
    config_path.write_text(
        "[project]\nname = 'demo'\ndependencies = ['my-core', 'requests>=2']\n"
        "[tool.uv.sources]\nmy-core = { path = '../packages/my-core', editable = true }\n"
    )

    spec = _environment_spec_from_config(
        config_path,
        environment_name="demo",
        optional_dependencies=[],
        local_packages=(),
    )

    assert spec.pypi == ("requests>=2",)
    assert len(spec.local) == 1
    assert spec.local[0].distribution_name == "my-core"
    assert spec.local[0].editable is False
    assert spec.local[0].content_identity is not None


class TestDependencyHash:
    """Tests for environment dependency hashing."""

    def test_hash_changes_when_dependency_file_changes(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        sources.mkdir(parents=True)
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="pyproject.toml",
        )
        (sources / "pyproject.toml").write_text("[project]\nname='a'\n")
        first = compute_dependency_hash(config)

        (sources / "pyproject.toml").write_text("[project]\nname='b'\n")

        assert compute_dependency_hash(config) != first

    def test_hash_includes_lock_file_and_install_script(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        sources.mkdir(parents=True)
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="pyproject.toml",
            install="install.py",
        )
        (sources / "pyproject.toml").write_text("[project]\nname='a'\n")
        (sources / "uv.lock").write_text("lock-a")
        (sources / "install.py").write_text("print('a')")
        first = compute_dependency_hash(config)

        (sources / "uv.lock").write_text("lock-b")
        second = compute_dependency_hash(config)
        (sources / "install.py").write_text("print('b')")

        assert second != first
        assert compute_dependency_hash(config) != second

    def test_hash_changes_when_extras_change(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        sources.mkdir(parents=True)
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="pyproject.toml",
            extras=["desktop"],
        )
        (sources / "pyproject.toml").write_text("[project]\nname='a'\n")
        first = compute_dependency_hash(config)

        config.extras = ["desktop", "server"]

        assert compute_dependency_hash(config) != first

    def test_project_install_fingerprint_changes_when_version_changes(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        project = sources / "backend"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname='a'\n")
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="project", command="test-app", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="backend/pyproject.toml",
        )

        first = compute_project_install_fingerprint(config, "v1.0.0")

        assert compute_project_install_fingerprint(config, "v1.0.1") != first

    def test_project_install_fingerprint_changes_when_project_metadata_changes(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        project = sources / "backend"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname='a'\n")
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="project", command="test-app", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="backend/pyproject.toml",
        )
        first = compute_project_install_fingerprint(config, "v1.0.0")

        (project / "pyproject.toml").write_text("[project]\nname='b'\n")

        assert compute_project_install_fingerprint(config, "v1.0.0") != first

    def test_project_install_fingerprint_changes_when_project_entrypoint_changes(self, tmp_path):
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        project = sources / "backend"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname='a'\n")
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="project", command="test-app", project_directory="backend"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="backend/pyproject.toml",
        )
        first = compute_project_install_fingerprint(config, "v1.0.0")

        config.entrypoint.command = "test-app-gui"

        assert compute_project_install_fingerprint(config, "v1.0.0") != first
