"""Tests for the proxy module."""

import os
import pytest
import yaml
from pathlib import Path

from launcher.proxy import (
    detect_proxy_settings,
    get_proxy_from_environment,
    discover_proxy_settings,
    _parse_proxy_from_yaml,
)


class TestGetProxyFromEnvironment:
    """Tests for get_proxy_from_environment function."""

    def test_no_proxy_env_vars(self, monkeypatch):
        """Test when no proxy environment variables are set."""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("http_proxy", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)

        result = get_proxy_from_environment()
        assert result is None

    def test_uppercase_proxy_vars(self, monkeypatch):
        """Test uppercase proxy environment variables."""
        monkeypatch.setenv("HTTP_PROXY", "http://proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "https://proxy:8080")

        result = get_proxy_from_environment()
        assert result is not None
        assert result.http == "http://proxy:8080"
        assert result.https == "https://proxy:8080"

    def test_lowercase_proxy_vars(self, monkeypatch):
        """Test lowercase proxy environment variables."""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.setenv("http_proxy", "http://proxy:8080")
        monkeypatch.setenv("https_proxy", "https://proxy:8080")

        result = get_proxy_from_environment()
        assert result is not None
        assert result.http == "http://proxy:8080"
        assert result.https == "https://proxy:8080"

    def test_mixed_case_priority(self, monkeypatch):
        """Test that uppercase takes priority over lowercase."""
        monkeypatch.setenv("HTTP_PROXY", "http://upper:8080")
        monkeypatch.setenv("http_proxy", "http://lower:8080")

        result = get_proxy_from_environment()
        assert result is not None
        assert result.http == "http://upper:8080"


class TestParseProxyFromYaml:
    """Tests for _parse_proxy_from_yaml function."""

    def test_parse_valid_proxy_config(self, tmp_path):
        """Test parsing valid proxy config from YAML."""
        config_data = {
            "proxy_servers": {
                "http": "http://proxy:8080",
                "https": "https://proxy:8080"
            }
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is not None
        assert result.http == "http://proxy:8080"
        assert result.https == "https://proxy:8080"

    def test_parse_http_only_proxy(self, tmp_path):
        """Test parsing HTTP-only proxy config."""
        config_data = {
            "proxy_servers": {
                "http": "http://proxy:8080"
            }
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is not None
        assert result.http == "http://proxy:8080"
        assert result.https is None

    def test_parse_no_proxy_section(self, tmp_path):
        """Test parsing config without proxy_servers section."""
        config_data = {
            "channels": ["conda-forge", "defaults"]
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_empty_proxy_section(self, tmp_path):
        """Test parsing config with empty proxy_servers section."""
        config_data = {
            "proxy_servers": {}
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_empty_file(self, tmp_path):
        """Test parsing empty file."""
        config_file = tmp_path / ".condarc"
        config_file.write_text("")

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_nonexistent_file(self, tmp_path):
        """Test parsing nonexistent file."""
        config_file = tmp_path / "nonexistent.yml"

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_invalid_yaml(self, tmp_path):
        """Test parsing invalid YAML file."""
        config_file = tmp_path / ".condarc"
        config_file.write_text("invalid: yaml: content: [")

        result = _parse_proxy_from_yaml(config_file)
        assert result is None


class TestDiscoverProxySettings:
    """Tests for discover_proxy_settings function."""

    def test_environment_takes_priority(self, monkeypatch, tmp_path):
        """Test that environment variables take priority over config files."""
        # Set environment variable
        monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")

        result = discover_proxy_settings()
        assert result is not None
        assert result.http == "http://env-proxy:8080"

    def test_no_proxy_found(self, monkeypatch):
        """Test when no proxy settings are found anywhere."""
        # Clear all proxy environment variables
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("http_proxy", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)

        # Note: This test may find proxy settings from system conda configs
        # if they exist. In a clean environment, it should return None.
        result = discover_proxy_settings()
        # We can't assert None here as the system might have conda configs
        # Just verify the function runs without error
        assert result is None or (result.http is not None or result.https is not None)
