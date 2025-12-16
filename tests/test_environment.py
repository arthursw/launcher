"""Tests for the environment module."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from launcher.environment import LauncherEnvironmentManager, EnvironmentError


class TestLauncherEnvironmentManager:
    """Tests for LauncherEnvironmentManager class."""

    @patch('launcher.environment.EnvironmentManager')
    def test_initialization_default_path(self, mock_env_manager_class):
        """Test initialization with default path."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        manager = LauncherEnvironmentManager()

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
        manager = LauncherEnvironmentManager(wetlands_path=custom_path)

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
        config.config_file_path = tmp_path / "pyproject.toml"
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        mock_instance.create_from_config.assert_called_once()

    @patch('launcher.environment.EnvironmentManager')
    def test_get_or_create_environment_no_config(self, mock_env_manager_class):
        """Test getting or creating environment without config file."""
        mock_instance = MagicMock()
        mock_env_manager_class.return_value = mock_instance

        mock_env = MagicMock()
        mock_instance.create.return_value = mock_env

        # Create a mock config with no config file
        config = MagicMock()
        config.env_name = "test_env"
        config.config_file_path = Path("/nonexistent/pyproject.toml")

        manager = LauncherEnvironmentManager()
        result = manager.get_or_create_environment(config)

        assert result == mock_env
        mock_instance.create.assert_called_once_with(name="test_env")

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
