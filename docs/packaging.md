# Packaging Guide

This guide explains how to use Launcher from your app repository.

You do not package your real app with PyInstaller. You package Launcher once,
and Launcher downloads, verifies, installs, and starts your real app releases.

## 1. Add Launcher Tooling

In your app repository, add Launcher as a development dependency:

```bash
uv add --dev launcher
```

## 2. Initialize Launcher Packaging

```bash
uv run launcher init --name MyApp --repository https://github.com/my-org/myapp.git
```

This creates the default app-owned launcher packaging folder:

```text
packaging/
`-- launcher/
    |-- application.yml
    `-- icon_128x128.png
```

Edit `packaging/launcher/application.yml` for your app:

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
main: main.py
path: "."
auto_update: true
configuration: pyproject.toml

trust:
  mode: signed_manifest
  # Replace this with the public key printed by `launcher release keygen`
  public_key: "<base64-ed25519-public-key>"
  # These default URLs match the manifest and signature produced by
  # `launcher release sign` and uploaded by `launcher release upload`.
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

The default config path is used automatically by `launcher run`,
`launcher build`, and `launcher release ...`.

## 3. Create The Signing Key

Generate the signing key once:

```bash
uv run launcher release keygen
```

This creates `launcher-signing-key.pem`, adds it to `.gitignore`, and prints the
public key to place in `packaging/launcher/application.yml`.

Replace:

```yaml
public_key: "<base64-ed25519-public-key>"
```

with the printed public key. The private key stays outside git and is used later
by `launcher release sign`.

The generated `manifest_url` and `signature_url` point to the release assets
that the launcher downloads at runtime. The defaults match the files produced by
`launcher release sign` and uploaded by `launcher release upload`. If you change
`repository` after running `init`, update those two URLs too, or rerun
`init --force` with the real repository. Edit them only for custom hosting,
custom asset paths, or renamed manifest/signature files. `{version}` is replaced
with the release tag the launcher is trying to run.

## 4. Build The Launcher

```bash
uv run --with pyinstaller launcher build
```

Launcher generates PyInstaller build files from `packaging/launcher/` and writes
the launcher build under:

```text
dist/launcher/
```

The generated launcher build is distinct from your app release artifacts. You
only need to rebuild it when launcher tooling, launcher config, icons, signing,
or packaging settings change.

For CI or inspection without running PyInstaller:

```bash
uv run launcher build --spec-only
```

## 5. Publish App Updates

For each real app release:

1. create a normal GitHub or GitLab release;
2. put the app source archive in `dist/`;
3. sign and verify the release manifest;
4. upload the manifest and signature as release assets.

```bash
uv run launcher release sign
uv run launcher release verify
uv run launcher release upload
```

By default, the release commands read
`packaging/launcher/application.yml`, infer the archive/version from `dist/`,
and write:

```text
dist/
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

Users do not need a new launcher build for every app change. The launcher will
find the new release, verify it, download it, and start it.

If defaults are not enough, pass explicit values:

```bash
uv run launcher release sign \
  --config packaging/launcher/application.yml \
  --archive dist/myapp-v1.2.3.zip \
  --version v1.2.3
```

During development, run the launcher from source with:

```bash
uv run launcher run
```
