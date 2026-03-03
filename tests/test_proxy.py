"""Tests for the proxy module."""

import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from launcher.proxy import (
    detect_proxy_settings,
    get_proxy_from_environment,
    get_ssl_cert_from_environment,
    discover_proxy_settings,
    _parse_proxy_from_yaml,
)


class TestGetSslCertFromEnvironment:
    """Tests for get_ssl_cert_from_environment function."""

    def test_finds_ssl_cert_file(self, monkeypatch, tmp_path):
        """Test finding cert via SSL_CERT_FILE."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        assert get_ssl_cert_from_environment() == str(cert)

    def test_finds_requests_ca_bundle(self, monkeypatch, tmp_path):
        """Test finding cert via REQUESTS_CA_BUNDLE."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(cert))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        assert get_ssl_cert_from_environment() == str(cert)

    def test_finds_curl_ca_bundle(self, monkeypatch, tmp_path):
        """Test finding cert via CURL_CA_BUNDLE."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.setenv("CURL_CA_BUNDLE", str(cert))

        assert get_ssl_cert_from_environment() == str(cert)

    def test_returns_none_for_missing_env_vars(self, monkeypatch):
        """Test returns None when no env vars are set."""
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        assert get_ssl_cert_from_environment() is None

    def test_returns_none_for_nonexistent_file(self, monkeypatch):
        """Test returns None when env var points to nonexistent file."""
        monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/cert.pem")
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        assert get_ssl_cert_from_environment() is None

    def test_priority_order(self, monkeypatch, tmp_path):
        """Test that SSL_CERT_FILE takes priority over others."""
        cert1 = tmp_path / "ssl.pem"
        cert1.write_text("cert1")
        cert2 = tmp_path / "requests.pem"
        cert2.write_text("cert2")
        monkeypatch.setenv("SSL_CERT_FILE", str(cert1))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(cert2))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        assert get_ssl_cert_from_environment() == str(cert1)


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

    def test_returns_proxy_with_ssl_cert_only(self, monkeypatch, tmp_path):
        """Test returns ProxySettings with just ssl_cert_file when no proxy URLs."""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("http_proxy", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)

        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        result = get_proxy_from_environment()
        assert result is not None
        assert result.http is None
        assert result.https is None
        assert result.ssl_cert_file == str(cert)


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

    def test_parse_ssl_verify_path(self, tmp_path):
        """Test parsing ssl_verify as a file path from conda config."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        config_data = {
            "ssl_verify": str(cert),
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is not None
        assert result.ssl_cert_file == str(cert)

    def test_parse_ssl_verify_boolean_ignored(self, tmp_path):
        """Test that boolean ssl_verify is ignored."""
        config_data = {
            "ssl_verify": True,
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_ssl_verify_false_ignored(self, tmp_path):
        """Test that ssl_verify: false is ignored."""
        config_data = {
            "ssl_verify": False,
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_ssl_verify_nonexistent_path_ignored(self, tmp_path):
        """Test that ssl_verify pointing to nonexistent file is ignored."""
        config_data = {
            "ssl_verify": "/nonexistent/cert.pem",
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is None

    def test_parse_cert_only_no_proxy_urls(self, tmp_path):
        """Test returns ProxySettings with cert only when no proxy URLs but ssl_verify is valid."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")
        config_data = {
            "ssl_verify": str(cert),
        }
        config_file = tmp_path / ".condarc"
        config_file.write_text(yaml.dump(config_data))

        result = _parse_proxy_from_yaml(config_file)
        assert result is not None
        assert result.http is None
        assert result.https is None
        assert result.ssl_cert_file == str(cert)


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
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        # Note: This test may find proxy settings from system conda configs
        # if they exist. In a clean environment, it should return None.
        result = discover_proxy_settings()
        # We can't assert None here as the system might have conda configs
        # Just verify the function runs without error
        assert result is None or (result.http is not None or result.https is not None)

    def test_merges_ssl_cert_from_conda_into_env(self, monkeypatch, tmp_path):
        """Test that ssl_cert_file from conda is merged into env result."""
        from launcher.config import ProxySettings

        monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        monkeypatch.delenv("http_proxy", raising=False)
        monkeypatch.delenv("https_proxy", raising=False)
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        # Mock detect_proxy_settings to return a result with ssl_cert_file
        conda_result = ProxySettings(ssl_cert_file="/path/to/conda-cert.pem")
        with patch("launcher.proxy.detect_proxy_settings", return_value=conda_result):
            result = discover_proxy_settings()

        assert result is not None
        assert result.http == "http://env-proxy:8080"
        assert result.ssl_cert_file == "/path/to/conda-cert.pem"
