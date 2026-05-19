# Configuration

`application.yml` is packaged configuration. The launcher does not update it
during normal operation.

## App Config

Required:

```yaml
name: MyApp
main: main.py
path: "~/Applications/MyApp"
repository: git@github.com:org/myapp.git
trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
  manifest_url: "https://github.com/org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

Useful optional fields:

```yaml
auto_update: true
version: v1.2.3
configuration: pyproject.toml
install: install.py
reinstall_on_update: false
gui_timeout: 3
init_message: "Initialized"
init_timeout: 30
```

`repository` can be replaced by explicit `api`, `releases_endpoint`, and
`archive_endpoint`.

## Runtime State

Mutable state is stored in OS app data:

- macOS: `~/Library/Application Support/<AppName>/launcher-state.yml`
- Windows: `%APPDATA%\<AppName>\launcher-state.yml`
- Linux: `~/.local/state/<AppName>/launcher-state.yml`

State stores:

- `version`
- `dependency_hash`
- proxy host, port, username, credential reference, and SSL certificate path

Set `LAUNCHER_STATE_DIR` to override the state root for tests or controlled
deployments.

## Proxy Secrets

Proxy passwords are never written to YAML. If the user selects the remember
option in the proxy prompt, the password is saved through `keyring` in the OS
keychain and state stores only a `credential_ref`.

If keychain storage is unavailable, the launcher keeps the entered proxy URL for
the current session only and writes password-free proxy metadata to state.

Avoid putting credentials in `proxy_servers`. Use password-free defaults only:

```yaml
proxy_servers:
  http: http://proxy.corp.com:8080
  https: http://proxy.corp.com:8080
  ssl_cert_file: /path/to/corporate-ca.pem
```

## Dependency Hashing

The runtime environment is recreated when dependency inputs change. The hash
includes the configured dependency file, common lock files such as `uv.lock` and
`pixi.lock`, and the optional install script.

State is updated only after the environment setup and install path succeeds.
