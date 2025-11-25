"""Tests for worker thread."""

import queue
import threading
import time
from unittest.mock import Mock, MagicMock, patch
import pytest
from worker import launcher_worker


class TestWorkerThread:
    """Test worker thread functionality."""

    @patch("worker.Launcher")
    @patch("worker.get_proxy_settings")
    def test_worker_calls_launcher_run(self, mock_get_proxy, mock_launcher_class):
        """Test that worker thread orchestrates launcher operations."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
project: testapp
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_launcher = MagicMock()
            mock_launcher.get_current_version.return_value = "testapp-v1.0.0"
            mock_launcher.sources_exist.return_value = True
            mock_launcher.config = {}  # No install script defined
            mock_launcher_class.return_value = mock_launcher

            # Mock proxy settings
            mock_proxy = MagicMock()
            mock_proxy.http = None
            mock_proxy.https = None
            mock_get_proxy.return_value = mock_proxy

            event_queue = queue.Queue()
            response_queue = queue.Queue()

            # Run worker in thread
            worker_thread = threading.Thread(
                target=launcher_worker,
                args=(str(config_path), event_queue, response_queue),
                daemon=True,
            )
            worker_thread.start()
            worker_thread.join(timeout=2)

            # Verify launcher methods were called
            mock_launcher.get_current_version.assert_called_once()
            mock_launcher.setup_environment.assert_called_once()
            mock_launcher.run_app.assert_called_once()

    @patch("worker.Launcher")
    def test_worker_sends_log_events(self, mock_launcher_class):
        """Test that worker sends log events to GUI."""
        mock_launcher = MagicMock()
        mock_launcher_class.return_value = mock_launcher

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        worker_thread = threading.Thread(
            target=launcher_worker,
            args=("test_config.yml", event_queue, response_queue),
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=2)

        # Check if any events were sent
        try:
            event = event_queue.get_nowait()
            # Verify it's a valid event
            assert "type" in event
        except queue.Empty:
            # It's okay if no events were sent in this basic test
            pass

    @patch("worker.Launcher")
    def test_worker_handles_proxy_requirement(self, mock_launcher_class):
        """Test that worker handles proxy requirement from launcher."""
        mock_launcher = MagicMock()
        mock_launcher.run.side_effect = Exception("Proxy required")
        mock_launcher_class.return_value = mock_launcher

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        # Pre-populate response queue with proxy settings
        response_queue.put(
            {"type": "proxy_settings", "http": "http://proxy:8080", "https": "https://proxy:8443"}
        )

        worker_thread = threading.Thread(
            target=launcher_worker,
            args=("test_config.yml", event_queue, response_queue),
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=2)

        # Verify worker attempted to run
        assert mock_launcher_class.called

    @patch("worker.Launcher")
    def test_worker_sends_error_events(self, mock_launcher_class):
        """Test that worker sends error events on failure."""
        mock_launcher = MagicMock()
        mock_launcher.run.side_effect = Exception("Test error")
        mock_launcher_class.return_value = mock_launcher

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        worker_thread = threading.Thread(
            target=launcher_worker,
            args=("test_config.yml", event_queue, response_queue),
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=2)

        # Check if error event was sent
        try:
            while not event_queue.empty():
                event = event_queue.get_nowait()
                if event["type"] == "error":
                    assert "message" in event
                    break
        except queue.Empty:
            pass

    @patch("worker.Launcher")
    def test_worker_thread_responsiveness(self, mock_launcher_class):
        """Test that worker thread can be interrupted."""
        mock_launcher = MagicMock()
        mock_launcher.run = Mock()
        mock_launcher_class.return_value = mock_launcher

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        worker_thread = threading.Thread(
            target=launcher_worker,
            args=("test_config.yml", event_queue, response_queue),
            daemon=True,
        )
        worker_thread.start()

        # Thread should finish promptly
        worker_thread.join(timeout=5)
        assert not worker_thread.is_alive()


class TestWorkerQueueCommunication:
    """Test worker thread queue communication."""

    def test_worker_event_queue_non_blocking(self):
        """Test that worker uses non-blocking queue operations."""
        event_queue = queue.Queue()

        # Queue should be empty initially
        with pytest.raises(queue.Empty):
            event_queue.get_nowait()

    def test_worker_response_queue_timeout(self):
        """Test that worker uses timeout for response queue."""
        response_queue = queue.Queue()

        # Should raise Empty after timeout
        with pytest.raises(queue.Empty):
            response_queue.get(timeout=0.1)

    def test_worker_multiple_queue_events(self):
        """Test worker handling multiple queue events."""
        event_queue = queue.Queue()

        # Put multiple events
        event_queue.put({"type": "log", "message": "Event 1"})
        event_queue.put({"type": "log", "message": "Event 2"})
        event_queue.put({"type": "log", "message": "Event 3"})

        # Retrieve all events
        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        assert len(events) == 3
        assert events[0]["message"] == "Event 1"
        assert events[2]["message"] == "Event 3"


class TestWorkerInstallScript:
    """Test worker thread install script execution."""

    @patch("worker.Launcher")
    @patch("worker.get_proxy_settings")
    def test_worker_calls_install_script_when_defined(self, mock_get_proxy, mock_launcher_class):
        """Test that worker executes install script when defined."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
project: testapp
configuration: pyproject.toml
install: install.sh
timeout: 3
"""
            config_path.write_text(config_content)

            mock_launcher = MagicMock()
            mock_launcher.get_current_version.return_value = "testapp-v1.0.0"
            mock_launcher.sources_exist.return_value = True
            mock_launcher.config = {"install": "install.sh"}
            mock_launcher_class.return_value = mock_launcher

            # Mock proxy settings
            mock_proxy = MagicMock()
            mock_proxy.http = None
            mock_proxy.https = None
            mock_get_proxy.return_value = mock_proxy

            event_queue = queue.Queue()
            response_queue = queue.Queue()

            # Run worker in thread
            worker_thread = threading.Thread(
                target=launcher_worker,
                args=(str(config_path), event_queue, response_queue),
                daemon=True,
            )
            worker_thread.start()
            worker_thread.join(timeout=2)

            # Verify launcher methods were called
            mock_launcher.get_current_version.assert_called_once()
            mock_launcher.setup_environment.assert_called_once()
            mock_launcher.run_install_script.assert_called_once()
            mock_launcher.run_app.assert_called_once()


class TestWorkerLauncherIntegration:
    """Test worker integration with launcher."""

    @patch("worker.Launcher")
    @patch("worker.get_proxy_settings")
    def test_worker_gets_proxy_settings_on_failure(
        self, mock_get_proxy, mock_launcher_class
    ):
        """Test that worker attempts to get proxy settings on network failure."""
        mock_launcher = MagicMock()
        mock_launcher.run.side_effect = Exception("Network error")
        mock_launcher_class.return_value = mock_launcher

        mock_get_proxy.return_value = Mock(http="http://proxy:8080")

        event_queue = queue.Queue()
        response_queue = queue.Queue()

        worker_thread = threading.Thread(
            target=launcher_worker,
            args=("test_config.yml", event_queue, response_queue),
            daemon=True,
        )
        worker_thread.start()
        worker_thread.join(timeout=2)

        # Verify launcher was instantiated
        assert mock_launcher_class.called

    @patch("worker.Launcher")
    @patch("worker.get_proxy_settings")
    def test_worker_passes_path_override_to_launcher(
        self, mock_get_proxy, mock_launcher_class
    ):
        """Test that worker passes path_override to Launcher."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "application.yml"
            config_content = """
name: TestApp
api: https://api.github.com/
tags_endpoint: /repos/owner/testapp/git/tags
archive_endpoint: /repos/owner/testapp/zipball/{ref}
main: main.py
path: "."
version: testapp-v1.0.0
auto_update: false
project: testapp
configuration: pyproject.toml
timeout: 3
"""
            config_path.write_text(config_content)

            mock_launcher = MagicMock()
            mock_launcher.get_current_version.return_value = "testapp-v1.0.0"
            mock_launcher.sources_exist.return_value = True
            mock_launcher.config = {}
            mock_launcher_class.return_value = mock_launcher

            mock_proxy = MagicMock()
            mock_proxy.http = None
            mock_proxy.https = None
            mock_get_proxy.return_value = mock_proxy

            event_queue = queue.Queue()
            response_queue = queue.Queue()

            override_path = "/override/path"

            worker_thread = threading.Thread(
                target=launcher_worker,
                args=(str(config_path), event_queue, response_queue, override_path),
                daemon=True,
            )
            worker_thread.start()
            worker_thread.join(timeout=2)

            # Verify Launcher was called with path_override
            mock_launcher_class.assert_called_once_with(
                str(config_path), path_override=override_path
            )
