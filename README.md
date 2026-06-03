# Launcher

Launcher helps Python developers ship desktop apps without rebuilding and
re-signing the app for every release.

It adds two useful features to your packaged app:

- **updates and versions:** it finds the app version to run, downloads it,
  verifies it, and keeps track of what is installed;
- **startup UX:** it can show progress while downloading or preparing the
  environment, and it can ask for proxy settings when the network requires them.

PyInstaller or cx-Freeze package the stable launcher. Your real app keeps
shipping as normal GitHub or GitLab releases.

## Why Use This?

Packaging Python apps can be slow and frustrating. A tiny code change often
means building a new executable, testing the bundle again, and redistributing a
large file.

Launcher separates the executable you give to users from the application code
you keep releasing:

1. add Launcher as a dev dependency in your app repo;
2. initialize `packaging/launcher/`;
3. build and sign the launcher executable;
4. publish releases of your app source code;
5. run `launcher release sign` for each app release;
6. users open the launcher;
7. the launcher updates and starts the app.

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
manifest. See [docs/security.md](docs/security.md).

## Minimal Packaging Workflow

In your app repository:

```bash
uv add --dev launcher
uv run launcher init --name MyApp --repository https://github.com/my-org/myapp.git
```

This creates:

```text
packaging/
`-- launcher/
    |-- application.yml
    `-- icon_128x128.png
```

Edit `packaging/launcher/application.yml`, then create the signing key:

```bash
uv run launcher release keygen
```

This writes `launcher-signing-key.pem`, adds it to `.gitignore`, and prints the
public key. Replace `trust.public_key` in
`packaging/launcher/application.yml` with that printed value. Keep the generated
`manifest_url` and `signature_url` if you will upload
`launcher-manifest.yml` and `launcher-manifest.yml.sig` as normal release
assets. If you change `repository` after running `init`, update those two URLs
too, or rerun `init --force` with the real repository. Edit them manually for
custom hosting or custom asset names.

Then build the launcher:

```bash
uv run --with pyinstaller launcher build
```

The launcher build is written under `dist/launcher/`. It is separate from app
release artifacts and only needs to be rebuilt when launcher config, assets, or
tooling change.

For each app release, put the source archive in `dist/` and run:

```bash
uv run launcher release sign
uv run launcher release verify
uv run launcher release upload
```

The release commands use `packaging/launcher/application.yml` by default and
write:

```text
dist/
|-- launcher-manifest.yml
`-- launcher-manifest.yml.sig
```

Upload those two files as release assets. `upload` uses the official GitHub or
GitLab CLI if it is installed and already authenticated.

## Learn The Pieces

- [Packaging guide](docs/packaging.md): how to build a launcher for your app.
- [Configuration guide](docs/configuration.md): what goes in
  `packaging/launcher/application.yml`.
- [Security guide](docs/security.md): why signed manifests are needed.

## Developing Launcher Itself

```bash
uv sync
uv run pytest
uv run ruff check .
```

Run from source:

```bash
uv run launcher run -c packaging/launcher/application.yml
```
