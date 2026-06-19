# Launcher

Launcher is a small stable executable that starts and updates a Python desktop app.

You package and sign Launcher when the executable, bundled config, icon, or launcher tooling changes.
Your app code ships separately as signed GitHub or GitLab release assets.

That split keeps normal app releases small:

- the launcher executable is the durable file users install;
- the app release archive is the versioned source bundle Launcher downloads, verifies, installs, and runs;
- the signed manifest tells Launcher which archive belongs to each app release.

## Minimal Workflow

Initialize an app repository:

```bash
uv add --dev launcher
uv run launcher init --name MyApp --repository https://github.com/my-org/myapp.git
uv run launcher config check
uv run launcher release keygen
```

Build the launcher executable when it changes:

```bash
uv run launcher build
# sign/notarize the built launcher here
uv run launcher build package --version v1.2.3
uv run launcher release create v1.2.3 --notes RELEASE_NOTES.md
uv run launcher build upload --version v1.2.3
```

Publish a normal app-only release:

```bash
uv run launcher release create v1.2.3 --notes RELEASE_NOTES.md
uv run launcher release archive v1.2.3
uv run launcher release sign
uv run launcher release verify
uv run launcher release upload
```

Only run `launcher build package` and `launcher build upload` for releases where the launcher executable changed.
For ordinary app changes, publish the app archive, manifest, and signature.

## Learn More

- [Packaging guide](docs/packaging.md)
- [Configuration guide](docs/configuration.md)
- [Security guide](docs/security.md)

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```
