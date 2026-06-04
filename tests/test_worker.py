"""Tests for the worker module."""

import queue
import pytest
from unittest.mock import patch, MagicMock

from launcher.worker import (
    LauncherWorker,
    WorkerEvent,
    GUIResponse,
    EventType,
    ResponseType,
    create_queues,
)
from launcher.config import ProxySettings
from launcher.state import LauncherState
from launcher.updater import HTTPStatusError, UpdaterError


@pytest.fixture
def queues():
    """Create event and response queues."""
    return create_queues()


@pytest.fixture
def mock_config_file(tmp_path):
    """Create a mock config file."""
    import yaml
    config_data = {
        "name": "TestApp",
        "main": "main.py",
        "path": str(tmp_path / "apps"),
        "repository": "git@github.com:owner/repo.git",
        "auto_update": False,
        "version": "testapp-v1.0.0",
    }
    config_file = tmp_path / "application.yml"
    config_file.write_text(yaml.dump(config_data))

    # Create the sources directory with main.py
    sources_dir = tmp_path / "apps" / "testapp-v1.0.0"
    sources_dir.mkdir(parents=True)
    (sources_dir / "main.py").write_text("print('hello')")
    (sources_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    return config_file


class TestCreateQueues:
    """Tests for create_queues function."""

    def test_creates_two_queues(self):
        """Test that create_queues returns two Queue objects."""
        event_queue, response_queue = create_queues()
        assert isinstance(event_queue, queue.Queue)
        assert isinstance(response_queue, queue.Queue)


class TestWorkerEvent:
    """Tests for WorkerEvent dataclass."""

    def test_log_event(self):
        """Test creating a log event."""
        event = WorkerEvent(type=EventType.LOG, message="Test message")
        assert event.type == EventType.LOG
        assert event.message == "Test message"

    def test_progress_event(self):
        """Test creating a progress event."""
        event = WorkerEvent(
            type=EventType.PROGRESS,
            current=50,
            total=100,
            message="Downloading..."
        )
        assert event.type == EventType.PROGRESS
        assert event.current == 50
        assert event.total == 100

    def test_proxy_required_event(self):
        """Test creating a proxy required event."""
        event = WorkerEvent(type=EventType.PROXY_REQUIRED, request_id="abc123")
        assert event.type == EventType.PROXY_REQUIRED
        assert event.request_id == "abc123"


class TestGUIResponse:
    """Tests for GUIResponse dataclass."""

    def test_proxy_settings_response(self):
        """Test creating a proxy settings response."""
        response = GUIResponse(
            type=ResponseType.PROXY_SETTINGS,
            request_id="abc123",
            data={"http": "http://proxy:8080", "https": "https://proxy:8080"}
        )
        assert response.type == ResponseType.PROXY_SETTINGS
        assert response.request_id == "abc123"
        assert response.data["http"] == "http://proxy:8080"

    def test_init_timeout_response(self):
        """Test creating an init timeout response."""
        response = GUIResponse(
            type=ResponseType.INIT_TIMEOUT_RESPONSE,
            request_id="abc123",
            data={"action": "wait"}
        )
        assert response.type == ResponseType.INIT_TIMEOUT_RESPONSE
        assert response.data["action"] == "wait"

    def test_proxy_settings_response_with_ssl_cert_file(self):
        """Test creating a proxy settings response with ssl_cert_file."""
        response = GUIResponse(
            type=ResponseType.PROXY_SETTINGS,
            request_id="abc123",
            data={
                "http": "http://proxy:8080",
                "https": None,
                "ssl_cert_file": "/path/to/cert.pem",
            }
        )
        assert response.type == ResponseType.PROXY_SETTINGS
        assert response.data["ssl_cert_file"] == "/path/to/cert.pem"


class TestLauncherWorker:
    """Tests for LauncherWorker class."""

    def test_worker_creation(self, mock_config_file, queues):
        """Test worker creation."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)

        assert worker.config_path == mock_config_file
        assert worker.event_queue == event_queue
        assert worker.response_queue == response_queue
        assert not worker.is_running()

    def test_worker_start_stop(self, mock_config_file, queues):
        """Test worker start and stop."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)

        with patch('launcher.worker.LauncherEnvironmentManager') as mock_env_manager:
            # Mock the environment manager
            mock_instance = MagicMock()
            mock_env_manager.return_value = mock_instance
            mock_instance.get_or_create_environment.return_value = MagicMock()

            worker.start()
            assert worker.is_running()

            worker.stop()
            # Give it a moment to stop
            import time
            time.sleep(0.5)

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    def test_worker_sends_log_events(
        self,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_file,
        queues
    ):
        """Test that worker sends log events."""
        event_queue, response_queue = queues

        # Mock update_sources to return immediately
        mock_update_sources.return_value = (False, "testapp-v1.0.0")

        # Mock environment manager
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.get_or_create_environment.return_value = MagicMock()

        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker.start()

        # Wait a bit for events
        import time
        time.sleep(0.5)

        # Collect events
        events = []
        while True:
            try:
                event = event_queue.get_nowait()
                events.append(event)
            except queue.Empty:
                break

        worker.stop()

        # Should have received log events
        log_events = [e for e in events if e.type == EventType.LOG]
        assert len(log_events) > 0

    def test_worker_handles_missing_config(self, tmp_path, queues):
        """Test worker handles missing config file."""
        event_queue, response_queue = queues
        nonexistent_config = tmp_path / "nonexistent.yml"

        worker = LauncherWorker(nonexistent_config, event_queue, response_queue)
        worker.start()

        # Wait for error event
        import time
        time.sleep(0.5)

        # Collect events
        events = []
        while True:
            try:
                event = event_queue.get_nowait()
                events.append(event)
            except queue.Empty:
                break

        worker.stop()

        # Should have received an error event
        error_events = [e for e in events if e.type == EventType.ERROR]
        assert len(error_events) > 0

    def test_stop_after_success_does_not_terminate_child_or_env(self, mock_config_file, queues):
        """Successful initialization transfers process ownership to the app."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker._completed = True
        worker._runner = MagicMock()
        worker._env_manager = MagicMock()

        worker.stop()

        worker._runner.stop.assert_not_called()
        worker._env_manager.exit.assert_not_called()

    def test_stop_before_success_terminates_child_and_env(self, mock_config_file, queues):
        """Cancellation or failure cleans up launcher-owned resources."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker._runner = MagicMock()
        worker._env_manager = MagicMock()

        worker.stop()

        worker._runner.stop.assert_called_once()
        worker._env_manager.exit.assert_called_once()

    def test_http_status_error_does_not_request_proxy(self, mock_config_file, queues):
        """HTTP 404/401-style update errors should not trigger proxy fallback."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker._config = MagicMock(proxy_servers=ProxySettings())
        worker._request_proxy = MagicMock()

        def fail_with_http_status(*args, **kwargs):
            raise HTTPStatusError(404, "https://example.com/releases", "Project Not Found")

        with pytest.raises(HTTPStatusError):
            worker._try_with_proxy_fallback("Update check", fail_with_http_status)

        worker._request_proxy.assert_not_called()

    def test_init_timeout_message_explains_reinstall_limits(self, mock_config_file, queues):
        """Readiness timeout prompt should explain what reinstall can fix."""
        event_queue, response_queue = queues
        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker._config = MagicMock(init_timeout=30)
        response_queue.put(
            GUIResponse(
                type=ResponseType.INIT_TIMEOUT_RESPONSE,
                request_id="ignored",
                data={"action": "exit"},
            )
        )

        worker._request_init_timeout_action()
        event = event_queue.get_nowait()

        assert event.type == EventType.INIT_TIMEOUT
        assert "did not report that it finished initializing" in event.message
        assert "Reinstalling recreates the local environment" in event.message
        assert "will not fix a broken release" in event.message

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    def test_worker_reports_updater_errors_as_update_errors(
        self,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_file,
        queues,
    ):
        """Expected update failures should not be reported as unexpected crashes."""
        event_queue, _response_queue = queues
        mock_update_sources.side_effect = UpdaterError("No releases found")
        mock_env_manager_class.return_value = MagicMock()

        worker = LauncherWorker(mock_config_file, event_queue, _response_queue)
        worker.start()

        import time
        time.sleep(0.5)
        worker.stop()

        errors = []
        while not event_queue.empty():
            event = event_queue.get_nowait()
            if event.type == EventType.ERROR:
                errors.append(event.message)

        assert errors == ["Update error: No releases found"]

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    @patch('launcher.worker.ScriptRunner')
    def test_worker_logs_process_handoff_without_init_message(
        self,
        mock_runner_class,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_file,
        queues,
    ):
        """When no init_message is configured, Launcher should explain the handoff."""
        event_queue, response_queue = queues
        mock_update_sources.return_value = (False, "testapp-v1.0.0")
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.environment_exists.return_value = True
        mock_env_instance.get_or_create_environment.return_value = MagicMock()
        process = MagicMock()
        process.pid = 12345
        mock_runner = MagicMock()
        mock_runner.start.return_value = process
        mock_runner.run_install_script.return_value = True
        mock_runner_class.return_value = mock_runner

        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker.start()

        import time
        time.sleep(0.5)
        worker.stop()

        logs = []
        complete = False
        while not event_queue.empty():
            event = event_queue.get_nowait()
            if event.type == EventType.LOG:
                logs.append(event.message)
            if event.type == EventType.COMPLETE:
                complete = True

        assert "Application process started with PID 12345" in logs
        assert "No init_message configured; launcher will exit and leave the application running." in logs
        assert complete is True
        mock_runner.ensure_still_running.assert_called_once()

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    @patch('launcher.worker.ScriptRunner')
    def test_dependency_hash_mismatch_recreates_environment(
        self,
        mock_runner_class,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_file,
        queues,
    ):
        """Changed dependency inputs force environment recreation."""
        event_queue, response_queue = queues
        state = LauncherState.for_app("TestApp")
        state.dependency_hash = "old"
        state.save()
        mock_update_sources.return_value = (False, "testapp-v1.0.0")
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.environment_exists.return_value = True
        mock_env_instance.get_or_create_environment.return_value = MagicMock()
        mock_runner = MagicMock()
        mock_runner.run_install_script.return_value = True
        mock_runner_class.return_value = mock_runner

        worker = LauncherWorker(mock_config_file, event_queue, response_queue)
        worker.start()

        import time
        time.sleep(0.5)
        worker.stop()

        mock_env_instance.delete_environment.assert_called_once_with("TestApp")


class TestReinstallOnUpdate:
    """Tests for reinstall_on_update behavior."""

    @pytest.fixture
    def mock_config_with_reinstall(self, tmp_path):
        """Create a mock config file with reinstall_on_update enabled."""
        import yaml
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": str(tmp_path / "apps"),
            "repository": "git@github.com:owner/repo.git",
            "auto_update": False,
            "version": "testapp-v1.0.0",
            "install": "install.py",
            "reinstall_on_update": True,
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        # Create the sources directory with main.py and install.py
        sources_dir = tmp_path / "apps" / "testapp-v1.0.0"
        sources_dir.mkdir(parents=True)
        (sources_dir / "main.py").write_text("print('hello')")
        (sources_dir / "install.py").write_text("print('install')")
        (sources_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        return config_file

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    @patch('launcher.worker.ScriptRunner')
    def test_install_script_runs_when_env_created(
        self,
        mock_runner_class,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_with_reinstall,
        queues
    ):
        """Test install script runs when environment is first created."""
        event_queue, response_queue = queues

        # Mock update_sources to return updated=True (new sources downloaded)
        mock_update_sources.return_value = (True, "testapp-v1.0.0")

        # Mock environment manager - env does not exist
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.environment_exists.return_value = False
        mock_env_instance.get_or_create_environment.return_value = MagicMock()

        # Mock runner
        mock_runner = MagicMock()
        mock_runner.run_install_script.return_value = True
        mock_runner_class.return_value = mock_runner

        worker = LauncherWorker(mock_config_with_reinstall, event_queue, response_queue)
        worker.start()

        # Wait for worker to process
        import time
        time.sleep(0.5)

        worker.stop()

        # Install script should have been called since env didn't exist
        mock_runner.run_install_script.assert_called_once()

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    @patch('launcher.worker.ScriptRunner')
    def test_install_script_runs_on_update_when_reinstall_on_update_enabled(
        self,
        mock_runner_class,
        mock_update_sources,
        mock_env_manager_class,
        mock_config_with_reinstall,
        queues
    ):
        """Test install script runs on update when reinstall_on_update is true."""
        event_queue, response_queue = queues

        # Mock update_sources to return updated=True (new sources downloaded)
        mock_update_sources.return_value = (True, "testapp-v1.0.0")

        # Mock environment manager - env already exists
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.environment_exists.return_value = True
        mock_env_instance.get_or_create_environment.return_value = MagicMock()

        # Mock runner
        mock_runner = MagicMock()
        mock_runner.run_install_script.return_value = True
        mock_runner_class.return_value = mock_runner

        worker = LauncherWorker(mock_config_with_reinstall, event_queue, response_queue)
        worker.start()

        # Wait for worker to process
        import time
        time.sleep(0.5)

        worker.stop()

        # Install script should have been called since updated=True and reinstall_on_update=True
        mock_runner.run_install_script.assert_called_once()

    @patch('launcher.worker.LauncherEnvironmentManager')
    @patch('launcher.worker.update_sources')
    @patch('launcher.worker.ScriptRunner')
    def test_install_script_skipped_on_update_when_reinstall_on_update_disabled(
        self,
        mock_runner_class,
        mock_update_sources,
        mock_env_manager_class,
        tmp_path,
        queues
    ):
        """Test install script skipped on update when reinstall_on_update is false."""
        import yaml
        event_queue, response_queue = queues

        # Create config with reinstall_on_update disabled
        config_data = {
            "name": "TestApp",
            "main": "main.py",
            "path": str(tmp_path / "apps"),
            "repository": "git@github.com:owner/repo.git",
            "auto_update": False,
            "version": "testapp-v1.0.0",
            "install": "install.py",
            "reinstall_on_update": False,  # Disabled
        }
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump(config_data))

        # Create the sources directory
        sources_dir = tmp_path / "apps" / "testapp-v1.0.0"
        sources_dir.mkdir(parents=True)
        (sources_dir / "main.py").write_text("print('hello')")
        (sources_dir / "install.py").write_text("print('install')")
        (sources_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # Mock update_sources to return updated=True (new sources downloaded)
        mock_update_sources.return_value = (True, "testapp-v1.0.0")

        # Mock environment manager - env already exists
        mock_env_instance = MagicMock()
        mock_env_manager_class.return_value = mock_env_instance
        mock_env_instance.environment_exists.return_value = True
        mock_env_instance.get_or_create_environment.return_value = MagicMock()

        # Mock runner
        mock_runner = MagicMock()
        mock_runner.run_install_script.return_value = True
        mock_runner_class.return_value = mock_runner

        worker = LauncherWorker(config_file, event_queue, response_queue)
        worker.start()

        # Wait for worker to process
        import time
        time.sleep(0.5)

        worker.stop()

        # Install script should NOT have been called since reinstall_on_update=False
        mock_runner.run_install_script.assert_not_called()
