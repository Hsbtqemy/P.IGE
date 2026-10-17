"""JSON API on the new model, under /api/v2 (see docs/modele.md).

The PoC routes in app.py (/api/tasks…) keep working on the legacy JSON data
for the current web app and the Thunderbird extension until they move here.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from pige.model.store import ModelStore

HexId = Field(pattern=r"^[0-9a-f]{32}$")
OptHexId = Field(default=None, pattern=r"^[0-9a-f]{32}$")
Date = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
OptDate = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
OptTime = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
Name = Field(min_length=1, max_length=300)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- schemas


class SpaceIn(_In):
    name: str = Name


class SpacePatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    archived: bool | None = None


class PlaceIn(_In):
    """Relative position in a list: exactly one of before / after."""

    before: str | None = OptHexId
    after: str | None = OptHexId


class ProjectIn(_In):
    space_id: str = HexId
    name: str = Name
    parent_id: str | None = OptHexId
    description: str | None = Field(default=None, max_length=20_000)
    team: str | None = Field(default=None, max_length=50)


class ProjectPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    team: str | None = Field(default=None, max_length=50)
    state: Literal["active", "dormant", "closed"] | None = None


class ProjectMove(_In):
    space_id: str = HexId
    parent_id: str | None = OptHexId


class LinkIn(_In):
    url: str = Field(min_length=1, max_length=2000, pattern=r"^https?://")
    label: str | None = Field(default=None, max_length=200)


class TaskIn(_In):
    title: str = Field(min_length=1, max_length=500)
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    note: str | None = Field(default=None, max_length=50_000)
    due_date: str | None = OptDate
    origin_entry_id: str | None = OptHexId
    people: list[str] = Field(default_factory=list, max_length=50)
    person_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)
    steps: list[str] = Field(default_factory=list, max_length=200)


class TaskPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=50_000)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears it
    status: Literal["open", "in_progress", "waiting", "done"] | None = None
    waiting_on: str | None = OptHexId
    people: list[str] | None = Field(default=None, max_length=50)
    person_ids: list[str] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)


class TaskMove(_In):
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId


class StepIn(_In):
    label: str = Field(min_length=1, max_length=500)


class StepPatch(_In):
    done: bool


class EntryIn(_In):
    entry_date: str = Date
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId
    kind: Literal["note", "meeting", "decision", "activity"] = "note"
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=500_000)
    start_time: str | None = OptTime
    end_time: str | None = OptTime
    source: Literal["journal", "writing", "capture", "mail", "import"] = "capture"
    mail_message_id: str | None = Field(default=None, max_length=998)
    people: list[str] = Field(default_factory=list, max_length=50)
    person_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)


class EntryPatch(_In):
    expected_revision: int = Field(ge=1)  # required: protects edits made on another device
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=500_000)
    kind: Literal["note", "meeting", "decision", "activity"] | None = None
    entry_date: str | None = OptDate
    start_time: str | None = OptTime  # "" clears it
    end_time: str | None = OptTime
    decision_applied: bool | None = None
    people: list[str] | None = Field(default=None, max_length=50)
    person_ids: list[str] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)


class EntryMove(_In):
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId


class PersonIn(_In):
    name: str = Name


class PersonPatch(_In):
    display_name: str | None = Field(default=None, min_length=1, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    organisation: str | None = Field(default=None, max_length=300)
    role: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = Field(default=None, max_length=50)


class TagPatch(_In):
    pinned: bool


class TimerIn(_In):
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId
    note: str | None = Field(default=None, max_length=2000)
    at: datetime | None = None


class TimerStop(_In):
    at: datetime | None = None


class BlockIn(_In):
    start: datetime
    end: datetime
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId
    entry_id: str | None = OptHexId
    source: Literal["timer", "agenda", "manual"] = "manual"
    overlap_mode: Literal["shared", "both", "exclusive"] = "shared"
    note: str | None = Field(default=None, max_length=2000)


class BlockPatch(_In):
    start: datetime | None = None
    end: datetime | None = None
    overlap_mode: Literal["shared", "both", "exclusive"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId


# ---------------------------------------------------------------- helpers


def _out(value: Any) -> Any:
    """Dataclasses (and lists of them) as plain JSON-ready data."""
    if isinstance(value, list):
        return [_out(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _out(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _place(body: PlaceIn) -> dict[str, str | None]:
    if (body.before is None) == (body.after is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give exactly one of before / after")
    return {"before": body.before, "after": body.after}


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown time zone {name!r}") from exc


def build_router(store: ModelStore, require_auth: Callable[..., str], default_timezone: str) -> APIRouter:
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_auth)])

    # ------------------------------------------------------------ overview

    @router.get("/tree")
    def tree() -> dict[str, Any]:
        """Everything the side column needs: spaces with their projects, pinned tags."""
        counts = store.open_task_counts()
        projects = store.list_projects()
        spaces = []
        for space in store.list_spaces():
            items = [
                {**_out(p), "open_tasks": counts.get(p.id, 0)} for p in projects if p.space_id == space.id
            ]
            spaces.append({**_out(space), "projects": items})
        pinned = [{**_out(tag), "uses": uses} for tag, uses in store.pinned_tags()]
        return {"spaces": spaces, "pinned_tags": pinned}

    @router.get("/search")
    def search(
        q: str = Query(min_length=1, max_length=200),
        space_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        include_done: bool = False,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return _out(store.search(q, limit=limit, space_id=space_id, include_done_tasks=include_done))

    # ------------------------------------------------------------ spaces

    @router.post("/spaces", status_code=status.HTTP_201_CREATED)
    def create_space(body: SpaceIn) -> dict[str, Any]:
        return _out(store.create_space(body.name))

    @router.patch("/spaces/{space_id}")
    def update_space(space_id: str, body: SpacePatch) -> dict[str, Any]:
        with store.transaction():
            if body.name is not None:
                store.rename_space(space_id, body.name)
            if body.archived is not None:
                store.set_space_archived(space_id, body.archived)
            return _out(store.get_space(space_id))

    @router.post("/spaces/{space_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_space(space_id: str, body: PlaceIn) -> Response:
        store.move_space(space_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_space(space_id: str) -> Response:
        store.delete_space(space_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ projects

    def _project_view(project_id: str) -> dict[str, Any]:
        project = store.get_project(project_id)
        return {
            **_out(project),
            "links": [{"url": u, "label": label} for u, label in store.project_links(project_id)],
            "last_activity": store.last_activity(project_id),
            "open_tasks": store.open_task_counts().get(project_id, 0),
        }

    @router.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(body: ProjectIn) -> dict[str, Any]:
        project = store.create_project(
            body.space_id, body.name, parent_id=body.parent_id, description=body.description, team=body.team
        )
        return _project_view(project.id)

    @router.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return _project_view(project_id)

    @router.patch("/projects/{project_id}")
    def update_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
        store.update_project(project_id, **body.model_dump(exclude_unset=True))
        return _project_view(project_id)

    @router.post("/projects/{project_id}/move")
    def move_project(project_id: str, body: ProjectMove) -> dict[str, Any]:
        store.move_project(project_id, space_id=body.space_id, parent_id=body.parent_id)
        return _project_view(project_id)

    @router.post("/projects/{project_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_project(project_id: str, body: PlaceIn) -> Response:
        store.reorder_project(project_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/projects/{project_id}/links")
    def set_links(project_id: str, body: list[LinkIn]) -> dict[str, Any]:
        store.set_project_links(project_id, [(link.url, link.label) for link in body[:50]])
        return _project_view(project_id)

    @router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_project(project_id: str) -> Response:
        store.delete_project(project_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/projects/{project_id}/tasks")
    def project_tasks(project_id: str, include_done: bool = False) -> list[dict[str, Any]]:
        store.get_project(project_id)
        return _out(store.tasks_for_project(project_id, include_done=include_done))

    @router.get("/stale-projects")
    def stale_projects(days: int = Query(default=30, ge=1, le=3650)) -> list[dict[str, Any]]:
        return [{**_out(p), "last_activity": last} for p, last in store.stale_projects(days=days)]

    # ------------------------------------------------------------ tasks

    def _task_view(task_id: str) -> dict[str, Any]:
        return {**_out(store.get_task(task_id)), "steps": _out(store.steps(task_id))}

    @router.post("/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(body: TaskIn) -> dict[str, Any]:
        task = store.create_task(
            body.title,
            project_id=body.project_id,
            space_id=body.space_id,
            note=body.note,
            due_date=body.due_date,
            origin_entry_id=body.origin_entry_id,
            people=body.people,
            person_ids=body.person_ids,
            tags=body.tags,
            steps=body.steps,
        )
        return _task_view(task.id)

    @router.get("/tasks/in-progress")
    def tasks_in_progress() -> list[dict[str, Any]]:
        return _out(store.in_progress_tasks())

    @router.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        return _task_view(task_id)

    @router.patch("/tasks/{task_id}")
    def update_task(task_id: str, body: TaskPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        with store.transaction():
            if {"title", "note", "due_date"} & fields.keys():
                store.update_task(
                    task_id,
                    title=body.title,
                    note=body.note,
                    due_date=body.due_date or None,
                    clear_due_date=body.due_date == "",
                )
            if body.status is not None:
                store.set_task_status(task_id, body.status, waiting_on=body.waiting_on)
            elif "waiting_on" in fields:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "waiting_on goes with status 'waiting'")
            if body.people is not None or body.person_ids is not None:
                store.set_task_people(task_id, names=body.people or [], person_ids=body.person_ids or [])
            if body.tags is not None:
                store.set_task_tags(task_id, body.tags)
            return _task_view(task_id)

    @router.post("/tasks/{task_id}/move")
    def move_task(task_id: str, body: TaskMove) -> dict[str, Any]:
        store.move_task(task_id, project_id=body.project_id, space_id=body.space_id)
        return _task_view(task_id)

    @router.post("/tasks/{task_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_task(task_id: str, body: PlaceIn) -> Response:
        store.reorder_task(task_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(task_id: str) -> Response:
        store.delete_task(task_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/tasks/{task_id}/steps", status_code=status.HTTP_201_CREATED)
    def add_step(task_id: str, body: StepIn) -> dict[str, Any]:
        return _out(store.add_step(task_id, body.label))

    @router.patch("/steps/{step_id}")
    def update_step(step_id: str, body: StepPatch) -> dict[str, Any]:
        return _out(store.set_step_done(step_id, body.done))

    @router.post("/steps/{step_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_step(step_id: str, body: PlaceIn) -> Response:
        store.reorder_step(step_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_step(step_id: str) -> Response:
        store.delete_step(step_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ entries

    def _entry_view(entry_id: str) -> dict[str, Any]:
        return {
            **_out(store.get_entry(entry_id)),
            "people": _out(store.entry_people(entry_id)),
            "tags": _out(store.entry_tags(entry_id)),
        }

    @router.get("/timeline")
    def timeline(
        space_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        project_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        task_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        person_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        tag_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> list[dict[str, Any]]:
        entries = store.timeline(
            space_id=space_id, project_id=project_id, task_id=task_id, person_id=person_id,
            tag_id=tag_id, day=day, limit=limit, offset=offset,
        )
        return [_entry_view(e.id) for e in entries]

    @router.post("/entries", status_code=status.HTTP_201_CREATED)
    def create_entry(body: EntryIn) -> dict[str, Any]:
        if body.mail_message_id:
            existing = store.entry_by_mail(body.mail_message_id)
            if existing is not None:  # the extension may resend after a lost reply
                return _entry_view(existing.id)
        data = body.model_dump()
        data["start_time"] = data["start_time"] or None
        data["end_time"] = data["end_time"] or None
        entry = store.create_entry(**data)
        return _entry_view(entry.id)

    @router.get("/entries/{entry_id}")
    def get_entry(entry_id: str) -> dict[str, Any]:
        return _entry_view(entry_id)

    @router.patch("/entries/{entry_id}")
    def update_entry(entry_id: str, body: EntryPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        with store.transaction():
            store.update_entry(
                entry_id,
                expected_revision=body.expected_revision,
                title=body.title,
                body=body.body,
                kind=body.kind,
                entry_date=body.entry_date,
                start_time=body.start_time,
                end_time=body.end_time,
                decision_applied=body.decision_applied,
            )
            if body.people is not None or body.person_ids is not None:
                store.set_entry_people(entry_id, names=body.people or [], person_ids=body.person_ids or [])
            if "tags" in fields and body.tags is not None:
                store.set_entry_tags(entry_id, body.tags)
            return _entry_view(entry_id)

    @router.post("/entries/{entry_id}/move")
    def move_entry(entry_id: str, body: EntryMove) -> dict[str, Any]:
        store.move_entry(entry_id, project_id=body.project_id, space_id=body.space_id, task_id=body.task_id)
        return _entry_view(entry_id)

    @router.get("/entries/{entry_id}/versions")
    def entry_versions(entry_id: str) -> list[dict[str, Any]]:
        store.get_entry(entry_id)
        return _out(store.entry_versions(entry_id))

    @router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_entry(entry_id: str) -> Response:
        store.delete_entry(entry_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ people and tags

    @router.get("/people")
    def people(tag_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$")) -> list[dict[str, Any]]:
        return [
            {**_out(p), "last_exchange": store.last_exchange(p.id)} for p in store.list_people(tag_id)
        ]

    @router.post("/people")
    def find_or_create_person(body: PersonIn, response: Response) -> dict[str, Any]:
        existing = store.find_people(body.name)
        person = existing[0] if existing else store.get_or_create_person(body.name)
        response.status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return _out(person)

    def _person_view(person_id: str) -> dict[str, Any]:
        return {
            **_out(store.get_person(person_id)),
            "tags": _out(store.person_tags(person_id)),
            "last_exchange": store.last_exchange(person_id),
            "waiting_on": _out(store.waiting_on(person_id)),  # « J'attends d'elle »
            "involved_in": _out(store.tasks_for_person(person_id)),
        }

    @router.get("/people/{person_id}")
    def get_person(person_id: str) -> dict[str, Any]:
        return _person_view(person_id)

    @router.patch("/people/{person_id}")
    def update_person(person_id: str, body: PersonPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        tags = fields.pop("tags", None)
        with store.transaction():
            store.update_person(person_id, **fields)
            if tags is not None:
                for tag in store.person_tags(person_id):
                    store.untag_person(person_id, tag.id)
                store.tag_person(person_id, tags)
            return _person_view(person_id)

    @router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_person(person_id: str) -> Response:
        store.delete_person(person_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.patch("/tags/{tag_id}")
    def update_tag(tag_id: str, body: TagPatch) -> dict[str, Any]:
        return _out(store.set_tag_pinned(tag_id, body.pinned))

    # ------------------------------------------------------------ time

    @router.get("/timers")
    def timers() -> list[dict[str, Any]]:
        return _out(store.running_timers())

    @router.post("/timers", status_code=status.HTTP_201_CREATED)
    def start_timer(body: TimerIn) -> dict[str, Any]:
        block = store.start_timer(
            project_id=body.project_id, space_id=body.space_id, task_id=body.task_id, note=body.note, at=body.at
        )
        return _out(block)

    @router.post("/timers/{block_id}/stop")
    def stop_timer(block_id: str, body: TimerStop) -> dict[str, Any]:
        return _out(store.stop_timer(block_id, at=body.at))

    @router.post("/blocks", status_code=status.HTTP_201_CREATED)
    def add_block(body: BlockIn) -> dict[str, Any]:
        return _out(store.add_block(**body.model_dump()))

    @router.patch("/blocks/{block_id}")
    def update_block(block_id: str, body: BlockPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        with store.transaction():
            if {"project_id", "space_id", "task_id"} & fields.keys():
                store.reassign_block(block_id, project_id=body.project_id, space_id=body.space_id, task_id=body.task_id)
            if {"start", "end", "overlap_mode", "note"} & fields.keys():
                store.update_block(block_id, start=body.start, end=body.end, overlap_mode=body.overlap_mode, note=body.note)
            return _out(store.get_block(block_id))

    @router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_block(block_id: str) -> Response:
        store.delete_block(block_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/days/{day}")
    def day_report(day: date, tz: str = Query(default=default_timezone, max_length=64)) -> dict[str, Any]:
        report = store.day_report(day, _zone(tz))
        return {
            "day": report.day.isoformat(),
            "presence_seconds": report.presence_seconds,
            "by_space": report.by_space,
            "by_project": {k or "": v for k, v in report.by_project.items()},
            "blocks": _out(report.blocks),
            "stale_timers": _out(report.stale_timers),
        }

    @router.post("/days/{day}/validate")
    def validate_day(day: date, tz: str = Query(default=default_timezone, max_length=64)) -> dict[str, int]:
        return {"validated": store.validate_day(day, _zone(tz))}

    return router
