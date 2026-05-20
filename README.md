# Launcher

Launcher helps Python developers ship desktop apps without rebuilding and
re-signing the app for every release.

It adds two useful features to your packaged app:

- **updates and versions:** it finds the app version to run, downloads it,
  verifies it, and keeps track of what is installed;
- **startup UX:** it can show progress while downloading or preparing the
  environment, and it can ask for proxy settings when the network requires them.

So tools like PyInstaller or cx-Freeze are used for the stable launcher, not for
every version of your application. On platforms that require code signing, such
as macOS, this also avoids repeating the signing process for every minor update.

## Why Use This?

Packaging Python apps can be slow and frustrating. A tiny code change often
means building a new executable, testing the bundle again, and redistributing a
large file.

Launcher separates the executable you give to users from the application code
you keep releasing. Your release process becomes closer to normal Python
development:

1. build and sign the launcher;
2. publish releases of your app source code;
3. run `launcher-release sign` for each release;
4. users open the launcher;
5. the launcher updates and starts the app.

This is useful when your users need a simple executable, but you want to keep
shipping app updates through GitHub or GitLab releases. Users still get a normal
app icon to open, and you still get controlled updates, version tracking,
progress feedback, and proxy handling.

## What Happens When The User Opens It?

Launcher:

1. reads the app configuration packaged with the launcher;
2. checks which app version should run;
3. securely downloads and verifies the app sources; (*)
4. shows progress if startup takes time;
5. asks for proxy settings if it cannot reach the internet;
6. creates or updates the Python environment;
7. starts your app;
8. exits without killing the app.

(*) Security note: the launcher does not blindly run downloaded code. Each
release must provide a signed manifest. The launcher verifies that signature,
then verifies that the downloaded archive matches the hash written in the signed
manifest. See [docs/security.md](docs/security.md) for a gentle explanation.

## The Files You Create

For each app, create a small folder with its launcher config and icons:

```text
launcher/
|-- main.py
|-- myapp/
|   |-- myapp.yml
|   |-- myapp.icns
|   `-- icon_128x128.png
`-- myapp_launcher.spec
```

`myapp.yml` tells Launcher what app to download and how to start it.

First, create the signing key:

```bash
uv run launcher-release keygen
```

The command creates `launcher-signing-key.pem`, adds it to `.gitignore`, and
prints the public key to put in `myapp.yml`.

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

The PyInstaller spec packages the generic launcher and includes `myapp.yml` as
data:

```python
a = Analysis(
    ["main.py"],
    datas=[
        ("myapp/myapp.yml", "myapp"),
        ("myapp/icon_128x128.png", "resources"),
    ],
)
```

Build it:

```bash
uv run --with pyinstaller pyinstaller myapp_launcher.spec
```

For each app release, put the source archive in `dist/` and sign it:

```bash
uv run launcher-release sign
uv run launcher-release verify
uv run launcher-release upload
```

By default, the command writes:

```text
dist/
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

Upload those two files as release assets.

`upload` uses the official GitHub or GitLab CLI if it is installed and already
authenticated. Install instructions are on the project pages:
[GitHub CLI](https://github.com/cli/cli#installation) and
[GitLab CLI](https://gitlab.com/gitlab-org/cli/#installation). You can also
upload `launcher-manifest.yml` and `launcher-manifest.yml.sig` manually from the
GitHub or GitLab release page; see [docs/security.md](docs/security.md).

The user receives the generated app or executable. The real app can then update
through normal releases.

## Learn The Pieces

- [Packaging guide](docs/packaging.md): how to build a launcher for your app.
- [Configuration guide](docs/configuration.md): what goes in `myapp.yml`.
- [Security guide](docs/security.md): why signed manifests are needed.

## Developing Launcher Itself

```bash
uv sync
uv run pytest
uv run ruff check .
```

Run from source:

```bash
uv run python main.py -c myapp/myapp.yml
```
