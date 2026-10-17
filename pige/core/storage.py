from __future__ import annotations

import json

from dataclasses import asdict
from datetime import datetime, time, timezone
from pathlib import Path
import logging
import shutil
import tempfile
from typing import Iterable
import zipfile

logger = logging.getLogger(__name__)

from pige.core.cache import EntryCache
from pige.core.indexing import INDEX_CONTENT_VERSION, SearchIndex, index_content_version
from pige.core.models import EntryMeta, Project, Task, TimeLog, TimerState, CalendarEvent
from pige.utils import dates, ids
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
    "priority",
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
        "mail_message_id",
    )
)
TASK_REQUIRED_KEYS = ("id", "project_id", "title")

LOCK_FILE_NAME = ".pige.lock"

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
        "parent_id",
        "display_order",
        "priority",
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
        self.calendar_events_path = data_dir / "calendar_events.json"  # NEW
        self.exports_dir = data_dir / "exports"
        self.index_path = data_dir / ".pige_index.db"
        self._entry_cache = EntryCache()  # Cache for entry metadata
        # One lock for every process using this data directory (server, CLI, GUI).
        self.lock = io_utils.FileLock(data_dir / LOCK_FILE_NAME)
        self._index_checked = False

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
        if not self.calendar_events_path.exists():  # NEW
            io_utils.safe_write_json(self.calendar_events_path, [])
        
        # Search index is created on-demand (first write or rebuild-index command)
    
    def _get_search_index(self) -> SearchIndex:
        """Open the search index (use as context manager).

        The first time, an index that is missing or was built by an older version
        (titles only, no entry bodies) is rebuilt from the data files.
        """
        if not self._index_checked:
            self._index_checked = True
            if index_content_version(self.index_path) != INDEX_CONTENT_VERSION:
                try:
                    self.rebuild_search_index()
                except Exception:
                    logger.warning("Could not rebuild the search index", exc_info=True)
        return SearchIndex(self.index_path)

    def _project_name(self, project_id: str) -> str:
        for project in self.read_projects():
            if project.id == project_id:
                return project.name
        return ""

    def _auto_index_entry(self, entry: EntryMeta) -> None:
        """Index an entry (title, tags, people, body, project), never failing the write."""
        try:
            body = self.read_entry_body(entry)
            with self._get_search_index() as idx:
                idx.index_entry(entry, body, self._project_name(entry.project_id))
        except Exception:
            logger.warning("Auto-indexing failed for entry %s, run rebuild-index", entry.id, exc_info=True)

    def _auto_index_projects(self, projects: list[Project]) -> None:
        try:
            with self._get_search_index() as idx:
                idx.index_projects_bulk(projects)
        except Exception:
            logger.warning("Auto-indexing of projects failed, run rebuild-index", exc_info=True)

    def _auto_index_tasks(self, tasks: list[Task]) -> None:
        try:
            names = {p.id: p.name for p in self.read_projects()}
            titles = {e.id: e.title for e in self.read_entries_meta()}
            data = [
                (t, names.get(t.project_id), titles.get(t.linked_entry_id) if t.linked_entry_id else None)
                for t in tasks
            ]
            with self._get_search_index() as idx:
                idx.index_tasks_bulk(data)
        except Exception:
            logger.warning("Auto-indexing of tasks failed, run rebuild-index", exc_info=True)
    
    def _auto_remove_entry(self, entry_id: str) -> None:
        """Remove an entry from FTS, silently ignoring errors."""
        try:
            with self._get_search_index() as idx:
                idx.remove_entry(entry_id)
        except Exception:
            logger.warning("Auto-index removal failed for entry %s, run rebuild-index", entry_id, exc_info=True)

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
            # Hierarchy fields (migration support)
            payload.setdefault("parent_id", None)
            payload.setdefault("display_order", 0)
            payload.setdefault("priority", 3)
            projects.append(Project(**payload))
        return projects

    def write_projects(self, projects: Iterable[Project]) -> None:
        projects = list(projects)
        data = [asdict(project) for project in projects]
        io_utils.safe_write_json(self.projects_path, data)
        self._auto_index_projects(projects)

    def append_entry_meta(self, entry: EntryMeta) -> None:
        self.append_entry_event(entry)

    def append_entry_event(self, entry: EntryMeta) -> None:
        payload = asdict(entry)
        payload["kind"] = "entry"
        io_utils.append_jsonl(self.entries_path, payload)
        self.invalidate_entry_cache()
        self._auto_index_entry(entry)

    def append_entry_update(self, entry_id: str, ts: str, patch: dict[str, object]) -> None:
        payload = {"kind": "entry_update", "ts": ts, "entry_id": entry_id, "patch": patch}
        io_utils.append_jsonl(self.entries_path, payload)
        self.invalidate_entry_cache()
        try:
            updated = self.get_entry(entry_id)
            if updated is not None:
                self._auto_index_entry(updated)
        except Exception:
            logger.warning("Auto-indexing skipped for entry %s, run rebuild-index", entry_id, exc_info=True)

    def append_entry_delete(self, entry_id: str, ts: str) -> None:
        payload = {"kind": "entry_delete", "ts": ts, "entry_id": entry_id}
        io_utils.append_jsonl(self.entries_path, payload)
        self.invalidate_entry_cache()
        self._auto_remove_entry(entry_id)

    def read_entries_meta(self) -> list[EntryMeta]:
        # The cache is only valid while entries.jsonl is unchanged on disk, so a
        # write by another process (server, CLI, GUI) is picked up on next read.
        signature = io_utils.file_signature(self.entries_path)
        cached = self._entry_cache.get_entries(signature)
        if cached is not None:
            return cached

        events = io_utils.read_jsonl(self.entries_path)
        entries = _fold_entry_events(events)
        self._entry_cache.set_entries(entries, signature)
        return entries
    
    def invalidate_entry_cache(self) -> None:
        """Invalidate the entry cache. Call this after write operations."""
        self._entry_cache.invalidate()

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

    def entry_path(self, entry: EntryMeta) -> Path | None:
        """Absolute path of an entry's Markdown file, or None if ``content_path``
        points outside ``entries/`` (corrupt or hostile data, e.g. a crafted backup)."""
        candidate = (self.data_dir / entry.content_path).resolve()
        try:
            candidate.relative_to(self.entries_dir.resolve())
        except ValueError:
            logger.warning("Ignoring unsafe content path for entry %s: %r", entry.id, entry.content_path)
            return None
        return candidate

    def read_entry_body(self, entry: EntryMeta) -> str:
        content_path = self.entry_path(entry)
        if content_path is None or not content_path.exists():
            return ""
        return self.read_entry_content(content_path)

    def write_entry_content(self, entry_id: str, content: str) -> Path:
        if not ids.is_safe_id(entry_id):
            raise ValueError(f"Invalid entry id: {entry_id!r}")
        path = self.entries_dir / f"{entry_id}.md"
        io_utils.safe_write_text(path, content)
        entry = self.get_entry(entry_id)
        if entry is not None:  # not yet logged while an entry is being created
            self._auto_index_entry(entry)
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
            payload.setdefault("mail_message_id", None)
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
                if path.suffix == ".tmp" or path.name == LOCK_FILE_NAME:
                    continue
                rel_path = path.relative_to(self.data_dir).as_posix()
                if rel_path == "calendar_subscriptions.json":
                    # Never copy calendar passwords into a backup that may travel.
                    handle.writestr(rel_path, _without_credentials(path))
                    continue
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
                _safe_extract_zip(handle, temp_path)

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
                if item.name == LOCK_FILE_NAME:
                    continue  # held by this process during the restore
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
                if rel_path.name == LOCK_FILE_NAME:
                    continue
                dest = self.data_dir / rel_path
                if path.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

    def write_tasks(self, tasks: Iterable[Task]) -> None:
        tasks = list(tasks)
        data = [asdict(task) for task in tasks]
        io_utils.safe_write_json(self.tasks_path, data)
        self._auto_index_tasks(tasks)

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
        self.invalidate_entry_cache()  # Invalidate after rewrite
        return {
            "before_lines": before_lines,
            "after_lines": len(snapshot),
            "entries_count": len(entries),
        }

    def migrate_projects_hierarchy(self) -> dict[str, int]:
        """
        Migrate existing projects to include hierarchy fields (parent_id, display_order).
        This is idempotent and safe to run multiple times.
        Returns: dict with migration stats (total, migrated, already_migrated).
        """
        projects = self.read_projects()
        migrated_count = 0
        
        for i, project in enumerate(projects):
            # Only set display_order if it's at default (0) AND there are multiple projects
            # This preserves any custom ordering that was already set
            if project.display_order == 0 and len(projects) > 1:
                project.display_order = i
                migrated_count += 1
        
        # Only write back if changes were made
        if migrated_count > 0:
            self.write_projects(projects)
        
        return {
            "total": len(projects),
            "migrated": migrated_count,
            "already_migrated": len(projects) - migrated_count,
        }

    def get_project_children(self, parent_id: str | None) -> list[Project]:
        """
        Get all direct children of a project (or root projects if parent_id is None).
        Children are sorted by display_order.
        
        Args:
            parent_id: Parent project ID, or None for root-level projects
            
        Returns:
            List of child projects sorted by display_order
        """
        projects = self.read_projects()
        children = [p for p in projects if p.parent_id == parent_id]
        return sorted(children, key=lambda p: p.display_order)

    def get_project_ancestors(self, project_id: str) -> list[Project]:
        """
        Get all ancestors of a project, from immediate parent to root.
        Returns empty list if project has no parent or doesn't exist.
        
        Args:
            project_id: Project ID to get ancestors for
            
        Returns:
            List of ancestor projects, ordered from parent to root
        """
        projects_by_id = {p.id: p for p in self.read_projects()}
        
        if project_id not in projects_by_id:
            return []
        
        ancestors: list[Project] = []
        current = projects_by_id[project_id]
        
        # Walk up the hierarchy
        while current.parent_id is not None:
            if current.parent_id not in projects_by_id:
                # Broken link - stop here
                break
            parent = projects_by_id[current.parent_id]
            ancestors.append(parent)
            current = parent
        
        return ancestors

    def get_project_descendants(self, project_id: str) -> list[Project]:
        """
        Get all descendants (children, grandchildren, etc.) of a project.
        
        Args:
            project_id: Project ID to get descendants for
            
        Returns:
            List of all descendant projects (recursively)
        """
        projects = self.read_projects()
        projects_by_id = {p.id: p for p in projects}
        
        if project_id not in projects_by_id:
            return []
        
        descendants: list[Project] = []
        to_process = [project_id]
        
        while to_process:
            current_id = to_process.pop(0)
            children = [p for p in projects if p.parent_id == current_id]
            descendants.extend(children)
            to_process.extend(p.id for p in children)
        
        return descendants

    def move_project(self, project_id: str, new_parent_id: str | None) -> None:
        """
        Move a project to a new parent (or to root if new_parent_id is None).
        
        Args:
            project_id: Project to move
            new_parent_id: New parent ID, or None to move to root
            
        Raises:
            ValueError: If project doesn't exist or move would create a cycle
        """
        projects = self.read_projects()
        projects_by_id = {p.id: p for p in projects}
        
        if project_id not in projects_by_id:
            raise ValueError(f"Project {project_id} not found")
        
        if new_parent_id is not None and new_parent_id not in projects_by_id:
            raise ValueError(f"Parent project {new_parent_id} not found")
        
        # Check for cycles: new_parent_id cannot be a descendant of project_id
        if new_parent_id is not None:
            descendants = self.get_project_descendants(project_id)
            if any(d.id == new_parent_id for d in descendants):
                raise ValueError("Cannot move project: would create a cycle")
        
        # Update the project
        project = projects_by_id[project_id]
        project.parent_id = new_parent_id
        
        # Reset display_order to append at end of new parent's children
        siblings = [p for p in projects if p.parent_id == new_parent_id and p.id != project_id]
        project.display_order = max([s.display_order for s in siblings], default=-1) + 1
        
        self.write_projects(projects)

    def reorder_projects(self, project_ids: list[str], parent_id: str | None = None) -> None:
        """
        Reorder projects within the same parent level.
        
        Args:
            project_ids: List of project IDs in desired order
            parent_id: Parent ID for these projects (None for root level)
            
        Raises:
            ValueError: If any project doesn't exist or doesn't belong to this parent
        """
        projects = self.read_projects()
        projects_by_id = {p.id: p for p in projects}
        
        # Validate all projects exist and belong to the specified parent
        for pid in project_ids:
            if pid not in projects_by_id:
                raise ValueError(f"Project {pid} not found")
            if projects_by_id[pid].parent_id != parent_id:
                raise ValueError(f"Project {pid} does not belong to parent {parent_id}")
        
        # Update display_order for each project in the list
        for i, pid in enumerate(project_ids):
            projects_by_id[pid].display_order = i
        
        self.write_projects(projects)
    
    def rebuild_search_index(self) -> dict[str, int]:
        """Rebuild the entire search index from scratch.
        
        This method reads all entries, projects, and tasks from storage
        and rebuilds the FTS index. Useful for:
        - Initial index creation
        - Recovering from corrupted index
        - Migrating existing data directories
        
        Returns:
            Statistics dict with counts of indexed items
        """
        logger.info("Rebuilding search index from all data...")
        
        # Load all data
        entries = self.read_entries_meta()
        projects = self.read_projects()
        tasks = self.read_tasks()
        
        # Prepare tasks data with context
        projects_by_id = {p.id: p for p in projects}
        entries_by_id = {e.id: e for e in entries}
        
        tasks_data = []
        for task in tasks:
            project_name = projects_by_id.get(task.project_id, None)
            project_name_str = project_name.name if project_name else None
            
            entry_title = None
            if task.linked_entry_id:
                entry = entries_by_id.get(task.linked_entry_id, None)
                entry_title = entry.title if entry else None
            
            tasks_data.append((task, project_name_str, entry_title))
        
        bodies = {entry.id: self.read_entry_body(entry) for entry in entries}
        self._index_checked = True  # avoid re-entering from _get_search_index
        with SearchIndex(self.index_path) as idx:
            stats = idx.rebuild(entries, projects, tasks_data, bodies)
        logger.info(f"Search index rebuilt: {stats}")
        return stats


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


def _safe_extract_zip(handle: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip archive safely, refusing path traversal entries."""
    base = dest.resolve()
    for member in handle.infolist():
        member_path = dest / member.filename
        resolved = member_path.resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"Unsafe path in backup archive: {member.filename}") from exc
    handle.extractall(dest)


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
            if not ids.is_safe_id(entry.id):
                raise ValueError(f"Invalid entry id {entry.id!r} in entries log")
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


# ===== Calendar Events Methods (NEW) =====
def read_calendar_events(storage: Storage) -> list[CalendarEvent]:
    """Read all calendar events."""
    data = io_utils.read_json(storage.calendar_events_path, default=[])
    events = []
    for item in data:
        event = CalendarEvent(
            id=item["id"],
            subscription_id=item["subscription_id"],
            title=item["title"],
            description=item.get("description"),
            start_date=item.get("start_date", ""),
            end_date=item.get("end_date"),
            start_time=item.get("start_time"),
            end_time=item.get("end_time"),
            location=item.get("location"),
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
            linked_entry_id=item.get("linked_entry_id")
        )
        events.append(event)
    return events


def write_calendar_events(storage: Storage, events: list[CalendarEvent]) -> None:
    """Write calendar events to disk."""
    data = []
    for event in events:
        data.append({
            "id": event.id,
            "subscription_id": event.subscription_id,
            "title": event.title,
            "description": event.description,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "location": event.location,
            "created_at": event.created_at,
            "updated_at": event.updated_at,
            "linked_entry_id": event.linked_entry_id
        })
    io_utils.safe_write_json(storage.calendar_events_path, data)
    logger.info(f"Saved {len(events)} calendar events")


def upsert_calendar_event(storage: Storage, event: CalendarEvent) -> None:
    """Insert or update a calendar event."""
    events = read_calendar_events(storage)
    
    # Find existing event
    existing_idx = None
    for idx, e in enumerate(events):
        if e.id == event.id:
            existing_idx = idx
            break
    
    if existing_idx is not None:
        events[existing_idx] = event
    else:
        events.append(event)
    
    write_calendar_events(storage, events)


def delete_calendar_event(storage: Storage, event_id: str) -> None:
    """Delete a calendar event by ID."""
    events = read_calendar_events(storage)
    events = [e for e in events if e.id != event_id]
    write_calendar_events(storage, events)


def delete_calendar_events_by_subscription(storage: Storage, subscription_id: str) -> None:
    """Delete all events from a specific subscription."""
    events = read_calendar_events(storage)
    events = [e for e in events if e.subscription_id != subscription_id]
    write_calendar_events(storage, events)
    logger.info(f"Deleted all events for subscription {subscription_id}")


def _without_credentials(path: Path) -> str:
    """calendar_subscriptions.json with usernames and passwords removed."""
    try:
        data = io_utils.read_json(path, default=[])
    except (OSError, ValueError):
        return "[]\n"
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item.pop("password", None)
                item.pop("username", None)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
