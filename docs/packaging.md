# Packaging

The package entry point is `launcher.main:main`. The repository-root `main.py`
is a thin wrapper for source and legacy execution.

PyInstaller specs should analyze the generic launcher script:

```python
a = Analysis(
    ["main.py"],
    datas=[
        ("myapp/myapp.yml", "myapp"),
        ("myapp/icon_128x128.png", "resources/"),
    ],
)
```

Do not create app-specific Python wrappers or pass permanent app arguments in
`Analysis([...])`.

## Config Lookup

An explicit `--config` path wins. Without it, the launcher checks:

1. `LAUNCHER_CONFIG`;
2. `application.yml` in the current working directory;
3. frozen sidecar configs beside the executable:
   `application.yml`, `{app}.yml`, `{app}/{app}.yml`;
4. the same names inside the PyInstaller bundle data;
5. source-mode `application.yml` beside the repository root wrapper.

## Example Build

```bash
uv run --with pyinstaller pyinstaller galaxy_launcher.spec
```

On macOS, distribute the generated app bundle. On Windows and Linux, distribute
the onedir output.
