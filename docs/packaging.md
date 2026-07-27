# Packaging Guide

This guide describes the release workflow for an app repository that uses Launcher.

Launcher is the stable executable users install.
Your app is the versioned archive Launcher downloads from GitHub or GitLab releases.

## Phase 1: Initialize Config

Add Launcher as a development dependency:

```bash
uv add --dev wetlands-launcher
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

Add `app.ico` for a native Windows executable and window icon, and add `app.icns` for a native macOS app-bundle icon.
Launcher bundles every available standard icon and applies the appropriate icon to its Tkinter or Qt window at runtime; `icon_128x128.png` is the portable window-icon fallback on macOS and Linux.

Edit `packaging/launcher/application.yml` for your app:

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
entrypoint:
  mode: script
  script: main.py
auto_update: true
configuration: pyproject.toml
release:
  # Optional. The default release tag is the exact project version.
  # tag_template: "v{version}"

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
For TOML configuration files with a static `[project].version`, release commands infer the exact release tag from that value.
The default template is `{version}`; configure `release.tag_template: "v{version}"` only when the repository deliberately uses prefixed tags.
An explicit version/tag argument remains available when project inference is unavailable, and must match when both values exist.

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
The private key is not needed to build, package, or upload launcher executables on another platform.
Copy it to another machine only if that machine will run `launcher release sign`, and transfer it through secure secret storage rather than Git.
Operating-system signing uses separate Apple or Microsoft signing credentials.

## Phase 3: Build, Sign, And Package The Launcher

Build the launcher executable:

```bash
uv run --with pyinstaller launcher build
```

Supply PyInstaller through the same `uv run` invocation so it can import the installed `launcher` package.
The build command deliberately ignores a `pyinstaller` executable that is present only on `PATH`, because it may belong to another Python environment and produce an incomplete launcher.

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
uv run launcher build package
```

The package name includes the app name, exact release tag, and platform:

```text
dist/MyApp-launcher-1.2.3-macos-arm64.zip
dist/MyApp-launcher-1.2.3-macos-x64.zip
dist/MyApp-launcher-1.2.3-windows-x64.zip
dist/MyApp-launcher-1.2.3-linux-x64.zip
```

On macOS, `launcher build package` prefers the `.app` bundle and packages it with `ditto`.
Otherwise it packages the PyInstaller directory-style build with Python zip tooling.

The examples use `--notes-text` for short inline release notes.
For longer notes, create a Markdown file such as `RELEASE_NOTES.md` and use `--notes RELEASE_NOTES.md` instead.
Both `release create` and `release update-notes` require exactly one of `--notes-text` or `--notes`.

Launcher artifacts are uploaded only when the launcher executable changes.
That is the canonical workflow.

If you prefer every release to be self-contained, you may build, package, and upload launcher artifacts for every release.
That costs more CI time and signing work, but it makes each release page contain every installer artifact directly.

Build every platform package from the same clean release commit.
Do not upload launcher packages yet: application archive creation must run while the release tag still points to `HEAD`.

## Phase 4: Create App Releases

Create the provider release with user-facing notes if it does not already exist:

```bash
uv run launcher release create --tag --push --notes-text "Release 1.2.3"
```

Create each release only once.

Before creating a release, Launcher verifies that tracked files and the index are clean.
Commit, stash, or revert tracked changes first so the release tag and the later source archive cannot silently omit local work.
Untracked files are allowed.

By default, the tag must already exist locally and on the configured remote.
To create a local lightweight tag at `HEAD`, pass `--tag`.
To push the tag before release creation, pass `--push`.
Use `--remote` when the remote is not `origin`.

GitHub release creation uses:

```bash
gh release create 1.2.3 --verify-tag --notes-file <generated-notes>
```

GitLab release creation uses:

```bash
glab release create 1.2.3 --notes-file <generated-notes>
```

Launcher preflights the remote GitLab tag first so `glab` cannot silently create a missing tag from the default branch.

Generated release notes are your notes plus a Launcher-managed download block when launcher download URLs are known.
Local launcher packages for the current version override older URLs from `packaging/launcher/distribution.yml`.

## Phase 5: Build The App Archive

For simple apps, no extra archive config is needed.
`launcher release archive` creates a zip from tracked files at the inferred release tag.

```bash
uv run launcher release archive
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

`sign` selects the exact standard application archive for the resolved tag, even when launcher packages are also present in `dist/`.
For a custom application archive name, pass both `--archive` and `--version`; the explicit tag must match project metadata when inference is available.
`verify` and `upload` use the exact archive name recorded in the signed manifest.

The signed release assets are:

```text
dist/
|-- myapp-1.2.3.zip
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

Upload the app archive, manifest, and signature:

```bash
uv run launcher release upload
```

GitHub upload uses:

```bash
gh release upload 1.2.3 \
  dist/myapp-1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig \
  --clobber
```

GitLab upload uses:

```bash
glab release upload 1.2.3 \
  dist/myapp-1.2.3.zip \
  dist/launcher-manifest.yml \
  dist/launcher-manifest.yml.sig \
  --use-package-registry
```

After these files are published, users can open the existing launcher and it will find, verify, install, and start the new app release.

## Phase 7: Upload Launcher Packages

After the application archive is published, upload each signed launcher package:

```bash
uv run launcher build upload
```

The command infers the tag and platform from project metadata and the standard package filename, uploads the package, and updates `packaging/launcher/distribution.yml` only after success.
Commit and push that metadata change before uploading from another machine so platform updates do not overwrite each other.

After the final platform upload, update the release notes once:

```bash
uv run launcher release update-notes --notes-text "Release 1.2.3"
```

`release update-notes` regenerates the managed download block from `distribution.yml` and is safe to rerun.
