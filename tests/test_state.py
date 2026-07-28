"""Tests for runtime state handling."""

import os
from pathlib import Path

import pytest
import yaml

from launcher.config import ProxySettings
from launcher.paths import get_default_state_dir, get_portable_state_dir
from launcher.state import LauncherState, StateStorageError, resolve_state_dir


def test_runtime_state_persists_version_dependency_hash_and_project_install(tmp_path):
    """Mutable runtime fields are stored outside application.yml."""
    state_path = tmp_path / "state.yml"
    state = LauncherState.load("TestApp", state_path)
    state.version = "v1.2.3"
    state.dependency_hash = "abc123"
    state.project_install_fingerprint = "project456"
    state.installation_root = str(tmp_path / "app")
    state.save()

    reloaded = LauncherState.load("TestApp", state_path)

    assert reloaded.version == "v1.2.3"
    assert reloaded.dependency_hash == "abc123"
    assert reloaded.project_install_fingerprint == "project456"
    assert reloaded.installation_root == str(tmp_path / "app")


def test_proxy_password_is_not_written_to_yaml(tmp_path):
    """Proxy passwords must not leak to runtime YAML state."""
    state_path = tmp_path / "state.yml"
    state = LauncherState.load("TestApp", state_path)
    state.remember_proxy_settings(
        ProxySettings(http="http://alice:secret@proxy.example.com:8080"),
        remember_password=False,
    )

    raw = state_path.read_text()
    data = yaml.safe_load(raw)

    assert "secret" not in raw
    assert data["proxy"]["http"]["host"] == "proxy.example.com"
    assert data["proxy"]["http"]["username"] == "alice"
    assert "credential_ref" not in data["proxy"]["http"]


def test_keychain_failure_falls_back_to_session_only(tmp_path, monkeypatch):
    """If keychain storage is unavailable, password remains session-only."""
    monkeypatch.setattr("launcher.state._store_keychain_password", lambda *_args: False)
    state_path = tmp_path / "state.yml"
    state = LauncherState.load("TestApp", state_path)
    proxy = ProxySettings(http="http://alice:secret@proxy.example.com:8080")

    state.remember_proxy_settings(proxy, remember_password=True)
    reloaded = LauncherState.load("TestApp", state_path)

    state_proxy = state.proxy_settings()
    reloaded_proxy = reloaded.proxy_settings()
    assert state_proxy is not None
    assert reloaded_proxy is not None
    assert state_proxy.http == proxy.http
    assert reloaded_proxy.http == "http://alice@proxy.example.com:8080"


def test_remembered_proxy_password_loads_from_keychain(tmp_path, monkeypatch):
    """Remembered passwords are reconstructed from keychain references."""
    passwords = {}

    def store(ref, username, password):
        passwords[(ref, username)] = password
        return True

    def load(ref, username):
        return passwords[(ref, username)]

    monkeypatch.setattr("launcher.state._store_keychain_password", store)
    monkeypatch.setattr("launcher.state._load_keychain_password", load)
    state_path = tmp_path / "state.yml"
    state = LauncherState.load("TestApp", state_path)
    state.remember_proxy_settings(
        ProxySettings(http="http://alice:secret@proxy.example.com:8080"),
        remember_password=True,
    )

    reloaded = LauncherState.load("TestApp", state_path)

    reloaded_proxy = reloaded.proxy_settings()
    assert reloaded_proxy is not None
    assert "secret" not in state_path.read_text()
    assert reloaded_proxy.http == "http://alice:secret@proxy.example.com:8080"


def test_default_state_paths(monkeypatch, tmp_path):
    """State paths follow the current platform conventions."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    assert get_default_state_dir("My App") == tmp_path / "xdg-state" / "My_App"

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert get_default_state_dir("My App") == tmp_path / "AppData" / "Roaming" / "My_App"

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert str(get_default_state_dir("My App")).endswith(
        os.path.join("Library", "Application Support", "My_App")
    )


def test_state_for_app_uses_launcher_state_dir(monkeypatch, tmp_path):
    """The test/runtime override should redirect per-app state roots."""
    monkeypatch.setenv("LAUNCHER_STATE_DIR", str(tmp_path / "runtime"))

    state = LauncherState.for_app("My App")

    assert state.state_path == tmp_path / "runtime" / "My_App" / "launcher-state.yml"


def test_existing_portable_state_precedes_os_state(monkeypatch, tmp_path):
    """An explicit portable sidecar remains discoverable on later launches."""
    monkeypatch.delenv("LAUNCHER_STATE_DIR", raising=False)
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / "launcher-state.yml").write_text("{}")
    canonical = tmp_path / "canonical"
    monkeypatch.setattr("launcher.state.get_portable_state_dir", lambda _name: portable)
    monkeypatch.setattr("launcher.state.get_default_state_dir", lambda _name: canonical)

    assert resolve_state_dir("My App") == portable
    assert not canonical.exists()


def test_portable_state_is_beside_macos_app_bundle(monkeypatch):
    """Portable state must never be written inside a signed app bundle."""
    monkeypatch.setattr("launcher.paths.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "launcher.paths.sys.executable",
        "/Downloads/MyApp.app/Contents/MacOS/myapp",
    )

    assert get_portable_state_dir("My App") == Path("/Downloads/My_App-launcher-data")


def test_unwritable_canonical_state_reports_portable_fallback(monkeypatch, tmp_path):
    """State discovery exposes, but does not silently select, Portable Mode."""
    monkeypatch.delenv("LAUNCHER_STATE_DIR", raising=False)
    canonical = tmp_path / "canonical"
    portable = tmp_path / "portable"
    monkeypatch.setattr("launcher.state.get_default_state_dir", lambda _name: canonical)
    monkeypatch.setattr("launcher.state.get_portable_state_dir", lambda _name: portable)
    monkeypatch.setattr(
        "launcher.state._require_writable_state_dir",
        lambda _path: (_ for _ in ()).throw(StateStorageError("read only")),
    )
    monkeypatch.setattr("launcher.state._state_dir_is_writable", lambda _path: True)

    with pytest.raises(StateStorageError) as raised:
        resolve_state_dir("My App")

    assert raised.value.state_dir == canonical
    assert raised.value.portable_dir == portable
    assert raised.value.portable_available is True
