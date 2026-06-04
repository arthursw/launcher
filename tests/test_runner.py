"""Tests for script runner errors."""

import os
from unittest.mock import MagicMock

from launcher.config import AppConfig
from launcher.runner import RunnerError, ScriptRunner


def test_start_missing_main_script_explains_config_and_archive(tmp_path):
    """Missing configured main script errors should explain what to fix."""
    sources = tmp_path / "sources"
    sources.mkdir()
    config = AppConfig(
        name="MyApp",
        main="main.py",
        path=str(sources),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=None, env=None)  # type: ignore[arg-type]

    try:
        runner.start()
    except RunnerError as e:
        message = str(e)
    else:
        raise AssertionError("RunnerError was not raised")

    assert "Configured main script not found" in message
    assert "main: main.py" in message
    assert str(sources / "myapp-v1.2.3") in message
    assert "Update `main`" in message
    assert "include that file in the release archive" in message


def test_start_uses_inferred_working_directory_and_pythonpath(tmp_path, monkeypatch):
    """A src-layout project should launch with importable project paths."""
    monkeypatch.setenv("PYTHONPATH", "existing")
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    main_script = app_sources / "backend" / "src" / "my_app" / "desktop.py"
    main_script.parent.mkdir(parents=True)
    main_script.write_text("print('hello')")
    (app_sources / "backend" / "pyproject.toml").write_text("[project]\nname='my-app'\n")
    config = AppConfig(
        name="MyApp",
        main="backend/src/my_app/desktop.py",
        path=str(sources),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
        configuration="backend/pyproject.toml",
    )
    process = MagicMock()
    env = MagicMock()
    env.execute_commands.return_value = process
    env_manager = MagicMock()
    env_manager.get_process_logger.return_value = None
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    assert runner.start() == process

    env.execute_commands.assert_called_once()
    call = env.execute_commands.call_args
    assert call.kwargs["commands"] == [f'python -u "{main_script}"']
    assert call.kwargs["wait"] is False
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "backend"
    pythonpath = call.kwargs["popen_kwargs"]["env"]["PYTHONPATH"].split(os.pathsep)
    assert pythonpath == [
        str(app_sources / "backend" / "src"),
        str(app_sources / "backend"),
        "existing",
    ]


def test_start_uses_explicit_working_directory_and_pythonpath(tmp_path, monkeypatch):
    """Explicit launch paths should override inferred import paths."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    main_script = app_sources / "scripts" / "desktop.py"
    main_script.parent.mkdir(parents=True)
    (app_sources / "runtime").mkdir()
    main_script.write_text("print('hello')")
    config = AppConfig(
        name="MyApp",
        main="scripts/desktop.py",
        path=str(sources),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
        working_directory="runtime",
        pythonpath=["lib", "plugins"],
    )
    process = MagicMock()
    env = MagicMock()
    env.execute_commands.return_value = process
    env_manager = MagicMock()
    env_manager.get_process_logger.return_value = None
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    runner.start()

    call = env.execute_commands.call_args
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "runtime"
    assert call.kwargs["popen_kwargs"]["env"]["PYTHONPATH"].split(os.pathsep) == [
        str(app_sources / "lib"),
        str(app_sources / "plugins"),
    ]


def test_ensure_still_running_rejects_immediate_exit(tmp_path):
    """Immediate app exits should be reported as startup failures."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    app_sources.mkdir(parents=True)
    main_script = app_sources / "main.py"
    main_script.write_text("print('hello')")
    config = AppConfig(
        name="MyApp",
        main="main.py",
        path=str(sources),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=None, env=None)  # type: ignore[arg-type]
    process = MagicMock()
    process.poll.return_value = 2
    runner._process = process
    runner._output_lines = ["Traceback", "boom"]

    try:
        runner.ensure_still_running(grace_seconds=0)
    except RunnerError as e:
        message = str(e)
    else:
        raise AssertionError("RunnerError was not raised")

    assert "Application exited immediately" in message
    assert "exit code 2" in message
    assert "main: main.py" in message
    assert str(main_script) in message
    assert "Recent application output" in message
    assert "boom" in message


def test_ensure_still_running_accepts_running_process(tmp_path):
    """A process still running after the grace period is a successful handoff."""
    config = AppConfig(
        name="MyApp",
        main="main.py",
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=None, env=None)  # type: ignore[arg-type]
    process = MagicMock()
    process.poll.return_value = None
    runner._process = process

    runner.ensure_still_running(grace_seconds=0)
