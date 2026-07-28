"""Tests for the config module."""

import pytest
from pathlib import Path
import yaml

from launcher.config import AppConfig, EntryPointConfig, ProxySettings, TrustConfig, load_config


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
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            repository="git@github.com:owner/repo.git"
        )
        assert config.name == "TestApp"
        assert config.entrypoint.mode == "script"
        assert config.entrypoint.script == "main.py"
        assert config.path == "."
        assert config.ask_install_location is True
        assert config.auto_update is True
        assert config.configuration == "pyproject.toml"
        assert config.extras == []
        assert config.reinstall_on_update is False  # Default value

    def test_minimal_config_with_endpoints(self):
        """Explicit release discovery endpoints should not require an archive endpoint."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=".",
            api="https://api.example.com",
            releases_endpoint="/releases",
        )
        assert config.api == "https://api.example.com"
        assert config.releases_endpoint == "/releases"
        assert config.archive_endpoint is None

    def test_config_validation_fails_without_repository_or_endpoints(self):
        """Test that config validation fails without repository or endpoints."""
        with pytest.raises(ValueError, match="Either 'repository' or both 'api' and 'releases_endpoint'"):
            AppConfig(
                name="TestApp",
                entrypoint=EntryPointConfig(mode="script", script="main.py"),
            )

    def test_env_name_sanitization(self):
        """Test environment name sanitization."""
        config = AppConfig(
            name="My App! 123",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=".",
            repository="git@github.com:owner/repo.git"
        )
        assert config.env_name == "My_App__123"

    def test_sources_path(self):
        """Test sources path generation."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0"
        )
        assert config.sources_path == Path("/tmp/apps").resolve() / "sources" / "testapp-v1.0.0"

    def test_script_path(self):
        """Test script path generation."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="src/main.py"),
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0"
        )
        assert config.script_path == Path("/tmp/apps").resolve() / "sources" / "testapp-v1.0.0" / "src" / "main.py"

    def test_config_file_path_is_none_when_configuration_disabled(self):
        """configuration: null explicitly disables dependency config loading."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration=None,
        )

        assert config.config_file_path is None

    def test_infers_working_directory_from_configuration(self):
        """Monorepo projects should launch from the dependency config directory."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="backend/src/test_app/desktop.py"),
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="backend/pyproject.toml",
        )

        assert config.working_directory_path == Path("/tmp/apps").resolve() / "sources" / "testapp-v1.0.0" / "backend"

    def test_infers_pythonpath_from_working_directory_src(self, tmp_path):
        """A src-layout project should make src and project root importable."""
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        (sources / "backend" / "src").mkdir(parents=True)
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="backend/src/test_app/desktop.py"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="backend/pyproject.toml",
        )

        assert config.pythonpath_paths == [
            sources / "backend" / "src",
            sources / "backend",
        ]

    def test_explicit_working_directory_and_pythonpath(self, tmp_path):
        """Explicit launch paths override inferred defaults."""
        sources = tmp_path / "apps" / "sources" / "testapp-v1.0.0"
        sources.mkdir(parents=True)
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="scripts/desktop.py"),
            path=str(tmp_path / "apps"),
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
            configuration="pyproject.toml",
            working_directory="runtime",
            pythonpath=["lib", "plugins"],
        )

        assert config.working_directory_path == sources / "runtime"
        assert config.pythonpath_paths == [sources / "lib", sources / "plugins"]

    def test_sources_path_sanitizes_version(self):
        """Release tags should not create nested paths."""
        config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path="/tmp/apps",
            repository="git@github.com:owner/repo.git",
            version="release/v1.0.0",
        )
        assert config.sources_path == Path("/tmp/apps").resolve() / "sources" / "testapp-release_v1.0.0"

    def test_relative_sources_path_uses_app_data_dir(self, tmp_path, monkeypatch):
        """Relative source roots should not depend on the process working directory."""
        monkeypatch.setattr(
            "launcher.config.get_default_install_dir",
            lambda _name: tmp_path / "app-data" / "Test_App",
        )
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        config = AppConfig(
            name="Test App",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path=".",
            repository="git@github.com:owner/repo.git",
            version="v1.0.0",
        )
        assert config.sources_path == tmp_path / "app-data" / "Test_App" / "sources" / "testapp-v1.0.0"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_minimal_config(self, tmp_path):
        """Test loading a minimal config file."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "repository": "git@github.com:owner/repo.git"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config.name == "TestApp"
        assert config.entrypoint.mode == "script"
        assert config.entrypoint.script == "main.py"
        assert config.path == "."
        assert config.repository == "git@github.com:owner/repo.git"
        assert config.configuration == "pyproject.toml"

    def test_load_config_allows_null_path(self, tmp_path):
        """path: null uses the portable per-app runtime data default."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": None,
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.path == "."

    def test_load_config_allows_null_configuration(self, tmp_path):
        """configuration: null is the explicit no-dependency-file setting."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "configuration": None,
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.configuration is None
        assert config.config_file_path is None

    def test_load_full_config(self, tmp_path):
        """Test loading a full config file."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {
                "mode": "project",
                "command": "test-app-gui",
                "project_directory": "backend",
                "args": ["--desktop"],
            },
            "path": "/tmp/apps",
            "repository": "git@github.com:owner/repo.git",
            "auto_update": False,
            "version": "testapp-v1.0.0",
            "configuration": "requirements.txt",
            "extras": ["desktop"],
            "working_directory": "backend",
            "pythonpath": ["backend/src"],
            "install": "install.py",
            "reinstall_on_update": True,
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
        assert config.entrypoint.mode == "project"
        assert config.entrypoint.command == "test-app-gui"
        assert config.entrypoint.project_directory == "backend"
        assert config.entrypoint.args == ["--desktop"]
        assert config.auto_update is False
        assert config.version == "testapp-v1.0.0"
        assert config.configuration == "requirements.txt"
        assert config.extras == ["desktop"]
        assert config.working_directory == "backend"
        assert config.pythonpath == ["backend/src"]
        assert config.install == "install.py"
        assert config.reinstall_on_update is True
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
            # missing "entrypoint"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="Required field 'entrypoint'"):
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
            "entrypoint": {"mode": "script", "script": "main.py"},
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

    def test_load_config_with_signed_manifest_trust(self, tmp_path):
        """Trust config is parsed and validated."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "trust": {
                "mode": "signed_manifest",
                "public_key": "abc",
                "manifest_url": "https://example.com/{version}/launcher-manifest.yml",
                "signature_url": "https://example.com/{version}/launcher-manifest.yml.sig",
                "archive_url": "https://example.com/{version}/{archive_name}",
            },
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert isinstance(config.trust, TrustConfig)
        assert config.trust.mode == "signed_manifest"
        assert config.trust.archive_url == "https://example.com/{version}/{archive_name}"

    def test_load_config_infers_missing_trust_urls_from_repository(self, tmp_path):
        """Repository-backed trust config should not require repeated release asset URLs."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "trust": {
                "mode": "signed_manifest",
                "public_key": "abc",
            },
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.trust is not None
        assert config.trust.manifest_url == "https://github.com/owner/repo/releases/download/{version}/launcher-manifest.yml"
        assert config.trust.signature_url == "https://github.com/owner/repo/releases/download/{version}/launcher-manifest.yml.sig"
        assert config.trust.archive_url == "https://github.com/owner/repo/releases/download/{version}/{archive_name}"

    def test_load_config_rejects_missing_trust_urls_without_repository(self, tmp_path):
        """Custom API configs need explicit signed release asset URLs."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "api": "https://updates.example.com",
            "releases_endpoint": "/releases/latest",
            "trust": {
                "mode": "signed_manifest",
                "public_key": "abc",
            },
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="trust.manifest_url, trust.signature_url, trust.archive_url"):
            load_config(config_file)

    def test_load_config_rejects_missing_entrypoint_mode(self, tmp_path):
        """Missing nested entrypoint fields should identify the missing YAML key."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"script": "main.py"},
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="entrypoint.mode is required"):
            load_config(config_file)

    def test_load_config_rejects_non_list_extras(self, tmp_path):
        """Dependency extras must be listed explicitly."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "extras": "desktop",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="'extras' must be a list of strings"):
            load_config(config_file)

    def test_load_config_rejects_non_list_pythonpath(self, tmp_path):
        """Python import path entries must be listed explicitly."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
            "pythonpath": "src",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match="'pythonpath' must be a list of strings"):
            load_config(config_file)

    def test_load_config_accepts_module_entrypoint(self, tmp_path):
        """Module entrypoints run a package with python -m semantics."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {
                "mode": "module",
                "module": "test_app",
                "args": ["--desktop", "--port", "8765"],
            },
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.entrypoint.mode == "module"
        assert config.entrypoint.module == "test_app"
        assert config.entrypoint.args == ["--desktop", "--port", "8765"]

    @pytest.mark.parametrize(
        ("entrypoint", "message"),
        [
            ({"mode": "unknown", "script": "main.py"}, "entrypoint.mode"),
            ({"mode": "script"}, "entrypoint.script is required"),
            ({"mode": "module"}, "entrypoint.module is required"),
            ({"mode": "project"}, "entrypoint.command is required"),
            (
                {"mode": "script", "script": "main.py", "module": "test_app"},
                "script entrypoints can only define",
            ),
            (
                {"mode": "module", "module": "test_app", "command": "test-app"},
                "module entrypoints can only define",
            ),
            ({"mode": "script", "script": "main.py", "args": "--debug"}, "entrypoint.args"),
        ],
    )
    def test_load_config_rejects_invalid_entrypoint(self, tmp_path, entrypoint, message):
        """Entrypoint validation should fail before build or run."""
        config_data = {
            "name": "TestApp",
            "entrypoint": entrypoint,
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ValueError, match=message):
            load_config(config_file)

    def test_config_save(self, tmp_path):
        """Test saving config back to file."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git"
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        config.version = "testapp-v2.0.0"
        config.extras = ["desktop"]
        config.working_directory = "backend"
        config.pythonpath = ["backend/src"]
        config.save()

        # Reload and verify
        reloaded = load_config(config_file)
        assert reloaded.version == "testapp-v2.0.0"
        assert reloaded.extras == ["desktop"]
        assert reloaded.working_directory == "backend"
        assert reloaded.pythonpath == ["backend/src"]

    def test_config_save_roundtrip_ssl_cert_file(self, tmp_path):
        """Test save + load roundtrip preserves ssl_cert_file."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
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

    def test_config_save_roundtrip_reinstall_on_update(self, tmp_path):
        """Test save + load roundtrip preserves reinstall_on_update."""
        config_data = {
            "name": "TestApp",
            "entrypoint": {"mode": "script", "script": "main.py"},
            "path": ".",
            "repository": "git@github.com:owner/repo.git",
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        config.reinstall_on_update = True
        config.save()

        reloaded = load_config(config_file)
        assert reloaded.reinstall_on_update is True

    def test_config_save_roundtrip_ask_install_location(self, tmp_path):
        """The developer can disable only the first-run location chooser."""
        config_file = tmp_path / "application.yml"
        config_file.write_text(
            yaml.dump(
                {
                    "name": "TestApp",
                    "entrypoint": {"mode": "script", "script": "main.py"},
                    "repository": "git@github.com:owner/repo.git",
                    "ask_install_location": False,
                }
            )
        )

        config = load_config(config_file)
        config.save()

        assert load_config(config_file).ask_install_location is False
