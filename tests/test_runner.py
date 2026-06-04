"""Tests for script runner errors."""

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
