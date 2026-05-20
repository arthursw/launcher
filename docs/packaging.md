# Packaging Guide

This guide explains how to use Launcher to ship your Python app.

You do not package your real app with PyInstaller. You package Launcher, and
Launcher downloads and starts your real app.

## 1. Prepare Your App

Your app should be in a GitHub or GitLab repository and should publish releases.
The release tag is the version Launcher will download.

Your app repository should contain a normal Python dependency file, for example:

- `pyproject.toml`
- `requirements.txt`
- `environment.yml`
- `pixi.toml`

Launcher uses that file to create the Python environment on the user's machine.

## 2. Add A Launcher Config

In this repository, create a folder for your app:

```text
myapp/
|-- myapp.yml
|-- myapp.icns
`-- icon_128x128.png
```

Generate the signing key once:

```bash
uv run launcher-release keygen
```

This creates `launcher-signing-key.pem`, adds it to `.gitignore`, and prints the
public key used below.

Minimal config:

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

See [configuration.md](configuration.md) for the meaning of each field.

## 3. Add A PyInstaller Spec

Create `myapp_launcher.spec`.

The important part is that PyInstaller analyzes the generic launcher, `main.py`,
and bundles your app config as data:

```python
a = Analysis(
    ["main.py"],
    datas=[
        ("myapp/myapp.yml", "myapp"),
        ("myapp/icon_128x128.png", "resources"),
    ],
)
```

Do not create a Python wrapper like `main_myapp.py`. The same launcher entry
point is used for every app.

## 4. Build The Launcher

```bash
uv run --with pyinstaller pyinstaller myapp_launcher.spec
```

On macOS, distribute the generated `.app` bundle. On Windows and Linux,
distribute the generated PyInstaller folder or executable.

## 5. Publish App Updates

When your real app changes:

1. create a normal GitHub or GitLab release;
2. put the source archive in `dist/`;
3. generate and check the signed launcher manifest;
4. upload `launcher-manifest.yml` and `launcher-manifest.yml.sig` as release
   assets.

The default signing command looks in `dist/`, infers the version from the
archive filename, writes the manifest and signature back to `dist/`, and uses
the app name from your config:

```bash
uv run launcher-release sign
uv run launcher-release verify
uv run launcher-release upload
```

For example, if `dist/` contains `myapp-v1.2.3.zip`, the manifest version is
`v1.2.3`.

Users do not need a new launcher build for every app change. The launcher will
find the new release, verify it, download it, and start it.

`upload` calls the official provider CLI:

- GitHub: `gh`, installed from https://github.com/cli/cli#installation
- GitLab: `glab`, installed from https://gitlab.com/gitlab-org/cli/#installation

Authenticate those tools as described in their documentation. Launcher does not
manage GitHub or GitLab tokens itself.

If you do not want to use `gh` or `glab`, upload `launcher-manifest.yml` and
`launcher-manifest.yml.sig` manually from the GitHub or GitLab release page. See
[security.md](security.md) for what those files are.

If defaults are not enough, pass the values explicitly:

```bash
uv run launcher-release sign \
  --config myapp/myapp.yml \
  --archive dist/myapp-v1.2.3.zip \
  --version v1.2.3

uv run launcher-release verify \
  --config myapp/myapp.yml \
  --archive dist/myapp-v1.2.3.zip

uv run launcher-release upload \
  --config myapp/myapp.yml \
  --archive dist/myapp-v1.2.3.zip
```

## During Development

You can run Launcher without PyInstaller:

```bash
uv run python main.py -c myapp/myapp.yml
```
