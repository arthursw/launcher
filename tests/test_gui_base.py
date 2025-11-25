"""Tests for GUI base class."""

import queue
from unittest.mock import Mock, MagicMock
import pytest
from gui.base_gui import BaseGUI


class ConcreteGUI(BaseGUI):
    """Concrete implementation of BaseGUI for testing."""

    def show_proxy_dialog(self):
        """Show proxy settings dialog."""
        return {"http": "http://proxy:8080", "https": "https://proxy:8443"}

    def run(self):
        """Run the GUI."""
        pass


class TestBaseGUI:
    """Test BaseGUI abstract class."""

    def test_base_gui_initialization(self):
        """Test initializing BaseGUI with required components."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        assert gui.launcher == launcher_mock
        assert gui.event_queue == event_queue
        assert gui.response_queue == response_queue

    def test_base_gui_abstract_methods(self):
        """Test that BaseGUI cannot be instantiated directly."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        with pytest.raises(TypeError):
            BaseGUI(launcher_mock, event_queue, response_queue)

    def test_gui_show_proxy_dialog_implementation(self):
        """Test that concrete implementation can show proxy dialog."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)
        settings = gui.show_proxy_dialog()

        assert settings["http"] == "http://proxy:8080"
        assert settings["https"] == "https://proxy:8443"

    def test_gui_queue_communication(self):
        """Test queue-based communication between GUI and worker."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        # Simulate worker sending event
        event_queue.put({"type": "log", "message": "Starting launcher"})

        # Simulate GUI receiving event
        event = event_queue.get_nowait()
        assert event["type"] == "log"
        assert event["message"] == "Starting launcher"

    def test_gui_handles_progress_events(self):
        """Test GUI handling progress events."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        # Simulate worker sending progress event
        event_queue.put({"type": "progress", "current": 50, "total": 100})

        event = event_queue.get_nowait()
        assert event["type"] == "progress"
        assert event["current"] == 50
        assert event["total"] == 100

    def test_gui_handles_proxy_required_event(self):
        """Test GUI handling proxy required event."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        # Simulate worker requesting proxy settings
        event_queue.put({"type": "proxy_required"})

        event = event_queue.get_nowait()
        assert event["type"] == "proxy_required"


class TestGUIIntegration:
    """Test GUI integration with launcher and worker."""

    def test_gui_worker_launcher_integration(self):
        """Test integration between GUI, worker, and launcher."""
        launcher_mock = Mock()
        launcher_mock.run = Mock()

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        # Simulate worker thread communicating with GUI
        event_queue.put({"type": "log", "message": "Launcher started"})
        event_queue.put({"type": "progress", "current": 0, "total": 100})

        # GUI reads events
        assert event_queue.get_nowait()["message"] == "Launcher started"
        assert event_queue.get_nowait()["current"] == 0

    def test_gui_responds_to_worker_requests(self):
        """Test GUI responding to worker requests."""
        launcher_mock = Mock()
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        gui = ConcreteGUI(launcher_mock, event_queue, response_queue)

        # Worker requests proxy settings
        event_queue.put({"type": "proxy_required"})

        # GUI gets the event and responds
        event = event_queue.get_nowait()
        if event["type"] == "proxy_required":
            response_queue.put({"type": "proxy_settings", "data": gui.show_proxy_dialog()})

        # Worker receives response
        response = response_queue.get_nowait()
        assert response["type"] == "proxy_settings"
        assert response["data"]["http"] == "http://proxy:8080"
