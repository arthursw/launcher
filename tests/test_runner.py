"""Tests for script runner errors."""

import asyncio
from unittest.mock import MagicMock

import pytest
from wetlands import ManagedProcessResult, OutputEvent, OutputStream, ProcessError

from launcher.config import AppConfig, EntryPointConfig
from launcher.paths import get_runtime_data_dir
from launcher.runner import MANAGED_PROCESS_OUTPUT_LIMIT, InitTimeoutError, RunnerError, ScriptRunner


async def _no_output_events():
    if False:
        yield None


def _managed_process_mock() -> MagicMock:
    process = MagicMock()
    process.events.return_value = _no_output_events()
    return process


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
    assert str(sources / "sources" / "myapp-v1.2.3") in message
    assert "Update `entrypoint.script`" in message
    assert "include that file in the release archive" in message


def test_start_uses_inferred_working_directory_and_pythonpath(tmp_path):
    """A src-layout project should launch with importable project paths."""
    sources = tmp_path / "sources"
    app_sources = sources / "sources" / "myapp-v1.2.3"
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
    process = _managed_process_mock()
    env = MagicMock()
    env.spawn.return_value = process
    env_manager = MagicMock()
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    assert runner.start() == process

    env.spawn.assert_called_once()
    call = env.spawn.call_args
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.args == (["python", "-u", str(bootstrap_path)],)
    assert call.kwargs["cwd"] == app_sources / "backend"
    assert call.kwargs["output_limit"] == MANAGED_PROCESS_OUTPUT_LIMIT
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "backend" / "src")) in bootstrap
    assert repr(str(app_sources / "backend")) in bootstrap
    assert repr(str(main_script.parent)) in bootstrap
    assert f"sys.argv = {[str(main_script)]!r}" in bootstrap
    assert f"runpy.run_path({str(main_script)!r}, run_name='__main__')" in bootstrap


def test_start_uses_explicit_working_directory_and_pythonpath(tmp_path):
    """Explicit launch paths should override inferred import paths."""
    sources = tmp_path / "sources"
    app_sources = sources / "sources" / "myapp-v1.2.3"
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
    process = _managed_process_mock()
    env = MagicMock()
    env.spawn.return_value = process
    env_manager = MagicMock()
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    runner.start()

    call = env.spawn.call_args
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.args == (["python", "-u", str(bootstrap_path)],)
    assert call.kwargs["cwd"] == app_sources / "runtime"
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "lib")) in bootstrap
    assert repr(str(app_sources / "plugins")) in bootstrap


def test_start_module_entrypoint_uses_run_module_and_args(tmp_path):
    """Module entrypoints should run with python -m style argv."""
    sources = tmp_path / "sources"
    app_sources = sources / "sources" / "myapp-v1.2.3"
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
    process = _managed_process_mock()
    env = MagicMock()
    env.spawn.return_value = process
    env_manager = MagicMock()
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    runner.start()

    call = env.spawn.call_args
    bootstrap_path = get_runtime_data_dir("MyApp") / "launcher-run.py"
    assert call.args == (["python", "-u", str(bootstrap_path)],)
    assert call.kwargs["cwd"] == app_sources / "backend"
    bootstrap = bootstrap_path.read_text()
    assert repr(str(app_sources / "backend" / "src")) in bootstrap
    assert "runpy.run_module('my_app', run_name='__main__', alter_sys=True)" in bootstrap
    assert "sys.argv = ['my_app', '--desktop', '--port', '8765']" in bootstrap


def test_start_project_entrypoint_runs_installed_command(tmp_path):
    """Project entrypoints should run the installed console command."""
    sources = tmp_path / "sources"
    app_sources = sources / "sources" / "myapp-v1.2.3"
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
    process = _managed_process_mock()
    env = MagicMock()
    env.spawn.return_value = process
    env_manager = MagicMock()
    runner = ScriptRunner(config, env_manager=env_manager, env=env)

    runner.start()

    call = env.spawn.call_args
    assert call.args == (["my-app-gui", "--port", "8765"],)
    assert call.kwargs["cwd"] == app_sources / "backend"


def test_ensure_still_running_rejects_immediate_exit(tmp_path):
    """Immediate app exits should be reported as startup failures."""
    sources = tmp_path / "sources"
    app_sources = sources / "sources" / "myapp-v1.2.3"
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
    process.returncode = 2
    process.wait.return_value = ManagedProcessResult(
        argv=("python", "main.py"),
        returncode=2,
        stdout="Traceback\nboom\n",
        stderr="",
        started_at=1.0,
        ended_at=2.0,
    )
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
    """A process still running after the grace period has started successfully."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=None, env=None)  # type: ignore[arg-type]
    process = MagicMock()
    process.returncode = None
    runner._process = process

    runner.ensure_still_running(grace_seconds=0)


def test_wait_for_init_uses_managed_process_output(tmp_path):
    """Wetlands managed output should detect an initialization message."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
        init_message="READY",
        init_timeout=0.5,
    )
    runner = ScriptRunner(config, env_manager=MagicMock(), env=MagicMock())
    process = MagicMock()
    process.wait_for_line.return_value = OutputEvent(0, 1.0, OutputStream.STDOUT, "READY\n")
    runner._process = process

    assert runner.wait_for_init() is True
    process.wait_for_line.assert_called_once()
    assert process.wait_for_line.call_args.kwargs["timeout"] == 0.5


def test_wait_for_init_translates_terminal_process_errors(tmp_path):
    """Wetlands terminal errors should remain actionable launcher errors."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
        init_message="READY",
        init_timeout=1,
    )
    runner = ScriptRunner(config, env_manager=MagicMock(), env=MagicMock())
    process = MagicMock()
    process.wait_for_line.side_effect = EOFError
    process.wait.side_effect = ProcessError(
        "output limit exceeded",
        argv=("python", "main.py"),
        environment="my-app",
        generation_id="generation-1",
    )
    runner._process = process

    with pytest.raises(InitTimeoutError, match="failed before initialization completed"):
        runner.wait_for_init()


def test_managed_output_events_preserve_stderr_and_write_log(tmp_path):
    """Managed stdout and stderr events should remain distinguishable in launcher logs."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    runner = ScriptRunner(config, env_manager=MagicMock(), env=MagicMock())
    process = MagicMock()

    async def events():
        yield OutputEvent(0, 1.0, OutputStream.STDOUT, "ready\n")
        yield OutputEvent(1, 2.0, OutputStream.STDERR, "warning\n")

    process.events.return_value = events()
    output_path = tmp_path / "app.log"
    callbacks = []

    asyncio.run(runner._consume_output_events(output_path, process, callbacks.append))

    assert runner.output_lines == ["ready", "[stderr] warning"]
    assert callbacks == ["ready", "[stderr] warning"]
    assert output_path.read_text() == "ready\n[stderr] warning\n"


def test_run_install_script_uses_managed_environment(tmp_path):
    """Install scripts should run to completion through Wetlands."""
    sources = tmp_path / "sources" / "testapp-v1.0.0"
    sources.mkdir(parents=True)
    install_script = sources / "install.py"
    install_script.write_text("print('installed')")
    config = AppConfig(
        name="TestApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/testapp.git",
        version="v1.0.0",
        configuration=None,
        install="install.py",
    )
    result = ManagedProcessResult(
        argv=("python", str(install_script)),
        returncode=0,
        stdout="installed\n",
        stderr="",
        started_at=1.0,
        ended_at=2.0,
    )
    environment = MagicMock()
    environment.run.return_value = result
    runner = ScriptRunner(config, env_manager=MagicMock(), env=environment)

    assert runner.run_install_script() is True
    environment.run.assert_called_once_with(
        ["python", str(install_script)],
        cwd=config.working_directory_path,
        output_limit=MANAGED_PROCESS_OUTPUT_LIMIT,
        check=False,
    )
    assert runner.output_lines == ["installed"]


def test_wait_for_exit_releases_the_managed_process(tmp_path):
    """Natural application exit should complete Wetlands cleanup."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    result = ManagedProcessResult(
        argv=("python", "main.py"),
        returncode=0,
        stdout="",
        stderr="",
        started_at=1.0,
        ended_at=2.0,
    )
    process = MagicMock()
    process.wait.return_value = result
    runner = ScriptRunner(config, env_manager=MagicMock(), env=MagicMock())
    runner._process = process

    assert runner.wait_for_exit() == 0
    process.wait.assert_called_once_with(check=False)
    process.close.assert_called_once_with()
    assert runner._process is None


def test_stop_retains_process_when_cleanup_can_be_retried(tmp_path):
    """A Wetlands cleanup error should leave the process available for retry."""
    config = AppConfig(
        name="MyApp",
        entrypoint=EntryPointConfig(mode="script", script="main.py"),
        path=str(tmp_path),
        repository="https://github.com/my-org/myapp.git",
        version="v1.2.3",
    )
    process = MagicMock()
    process.close.side_effect = ProcessError(
        "cleanup failed",
        argv=("python", "main.py"),
        environment="my-app",
        generation_id="generation-1",
    )
    runner = ScriptRunner(config, env_manager=MagicMock(), env=MagicMock())
    runner._process = process

    with pytest.raises(RunnerError, match="Failed to clean up application process"):
        runner.stop()

    assert runner._process is process
