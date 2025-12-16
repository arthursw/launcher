"""Tests for the worker module."""

import queue
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from launcher.worker import (
    LauncherWorker,
    WorkerEvent,
    GUIResponse,
    EventType,
    ResponseType,
    create_queues,
)


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
