"""Tests for the config module."""

import pytest
from pathlib import Path
import tempfile
import yaml

from launcher.config import AppConfig, ProxySettings, load_config


class TestProxySettings:
    """Tests for ProxySettings dataclass."""

    def test_empty_proxy(self):
        """Test empty proxy settings."""
        proxy = ProxySettings()
        assert proxy.http is None
        assert proxy.https is None
        assert proxy.to_dict() == {}

    def test_http_only_proxy(self):
        """Test HTTP-only proxy settings."""
        proxy = ProxySettings(http="http://proxy:8080")
        assert proxy.http == "http://proxy:8080"
        assert proxy.https is None
        assert proxy.to_dict() == {"http": "http://proxy:8080"}

    def test_full_proxy(self):
        """Test full proxy settings."""
        proxy = ProxySettings(
            http="http://proxy:8080",
            https="https://proxy:8080"
        )
        assert proxy.to_dict() == {
            "http": "http://proxy:8080",
            "https": "https://proxy:8080"
        }

    def test_verify_returns_true_by_default(self):
        """Test that verify returns True when no ssl_cert_file is set."""
        proxy = ProxySettings()
        assert proxy.verify is True

    def test_verify_returns_cert_path_when_set(self):
        """Test that verify returns the cert path when ssl_cert_file is set."""
        proxy = ProxySettings(ssl_cert_file="/path/to/cert.pem")
        assert proxy.verify == "/path/to/cert.pem"

    def test_to_dict_excludes_ssl_cert_file(self):
        """Test that to_dict() does not include ssl_cert_file."""
        proxy = ProxySettings(
            http="http://proxy:8080",
            ssl_cert_file="/path/to/cert.pem"
        )
        result = proxy.to_dict()
        assert "ssl_cert_file" not in result
        assert result == {"http": "http://proxy:8080"}

    def test_validate_ssl_cert_file_existing_pem(self, tmp_path):
        """Test validation passes for existing .pem file."""
        cert = tmp_path / "ca.pem"
        cert.write_text("cert content")
        proxy = ProxySettings(ssl_cert_file=str(cert))
        assert proxy.validate_ssl_cert_file() is True

    def test_validate_ssl_cert_file_existing_crt(self, tmp_path):
        """Test validation passes for existing .crt file."""
        cert = tmp_path / "ca.crt"
        cert.write_text("cert content")
        proxy = ProxySettings(ssl_cert_file=str(cert))
        assert proxy.validate_ssl_cert_file() is True

    def test_validate_ssl_cert_file_existing_cer(self, tmp_path):
        """Test validation passes for existing .cer file."""
        cert = tmp_path / "ca.cer"
        cert.write_text("cert content")
        proxy = ProxySettings(ssl_cert_file=str(cert))
        assert proxy.validate_ssl_cert_file() is True

    def test_validate_ssl_cert_file_missing_file(self):
        """Test validation fails for missing file."""
        proxy = ProxySettings(ssl_cert_file="/nonexistent/cert.pem")
        with pytest.raises(FileNotFoundError, match="SSL certificate file not found"):
            proxy.validate_ssl_cert_file()

    def test_validate_ssl_cert_file_bad_extension(self, tmp_path):
        """Test validation fails for unrecognised extension."""
        cert = tmp_path / "ca.txt"
        cert.write_text("cert content")
        proxy = ProxySettings(ssl_cert_file=str(cert))
        with pytest.raises(ValueError, match="Unrecognised certificate extension"):
            proxy.validate_ssl_cert_file()

    def test_validate_ssl_cert_file_none(self):
        """Test validation passes when ssl_cert_file is None."""
        proxy = ProxySettings()
        assert proxy.validate_ssl_cert_file() is True


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_minimal_config_with_repository(self):
        """Test minimal config with repository URL."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            repository="git@github.com:owner/repo.git"
        )
        assert config.name == "TestApp"
        assert config.main == "main.py"
        assert config.auto_update is True
        assert config.configuration == "pyproject.toml"

    def test_minimal_config_with_endpoints(self):
        """Test minimal config with explicit endpoints."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            api="https://api.example.com",
            releases_endpoint="/releases",
            archive_endpoint="/archive/{ref}"
        )
        assert config.api == "https://api.example.com"
        assert config.releases_endpoint == "/releases"

    def test_config_validation_fails_without_repository_or_endpoints(self):
        """Test that config validation fails without repository or endpoints."""
        with pytest.raises(ValueError, match="Either 'repository' or all of"):
            AppConfig(
                name="TestApp",
                main="main.py",
                path="."
            )

    def test_env_name_sanitization(self):
        """Test environment name sanitization."""
        config = AppConfig(
            name="My App! 123",
            main="main.py",
            path=".",
            repository="git@github.com:owner/repo.git"
        )
        assert config.env_name == "My_App__123"

    def test_sources_path(self):
        """Test sources path generation."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0"
        )
        assert config.sources_path == Path("/tmp/apps/testapp-v1.0.0")

    def test_main_script_path(self):
        """Test main script path generation."""
        config = AppConfig(
            name="TestApp",
            main="src/main.py",
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0"
        )
        assert config.main_script_path == Path("/tmp/apps/testapp-v1.0.0/src/main.py")


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_minimal_config(self, tmp_path):
        """Test loading a minimal config file."""
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": ".",
            "repository": "git@github.com:owner/repo.git"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config.name == "TestApp"
        assert config.main == "main.py"
        assert config.repository == "git@github.com:owner/repo.git"

    def test_load_full_config(self, tmp_path):
        """Test loading a full config file."""
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": "/tmp/apps",
            "repository": "git@github.com:owner/repo.git",
            "auto_update": False,
            "version": "testapp-v1.0.0",
            "configuration": "requirements.txt",
            "install": "install.py",
            "gui_timeout": 5,
            "init_message": "Ready",
            "init_timeout": 60,
            "proxy_servers": {
                "http": "http://proxy:8080",
                "https": "https://proxy:8080"
            }
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config.name == "TestApp"
        assert config.auto_update is False
        assert config.version == "testapp-v1.0.0"
        assert config.configuration == "requirements.txt"
        assert config.install == "install.py"
        assert config.gui_timeout == 5
        assert config.init_message == "Ready"
        assert config.init_timeout == 60
        assert config.proxy_servers.http == "http://proxy:8080"
        assert config.proxy_servers.https == "https://proxy:8080"

    def test_load_config_file_not_found(self):
        """Test that FileNotFoundError is raised for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/path/config.yml"))

    def test_load_config_missing_required_field(self, tmp_path):
        """Test that ValueError is raised for missing required fields."""
        config_data = {
            "name": "TestApp",
            # missing "main" and "path"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="Required field 'main'"):
            load_config(config_file)

    def test_load_empty_config(self, tmp_path):
        """Test that ValueError is raised for empty config."""
        config_file = tmp_path / "application.yml"
        config_file.write_text("")

        with pytest.raises(ValueError, match="empty"):
            load_config(config_file)

    def test_load_config_with_ssl_cert_file(self, tmp_path):
        """Test loading config with ssl_cert_file in proxy_servers."""
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "proxy_servers": {
                "http": "http://proxy:8080",
                "ssl_cert_file": "/path/to/cert.pem",
            }
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config.proxy_servers.http == "http://proxy:8080"
        assert config.proxy_servers.ssl_cert_file == "/path/to/cert.pem"

    def test_config_save(self, tmp_path):
        """Test saving config back to file."""
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": ".",
            "repository": "git@github.com:owner/repo.git"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        config.version = "testapp-v2.0.0"
        config.save()

        # Reload and verify
        reloaded = load_config(config_file)
        assert reloaded.version == "testapp-v2.0.0"

    def test_config_save_roundtrip_ssl_cert_file(self, tmp_path):
        """Test save + load roundtrip preserves ssl_cert_file."""
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        config.proxy_servers = ProxySettings(
            http="http://proxy:8080",
            ssl_cert_file="/path/to/cert.pem",
        )
        config.save()

        reloaded = load_config(config_file)
        assert reloaded.proxy_servers.http == "http://proxy:8080"
        assert reloaded.proxy_servers.ssl_cert_file == "/path/to/cert.pem"
