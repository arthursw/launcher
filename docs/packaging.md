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
    |-- launcher.svg
    `-- icon_128x128.png
```

The SVG is editable source artwork. The PNG is used as the default build icon.
To copy a custom app icon into `packaging/launcher/`, pass `--icon`:

```bash
uv run launcher init \
  --name MyApp \
  --repository https://github.com/my-org/myapp.git \
  --icon path/to/app.icns
```

Supported icon inputs are `.icns`, `.ico`, and `.png`. On macOS, `.icns` is the
native icon format and is preferred for polished releases, but `.png` can be used.

Edit `packaging/launcher/application.yml` for your app:

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
entrypoint:
  mode: script
  script: main.py
auto_update: true
configuration: pyproject.toml
# extras:
#   - desktop

trust:
  mode: signed_manifest
  # Replace this with the public key printed by `launcher release keygen`
  public_key: "<base64-ed25519-public-key>"
  # These default URLs match the archive, manifest, and signature produced by
  # `launcher release sign` and uploaded by `launcher release upload`.
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
  archive_url: "https://github.com/my-org/myapp/releases/download/{version}/{archive_name}"
```

The default config path is used automatically by `launcher run`,
`launcher build`, and `launcher release ...`.

`path` is optional. When omitted, Launcher stores downloaded app sources in the
per-app runtime data directory, using one subfolder per version.

To validate the config without building or starting the app:

```bash
uv run launcher config check
```

Choose the entrypoint mode that matches how you start the app during
development:

```yaml
entrypoint:
  mode: script
  script: main.py
```

```yaml
entrypoint:
  mode: module
  module: my_app
  args:
    - --desktop
```

```yaml
entrypoint:
  mode: project
  command: my-app-gui
  project_directory: backend
```

Use `script` for a Python file, `module` for `python -m ...`, and `project`
for installed console scripts or apps that need package metadata, entry points,
plugins, or packaged data.

Entrypoint paths and `configuration` are relative to the downloaded repository
root. If your Python project is in a subdirectory, point the dependency config
at that subdirectory:

```yaml
entrypoint:
  mode: module
  module: my_app
  args:
    - --desktop
configuration: backend/pyproject.toml
extras:
  - desktop
```

Use `extras` for optional dependency groups from `pyproject.toml`, for example
the same group you install during development with `uv sync --extra desktop`.
The configured dependency file must exist in the downloaded release archive. If
your app intentionally has no dependency config file, set `configuration: null`.

Launcher starts the app from the directory containing `configuration` and makes
that directory importable. If that directory has a `src/` folder, Launcher makes
it importable too. For the example above, the inferred launch directory is
`backend/` and `backend/src` is importable. Override this only for unusual
layouts:

```yaml
working_directory: backend
pythonpath:
  - backend/src
```

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

The generated `manifest_url`, `signature_url`, and `archive_url` point to the release assets that the launcher downloads at runtime.
The defaults match the files produced by `launcher release sign` and uploaded by `launcher release upload`.
If you change `repository` after running `init`, update those URLs too, or rerun `init --force` with the real repository.
Edit them only for custom hosting, custom asset paths, or renamed release assets.
`{version}` is replaced with the release tag the launcher is trying to run, and `{archive_name}` is replaced with the local archive filename written into the signed manifest.

For GitLab, the packaged launcher uses the public GitLab API. If update checks
fail with `404 Project Not Found`, verify that the project is public or add the
numeric project id to `application.yml`:

```yaml
gitlab_project_id: "123456"
```

## 4. Build The Launcher

```bash
uv run --with pyinstaller launcher build
```

`launcher build` validates `packaging/launcher/application.yml` before writing
build files or running PyInstaller, so config errors fail before a packaged app
is produced.

Launcher generates PyInstaller build files from `packaging/launcher/` and writes
the launcher build under:

```text
dist/launcher/
```

On macOS, PyInstaller may produce both forms:

```text
dist/launcher/
|-- MyApp.app
|-- myapp/
`-- build/
```

`MyApp.app` is the macOS app bundle. `myapp/` is PyInstaller's
directory-style executable build, which is useful for command-line debugging.
`build/` contains generated PyInstaller inputs and intermediate files; it is not
part of the app release you give to users.

The generated launcher build is distinct from your app release artifacts. You
only need to rebuild it when launcher tooling, launcher config, icons, signing,
or packaging settings change.

For CI or inspection without running PyInstaller:

```bash
uv run launcher build --spec-only
```

For a one-off build icon override without changing `packaging/launcher/`:

```bash
uv run --with pyinstaller launcher build --icon path/to/app.icns
```

## 5. Publish App Updates

For each app release, first publish a normal GitHub or GitLab release for the
version tag, then let Launcher create and upload the signed update metadata for
that release.

### 5.1. Create The Release

Create the GitHub or GitLab release for the tag you want users to run.

```bash
gh release create v1.2.3 --generate-notes
```

```bash
glab release create v1.2.3 --notes "Release v1.2.3"
```

For more options, see [`gh release create`](https://cli.github.com/manual/gh_release_create)
and [`glab release create`](https://docs.gitlab.com/cli/release/create/).

You can also create the release manually in the GitHub or GitLab web UI. See
GitHub's [web UI release guide](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository?tool=webui)
and GitLab's [Releases page guide](https://docs.gitlab.com/user/project/releases/#create-a-release-in-the-releases-page).
For GitLab, tags alone are not enough: the packaged launcher asks the GitLab
Releases API for the latest release.

### 5.2. Create Or Update The Archive Script

Keep archive construction in the app repository, for example in `packaging/launcher/build-release-archive.sh`.
The script should take a version and write one `.zip` archive to `dist/`, such as `dist/myapp-v1.2.3.zip`.
Simple apps can make this script zip tracked sources.
Apps with generated assets should build those assets first and include the generated output in the zip.
Do not commit generated `frontend/dist/` only for Launcher; build it inside the archive script or CI release job.

### 5.3. Build The App Archive

```bash
./packaging/launcher/build-release-archive.sh v1.2.3
```

Launcher hashes this exact local archive when it creates the signed manifest.

### 5.4. Sign And Verify

Create and verify the signed Launcher metadata:

```bash
uv run launcher release sign
uv run launcher release verify
```

By default, these commands read `packaging/launcher/application.yml`, infer the `.zip` archive from `dist/`, infer the version from the archive filename, and write the archive URL into the signed manifest.
If the archive filename does not contain the version, pass `--version` to `sign`.
Both commands also check that the archive can be safely extracted by the packaged launcher.
Unsafe paths, special files, and unsafe symlinks are rejected before metadata is uploaded.
The commands write:

```text
dist/
|-- myapp-v1.2.3.zip
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

### 5.5. Upload The App Archive And Launcher Metadata

Upload the app archive, manifest, and signature to the release:

```bash
uv run launcher release upload
```

This is the recommended upload step because it uses the configured repository and the signed manifest's archive metadata.
The packaged launcher expects all three files to be available as release assets.

If you need to upload the generated files manually, the equivalent CLI commands are:

```bash
gh release upload v1.2.3 \
  dist/myapp-v1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig \
  --clobber

glab release upload v1.2.3 \
  dist/myapp-v1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig
```

For more options, see [`gh release upload`](https://cli.github.com/manual/gh_release_upload)
and [`glab release upload`](https://docs.gitlab.com/cli/release/upload/).

Users do not need a new launcher build for every app change. The launcher will
find the new release, verify it, download it, and start it.

If `dist/` contains more than one archive, if the archive filename does not
contain the version, or if you want the release process to be fully explicit,
pass the same archive to all three Launcher commands and pass the version to
`sign`:

```bash
uv run launcher release sign \
  --config packaging/launcher/application.yml \
  --archive dist/myapp-v1.2.3.zip \
  --version v1.2.3
uv run launcher release verify \
  --config packaging/launcher/application.yml \
  --archive dist/myapp-v1.2.3.zip
uv run launcher release upload \
  --config packaging/launcher/application.yml \
  --archive dist/myapp-v1.2.3.zip
```

During development, run the launcher from source with:

```bash
uv run launcher run
```
