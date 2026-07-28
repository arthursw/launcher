"""Tests for the updater module."""

import io
import base64
import hashlib
import stat
import zipfile
import pytest
from unittest.mock import Mock, patch
import yaml

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from launcher.config import AppConfig, EntryPointConfig, ProxySettings, TrustConfig
from launcher.updater import (
    fetch_latest_release,
    fetch_signed_manifest,
    parse_manifest,
    check_sources_exist,
    download_and_extract_sources,
    update_sources,
    HTTPStatusError,
    NetworkError,
    DownloadError,
    UpdaterError,
)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return AppConfig(
        name="TestApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path="/tmp/test_apps",
        repository="git@github.com:owner/repo.git"
    )


@pytest.fixture
def signed_config(mock_config):
    """Create a config with a real Ed25519 trust key."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    mock_config.trust = TrustConfig(
        mode="signed_manifest",
        public_key=base64.b64encode(public_key).decode("ascii"),
        manifest_url="https://example.com/{version}/launcher-manifest.yml",
        signature_url="https://example.com/{version}/launcher-manifest.yml.sig",
        archive_url="https://example.com/{version}/{archive_name}",
    )
    return mock_config, private_key


def _zip_bytes(files: dict[str, str]) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_buffer.getvalue()


def _archive_url(version: str = "v1.0.0") -> str:
    return f"https://downloads.example.com/{version}/testapp-{version}.zip"


def _manifest_bytes(app: str, version: str, archive_bytes: bytes) -> bytes:
    return yaml.safe_dump(
        {
            "schema_version": 2,
            "application": app,
            "version": version,
            "archive": {
                "name": f"testapp-{version}.zip",
                "url": _archive_url(version),
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            },
        },
        sort_keys=False,
    ).encode("utf-8")



class TestCheckSourcesExist:
    """Tests for check_sources_exist function."""

    def test_sources_exist(self, tmp_path, mock_config):
        """Test when sources directory exists."""
        mock_config.path = str(tmp_path)
        mock_config.version = "v1.0.0"

        # Create the sources directory (app name is sanitized: "TestApp" -> "testapp")
        sources_dir = tmp_path / "sources" / "testapp-v1.0.0"
        sources_dir.mkdir(parents=True)

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
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
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
    def test_fetch_gitlab_empty_releases(self, mock_get):
        """An empty GitLab release list should explain that no releases exist."""
        from launcher.config import AppConfig
        mock_config = AppConfig(
            name="TestApp",
            entrypoint=EntryPointConfig(mode="script", script="main.py"),
            path="/tmp/test_apps",
            repository="git@gitlab.com:owner/repo.git"
        )
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(UpdaterError, match="No releases found"):
            fetch_latest_release(mock_config)

    @patch('launcher.updater.requests.get')
    def test_fetch_no_release(self, mock_get, mock_config):
        """Test error when no release found (GitHub returns 404)."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found",
            response=mock_response,
        )
        mock_get.return_value = mock_response

        with pytest.raises(HTTPStatusError, match="repository path or GitLab project id"):
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
        fetch_latest_release(mock_config, proxy_settings=proxy)

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
        result = download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

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

        download_and_extract_sources(mock_config, "v1.0.0", progress_callback=progress_callback, archive_url=_archive_url())

        # Verify progress was reported
        assert len(progress_calls) > 0

    @patch('launcher.updater.requests.get')
    def test_download_connection_error(self, mock_get, mock_config):
        """Test connection error during download."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(NetworkError, match="Failed to download"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

    @patch('launcher.updater.requests.get')
    def test_reject_archive_sha_mismatch(self, mock_get, tmp_path, mock_config):
        """Archives must match the signed manifest hash before extraction."""
        mock_config.path = str(tmp_path)
        archive = _zip_bytes({"root/main.py": "print('hello')"})
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="SHA-256"):
            download_and_extract_sources(
                mock_config,
                "v1.0.0",
                expected_sha256="0" * 64,
                archive_url=_archive_url(),
            )

        assert not (tmp_path / "sources" / "testapp-v1.0.0").exists()

    @pytest.mark.parametrize(
        "name",
        [
            "../evil.py",
            "/tmp/evil.py",
            "C:/tmp/evil.py",
            "root/../../evil.py",
            "root\\evil.py",
        ],
    )
    @patch('launcher.updater.requests.get')
    def test_reject_unsafe_zip_paths(self, mock_get, tmp_path, mock_config, name):
        """Unsafe archive paths must not be extracted."""
        mock_config.path = str(tmp_path)
        archive = _zip_bytes({name: "evil"})
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        assert not (tmp_path / "evil.py").exists()
        assert not (tmp_path / "sources" / "testapp-v1.0.0").exists()

    @patch('launcher.updater.requests.get')
    def test_extract_zip_internal_symlink(self, mock_get, tmp_path, mock_config):
        """Internal symlink members should be preserved when they stay in the app tree."""
        mock_config.path = str(tmp_path)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("root/target.txt", "target")
            info = zipfile.ZipInfo("root/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target.txt")
        archive = zip_buffer.getvalue()
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        link = result / "link"
        assert link.is_symlink()
        assert link.readlink().as_posix() == "target.txt"
        assert link.read_text() == "target"

    @patch('launcher.updater.requests.get')
    def test_extract_zip_internal_symlink_from_subdirectory(self, mock_get, tmp_path, mock_config):
        """Relative symlink targets may point elsewhere inside the app tree."""
        mock_config.path = str(tmp_path)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("root/target.txt", "target")
            info = zipfile.ZipInfo("root/pkg/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "../target.txt")
        archive = zip_buffer.getvalue()
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        link = result / "pkg" / "link"
        assert link.is_symlink()
        assert link.readlink().as_posix() == "../target.txt"
        assert link.read_text() == "target"

    @pytest.mark.parametrize("target", ["../outside", "/tmp/outside", "C:/tmp/outside", "dir\\outside"])
    @patch('launcher.updater.requests.get')
    def test_reject_unsafe_zip_symlink_target(self, mock_get, tmp_path, mock_config, target):
        """Symlink targets must not escape the extracted app tree."""
        mock_config.path = str(tmp_path)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            info = zipfile.ZipInfo("root/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
        archive = zip_buffer.getvalue()
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="unsafe symlink"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        assert not (tmp_path / "sources" / "testapp-v1.0.0").exists()

    @pytest.mark.parametrize("target", ["missing.txt", "b"])
    @patch('launcher.updater.requests.get')
    def test_reject_unresolvable_zip_symlink_target(self, mock_get, tmp_path, mock_config, target):
        """Symlink targets must resolve to a real non-cyclic archive member."""
        mock_config.path = str(tmp_path)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            info = zipfile.ZipInfo("root/a")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
            if target == "b":
                other = zipfile.ZipInfo("root/b")
                other.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(other, "a")
        archive = zip_buffer.getvalue()
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="symlink"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        assert not (tmp_path / "sources" / "testapp-v1.0.0").exists()

    @patch('launcher.updater.requests.get')
    def test_reject_zip_symlink_with_child_entries(self, mock_get, tmp_path, mock_config):
        """A symlink path must not also be used as a directory prefix."""
        mock_config.path = str(tmp_path)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("root/target", "target")
            info = zipfile.ZipInfo("root/pkg")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target")
            zf.writestr("root/pkg/main.py", "print('bad')")
        archive = zip_buffer.getvalue()
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="symlink"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        assert not (tmp_path / "sources" / "testapp-v1.0.0").exists()

    @patch('launcher.updater.requests.get')
    def test_existing_target_is_not_overwritten(self, mock_get, tmp_path, mock_config):
        """Extraction never overwrites an existing source directory."""
        mock_config.path = str(tmp_path)
        existing = tmp_path / "sources" / "testapp-v1.0.0"
        existing.mkdir(parents=True)
        (existing / "main.py").write_text("old")
        archive = _zip_bytes({"root/main.py": "new"})
        mock_response = Mock()
        mock_response.headers = {"content-length": str(len(archive))}
        mock_response.iter_content = lambda chunk_size: [archive]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with pytest.raises(DownloadError, match="already exist"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

        assert (existing / "main.py").read_text() == "old"

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
            download_and_extract_sources(mock_config, "v1.0.0", archive_url=_archive_url())

    def test_download_requires_archive_url(self, tmp_path, mock_config):
        """Provider archive endpoints are not used for signed-manifest downloads."""
        mock_config.path = str(tmp_path)

        with pytest.raises(DownloadError, match="Archive URL is required"):
            download_and_extract_sources(mock_config, "v1.0.0")

    def test_download_invalid_archive_url_is_launcher_error(self, tmp_path, mock_config):
        """Malformed archive URLs should not escape requests exceptions to callers."""
        mock_config.path = str(tmp_path)

        with pytest.raises(NetworkError, match="Failed to download"):
            download_and_extract_sources(mock_config, "v1.0.0", archive_url="not-a-url")


class TestSignedManifest:
    """Tests for signed manifest verification."""

    @patch("launcher.updater.requests.get")
    def test_fetch_signed_manifest_accepts_valid_signature(self, mock_get, signed_config):
        config, private_key = signed_config
        archive = b"archive"
        manifest = _manifest_bytes("TestApp", "v1.0.0", archive)
        signature = private_key.sign(manifest)
        responses = []
        for content in (manifest, signature):
            response = Mock()
            response.content = content
            response.raise_for_status = Mock()
            responses.append(response)
        mock_get.side_effect = responses

        result = fetch_signed_manifest(config, "v1.0.0")

        assert result.schema_version == 2
        assert result.archive_name == "testapp-v1.0.0.zip"
        assert result.archive_url == "https://downloads.example.com/v1.0.0/testapp-v1.0.0.zip"
        assert result.archive_sha256 == hashlib.sha256(archive).hexdigest()
        assert mock_get.call_args_list[0].args[0] == "https://example.com/v1.0.0/launcher-manifest.yml"
        assert mock_get.call_args_list[1].args[0] == "https://example.com/v1.0.0/launcher-manifest.yml.sig"

    def test_parse_manifest_rejects_schema_v1(self):
        manifest = yaml.safe_dump(
            {
                "schema_version": 1,
                "application": "TestApp",
                "version": "v1.0.0",
                "archive": {"sha256": "0" * 64},
            }
        ).encode("utf-8")

        with pytest.raises(UpdaterError, match="schema_version must be 2"):
            parse_manifest(manifest, "TestApp", "v1.0.0")

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            (["not", "a", "mapping"], "Manifest must be a mapping"),
            (
                {
                    "schema_version": 2,
                    "application": "TestApp",
                    "version": "v1.0.0",
                    "archive": "not-a-mapping",
                },
                "Manifest archive must be a mapping",
            ),
        ],
    )
    def test_parse_manifest_rejects_non_mapping_data(self, payload, message):
        manifest = yaml.safe_dump(payload).encode("utf-8")

        with pytest.raises(UpdaterError, match=message):
            parse_manifest(manifest, "TestApp", "v1.0.0")

    def test_parse_manifest_rejects_invalid_archive_url(self):
        manifest = yaml.safe_dump(
            {
                "schema_version": 2,
                "application": "TestApp",
                "version": "v1.0.0",
                "archive": {
                    "name": "testapp-v1.0.0.zip",
                    "url": "not-a-url",
                    "sha256": "0" * 64,
                },
            }
        ).encode("utf-8")

        with pytest.raises(UpdaterError, match=r"absolute http\(s\) URL"):
            parse_manifest(manifest, "TestApp", "v1.0.0")

    @patch("launcher.updater.requests.get")
    def test_fetch_signed_manifest_rejects_bad_signature(self, mock_get, signed_config):
        config, _private_key = signed_config
        manifest = _manifest_bytes("TestApp", "v1.0.0", b"archive")
        responses = []
        for content in (manifest, b"bad-signature"):
            response = Mock()
            response.content = content
            response.raise_for_status = Mock()
            responses.append(response)
        mock_get.side_effect = responses

        with pytest.raises(UpdaterError, match="signature"):
            fetch_signed_manifest(config, "v1.0.0")

    @patch("launcher.updater.requests.get")
    def test_fetch_signed_manifest_rejects_app_mismatch(self, mock_get, signed_config):
        config, private_key = signed_config
        manifest = _manifest_bytes("OtherApp", "v1.0.0", b"archive")
        signature = private_key.sign(manifest)
        responses = []
        for content in (manifest, signature):
            response = Mock()
            response.content = content
            response.raise_for_status = Mock()
            responses.append(response)
        mock_get.side_effect = responses

        with pytest.raises(UpdaterError, match="application"):
            fetch_signed_manifest(config, "v1.0.0")

    @patch("launcher.updater.requests.get")
    def test_fixed_version_downloads_manifest_archive_url(self, mock_get, tmp_path, signed_config):
        """Fixed-version updates should download the app archive URL named in the manifest."""
        config, private_key = signed_config
        config.path = str(tmp_path)
        config.auto_update = False
        config.version = "v1.0.0"
        archive = _zip_bytes({"root/main.py": "print('hello')"})
        manifest = _manifest_bytes("TestApp", "v1.0.0", archive)
        signature = private_key.sign(manifest)

        manifest_response = Mock(content=manifest)
        manifest_response.raise_for_status = Mock()
        signature_response = Mock(content=signature)
        signature_response.raise_for_status = Mock()
        archive_response = Mock()
        archive_response.headers = {"content-length": str(len(archive))}
        archive_response.iter_content = lambda chunk_size: [archive]
        archive_response.raise_for_status = Mock()
        mock_get.side_effect = [manifest_response, signature_response, archive_response]

        updated, version = update_sources(config)

        assert updated is True
        assert version == "v1.0.0"
        assert (tmp_path / "sources" / "testapp-v1.0.0" / "main.py").read_text() == "print('hello')"
        assert mock_get.call_args_list[2].args[0] == "https://downloads.example.com/v1.0.0/testapp-v1.0.0.zip"

    @patch("launcher.updater.requests.get")
    def test_auto_update_downloads_manifest_archive_url(self, mock_get, tmp_path, signed_config):
        """Auto-update should download the app archive URL named in the manifest."""
        config, private_key = signed_config
        config.path = str(tmp_path)
        config.auto_update = True
        config.archive_endpoint = "/provider/archive/{ref}"
        archive = _zip_bytes({"root/main.py": "print('hello')"})
        manifest = _manifest_bytes("TestApp", "v2.0.0", archive)
        signature = private_key.sign(manifest)

        latest_response = Mock()
        latest_response.json.return_value = {"tag_name": "v2.0.0"}
        latest_response.raise_for_status = Mock()
        manifest_response = Mock(content=manifest)
        manifest_response.raise_for_status = Mock()
        signature_response = Mock(content=signature)
        signature_response.raise_for_status = Mock()
        archive_response = Mock()
        archive_response.headers = {"content-length": str(len(archive))}
        archive_response.iter_content = lambda chunk_size: [archive]
        archive_response.raise_for_status = Mock()
        mock_get.side_effect = [
            latest_response,
            manifest_response,
            signature_response,
            archive_response,
        ]

        updated, version = update_sources(config)

        assert updated is True
        assert version == "v2.0.0"
        assert (tmp_path / "sources" / "testapp-v2.0.0" / "main.py").read_text() == "print('hello')"
        assert mock_get.call_args_list[3].args[0] == _archive_url("v2.0.0")
        assert "/provider/archive/" not in mock_get.call_args_list[3].args[0]

    @patch("launcher.updater.requests.get")
    def test_missing_manifest_archive_asset_has_upload_guidance(self, mock_get, tmp_path, signed_config):
        """A missing app archive asset should point at the archive named in the manifest."""
        import requests

        config, _private_key = signed_config
        config.path = str(tmp_path)
        archive_response = Mock()
        archive_response.status_code = 404
        archive_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found",
            response=archive_response,
        )
        mock_get.return_value = archive_response

        with pytest.raises(HTTPStatusError) as exc_info:
            download_and_extract_sources(
                config,
                "v1.0.0",
                archive_url="https://downloads.example.com/v1.0.0/testapp-v1.0.0.zip",
            )

        message = str(exc_info.value)
        assert "Release archive asset is missing" in message
        assert "Upload the app archive named in the signed manifest" in message

    def test_update_sources_rejects_download_without_trust(self, tmp_path, mock_config):
        """A missing app archive download cannot proceed without signed manifest trust."""
        mock_config.path = str(tmp_path)
        mock_config.auto_update = False
        mock_config.version = "v1.0.0"

        with pytest.raises(UpdaterError, match="Signed manifest"):
            update_sources(mock_config)
