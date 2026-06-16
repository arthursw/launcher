"""Tests for runtime state handling."""

import os

import yaml

from launcher.config import ProxySettings
from launcher.paths import get_default_state_dir
from launcher.state import LauncherState


def test_runtime_state_persists_version_dependency_hash_and_project_install(tmp_path):
    """Mutable runtime fields are stored outside application.yml."""
    state_path = tmp_path / "state.yml"
    state = LauncherState.load("TestApp", state_path)
    state.version = "v1.2.3"
    state.dependency_hash = "abc123"
    state.project_install_fingerprint = "project456"
    state.save()

    reloaded = LauncherState.load("TestApp", state_path)

    assert reloaded.version == "v1.2.3"
    assert reloaded.dependency_hash == "abc123"
    assert reloaded.project_install_fingerprint == "project456"


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
