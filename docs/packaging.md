# Packaging Guide

This guide describes the release workflow for an app repository that uses Launcher.

Launcher is the stable executable users install.
Your app is the versioned archive Launcher downloads from GitHub or GitLab releases.

## Phase 1: Initialize Config

Add Launcher as a development dependency:

```bash
uv add --dev launcher
```

Create the app-owned packaging files:

```bash
uv run launcher init --name MyApp --repository https://github.com/my-org/myapp.git
```

Launcher writes:

```text
packaging/
`-- launcher/
    |-- application.yml
    |-- launcher.svg
    `-- icon_128x128.png
```

Edit `packaging/launcher/application.yml` for your app:

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
entrypoint:
  mode: script
  script: main.py
auto_update: true
configuration: pyproject.toml

trust:
  mode: signed_manifest
  public_key: "<base64-ed25519-public-key>"
```

Validate the config:

```bash
uv run launcher config check
```

Use `script` for a Python file, `module` for `python -m ...`, and `project` for an installed console command.
Entrypoint paths and `configuration` are relative to the downloaded app archive root.
If your app has optional dependencies, list their extras in `extras`.
If the dependency file lives below the repository root, set `configuration` to that path.

## Phase 2: Create The Signing Key

Generate the app release signing key once:

```bash
uv run launcher release keygen
```

The command writes `launcher-signing-key.pem`, adds it to `.gitignore`, and prints the public key.
Copy the printed public key into `trust.public_key`.

Keep the private key secret.
`launcher release sign` uses it to sign `launcher-manifest.yml`.
The packaged launcher verifies that manifest before it downloads or runs app code.

## Phase 3: Build, Sign, Package, And Upload The Launcher

Build the launcher executable:

```bash
uv run launcher build
```

The build output is written under `dist/launcher/`.
On macOS, PyInstaller can produce `dist/launcher/MyApp.app`.
On Windows and Linux, PyInstaller produces a directory-style build such as `dist/launcher/myapp/`.

Sign and notarize the built launcher before packaging it.
Launcher does not replace operating-system signing.

Useful official references:

- Apple: [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- Apple: [Code Signing Services](https://developer.apple.com/documentation/security/code-signing-services)
- Microsoft: [Cryptography Tools](https://learn.microsoft.com/en-us/windows/win32/seccrypto/cryptography-tools)
- Microsoft: [SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)

For Linux, trust normally comes from the distribution channel.
Use the signing and packaging conventions of the package manager, repository, or installer format you distribute through.

After OS signing and notarization, package the launcher:

```bash
uv run launcher build package --version v1.2.3
```

The package name includes the app name, release version, and platform:

```text
dist/MyApp-launcher-v1.2.3-macos-arm64.zip
dist/MyApp-launcher-v1.2.3-macos-x64.zip
dist/MyApp-launcher-v1.2.3-windows-x64.zip
dist/MyApp-launcher-v1.2.3-linux-x64.zip
```

On macOS, `launcher build package` prefers the `.app` bundle and packages it with `ditto`.
Otherwise it packages the PyInstaller directory-style build with Python zip tooling.

Create the release and upload the launcher package:

```bash
uv run launcher release create v1.2.3 --notes RELEASE_NOTES.md
uv run launcher build upload --version v1.2.3
```

`launcher build upload` uploads the current platform package with the provider CLI and updates `packaging/launcher/distribution.yml` only after the upload succeeds.
That file is the source of truth for launcher download URLs used in future release notes.

Launcher artifacts are uploaded only when the launcher executable changes.
That is the canonical workflow.

If you prefer every release to be self-contained, you may build, package, and upload launcher artifacts for every release.
That costs more CI time and signing work, but it makes each release page contain every installer artifact directly.

## Phase 4: Create App Releases

Write user-facing release notes in Markdown, then create the provider release:

```bash
uv run launcher release create v1.2.3 --notes RELEASE_NOTES.md
```

By default, the tag must already exist locally and on the configured remote.
To create a local lightweight tag at `HEAD`, pass `--tag`.
To push the tag before release creation, pass `--push`.
Use `--remote` when the remote is not `origin`.

GitHub release creation uses:

```bash
gh release create v1.2.3 --verify-tag --notes-file <generated-notes>
```

GitLab release creation uses:

```bash
glab release create v1.2.3 --notes-file <generated-notes>
```

Launcher preflights the remote GitLab tag first so `glab` cannot silently create a missing tag from the default branch.

Generated release notes are your notes plus a Launcher-managed download block when launcher download URLs are known.
Local launcher packages for the current version override older URLs from `packaging/launcher/distribution.yml`.

## Phase 5: Build The App Archive

For simple apps, no extra archive config is needed.
`launcher release archive VERSION` creates a zip from tracked files at the requested git ref.

```bash
uv run launcher release archive v1.2.3
```

Before writing the archive, Launcher verifies that the release ref resolves to `HEAD` and that tracked files are clean.
Untracked generated files are allowed so configured build outputs can be included.

For generated assets, configure `release.archive` in `packaging/launcher/application.yml`:

```yaml
release:
  archive:
    build:
      - command: ["npm", "ci"]
        cwd: frontend
      - command: ["npm", "run", "build"]
        cwd: frontend
    include:
      - frontend/dist
      - source: frontend/dist
        destination: my_app/static
```

`build` commands are argv lists run with `shell=False`.
`cwd` is relative to the repository root.
String `include` entries preserve the source path in the archive.
Object `include` entries copy `source` to `destination`, where `destination` is relative to the archive root.

For rare cases, use a Python custom script:

```yaml
release:
  archive:
    custom_script: packaging/launcher/custom_archive.py
```

The custom script is called as `python <script> <version> <archive_path>`.
It must create the requested zip and cannot be combined with `build` or `include`.

## Phase 6: Publish Signed App Update Assets

Create and verify the signed update metadata:

```bash
uv run launcher release sign
uv run launcher release verify
```

The commands infer the archive and version from `dist/` by default.
If more than one archive exists, pass `--archive`.
If the archive filename does not contain the version, pass `--version` to `sign`.

The signed release assets are:

```text
dist/
|-- myapp-v1.2.3.zip
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

Upload the app archive, manifest, and signature:

```bash
uv run launcher release upload
```

GitHub upload uses:

```bash
gh release upload v1.2.3 \
  dist/myapp-v1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig \
  --clobber
```

GitLab upload uses:

```bash
glab release upload v1.2.3 \
  dist/myapp-v1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig \
  --use-package-registry
```

After these files are published, users can open the existing launcher and it will find, verify, install, and start the new app release.
