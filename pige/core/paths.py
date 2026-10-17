"""Where P.IGE keeps its files: one resolution shared by the CLI, the GUI and the server.

Data directory, in order of priority:
1. ``PIGE_DATA_DIR`` environment variable;
2. ``data_dir`` in the global config file (written by the GUI's folder chooser);
3. ``./data`` in the current directory, if it already exists (older installs);
4. the per-user data folder of the operating system (platformdirs):
   Linux ``~/.local/share/PIGE``, macOS ``~/Library/Application Support/PIGE``,
   Windows ``%LOCALAPPDATA%\\PIGE``.

Step 3 keeps existing setups working unchanged; step 4 replaces the former
fallback, which created ``./data`` wherever the program happened to start
(``/data`` for a macOS .app, which cannot be written).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import platformdirs

APP_NAME = "PIGE"
logger = logging.getLogger(__name__)


def global_config_path() -> Path:
    """Location of the global config file (unchanged from earlier versions)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        base_path = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return base_path / APP_NAME / "config.json"
    return Path.home() / ".config" / "pige" / "config.json"


def load_global_config() -> dict:
    path = global_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        logger.exception("Failed to load global config from %s", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def resolve_data_dir(cwd: Path | None = None) -> Path:
    env = os.environ.get("PIGE_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    configured = load_global_config().get("data_dir")
    if configured:
        return Path(str(configured)).expanduser()
    legacy = (cwd or Path.cwd()) / "data"
    if (legacy / "projects.json").exists():
        return legacy
    return default_data_dir()


def log_dir() -> Path:
    env = os.environ.get("PIGE_LOG_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))
