"""Routes of the code journal: link a project to a repository, read its work items, sync."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from pige.model import ModelStore
from pige.server.code import OPEN_STATUSES, CodeError, CodeJournal, normalize_repo

HEX = r"^[0-9a-f]{32}$"


class RepoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str | None = Field(default=None, max_length=300)  # None or "": unlink


def build_code_router(
    store: ModelStore, journal: CodeJournal, require_auth: Callable[..., Any], require_session: Callable[..., Any],
    has_token: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_auth)])

    def view(project_id: str) -> dict[str, Any]:
        store.get_project(project_id)
        link = store.project_repo(project_id)
        if link is None:
            return {"repo": None, "token": has_token}
        fiches = link["fiches"]
        return {
            "repo": link["repo"], "branch": link["branch"], "last_sync": link["last_sync"],
            "last_error": link["last_error"], "token": has_token,
            "chantiers": [f for f in fiches if f["status"] in OPEN_STATUSES],
            "closed": sum(1 for f in fiches if f["status"] not in OPEN_STATUSES),
        }

    @router.get("/projects/{project_id}/code")
    def get_code(project_id: str) -> dict[str, Any]:
        return view(project_id)

    @router.put("/projects/{project_id}/repo")
    def set_repo(project_id: str, body: RepoIn, _sid: str = Depends(require_session)) -> dict[str, Any]:
        if not body.repo or not body.repo.strip():
            store.set_project_repo(project_id, None)
            return view(project_id)
        try:
            repo = normalize_repo(body.repo)
        except CodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        store.set_project_repo(project_id, repo)
        try:
            journal.sync(project_id)
        except CodeError:
            pass  # recorded, shown with the link
        return view(project_id)

    @router.post("/projects/{project_id}/code/sync")
    def sync(project_id: str, _sid: str = Depends(require_session)) -> dict[str, Any]:
        try:
            journal.sync(project_id)
        except CodeError:
            pass
        return view(project_id)

    return router
