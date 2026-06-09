"""Tests for the environment module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from launcher.config import AppConfig, EntryPointConfig
from launcher.environment import (
    LauncherEnvironmentManager,
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
        assert 'wetlands_instance_path' in call_kwargs
        assert '.launcher/wetlands' in str(call_kwargs['wetlands_instance_path'])

    @patch('launcher.environment.EnvironmentManager')
    def test_initialization_custom_path(self, mock_env_manager_class, tmp_path):
        """Test initialization with custom path."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        custom_path = tmp_path / "custom_wetlands"
        LauncherEnvironmentManager(wetlands_path=custom_path)

        call_kwargs = mock_env_manager_class.call_args[1]
        assert call_kwargs['wetlands_instance_path'] == custom_path

    @patch('launcher.environment.EnvironmentManager')
    def test_environment_exists(self, mock_env_manager_class):
        """Test checking if environment exists."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        # Setup mock
        mock_instance.settings_manager.get_environment_path_from_name.return_value = Path("/env/path")
        mock_instance.environment_exists.return_value = True

        manager = LauncherEnvironmentManager()
        result = manager.environment_exists("test_env")

        assert result is True
        mock_instance.settings_manager.get_environment_path_from_name.assert_called_with("test_env")

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_from_config(self, mock_env_manager_class, tmp_path):
        """Test getting or creating environment from config file."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.create_from_config.return_value = mock_env

        # Create a mock config
        config = MagicMock()
        config.env_name = "test_env"
        config.extras = []
        config.config_file_path = tmp_path / "pyproject.toml"
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        mock_instance.create_from_config.assert_called_once()
        assert mock_instance.create_from_config.call_args.kwargs["optional_dependencies"] is None

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_from_config_with_extras(self, mock_env_manager_class, tmp_path):
        """Python optional dependency groups are passed to Wetlands."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.create_from_config.return_value = mock_env

        config = MagicMock()
        config.env_name = "test_env"
        config.extras = ["desktop", "server"]
        config.config_file_path = tmp_path / "pyproject.toml"
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        mock_instance.create_from_config.assert_called_once_with(
            name="test_env",
            config_path=tmp_path / "pyproject.toml",
            optional_dependencies=["desktop", "server"],
        )

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_configuration_disabled(self, mock_env_manager_class):
        """configuration: null creates an environment without dependency config."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.create.return_value = mock_env

        config = MagicMock()
        config.env_name = "test_env"
        config.configuration = None
        config.extras = []
        config.config_file_path = None

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        mock_instance.create.assert_called_once_with(name="test_env")

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

        mock_instance.set_proxies.assert_called_once_with({
            "http": "http://proxy:8080",
            "https": "https://proxy:8080"
        })

    @patch('launcher.environment.EnvironmentManager')
    def test_set_proxies_http_only(self, mock_env_manager_class):
        """Test setting HTTP-only proxy."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        manager = LauncherEnvironmentManager()
        manager.set_proxies("http://proxy:8080", None)

        mock_instance.set_proxies.assert_called_once_with({
            "http": "http://proxy:8080"
        })

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

        mock_instance.exit.assert_called_once()

    @patch('launcher.environment.EnvironmentManager')
    def test_delete_environment_success(self, mock_env_manager_class):
        """Test deleting an environment."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        # Setup mock
        mock_instance.settings_manager.get_environment_path_from_name.return_value = Path("/env/path")
        mock_instance.environment_exists.return_value = True

        mock_env = MagicMock()
        mock_instance.load.return_value = mock_env

        manager = LauncherEnvironmentManager()
        result = manager.delete_environment("test_env")

        assert result is True
        mock_env.delete.assert_called_once()

    @patch('launcher.environment.EnvironmentManager')
    def test_delete_environment_not_exists(self, mock_env_manager_class):
        """Test deleting non-existent environment."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        # Setup mock - environment doesn't exist
        mock_instance.settings_manager.get_environment_path_from_name.return_value = Path("/env/path")
        mock_instance.environment_exists.return_value = False

        manager = LauncherEnvironmentManager()
        result = manager.delete_environment("test_env")

        assert result is False


class TestDependencyHash:
    """Tests for environment dependency hashing."""

    def test_hash_changes_when_dependency_file_changes(self, tmp_path):
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
        sources = tmp_path / "apps" / "testapp-v1.0.0"
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
