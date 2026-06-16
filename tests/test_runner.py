"""Tests for script runner errors."""

from unittest.mock import MagicMock

from launcher.config import AppConfig, EntryPointConfig
from launcher.paths import get_runtime_data_dir
from launcher.runner import RunnerError, ScriptRunner


def test_start_missing_script_entrypoint_explains_config_and_archive(tmp_path):
    """Missing configured script entrypoint errors should explain what to fix."""
    sources = tmp_path / "sources"
    sources.mkdir()
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
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

    assert "Configured script entrypoint not found" in message
    assert "entrypoint.script: main.py" in message
    assert str(sources / "myapp-v1.2.3") in message
    assert "Update `entrypoint.script`" in message
    assert "include that file in the release archive" in message


def test_start_uses_inferred_working_directory_and_pythonpath(tmp_path):
    """A src-layout project should launch with importable project paths."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    main_script = app_sources / "backend" / "src" / "my_app" / "desktop.py"
    main_script.parent.mkdir(parents=True)
    main_script.write_text("print('hello')")
    (app_sources / "backend" / "pyproject.toml").write_text("[project]\nname='my-app'\n")
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="backend/src/my_app/desktop.py"),
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
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.kwargs["commands"] == [f'python -u "{bootstrap_path}"']
    assert call.kwargs["wait"] is False
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "backend"
    assert "env" not in call.kwargs["popen_kwargs"]
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "backend" / "src")) in bootstrap
    assert repr(str(app_sources / "backend")) in bootstrap
    assert repr(str(main_script.parent)) in bootstrap
    assert f"sys.argv = {[str(main_script)]!r}" in bootstrap
    assert f"runpy.run_path({str(main_script)!r}, run_name='__main__')" in bootstrap


def test_start_uses_explicit_working_directory_and_pythonpath(tmp_path):
    """Explicit launch paths should override inferred import paths."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    main_script = app_sources / "scripts" / "desktop.py"
    main_script.parent.mkdir(parents=True)
    (app_sources / "runtime").mkdir()
    main_script.write_text("print('hello')")
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="scripts/desktop.py"),
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
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.kwargs["commands"] == [f'python -u "{bootstrap_path}"']
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "runtime"
    assert "env" not in call.kwargs["popen_kwargs"]
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "lib")) in bootstrap
    assert repr(str(app_sources / "plugins")) in bootstrap


def test_start_module_entrypoint_uses_run_module_and_args(tmp_path):
    """Module entrypoints should run with python -m style argv."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    (app_sources / "backend" / "src" / "my_app").mkdir(parents=True)
    (app_sources / "backend" / "src" / "my_app" / "__main__.py").write_text("print('hello')")
    (app_sources / "backend" / "pyproject.toml").write_text("[project]\nname='my-app'\n")
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(
            mode="module",
            module="my_app",
            args=["--desktop", "--port", "8765"],
        ),
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

    runner.start()

    call = env.execute_commands.call_args
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.kwargs["commands"] == [f'python -u "{bootstrap_path}"']
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "backend"
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "backend" / "src")) in bootstrap
    assert "runpy.run_module('my_app', run_name='__main__', alter_sys=True)" in bootstrap
    assert "sys.argv = ['my_app', '--desktop', '--port', '8765']" in bootstrap


def test_start_project_entrypoint_runs_installed_command(tmp_path):
    """Project entrypoints should run the installed console command."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    (app_sources / "backend").mkdir(parents=True)
    (app_sources / "backend" / "pyproject.toml").write_text("[project]\nname='my-app'\n")
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(
            mode="project",
            command="my-app-gui",
            args=["--port", "8765"],
        ),
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

    runner.start()

    call = env.execute_commands.call_args
    assert call.kwargs["commands"] == ["my-app-gui --port 8765"]
    assert call.kwargs["popen_kwargs"]["cwd"] == app_sources / "backend"


def test_ensure_still_running_rejects_immediate_exit(tmp_path):
    """Immediate app exits should be reported as startup failures."""
    sources = tmp_path / "sources"
    app_sources = sources / "myapp-v1.2.3"
    app_sources.mkdir(parents=True)
    main_script = app_sources / "main.py"
    main_script.write_text("print('hello')")
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
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
    assert "entrypoint.script: main.py" in message
    assert str(app_sources) in message
    assert "Recent application output" in message
    assert "boom" in message


def test_ensure_still_running_accepts_running_process(tmp_path):
    """A process still running after the grace period is a successful handoff."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=None, env=None)  # type: ignore[arg-type]
    process = MagicMock()
    process.poll.return_value = None
    runner._process = process

    runner.ensure_still_running(grace_seconds=0)
