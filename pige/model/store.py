"""Business operations on the model database (see docs/modele.md).

All writes go through :meth:`ModelStore._tx`, one ``BEGIN IMMEDIATE`` transaction
per operation, so a failed operation leaves nothing half-written.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Iterable, Iterator, Literal, Sequence, cast

from pige.model.text import fold, name_key
from pige.model.timecount import OverlapMode, Span, counted_seconds, presence_seconds

TaskStatus = Literal["open", "in_progress", "waiting", "done"]
EntryKind = Literal["note", "meeting", "decision", "activity"]
EntrySource = Literal["journal", "writing", "capture", "mail", "import"]
ProjectState = Literal["active", "dormant", "closed"]
BlockSource = Literal["timer", "agenda", "manual"]

_POSITION_EPSILON = 1e-9


class NotFoundError(LookupError):
    """The requested row does not exist."""


class InvalidOperationError(ValueError):
    """The operation breaks a rule of the model."""


def _new_id() -> str:
    return uuid.uuid4().hex


def _utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("datetimes must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _check_date(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InvalidOperationError(f"{field}: expected YYYY-MM-DD, got {value!r}") from exc


def _check_time(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return time.fromisoformat(value).strftime("%H:%M")
    except ValueError as exc:
        raise InvalidOperationError(f"{field}: expected HH:MM, got {value!r}") from exc


# ---------------------------------------------------------------- records


@dataclass(frozen=True)
class Space:
    id: str
    name: str
    position: float
    archived: bool


@dataclass(frozen=True)
class Project:
    id: str
    space_id: str
    parent_id: str | None
    name: str
    description: str | None
    team: str | None
    state: str
    position: float
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Person:
    id: str
    display_name: str
    email: str | None
    organisation: str | None
    role: str | None
    note: str | None
    directory_uid: str | None


@dataclass(frozen=True)
class Tag:
    id: str
    name: str
    pinned: bool
    position: float


@dataclass(frozen=True)
class Task:
    id: str
    space_id: str
    project_id: str | None
    title: str
    note: str | None
    status: str
    waiting_on: str | None
    due_date: str | None
    position: float
    origin_entry_id: str | None
    created_at: str
    updated_at: str
    status_since: str
    done_at: str | None
    steps_done: int = 0
    steps_total: int = 0


@dataclass(frozen=True)
class Step:
    id: str
    task_id: str
    label: str
    done: bool
    position: float


@dataclass(frozen=True)
class Entry:
    id: str
    space_id: str
    project_id: str | None
    task_id: str | None
    kind: str
    title: str
    body: str
    entry_date: str
    start_time: str | None
    end_time: str | None
    decision_applied: bool | None
    source: str
    mail_message_id: str | None
    created_at: str
    updated_at: str
    version: int


@dataclass(frozen=True)
class EntryVersion:
    entry_id: str
    version: int
    title: str
    body: str
    saved_at: str


@dataclass(frozen=True)
class TimeBlock:
    id: str
    space_id: str
    project_id: str | None
    task_id: str | None
    entry_id: str | None
    start_at: datetime
    end_at: datetime | None
    source: str
    overlap_mode: str
    note: str | None
    validated: bool


@dataclass(frozen=True)
class CountedBlock:
    block: TimeBlock
    start: datetime
    end: datetime
    counted_seconds: int


@dataclass(frozen=True)
class DayReport:
    day: date
    blocks: list[CountedBlock]
    presence_seconds: int
    by_space: dict[str, int]
    by_project: dict[str | None, int]


@dataclass(frozen=True)
class SearchHit:
    kind: Literal["entry", "task"]
    id: str
    title: str
    snippet: str


def _row_to(cls: Any, row: sqlite3.Row, **overrides: Any) -> Any:
    data = {k: row[k] for k in row.keys() if k in cls.__dataclass_fields__}
    data.update(overrides)
    return cls(**data)


# ---------------------------------------------------------------- store


class ModelStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        if self.conn.in_transaction:
            # Nested call inside an operation: join the outer transaction.
            yield self.conn
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def _one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(sql, params).fetchone()
        return row

    def _require(self, table: str, row_id: str) -> sqlite3.Row:
        row = self._one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        if row is None:
            raise NotFoundError(f"{table}: {row_id} not found")
        return row

    # ------------------------------------------------------------ ordering

    def _next_position(self, table: str, scope: str, params: Sequence[Any]) -> float:
        row = self._one(f"SELECT max(position) FROM {table} WHERE {scope}", params)
        top = row[0] if row is not None else None
        return float(top) + 1.0 if top is not None else 1.0

    def _reorder(
        self,
        table: str,
        row_id: str,
        scope: str,
        params: Sequence[Any],
        *,
        before: str | None,
        after: str | None,
    ) -> float:
        """Place ``row_id`` just before ``before`` or just after ``after`` within ``scope``."""
        if (before is None) == (after is None):
            raise InvalidOperationError("give exactly one of before / after")
        anchor_id = before if before is not None else after
        if anchor_id == row_id:
            raise InvalidOperationError("cannot place a row relative to itself")
        for attempt in range(2):
            anchor = self._one(
                f"SELECT position FROM {table} WHERE id = ? AND {scope}", (anchor_id, *params)
            )
            if anchor is None:
                raise InvalidOperationError(f"{anchor_id} is not in the same list")
            pos = float(anchor[0])
            if before is not None:
                neighbour = self._one(
                    f"SELECT max(position) FROM {table} WHERE {scope} AND position < ? AND id <> ?",
                    (*params, pos, row_id),
                )
                other = neighbour[0] if neighbour is not None else None
                new = (float(other) + pos) / 2 if other is not None else pos - 1.0
            else:
                neighbour = self._one(
                    f"SELECT min(position) FROM {table} WHERE {scope} AND position > ? AND id <> ?",
                    (*params, pos, row_id),
                )
                other = neighbour[0] if neighbour is not None else None
                new = (pos + float(other)) / 2 if other is not None else pos + 1.0
            if other is None or abs(new - pos) > _POSITION_EPSILON and abs(new - float(other)) > _POSITION_EPSILON:
                self.conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (new, row_id))
                return new
            if attempt == 0:  # gap exhausted: renumber the list 1..n and retry once
                ids = [r[0] for r in self.conn.execute(
                    f"SELECT id FROM {table} WHERE {scope} ORDER BY position, id", params
                )]
                for i, rid in enumerate(ids, start=1):
                    self.conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (float(i), rid))
        raise RuntimeError("could not find a free position")  # pragma: no cover

    # ------------------------------------------------------------ spaces

    def create_space(self, name: str) -> Space:
        with self._tx():
            space_id = _new_id()
            self.conn.execute(
                "INSERT INTO spaces(id, name, position, created_at) VALUES (?, ?, ?, ?)",
                (space_id, name.strip(), self._next_position("spaces", "1=1", ()), _utc(_now())),
            )
            return self.get_space(space_id)

    def get_space(self, space_id: str) -> Space:
        row = self._require("spaces", space_id)
        return _row_to(Space, row, archived=bool(row["archived"]))

    def list_spaces(self, *, include_archived: bool = False) -> list[Space]:
        sql = "SELECT * FROM spaces" + ("" if include_archived else " WHERE archived = 0")
        rows = self.conn.execute(sql + " ORDER BY position, name").fetchall()
        return [_row_to(Space, r, archived=bool(r["archived"])) for r in rows]

    def rename_space(self, space_id: str, name: str) -> Space:
        with self._tx():
            self._require("spaces", space_id)
            self.conn.execute("UPDATE spaces SET name = ? WHERE id = ?", (name.strip(), space_id))
            return self.get_space(space_id)

    def move_space(self, space_id: str, *, before: str | None = None, after: str | None = None) -> None:
        with self._tx():
            self._require("spaces", space_id)
            self._reorder("spaces", space_id, "1=1", (), before=before, after=after)

    # ------------------------------------------------------------ projects

    def create_project(
        self,
        space_id: str,
        name: str,
        *,
        parent_id: str | None = None,
        description: str | None = None,
        team: str | None = None,
    ) -> Project:
        with self._tx():
            self._require("spaces", space_id)
            project_id = _new_id()
            now = _utc(_now())
            position = self._next_position("projects", "space_id = ? AND parent_id IS ?", (space_id, parent_id))
            try:
                self.conn.execute(
                    "INSERT INTO projects(id, space_id, parent_id, name, description, team, position, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (project_id, space_id, parent_id, name.strip(), _clean(description), _clean(team), position, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            return self.get_project(project_id)

    def get_project(self, project_id: str) -> Project:
        return _row_to(Project, self._require("projects", project_id))

    def list_projects(self, space_id: str | None = None, *, states: Iterable[str] = ("active", "dormant")) -> list[Project]:
        """Projects in display order: each parent followed by its sub-projects."""
        wanted = tuple(states)
        marks = ",".join("?" for _ in wanted) or "NULL"
        params: list[Any] = list(wanted)
        sql = f"SELECT * FROM projects WHERE state IN ({marks})"
        if space_id is not None:
            sql += " AND space_id = ?"
            params.append(space_id)
        rows = [_row_to(Project, r) for r in self.conn.execute(sql, params).fetchall()]
        spaces = {s.id: s.position for s in self.list_spaces(include_archived=True)}
        by_parent: dict[str | None, list[Project]] = {}
        for p in rows:
            by_parent.setdefault(p.parent_id, []).append(p)
        present = {p.id for p in rows}
        tops = [p for p in rows if p.parent_id is None or p.parent_id not in present]
        tops.sort(key=lambda p: (spaces.get(p.space_id, 0.0), p.space_id, p.position, p.name))
        ordered: list[Project] = []
        for top in tops:
            ordered.append(top)
            if top.parent_id is None:
                ordered.extend(sorted(by_parent.get(top.id, []), key=lambda p: (p.position, p.name)))
        return ordered

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        team: str | None = None,
        state: ProjectState | None = None,
    ) -> Project:
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = _clean(description)
        if team is not None:
            changes["team"] = _clean(team)
        if state is not None:
            changes["state"] = state
        with self._tx():
            self._require("projects", project_id)
            if changes:
                changes["updated_at"] = _utc(_now())
                sets = ", ".join(f"{k} = ?" for k in changes)
                try:
                    self.conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*changes.values(), project_id))
                except sqlite3.IntegrityError as exc:
                    raise InvalidOperationError(str(exc)) from exc
            return self.get_project(project_id)

    def move_project(self, project_id: str, *, space_id: str, parent_id: str | None) -> Project:
        """Change a project's space and/or parent; sub-projects and attached rows follow."""
        with self._tx():
            self._require("spaces", space_id)
            self._require("projects", project_id)
            position = self._next_position("projects", "space_id = ? AND parent_id IS ?", (space_id, parent_id))
            try:
                self.conn.execute(
                    "UPDATE projects SET space_id = ?, parent_id = ?, position = ?, updated_at = ? WHERE id = ?",
                    (space_id, parent_id, position, _utc(_now()), project_id),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            return self.get_project(project_id)

    def reorder_project(self, project_id: str, *, before: str | None = None, after: str | None = None) -> None:
        with self._tx():
            p = self.get_project(project_id)
            self._reorder("projects", project_id, "space_id = ? AND parent_id IS ?", (p.space_id, p.parent_id),
                          before=before, after=after)

    def set_project_links(self, project_id: str, links: Sequence[tuple[str, str | None]]) -> None:
        with self._tx():
            self._require("projects", project_id)
            self.conn.execute("DELETE FROM project_links WHERE project_id = ?", (project_id,))
            seen: set[str] = set()
            for i, (url, label) in enumerate(links, start=1):
                url = url.strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                self.conn.execute(
                    "INSERT INTO project_links(project_id, position, url, label) VALUES (?, ?, ?, ?)",
                    (project_id, float(i), url, _clean(label)),
                )

    def project_links(self, project_id: str) -> list[tuple[str, str | None]]:
        rows = self.conn.execute(
            "SELECT url, label FROM project_links WHERE project_id = ? ORDER BY position", (project_id,)
        ).fetchall()
        return [(r["url"], r["label"]) for r in rows]

    def last_activity(self, project_id: str) -> str | None:
        """Latest moment something happened in the project (entry, task change, time)."""
        row = self._one(
            """
            SELECT max(t) FROM (
                SELECT max(updated_at) AS t FROM entries WHERE project_id = ?
                UNION ALL SELECT max(updated_at) FROM tasks WHERE project_id = ?
                UNION ALL SELECT max(coalesce(end_at, start_at)) FROM time_blocks WHERE project_id = ?
            )
            """,
            (project_id, project_id, project_id),
        )
        return row[0] if row is not None else None

    def stale_projects(self, *, days: int = 30, now: datetime | None = None) -> list[tuple[Project, str]]:
        """Active projects with nothing new for ``days`` days, oldest first."""
        limit = _utc((now or _now()) - timedelta(days=days))
        result = []
        for p in self.list_projects(states=("active",)):
            last = self.last_activity(p.id) or p.created_at
            if last < limit:
                result.append((p, last))
        result.sort(key=lambda item: item[1])
        return result

    # ------------------------------------------------------------ people

    def find_people(self, name: str) -> list[Person]:
        rows = self.conn.execute(
            "SELECT * FROM people WHERE match_key = ? ORDER BY created_at", (name_key(name),)
        ).fetchall()
        return [_row_to(Person, r) for r in rows]

    def get_or_create_person(self, name: str) -> Person:
        """The person with this name (in any order/case/accents), created if unknown."""
        cleaned = " ".join(name.split()).lstrip("@")
        if not cleaned:
            raise InvalidOperationError("empty person name")
        with self._tx():
            found = self.find_people(cleaned)
            if found:
                return found[0]
            person_id = _new_id()
            self.conn.execute(
                "INSERT INTO people(id, display_name, match_key, created_at) VALUES (?, ?, ?, ?)",
                (person_id, cleaned, name_key(cleaned), _utc(_now())),
            )
            return self.get_person(person_id)

    def get_person(self, person_id: str) -> Person:
        return _row_to(Person, self._require("people", person_id))

    def update_person(
        self,
        person_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        organisation: str | None = None,
        role: str | None = None,
        note: str | None = None,
        directory_uid: str | None = None,
    ) -> Person:
        changes: dict[str, Any] = {}
        if display_name is not None:
            cleaned = " ".join(display_name.split())
            if not cleaned:
                raise InvalidOperationError("empty person name")
            changes["display_name"] = cleaned
            changes["match_key"] = name_key(cleaned)
        for key, value in (("email", email), ("organisation", organisation), ("role", role),
                           ("note", note), ("directory_uid", directory_uid)):
            if value is not None:
                changes[key] = _clean(value)
        with self._tx():
            self._require("people", person_id)
            if changes:
                sets = ", ".join(f"{k} = ?" for k in changes)
                try:
                    self.conn.execute(f"UPDATE people SET {sets} WHERE id = ?", (*changes.values(), person_id))
                except sqlite3.IntegrityError as exc:
                    raise InvalidOperationError(f"another person already has this e-mail: {exc}") from exc
            return self.get_person(person_id)

    def list_people(self, tag_id: str | None = None) -> list[Person]:
        if tag_id is None:
            rows = self.conn.execute("SELECT * FROM people").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT p.* FROM people p JOIN person_tags pt ON pt.person_id = p.id WHERE pt.tag_id = ?", (tag_id,)
            ).fetchall()
        people = [_row_to(Person, r) for r in rows]
        return sorted(people, key=lambda p: fold(p.display_name))

    def _resolve_people(self, people: Iterable[str]) -> list[str]:
        """Person ids for a mix of ids and names (names are created if unknown)."""
        ids: list[str] = []
        for item in people:
            if self._one("SELECT 1 FROM people WHERE id = ?", (item,)):
                pid = item
            else:
                pid = self.get_or_create_person(item).id
            if pid not in ids:
                ids.append(pid)
        return ids

    def waiting_on(self, person_id: str) -> list[Task]:
        """Open tasks waiting for this person."""
        return self._tasks("t.waiting_on = ? AND t.status = 'waiting'", (person_id,), order="t.status_since")

    # ------------------------------------------------------------ tags

    @staticmethod
    def _tag_name(name: str) -> str:
        cleaned = " ".join(name.split()).lstrip("#").strip()
        if not cleaned:
            raise InvalidOperationError("empty tag name")
        return cleaned

    def get_or_create_tag(self, name: str) -> Tag:
        cleaned = self._tag_name(name)
        with self._tx():
            row = self._one("SELECT * FROM tags WHERE name = ? COLLATE NOCASE", (cleaned,))
            if row is None:
                tag_id = _new_id()
                self.conn.execute(
                    "INSERT INTO tags(id, name, position) VALUES (?, ?, ?)",
                    (tag_id, cleaned, self._next_position("tags", "1=1", ())),
                )
                row = self._require("tags", tag_id)
            return _row_to(Tag, row, pinned=bool(row["pinned"]))

    def set_tag_pinned(self, tag_id: str, pinned: bool) -> Tag:
        with self._tx():
            self._require("tags", tag_id)
            self.conn.execute("UPDATE tags SET pinned = ? WHERE id = ?", (int(pinned), tag_id))
            row = self._require("tags", tag_id)
            return _row_to(Tag, row, pinned=bool(row["pinned"]))

    def pinned_tags(self) -> list[tuple[Tag, int]]:
        """Pinned tags in order, with how many people, entries and tasks carry them."""
        rows = self.conn.execute(
            """
            SELECT t.*,
                   (SELECT count(*) FROM person_tags WHERE tag_id = t.id)
                 + (SELECT count(*) FROM entry_tags WHERE tag_id = t.id)
                 + (SELECT count(*) FROM task_tags t2 JOIN tasks k ON k.id = t2.task_id
                    WHERE t2.tag_id = t.id AND k.status <> 'done') AS uses
            FROM tags t WHERE t.pinned = 1 ORDER BY t.position, t.name
            """
        ).fetchall()
        return [(_row_to(Tag, r, pinned=True), int(r["uses"])) for r in rows]

    def _resolve_tags(self, tags: Iterable[str]) -> list[str]:
        ids: list[str] = []
        for name in tags:
            tid = self.get_or_create_tag(name).id
            if tid not in ids:
                ids.append(tid)
        return ids

    def tag_person(self, person_id: str, tags: Iterable[str]) -> None:
        with self._tx():
            self._require("people", person_id)
            for tid in self._resolve_tags(tags):
                self.conn.execute("INSERT OR IGNORE INTO person_tags(person_id, tag_id) VALUES (?, ?)", (person_id, tid))

    # ------------------------------------------------------------ tasks

    def _task_scope(self, task: Task) -> tuple[str, tuple[Any, ...]]:
        return "space_id = ? AND project_id IS ?", (task.space_id, task.project_id)

    def _scope_for(self, *, project_id: str | None, space_id: str | None) -> tuple[str, str | None]:
        if project_id is not None:
            project = self.get_project(project_id)
            if space_id is not None and space_id != project.space_id:
                raise InvalidOperationError("project is not in this space")
            return project.space_id, project_id
        if space_id is None:
            raise InvalidOperationError("give a project or a space")
        self._require("spaces", space_id)
        return space_id, None

    def create_task(
        self,
        title: str,
        *,
        project_id: str | None = None,
        space_id: str | None = None,
        note: str | None = None,
        due_date: str | None = None,
        origin_entry_id: str | None = None,
        people: Iterable[str] = (),
        tags: Iterable[str] = (),
        steps: Iterable[str] = (),
    ) -> Task:
        with self._tx():
            space, project = self._scope_for(project_id=project_id, space_id=space_id)
            task_id = _new_id()
            now = _utc(_now())
            position = self._next_position("tasks", "space_id = ? AND project_id IS ?", (space, project))
            self.conn.execute(
                "INSERT INTO tasks(id, space_id, project_id, title, note, due_date, position, origin_entry_id,"
                " created_at, updated_at, status_since) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, space, project, title.strip(), _clean(note), _check_date(due_date, "due_date"),
                 position, origin_entry_id, now, now, now),
            )
            for pid in self._resolve_people(people):
                self.conn.execute("INSERT INTO task_people(task_id, person_id) VALUES (?, ?)", (task_id, pid))
            for tid in self._resolve_tags(tags):
                self.conn.execute("INSERT INTO task_tags(task_id, tag_id) VALUES (?, ?)", (task_id, tid))
            for label in steps:
                self.add_step(task_id, label)
            return self.get_task(task_id)

    _TASK_SELECT = """
        SELECT t.*,
               (SELECT count(*) FROM task_steps s WHERE s.task_id = t.id AND s.done = 1) AS steps_done,
               (SELECT count(*) FROM task_steps s WHERE s.task_id = t.id) AS steps_total
        FROM tasks t
    """

    def _tasks(self, where: str, params: Sequence[Any], *, order: str = "t.position, t.created_at") -> list[Task]:
        rows = self.conn.execute(f"{self._TASK_SELECT} WHERE {where} ORDER BY {order}", params).fetchall()
        return [_row_to(Task, r) for r in rows]

    def get_task(self, task_id: str) -> Task:
        found = self._tasks("t.id = ?", (task_id,))
        if not found:
            raise NotFoundError(f"tasks: {task_id} not found")
        return found[0]

    def tasks_for_project(self, project_id: str, *, include_done: bool = False) -> list[Task]:
        """Tasks of a project in manual order (done ones last, most recent first)."""
        open_tasks = self._tasks("t.project_id = ? AND t.status <> 'done'", (project_id,))
        if not include_done:
            return open_tasks
        return open_tasks + self._tasks("t.project_id = ? AND t.status = 'done'", (project_id,),
                                        order="t.done_at DESC")

    def tasks_for_space(self, space_id: str) -> list[Task]:
        """Open tasks attached to the space itself (no project)."""
        return self._tasks("t.space_id = ? AND t.project_id IS NULL AND t.status <> 'done'", (space_id,))

    def in_progress_tasks(self) -> list[Task]:
        """Tasks in progress, the longest-running first."""
        return self._tasks("t.status = 'in_progress'", (), order="t.status_since")

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        note: str | None = None,
        due_date: str | None = None,
        clear_due_date: bool = False,
    ) -> Task:
        changes: dict[str, Any] = {}
        if title is not None:
            changes["title"] = title.strip()
        if note is not None:
            changes["note"] = _clean(note)
        if clear_due_date:
            changes["due_date"] = None
        elif due_date is not None:
            changes["due_date"] = _check_date(due_date, "due_date")
        with self._tx():
            self._require("tasks", task_id)
            if changes:
                changes["updated_at"] = _utc(_now())
                sets = ", ".join(f"{k} = ?" for k in changes)
                try:
                    self.conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*changes.values(), task_id))
                except sqlite3.IntegrityError as exc:
                    raise InvalidOperationError(str(exc)) from exc
            return self.get_task(task_id)

    def set_task_status(self, task_id: str, status: TaskStatus, *, waiting_on: str | None = None) -> Task:
        """Change status. ``waiting`` needs the person (id or name) being waited on."""
        if status not in ("open", "in_progress", "waiting", "done"):
            raise InvalidOperationError(f"unknown status {status!r}")
        with self._tx():
            current = self.get_task(task_id)
            person_id: str | None = None
            if status == "waiting":
                if not waiting_on:
                    raise InvalidOperationError("say who the task is waiting on")
                person_id = self._resolve_people([waiting_on])[0]
            elif waiting_on is not None:
                raise InvalidOperationError("waiting_on only applies to the 'waiting' status")
            now = _utc(_now())
            since = current.status_since if (current.status == status and current.waiting_on == person_id) else now
            self.conn.execute(
                "UPDATE tasks SET status = ?, waiting_on = ?, status_since = ?, done_at = ?, updated_at = ? WHERE id = ?",
                (status, person_id, since, now if status == "done" else None, now, task_id),
            )
            return self.get_task(task_id)

    def reorder_task(self, task_id: str, *, before: str | None = None, after: str | None = None) -> None:
        with self._tx():
            task = self.get_task(task_id)
            scope, params = self._task_scope(task)
            self._reorder("tasks", task_id, scope, params, before=before, after=after)

    def move_task(self, task_id: str, *, project_id: str | None = None, space_id: str | None = None) -> Task:
        with self._tx():
            self._require("tasks", task_id)
            space, project = self._scope_for(project_id=project_id, space_id=space_id)
            position = self._next_position("tasks", "space_id = ? AND project_id IS ?", (space, project))
            self.conn.execute(
                "UPDATE tasks SET space_id = ?, project_id = ?, position = ?, updated_at = ? WHERE id = ?",
                (space, project, position, _utc(_now()), task_id),
            )
            return self.get_task(task_id)

    def add_step(self, task_id: str, label: str) -> Step:
        with self._tx():
            self._require("tasks", task_id)
            step_id = _new_id()
            self.conn.execute(
                "INSERT INTO task_steps(id, task_id, label, position) VALUES (?, ?, ?, ?)",
                (step_id, task_id, label.strip(), self._next_position("task_steps", "task_id = ?", (task_id,))),
            )
            self.conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (_utc(_now()), task_id))
            return self._step(step_id)

    def _step(self, step_id: str) -> Step:
        row = self._require("task_steps", step_id)
        return _row_to(Step, row, done=bool(row["done"]))

    def set_step_done(self, step_id: str, done: bool) -> Step:
        with self._tx():
            row = self._require("task_steps", step_id)
            self.conn.execute("UPDATE task_steps SET done = ? WHERE id = ?", (int(done), step_id))
            self.conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (_utc(_now()), row["task_id"]))
            return self._step(step_id)

    def reorder_step(self, step_id: str, *, before: str | None = None, after: str | None = None) -> None:
        with self._tx():
            row = self._require("task_steps", step_id)
            self._reorder("task_steps", step_id, "task_id = ?", (row["task_id"],), before=before, after=after)

    def steps(self, task_id: str) -> list[Step]:
        rows = self.conn.execute(
            "SELECT * FROM task_steps WHERE task_id = ? ORDER BY position", (task_id,)
        ).fetchall()
        return [_row_to(Step, r, done=bool(r["done"])) for r in rows]

    # ------------------------------------------------------------ entries

    def create_entry(
        self,
        *,
        entry_date: str,
        project_id: str | None = None,
        space_id: str | None = None,
        task_id: str | None = None,
        kind: EntryKind = "note",
        title: str = "",
        body: str = "",
        start_time: str | None = None,
        end_time: str | None = None,
        source: EntrySource = "capture",
        mail_message_id: str | None = None,
        people: Iterable[str] = (),
        tags: Iterable[str] = (),
    ) -> Entry:
        with self._tx():
            if task_id is not None and project_id is None and space_id is None:
                task = self.get_task(task_id)
                project_id, space_id = task.project_id, task.space_id
            space, project = self._scope_for(project_id=project_id, space_id=space_id)
            if task_id is not None:
                task = self.get_task(task_id)
                if task.space_id != space or (project is not None and task.project_id not in (None, project)):
                    raise InvalidOperationError("the task belongs to another project")
            entry_id = _new_id()
            now = _utc(_now())
            try:
                self.conn.execute(
                    "INSERT INTO entries(id, space_id, project_id, task_id, kind, title, body, entry_date, start_time,"
                    " end_time, decision_applied, source, mail_message_id, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry_id, space, project, task_id, kind, title.strip(), body,
                     _check_date(entry_date, "entry_date"), _check_time(start_time, "start_time"),
                     _check_time(end_time, "end_time"), 0 if kind == "decision" else None, source,
                     _clean(mail_message_id), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            for pid in self._resolve_people(people):
                self.conn.execute("INSERT INTO entry_people(entry_id, person_id) VALUES (?, ?)", (entry_id, pid))
            for tid in self._resolve_tags(tags):
                self.conn.execute("INSERT INTO entry_tags(entry_id, tag_id) VALUES (?, ?)", (entry_id, tid))
            return self.get_entry(entry_id)

    def get_entry(self, entry_id: str) -> Entry:
        row = self._require("entries", entry_id)
        applied = row["decision_applied"]
        return _row_to(Entry, row, decision_applied=None if applied is None else bool(applied))

    def entry_by_mail(self, message_id: str) -> Entry | None:
        row = self._one("SELECT id FROM entries WHERE mail_message_id = ?", (message_id.strip(),))
        return self.get_entry(row["id"]) if row is not None else None

    def update_entry(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: EntryKind | None = None,
        entry_date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        decision_applied: bool | None = None,
        expected_version: int | None = None,
    ) -> Entry:
        """Update an entry; a title/body change keeps the previous text as a version.

        ``expected_version`` rejects the update if someone saved in between
        (two devices editing the same entry).
        """
        with self._tx():
            current = self.get_entry(entry_id)
            if expected_version is not None and expected_version != current.version:
                raise InvalidOperationError(
                    f"entry changed elsewhere (version {current.version}, expected {expected_version})"
                )
            changes: dict[str, Any] = {}
            text_changed = (title is not None and title.strip() != current.title) or (
                body is not None and body != current.body
            )
            if title is not None:
                changes["title"] = title.strip()
            if body is not None:
                changes["body"] = body
            if kind is not None:
                changes["kind"] = kind
                if kind != "decision":
                    changes["decision_applied"] = None
                elif current.decision_applied is None:
                    changes["decision_applied"] = 0
            if entry_date is not None:
                changes["entry_date"] = _check_date(entry_date, "entry_date")
            if start_time is not None:
                changes["start_time"] = _check_time(start_time, "start_time") if start_time else None
            if end_time is not None:
                changes["end_time"] = _check_time(end_time, "end_time") if end_time else None
            if decision_applied is not None:
                if (kind or current.kind) != "decision":
                    raise InvalidOperationError("only decisions can be applied")
                changes["decision_applied"] = int(decision_applied)
            if not changes:
                return current
            now = _utc(_now())
            if text_changed:
                self.conn.execute(
                    "INSERT INTO entry_versions(entry_id, version, title, body, saved_at) VALUES (?, ?, ?, ?, ?)",
                    (entry_id, current.version, current.title, current.body, current.updated_at),
                )
                changes["version"] = current.version + 1
            changes["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in changes)
            try:
                self.conn.execute(f"UPDATE entries SET {sets} WHERE id = ?", (*changes.values(), entry_id))
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            return self.get_entry(entry_id)

    def entry_versions(self, entry_id: str) -> list[EntryVersion]:
        """Previous versions, newest first (the current text is in the entry itself)."""
        rows = self.conn.execute(
            "SELECT * FROM entry_versions WHERE entry_id = ? ORDER BY version DESC", (entry_id,)
        ).fetchall()
        return [_row_to(EntryVersion, r) for r in rows]

    def set_entry_people(self, entry_id: str, people: Iterable[str]) -> None:
        with self._tx():
            self._require("entries", entry_id)
            self.conn.execute("DELETE FROM entry_people WHERE entry_id = ?", (entry_id,))
            for pid in self._resolve_people(people):
                self.conn.execute("INSERT INTO entry_people(entry_id, person_id) VALUES (?, ?)", (entry_id, pid))

    def set_entry_tags(self, entry_id: str, tags: Iterable[str]) -> None:
        with self._tx():
            self._require("entries", entry_id)
            self.conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
            for tid in self._resolve_tags(tags):
                self.conn.execute("INSERT INTO entry_tags(entry_id, tag_id) VALUES (?, ?)", (entry_id, tid))

    def entry_people(self, entry_id: str) -> list[Person]:
        rows = self.conn.execute(
            "SELECT p.* FROM people p JOIN entry_people ep ON ep.person_id = p.id WHERE ep.entry_id = ?"
            " ORDER BY p.display_name", (entry_id,)
        ).fetchall()
        return [_row_to(Person, r) for r in rows]

    def timeline(
        self,
        *,
        space_id: str | None = None,
        project_id: str | None = None,
        include_subprojects: bool = True,
        task_id: str | None = None,
        person_id: str | None = None,
        tag_id: str | None = None,
        day: str | None = None,
        limit: int = 200,
    ) -> list[Entry]:
        """Entries, newest first, filtered by any combination of the arguments.

        The project journal, a person's history, a tag page, a task's thread and
        the day's page are all this one query.
        """
        where: list[str] = []
        params: list[Any] = []
        if space_id is not None:
            where.append("e.space_id = ?")
            params.append(space_id)
        if project_id is not None:
            if include_subprojects:
                where.append("(e.project_id = ? OR e.project_id IN (SELECT id FROM projects WHERE parent_id = ?))")
                params += [project_id, project_id]
            else:
                where.append("e.project_id = ?")
                params.append(project_id)
        if task_id is not None:
            where.append("e.task_id = ?")
            params.append(task_id)
        if person_id is not None:
            where.append("EXISTS (SELECT 1 FROM entry_people ep WHERE ep.entry_id = e.id AND ep.person_id = ?)")
            params.append(person_id)
        if tag_id is not None:
            where.append(
                "(EXISTS (SELECT 1 FROM entry_tags et WHERE et.entry_id = e.id AND et.tag_id = ?)"
                " OR EXISTS (SELECT 1 FROM entry_people ep JOIN person_tags pt ON pt.person_id = ep.person_id"
                "            WHERE ep.entry_id = e.id AND pt.tag_id = ?))"
            )
            params += [tag_id, tag_id]
        if day is not None:
            where.append("e.entry_date = ?")
            params.append(_check_date(day, "day"))
        sql = "SELECT e.* FROM entries e"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.entry_date DESC, coalesce(e.start_time, '99:99') DESC, e.created_at DESC LIMIT ?"
        params.append(int(limit))
        out = []
        for r in self.conn.execute(sql, params).fetchall():
            applied = r["decision_applied"]
            out.append(_row_to(Entry, r, decision_applied=None if applied is None else bool(applied)))
        return out

    def last_exchange(self, person_id: str) -> str | None:
        row = self._one(
            "SELECT max(e.entry_date) FROM entries e JOIN entry_people ep ON ep.entry_id = e.id WHERE ep.person_id = ?",
            (person_id,),
        )
        return row[0] if row is not None else None

    # ------------------------------------------------------------ search

    @staticmethod
    def _fts_query(text: str) -> str | None:
        words = re.findall(r"\w+", text, flags=re.UNICODE)
        if not words:
            return None
        # Each word quoted (no FTS syntax injection), the last one as a prefix.
        quoted = [f'"{w}"' for w in words[:-1]] + [f'"{words[-1]}"*']
        return " ".join(quoted)

    def search(self, text: str, *, limit: int = 50) -> list[SearchHit]:
        query = self._fts_query(text)
        if query is None:
            return []
        hits: list[SearchHit] = []
        for r in self.conn.execute(
            "SELECT e.id, e.title, snippet(entries_fts, 1, '[', ']', '…', 12) AS snip FROM entries_fts"
            " JOIN entries e ON e.rowid = entries_fts.rowid WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ):
            hits.append(SearchHit("entry", r["id"], r["title"], r["snip"]))
        for r in self.conn.execute(
            "SELECT t.id, t.title, snippet(tasks_fts, 1, '[', ']', '…', 12) AS snip FROM tasks_fts"
            " JOIN tasks t ON t.rowid = tasks_fts.rowid WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ):
            hits.append(SearchHit("task", r["id"], r["title"], r["snip"]))
        return hits

    # ------------------------------------------------------------ time

    def _block(self, row: sqlite3.Row) -> TimeBlock:
        return _row_to(
            TimeBlock,
            row,
            start_at=_parse_utc(row["start_at"]),
            end_at=_parse_utc(row["end_at"]) if row["end_at"] else None,
            validated=bool(row["validated"]),
        )

    def get_block(self, block_id: str) -> TimeBlock:
        return self._block(self._require("time_blocks", block_id))

    def _target(self, project_id: str | None, space_id: str | None, task_id: str | None) -> tuple[str, str | None]:
        if task_id is not None and project_id is None and space_id is None:
            task = self.get_task(task_id)
            return task.space_id, task.project_id
        space, project = self._scope_for(project_id=project_id, space_id=space_id)
        if task_id is not None:
            task = self.get_task(task_id)
            if task.space_id != space or (project is not None and task.project_id != project):
                raise InvalidOperationError("the task belongs to another project")
        return space, project

    def start_timer(
        self,
        *,
        project_id: str | None = None,
        space_id: str | None = None,
        task_id: str | None = None,
        note: str | None = None,
        at: datetime | None = None,
    ) -> TimeBlock:
        """Start a timer. Others keep running: overlapping time is shared by default."""
        with self._tx():
            space, project = self._target(project_id, space_id, task_id)
            block_id = _new_id()
            self.conn.execute(
                "INSERT INTO time_blocks(id, space_id, project_id, task_id, start_at, source, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'timer', ?, ?)",
                (block_id, space, project, task_id, _utc(at or _now()), _clean(note), _utc(_now())),
            )
            return self.get_block(block_id)

    def stop_timer(self, block_id: str, *, at: datetime | None = None) -> TimeBlock:
        with self._tx():
            block = self.get_block(block_id)
            if block.end_at is not None:
                raise InvalidOperationError("this timer is already stopped")
            end = at or _now()
            if end <= block.start_at:
                raise InvalidOperationError("a timer cannot stop before it started")
            self.conn.execute("UPDATE time_blocks SET end_at = ? WHERE id = ?", (_utc(end), block_id))
            return self.get_block(block_id)

    def running_timers(self) -> list[TimeBlock]:
        rows = self.conn.execute("SELECT * FROM time_blocks WHERE end_at IS NULL ORDER BY start_at").fetchall()
        return [self._block(r) for r in rows]

    def add_block(
        self,
        start: datetime,
        end: datetime,
        *,
        project_id: str | None = None,
        space_id: str | None = None,
        task_id: str | None = None,
        entry_id: str | None = None,
        source: BlockSource = "manual",
        overlap_mode: OverlapMode = "shared",
        note: str | None = None,
    ) -> TimeBlock:
        if end <= start:
            raise InvalidOperationError("a block must end after it starts")
        with self._tx():
            space, project = self._target(project_id, space_id, task_id)
            block_id = _new_id()
            try:
                self.conn.execute(
                    "INSERT INTO time_blocks(id, space_id, project_id, task_id, entry_id, start_at, end_at, source,"
                    " overlap_mode, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (block_id, space, project, task_id, entry_id, _utc(start), _utc(end), source, overlap_mode,
                     _clean(note), _utc(_now())),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            return self.get_block(block_id)

    def update_block(
        self,
        block_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        overlap_mode: OverlapMode | None = None,
        note: str | None = None,
    ) -> TimeBlock:
        with self._tx():
            block = self.get_block(block_id)
            new_start = start or block.start_at
            new_end = end or block.end_at
            if new_end is not None and new_end <= new_start:
                raise InvalidOperationError("a block must end after it starts")
            try:
                self.conn.execute(
                    "UPDATE time_blocks SET start_at = ?, end_at = ?, overlap_mode = ?, note = ?, validated = 0"
                    " WHERE id = ?",
                    (_utc(new_start), _utc(new_end) if new_end else None, overlap_mode or block.overlap_mode,
                     _clean(note) if note is not None else block.note, block_id),
                )
            except sqlite3.IntegrityError as exc:
                raise InvalidOperationError(str(exc)) from exc
            return self.get_block(block_id)

    def reassign_block(
        self, block_id: str, *, project_id: str | None = None, space_id: str | None = None, task_id: str | None = None
    ) -> TimeBlock:
        with self._tx():
            self._require("time_blocks", block_id)
            space, project = self._target(project_id, space_id, task_id)
            self.conn.execute(
                "UPDATE time_blocks SET space_id = ?, project_id = ?, task_id = ?, validated = 0 WHERE id = ?",
                (space, project, task_id, block_id),
            )
            return self.get_block(block_id)

    @staticmethod
    def _day_window(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time(0, 0), tzinfo=tz)
        end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
        return start, end

    def day_report(self, day: date, tz: tzinfo, *, now: datetime | None = None) -> DayReport:
        """Blocks of a local day, clipped to it, with the time credited to each."""
        win_start, win_end = self._day_window(day, tz)
        moment = now or _now()
        rows = self.conn.execute(
            "SELECT * FROM time_blocks WHERE start_at < ? AND (end_at IS NULL OR end_at > ?) ORDER BY start_at",
            (_utc(win_end), _utc(win_start)),
        ).fetchall()
        clipped: list[tuple[TimeBlock, datetime, datetime]] = []
        for r in rows:
            block = self._block(r)
            start = max(block.start_at, win_start)
            end = min(block.end_at or moment, win_end)
            if end > start:
                clipped.append((block, start, end))
        spans = [Span(b.id, s, e, cast(OverlapMode, b.overlap_mode)) for b, s, e in clipped]
        credit = counted_seconds(spans)
        counted = [CountedBlock(b, s, e, credit[b.id]) for b, s, e in clipped]
        by_space: dict[str, int] = {}
        by_project: dict[str | None, int] = {}
        for c in counted:
            by_space[c.block.space_id] = by_space.get(c.block.space_id, 0) + c.counted_seconds
            by_project[c.block.project_id] = by_project.get(c.block.project_id, 0) + c.counted_seconds
        return DayReport(day, counted, presence_seconds(spans), by_space, by_project)

    def validate_day(self, day: date, tz: tzinfo) -> int:
        """Mark the day's finished blocks as checked. Returns how many were marked."""
        win_start, win_end = self._day_window(day, tz)
        with self._tx():
            cur = self.conn.execute(
                "UPDATE time_blocks SET validated = 1 WHERE end_at IS NOT NULL AND start_at < ? AND end_at > ?",
                (_utc(win_end), _utc(win_start)),
            )
            return int(cur.rowcount)
