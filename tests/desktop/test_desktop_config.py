"""Unit tests for desktop client configuration management."""

import json
import os
from pathlib import Path
import pytest

from desktop.config import DesktopConfig, get_default_config_path


def test_desktop_config_defaults():
    cfg = DesktopConfig()
    assert cfg.backend_url == "http://127.0.0.1:8000"
    assert cfg.health_poll_interval_seconds == 10
    assert cfg.feed_poll_interval_seconds == 5
    assert cfg.incidents_poll_interval_seconds == 10
    assert cfg.connectors_poll_interval_seconds == 15
    assert cfg.request_timeout_seconds == 5.0
    assert cfg.reindex_timeout_seconds == 30.0
    assert cfg.window_width == 1280
    assert cfg.window_height == 850


def test_desktop_config_save_and_load(tmp_path: Path):
    cfg_file = tmp_path / "test_config.json"
    cfg = DesktopConfig(
        backend_url="http://192.168.1.50:8000",
        health_poll_interval_seconds=20,
        feed_poll_interval_seconds=8,
        window_width=1600,
        window_height=900,
    )
    cfg.save(config_path=cfg_file)
    assert cfg_file.exists()

    loaded = DesktopConfig.load(config_path=cfg_file)
    assert loaded.backend_url == "http://192.168.1.50:8000"
    assert loaded.health_poll_interval_seconds == 20
    assert loaded.feed_poll_interval_seconds == 8
    assert loaded.window_width == 1600
    assert loaded.window_height == 900


def test_desktop_config_env_overrides(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "test_config.json"
    cfg = DesktopConfig(backend_url="http://localhost:8000")
    cfg.save(config_path=cfg_file)

    monkeypatch.setenv("SENTINELOPS_API_URL", "http://custom-host:9000/")
    monkeypatch.setenv("SENTINELOPS_POLL_INTERVAL", "12")

    loaded = DesktopConfig.load(config_path=cfg_file)
    assert loaded.backend_url == "http://custom-host:9000"
    assert loaded.health_poll_interval_seconds == 12
    assert loaded.feed_poll_interval_seconds == 6
    assert loaded.incidents_poll_interval_seconds == 12


def test_appdata_config_path():
    path = get_default_config_path()
    assert "SentinelOps" in str(path)
    assert path.name == "desktop_config.json"
