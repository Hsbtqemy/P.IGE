"""FastAPI application: JSON API under /api, compiled web interface at /."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Scope

from pige.core.exceptions import ProjectNotFoundError, TaskNotFoundError
from pige.core.models import Task
from pige.core.service import INBOX_TAG, PigeService
from pige.core.storage import Storage
from pige.model import DB_FILE_NAME, ConflictError, ModelStore, NotFoundError
from pige.server.api_model import build_router
from pige.server.auth import LoginThrottle, SessionSigner, verify_api_token, verify_password
from pige.server.config import Settings

SESSION_COOKIE = "pige_session"
# Browsers cannot set custom headers on cross-site form posts, so requiring this
# header on cookie-authenticated writes blocks CSRF on top of SameSite=Strict.
CSRF_HEADER = "x-pige-client"


# ---------------------------------------------------------------- schemas


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=500)
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    note: str | None = Field(default=None, max_length=20_000)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    mail_message_id: str | None = Field(default=None, max_length=998)


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: Literal["open", "in_progress", "done"] | None = None
    note: str | None = Field(default=None, max_length=20_000)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- helpers


def _task_out(task: Task, project_names: dict[str, str]) -> dict[str, object]:
    data = asdict(task)
    data["project_name"] = project_names.get(task.project_id, "")
    return data


class _AppStaticFiles(StaticFiles):
    """Static web build; unknown page paths (/journal/2026-10-15…) get the app shell.

    The interface routes are resolved in the browser, so any GET for a path without
    a file extension that is not a real file answers with ``200.html`` (the SvelteKit
    fallback page). Missing assets (with an extension) stay 404.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            fallback = Path(str(self.directory)) / "200.html"
            last = path.rsplit("/", 1)[-1]
            is_page = "." not in last and not path.startswith(("_app/", "api"))
            if exc.status_code == 404 and is_page and fallback.is_file():
                return FileResponse(fallback, media_type="text/html")
            raise


class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path in ("/", "/index.html", "/200.html", "/service-worker.js", "/manifest.webmanifest") or (
            "." not in path.rsplit("/", 1)[-1]
        ):
            # Always revalidate the entry points so a new version is picked up.
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    settings: Settings, service: PigeService | None = None, model_store: ModelStore | None = None
) -> FastAPI:
    if service is None:
        service = PigeService(Storage(settings.data_dir))
        service.init_storage()
    if model_store is None:
        # New model (/api/v2). The server's data never sits in a synced folder: WAL is fine.
        model_store = ModelStore(settings.data_dir / DB_FILE_NAME, wal=True)
    signer = SessionSigner(
        settings.session_secret,
        settings.session_days * 86400,
        bound_to=settings.password_hash,
        not_before=settings.sessions_not_before,
    )
    throttle = LoginThrottle()
    # scrypt uses ~32 MiB per check: cap concurrent password checks.
    password_checks = threading.BoundedSemaphore(2)
    # The service writes whole JSON files; one writer at a time.
    lock = threading.Lock()

    app = FastAPI(title="P.IGE", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_SecurityHeaders)

    # ------------------------------------------------------------ auth

    def require_auth(request: Request) -> str:
        """Return the auth method ('token' or 'session') or reject the request."""
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            if verify_api_token(header[7:].strip(), settings.api_token_hashes):
                return "token"
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
        if signer.is_valid(request.cookies.get(SESSION_COOKIE)):
            if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "web":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing client header")
            return "session"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    @app.exception_handler(TaskNotFoundError)
    @app.exception_handler(ProjectNotFoundError)
    async def _not_found(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc).splitlines()[0]}, status_code=404)

    @app.exception_handler(NotFoundError)
    async def _model_not_found(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc).splitlines()[0]}, status_code=404)

    @app.exception_handler(ConflictError)
    async def _conflict(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc).splitlines()[0]}, status_code=409)

    @app.exception_handler(UnicodeError)
    async def _bad_text(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Invalid characters in the request"}, status_code=400)

    @app.exception_handler(sqlite3.OperationalError)
    async def _busy(_request: Request, exc: Exception) -> JSONResponse:
        # Typically "database is locked" after the busy timeout: safe to retry.
        return JSONResponse({"detail": "Busy, please try again"}, status_code=503)

    @app.exception_handler(OverflowError)
    async def _out_of_range(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Value out of range"}, status_code=400)

    @app.exception_handler(ValueError)
    async def _bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc).splitlines()[0]}, status_code=400)

    # ------------------------------------------------------------ routes

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, bool]:
        client = request.client.host if request.client else "unknown"
        if not throttle.acquire(client):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try later")
        with password_checks:
            ok = verify_password(body.password, settings.password_hash)
        if not ok:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
        throttle.succeeded(client)
        response.set_cookie(
            SESSION_COOKIE,
            signer.issue(),
            max_age=signer.max_age_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
        )
        return {"authenticated": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        if request.headers.get(CSRF_HEADER) != "web":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing client header")
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"authenticated": False}

    @app.get("/api/session")
    def session(request: Request) -> dict[str, bool]:
        return {"authenticated": signer.is_valid(request.cookies.get(SESSION_COOKIE))}

    @app.get("/api/projects")
    def projects(_auth: str = Depends(require_auth)) -> list[dict[str, object]]:
        with lock:
            items = service.list_projects("active")
        return [
            {"id": p.id, "name": p.name, "parent_id": p.parent_id, "inbox": INBOX_TAG in p.tags}
            for p in items
        ]

    @app.get("/api/tasks")
    def tasks(
        status_filter: Literal["open", "in_progress", "done", "all"] = Query("open", alias="status"),
        _auth: str = Depends(require_auth),
    ) -> list[dict[str, object]]:
        with lock:
            items = service.list_all_tasks(status_filter)
            names = {p.id: p.name for p in service.list_projects("all")}
        return [_task_out(t, names) for t in items]

    @app.post("/api/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(body: TaskIn, _auth: str = Depends(require_auth)) -> dict[str, object]:
        with lock:
            project_id = body.project_id or service.ensure_inbox_project().id
            task = service.create_task(
                project_id,
                body.title,
                [],
                body.note,
                None,
                body.due_date,
                task_id=body.id,
                mail_message_id=body.mail_message_id,
            )
            names = {p.id: p.name for p in service.list_projects("all")}
        return _task_out(task, names)

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: str, body: TaskPatch, _auth: str = Depends(require_auth)) -> dict[str, object]:
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
        with lock:
            task = service.update_task(task_id, patch)
            names = {p.id: p.name for p in service.list_projects("all")}
        return _task_out(task, names)

    app.include_router(build_router(model_store, require_auth, settings.timezone))

    @app.api_route("/api", methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
    @app.api_route("/api/{path:path}", methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"])
    def api_not_found(path: str = "") -> None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown API route")

    if settings.web_dir is not None:
        web_dir = Path(settings.web_dir)
        if not (web_dir / "index.html").is_file():
            raise RuntimeError(f"Web interface not built: {web_dir / 'index.html'} missing")
        app.mount("/", _AppStaticFiles(directory=web_dir, html=True), name="web")

    return app
