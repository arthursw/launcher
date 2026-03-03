"""Tests for the updater module."""

import io
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from launcher.config import AppConfig, ProxySettings
from launcher.updater import (
    fetch_latest_release,
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



class TestCheckSourcesExist:
    """Tests for check_sources_exist function."""

    def test_sources_exist(self, tmp_path, mock_config):
        """Test when sources directory exists."""
        mock_config.path = str(tmp_path)
        mock_config.version = "v1.0.0"

        # Create the sources directory (app name is sanitized: "TestApp" -> "testapp")
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


class TestFetchLatestRelease:
    """Tests for fetch_latest_release function."""

    @patch('launcher.updater.requests.get')
    def test_fetch_github_latest_release(self, mock_get, mock_config):
        """Test fetching latest release from GitHub API."""
        mock_response = Mock()
        # GitHub /repos/{owner}/{repo}/releases/latest returns a single object
        mock_response.json.return_value = {
            "tag_name": "v2.0.0",
            "name": "Release v2.0.0",
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = fetch_latest_release(mock_config)
        assert result == "v2.0.0"

    @patch('launcher.updater.requests.get')
    def test_fetch_gitlab_releases(self, mock_get):
        """Test fetching releases from GitLab API (list response)."""
        from launcher.config import AppConfig
        mock_config = AppConfig(
            name="TestApp",
            main="main.py",
            path="/tmp/test_apps",
            repository="git@gitlab.com:owner/repo.git"
        )
        mock_response = Mock()
        # GitLab /projects/{id}/releases returns a list of releases sorted by released_at
        mock_response.json.return_value = [
            {"tag_name": "v2.0.0", "name": "Release v2.0.0"},
            {"tag_name": "v1.0.0", "name": "Release v1.0.0"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = fetch_latest_release(mock_config)
        assert result == "v2.0.0"

    @patch('launcher.updater.requests.get')
    def test_fetch_no_release(self, mock_get, mock_config):
        """Test error when no release found (GitHub returns 404)."""
        import requests
        mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")

        with pytest.raises(NetworkError, match="HTTP error"):
            fetch_latest_release(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_connection_error(self, mock_get, mock_config):
        """Test network error handling."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(NetworkError, match="Failed to connect"):
            fetch_latest_release(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_timeout_error(self, mock_get, mock_config):
        """Test timeout error handling."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        with pytest.raises(NetworkError, match="timed out"):
            fetch_latest_release(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_with_proxy(self, mock_get, mock_config):
        """Test fetching with proxy settings."""
        mock_response = Mock()
        mock_response.json.return_value = {"tag_name": "v1.0.0"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        proxy = ProxySettings(http="http://proxy:8080", https="https://proxy:8080")
        result = fetch_latest_release(mock_config, proxy_settings=proxy)

        # Verify proxy was passed to requests
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs['proxies'] == {"http": "http://proxy:8080", "https": "https://proxy:8080"}

    @patch('launcher.updater.requests.get')
    def test_fetch_with_ssl_cert_file(self, mock_get, mock_config):
        """Test fetching passes verify=cert_path when ssl_cert_file is set."""
        mock_response = Mock()
        mock_response.json.return_value = {"tag_name": "v1.0.0"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        proxy = ProxySettings(ssl_cert_file="/path/to/cert.pem")
        fetch_latest_release(mock_config, proxy_settings=proxy)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs['verify'] == "/path/to/cert.pem"

    @patch('launcher.updater.requests.get')
    def test_fetch_without_ssl_cert_uses_true(self, mock_get, mock_config):
        """Test fetching passes verify=True when no cert is set."""
        mock_response = Mock()
        mock_response.json.return_value = {"tag_name": "v1.0.0"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        fetch_latest_release(mock_config)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs['verify'] is True


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
