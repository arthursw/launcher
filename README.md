# Launcher

Launcher is a small Python bootstrap application for shipping Python apps
without freezing the real app every time it changes.

At runtime it:

1. reads an immutable app configuration;
2. resolves the target release;
3. verifies a signed release manifest with Ed25519;
4. downloads and verifies the source archive hash from that manifest;
5. safely extracts sources;
6. creates or recreates the Python environment with Wetlands;
7. runs the configured app entry point and exits after successful initialization.

The launched app keeps running after the launcher exits.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

Run from source:

```bash
uv run python main.py -c application.yml
uv run python main.py -c application.yml --no-gui
uv run python main.py -c application.yml --immediate-gui
```

The package entry point is `launcher.main:main`. The repository-root `main.py`
is only a thin compatibility wrapper.

## Required Update Trust

Updates require a signed manifest. Add this to each app config:

```yaml
trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
  manifest_url: "https://github.com/org/app/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/org/app/releases/download/{version}/launcher-manifest.yml.sig"
```

Manifest format:

```yaml
schema_version: 1
application: MyApp
version: v1.2.3
archive:
  sha256: "<hex-sha256-of-source-archive>"
```

Publish `launcher-manifest.yml` and `launcher-manifest.yml.sig` as release
assets. See [docs/security.md](docs/security.md) for the full release flow.

## Configuration And State

`application.yml` is treated as packaged configuration. Runtime values are kept
in OS app data:

- macOS: `~/Library/Application Support/<AppName>/launcher-state.yml`
- Windows: `%APPDATA%\<AppName>\launcher-state.yml`
- Linux: `~/.local/state/<AppName>/launcher-state.yml`

Runtime state stores the installed version, dependency hash, and proxy metadata.
Proxy passwords are never written to YAML. If the user chooses the remember
option, passwords are stored through the OS keychain via `keyring`; otherwise
they are session-only.

See [docs/configuration.md](docs/configuration.md).

## Packaging

PyInstaller specs should analyze the generic launcher entry point, not an
app-specific Python wrapper. Bundle the app YAML as data.

```bash
uv run --with pyinstaller pyinstaller galaxy_launcher.spec
```

When no config is passed, source runs check `application.yml` in the current
directory and beside the repo root wrapper. Frozen apps also check sidecar and
bundled configs named after the executable.

See [docs/packaging.md](docs/packaging.md).
