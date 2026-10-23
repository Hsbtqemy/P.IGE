"""JSON API on the new model, under /api/v2 (see docs/modele.md).

The PoC routes in app.py (/api/tasks…) keep working on the legacy JSON data
for the current web app and the Thunderbird extension until they move here.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from pige.model.store import Entry, ModelStore

HEX = r"^[0-9a-f]{32}$"
IdPath = Annotated[str, Path(pattern=HEX)]
ShortText = Annotated[str, Field(min_length=1, max_length=300)]
StepText = Annotated[str, Field(min_length=1, max_length=500)]

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
    id: str | None = OptHexId  # chosen by the device: sending again returns the same task
    title: str = Field(min_length=1, max_length=500)
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    note: str | None = Field(default=None, max_length=50_000)
    due_date: str | None = OptDate
    origin_entry_id: str | None = OptHexId
    people: list[ShortText] = Field(default_factory=list, max_length=50)
    person_ids: list[Annotated[str, Field(pattern=HEX)]] = Field(default_factory=list, max_length=50)
    tags: list[ShortText] = Field(default_factory=list, max_length=50)
    steps: list[StepText] = Field(default_factory=list, max_length=200)


class TaskPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=50_000)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears it
    status: Literal["open", "in_progress", "waiting", "done"] | None = None
    waiting_on: str | None = OptHexId
    people: list[ShortText] | None = Field(default=None, max_length=50)
    person_ids: list[Annotated[str, Field(pattern=HEX)]] | None = Field(default=None, max_length=50)
    tags: list[ShortText] | None = Field(default=None, max_length=50)


class TaskMove(_In):
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId


class ProjectPersonIn(_In):
    role: str | None = Field(default=None, max_length=120)


class FollowUpIn(_In):
    entry_date: str = Date
    body: str = Field(min_length=1, max_length=20_000)


class MailFollowUpIn(_In):
    """A mail for a task's follow-up, sent by the Thunderbird extension."""

    message_id: str = Field(min_length=3, max_length=998)
    references: list[Annotated[str, Field(max_length=998)]] = Field(default_factory=list, max_length=100)
    direction: Literal["sent", "received"]
    sent_at: datetime
    day: str = Date  # the local day of sent_at, for the « Échange du … » entry
    author: str = Field(default="", max_length=500)
    recipients: str = Field(default="", max_length=2000)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20_000)
    attachments: str = Field(default="", max_length=2000)


class StepIn(_In):
    label: str = Field(min_length=1, max_length=500)


class StepPatch(_In):
    done: bool


class EntryIn(_In):
    id: str | None = OptHexId  # chosen by the device: sending again returns the same entry
    entry_date: str = Date
    project_id: str | None = OptHexId
    space_id: str | None = OptHexId
    task_id: str | None = OptHexId
    kind: Literal["note", "meeting", "decision", "activity"] = "note"
    title: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=200_000)
    start_time: str | None = OptTime
    end_time: str | None = OptTime
    source: Literal["journal", "writing", "capture", "mail", "import"] = "capture"
    mail_message_id: str | None = Field(default=None, max_length=998)
    people: list[ShortText] = Field(default_factory=list, max_length=50)
    person_ids: list[Annotated[str, Field(pattern=HEX)]] = Field(default_factory=list, max_length=50)
    tags: list[ShortText] = Field(default_factory=list, max_length=50)


class EntryPatch(_In):
    expected_revision: int = Field(ge=1)  # required: protects edits made on another device
    autosave: bool = False  # saving while typing: versions only after a pause
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=200_000)
    kind: Literal["note", "meeting", "decision", "activity"] | None = None
    entry_date: str | None = OptDate
    start_time: str | None = OptTime  # "" clears it
    end_time: str | None = OptTime
    decision_applied: bool | None = None
    people: list[ShortText] | None = Field(default=None, max_length=50)
    person_ids: list[Annotated[str, Field(pattern=HEX)]] | None = Field(default=None, max_length=50)
    tags: list[ShortText] | None = Field(default=None, max_length=50)


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
    tags: list[ShortText] | None = Field(default=None, max_length=50)


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
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return value


def _cleared(body: BaseModel, fields: tuple[str, ...]) -> dict[str, str]:
    """Fields sent explicitly as null: "" for the store, which treats it as « clear »."""
    return {f: "" for f in fields if f in body.model_fields_set and getattr(body, f) is None}


def _not_null(body: BaseModel, fields: tuple[str, ...]) -> None:
    for f in fields:
        if f in body.model_fields_set and getattr(body, f) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f} cannot be cleared")


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
    def require_v2(request: Request, auth: str = Depends(require_auth)) -> str:
        # API tokens (Thunderbird extension, scripts) capture and read; only the
        # signed-in web app may delete, so a leaked token cannot wipe anything.
        if auth == "token" and request.method == "DELETE":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Deleting needs the signed-in web app")
        return auth

    router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_v2)])

    # ------------------------------------------------------------ overview

    @router.get("/tree")
    def tree(include_archived: bool = False) -> dict[str, Any]:
        """Everything the side column needs: spaces with their projects, pinned tags.

        ``include_archived`` adds archived spaces and closed projects (to reopen them)."""
        counts = store.open_task_counts()
        states = ("active", "dormant", "closed") if include_archived else ("active", "dormant")
        projects = store.list_projects(states=states)
        spaces = []
        for space in store.list_spaces(include_archived=include_archived):
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
    def update_space(space_id: IdPath, body: SpacePatch) -> dict[str, Any]:
        with store.transaction():
            if body.name is not None:
                store.rename_space(space_id, body.name)
            if body.archived is not None:
                store.set_space_archived(space_id, body.archived)
            return _out(store.get_space(space_id))

    @router.post("/spaces/{space_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_space(space_id: IdPath, body: PlaceIn) -> Response:
        store.move_space(space_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_space(space_id: IdPath) -> Response:
        store.delete_space(space_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ projects

    def _project_view(project_id: str) -> dict[str, Any]:
        project = store.get_project(project_id)
        return {
            **_out(project),
            "links": [{"url": u, "label": label} for u, label in store.project_links(project_id)],
            "last_activity": store.last_activity(project_id),
            "open_tasks": store.open_task_count(project_id),
            "people": _project_people(project),
        }

    def _project_people(project: Any) -> list[dict[str, Any]]:
        """The project's people, then (shown, not copied) those of its parent project."""
        out = [{**_out(p), "project_role": role, "inherited": False} for p, role in store.project_people(project.id)]
        if project.parent_id:
            own = {p["id"] for p in out}
            out += [
                {**_out(p), "project_role": role, "inherited": True}
                for p, role in store.project_people(project.parent_id) if p.id not in own
            ]
        return out

    @router.put("/projects/{project_id}/people/{person_id}")
    def set_project_person(project_id: IdPath, person_id: IdPath, body: ProjectPersonIn) -> dict[str, Any]:
        store.set_project_person(project_id, person_id, body.role)
        return _project_view(project_id)

    @router.delete("/projects/{project_id}/people/{person_id}")
    def remove_project_person(project_id: IdPath, person_id: IdPath) -> dict[str, Any]:
        store.remove_project_person(project_id, person_id)
        return _project_view(project_id)

    @router.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(body: ProjectIn) -> dict[str, Any]:
        project = store.create_project(
            body.space_id, body.name, parent_id=body.parent_id, description=body.description, team=body.team
        )
        return _project_view(project.id)

    @router.get("/projects/{project_id}")
    def get_project(project_id: IdPath) -> dict[str, Any]:
        return _project_view(project_id)

    @router.patch("/projects/{project_id}")
    def update_project(project_id: IdPath, body: ProjectPatch) -> dict[str, Any]:
        _not_null(body, ("name", "state"))
        fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        fields.update(_cleared(body, ("description", "team")))
        store.update_project(project_id, **fields)
        return _project_view(project_id)

    @router.post("/projects/{project_id}/move")
    def move_project(project_id: IdPath, body: ProjectMove) -> dict[str, Any]:
        store.move_project(project_id, space_id=body.space_id, parent_id=body.parent_id)
        return _project_view(project_id)

    @router.post("/projects/{project_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_project(project_id: IdPath, body: PlaceIn) -> Response:
        store.reorder_project(project_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/projects/{project_id}/links")
    def set_links(project_id: IdPath, body: Annotated[list[LinkIn], Field(max_length=50)]) -> dict[str, Any]:
        store.set_project_links(project_id, [(link.url, link.label) for link in body])
        return _project_view(project_id)

    @router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_project(project_id: IdPath) -> Response:
        store.delete_project(project_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/projects/{project_id}/tasks")
    def project_tasks(
        project_id: str, include_done: bool = False, done_limit: int = Query(default=50, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        store.get_project(project_id)
        return _out(store.tasks_for_project(project_id, include_done=include_done, done_limit=done_limit))

    @router.get("/spaces/{space_id}/tasks")
    def space_tasks(space_id: IdPath) -> list[dict[str, Any]]:
        """Open tasks attached to the space itself (no project)."""
        store.get_space(space_id)
        return _out(store.tasks_for_space(space_id))

    @router.get("/stale-projects")
    def stale_projects(days: int = Query(default=30, ge=1, le=3650)) -> list[dict[str, Any]]:
        return [{**_out(p), "last_activity": last} for p, last in store.stale_projects(days=days)]

    # ------------------------------------------------------------ tasks

    def _task_view(task_id: str) -> dict[str, Any]:
        return {
            **_out(store.get_task(task_id)),
            "steps": _out(store.steps(task_id)),
            "people": _out(store.task_people(task_id)),
            "tags": _out(store.task_tags(task_id)),
        }

    @router.post("/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(body: TaskIn, response: Response) -> dict[str, Any]:
        with store.transaction():
            if body.id is not None and store.task_exists(body.id):
                response.status_code = status.HTTP_200_OK  # a resend after a lost reply
                return _task_view(body.id)
            return _new_task(body)

    def _new_task(body: TaskIn) -> dict[str, Any]:
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
            new_id=body.id,
        )
        return _task_view(task.id)

    @router.get("/tasks")
    def open_tasks(living: bool = False) -> list[dict[str, Any]]:
        """Every open task (the « Tâches » view groups them by project); ``living``: only those
        of active projects and spaces (the day's plan)."""
        return _out(store.open_tasks(living=living))

    @router.get("/tasks/done")
    def done_tasks(since: datetime, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        """Tasks finished since a moment (« Terminées aujourd'hui » in Ma journée)."""
        if since.tzinfo is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "since: a time with its offset is expected")
        return _out(store.done_tasks_since(since, limit=limit))

    @router.get("/tasks/{task_id}/mails")
    def task_mails(task_id: IdPath) -> list[dict[str, Any]]:
        store.get_task(task_id)
        return _out(store.task_mails(task_id))

    @router.post("/tasks/{task_id}/followups", status_code=status.HTTP_201_CREATED)
    def add_followup(task_id: IdPath, body: FollowUpIn) -> dict[str, Any]:
        """« Ajouter un suivi »: a dated note of the task, in the journal too."""
        task = store.get_task(task_id)
        entry = store.create_entry(
            entry_date=body.entry_date, project_id=task.project_id,
            space_id=None if task.project_id else task.space_id, task_id=task_id, body=body.body, source="journal",
        )
        return _entry_view(entry.id)

    @router.post("/mail-followups")
    def add_mail_followup(body: MailFollowUpIn, response: Response) -> dict[str, Any]:
        """A reply sent (or a mail kept) about a mail a task came from: into that task's follow-up."""
        if body.sent_at.tzinfo is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "sent_at: a time with its offset is expected")
        with store.transaction():
            task_id = store.task_for_mail([*body.references, body.message_id])
            if task_id is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune tâche ne vient de cet échange")
            task = store.get_task(task_id)
            if task.origin_entry_id is not None:
                origin = store.get_entry(task.origin_entry_id)
                if (origin.mail_message_id or "").strip() == body.message_id.strip():
                    # The mail the task came from is already shown above the follow-up.
                    raise HTTPException(status.HTTP_409_CONFLICT, "C'est le mail dont la tâche est issue")
            mail, created = store.add_task_mail(
                task_id, message_id=body.message_id, direction=body.direction, sent_at=body.sent_at, day=body.day,
                author=body.author, recipients=body.recipients, subject=body.subject, body=body.body,
                attachments=body.attachments,
            )
            response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return {"task": _out(store.get_task(task_id)), "mail": _out(mail), "created": created}

    @router.delete("/task-mails/{mail_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task_mail(mail_id: IdPath) -> Response:
        store.delete_task_mail(mail_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/tasks/in-progress")
    def tasks_in_progress() -> list[dict[str, Any]]:
        return _out(store.in_progress_tasks())

    @router.get("/tasks/{task_id}")
    def get_task(task_id: IdPath) -> dict[str, Any]:
        return _task_view(task_id)

    @router.patch("/tasks/{task_id}")
    def update_task(task_id: IdPath, body: TaskPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        _not_null(body, ("title", "status", "people", "person_ids", "tags"))
        with store.transaction():
            if {"title", "note", "due_date"} & fields.keys():
                store.update_task(
                    task_id,
                    title=body.title,
                    note="" if "note" in fields and body.note is None else body.note,
                    due_date=body.due_date or None,
                    clear_due_date="due_date" in fields and not body.due_date,
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
    def move_task(task_id: IdPath, body: TaskMove) -> dict[str, Any]:
        store.move_task(task_id, project_id=body.project_id, space_id=body.space_id)
        return _task_view(task_id)

    @router.post("/tasks/{task_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_task(task_id: IdPath, body: PlaceIn) -> Response:
        store.reorder_task(task_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(task_id: IdPath) -> Response:
        store.delete_task(task_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/tasks/{task_id}/steps", status_code=status.HTTP_201_CREATED)
    def add_step(task_id: IdPath, body: StepIn) -> dict[str, Any]:
        return _out(store.add_step(task_id, body.label))

    @router.patch("/steps/{step_id}")
    def update_step(step_id: IdPath, body: StepPatch) -> dict[str, Any]:
        return _out(store.set_step_done(step_id, body.done))

    @router.post("/steps/{step_id}/place", status_code=status.HTTP_204_NO_CONTENT)
    def place_step(step_id: IdPath, body: PlaceIn) -> Response:
        store.reorder_step(step_id, **_place(body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_step(step_id: IdPath) -> Response:
        store.delete_step(step_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ entries

    def _entry_views(entries: list[Entry]) -> list[dict[str, Any]]:
        ids = [e.id for e in entries]
        people = store.people_for_entries(ids)
        tags = store.tags_for_entries(ids)
        code = store.code_summaries([e.id for e in entries if e.source == "import"])
        return [
            {**_out(e), "people": _out(people[e.id]), "tags": _out(tags[e.id]),
             **({"code": code[e.id]} if e.id in code else {})}
            for e in entries
        ]

    def _entry_view(entry_id: str) -> dict[str, Any]:
        return _entry_views([store.get_entry(entry_id)])[0]

    @router.get("/timeline")
    def timeline(
        space_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        project_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        task_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        person_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        tag_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        source: Literal["journal", "writing", "capture", "mail", "import"] | None = None,
        without_project: bool = False,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> list[dict[str, Any]]:
        entries = store.timeline(
            space_id=space_id, project_id=project_id, task_id=task_id, person_id=person_id,
            tag_id=tag_id, day=day, source=source, without_project=without_project, limit=limit, offset=offset,
        )
        return _entry_views(entries)

    @router.get("/journal/days")
    def journal_days(month: str = Query(pattern=r"^\d{4}-\d{2}$")) -> list[str]:
        """Days of the month that have a page in the journal (for the little calendar)."""
        return store.entry_days(month)

    @router.post("/entries", status_code=status.HTTP_201_CREATED)
    def create_entry(body: EntryIn, response: Response) -> dict[str, Any]:
        if body.id is not None:
            with store.transaction():
                if store.entry_exists(body.id):
                    response.status_code = status.HTTP_200_OK  # a resend after a lost reply
                    _complete_mail(body.id, body)
                    return _entry_view(body.id)
                if not body.mail_message_id:
                    return _entry_view(_create_entry(body).id)
        if body.mail_message_id:
            # The extension may resend after a lost reply: the same mail gives the same entry.
            # Checked inside the write transaction, so two simultaneous resends cannot both insert.
            with store.transaction():
                existing = store.entry_by_mail(body.mail_message_id)
                if existing is not None:
                    response.status_code = status.HTTP_200_OK
                    _complete_mail(existing.id, body)
                    return _entry_view(existing.id)
                return _entry_view(_create_entry(body).id)
        return _entry_view(_create_entry(body).id)

    def _complete_mail(entry_id: str, body: EntryIn) -> None:
        """A mail filed again by a newer extension brings its full text: it replaces the short
        excerpt of the first filing, unless the entry's text was edited since (then the old text
        is no longer contained in the new one)."""
        if body.source != "mail":
            return
        current = store.get_entry(entry_id)
        if current.source != "mail" or len(body.body) <= len(current.body):
            return
        old = " ".join(current.body.rstrip().removesuffix("…").split())
        if old not in " ".join(body.body.split()):
            return
        store.update_entry(entry_id, body=body.body, expected_revision=current.revision)

    def _create_entry(body: EntryIn) -> Entry:
        data = body.model_dump()
        data["new_id"] = data.pop("id")
        data["start_time"] = data["start_time"] or None
        data["end_time"] = data["end_time"] or None
        with store.transaction():
            entry = store.create_entry(**data)
            store.sync_entry_block(entry.id, _zone(default_timezone))
            return entry

    @router.get("/entries/{entry_id}")
    def get_entry(entry_id: IdPath) -> dict[str, Any]:
        return _entry_view(entry_id)

    @router.patch("/entries/{entry_id}")
    def update_entry(entry_id: IdPath, body: EntryPatch) -> dict[str, Any]:
        _not_null(body, ("kind", "entry_date", "decision_applied", "people", "person_ids", "tags"))
        cleared = _cleared(body, ("title", "body", "start_time", "end_time"))
        with store.transaction():
            store.update_entry(
                entry_id,
                expected_revision=body.expected_revision,
                title=cleared.get("title", body.title),
                body=cleared.get("body", body.body),
                kind=body.kind,
                entry_date=body.entry_date,
                start_time=cleared.get("start_time", body.start_time),
                end_time=cleared.get("end_time", body.end_time),
                decision_applied=body.decision_applied,
                autosave=body.autosave,
            )
            if body.people is not None or body.person_ids is not None:
                store.set_entry_people(entry_id, names=body.people or [], person_ids=body.person_ids or [])
            if body.tags is not None:
                store.set_entry_tags(entry_id, body.tags)
            # A range set by hand counts its time (Ma journée), and the block follows the entry.
            # A meeting noted from the agenda counts only once its range is touched.
            ranged = {"start_time", "end_time", "entry_date"} & body.model_fields_set
            if ranged or store.entry_block(entry_id) is not None:
                store.sync_entry_block(entry_id, _zone(default_timezone))
            return _entry_view(entry_id)

    @router.post("/entries/{entry_id}/move")
    def move_entry(entry_id: IdPath, body: EntryMove) -> dict[str, Any]:
        store.move_entry(entry_id, project_id=body.project_id, space_id=body.space_id, task_id=body.task_id)
        return _entry_view(entry_id)

    @router.get("/entries/{entry_id}/versions")
    def entry_versions(entry_id: IdPath, limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        store.get_entry(entry_id)
        return _out(store.entry_versions(entry_id, limit=limit))

    @router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_entry(entry_id: IdPath) -> Response:
        store.delete_entry(entry_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ people and tags

    @router.get("/people")
    def people(tag_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$")) -> list[dict[str, Any]]:
        last = store.last_exchanges()
        return [{**_out(p), "last_exchange": last.get(p.id)} for p in store.list_people(tag_id)]

    @router.post("/people")
    def find_or_create_person(body: PersonIn, response: Response) -> dict[str, Any]:
        person, created = store.find_or_create_person(body.name)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return _person_view(person.id)

    def _person_view(person_id: str) -> dict[str, Any]:
        return {
            **_out(store.get_person(person_id)),
            "tags": _out(store.person_tags(person_id)),
            "last_exchange": store.last_exchange(person_id),
            "waiting_on": _out(store.waiting_on(person_id)),  # « J'attends d'elle »
            "involved_in": _out(store.tasks_for_person(person_id)),
            "projects": [{**_out(p), "project_role": role} for p, role in store.person_projects(person_id)],
        }

    @router.get("/people/{person_id}")
    def get_person(person_id: IdPath) -> dict[str, Any]:
        return _person_view(person_id)

    @router.patch("/people/{person_id}")
    def update_person(person_id: IdPath, body: PersonPatch) -> dict[str, Any]:
        _not_null(body, ("display_name", "tags"))
        fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        tags = fields.pop("tags", None)
        fields.update(_cleared(body, ("email", "organisation", "role", "note")))
        with store.transaction():
            store.update_person(person_id, **fields)
            if tags is not None:
                for tag in store.person_tags(person_id):
                    store.untag_person(person_id, tag.id)
                store.tag_person(person_id, tags)
            return _person_view(person_id)

    @router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_person(person_id: IdPath) -> Response:
        store.delete_person(person_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/tags")
    def tags() -> list[dict[str, Any]]:
        return [{**_out(tag), "uses": uses} for tag, uses in store.list_tags()]

    @router.get("/tags/{tag_id}")
    def get_tag(tag_id: IdPath) -> dict[str, Any]:
        return {
            **_out(store.get_tag(tag_id)),
            "people": _out(store.list_people(tag_id)),
            "tasks": _out(store.tasks_for_tag(tag_id)),
        }

    @router.patch("/tags/{tag_id}")
    def update_tag(tag_id: IdPath, body: TagPatch) -> dict[str, Any]:
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
    def stop_timer(block_id: IdPath, body: TimerStop) -> dict[str, Any]:
        return _out(store.stop_timer(block_id, at=body.at))

    @router.post("/blocks", status_code=status.HTTP_201_CREATED)
    def add_block(body: BlockIn) -> dict[str, Any]:
        return _out(store.add_block(**body.model_dump()))

    @router.patch("/blocks/{block_id}")
    def update_block(block_id: IdPath, body: BlockPatch) -> dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        _not_null(body, ("start", "overlap_mode"))
        with store.transaction():
            current = store.get_block(block_id)
            if {"project_id", "space_id", "task_id"} & fields.keys():
                # Only the fields sent change; the others keep their current value.
                project = fields["project_id"] if "project_id" in fields else current.project_id
                task = fields["task_id"] if "task_id" in fields else current.task_id
                space = fields["space_id"] if "space_id" in fields else (None if project else current.space_id)
                store.reassign_block(block_id, project_id=project, space_id=space, task_id=task)
            if {"start", "end", "overlap_mode", "note"} & fields.keys():
                store.update_block(
                    block_id,
                    start=body.start,
                    end=body.end,
                    overlap_mode=body.overlap_mode,
                    note="" if "note" in fields and body.note is None else body.note,
                )
            return _out(store.get_block(block_id))

    @router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_block(block_id: IdPath) -> Response:
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

    @router.get("/weeks/{day}")
    def week_report(day: date, tz: str = Query(default=default_timezone, max_length=64)) -> dict[str, Any]:
        """The week (Monday to Sunday) holding ``day``: time per day, per space and per project."""
        zone_ = _zone(tz)
        monday = day - timedelta(days=day.weekday())
        days: list[dict[str, Any]] = []
        by_space: dict[str, int] = {}
        by_project: dict[str, int] = {}
        for i in range(7):
            report = store.day_report(monday + timedelta(days=i), zone_)
            days.append({"day": report.day.isoformat(), "presence_seconds": report.presence_seconds,
                         "counted_seconds": sum(report.by_space.values())})
            for k, v in report.by_space.items():
                by_space[k] = by_space.get(k, 0) + v
            for pk, v in report.by_project.items():
                by_project[pk or ""] = by_project.get(pk or "", 0) + v
        return {
            "start": monday.isoformat(),
            "end": (monday + timedelta(days=6)).isoformat(),
            "presence_seconds": sum(d["presence_seconds"] for d in days),
            "days": days,
            "by_space": by_space,
            "by_project": by_project,
        }

    @router.post("/days/{day}/validate")
    def validate_day(day: date, tz: str = Query(default=default_timezone, max_length=64)) -> dict[str, int]:
        return {"validated": store.validate_day(day, _zone(tz))}

    return router
