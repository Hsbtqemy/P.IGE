from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timezone
from pathlib import Path
import logging
import shutil
import tempfile
from typing import Iterable
import zipfile

logger = logging.getLogger(__name__)

from pige.core.models import EntryMeta, Project, Task, TimeLog, TimerState
from pige.utils import dates
from pige.utils import io as io_utils


ALLOWED_ENTRY_PATCH_KEYS = {
    "title",
    "tags",
    "entry_date",
    "person",
    "group",
    "project_id",
    "start_time",
    "end_time",
    "decision_done",
    "context_status",
}

TIMELOG_KEYS = frozenset(
    ("id", "project_id", "start", "end", "duration_sec", "duration_min", "note", "tags")
)
TIMELOG_REQUIRED_KEYS = ("id", "project_id", "start", "end")

TASK_KEYS = frozenset(
    (
        "id",
        "project_id",
        "title",
        "status",
        "created_at",
        "done_at",
        "due_date",
        "tags",
        "linked_entry_id",
        "note",
    )
)
TASK_REQUIRED_KEYS = ("id", "project_id", "title")

TIMER_STATE_KEYS = frozenset(("running", "project_id", "start_ts", "note"))

PROJECT_KEYS = frozenset(
    (
        "id",
        "name",
        "description",
        "status",
        "tags",
        "created_at",
        "person",
        "group",
        "links",
    )
)


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.projects_path = data_dir / "projects.json"
        self.entries_path = data_dir / "entries.jsonl"
        self.entries_dir = data_dir / "entries"
        self.tasks_path = data_dir / "tasks.json"
        self.timers_path = data_dir / "timers.json"
        self.timelogs_path = data_dir / "timelogs.jsonl"
        self.exports_dir = data_dir / "exports"

    def init_storage(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        if not self.projects_path.exists():
            io_utils.safe_write_json(self.projects_path, [])
        if not self.entries_path.exists():
            self.entries_path.touch()
        if not self.tasks_path.exists():
            io_utils.safe_write_json(self.tasks_path, [])
        if not self.timers_path.exists():
            io_utils.safe_write_json(self.timers_path, asdict(default_timer_state()))
        if not self.timelogs_path.exists():
            self.timelogs_path.touch()

    def read_projects(self) -> list[Project]:
        data = io_utils.read_json(self.projects_path, default=[])
        projects: list[Project] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            payload = {k: item[k] for k in PROJECT_KEYS if k in item}
            if not all(payload.get(k) for k in ("id", "name")):
                continue
            payload.setdefault("description", None)
            payload.setdefault("status", "active")
            payload.setdefault("tags", [])
            payload.setdefault("created_at", "")
            payload.setdefault("person", None)
            payload.setdefault("group", None)
            links = payload.get("links")
            payload["links"] = list(links) if isinstance(links, list) else []
            projects.append(Project(**payload))
        return projects

    def write_projects(self, projects: Iterable[Project]) -> None:
        data = [asdict(project) for project in projects]
        io_utils.safe_write_json(self.projects_path, data)

    def append_entry_meta(self, entry: EntryMeta) -> None:
        self.append_entry_event(entry)

    def append_entry_event(self, entry: EntryMeta) -> None:
        payload = asdict(entry)
        payload["kind"] = "entry"
        io_utils.append_jsonl(self.entries_path, payload)

    def append_entry_update(self, entry_id: str, ts: str, patch: dict[str, object]) -> None:
        payload = {"kind": "entry_update", "ts": ts, "entry_id": entry_id, "patch": patch}
        io_utils.append_jsonl(self.entries_path, payload)

    def append_entry_delete(self, entry_id: str, ts: str) -> None:
        payload = {"kind": "entry_delete", "ts": ts, "entry_id": entry_id}
        io_utils.append_jsonl(self.entries_path, payload)

    def read_entries_meta(self) -> list[EntryMeta]:
        events = io_utils.read_jsonl(self.entries_path)
        return _fold_entry_events(events)

    def list_entries(self, project_id: str | None = None) -> list[EntryMeta]:
        entries = self.read_entries_meta()
        if project_id is None:
            return entries
        return [entry for entry in entries if entry.project_id == project_id]

    def get_entry(self, entry_id: str) -> EntryMeta | None:
        for entry in self.read_entries_meta():
            if entry.id == entry_id:
                return entry
        return None

    def read_entry_body(self, entry: EntryMeta) -> str:
        content_path = self.data_dir / entry.content_path
        if not content_path.exists():
            return ""
        return self.read_entry_content(content_path)

    def write_entry_content(self, entry_id: str, content: str) -> Path:
        path = self.entries_dir / f"{entry_id}.md"
        io_utils.safe_write_text(path, content)
        return path

    def read_entry_content(self, content_path: Path) -> str:
        with open(content_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def read_tasks(self) -> list[Task]:
        data = io_utils.read_json(self.tasks_path, default=[])
        tasks: list[Task] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            payload = {k: item[k] for k in TASK_KEYS if k in item}
            if not all(payload.get(k) for k in TASK_REQUIRED_KEYS):
                continue
            status = str(payload.get("status") or "").strip() or "open"
            if status not in ("open", "in_progress", "done"):
                status = "open"
            payload["status"] = status
            payload.setdefault("created_at", "")
            payload.setdefault("done_at", None)
            payload.setdefault("due_date", None)
            tags = payload.get("tags")
            payload["tags"] = list(tags) if isinstance(tags, list) else []
            payload.setdefault("linked_entry_id", None)
            payload.setdefault("note", None)
            tasks.append(Task(**payload))
        return tasks

    def create_backup(self, zip_path: Path) -> Path:
        zip_path = Path(zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        paths = sorted(self.data_dir.rglob("*"))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for path in paths:
                if not path.is_file():
                    continue
                if path.suffix == ".tmp":
                    continue
                rel_path = path.relative_to(self.data_dir).as_posix()
                handle.write(path, rel_path)
        return zip_path

    def restore_backup(self, zip_path: Path) -> None:
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise ValueError(f"Backup file not found: {zip_path}")
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        safety_backup = self.exports_dir / f"backup_before_restore_{timestamp}.zip"
        self.create_backup(safety_backup)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with zipfile.ZipFile(zip_path, "r") as handle:
                handle.extractall(temp_path)

            source_dir = temp_path
            if not _has_backup_markers(source_dir):
                subdirs = [item for item in temp_path.iterdir() if item.is_dir()]
                if len(subdirs) == 1 and _has_backup_markers(subdirs[0]):
                    source_dir = subdirs[0]
                else:
                    raise ValueError("Backup format not recognized")

            (source_dir / "entries").mkdir(parents=True, exist_ok=True)
            self.data_dir.mkdir(parents=True, exist_ok=True)

            for item in self.data_dir.iterdir():
                if item.resolve() == safety_backup.resolve():
                    continue
                if item.is_dir():
                    if _path_contains(item, safety_backup):
                        for child in item.iterdir():
                            if child.resolve() == safety_backup.resolve():
                                continue
                            if child.is_dir():
                                shutil.rmtree(child)
                            else:
                                child.unlink()
                        continue
                    shutil.rmtree(item)
                else:
                    item.unlink()

            for path in sorted(source_dir.rglob("*")):
                rel_path = path.relative_to(source_dir)
                dest = self.data_dir / rel_path
                if path.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

    def write_tasks(self, tasks: Iterable[Task]) -> None:
        data = [asdict(task) for task in tasks]
        io_utils.safe_write_json(self.tasks_path, data)

    def read_timer_state(self) -> TimerState:
        default_data = asdict(default_timer_state())
        data = io_utils.read_json(self.timers_path, default=default_data)
        if not isinstance(data, dict):
            return TimerState(**default_data)
        payload = {k: data[k] for k in TIMER_STATE_KEYS if k in data}
        payload.setdefault("running", False)
        payload.setdefault("project_id", None)
        payload.setdefault("start_ts", None)
        payload.setdefault("note", None)
        return TimerState(**payload)

    def write_timer_state(self, state: TimerState) -> None:
        io_utils.safe_write_json(self.timers_path, asdict(state))

    def append_timelog(self, timelog: TimeLog) -> None:
        io_utils.append_jsonl(self.timelogs_path, asdict(timelog))

    def read_timelogs(self) -> list[TimeLog]:
        data = io_utils.read_jsonl(self.timelogs_path)
        result: list[TimeLog] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if not all(k in item for k in TIMELOG_REQUIRED_KEYS):
                continue
            payload = {k: item[k] for k in TIMELOG_KEYS if k in item}
            payload.setdefault("duration_sec", None)
            payload.setdefault("duration_min", None)
            payload.setdefault("note", None)
            tags = payload.get("tags")
            payload["tags"] = list(tags) if isinstance(tags, list) else []
            result.append(TimeLog(**payload))
        return result

    def write_timelogs(self, timelogs: Iterable[TimeLog]) -> None:
        data = (asdict(timelog) for timelog in timelogs)
        io_utils.safe_write_jsonl(self.timelogs_path, data)

    def compact_entries_log(self) -> dict[str, int]:
        """
        Rewrite entries.jsonl as a snapshot of current entries only (one "entry"
        event per entry). Reduces file size and replay time; removes update/delete
        history. Returns counts: before_lines, after_lines, entries_count.
        """
        events = io_utils.read_jsonl(self.entries_path)
        before_lines = len(events)
        entries = self.read_entries_meta()
        snapshot: list[dict[str, object]] = []
        for entry in entries:
            payload = asdict(entry)
            payload["kind"] = "entry"
            snapshot.append(payload)
        io_utils.safe_write_jsonl(self.entries_path, snapshot)
        return {
            "before_lines": before_lines,
            "after_lines": len(snapshot),
            "entries_count": len(entries),
        }


def default_timer_state() -> TimerState:
    return TimerState(running=False, project_id=None, start_ts=None, note=None)


def is_pige_data_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return (
        (path / "projects.json").exists()
        and (path / "entries.jsonl").exists()
        and (path / "entries").is_dir()
    )


def recap_data_dir(path: Path) -> dict[str, int]:
    storage = Storage(path)
    recap = {
        "projects": len(storage.read_projects()),
        "entries": len(storage.read_entries_meta()),
        "tasks": len(storage.read_tasks()),
        "timelogs": len(storage.read_timelogs()),
        "entry_files": _count_entry_files(path / "entries"),
    }
    return recap


def copy_data_dir_contents(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        raise ValueError(f"Source data directory not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    files = (
        "projects.json",
        "entries.jsonl",
        "tasks.json",
        "timers.json",
        "timelogs.jsonl",
        ".pige_prefs.json",
        "gui_prefs.json",
    )
    for name in files:
        src_file = src / name
        if not src_file.exists() or not src_file.is_file():
            continue
        if src_file.suffix == ".tmp":
            continue
        shutil.copy2(src_file, dst / name)
    for dir_name in ("entries", "exports"):
        src_dir = src / dir_name
        if not src_dir.exists() or not src_dir.is_dir():
            continue
        dst_dir = dst / dir_name
        if dst_dir.exists():
            raise ValueError(f"Destination already contains {dir_name}")
        shutil.copytree(src_dir, dst_dir, ignore=shutil.ignore_patterns("*.tmp"))


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
        logger.debug("Could not count entry files in %s", entries_dir, exc_info=True)
        return 0


def _path_contains(parent: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _has_backup_markers(path: Path) -> bool:
    return (path / "projects.json").exists() and (path / "entries.jsonl").exists()


def _normalize_entry_ts(value: object, entry_date: object | None = None) -> str:
    ts_value = value.strip() if isinstance(value, str) else ""
    if ts_value:
        try:
            dates.parse_utc_z(ts_value)
            return ts_value
        except Exception:
            logger.debug("parse_utc_z failed for ts_value=%r", ts_value, exc_info=True)
            pass
        try:
            parsed_date = dates.parse_date(ts_value)
            return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc).strftime(
                dates.UTC_Z_FORMAT
            )
        except Exception:
            logger.debug("parse_date failed for ts_value=%r", ts_value, exc_info=True)
            pass
        parsed_dt = _parse_iso_datetime(ts_value)
        if parsed_dt is not None:
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(microsecond=0)
            return parsed_dt.strftime(dates.UTC_Z_FORMAT)
    if isinstance(entry_date, str) and entry_date:
        try:
            parsed_date = dates.parse_date(entry_date)
            return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc).strftime(
                dates.UTC_Z_FORMAT
            )
        except Exception:
            logger.debug("parse_date failed for entry_date=%r", entry_date, exc_info=True)
            pass
    return "1970-01-01T00:00:00Z"


def _parse_iso_datetime(value: str) -> datetime | None:
    iso_value = value.strip()
    if iso_value.endswith("Z"):
        iso_value = f"{iso_value[:-1]}+00:00"
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        return None


def _fold_entry_events(events: list[object]) -> list[EntryMeta]:
    entries: dict[str, EntryMeta] = {}
    order: list[str] = []
    for raw in events:
        if not isinstance(raw, dict):
            raise ValueError("Invalid entry event")
        kind = raw.get("kind") or "entry"
        if kind == "entry":
            entry_data = {k: v for k, v in raw.items() if k != "kind"}
            entry_data["ts"] = _normalize_entry_ts(
                entry_data.get("ts"), entry_data.get("entry_date")
            )
            entry = EntryMeta(**entry_data)
            if not entry.context_status:
                entry.context_status = None
            entries[entry.id] = entry
            if entry.id not in order:
                order.append(entry.id)
            continue
        if kind == "entry_update":
            entry_id = raw.get("entry_id")
            if not entry_id or entry_id not in entries:
                raise ValueError(f"Unknown entry_id {entry_id} in update")
            patch = raw.get("patch")
            if not isinstance(patch, dict):
                raise ValueError("Invalid entry_update patch")
            if "type" in patch:
                raise ValueError("Entry type cannot be updated")
            unknown_keys = set(patch.keys()) - ALLOWED_ENTRY_PATCH_KEYS
            if unknown_keys:
                raise ValueError(f"Invalid entry_update keys: {sorted(unknown_keys)}")
            updated = _apply_entry_patch(entries[entry_id], patch)
            if not updated.context_status:
                updated.context_status = None
            entries[entry_id] = updated
            continue
        if kind == "entry_delete":
            entry_id = raw.get("entry_id")
            if not entry_id or entry_id not in entries:
                raise ValueError(f"Unknown entry_id {entry_id} in delete")
            entries.pop(entry_id, None)
            if entry_id in order:
                order.remove(entry_id)
            continue
        raise ValueError(f"Unknown entry event kind {kind}")
    return [entries[entry_id] for entry_id in order if entry_id in entries]


def _apply_entry_patch(entry: EntryMeta, patch: dict[str, object]) -> EntryMeta:
    data = asdict(entry)
    for key, value in patch.items():
        data[key] = value
    return EntryMeta(**data)
