"""Standalone helpers for the PIGE GUI (config, paths, formatting, dialogs support)."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from pige.core import paths
from pige.utils import io as io_utils
from pige.core.storage import Storage
from pige.utils import dates, strings

from pige.interfaces.gui_constants import (
    TYPE_DISPLAY_TO_INTERNAL,
    TYPE_INTERNAL_TO_DISPLAY,
    UI_DATE_FORMAT,
)

logger = logging.getLogger(__name__)

_UI_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _menu_accel(key: str, modifier: str = "Ctrl") -> str:
    """Return menu accelerator label: Ctrl+X on Windows, ⌘X on macOS."""
    if sys.platform == "darwin":
        return f"⌘{key.upper()}"
    return f"{modifier}+{key.upper()}"


def _display_entry_type(value: str) -> str:
    return TYPE_INTERNAL_TO_DISPLAY.get(value, value)


def _internal_entry_type(value: str) -> str:
    return TYPE_DISPLAY_TO_INTERNAL.get(value, value)


def format_date_ui(value: str | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime(UI_DATE_FORMAT)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return ""
        if _UI_DATE_PATTERN.match(cleaned):
            return cleaned
        try:
            parsed = datetime.strptime(cleaned, UI_DATE_FORMAT).date()
            return parsed.strftime(UI_DATE_FORMAT)
        except Exception:
            pass
        try:
            parsed = dates.parse_date(cleaned)
            return parsed.strftime(UI_DATE_FORMAT)
        except Exception:
            return cleaned
    return str(value)


def parse_date_ui(text: str) -> date:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Date is required")
    try:
        return datetime.strptime(cleaned, UI_DATE_FORMAT).date()
    except ValueError:
        pass
    try:
        return dates.parse_date(cleaned)
    except Exception as exc:
        raise ValueError("Date must be DD/MM/YYYY (or YYYY-MM-DD)") from exc


def split_people(text: str | None) -> list[str]:
    return strings.split_people(text)


def join_people_storage(people: list[str]) -> str:
    return strings.join_people_storage(people)


def format_people_inline(text: str | None, max_items: int = 3) -> str:
    return strings.format_people_inline(text, max_items=max_items)


def _data_dir_from_env() -> Path:
    env = os.environ.get("PIGE_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return paths.resolve_data_dir()


def _global_config_path() -> Path:
    return paths.global_config_path()


def _load_global_config() -> dict:
    return paths.load_global_config()


def _save_global_config(cfg: dict) -> None:
    io_utils.safe_write_json(paths.global_config_path(), cfg)


def _resolve_data_dir() -> Path:
    return paths.resolve_data_dir()


def _is_dir_empty(path: Path) -> bool:
    try:
        return next(path.iterdir(), None) is None
    except Exception:
        logger.debug("Could not list directory %s", path, exc_info=True)
        return False


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except Exception:
        logger.debug(
            "Path check failed for child=%s parent=%s", child, parent, exc_info=True
        )
        return False


def _count_entry_files(entries_dir: Path) -> int:
    if not entries_dir.exists():
        return 0
    try:
        return sum(
            1
            for item in entries_dir.iterdir()
            if item.is_file() and item.suffix.lower() == ".md"
        )
    except Exception:
        logger.debug(
            "Could not count entry files in %s", entries_dir, exc_info=True
        )
        return 0


def _detect_pige_data_dir(path: Path) -> tuple[bool, dict[str, int]]:
    if not path.exists() or not path.is_dir():
        return False, {}
    core_files = (
        (path / "projects.json").exists()
        and (path / "entries.jsonl").exists()
        and (path / "entries").is_dir()
    )
    if not core_files:
        return False, {}
    try:
        storage = Storage(path)
        recap = {
            "projects": len(storage.read_projects()),
            "entries": len(storage.read_entries_meta()),
            "tasks": len(storage.read_tasks()),
            "timelogs": len(storage.read_timelogs()),
            "entry_files": _count_entry_files(path / "entries"),
        }
    except Exception:
        logger.exception(
            "Failed to detect PIGE data dir or read recap at %s", path
        )
        return False, {}
    return True, recap


def _safe_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(path) + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def _open_path(path: Path) -> bool:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            result = subprocess.run(["open", str(path)], check=False)
            return result.returncode == 0
        result = subprocess.run(["xdg-open", str(path)], check=False)
        return result.returncode == 0
    except Exception:
        logger.debug("Could not open path %s", path, exc_info=True)
        return False
