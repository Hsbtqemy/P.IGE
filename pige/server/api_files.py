"""Files kept by P.IGE, stored under ``<data>/files/`` and served only to a signed-in user:
images uploaded from the web app (pasted in a long text, attached to a paragraph), and the
attachments of mails filed from Thunderbird when asked (any kind, always downloaded, never
shown in the page).

The browser shrinks photos before sending (about 2000 px), so a file stays small; the server
checks what it receives is really an image of an accepted kind (never SVG: it could carry
script), and serves it with its own type, ``nosniff`` and no sharing.
"""

from __future__ import annotations

import os
import re
import struct
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from pige.model import ModelStore
from pige.model.store import NotFoundError, _new_id

MAX_BYTES = 8 * 1024 * 1024
ACCEPTED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
# Attachments keep their declared type when it is a plain document kind; anything else
# (HTML, SVG, scripts…) is stored and served as bytes to download.
DOCUMENT_TYPES = {
    "application/pdf", "application/zip", "text/plain", "text/csv", "application/msword", "application/rtf",
    "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "audio/mpeg", "audio/mp4", "video/mp4", *ACCEPTED,
}


def document_type(declared: str) -> str:
    kind = declared.split(";")[0].strip().lower()
    return kind if kind in DOCUMENT_TYPES else "application/octet-stream"


def safe_name(name: str) -> str:
    """A file name to offer for download (no path, no control characters)."""
    base = re.sub(r"[\x00-\x1f/\\]+", " ", name).strip().strip(".") or "fichier"
    return base[:200]


def sniff(head: bytes) -> str | None:
    """The image type from its first bytes (what it is, not what it claims to be)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def dimensions(data: bytes, mime: str) -> tuple[int | None, int | None]:
    """Width and height for PNG and GIF (cheap); the browser sends them for the others."""
    try:
        if mime == "image/png" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if mime == "image/gif" and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h)
    except struct.error:
        pass
    return None, None


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, file_id: str, mime: str) -> Path:
        return self.root / file_id[:2] / f"{file_id}.{ACCEPTED.get(mime, 'bin')}"

    def write(self, file_id: str, mime: str, data: bytes) -> None:
        target = self.path(file_id, mime)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)

    def remove(self, file_id: str) -> None:
        for ext in [*ACCEPTED.values(), "bin"]:
            (self.root / file_id[:2] / f"{file_id}.{ext}").unlink(missing_ok=True)

    def sweep(self, store: ModelStore) -> int:
        """Forget files never attached for two days, and remove from disk what no row knows
        (an entry deleted takes its files' rows with it)."""
        for fid in store.drop_loose_files(datetime.now(timezone.utc) - timedelta(days=2)):
            self.remove(fid)
        known = store.file_ids()
        removed = 0
        if self.root.is_dir():
            for path in self.root.glob("*/*.*"):
                if path.stem not in known:
                    path.unlink(missing_ok=True)
                    removed += 1
        return removed


def build_files_router(store: ModelStore, files: FileStore, require_auth: Callable[..., str]) -> APIRouter:
    def require_v2(request: Request, auth: str = Depends(require_auth)) -> str:
        if auth == "token" and request.method == "DELETE":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Deleting needs the signed-in web app")
        return auth

    router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_v2)])

    def view(f: Any) -> dict[str, Any]:
        return {"id": f.id, "entry_id": f.entry_id, "task_mail_id": f.task_mail_id, "kind": f.kind, "name": f.name,
                "mime": f.mime, "size": f.size, "width": f.width, "height": f.height,
                "url": f"/api/v2/files/{f.id}"}

    @router.post("/files", status_code=status.HTTP_201_CREATED)
    async def upload(
        request: Request,
        name: str = Query(default="", max_length=200),
        entry_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        width: int | None = Query(default=None, ge=1, le=20000),
        height: int | None = Query(default=None, ge=1, le=20000),
        attachment: bool = False,
        task_mail_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
    ) -> dict[str, Any]:
        """The file is the request's body (no form encoding). ``attachment``: a mail's
        attachment, of any kind, held by its filed mail (``entry_id``) or follow-up mail."""
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_BYTES:
            raise HTTPException(413, "Image trop lourde (8 Mo au plus)")
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "Image trop lourde (8 Mo au plus)")
        if attachment:
            if entry_id is None and task_mail_id is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Une pièce jointe appartient à un mail")
            same = store.same_attachment(entry_id=entry_id, task_mail_id=task_mail_id, name=name, size=len(data))
            if same is not None:
                return view(same)
            mime = sniff(bytes(data[:16])) or document_type(request.headers.get("content-type", ""))
            w = h = None
        else:
            sniffed = sniff(bytes(data[:16]))
            if sniffed is None:
                raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Seules les images JPEG, PNG, WebP et GIF")
            mime = sniffed
            w, h = dimensions(bytes(data[:32]), mime)
            w, h = w or width, h or height
        file_id = _new_id()
        files.write(file_id, mime if not attachment else "bin", bytes(data))
        try:
            stored = store.add_file(file_id, mime=mime, size=len(data), name=name, width=w, height=h,
                                    entry_id=entry_id, kind="attachment" if attachment else "image",
                                    task_mail_id=task_mail_id)
        except NotFoundError:
            files.remove(file_id)
            raise
        return view(stored)

    @router.get("/files/{file_id}")
    def download(file_id: str) -> FileResponse:
        if not (len(file_id) == 32 and all(c in "0123456789abcdef" for c in file_id)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        f = store.get_file(file_id)
        path = files.path(f.id, f.mime if f.kind == "image" else "bin")
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier absent du serveur")
        if f.kind == "attachment":
            quoted = urllib.parse.quote(safe_name(f.name))
            return FileResponse(path, media_type=document_type(f.mime), headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
                "Content-Security-Policy": "sandbox; default-src 'none'",
            })
        return FileResponse(path, media_type=f.mime, headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
        })

    @router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete(file_id: str) -> Response:
        f = store.get_file(file_id)
        store.delete_file(f.id)
        files.remove(f.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/attachments")
    def attachments(
        project_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        space_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        without_project: bool = False,
    ) -> list[dict[str, Any]]:
        """Every attachment kept from the mails of a project (or of a space without project)."""
        if project_id is None and space_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Un projet ou un espace")
        return [
            {"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"], "url": f"/api/v2/files/{r['id']}",
             "day": r["mail_day"], "author": (r["mail_author"] or "").strip(),
             "conversation_id": r["conversation_id"], "subject": r["conversation_subject"]}
            for r in store.mail_attachments(project_id=project_id, space_id=space_id, without_project=without_project)
        ]

    @router.get("/files")
    def list_files(
        entry_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        task_mail_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
    ) -> list[dict[str, Any]]:
        if entry_id:
            return [view(f) for f in store.files_for([entry_id])[entry_id]]
        if task_mail_id:
            return [view(f) for f in store.files_for_mails([task_mail_id])[task_mail_id]]
        return []

    return router
