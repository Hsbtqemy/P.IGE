"""Routes of the code journal: link a project to a repository, read its work items, sync."""

from __future__ import annotations

from typing import Any, Callable

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from pige.model import ModelStore
from pige.server.code import OPEN_STATUSES, PUSHED, CodeError, CodeJournal, normalize_export, normalize_repo

MAX_EXPORT_BYTES = 20 * 1024 * 1024

HEX = r"^[0-9a-f]{32}$"


class RepoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str | None = Field(default=None, max_length=300)  # None or "": unlink
    export_url: str | None = Field(default=None, max_length=500)  # pilote's export on GitHub Pages


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
            "repo": link["repo"], "export_url": link["export_url"], "pushed": link["export_url"] == PUSHED,
            "branch": link["branch"], "last_sync": link["last_sync"],
            "last_error": link["last_error"], "token": has_token,
            "chantiers": [f for f in fiches if f["status"] in OPEN_STATUSES],
            "closed": sum(1 for f in fiches if f["status"] not in OPEN_STATUSES),
        }

    @router.get("/code")
    def linked() -> list[dict[str, Any]]:
        """The linked repositories and when they were read (for « Récupérer le code »)."""
        return [
            {"project_id": r["project_id"], "repo": r["repo"], "export_url": r["export_url"], "last_sync": r["last_sync"],
             "last_error": r["last_error"]}
            for r in store.project_repos()
        ]

    @router.post("/code/export")
    async def receive_export(request: Request, repo: str = Query(min_length=3, max_length=300)) -> dict[str, Any]:
        """« pilote envoyer » (npm run pige): a repository sends its pilote journal.json. Token
        allowed (the same as Thunderbird's). Goes to every project linked to that repository."""
        try:
            name = normalize_repo(repo)
        except CodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        projects = store.projects_for_repo(name)
        if not projects:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Aucun projet P.IGE n'est relié à {name} : sur la page du projet, « Relier un dépôt de code ».",
            )
        raw = await request.body()
        if len(raw) > MAX_EXPORT_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Export trop volumineux.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ce n'est pas un export pilote (JSON illisible).") from exc
        out = []
        for project_id in projects:
            try:
                result = journal.receive(project_id, data)
            except CodeError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            out.append({"project": store.get_project(project_id).name, **result})
        return {"repo": name, "projects": out}

    @router.post("/code/sync")
    def sync_all(_sid: str = Depends(require_session)) -> dict[str, Any]:
        return journal.sync_all()

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
            export = normalize_export(body.export_url) if body.export_url and body.export_url.strip() else None
        except CodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        store.set_project_repo(project_id, repo, export)
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
