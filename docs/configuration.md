# Configuration Guide

Each packaged launcher includes one YAML file describing the app it should run.
This file is usually named after the app, for example `myapp/myapp.yml`.

## Minimal Example

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
main: main.py
path: "~/Applications/MyApp"
auto_update: true
configuration: pyproject.toml

trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

## Main Fields

- `name`: display name of your app. Also used to name local data folders.
- `repository`: GitHub or GitLab repository containing your app.
- `main`: Python file to run inside the downloaded app sources.
- `path`: where app sources are stored on the user's machine.
- `auto_update`: when true, Launcher checks the latest release.
- `configuration`: dependency file in your app sources.

If your repository cannot be inferred automatically, you can use explicit API
fields instead of `repository`:

```yaml
api: https://api.github.com
releases_endpoint: /repos/my-org/myapp/releases/latest
archive_endpoint: /repos/my-org/myapp/zipball/{ref}
```

## Security Fields

The `trust` section tells Launcher how to verify downloaded app sources.
Generate the key with:

```bash
uv run launcher-release keygen
```

The command prints the `public_key` value.

```yaml
trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

This is required because Launcher downloads Python code and runs it. See
[security.md](security.md) for the explanation.

## Optional Fields

```yaml
version: v1.2.3
install: install.py
reinstall_on_update: false
gui_timeout: 3
init_message: "Initialized"
init_timeout: 30
```

- `version`: fixed version to use when `auto_update` is false.
- `install`: optional Python install script in your app sources.
- `reinstall_on_update`: rerun the install script after an update.
- `gui_timeout`: seconds before showing a progress window.
- `init_message`: text printed by your app when it is ready.
- `init_timeout`: how long to wait for `init_message`.

## Runtime State

Launcher does not edit the packaged YAML file during normal use.

Values that change, such as the installed version, dependency hash, and proxy
settings, are saved in the user's app data folder:

- macOS: `~/Library/Application Support/<AppName>/launcher-state.yml`
- Windows: `%APPDATA%\<AppName>\launcher-state.yml`
- Linux: `~/.local/state/<AppName>/launcher-state.yml`

Proxy passwords are not stored in YAML. If the user chooses to remember a proxy
password, Launcher stores it in the operating system keychain.
