"""Tests for proxy handling."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from proxy import get_proxy_settings, ProxySettings


class TestProxySettings:
    """Test proxy settings data class."""

    def test_proxy_settings_creation(self):
        """Test creating proxy settings."""
        settings = ProxySettings(http="http://proxy:8080", https="https://proxy:8443")
        assert settings.http == "http://proxy:8080"
        assert settings.https == "https://proxy:8443"

    def test_proxy_settings_optional(self):
        """Test creating proxy settings with optional values."""
        settings = ProxySettings()
        assert settings.http is None
        assert settings.https is None


class TestGetProxySettings:
    """Test get_proxy_settings function."""

    def test_get_proxy_from_config_file(self):
        """Test reading proxy settings from application.yml."""
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
project: testapp
configuration: pyproject.toml
timeout: 3
proxy_servers:
  http: http://proxy.corp.com:8080
  https: https://proxy.corp.com:8443
"""
            config_path.write_text(config_content)

            settings = get_proxy_settings(str(config_path))

            assert settings.http == "http://proxy.corp.com:8080"
            assert settings.https == "https://proxy.corp.com:8443"

    def test_get_proxy_no_proxy_defined(self):
        """Test when no proxy is defined in config."""
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
project: testapp
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            settings = get_proxy_settings(str(config_path))

            assert settings.http is None
            assert settings.https is None

    def test_get_proxy_partial_config(self):
        """Test when only some proxy settings are defined."""
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
project: testapp
configuration: pyproject.toml
timeout: 3
proxy_servers:
  http: http://proxy.corp.com:8080
"""
            config_path.write_text(config_content)

            settings = get_proxy_settings(str(config_path))

            assert settings.http == "http://proxy.corp.com:8080"
            assert settings.https is None

    def test_get_proxy_from_condarc(self):
        """Test reading proxy settings from conda config file."""
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
project: testapp
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            # Create a conda rc file
            condarc_path = Path(tmpdir) / ".condarc"
            condarc_content = """proxy_servers:
  http: http://conda-proxy:8080
  https: https://conda-proxy:8443
"""
            condarc_path.write_text(condarc_content)

            # Patch the conda rc paths to include our test file
            with patch("proxy._get_conda_rc_paths") as mock_paths:
                mock_paths.return_value = [str(condarc_path)]
                settings = get_proxy_settings(str(config_path))

                # Should get proxy from condarc since config doesn't have it
                assert settings.http == "http://conda-proxy:8080"
                assert settings.https == "https://conda-proxy:8443"

    def test_get_proxy_invalid_config(self):
        """Test handling of invalid YAML in proxy config - returns empty settings gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
invalid yaml: [
"""
            config_path.write_text(config_content)

            # get_proxy_settings should handle invalid YAML gracefully
            # and return empty ProxySettings instead of raising
            settings = get_proxy_settings(str(config_path))
            assert settings.http is None
            assert settings.https is None

    def test_update_proxy_in_config(self):
        """Test updating proxy settings in application.yml."""
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
project: testapp
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            from proxy import update_proxy_in_config

            new_settings = ProxySettings(
                http="http://new-proxy:8080", https="https://new-proxy:8443"
            )
            update_proxy_in_config(str(config_path), new_settings)

            # Verify settings were saved
            settings = get_proxy_settings(str(config_path))
            assert settings.http == "http://new-proxy:8080"
            assert settings.https == "https://new-proxy:8443"
