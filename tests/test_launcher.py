"""Tests for core launcher functionality."""

import os
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
from launcher import Launcher


class TestLauncherConfig:
    """Test configuration loading."""

    def test_load_config_valid_yaml(self):
        """Test loading a valid application.yml file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            config = launcher.load_config()

            assert config["name"] == "TestApp"
            assert config["version"] == "testapp-v1.0.0"
            assert config["auto_update"] is False

    def test_load_config_file_not_found(self):
        """Test that FileNotFoundError is raised when config doesn't exist."""
        with pytest.raises(FileNotFoundError):
            Launcher("/nonexistent/path/application.yml")

    def test_load_config_invalid_yaml(self):
        """Test that invalid YAML raises an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_path.write_text("invalid: yaml: content: [")

            with pytest.raises(Exception):  # YAML parsing error
                Launcher(str(config_path))

    def test_path_override(self):
        """Test that path_override parameter overrides config path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            override_path = "/override/path"
            launcher = Launcher(str(config_path), path_override=override_path)

            assert launcher.config["path"] == override_path

    def test_path_not_overridden_when_not_provided(self):
        """Test that path from config is used when no override provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            original_path = "/original/path"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{original_path}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))

            assert launcher.config["path"] == original_path

    def test_load_config_with_repository_github(self):
        """Test loading config with repository instead of explicit endpoints."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
repository: git@github.com:owner/testapp.git
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            config = launcher.config

            # Endpoints should be inferred from repository
            assert config["api"] == "https://api.github.com/"
            assert config["tags_endpoint"] == "/repos/owner/testapp/git/tags"
            assert config["archive_endpoint"] == "/repos/owner/testapp/zipball/{ref}"

    def test_load_config_with_repository_gitlab(self):
        """Test loading config with GitLab repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
repository: git@gitlab.inria.fr:owner/testapp.git
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            config = launcher.config

            # Endpoints should be inferred from repository
            assert config["api"] == "https://gitlab.inria.fr/api/v4/"
            assert config["tags_endpoint"] == "/projects/owner%2Ftestapp/repository/tags"
            assert config["archive_endpoint"] == "/projects/owner%2Ftestapp/repository/archive.zip"

    def test_explicit_endpoints_override_repository(self):
        """Test that explicit endpoints override repository inference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
repository: git@github.com:owner/testapp.git
api: https://custom.api.com/
tags_endpoint: /custom/tags
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            config = launcher.config

            # Explicit endpoints should take priority
            assert config["api"] == "https://custom.api.com/"
            assert config["tags_endpoint"] == "/custom/tags"
            # archive_endpoint should be inferred since not explicitly provided
            assert config["archive_endpoint"] == "/repos/owner/testapp/zipball/{ref}"

    def test_missing_repository_and_endpoints_raises_error(self):
        """Test that missing both repository and endpoints raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            with pytest.raises(ValueError, match="Configuration must include either"):
                Launcher(str(config_path))


class TestLauncherVersion:
    """Test version management."""

    def test_get_current_version_no_auto_update(self):
        """Test that get_current_version returns config version when auto_update is false."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            version = launcher.get_current_version()

            assert version == "testapp-v1.0.0"

    @patch("launcher.requests.get")
    def test_get_current_version_with_auto_update(self, mock_get):
        """Test that get_current_version fetches latest tag when auto_update is true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: true
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            # Mock API response
            mock_response = Mock()
            mock_response.json.return_value = [
                {"name": "v2.0.0", "commit": {"sha": "abc123"}},
                {"name": "v1.0.0", "commit": {"sha": "def456"}},
            ]
            mock_get.return_value = mock_response

            launcher = Launcher(str(config_path))
            version = launcher.get_current_version()

            assert version == "testapp-v2.0.0"
            mock_get.assert_called_once()

    @patch("launcher.requests.get")
    def test_get_current_version_api_failure_fallback(self, mock_get):
        """Test that get_current_version falls back to config version on API failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: true
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_get.side_effect = Exception("Network error")

            launcher = Launcher(str(config_path))
            version = launcher.get_current_version()

            # Should fall back to config version
            assert version == "testapp-v1.0.0"


class TestLauncherSources:
    """Test source file management."""

    def test_sources_exist_true(self):
        """Test that sources_exist returns True when directory exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            # Create the source directory
            source_dir = Path(tmpdir) / "testapp-v1.0.0"
            source_dir.mkdir()

            launcher = Launcher(str(config_path))
            exists = launcher.sources_exist("testapp-v1.0.0")

            assert exists is True

    def test_sources_exist_false(self):
        """Test that sources_exist returns False when directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            exists = launcher.sources_exist("testapp-v1.0.0")

            assert exists is False


class TestLauncherDownload:
    """Test source downloading."""

    @patch("launcher.requests.get")
    @patch("launcher.zipfile.ZipFile")
    def test_download_sources_success(self, mock_zipfile, mock_get):
        """Test successful source download and extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            # Mock download
            mock_response = Mock()
            mock_response.content = b"zip file content"
            mock_get.return_value = mock_response

            # Mock zipfile
            mock_zf = MagicMock()
            mock_zipfile.return_value.__enter__.return_value = mock_zf

            launcher = Launcher(str(config_path))
            launcher.download_sources("testapp-v1.0.0")

            # Verify download was called
            mock_get.assert_called_once()
            # Verify extraction was called
            mock_zf.extractall.assert_called_once()

    @patch("launcher.requests.get")
    def test_download_sources_api_failure(self, mock_get):
        """Test that download_sources raises error on API failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_get.side_effect = Exception("Network error")

            launcher = Launcher(str(config_path))
            with pytest.raises(Exception):
                launcher.download_sources("testapp-v1.0.0")


class TestLauncherEnvironment:
    """Test environment setup."""

    @patch("launcher.EnvironmentManager")
    def test_setup_environment_creates_env(self, mock_env_manager):
        """Test that setup_environment creates a conda environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            # Create source directory with pyproject.toml
            source_dir = Path(tmpdir) / "testapp-v1.0.0"
            source_dir.mkdir()
            (source_dir / "pyproject.toml").write_text(
                "[project]\nname = 'testapp'\n"
            )

            launcher = Launcher(str(config_path))

            # Mock the environment manager
            mock_env_instance = MagicMock()
            mock_env_manager.return_value = mock_env_instance
            mock_env_manager.return_value.create.return_value = MagicMock()

            launcher.setup_environment("testapp-v1.0.0")

            mock_env_manager.assert_called_once()
            mock_env_manager.return_value.create.assert_called_once()


class TestLauncherInstallScript:
    """Test install script execution."""

    @patch("launcher.EnvironmentManager")
    def test_run_install_script_when_defined(self, mock_env_manager):
        """Test that run_install_script executes when install attribute is defined."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
install: install.sh
timeout: 3
"""
            config_path.write_text(config_content)

            # Create source directory with install script
            source_dir = Path(tmpdir) / "testapp-v1.0.0"
            source_dir.mkdir()
            (source_dir / "install.sh").write_text("#!/bin/bash\necho 'Installing'")

            launcher = Launcher(str(config_path))

            # Mock the environment manager
            mock_env_instance = MagicMock()
            mock_env_manager.return_value = mock_env_instance
            mock_env_instance.get_environment.return_value = MagicMock()

            launcher.run_install_script("testapp-v1.0.0")

            # Verify environment was retrieved and command executed
            mock_env_instance.get_environment.assert_called_once()
            mock_env_instance.get_environment.return_value.executeCommands.assert_called_once_with(
                "bash install.sh"
            )

    @patch("launcher.EnvironmentManager")
    def test_run_install_script_skipped_when_not_defined(self, mock_env_manager):
        """Test that run_install_script is skipped when install attribute is not defined."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            launcher = Launcher(str(config_path))
            launcher.run_install_script("testapp-v1.0.0")

            # Verify environment manager was not called
            mock_env_manager.assert_not_called()

    @patch("launcher.EnvironmentManager")
    def test_run_install_script_skipped_when_file_missing(self, mock_env_manager):
        """Test that run_install_script is skipped when install script file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
install: missing_install.sh
timeout: 3
"""
            config_path.write_text(config_content)

            # Create source directory without install script
            source_dir = Path(tmpdir) / "testapp-v1.0.0"
            source_dir.mkdir()

            launcher = Launcher(str(config_path))
            launcher.run_install_script("testapp-v1.0.0")

            # Verify environment manager was not called (script was skipped)
            mock_env_manager.assert_not_called()


class TestLauncherRun:
    """Test the main run method."""

    @patch("launcher.Launcher.get_current_version")
    @patch("launcher.Launcher.sources_exist")
    @patch("launcher.Launcher.setup_environment")
    @patch("launcher.Launcher.run_install_script")
    @patch("launcher.Launcher.run_app")
    def test_run_with_existing_sources(
        self,
        mock_run_app,
        mock_run_install,
        mock_setup_env,
        mock_sources_exist,
        mock_get_version,
    ):
        """Test run method when sources already exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_get_version.return_value = "testapp-v1.0.0"
            mock_sources_exist.return_value = True

            launcher = Launcher(str(config_path))
            launcher.run()

            mock_get_version.assert_called_once()
            mock_sources_exist.assert_called_once_with("testapp-v1.0.0")
            mock_setup_env.assert_called_once()
            mock_run_install.assert_called_once()
            mock_run_app.assert_called_once()

    @patch("launcher.Launcher.get_current_version")
    @patch("launcher.Launcher.sources_exist")
    @patch("launcher.Launcher.download_sources")
    @patch("launcher.Launcher.setup_environment")
    @patch("launcher.Launcher.run_install_script")
    @patch("launcher.Launcher.run_app")
    def test_run_with_missing_sources(
        self,
        mock_run_app,
        mock_run_install,
        mock_setup_env,
        mock_download,
        mock_sources_exist,
        mock_get_version,
    ):
        """Test run method when sources need to be downloaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = f"""
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{{ref}}
main: main.py
path: "{tmpdir}"
version: testapp-v1.0.0
auto_update: false
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_get_version.return_value = "testapp-v1.0.0"
            mock_sources_exist.return_value = False

            launcher = Launcher(str(config_path))
            launcher.run()

            mock_get_version.assert_called_once()
            mock_sources_exist.assert_called_once_with("testapp-v1.0.0")
            mock_download.assert_called_once()
            mock_setup_env.assert_called_once()
            mock_run_install.assert_called_once()
            mock_run_app.assert_called_once()
