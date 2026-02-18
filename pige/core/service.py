from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, date, time, timedelta
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Iterable
import uuid

logger = logging.getLogger(__name__)

from pige.core.exceptions import (
    ProjectNotFoundError,
    EntryNotFoundError,
    TaskNotFoundError,
    InvalidEntryTypeError,
    MeetingHoursError,
    TimerAlreadyRunningError,
    TimerNotRunningError,
    BackupFormatError,
)
from pige.core.models import EntryMeta, Project, Task, TimeLog, TimerState
from pige.core.storage import (
    Storage,
    copy_data_dir_contents,
    default_timer_state,
    recap_data_dir,
)
from pige.utils import dates, ids, io as io_utils, strings


VALID_ENTRY_TYPES = ("note", "meeting", "decision", "log")
VALID_CONTEXT_STATUSES = ("created", "actual", "treated")
_UNSET = object()
REDACTED_PLACEHOLDER = "[Content redacted]"


def normalize_context_status(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in VALID_CONTEXT_STATUSES:
        return cleaned
    return "created"


@dataclass
class ThreadSummary:
    project_id: str
    people_key: tuple[str, ...]
    people_label: str
    last_entry_id: str
    last_entry_title: str
    last_entry_date: date
    open_actions: int


class PigeService:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def init_storage(self) -> None:
        self.storage.init_storage()

    def migrate_data_dir(self, dest_dir: Path) -> dict[str, int]:
        if not dest_dir.exists() or not dest_dir.is_dir():
            raise ValueError(f"Destination folder not found: {dest_dir}")
        try:
            if any(dest_dir.iterdir()):
                raise ValueError("Destination folder must be empty")
        except Exception as exc:
            raise ValueError(f"Unable to read destination folder: {exc}") from exc

        src_dir = self.storage.data_dir
        staging = dest_dir.parent / f".pige_migrate_tmp_{uuid.uuid4().hex}"
        if staging.exists():
            raise ValueError(f"Migration staging folder already exists: {staging}")

        keep_staging = False
        try:
            copy_data_dir_contents(src_dir, staging)
            recap = recap_data_dir(staging)
            try:
                dest_dir.rmdir()
            except OSError as exc:
                raise ValueError(f"Destination folder must be empty: {exc}") from exc
            try:
                os.replace(staging, dest_dir)
            except OSError as exc:
                keep_staging = True
                raise ValueError(
                    "Failed to move migrated data into place.\n"
                    f"Staging folder remains at: {staging}\n"
                    f"Error: {exc}"
                ) from exc
        except Exception as exc:
            if staging.exists() and not keep_staging:
                try:
                    shutil.rmtree(staging)
                except Exception:
                    logger.warning("Failed to remove migration staging folder %s", staging, exc_info=True)
                    pass
            if isinstance(exc, ValueError):
                raise
            raise ValueError(str(exc)) from exc
        return recap

    def create_project(
        self,
        name: str,
        description: str | None,
        tags: Iterable[str],
        person: str | None = None,
        group: str | None = None,
        parent_id: str | None = None,
    ) -> Project:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Project name is required")
        
        # Validate parent exists if specified
        if parent_id is not None:
            parent = self._get_project(parent_id)
            # Check maximum depth (prevent excessive nesting)
            parent_depth = self.get_project_depth(parent_id)
            if parent_depth >= 9:  # Parent at depth 9 means child would be at depth 10
                raise ValueError(f"Cannot create project: maximum hierarchy depth (10) exceeded")
        
        clean_person = (person or "").strip() or None
        clean_group = (group or "").strip() or None
        
        # Calculate display_order (append to end of siblings)
        siblings = self.storage.get_project_children(parent_id)
        display_order = max([s.display_order for s in siblings], default=-1) + 1
        
        project = Project(
            id=ids.new_id(),
            name=clean_name,
            description=description,
            status="active",
            tags=list(tags),
            created_at=dates.utc_now_iso(),
            person=clean_person,
            group=clean_group,
            parent_id=parent_id,
            display_order=display_order,
        )
        projects = self.storage.read_projects()
        projects.append(project)
        self.storage.write_projects(projects)
        return project

    def get_project_depth(self, project_id: str) -> int:
        """
        Calculate the depth of a project in the hierarchy.
        Root projects have depth 0, their children depth 1, etc.
        
        Args:
            project_id: Project ID to calculate depth for
            
        Returns:
            Depth level (0 for root)
        """
        ancestors = self.storage.get_project_ancestors(project_id)
        return len(ancestors)

    def move_project(self, project_id: str, new_parent_id: str | None) -> None:
        """
        Move a project to a new parent with validation.
        
        Args:
            project_id: Project to move
            new_parent_id: New parent ID, or None for root
            
        Raises:
            ValueError: If validation fails (cycle, depth, not found)
        """
        # Validate project exists
        project = self._get_project(project_id)
        
        # Validate new parent exists if specified
        if new_parent_id is not None:
            self._get_project(new_parent_id)
            
            # Check depth after move
            new_parent_depth = self.get_project_depth(new_parent_id)
            # Get the maximum depth of any descendant relative to the project being moved
            descendants = self.storage.get_project_descendants(project_id)
            if descendants:
                current_depth = self.get_project_depth(project_id)
                max_descendant_relative_depth = max(
                    [self.get_project_depth(d.id) - current_depth for d in descendants]
                )
            else:
                max_descendant_relative_depth = 0
            
            # New total depth = new parent depth + 1 (for project) + deepest descendant
            new_total_depth = new_parent_depth + 1 + max_descendant_relative_depth
            
            if new_total_depth > 9:  # Max depth is 9 (levels 0-9 = 10 levels)
                raise ValueError(
                    f"Cannot move project: would exceed maximum depth (10). "
                    f"New depth would be {new_total_depth + 1}"
                )
        
        # Delegate to storage (which checks for cycles)
        self.storage.move_project(project_id, new_parent_id)

    def reorder_projects_in_parent(
        self, project_ids: list[str], parent_id: str | None = None
    ) -> None:
        """
        Reorder projects within the same parent level.
        
        Args:
            project_ids: List of project IDs in desired order
            parent_id: Parent ID (None for root level)
        """
        # Validate all projects exist
        for pid in project_ids:
            self._get_project(pid)
        
        # Delegate to storage
        self.storage.reorder_projects(project_ids, parent_id)

    def get_project_tree(self) -> list[dict]:
        """
        Get hierarchical project tree structure.
        
        Returns:
            List of dicts with 'project' and 'children' keys
        """
        def build_tree(parent_id: str | None) -> list[dict]:
            children_projects = self.storage.get_project_children(parent_id)
            result = []
            for child in children_projects:
                result.append({
                    "project": child,
                    "children": build_tree(child.id),
                    "depth": self.get_project_depth(child.id),
                })
            return result
        
        return build_tree(None)

    def list_projects(self, status: str = "active") -> list[Project]:
        projects = self.storage.read_projects()
        if status == "all":
            return projects
        return [project for project in projects if project.status == status]

    def search(
        self, query: str, *, include_body: bool = False
    ) -> tuple[list[Project], list[EntryMeta]]:
        needle = (query or "").strip().lower()
        if not needle:
            return [], []

        projects: list[Project] = []
        for project in self.storage.read_projects():
            haystack = " ".join(
                [
                    project.name,
                    project.description or "",
                    " ".join(project.tags),
                    project.person or "",
                    project.group or "",
                ]
            ).lower()
            if needle in haystack:
                projects.append(project)
        projects.sort(key=lambda item: item.name.lower())

        entries: list[EntryMeta] = []
        for entry in self.storage.read_entries_meta():
            haystack = " ".join(
                [
                    entry.title,
                    " ".join(entry.tags),
                    entry.person or "",
                    entry.group or "",
                ]
            ).lower()
            matched = needle in haystack
            if not matched and include_body:
                body = self.storage.read_entry_body(entry)
                matched = needle in body.lower()
            if matched:
                entries.append(entry)
        entries.sort(key=lambda item: (_entry_local_date(item), item.ts), reverse=True)
        return projects, entries

    def advanced_search(
        self, query: str, *, include_body: bool = False
    ) -> tuple[list[Project], list[EntryMeta]]:
        """Advanced search with field-specific filters.
        
        Supports queries like:
        - tag:alpha person:John type:meeting
        - date:>=2024-01-01 date:<=2024-12-31
        - person:"Jane Doe" status:actual
        
        Args:
            query: Search query with field:value syntax
            include_body: If True, also search in entry body content
            
        Returns:
            Tuple of (matching_projects, matching_entries)
        """
        from pige.core.search import parse_search_query, apply_search_filters
        
        if not query or not query.strip():
            return [], []
        
        # Parse the query
        filters = parse_search_query(query)
        
        # For projects, use basic search on free text if present
        projects: list[Project] = []
        if filters.free_text:
            needle = filters.free_text.lower()
            for project in self.storage.read_projects():
                haystack = " ".join(
                    [
                        project.name,
                        project.description or "",
                        " ".join(project.tags),
                        project.person or "",
                        project.group or "",
                    ]
                ).lower()
                if needle in haystack:
                    projects.append(project)
            projects.sort(key=lambda item: item.name.lower())
        
        # For entries, apply structured filters
        entries = self.storage.read_entries_meta()
        entries = apply_search_filters(entries, filters)
        
        # If include_body is True and there's free text, also search in body
        if include_body and filters.free_text:
            needle = filters.free_text.lower()
            filtered_entries = []
            for entry in entries:
                body = self.storage.read_entry_body(entry)
                if needle in body.lower():
                    filtered_entries.append(entry)
            entries = filtered_entries
        
        entries.sort(key=lambda item: (_entry_local_date(item), item.ts), reverse=True)
        return projects, entries

    def update_project(
        self,
        project_id: str,
        name: str,
        description: str | None,
        tags: Iterable[str],
        person: str | None,
        group: str | None,
        status: str,
        links: Iterable[str] | str | None | object = _UNSET,
    ) -> Project:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Project name is required")
        if status not in ("active", "archived"):
            raise ValueError(
                f"Invalid status {status}. Valid statuses: active, archived"
            )
        clean_person = (person or "").strip() or None
        clean_group = (group or "").strip() or None
        clean_description = (description or "").strip() or None

        projects = self.storage.read_projects()
        updated: Project | None = None
        for idx, project in enumerate(projects):
            if project.id != project_id:
                continue
            if links is _UNSET:
                clean_links = list(project.links or [])
            else:
                clean_links = _normalize_project_links(links)
            updated = Project(
                id=project.id,
                name=clean_name,
                description=clean_description,
                status=status,
                tags=list(tags),
                created_at=project.created_at or dates.utc_now_iso(),
                person=clean_person,
                group=clean_group,
                links=clean_links,
            )
            projects[idx] = updated
            break
        if updated is None:
            raise ProjectNotFoundError(project_id)
        self.storage.write_projects(projects)
        return updated

    def delete_project(self, project_id: str) -> None:
        projects = self.storage.read_projects()
        project = next((item for item in projects if item.id == project_id), None)
        if not project:
            raise ProjectNotFoundError(project_id)

        delete_ts = dates.utc_now_iso()
        entries = [
            entry
            for entry in self.storage.read_entries_meta()
            if entry.project_id == project_id
        ]
        for entry in entries:
            entry_path = self.storage.data_dir / entry.content_path
            if entry_path.exists():
                entry_path.unlink()
            self.storage.append_entry_delete(entry.id, delete_ts)

        tasks = self.storage.read_tasks()
        remaining_tasks = [task for task in tasks if task.project_id != project_id]
        if len(remaining_tasks) != len(tasks):
            self.storage.write_tasks(remaining_tasks)

        timelogs = self.storage.read_timelogs()
        remaining_logs = [log for log in timelogs if log.project_id != project_id]
        if len(remaining_logs) != len(timelogs):
            self.storage.write_timelogs(remaining_logs)

        timer_state = self.storage.read_timer_state()
        if timer_state.project_id == project_id:
            self.storage.write_timer_state(default_timer_state())

        remaining_projects = [item for item in projects if item.id != project_id]
        self.storage.write_projects(remaining_projects)


    def list_tasks(self, project_id: str, status: str = "open") -> list[Task]:
        self._ensure_project_exists(project_id)
        if status not in ("open", "in_progress", "done", "all"):
            raise ValueError(
                "Invalid task status. Valid statuses: open, in_progress, done, all"
            )
        tasks = [task for task in self.storage.read_tasks() if task.project_id == project_id]
        if status != "all":
            tasks = [task for task in tasks if task.status == status]
            tasks.sort(key=_task_sort_key)
            return tasks
        tasks.sort(key=_task_sort_key)
        return tasks

    def list_in_progress_threads(self, *, days: int = 14) -> list[ThreadSummary]:
        try:
            days_value = int(days)
        except (TypeError, ValueError):
            days_value = 14

        entries = self.storage.read_entries_meta()
        if not entries:
            return []

        today = datetime.now().astimezone().date()
        thread_state: dict[tuple[str, tuple[str, ...]], dict[str, object]] = {}
        entry_to_thread: dict[str, tuple[str, tuple[str, ...]]] = {}

        for entry in entries:
            people = strings.split_people(entry.person)
            if people:
                people_key = tuple(sorted({person.lower() for person in people}))
            else:
                people_key = ("__none__",)
            thread_key = (entry.project_id, people_key)
            entry_to_thread[entry.id] = thread_key

            entry_date = _entry_local_date(entry)
            entry_key = (entry_date, entry.ts)
            state = thread_state.get(thread_key)
            if state is None:
                thread_state[thread_key] = {
                    "last_entry": entry,
                    "last_key": entry_key,
                    "display_map": {person.lower(): person for person in people},
                }
                continue

            display_map = state["display_map"]
            if isinstance(display_map, dict):
                for person in people:
                    key = person.lower()
                    if key not in display_map:
                        display_map[key] = person
            last_key = state.get("last_key", entry_key)
            if isinstance(last_key, tuple) and entry_key > last_key:
                state["last_entry"] = entry
                state["last_key"] = entry_key

        open_counts: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
        for task in self.storage.read_tasks():
            if task.status not in ("open", "in_progress"):
                continue
            if not task.linked_entry_id:
                continue
            thread_key = entry_to_thread.get(task.linked_entry_id)
            if not thread_key:
                continue
            open_counts[thread_key] += 1

        def build_people_label(
            people_key: tuple[str, ...], display_map: dict[str, str]
        ) -> str:
            if people_key == ("__none__",):
                return ""
            labels: list[str] = []
            for key in people_key:
                if key == "__none__":
                    continue
                label = display_map.get(key)
                if not label:
                    label = key.title()
                labels.append(label)
            return ", ".join(labels)

        summaries: list[tuple[ThreadSummary, str]] = []
        for thread_key, state in thread_state.items():
            last_entry = state.get("last_entry")
            last_key = state.get("last_key")
            display_map = state.get("display_map")
            if not isinstance(last_entry, EntryMeta) or not isinstance(last_key, tuple):
                continue
            if not isinstance(display_map, dict):
                display_map = {}
            last_date = last_key[0]
            last_ts = last_key[1]
            open_actions = open_counts.get(thread_key, 0)
            active_recent = (today - last_date).days <= days_value
            if not (active_recent or open_actions > 0):
                continue
            people_label = build_people_label(thread_key[1], display_map)
            summaries.append(
                (
                    ThreadSummary(
                        project_id=thread_key[0],
                        people_key=thread_key[1],
                        people_label=people_label,
                        last_entry_id=last_entry.id,
                        last_entry_title=last_entry.title,
                        last_entry_date=last_date,
                        open_actions=open_actions,
                    ),
                    last_ts,
                )
            )

        summaries.sort(key=lambda item: (item[0].last_entry_date, item[1]), reverse=True)
        return [summary for summary, _ts in summaries]

    def create_task(
        self,
        project_id: str,
        title: str,
        tags: Iterable[str],
        note: str | None,
        linked_entry_id: str | None,
        due_date: str | None = None,
    ) -> Task:
        self._ensure_project_exists(project_id)
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Task title is required")
        clean_tags = _clean_task_tags(tags)
        clean_note = (note or "").strip() or None
        clean_due_date = _normalize_due_date(due_date)
        task = Task(
            id=ids.new_id(),
            project_id=project_id,
            title=clean_title,
            status="open",
            created_at=dates.utc_now_iso(),
            done_at=None,
            due_date=clean_due_date,
            tags=clean_tags,
            linked_entry_id=linked_entry_id,
            note=clean_note,
        )
        tasks = self.storage.read_tasks()
        tasks.append(task)
        self.storage.write_tasks(tasks)
        return task

    def update_task(self, task_id: str, patch: dict[str, object]) -> Task:
        if not isinstance(patch, dict):
            raise ValueError("Task patch must be a dict")
        allowed = {"title", "tags", "note", "due_date", "status"}
        unknown = set(patch.keys()) - allowed
        if unknown:
            raise ValueError(f"Invalid task patch keys: {sorted(unknown)}")
        tasks = self.storage.read_tasks()
        updated: Task | None = None
        for idx, task in enumerate(tasks):
            if task.id != task_id:
                continue
            title = task.title
            if "title" in patch:
                title = str(patch["title"] or "").strip()
                if not title:
                    raise ValueError("Task title is required")
            tags = task.tags
            if "tags" in patch:
                raw_tags = patch.get("tags") or []
                tags = _clean_task_tags(raw_tags)
            note = task.note
            if "note" in patch:
                note = (str(patch["note"]) if patch["note"] is not None else "").strip() or None
            due_date = task.due_date
            if "due_date" in patch:
                due_date = _normalize_due_date(patch.get("due_date"))
            status = task.status
            done_at = task.done_at
            if "status" in patch:
                status = str(patch.get("status") or "").strip()
                if status not in ("open", "in_progress", "done"):
                    raise ValueError(
                        "Invalid task status. Valid statuses: open, in_progress, done"
                    )
                if status == "done":
                    done_at = task.done_at or dates.utc_now_iso()
                else:
                    done_at = None
            updated = Task(
                id=task.id,
                project_id=task.project_id,
                title=title,
                status=status,
                created_at=task.created_at,
                done_at=done_at,
                due_date=due_date,
                tags=tags,
                linked_entry_id=task.linked_entry_id,
                note=note,
            )
            tasks[idx] = updated
            break
        if updated is None:
            raise ValueError(f"Task {task_id} not found")
        self.storage.write_tasks(tasks)
        return updated

    def set_task_done(self, task_id: str, done: bool) -> Task:
        tasks = self.storage.read_tasks()
        updated: Task | None = None
        for idx, task in enumerate(tasks):
            if task.id != task_id:
                continue
            if done:
                status = "done"
                done_at = dates.utc_now_iso()
            else:
                status = "open"
                done_at = None
            updated = Task(
                id=task.id,
                project_id=task.project_id,
                title=task.title,
                status=status,
                created_at=task.created_at,
                done_at=done_at,
                due_date=task.due_date,
                tags=list(task.tags),
                linked_entry_id=task.linked_entry_id,
                note=task.note,
            )
            tasks[idx] = updated
            break
        if updated is None:
            raise ValueError(f"Task {task_id} not found")
        self.storage.write_tasks(tasks)
        return updated

    def delete_task(self, task_id: str) -> None:
        tasks = self.storage.read_tasks()
        remaining = [task for task in tasks if task.id != task_id]
        if len(remaining) == len(tasks):
            raise ValueError(f"Task {task_id} not found")
        self.storage.write_tasks(remaining)

    def backup_data(self, out_path: str | None = None) -> str:
        if out_path:
            path = Path(out_path)
        else:
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            path = self.storage.exports_dir / f"backup_{timestamp}.zip"
        output = self.storage.create_backup(path)
        return str(output)

    def restore_data(self, zip_path: str) -> None:
        self.storage.restore_backup(Path(zip_path))

    def compact_entries(self) -> dict[str, int]:
        """
        Compact entries.jsonl to a snapshot (one line per current entry).
        Removes update/delete history; reduces file size and load time.
        Returns dict with before_lines, after_lines, entries_count.
        """
        return self.storage.compact_entries_log()

    def add_entry(
        self,
        project_id: str,
        entry_type: str,
        title: str,
        tags: Iterable[str],
        body: str | None,
        entry_date: date | None = None,
        person: str | None = None,
        group: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        decision_done: bool | None = None,
    ) -> tuple[EntryMeta, Path]:
        project = self._get_project(project_id)
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Entry title is required")
        if entry_type not in VALID_ENTRY_TYPES:
            raise InvalidEntryTypeError(entry_type, VALID_ENTRY_TYPES)
        if decision_done is not None and entry_type != "decision":
            raise ValueError("Decision flag only valid for decision entries")
        if decision_done is not None and not isinstance(decision_done, bool):
            raise ValueError("Decision flag must be a boolean")
        normalized_start = _normalize_time(start_time)
        normalized_end = _normalize_time(end_time)
        if entry_type != "meeting" and (normalized_start or normalized_end):
            raise ValueError("Meeting hours only valid for meeting entries")
        if normalized_start and normalized_end:
            start_dt = datetime.strptime(normalized_start, "%H:%M")
            end_dt = datetime.strptime(normalized_end, "%H:%M")
            if start_dt > end_dt:
                raise MeetingHoursError("Meeting start must be before end")
        entry_date_value = entry_date or datetime.now().astimezone().date()
        if entry_date is not None:
            ts_value = dates.local_date_midday_to_utc_z(entry_date_value)
        else:
            ts_value = dates.utc_now_iso()
        entry_id = ids.new_id()
        content_path = f"entries/{entry_id}.md"
        entry_person = (person or "").strip() or project.person
        entry_group = (group or "").strip() or project.group
        entry = EntryMeta(
            id=entry_id,
            ts=ts_value,
            project_id=project.id,
            type=entry_type,
            title=clean_title,
            tags=list(tags),
            content_path=content_path,
            entry_date=entry_date_value.isoformat(),
            person=entry_person,
            group=entry_group,
            start_time=normalized_start,
            end_time=normalized_end,
            decision_done=decision_done if entry_type == "decision" else None,
        )
        self.storage.append_entry_event(entry)
        content = body or ""
        md_path = self.storage.write_entry_content(entry_id, content)
        return entry, md_path

    def update_entry_content(self, entry_id: str, content: str) -> Path:
        entries = {entry.id: entry for entry in self.storage.read_entries_meta()}
        if entry_id not in entries:
            raise ValueError(f"Entry {entry_id} not found")
        return self.storage.write_entry_content(entry_id, content)

    def update_entry_meta(
        self,
        entry_id: str,
        *,
        title: str | None | object = _UNSET,
        tags: Iterable[str] | None | object = _UNSET,
        entry_date: date | str | None | object = _UNSET,
        person: str | None | object = _UNSET,
        group: str | None | object = _UNSET,
        start_time: str | None | object = _UNSET,
        end_time: str | None | object = _UNSET,
        decision_done: bool | None | object = _UNSET,
    ) -> EntryMeta:
        entries = {entry.id: entry for entry in self.storage.read_entries_meta()}
        entry = entries.get(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")

        patch: dict[str, object] = {}
        if title is not _UNSET:
            clean_title = (title or "").strip()
            if not clean_title:
                raise ValueError("Entry title is required")
            patch["title"] = clean_title
        if tags is not _UNSET:
            patch["tags"] = list(tags) if tags is not None else []
        if entry_date is not _UNSET:
            if entry_date is None:
                patch["entry_date"] = None
            elif isinstance(entry_date, date):
                patch["entry_date"] = entry_date.isoformat()
            elif isinstance(entry_date, str):
                parsed = dates.parse_date(entry_date)
                patch["entry_date"] = parsed.isoformat()
            else:
                raise ValueError("Invalid entry_date")
        if person is not _UNSET:
            patch["person"] = (person or "").strip() or None
        if group is not _UNSET:
            patch["group"] = (group or "").strip() or None
        if start_time is not _UNSET:
            patch["start_time"] = _normalize_time(start_time)
        if end_time is not _UNSET:
            patch["end_time"] = _normalize_time(end_time)
        if decision_done is not _UNSET:
            if decision_done is not None and not isinstance(decision_done, bool):
                raise ValueError("Decision flag must be a boolean")
            patch["decision_done"] = decision_done

        if patch:
            _validate_entry_patch(entry, patch)
            self.storage.append_entry_update(entry_id, dates.utc_now_iso(), patch)
        updated = {item.id: item for item in self.storage.read_entries_meta()}
        if entry_id not in updated:
            raise ValueError(f"Entry {entry_id} not found")
        return updated[entry_id]

    def set_entry_context_status(self, entry_id: str, status: str | None) -> EntryMeta:
        cleaned = (status or "").strip().lower()
        if not cleaned:
            normalized = "created"
        elif cleaned not in VALID_CONTEXT_STATUSES:
            valid = ", ".join(VALID_CONTEXT_STATUSES)
            raise ValueError(
                f"Invalid context status {status}. Valid statuses: {valid}"
            )
        else:
            normalized = cleaned

        entries = {entry.id: entry for entry in self.storage.read_entries_meta()}
        entry = entries.get(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")

        stored_status = None if normalized == "created" else normalized
        patch = {"context_status": stored_status}
        _validate_entry_patch(entry, patch)
        self.storage.append_entry_update(entry_id, dates.utc_now_iso(), patch)
        updated = {item.id: item for item in self.storage.read_entries_meta()}
        if entry_id not in updated:
            raise ValueError(f"Entry {entry_id} not found")
        return updated[entry_id]

    def list_in_progress_entries(
        self,
        *,
        include_created: bool = False,
        include_treated: bool = False,
    ) -> list[EntryMeta]:
        entries = self.storage.read_entries_meta()
        filtered: list[EntryMeta] = []
        for entry in entries:
            status = normalize_context_status(getattr(entry, "context_status", None))
            if status == "actual":
                filtered.append(entry)
            elif status == "created" and include_created:
                filtered.append(entry)
            elif status == "treated" and include_treated:
                filtered.append(entry)
        filtered.sort(key=lambda item: (_entry_local_date(item), item.ts), reverse=True)
        return filtered

    def count_open_actions_by_entry(self, entry_ids: list[str]) -> dict[str, int]:
        if not entry_ids:
            return {}
        entry_set = set(entry_ids)
        counts: dict[str, int] = defaultdict(int)
        for task in self.storage.read_tasks():
            if task.status not in ("open", "in_progress"):
                continue
            entry_id = task.linked_entry_id
            if not entry_id or entry_id not in entry_set:
                continue
            counts[entry_id] += 1
        return dict(counts)

    def extract_followup_tasks(self, entry_id: str) -> list[str]:
        entry = self.storage.get_entry(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")
        body = self.storage.read_entry_body(entry)
        if not body:
            return []
        titles: list[str] = []
        seen: set[str] = set()
        checklist_re = re.compile(r"^\s*-\s*\[\s*\]\s+(.+)$")
        action_re = re.compile(r"^\s*(ACTION|TODO)\s*:\s*(.+)$", re.IGNORECASE)
        for line in body.splitlines():
            match = checklist_re.match(line)
            if match:
                title = match.group(1).strip()
            else:
                match = action_re.match(line)
                if not match:
                    continue
                title = match.group(2).strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
        return titles

    def create_followup_tasks(self, entry_id: str, titles: list[str]) -> list[Task]:
        entry = self.storage.get_entry(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")
        created: list[Task] = []
        for raw_title in titles:
            title = str(raw_title or "").strip()
            if not title:
                continue
            task = self.create_task(
                entry.project_id,
                title,
                [],
                None,
                entry.id,
                None,
            )
            created.append(task)
        return created

    def move_entry(
        self,
        entry_id: str,
        new_project_id: str,
        *,
        keep_tags: bool = True,
        keep_people: bool = True,
    ) -> EntryMeta:
        entries = {entry.id: entry for entry in self.storage.read_entries_meta()}
        entry = entries.get(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")
        self._ensure_project_exists(new_project_id)
        if entry.project_id == new_project_id:
            raise ValueError("Entry is already in that project")

        patch: dict[str, object] = {"project_id": new_project_id}
        if not keep_tags:
            patch["tags"] = []
        if not keep_people:
            patch["person"] = None
            patch["group"] = None
        _validate_entry_patch(entry, patch)
        self.storage.append_entry_update(entry_id, dates.utc_now_iso(), patch)

        updated = {item.id: item for item in self.storage.read_entries_meta()}
        if entry_id not in updated:
            raise ValueError(f"Entry {entry_id} not found")
        return updated[entry_id]

    def delete_entry(self, entry_id: str) -> None:
        entries = {entry.id: entry for entry in self.storage.read_entries_meta()}
        entry = entries.get(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")
        entry_path = self.storage.data_dir / entry.content_path
        if entry_path.exists():
            entry_path.unlink()
        self.storage.append_entry_delete(entry_id, dates.utc_now_iso())

    def log_today(self) -> list[tuple[Project, list[EntryMeta]]]:
        start_utc, end_utc = dates.local_day_range_utc()
        entries = self.storage.read_entries_meta()
        project_map = {project.id: project for project in self.storage.read_projects()}
        grouped: dict[str, list[EntryMeta]] = defaultdict(list)
        for entry in entries:
            entry_dt = dates.parse_utc_z(entry.ts)
            if start_utc <= entry_dt <= end_utc:
                grouped[entry.project_id].append(entry)
        output: list[tuple[Project, list[EntryMeta]]] = []
        for project_id, entry_list in grouped.items():
            project = project_map.get(project_id)
            if project is None:
                continue
            entry_list.sort(key=lambda item: item.ts)
            output.append((project, entry_list))
        output.sort(key=lambda item: item[0].name)
        return output

    def time_start(self, project_id: str, note: str | None) -> Project:
        state = self.storage.read_timer_state()
        if state.running:
            running_id = state.project_id or "unknown"
            raise TimerAlreadyRunningError(running_id)
        project = self._get_project(project_id)
        new_state = TimerState(
            running=True,
            project_id=project.id,
            start_ts=dates.utc_now_iso(),
            note=note,
        )
        self.storage.write_timer_state(new_state)
        return project

    def time_stop(self, create_activity: bool = False) -> tuple[TimeLog, Project]:
        state = self.storage.read_timer_state()
        if not state.running:
            raise TimerNotRunningError()
        if not state.project_id or not state.start_ts:
            raise ValueError("Timer state is invalid")
        project = self._get_project(state.project_id)
        start_dt = dates.parse_utc_z(state.start_ts)
        end_dt = datetime.now(timezone.utc).replace(microsecond=0)
        duration_sec = int((end_dt - start_dt).total_seconds())
        duration_min = duration_sec // 60
        timelog = TimeLog(
            id=ids.new_id(),
            project_id=project.id,
            start=start_dt.strftime(dates.UTC_Z_FORMAT),
            end=end_dt.strftime(dates.UTC_Z_FORMAT),
            duration_sec=duration_sec,
            duration_min=duration_min,
            note=state.note,
            tags=[],
        )
        self.storage.append_timelog(timelog)
        self.storage.write_timer_state(default_timer_state())
        if create_activity:
            self._create_activity_entry(project, start_dt, end_dt, duration_sec, state.note)
        return timelog, project

    def add_manual_time(
        self,
        project_id: str,
        duration_sec: int,
        day: date | str | None,
        note: str | None,
        create_activity: bool = False,
    ) -> TimeLog:
        state = self.storage.read_timer_state()
        if state.running:
            raise ValueError("Timer is running")
        project = self._get_project(project_id)

        try:
            duration_value = int(duration_sec)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid duration") from exc
        if duration_value <= 0:
            raise ValueError("Duration must be greater than zero")

        if day is None:
            day_value = datetime.now().astimezone().date()
        elif isinstance(day, datetime):
            day_value = day.date()
        elif isinstance(day, date):
            day_value = day
        elif isinstance(day, str):
            day_value = dates.parse_date(day)
        else:
            raise ValueError("Invalid day")

        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        start_local = datetime.combine(day_value, time(12, 0), tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc).replace(microsecond=0)
        end_utc = (start_utc + timedelta(seconds=duration_value)).replace(microsecond=0)
        duration_min = duration_value // 60
        clean_note = (note or "").strip() or None

        timelog = TimeLog(
            id=ids.new_id(),
            project_id=project.id,
            start=start_utc.strftime(dates.UTC_Z_FORMAT),
            end=end_utc.strftime(dates.UTC_Z_FORMAT),
            duration_sec=duration_value,
            duration_min=duration_min,
            note=clean_note,
            tags=[],
        )
        self.storage.append_timelog(timelog)
        if create_activity:
            self._create_activity_entry(
                project, start_utc, end_utc, duration_value, clean_note
            )
        return timelog

    def time_today(self) -> dict[str, int]:
        start_utc, end_utc = dates.local_day_range_utc()
        totals: dict[str, int] = defaultdict(int)
        for log in self.storage.read_timelogs():
            start_dt = dates.parse_utc_z(log.start)
            if start_utc <= start_dt <= end_utc:
                totals[log.project_id] += _timelog_duration_sec(log)
        return dict(totals)

    def export_project_raw(
        self,
        project_id: str,
        from_date: date | None,
        to_date: date | None,
        out_path: Path | None,
        *,
        redact_bodies: bool = False,
    ) -> tuple[Path, list[str]]:
        project = self._get_project(project_id)
        entries = [
            entry
            for entry in self.storage.read_entries_meta()
            if entry.project_id == project_id
        ]
        start_utc = None
        end_utc = None
        if from_date and to_date:
            start_utc, end_utc = dates.local_date_range_to_utc(from_date, to_date)
        elif from_date:
            start_utc, _ = dates.local_date_range_to_utc(from_date, from_date)
        elif to_date:
            _, end_utc = dates.local_date_range_to_utc(to_date, to_date)
        filtered: list[EntryMeta] = []
        for entry in entries:
            entry_dt = dates.parse_utc_z(entry.ts)
            if start_utc and entry_dt < start_utc:
                continue
            if end_utc and entry_dt > end_utc:
                continue
            filtered.append(entry)
        filtered.sort(key=lambda item: item.ts)
        from_label = from_date.isoformat() if from_date else "all"
        to_label = to_date.isoformat() if to_date else "all"
        export_name = strings.sanitize_project_name(project.name)
        if out_path is None:
            out_path = (
                self.storage.exports_dir
                / f"{export_name}_{from_label}_{to_label}.md"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        lines: list[str] = [
            f"# {project.name}",
            "",
            f"**Status:** {project.status}",
            f"**Tags:** {strings.format_tags(project.tags)}",
            f"**Export range:** {from_label} -> {to_label}",
            f"**Generated:** {dates.local_now_iso()}",
            "",
            "---",
            "",
        ]
        task_lines = _format_tasks_section(self.list_tasks(project_id, status="all"))
        lines.extend(task_lines)
        lines.append("")
        if not filtered:
            lines.append("No entries in date range.")
            content = "\n".join(lines)
            io_utils.safe_write_text(out_path, content)
            return out_path, warnings
        for entry in filtered:
            entry_dt = dates.parse_utc_z(entry.ts).astimezone()
            date_label = entry.entry_date or entry_dt.date().isoformat()
            time_label = entry_dt.time().strftime("%H:%M:%S")
            lines.extend(
                [
                    f"## {date_label} {time_label} - {entry.type} - {entry.title}",
                    "",
                    f"- **Date:** {date_label}",
                    f"- **Tags:** {strings.format_tags(entry.tags)}",
                    *(
                        [f"- **Person:** {entry.person}"]
                        if entry.person
                        else []
                    ),
                    *(
                        [f"- **Group:** {entry.group}"]
                        if entry.group
                        else []
                    ),
                    *(
                        [
                            f"- **Meeting hours:** {entry.start_time} - {entry.end_time}"
                        ]
                        if entry.type == "meeting"
                        and entry.start_time
                        and entry.end_time
                        else []
                    ),
                    *(
                        [
                            f"- **Decision done:** {'Yes' if entry.decision_done else 'No'}"
                        ]
                        if entry.type == "decision" and entry.decision_done is not None
                        else []
                    ),
                    f"- **Entry ID:** {entry.id}",
                    f"- **Source:** {entry.content_path}",
                    "",
                ]
            )
            content_path = self.storage.data_dir / entry.content_path
            if content_path.exists():
                if redact_bodies:
                    lines.append(REDACTED_PLACEHOLDER)
                else:
                    lines.append(self.storage.read_entry_content(content_path))
            else:
                warnings.append(f"Missing content file for entry {entry.id}")
                lines.append(f"[Content file missing: {entry.content_path}]")
            lines.extend(["", "---", ""])
        content = "\n".join(lines)
        io_utils.safe_write_text(out_path, content)
        return out_path, warnings

    def export_project_narrative(
        self,
        project_id: str,
        from_date: date | None,
        to_date: date | None,
        out_path: Path | None,
        *,
        redact_bodies: bool = False,
    ) -> Path:
        """
        SPEC: Narrative Markdown export
        1) Front-matter with # Project, period, generated, tags/status
        2) ## Resume with counts/aggregates only (entry counts, type breakdown, total time if timelogs)
        3) ## Objectifs placeholder TODO
        4) ## Decisions with full content for decision entries
        5) ## Chronologie with full content for all entries
        6) ## Temps with simple tables per day + total, or mention "Aucun timelog"
        7) ## Annexes listing sources entries/<id>.md
        Rules: filter from/to inclusive, display local times, placeholder if md missing + warning.
        """
        project = self._get_project(project_id)
        entries = [
            entry
            for entry in self.storage.read_entries_meta()
            if entry.project_id == project_id
        ]
        start_utc = None
        end_utc = None
        if from_date and to_date:
            start_utc, end_utc = dates.local_date_range_to_utc(from_date, to_date)
        elif from_date:
            start_utc, _ = dates.local_date_range_to_utc(from_date, from_date)
        elif to_date:
            _, end_utc = dates.local_date_range_to_utc(to_date, to_date)
        filtered: list[EntryMeta] = []
        for entry in entries:
            entry_dt = dates.parse_utc_z(entry.ts)
            if start_utc and entry_dt < start_utc:
                continue
            if end_utc and entry_dt > end_utc:
                continue
            filtered.append(entry)
        filtered.sort(key=lambda item: (_entry_local_date(item), item.ts))

        from_label = _format_date_ddmmyyyy(from_date) if from_date else "all"
        to_label = _format_date_ddmmyyyy(to_date) if to_date else "all"
        period_label = f"{from_label} → {to_label}"
        export_name = strings.sanitize_project_name(project.name)
        if out_path is None:
            out_path = (
                self.storage.exports_dir
                / f"{export_name}_narrative_{from_label}_{to_label}.md"
            )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = [
            f"# {project.name}",
            "",
            f"**Period:** {period_label}",
            f"**Generated:** {dates.local_now_iso()}",
            f"**Status:** {project.status}",
            f"**Tags:** {strings.format_tags(project.tags)}",
            "",
            "---",
            "",
            "## Résumé",
            "",
        ]

        # Counts by type
        type_counts: dict[str, int] = defaultdict(int)
        for entry in filtered:
            type_counts[entry.type] = type_counts.get(entry.type, 0) + 1
        lines.append(f"- Total entries: {len(filtered)}")
        for etype in VALID_ENTRY_TYPES:
            count = type_counts.get(etype, 0)
            if count:
                lines.append(f"- {etype.capitalize()}: {count}")
        total_time_sec = 0
        if from_date and to_date:
            start_utc_r, end_utc_r = dates.local_date_range_to_utc(from_date, to_date)
            for log in self.storage.read_timelogs():
                if log.project_id != project_id:
                    continue
                try:
                    start_dt = dates.parse_utc_z(log.start)
                except Exception:
                    continue
                if start_dt < start_utc_r or start_dt > end_utc_r:
                    continue
                total_time_sec += _timelog_duration_sec(log)
        else:
            for log in self.storage.read_timelogs():
                if log.project_id == project_id:
                    total_time_sec += _timelog_duration_sec(log)
        if total_time_sec > 0:
            lines.append(f"- Total time: {_format_duration_hms(total_time_sec)}")
        lines.extend(["", "## Objectifs", "", "_TODO_", "", "---", ""])

        # ## Decisions
        decisions = [e for e in filtered if e.type == "decision"]
        lines.extend(["## Décisions", ""])
        if not decisions:
            lines.append("_Aucune entrée de type décision sur la période._")
            lines.append("")
        else:
            for entry in decisions:
                lines.extend([
                    f"### {entry.title}",
                    f"*{_format_date_ddmmyyyy(_entry_local_date(entry))}*",
                    "",
                ])
                content_path = self.storage.data_dir / entry.content_path
                if content_path.exists():
                    if redact_bodies:
                        lines.append(REDACTED_PLACEHOLDER)
                    else:
                        lines.append(self.storage.read_entry_content(content_path))
                else:
                    lines.append("[Fichier contenu manquant]")
                lines.extend(["", "---", ""])
        lines.append("")

        # ## Chronologie
        lines.extend(["## Chronologie", ""])
        if not filtered:
            lines.append("_Aucune entrée sur la période._")
            lines.append("")
        else:
            for entry in filtered:
                date_label = _format_date_ddmmyyyy(_entry_local_date(entry))
                time_label = _entry_time_label(entry)
                title_part = f"**{entry.title}** ({entry.type})"
                if time_label:
                    lines.append(f"### {date_label} {time_label} — {title_part}")
                else:
                    lines.append(f"### {date_label} — {title_part}")
                lines.append("")
                content_path = self.storage.data_dir / entry.content_path
                if content_path.exists():
                    if redact_bodies:
                        lines.append(REDACTED_PLACEHOLDER)
                    else:
                        lines.append(self.storage.read_entry_content(content_path))
                else:
                    lines.append("[Fichier contenu manquant]")
                lines.extend(["", "---", ""])
        lines.append("")

        # ## Temps
        lines.extend(["## Temps", ""])
        project_logs = [log for log in self.storage.read_timelogs() if log.project_id == project_id]
        if from_date and to_date:
            start_utc_t, end_utc_t = dates.local_date_range_to_utc(from_date, to_date)
            project_logs = [
                log for log in project_logs
                if start_utc_t <= dates.parse_utc_z(log.start) <= end_utc_t
            ]
        if not project_logs:
            lines.append("_Aucun timelog._")
            lines.append("")
        else:
            day_to_logs: dict[date, list[TimeLog]] = defaultdict(list)
            for log in project_logs:
                try:
                    start_dt = dates.parse_utc_z(log.start).astimezone()
                    day_to_logs[start_dt.date()].append(log)
                except Exception:
                    continue
            total_sec = 0
            for day in sorted(day_to_logs.keys()):
                day_logs = day_to_logs[day]
                day_sec = sum(_timelog_duration_sec(l) for l in day_logs)
                total_sec += day_sec
                lines.append(f"### {_format_date_ddmmyyyy(day)}")
                lines.append("")
                lines.append("| Début | Fin | Durée | Note |")
                lines.append("|-------|-----|-------|------|")
                for log in sorted(day_logs, key=lambda l: l.start):
                    try:
                        start_dt = dates.parse_utc_z(log.start).astimezone()
                        end_dt = dates.parse_utc_z(log.end).astimezone()
                        start_str = start_dt.strftime("%H:%M")
                        end_str = end_dt.strftime("%H:%M")
                    except Exception:
                        start_str = log.start
                        end_str = log.end or ""
                    dur = _timelog_duration_sec(log)
                    note = (log.note or "").replace("|", "\\|")
                    lines.append(f"| {start_str} | {end_str} | {_format_duration_hms(dur)} | {note} |")
                lines.append("")
                lines.append(f"**Sous-total jour:** {_format_duration_hms(day_sec)}")
                lines.append("")
            lines.append(f"**Total:** {_format_duration_hms(total_sec)}")
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.extend(["## Annexes", "", "Sources (fichiers entrées):", ""])
        for entry in filtered:
            lines.append(f"- `{entry.content_path}`")
        lines.append("")

        content = "\n".join(lines).rstrip() + "\n"
        io_utils.safe_write_text(out_path, content)
        return out_path

    def export_meeting_minutes(
        self,
        entry_id: str,
        out_path: str | None = None,
        *,
        include_decisions: bool = True,
        include_tasks: bool = True,
        window_days: int = 1,
        internal: bool = False,
        redact_bodies: bool = False,
    ) -> str:
        entry = self.storage.get_entry(entry_id)
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")
        if entry.type != "meeting":
            raise ValueError("Entry is not a meeting")
        project = self._get_project(entry.project_id)
        meeting_date = _entry_local_date(entry)
        meeting_date_label = _format_date_ddmmyyyy(meeting_date)
        time_label = _format_meeting_time(entry)
        person_group = " ".join(
            [part for part in [entry.person, entry.group] if part]
        ).strip()
        if redact_bodies:
            body = REDACTED_PLACEHOLDER
        else:
            body = self.storage.read_entry_body(entry)
            if not body.strip():
                body = "_No notes._"

        lines: list[str] = [
            f"# {project.name}",
            "",
            f"**Date:** {meeting_date_label}",
            f"**Title:** {entry.title}",
        ]
        if time_label:
            lines.append(f"**Time:** {time_label}")
        if person_group:
            lines.append(f"**Person/Group:** {person_group}")
        lines.extend(["", "## Notes / Compte-rendu", "", body, ""])

        related_decisions: list[EntryMeta] = []
        if include_decisions:
            for decision in self.storage.list_entries(project.id):
                if decision.type != "decision":
                    continue
                decision_date = _entry_local_date(decision)
                if abs((decision_date - meeting_date).days) <= window_days:
                    related_decisions.append(decision)
            related_decisions.sort(key=lambda item: (_entry_local_date(item), item.ts))

            lines.extend(["## Decisions", ""])
            if related_decisions:
                for decision in related_decisions:
                    status = ""
                    if decision.decision_done is True:
                        status = " (Applied)"
                    elif decision.decision_done is False:
                        status = " (Pending)"
                    lines.append(f"- {decision.title}{status}")
            else:
                lines.append("- None.")
            lines.append("")

        if include_tasks:
            today = datetime.now().astimezone().date()
            due_cutoff = today + timedelta(days=14)
            tasks = [
                task
                for task in self.storage.read_tasks()
                if task.project_id == project.id and task.status in ("open", "in_progress")
            ]
            filtered_tasks: list[Task] = []
            for task in tasks:
                if not task.due_date:
                    filtered_tasks.append(task)
                    continue
                try:
                    due_date = dates.parse_date(task.due_date)
                except Exception:
                    filtered_tasks.append(task)
                    continue
                if due_date <= due_cutoff:
                    filtered_tasks.append(task)
            filtered_tasks.sort(key=_task_sort_key)

            lines.extend(["## Actions", ""])
            if filtered_tasks:
                for task in filtered_tasks:
                    label = task.title
                    if task.due_date:
                        due_label = _format_date_ddmmyyyy(task.due_date)
                        label += f" (due {due_label})"
                    lines.append(f"- [ ] {label}")
            else:
                lines.append("- None.")
            lines.append("")

        lines.extend(["## Next steps", "", "- "])

        if internal:
            lines.extend(["", "## Annexes", ""])
            lines.append(f"- Entry ID: {entry.id}")
            lines.append(f"- Entry TS: {entry.ts}")
            lines.append(f"- Tags: {strings.format_tags(entry.tags)}")
            lines.append(f"- Source: {entry.content_path}")
            if related_decisions:
                lines.append("- Related decisions:")
                for decision in related_decisions:
                    lines.append(f"  - {decision.id} ({decision.title})")

        if out_path:
            output_path = Path(out_path)
        else:
            date_part = meeting_date.strftime("%d-%m-%Y")
            project_part = _sanitize_filename_part(project.name, "project")
            title_part = _sanitize_filename_part(entry.title, "meeting")
            suffix = entry.id[:8]
            filename = f"{project_part} - CR - {date_part} - {title_part} - {suffix}.md"
            output_path = self.storage.exports_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines).rstrip() + "\n"
        io_utils.safe_write_text(output_path, content)
        return str(output_path)

    def export_weekly_summary(
        self,
        start: date,
        end: date,
        project_id: str | None = None,
        out_path: str | None = None,
        *,
        include_time: bool = False,
        include_tasks: bool = True,
        include_decisions: bool = True,
    ) -> str:
        if start > end:
            raise ValueError("Invalid date range: start is after end")
        if project_id:
            self._ensure_project_exists(project_id)

        entries = self.storage.list_entries(project_id)
        filtered: list[EntryMeta] = []
        for entry in entries:
            entry_date = _entry_local_date(entry)
            if start <= entry_date <= end:
                filtered.append(entry)

        project_map = {project.id: project for project in self.storage.read_projects()}
        grouped: dict[str, list[EntryMeta]] = defaultdict(list)
        for entry in filtered:
            grouped[entry.project_id].append(entry)
        if project_id and project_id not in grouped:
            grouped[project_id] = []

        counts = {"meeting": 0, "note": 0, "decision": 0, "log": 0}
        decisions_done = 0
        decisions_pending = 0
        for entry in filtered:
            if entry.type == "decision" and not include_decisions:
                continue
            counts[entry.type] = counts.get(entry.type, 0) + 1
            if entry.type == "decision":
                if entry.decision_done is True:
                    decisions_done += 1
                else:
                    decisions_pending += 1

        tasks = self.storage.read_tasks()
        if project_id:
            tasks = [task for task in tasks if task.project_id == project_id]
        tasks_open = sum(
            1 for task in tasks if task.status in ("open", "in_progress")
        )
        tasks_done = sum(1 for task in tasks if task.status == "done")

        start_label = _format_date_ddmmyyyy(start)
        end_label = _format_date_ddmmyyyy(end)
        lines: list[str] = [
            f"# Weekly Summary - {start_label} to {end_label}",
            "",
            "## Résumé global",
            "",
            f"- Meetings: {counts['meeting']}",
            f"- Notes: {counts['note']}",
        ]
        if include_decisions:
            lines.append(
                f"- Decisions: {counts['decision']} (Applied: {decisions_done}, Pending: {decisions_pending})"
            )
        lines.append(f"- Activities: {counts['log']}")
        if include_tasks:
            lines.append(
                f"- Tasks (overall): {tasks_open} open / {tasks_done} done"
            )
        lines.append("")

        def project_sort_key(pid: str) -> str:
            project = project_map.get(pid)
            return project.name.lower() if project else pid

        for pid in sorted(grouped.keys(), key=project_sort_key):
            project = project_map.get(pid)
            project_name = project.name if project else pid
            lines.extend([f"## {project_name}", ""])
            day_map: dict[date, list[EntryMeta]] = defaultdict(list)
            for entry in grouped[pid]:
                day_map[_entry_local_date(entry)].append(entry)
            for day in sorted(day_map.keys()):
                lines.extend([f"### {_format_date_ddmmyyyy(day)}", ""])
                for entry_type, label in (
                    ("meeting", "Meetings"),
                    ("note", "Notes"),
                    ("decision", "Decisions"),
                    ("log", "Activities"),
                ):
                    if entry_type == "decision" and not include_decisions:
                        continue
                    entries_for_type = [
                        entry for entry in day_map[day] if entry.type == entry_type
                    ]
                    if not entries_for_type:
                        continue
                    entries_for_type.sort(key=_entry_time_sort_key)
                    lines.extend([f"#### {label}", ""])
                    for entry in entries_for_type:
                        time_label = _entry_time_label(entry)
                        title = entry.title
                        if entry.type == "decision" and entry.decision_done is True:
                            title = f"{title} (Applied)"
                        label_parts = [title] if not time_label else [time_label, title]
                        lines.append(f"- {' '.join(label_parts)}")
                    lines.append("")

            if include_tasks:
                project_tasks = [task for task in tasks if task.project_id == pid]
                open_tasks = [
                    task
                    for task in project_tasks
                    if task.status in ("open", "in_progress")
                ]
                overdue_tasks: list[Task] = []
                due_soon_tasks: list[Task] = []
                today = datetime.now().astimezone().date()
                for task in open_tasks:
                    if not task.due_date:
                        continue
                    try:
                        due_date = dates.parse_date(task.due_date)
                    except Exception:
                        continue
                    if due_date < today:
                        overdue_tasks.append(task)
                    if start <= due_date <= end:
                        due_soon_tasks.append(task)
                lines.extend(
                    [
                        "#### Tasks snapshot",
                        "",
                        f"- Open: {len(open_tasks)}",
                        f"- Overdue: {len(overdue_tasks)}",
                        f"- Due soon: {len(due_soon_tasks)}",
                        "",
                    ]
                )
                if overdue_tasks:
                    lines.append("Overdue:")
                    for task in overdue_tasks:
                        due_label = _format_date_ddmmyyyy(task.due_date)
                        lines.append(f"- {task.title} (due {due_label})")
                    lines.append("")
                if due_soon_tasks:
                    lines.append("Due soon:")
                    for task in due_soon_tasks:
                        due_label = _format_date_ddmmyyyy(task.due_date)
                        lines.append(f"- {task.title} (due {due_label})")
                    lines.append("")

        if include_time:
            start_utc, end_utc = dates.local_date_range_to_utc(start, end)
            totals: dict[str, int] = defaultdict(int)
            for log in self.storage.read_timelogs():
                try:
                    start_dt = dates.parse_utc_z(log.start)
                except Exception:
                    continue
                if start_dt < start_utc or start_dt > end_utc:
                    continue
                totals[log.project_id] += _timelog_duration_sec(log)
            if project_id:
                totals = {project_id: totals.get(project_id, 0)}
            if totals:
                lines.extend(["## Time", ""])
                total_all = 0
                for pid, seconds in sorted(totals.items(), key=lambda item: project_sort_key(item[0])):
                    project = project_map.get(pid)
                    name = project.name if project else pid
                    lines.append(f"- {name}: {_format_duration_hms(seconds)}")
                    total_all += seconds
                lines.append(f"- Total: {_format_duration_hms(total_all)}")
                lines.append("")

        if out_path:
            output_path = Path(out_path)
        else:
            scope = "All"
            if project_id:
                project = project_map.get(project_id)
                scope = _sanitize_filename_part(
                    project.name if project else project_id, "project"
                )
            filename = (
                f"Weekly Summary - {start.isoformat()} to {end.isoformat()} ({scope}).md"
            )
            output_path = self.storage.exports_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines).rstrip() + "\n"
        io_utils.safe_write_text(output_path, content)
        return str(output_path)

    def _get_project(self, project_id: str) -> Project:
        for project in self.storage.read_projects():
            if project.id == project_id:
                return project
        raise ProjectNotFoundError(project_id)

    def _ensure_project_exists(self, project_id: str) -> Project:
        return self._get_project(project_id)

    def _create_activity_entry(
        self,
        project: Project,
        start_dt: datetime,
        end_dt: datetime,
        duration_sec: int,
        note: str | None,
    ) -> EntryMeta:
        local_end = end_dt.astimezone()
        entry_date = local_end.date()
        title = f"Activity - {_format_duration_hms(duration_sec)}"
        body = _build_activity_body(start_dt, end_dt, duration_sec, note)
        entry, _md_path = self.add_entry(
            project.id,
            "log",
            title,
            [],
            body,
            entry_date=entry_date,
        )
        return entry

    def export_project_hierarchy(
        self,
        out_path: Path | None = None,
        *,
        include_archived: bool = False,
    ) -> Path:
        """
        Export project hierarchy as indented Markdown.
        
        Args:
            out_path: Output file path (default: exports/project_hierarchy.md)
            include_archived: Include archived projects
            
        Returns:
            Path to generated file
        """
        if out_path is None:
            out_path = self.storage.exports_dir / "project_hierarchy.md"
        
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get project tree
        tree = self.get_project_tree()
        
        lines: list[str] = [
            "# Project Hierarchy",
            "",
            f"**Generated:** {dates.local_now_iso()}",
            "",
            "---",
            "",
        ]
        
        if not tree:
            lines.append("No projects found.")
        else:
            # Recursive function to format tree with indentation
            def format_tree_node(node: dict, indent_level: int = 0) -> None:
                project = node["project"]
                children = node["children"]
                
                # Skip archived if not included
                if not include_archived and project.status == "archived":
                    return
                
                # Format project line with indentation
                indent = "  " * indent_level
                icon = "Folder" if children else "File"
                status_icon = "Active" if project.status == "active" else "Archived"
                
                # Count entries
                entries = [e for e in self.storage.read_entries_meta() if e.project_id == project.id]
                entry_count = len(entries)
                
                # Count tasks
                tasks = [t for t in self.storage.read_tasks() if t.project_id == project.id]
                open_tasks = sum(1 for t in tasks if t.status in ("open", "in_progress"))
                
                lines.append(
                    f"{indent}- **{project.name}** [{status_icon}, {icon}] "
                    f"({entry_count} entries, {open_tasks} open tasks)"
                )
                
                # Add metadata
                if project.description:
                    lines.append(f"{indent}  *{project.description}*")
                
                if project.tags:
                    lines.append(f"{indent}  Tags: {', '.join(project.tags)}")
                
                if project.person:
                    lines.append(f"{indent}  Person: {project.person}")
                
                if project.group:
                    lines.append(f"{indent}  Group: {project.group}")
                
                lines.append("")
                
                # Recursively format children
                for child_node in children:
                    format_tree_node(child_node, indent_level + 1)
            
            # Format each root node
            for root_node in tree:
                format_tree_node(root_node, 0)
        
        # Add legend
        lines.extend([
            "---",
            "",
            "**Legend:**",
            "- Folder: Project with children",
            "- File: Project without children",
            "- Active/Archived: Project status",
            "",
        ])
        
        content = "\n".join(lines)
        io_utils.safe_write_text(out_path, content)
        
        return out_path

    # ===== Dashboard Methods =====

    def get_in_progress_items(self, days: int = 7) -> dict[str, list]:
        """Get items currently in progress.
        
        Returns entries and tasks that are actively being worked on.
        
        Args:
            days: Consider entries from last N days as potentially in progress
            
        Returns:
            Dict with 'entries' and 'tasks' lists
        """
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.now().date() - timedelta(days=days)
        
        # Get recent entries (heuristic for "in progress")
        all_entries = self.storage.read_entries_meta()
        
        # Filter: recent entries (last N days) that aren't meetings or decisions
        in_progress_entries = [
            e for e in all_entries
            if e.entry_date and e.entry_date >= cutoff_date.isoformat()
            and e.type not in ("meeting", "decision")
        ]
        
        # Sort by date descending (most recent first)
        in_progress_entries.sort(key=lambda e: e.entry_date or "", reverse=True)
        
        # Get in-progress tasks from all projects
        in_progress_tasks = []
        projects = self.list_projects()
        
        for project in projects:
            tasks = self.list_tasks(project_id=project.id, status="in_progress")
            in_progress_tasks.extend(tasks)
        
        return {
            "entries": in_progress_entries,
            "tasks": in_progress_tasks
        }
    
    def get_pending_items(self) -> dict[str, list]:
        """Get items that are pending or blocked.
        
        Returns:
            Dict with 'entries' and 'tasks' lists
        """
        # Get pending/open tasks from all projects
        pending_tasks = []
        projects = self.list_projects()
        
        for project in projects:
            # Get tasks with "open" status (waiting to be started)
            tasks = self.list_tasks(project_id=project.id, status="open")
            pending_tasks.extend(tasks)
        
        # TODO: Could also filter entries with "waiting" or "blocked" tags
        pending_entries = []
        
        return {
            "entries": pending_entries,
            "tasks": pending_tasks
        }
    
    def get_upcoming_items(self, days: int = 7) -> list[dict]:
        """Get upcoming items in the next N days.
        
        Args:
            days: Look ahead N days
            
        Returns:
            List of dicts with: date, type, title, project_id, item_id
        """
        from datetime import datetime, timedelta
        
        today = datetime.now().date()
        end_date = today + timedelta(days=days)
        
        upcoming = []
        
        # Get meetings in date range
        all_entries = self.storage.read_entries_meta()
        meetings = [
            e for e in all_entries
            if e.type == "meeting"
            and e.entry_date
            and today.isoformat() <= e.entry_date <= end_date.isoformat()
        ]
        
        for meeting in meetings:
            project = self._projects_by_id.get(meeting.project_id)
            upcoming.append({
                "date": meeting.entry_date,
                "type": "Meeting",
                "title": meeting.title,
                "project_name": project.name if project else meeting.project_id,
                "project_id": meeting.project_id,
                "item_id": meeting.id
            })
        
        # Sort by date
        upcoming.sort(key=lambda x: x["date"])
        
        return upcoming
    
    def get_focus_suggestions(self) -> dict:
        """Calculate focus suggestions based on current state.
        
        Returns:
            Dict with suggestions and metrics
        """
        projects = self.list_projects()
        
        # Find project with most open tasks
        busiest_project = None
        max_open_tasks = 0
        
        for project in projects:
            if project.status != "active":
                continue
            
            tasks = self.list_tasks(project_id=project.id, status="open")
            in_progress_tasks = self.list_tasks(project_id=project.id, status="in_progress")
            total_open = len(tasks) + len(in_progress_tasks)
            
            if total_open > max_open_tasks:
                max_open_tasks = total_open
                busiest_project = (project, total_open)
        
        # Find oldest in-progress items
        in_progress = self.get_in_progress_items(days=30)
        oldest_entry = None
        
        if in_progress["entries"]:
            # Sort by date ascending (oldest first)
            sorted_entries = sorted(
                in_progress["entries"],
                key=lambda e: e.entry_date or "9999-99-99"
            )
            oldest_entry = sorted_entries[0] if sorted_entries else None
        
        return {
            "busiest_project": busiest_project,
            "oldest_entry": oldest_entry,
            "total_in_progress": len(in_progress["entries"]) + len(in_progress["tasks"]),
            "total_pending": len(self.get_pending_items()["tasks"])
        }


def _normalize_time(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"Invalid time {value}. Expected HH:MM") from exc
    return parsed.strftime("%H:%M")


def _timelog_duration_sec(log: TimeLog) -> int:
    if log.duration_sec is not None:
        return int(log.duration_sec)
    if log.duration_min is not None:
        return int(log.duration_min) * 60
    try:
        start_dt = dates.parse_utc_z(log.start)
        end_dt = dates.parse_utc_z(log.end)
        return int((end_dt - start_dt).total_seconds())
    except Exception:
        return 0


def _validate_entry_patch(entry: EntryMeta, patch: dict[str, object]) -> None:
    if entry.type != "meeting":
        if patch.get("start_time") is not None or patch.get("end_time") is not None:
            raise ValueError("Meeting hours only valid for meeting entries")
    if entry.type != "decision" and "decision_done" in patch:
        raise ValueError("Decision flag only valid for decision entries")
    if "context_status" in patch:
        status = patch.get("context_status")
        if status is not None:
            if not isinstance(status, str) or status not in VALID_CONTEXT_STATUSES:
                valid = ", ".join(VALID_CONTEXT_STATUSES)
                raise ValueError(f"Context status must be one of: {valid}")
    start_time = patch.get("start_time", entry.start_time)
    end_time = patch.get("end_time", entry.end_time)
    if start_time and end_time:
        start_dt = datetime.strptime(str(start_time), "%H:%M")
        end_dt = datetime.strptime(str(end_time), "%H:%M")
        if start_dt > end_dt:
            raise ValueError("Meeting start must be before end")


def _format_duration_hms(seconds: int) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_date_ddmmyyyy(value: date | str) -> str:
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, str) and value:
        try:
            return dates.parse_date(value).strftime("%d/%m/%Y")
        except Exception:
            return value
    return ""


def _format_meeting_time(entry: EntryMeta) -> str:
    if entry.start_time and entry.end_time:
        return f"{entry.start_time} - {entry.end_time}"
    if entry.start_time:
        return entry.start_time
    if entry.end_time:
        return entry.end_time
    return ""


def _entry_local_date(entry: EntryMeta) -> date:
    if entry.entry_date:
        try:
            return dates.parse_date(entry.entry_date)
        except Exception:
            pass
    try:
        return dates.parse_utc_z(entry.ts).astimezone().date()
    except Exception:
        return datetime.now().astimezone().date()


def _entry_time_label(entry: EntryMeta) -> str:
    if entry.type == "meeting":
        meeting_label = _format_meeting_time(entry)
        if meeting_label:
            return meeting_label
    try:
        return dates.parse_utc_z(entry.ts).astimezone().strftime("%H:%M")
    except Exception:
        return ""


def _entry_time_sort_key(entry: EntryMeta) -> tuple:
    if entry.type == "meeting" and entry.start_time:
        return (0, entry.start_time, entry.ts)
    try:
        entry_dt = dates.parse_utc_z(entry.ts).astimezone()
        return (1, entry_dt.strftime("%H:%M:%S"), entry.ts)
    except Exception:
        return (2, "", entry.ts)


def _sanitize_filename_part(value: str, fallback: str) -> str:
    cleaned = strings.sanitize_project_name(value)
    return cleaned if cleaned else fallback


def _format_local_dt(dt: datetime) -> str:
    return dt.astimezone().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _build_activity_body(
    start_dt: datetime, end_dt: datetime, duration_sec: int, note: str | None
) -> str:
    minutes = duration_sec // 60
    seconds = duration_sec % 60
    lines = [
        f"Started: {_format_local_dt(start_dt)}",
        f"Ended: {_format_local_dt(end_dt)}",
        f"Duration: {_format_duration_hms(duration_sec)} ({minutes} min {seconds} sec)",
    ]
    if note:
        lines.append(f"Note: {note}")
    return "\n".join(lines) + "\n"


def _clean_task_tags(tags: Iterable[str] | object) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags_iter = strings.parse_tags(tags)
    else:
        tags_iter = list(tags)
    cleaned: list[str] = []
    for tag in tags_iter:
        value = str(tag).strip()
        if not value:
            continue
        if "," in value:
            raise ValueError("Task tags cannot contain commas")
        cleaned.append(value)
    return cleaned


def _normalize_project_links(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.splitlines()
    else:
        try:
            items = list(value)
        except TypeError:
            return []
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def _normalize_due_date(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        dates.parse_date(cleaned)
    except Exception as exc:
        raise ValueError("Due date must be YYYY-MM-DD") from exc
    return cleaned


def _task_sort_key(task: Task) -> tuple[int, int, str, str]:
    status_rank = {"in_progress": 0, "open": 1, "done": 2}
    missing_due = 1 if not task.due_date else 0
    due_label = task.due_date or ""
    rank = status_rank.get(task.status, 3)
    return (rank, missing_due, due_label, task.created_at)


def _format_tasks_section(tasks: list[Task]) -> list[str]:
    lines = ["## Tasks", ""]
    if not tasks:
        lines.append("No tasks.")
        return lines
    open_tasks = [task for task in tasks if task.status in ("open", "in_progress")]
    done_tasks = [task for task in tasks if task.status == "done"]
    for task in open_tasks:
        lines.append(_format_task_line(task, False))
    for task in done_tasks:
        lines.append(_format_task_line(task, True))
    return lines


def _format_task_line(task: Task, done: bool) -> str:
    checkbox = "x" if done else " "
    parts = [task.title]
    if task.tags:
        parts.append(f"(tags: {strings.format_tags(task.tags)})")
    if task.linked_entry_id:
        parts.append(f"(source entry: {task.linked_entry_id})")
    return f"- [{checkbox}] " + " ".join(parts)

