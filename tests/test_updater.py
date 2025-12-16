"""Tests for the updater module."""

import io
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from launcher.config import AppConfig, ProxySettings
from launcher.updater import (
    fetch_latest_tag,
    get_version_string,
    check_sources_exist,
    download_and_extract_sources,
    NetworkError,
    DownloadError,
    UpdaterError,
)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return AppConfig(
        name="TestApp",
        main="main.py",
        path="/tmp/test_apps",
        repository="git@github.com:owner/repo.git"
    )


class TestGetVersionString:
    """Tests for get_version_string function."""

    def test_basic_version_string(self):
        """Test basic version string generation."""
        result = get_version_string("MyApp", "v1.0.0")
        assert result == "myapp-v1.0.0"

    def test_version_string_with_special_chars(self):
        """Test version string with special characters in app name."""
        result = get_version_string("My App!", "v1.0.0")
        assert result == "myapp-v1.0.0"

    def test_version_string_preserves_dashes(self):
        """Test that dashes in app name are preserved."""
        result = get_version_string("my-app", "v1.0.0")
        assert result == "my-app-v1.0.0"

    def test_version_string_preserves_underscores(self):
        """Test that underscores in app name are preserved."""
        result = get_version_string("my_app", "v1.0.0")
        assert result == "my_app-v1.0.0"


class TestCheckSourcesExist:
    """Tests for check_sources_exist function."""

    def test_sources_exist(self, tmp_path, mock_config):
        """Test when sources directory exists."""
        mock_config.path = str(tmp_path)
        mock_config.version = "testapp-v1.0.0"

        # Create the sources directory
        sources_dir = tmp_path / "testapp-v1.0.0"
        sources_dir.mkdir()

        assert check_sources_exist(mock_config) is True

    def test_sources_not_exist(self, tmp_path, mock_config):
        """Test when sources directory doesn't exist."""
        mock_config.path = str(tmp_path)
        mock_config.version = "testapp-v1.0.0"

        assert check_sources_exist(mock_config) is False

    def test_sources_no_version(self, mock_config):
        """Test when no version is set."""
        mock_config.version = None
        assert check_sources_exist(mock_config) is False


class TestFetchLatestTag:
    """Tests for fetch_latest_tag function."""

    @patch('launcher.updater.requests.get')
    def test_fetch_github_tags(self, mock_get, mock_config):
        """Test fetching tags from GitHub API."""
        mock_response = Mock()
        mock_response.json.return_value = [
            {"name": "v2.0.0"},
            {"name": "v1.0.0"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = fetch_latest_tag(mock_config)
        assert result == "v2.0.0"

    @patch('launcher.updater.requests.get')
    def test_fetch_no_tags(self, mock_get, mock_config):
        """Test error when no tags found."""
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(UpdaterError, match="No tags found"):
            fetch_latest_tag(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_connection_error(self, mock_get, mock_config):
        """Test network error handling."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(NetworkError, match="Failed to connect"):
            fetch_latest_tag(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_timeout_error(self, mock_get, mock_config):
        """Test timeout error handling."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        with pytest.raises(NetworkError, match="timed out"):
            fetch_latest_tag(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_with_proxy(self, mock_get, mock_config):
        """Test fetching with proxy settings."""
        mock_response = Mock()
        mock_response.json.return_value = [{"name": "v1.0.0"}]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        proxy = ProxySettings(http="http://proxy:8080", https="https://proxy:8080")
        result = fetch_latest_tag(mock_config, proxy_settings=proxy)

        # Verify proxy was passed to requests
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs['proxies'] == {"http": "http://proxy:8080", "https": "https://proxy:8080"}


class TestDownloadAndExtractSources:
    """Tests for download_and_extract_sources function."""

    @patch('launcher.updater.requests.get')
    def test_download_and_extract(self, mock_get, tmp_path, mock_config):
        """Test downloading and extracting sources."""
        mock_config.path = str(tmp_path)

        # Create a mock zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("owner-repo-abc123/main.py", "print('hello')")
            zf.writestr("owner-repo-abc123/README.md", "# Test")
        zip_buffer.seek(0)

        # Mock response
        mock_response = Mock()
        mock_response.headers = {'content-length': str(len(zip_buffer.getvalue()))}
        mock_response.iter_content = lambda chunk_size: [zip_buffer.getvalue()]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Download and extract
        result = download_and_extract_sources(mock_config, "v1.0.0")

        # Verify extraction
        assert result.exists()
        assert (result / "main.py").exists()
        assert (result / "README.md").exists()

    @patch('launcher.updater.requests.get')
    def test_download_with_progress_callback(self, mock_get, tmp_path, mock_config):
        """Test progress callback is called during download."""
        mock_config.path = str(tmp_path)

        # Create a small zip
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("root/main.py", "print('hello')")
        zip_buffer.seek(0)

        mock_response = Mock()
        mock_response.headers = {'content-length': str(len(zip_buffer.getvalue()))}
        mock_response.iter_content = lambda chunk_size: [zip_buffer.getvalue()]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Track progress calls
        progress_calls = []
        def progress_callback(current, total, message):
            progress_calls.append((current, total, message))

        download_and_extract_sources(mock_config, "v1.0.0", progress_callback=progress_callback)

        # Verify progress was reported
        assert len(progress_calls) > 0

    @patch('launcher.updater.requests.get')
    def test_download_connection_error(self, mock_get, mock_config):
        """Test connection error during download."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(NetworkError, match="Failed to download"):
            download_and_extract_sources(mock_config, "v1.0.0")

    @patch('launcher.updater.requests.get')
    def test_download_invalid_zip(self, mock_get, tmp_path, mock_config):
        """Test error handling for invalid zip file."""
        mock_config.path = str(tmp_path)

        mock_response = Mock()
        mock_response.headers = {'content-length': '100'}
        mock_response.iter_content = lambda chunk_size: [b'not a zip file']
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="Invalid zip"):
            download_and_extract_sources(mock_config, "v1.0.0")
