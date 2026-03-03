"""Tests for the GUI base module."""

import queue
import pytest
from unittest.mock import Mock, patch

from launcher.worker import WorkerEvent, GUIResponse, EventType, ResponseType
from launcher.gui.base import BaseGUI


class ConcreteGUI(BaseGUI):
    """Concrete implementation of BaseGUI for testing."""

    def __init__(self, event_queue, response_queue, app_name="Test"):
        super().__init__(event_queue, response_queue, app_name)
        self.progress_updates = []
        self.log_messages = []
        self.proxy_dialogs = []
        self.timeout_dialogs = []
        self.errors = []
        self.completed = False
        self._should_continue = True

    def _create_window(self):
        pass

    def _update_progress(self, current, total, message):
        self.progress_updates.append((current, total, message))

    def _append_log(self, message):
        self.log_messages.append(message)

    def _show_proxy_dialog(self, request_id):
        self.proxy_dialogs.append(request_id)
        # Simulate user submitting proxy
        self._submit_proxy_response(request_id, "http://proxy:8080", None, ssl_cert_file=None)

    def _show_init_timeout_dialog(self, request_id, message):
        self.timeout_dialogs.append((request_id, message))
        # Simulate user choosing to wait
        self._submit_init_timeout_response(request_id, "wait")

    def _show_error(self, message):
        self.errors.append(message)

    def _show_complete(self):
        self.completed = True

    def _process_events_once(self):
        return self._should_continue

    def show(self):
        pass

    def hide(self):
        pass

    def destroy(self):
        self._should_continue = False


@pytest.fixture
def queues():
    """Create test queues."""
    return queue.Queue(), queue.Queue()


@pytest.fixture
def gui(queues):
    """Create a concrete GUI instance."""
    event_queue, response_queue = queues
    return ConcreteGUI(event_queue, response_queue)


class TestBaseGUI:
    """Tests for BaseGUI abstract class."""

    def test_initialization(self, gui, queues):
        """Test GUI initialization."""
        event_queue, response_queue = queues
        assert gui.event_queue == event_queue
        assert gui.response_queue == response_queue
        assert gui.app_name == "Test"
        assert not gui.is_completed
        assert gui.error_message is None

    def test_handle_log_event(self, gui, queues):
        """Test handling log events."""
        event = WorkerEvent(type=EventType.LOG, message="Test log")
        gui._handle_event(event)

        assert len(gui.log_messages) == 1
        assert gui.log_messages[0] == "Test log"

    def test_handle_progress_event(self, gui, queues):
        """Test handling progress events."""
        event = WorkerEvent(
            type=EventType.PROGRESS,
            current=50,
            total=100,
            message="Downloading"
        )
        gui._handle_event(event)

        assert len(gui.progress_updates) == 1
        assert gui.progress_updates[0] == (50, 100, "Downloading")

    def test_handle_proxy_required_event(self, gui, queues):
        """Test handling proxy required events."""
        event_queue, response_queue = queues
        event = WorkerEvent(type=EventType.PROXY_REQUIRED, request_id="test-123")
        gui._handle_event(event)

        assert len(gui.proxy_dialogs) == 1
        assert gui.proxy_dialogs[0] == "test-123"

        # Check response was sent
        response = response_queue.get_nowait()
        assert response.type == ResponseType.PROXY_SETTINGS
        assert response.request_id == "test-123"
        assert response.data["http"] == "http://proxy:8080"

    def test_handle_init_timeout_event(self, gui, queues):
        """Test handling init timeout events."""
        event_queue, response_queue = queues
        event = WorkerEvent(
            type=EventType.INIT_TIMEOUT,
            request_id="test-456",
            message="Timeout occurred"
        )
        gui._handle_event(event)

        assert len(gui.timeout_dialogs) == 1
        assert gui.timeout_dialogs[0] == ("test-456", "Timeout occurred")

        # Check response was sent
        response = response_queue.get_nowait()
        assert response.type == ResponseType.INIT_TIMEOUT_RESPONSE
        assert response.request_id == "test-456"
        assert response.data["action"] == "wait"

    def test_handle_error_event(self, gui, queues):
        """Test handling error events."""
        event = WorkerEvent(type=EventType.ERROR, message="Test error")
        gui._handle_event(event)

        assert len(gui.errors) == 1
        assert gui.errors[0] == "Test error"
        assert gui.error_message == "Test error"

    def test_handle_complete_event(self, gui, queues):
        """Test handling complete events."""
        event = WorkerEvent(type=EventType.COMPLETE)
        gui._handle_event(event)

        assert gui.completed
        assert gui.is_completed

    def test_check_events(self, gui, queues):
        """Test checking multiple events from queue."""
        event_queue, response_queue = queues

        # Put multiple events in queue
        event_queue.put(WorkerEvent(type=EventType.LOG, message="Message 1"))
        event_queue.put(WorkerEvent(type=EventType.LOG, message="Message 2"))
        event_queue.put(WorkerEvent(type=EventType.PROGRESS, current=25, total=100, message="Progress"))

        gui._check_events()

        assert len(gui.log_messages) == 2
        assert len(gui.progress_updates) == 1

    def test_submit_proxy_response(self, gui, queues):
        """Test submitting proxy response."""
        event_queue, response_queue = queues

        gui._submit_proxy_response("req-1", "http://proxy:80", "https://proxy:443")

        response = response_queue.get_nowait()
        assert response.type == ResponseType.PROXY_SETTINGS
        assert response.request_id == "req-1"
        assert response.data["http"] == "http://proxy:80"
        assert response.data["https"] == "https://proxy:443"

    def test_submit_proxy_response_with_ssl_cert_file(self, gui, queues):
        """Test submitting proxy response with ssl_cert_file."""
        event_queue, response_queue = queues

        gui._submit_proxy_response("req-1", "http://proxy:80", None, ssl_cert_file="/path/to/cert.pem")

        response = response_queue.get_nowait()
        assert response.type == ResponseType.PROXY_SETTINGS
        assert response.request_id == "req-1"
        assert response.data["http"] == "http://proxy:80"
        assert response.data["ssl_cert_file"] == "/path/to/cert.pem"

    def test_submit_init_timeout_response(self, gui, queues):
        """Test submitting init timeout response."""
        event_queue, response_queue = queues

        gui._submit_init_timeout_response("req-2", "reinstall")

        response = response_queue.get_nowait()
        assert response.type == ResponseType.INIT_TIMEOUT_RESPONSE
        assert response.request_id == "req-2"
        assert response.data["action"] == "reinstall"
