"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolate_launcher_state(tmp_path, monkeypatch):
    """Keep launcher runtime state out of the developer's real app data."""
    monkeypatch.setenv("LAUNCHER_STATE_DIR", str(tmp_path / "launcher-state"))
