# Configuration Guide

Each packaged launcher includes one YAML file describing the app it should run.
In an app repository, the default location is
`packaging/launcher/application.yml`.

## Minimal Example

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
main: main.py
path: "."
auto_update: true
configuration: pyproject.toml
# extras:
#   - desktop

trust:
  mode: signed_manifest
  # Replace this with the public key printed by: launcher release keygen
  public_key: "<base64-ed25519-public-key>"
  # These default URLs match the manifest and signature produced by
  # launcher release sign and uploaded by launcher release upload.
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

## Main Fields

- `name`: display name of your app. Also used to name local data folders.
- `repository`: GitHub or GitLab repository containing your app.
- `gitlab_project_id`: optional numeric GitLab project id. Use this for GitLab
  instances where the project path cannot be resolved by the public API.
- `main`: Python file to run inside the downloaded app sources.
- `path`: where app sources are stored on the user's machine. Relative paths
  are resolved inside the launcher's per-app runtime data directory, so the
  generated `path: "."` is portable across platforms.
- `auto_update`: when true, Launcher checks the latest release.
- `configuration`: dependency file in your app sources, relative to the
  downloaded repository root. The file must exist. Set `configuration: null`
  only for apps that intentionally have no dependency config file.
- `extras`: optional dependency groups to install from `configuration`.
- `working_directory`: optional app launch directory, relative to the downloaded
  repository root.
- `pythonpath`: optional list of import paths to prepend before starting the
  app, relative to the downloaded repository root.

If your app code lives below the repository root, use paths from the repository
root:

```yaml
main: backend/src/my_app/desktop.py
configuration: backend/pyproject.toml
extras:
  - desktop
```

This is equivalent to installing the dependency file with the optional
`desktop` group. For a `pyproject.toml` managed by `uv`, use the same group name
you would pass to `uv sync --extra desktop`.

By default, Launcher starts the app from the directory containing
`configuration`. In the example above, the working directory is `backend/`.
Launcher also prepends that directory to `PYTHONPATH`, and prepends
`backend/src` when that folder exists. That makes common `src/` Python projects
importable without extra config.

For unusual layouts, override those launch paths explicitly:

```yaml
working_directory: backend
pythonpath:
  - backend/src
  - backend/plugins
```

If your repository cannot be inferred automatically, you can use explicit API
fields instead of `repository`:

```yaml
api: https://api.github.com
releases_endpoint: /repos/my-org/myapp/releases/latest
archive_endpoint: /repos/my-org/myapp/zipball/{ref}
```

For GitLab, Launcher uses API v4. A project path such as
`group/myapp` is sent to GitLab as `group%2Fmyapp`, which is the normal GitLab
API format. If GitLab returns `404 Project Not Found`, check that the project is
publicly visible to the packaged app. For private or restricted self-hosted
GitLab projects, prefer the numeric project id:

```yaml
repository: https://gitlab.example.org/my-group/myapp
gitlab_project_id: "123456"
```

## Security Fields

The `trust` section tells Launcher how to verify downloaded app sources.
Generate the key with:

```bash
uv run launcher release keygen
```

The command writes `launcher-signing-key.pem`, adds it to `.gitignore`, and
prints the `public_key` value. Replace the placeholder in
`packaging/launcher/application.yml` with the printed value; `keygen` does not
edit the config file.

```yaml
trust:
  mode: signed_manifest
  # Replace this with the public key printed by: launcher release keygen
  public_key: "<base64-ed25519-public-key>"
  # These default URLs match the manifest and signature produced by
  # launcher release sign and uploaded by launcher release upload.
  manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
```

This is required because Launcher downloads Python code and runs it. See
[security.md](security.md) for the explanation.

`manifest_url` and `signature_url` are the runtime download URLs for
`launcher-manifest.yml` and `launcher-manifest.yml.sig`. The defaults match the
files produced by `launcher release sign` and uploaded by
`launcher release upload`. If you change `repository` after running
`launcher init`, update these URLs too, or rerun `launcher init --force` with
the real repository. Edit them manually for custom hosting, custom asset paths,
or renamed files. `{version}` is replaced with the release tag the launcher is
trying to run.

## Optional Fields

```yaml
version: v1.2.3
working_directory: backend
pythonpath:
  - backend/src
install: install.py
reinstall_on_update: false
gui_timeout: 3
init_message: "Initialized"
init_timeout: 30
```

- `version`: fixed version to use when `auto_update` is false.
- `working_directory`: override the inferred app launch directory.
- `pythonpath`: override inferred Python import paths.
- `install`: optional Python install script in your app sources.
- `reinstall_on_update`: rerun the install script after an update.
- `gui_timeout`: seconds before showing a progress window.
- `init_message`: optional text printed by your app when it is ready.
- `init_timeout`: how long to wait for `init_message` when it is configured.

Without `init_message`, Launcher starts the app, checks that it does not exit
immediately, then exits and leaves the app running.

With `init_message`, Launcher keeps watching the app output until that text is
printed. If the timeout expires, the user can keep waiting, reinstall the local
environment, or exit. Reinstalling may fix a corrupted local environment, but it
will not fix a broken release; publish a fixed release and restart Launcher in
that case.

## Runtime State

Launcher does not edit the packaged YAML file during normal use.

Values that change, such as the installed version, dependency hash, and proxy
settings, are saved in the user's app data folder:

- macOS: `~/Library/Application Support/<AppName>/launcher-state.yml`
- Windows: `%APPDATA%\<AppName>\launcher-state.yml`
- Linux: `~/.local/state/<AppName>/launcher-state.yml`

Downloaded app sources are stored under the configured `path`. With the default
`path: "."`, sources are stored beside the launcher state in the same per-app
runtime data directory, with one subfolder per version:

- macOS: `~/Library/Application Support/<AppName>/<appname>-<version>/`
- Windows: `%APPDATA%\<AppName>\<appname>-<version>\`
- Linux: `~/.local/state/<AppName>/<appname>-<version>/`

The launcher never writes downloaded sources inside the signed `.app` bundle.

Proxy passwords are not stored in YAML. If the user chooses to remember a proxy
password, Launcher stores it in the operating system keychain.
