"""Images kept by P.IGE: uploaded from the web app (pasted in a long text, attached to a
paragraph), stored under ``<data>/files/`` and served only to a signed-in user.

The browser shrinks photos before sending (about 2000 px), so a file stays small; the server
checks what it receives is really an image of an accepted kind (never SVG: it could carry
script), and serves it with its own type, ``nosniff`` and no sharing.
"""

from __future__ import annotations

import os
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from pige.model import ModelStore
from pige.model.store import NotFoundError, _new_id

MAX_BYTES = 8 * 1024 * 1024
ACCEPTED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


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
        for mime in ACCEPTED:
            self.path(file_id, mime).unlink(missing_ok=True)

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
        return {"id": f.id, "entry_id": f.entry_id, "name": f.name, "mime": f.mime, "size": f.size,
                "width": f.width, "height": f.height, "url": f"/api/v2/files/{f.id}"}

    @router.post("/files", status_code=status.HTTP_201_CREATED)
    async def upload(
        request: Request,
        name: str = Query(default="", max_length=200),
        entry_id: str | None = Query(default=None, pattern=r"^[0-9a-f]{32}$"),
        width: int | None = Query(default=None, ge=1, le=20000),
        height: int | None = Query(default=None, ge=1, le=20000),
    ) -> dict[str, Any]:
        """The image is the request's body (no form encoding)."""
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_BYTES:
            raise HTTPException(413, "Image trop lourde (8 Mo au plus)")
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "Image trop lourde (8 Mo au plus)")
        mime = sniff(bytes(data[:16]))
        if mime is None:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Seules les images JPEG, PNG, WebP et GIF")
        w, h = dimensions(bytes(data[:32]), mime)
        file_id = _new_id()
        files.write(file_id, mime, bytes(data))
        try:
            stored = store.add_file(file_id, mime=mime, size=len(data), name=name, width=w or width,
                                    height=h or height, entry_id=entry_id)
        except NotFoundError:
            files.remove(file_id)
            raise
        return view(stored)

    @router.get("/files/{file_id}")
    def download(file_id: str) -> FileResponse:
        if not (len(file_id) == 32 and all(c in "0123456789abcdef" for c in file_id)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        f = store.get_file(file_id)
        path = files.path(f.id, f.mime)
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier absent du serveur")
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

    return router
