"""Mutable runtime state for the launcher."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import yaml

from .config import ProxySettings
from .paths import get_runtime_data_dir

logger = logging.getLogger(__name__)


@dataclass
class ProxyCredential:
    """Persistable proxy endpoint metadata."""

    scheme: str
    host: str
    port: Optional[int] = None
    username: Optional[str] = None
    credential_ref: Optional[str] = None


@dataclass
class LauncherState:
    """Mutable state kept outside the packaged configuration."""

    app_name: str
    state_path: Path
    version: Optional[str] = None
    dependency_hash: Optional[str] = None
    proxy_http: Optional[ProxyCredential] = None
    proxy_https: Optional[ProxyCredential] = None
    proxy_ssl_cert_file: Optional[str] = None
    session_proxy_settings: Optional[ProxySettings] = field(default=None, repr=False)

    @classmethod
    def for_app(cls, app_name: str, state_dir: Optional[Path] = None) -> "LauncherState":
        """Load state for an application."""
        root = state_dir or get_runtime_data_dir(app_name)
        path = root / "launcher-state.yml"
        return cls.load(app_name, path)

    @classmethod
    def load(cls, app_name: str, state_path: Path) -> "LauncherState":
        """Load state from a YAML file, returning empty state if absent."""
        state_path = state_path.expanduser()
        if not state_path.exists():
            return cls(app_name=app_name, state_path=state_path)

        with open(state_path) as f:
            data = yaml.safe_load(f) or {}

        proxy_data = data.get("proxy") or {}
        return cls(
            app_name=app_name,
            state_path=state_path,
            version=data.get("version"),
            dependency_hash=data.get("dependency_hash"),
            proxy_http=_credential_from_dict(proxy_data.get("http")),
            proxy_https=_credential_from_dict(proxy_data.get("https")),
            proxy_ssl_cert_file=proxy_data.get("ssl_cert_file"),
        )

    def save(self) -> None:
        """Write state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if self.version:
            data["version"] = self.version
        if self.dependency_hash:
            data["dependency_hash"] = self.dependency_hash

        proxy: dict[str, Any] = {}
        if self.proxy_http:
            proxy["http"] = _credential_to_dict(self.proxy_http)
        if self.proxy_https:
            proxy["https"] = _credential_to_dict(self.proxy_https)
        if self.proxy_ssl_cert_file:
            proxy["ssl_cert_file"] = self.proxy_ssl_cert_file
        if proxy:
            data["proxy"] = proxy

        with open(self.state_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    def proxy_settings(self) -> Optional[ProxySettings]:
        """Return persisted proxy settings, loading passwords from keychain if available."""
        if self.session_proxy_settings:
            return self.session_proxy_settings

        http = _url_from_credential(self.proxy_http)
        https = _url_from_credential(self.proxy_https)
        if http or https or self.proxy_ssl_cert_file:
            return ProxySettings(http=http, https=https, ssl_cert_file=self.proxy_ssl_cert_file)
        return None

    def remember_proxy_settings(
        self,
        proxy: ProxySettings,
        remember_password: bool = False,
    ) -> None:
        """Persist proxy metadata, storing passwords in keychain only by opt-in."""
        self.proxy_http = _credential_from_url(
            proxy.http,
            self.app_name,
            "http",
            remember_password,
        )
        self.proxy_https = _credential_from_url(
            proxy.https,
            self.app_name,
            "https",
            remember_password,
        )
        self.proxy_ssl_cert_file = proxy.ssl_cert_file
        self.session_proxy_settings = proxy
        self.save()


def _credential_from_dict(data: Optional[dict[str, Any]]) -> Optional[ProxyCredential]:
    if not data:
        return None
    return ProxyCredential(
        scheme=data["scheme"],
        host=data["host"],
        port=data.get("port"),
        username=data.get("username"),
        credential_ref=data.get("credential_ref"),
    )


def _credential_to_dict(credential: ProxyCredential) -> dict[str, Any]:
    data: dict[str, Any] = {
        "scheme": credential.scheme,
        "host": credential.host,
    }
    if credential.port is not None:
        data["port"] = credential.port
    if credential.username:
        data["username"] = credential.username
    if credential.credential_ref:
        data["credential_ref"] = credential.credential_ref
    return data


def _credential_from_url(
    url: Optional[str],
    app_name: str,
    state_key: str,
    remember_password: bool,
) -> Optional[ProxyCredential]:
    if not url:
        return None

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.hostname:
        return None

    credential_ref = None
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    if remember_password and password:
        credential_ref = f"launcher:{app_name}:{state_key}:{secrets.token_urlsafe(12)}"
        if not _store_keychain_password(credential_ref, username or "", password):
            credential_ref = None

    return ProxyCredential(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port,
        username=username,
        credential_ref=credential_ref,
    )


def _url_from_credential(credential: Optional[ProxyCredential]) -> Optional[str]:
    if not credential:
        return None

    password = None
    if credential.credential_ref:
        password = _load_keychain_password(credential.credential_ref, credential.username or "")

    userinfo = ""
    if credential.username:
        userinfo = quote(credential.username)
        if password:
            userinfo = f"{userinfo}:{quote(password)}"
        userinfo = f"{userinfo}@"

    host = credential.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{userinfo}{host}"
    if credential.port is not None:
        netloc = f"{netloc}:{credential.port}"
    return urlunsplit((credential.scheme, netloc, "", "", ""))


def _store_keychain_password(credential_ref: str, username: str, password: str) -> bool:
    try:
        import keyring

        keyring.set_password(credential_ref, username, password)
        return True
    except Exception as e:
        logger.warning("Could not store proxy password in keychain: %s", e)
        return False


def _load_keychain_password(credential_ref: str, username: str) -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(credential_ref, username)
    except Exception as e:
        logger.warning("Could not load proxy password from keychain: %s", e)
        return None
